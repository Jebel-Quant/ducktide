"""Domain models and the table schema derived from them.

A ducktide table is described by one Pydantic model. Its fields *are* the
columns: names, order and SQL types are all derived from the model, so there is
no second class and no hand-written schema to keep in step with it.

Examples:
    >>> from ducktide.model import DomainModel, column_definitions
    >>> class Sensor(DomainModel):
    ...     id: int
    ...     name: str
    ...     site: str | None = None
    >>> column_definitions(Sensor, primary_key="id")
    {'id': 'BIGINT PRIMARY KEY', 'name': 'VARCHAR NOT NULL', 'site': 'VARCHAR'}

    Anything the type mapping cannot express is overridden per column:

    >>> column_definitions(Sensor, primary_key="id", sql_types={"name": "VARCHAR NOT NULL UNIQUE"})
    {'id': 'BIGINT PRIMARY KEY', 'name': 'VARCHAR NOT NULL UNIQUE', 'site': 'VARCHAR'}
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .exceptions import ValidationError

# Exact-type lookup, so ``bool`` never falls through to ``int`` and
# ``datetime`` never to ``date``.
_SQL_TYPES: dict[type, str] = {
    bool: "BOOLEAN",
    int: "BIGINT",
    float: "DOUBLE",
    str: "VARCHAR",
    bytes: "BLOB",
    Decimal: "DECIMAL",
    date: "DATE",
    datetime: "TIMESTAMP",
    time: "TIME",
    timedelta: "INTERVAL",
    UUID: "UUID",
}


class DomainModel(BaseModel):
    """Optional base for domain models: immutable, whitespace-stripped.

    Any Pydantic model can back a table; this base only fixes the configuration
    ducktide recommends — frozen values, so a row read back is never mutated in
    place behind the table's back.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Split ``X | None`` into ``(X, True)``; anything else is ``(annotation, False)``.

    Args:
        annotation: A field annotation.

    Returns:
        The inner annotation and whether ``None`` was allowed.
    """
    if get_origin(annotation) in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1 and len(args) < len(get_args(annotation)):
            return args[0], True
    return annotation, False


def _sql_type(model: type[BaseModel], field: str, annotation: Any) -> tuple[str, bool]:
    """Map a field annotation to a DuckDB type and its nullability.

    Args:
        model: The model the field belongs to (for the error message).
        field: The field name (for the error message).
        annotation: The field's annotation.

    Returns:
        The DuckDB type name and whether the column is nullable.

    Raises:
        ValidationError: If the annotation has no DuckDB mapping.
    """
    inner, nullable = _unwrap_optional(annotation)
    try:
        return _SQL_TYPES[inner], nullable
    except (KeyError, TypeError):
        raise ValidationError(  # noqa: TRY003
            f"{model.__name__}.{field}: no DuckDB type for {annotation!r}; pass sql_types={{{field!r}: '...'}}"
        ) from None


def column_definitions(
    model: type[BaseModel],
    *,
    primary_key: str = "id",
    sql_types: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Derive ``{column: SQL definition}`` from a model's fields, in field order.

    Non-optional fields become ``NOT NULL``; ``X | None`` fields are nullable.
    The primary-key column gets ``PRIMARY KEY`` (which implies ``NOT NULL``).
    An entry in ``sql_types`` replaces the derived definition for that column
    wholesale, constraints included.

    Args:
        model: The Pydantic model describing the table.
        primary_key: The field holding the primary key.
        sql_types: Per-column definitions that override the derived ones.

    Returns:
        The column definitions, keyed by field name in declaration order.

    Raises:
        ValidationError: If ``primary_key`` or a ``sql_types`` key is not a field
            of the model, or a field's type has no DuckDB mapping and no override.
    """
    fields = model.model_fields
    overrides = dict(sql_types or {})
    unknown = sorted({primary_key, *overrides} - fields.keys())
    if unknown:
        raise ValidationError(f"{model.__name__} has no field(s) {', '.join(unknown)}")  # noqa: TRY003

    definitions: dict[str, str] = {}
    for name, info in fields.items():
        if name in overrides:
            definitions[name] = overrides[name]
            continue
        sql_type, nullable = _sql_type(model, name, info.annotation)
        if name == primary_key:
            definitions[name] = f"{sql_type} PRIMARY KEY"
        else:
            definitions[name] = sql_type if nullable else f"{sql_type} NOT NULL"
    return definitions

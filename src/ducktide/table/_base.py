"""Base state and shared helpers for the :class:`~ducktide.table.Table`.

This module defines :class:`TableBase`, which owns the connection, the bound
model and the cached table metadata (name, columns, primary key) shared
by every table mixin. It also provides the small helpers used across the
query, write and import/export mixins.
"""

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any, Self

import duckdb
from pydantic import BaseModel

from ..exceptions import DataError
from ..model import column_definitions
from ..utils import sql


class TableBase:
    """Shared state and helpers for the table mixins.

    Holds the active connection and the metadata derived from the bound model.
    The concrete :class:`~ducktide.table.Table` composes this base with the
    query, write and import/export mixins.

    Attributes:
        connection: Active DuckDB connection used to execute queries.
        model: The Pydantic model each row is read back as.
        table_name: The database table name.
        columns: The table's columns — the model's fields, in declaration order.
        pk: The primary-key column name.
    """

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        model: type[BaseModel],
        *,
        name: str | None = None,
        primary_key: str = "id",
        sql_types: Mapping[str, str] | None = None,
        read_only: bool = False,
    ) -> None:
        """Bind a table to a model and create it unless read-only.

        Args:
            connection: Active DuckDB connection used to execute queries.
            model: The Pydantic model describing the table; its fields are the columns.
            name: The table name. Defaults to the model's class name, lower-cased.
            primary_key: The field holding the primary key.
            sql_types: Per-column SQL definitions overriding the derived ones
                (see :func:`ducktide.model.column_definitions`).
            read_only: If True, skip creating the table.
        """
        definitions = column_definitions(model, primary_key=primary_key, sql_types=sql_types)
        self.connection = connection
        self.model = model
        self.table_name = sql.validate_identifier(name or model.__name__.lower(), "table name")
        self.columns = tuple(definitions)
        self.pk = primary_key

        if not read_only:
            self.connection.execute(sql.create_table_if_not_exists(self.table_name, definitions))

    @classmethod
    def of(cls, model: type[BaseModel], **options: Any) -> Callable[..., Self]:
        """Return a factory binding ``model``, for :class:`~ducktide.db.DB`'s ``tables_map``.

        ``DB`` calls each factory with ``(connection, read_only=...)``; this
        fills in the model and any table options up front.

        Args:
            model: The Pydantic model describing the table.
            **options: ``name``, ``primary_key`` or ``sql_types``, as for the constructor.

        Returns:
            A callable building the table from a connection.
        """
        return partial(cls, model=model, **options)

    def _to_models(self, cursor: duckdb.DuckDBPyConnection) -> list[Any]:
        """Read a cursor's rows back as model instances, matching values to fields by column name.

        Names come from the cursor's own description, so the result does not
        depend on the table's physical column order.

        Args:
            cursor: A cursor holding the result of a query.

        Returns:
            One validated model instance per row.
        """
        names = [column[0] for column in cursor.description or ()]
        return [self.model.model_validate(dict(zip(names, row, strict=True))) for row in cursor.fetchall()]

    def execute(self, query: str, params: Sequence[Any] | None = None) -> list[Any]:
        """Execute a SQL query and read its rows back as model instances.

        Args:
            query: SQL query string with optional placeholders.
            params: Parameter values for the query placeholders.

        Returns:
            List of model instances created from the query results.
        """
        return self._to_models(self.connection.execute(query, params))

    def _get_single_result(self, results: list[Any], identifier: str, value: Any) -> Any:
        """Return a single result from a list, raising KeyError if not found.

        Args:
            results: List of query results.
            identifier: Name of the identifier field (for error message).
            value: Value of the identifier (for error message).

        Returns:
            The first (and expected only) result from the list.

        Raises:
            KeyError: If the results list is empty.
        """
        if not results:
            raise KeyError(f"No row found for {identifier} = {value}")  # noqa: TRY003
        return results[0]

    def _values_from_obj(self, obj: Any) -> tuple[Any, ...]:
        """Extract column values from an object as a tuple.

        Args:
            obj: A model instance with attributes matching the table columns.

        Returns:
            A tuple of values in column order.

        Raises:
            DataError: If the object is missing a required column attribute.
        """
        # Any object carrying every column as an attribute can be written.
        try:
            return tuple(getattr(obj, col) for col in self.columns)
        except AttributeError as exc:
            raise DataError(f"Object {type(obj).__name__} is missing required column: {exc}") from exc  # noqa: TRY003

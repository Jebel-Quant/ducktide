"""Tests for ducktide.model: DomainModel and the schema derived from a model."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import pydantic
import pytest
from pydantic import BaseModel

from ducktide.exceptions import ValidationError
from ducktide.model import DomainModel, column_definitions


class AllTypes(BaseModel):
    """One field per mapped Python type."""

    id: int
    flag: bool
    ratio: float
    label: str
    payload: bytes
    amount: Decimal
    day: date
    at: datetime
    clock: time
    span: timedelta
    uid: UUID


def test_every_mapped_type_has_its_duckdb_type() -> None:
    """Each supported annotation maps to its DuckDB type; required fields are NOT NULL."""
    assert column_definitions(AllTypes) == {
        "id": "BIGINT PRIMARY KEY",
        "flag": "BOOLEAN NOT NULL",
        "ratio": "DOUBLE NOT NULL",
        "label": "VARCHAR NOT NULL",
        "payload": "BLOB NOT NULL",
        "amount": "DECIMAL NOT NULL",
        "day": "DATE NOT NULL",
        "at": "TIMESTAMP NOT NULL",
        "clock": "TIME NOT NULL",
        "span": "INTERVAL NOT NULL",
        "uid": "UUID NOT NULL",
    }


def test_optional_fields_are_nullable_in_both_spellings() -> None:
    """``X | None`` and ``Optional[X]`` both drop NOT NULL."""

    class Nullable(BaseModel):
        """Nullable fields in both spellings."""

        id: int
        a: str | None = None
        b: Optional[int] = None  # noqa: UP045 - the typing.Optional spelling is the case under test

    assert column_definitions(Nullable) == {"id": "BIGINT PRIMARY KEY", "a": "VARCHAR", "b": "BIGINT"}


def test_primary_key_can_be_any_field() -> None:
    """``primary_key`` moves the PRIMARY KEY constraint to the named field."""

    class Keyed(BaseModel):
        """Keyed by a non-``id`` field."""

        code: str
        value: float

    assert column_definitions(Keyed, primary_key="code") == {
        "code": "VARCHAR PRIMARY KEY",
        "value": "DOUBLE NOT NULL",
    }


def test_sql_types_override_the_derived_definition_wholesale() -> None:
    """An override replaces the whole definition, including a type the mapping lacks."""

    class Tagged(BaseModel):
        """Holds a field type with no DuckDB mapping."""

        id: int
        tags: list[str]

    assert column_definitions(Tagged, sql_types={"tags": "VARCHAR[]"}) == {
        "id": "BIGINT PRIMARY KEY",
        "tags": "VARCHAR[]",
    }


def test_unmapped_type_without_override_is_rejected() -> None:
    """A field type with no DuckDB mapping names the field and the fix."""

    class Tagged(BaseModel):
        """Holds a field type with no DuckDB mapping."""

        id: int
        tags: list[str]

    with pytest.raises(ValidationError, match=r"Tagged\.tags: no DuckDB type .*sql_types"):
        column_definitions(Tagged)


def test_non_optional_union_is_rejected() -> None:
    """A union of two real types is not guessed at."""

    class Either(BaseModel):
        """Holds a non-optional union."""

        id: int
        value: int | str

    with pytest.raises(ValidationError, match=r"Either\.value"):
        column_definitions(Either)


def test_unknown_primary_key_or_override_is_rejected() -> None:
    """Naming a field the model does not have is an error, not a silent no-op."""

    class Plain(BaseModel):
        """A single-field model."""

        id: int

    with pytest.raises(ValidationError, match="has no field"):
        column_definitions(Plain, primary_key="missing")
    with pytest.raises(ValidationError, match="has no field"):
        column_definitions(Plain, sql_types={"missing": "INTEGER"})


def test_domain_model_is_frozen_and_strips_whitespace() -> None:
    """DomainModel instances are immutable and trim string input."""

    class Named(DomainModel):
        """A frozen model with a string field."""

        name: str

    named = Named(name="  north  ")
    assert named.name == "north"
    with pytest.raises(pydantic.ValidationError):
        named.name = "south"

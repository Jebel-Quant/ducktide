"""Shared fixtures and helpers for the jqr.database.table test package.

Security note: S101 (assert statements) are intentional in test code — pytest
relies on assert for test assertions and they are never executed in production.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import duckdb
import pytest

from jqr.database.orm.base import ORMModel
from jqr.database.table import Table


class MockModel(ORMModel):
    """A minimal mock model for testing Table."""

    _table_name: ClassVar[str] = "mock_table"
    _columns: ClassVar[list[str]] = ["id", "name", "expiry"]
    _schema: ClassVar[dict[str, str]] = {
        "id": "INTEGER PRIMARY KEY",
        "name": "TEXT",
        "expiry": "DATE",
    }

    def __init__(self, id: int, name: str, expiry: date | str | None = None):
        """Initialize a MockModel instance."""
        self.id = id
        self.name = name
        self.expiry = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry

    @classmethod
    def from_row(cls, row: tuple):
        """Create a MockModel from a database row."""
        return cls(*row)

    def to_dict(self):
        """Convert the MockModel to a dictionary."""
        return {"id": self.id, "name": self.name, "expiry": self.expiry}

    def _to_dict(self) -> dict[str, Any]:
        """Return the model as a dict (mock)."""
        return self.to_dict()

    @classmethod
    def _from_row(cls, row: tuple[Any, ...]) -> MockModel:
        """Build a model instance from a database row (mock)."""
        return cls.from_row(row)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> MockModel:
        """Build a model instance from a dict (mock)."""
        return cls(id=data["id"], name=data["name"], expiry=data.get("expiry"))


@pytest.fixture
def connection():
    """Provide a fresh in-memory DuckDB connection."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE mock_table (id INTEGER PRIMARY KEY, name TEXT, expiry DATE)")
    yield con
    con.close()


@pytest.fixture
def table(connection):
    """Provide a Table instance for MockModel."""
    return Table(
        connection=connection,
        model_class=MockModel,
    )

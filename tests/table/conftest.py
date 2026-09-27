"""Shared fixtures and helpers for the ducktide.table test package.

Security note: S101 (assert statements) are intentional in test code — pytest
relies on assert for test assertions and they are never executed in production.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest
from pydantic import BaseModel

from ducktide.table import Table


class MockModel(BaseModel):
    """A minimal model for testing Table; ``name`` and ``expiry`` are nullable columns."""

    id: int
    name: str | None = None
    expiry: date | None = None


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
    return Table(connection, MockModel, name="mock_table")

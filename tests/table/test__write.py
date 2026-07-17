"""Tests for the WriteMixin class in jqr.database.table._write."""

from __future__ import annotations

from datetime import date

from .conftest import MockModel


class TestWriteMixin:
    """Test Table insertion methods."""

    def test_insert_empty(self, table):
        """Test insert with no objects (should do nothing)."""
        table.insert()
        assert len(table) == 0

    def test_insert_single(self, table):
        """Test inserting a single object."""
        obj = MockModel(1, "test", date(2025, 1, 1))
        table.insert(obj)
        assert len(table) == 1
        retrieved = table.get(1)
        assert retrieved.name == "test"

    def test_insert_multiple(self, table):
        """Test inserting multiple objects (delegates to bulk_insert)."""
        objs = [MockModel(1, "a"), MockModel(2, "b")]
        table.insert(*objs)
        assert len(table) == 2

    def test_bulk_insert_empty(self, table):
        """Test bulk_insert with an empty iterable."""
        table.bulk_insert([])
        assert len(table) == 0

"""Tests for the TableBase class in ducktide.table._base."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ducktide.exceptions import DataError

from .conftest import MockModel


class TestTableBase:
    """Test Table initialization and base-level helpers."""

    def test_mock_model_internal_methods(self):
        """Test internal methods of MockModel to ensure 100% coverage."""
        obj = MockModel(1, "test", date(2025, 1, 1))

        # Test to_dict and _to_dict
        expected_dict = {"id": 1, "name": "test", "expiry": date(2025, 1, 1)}
        assert obj.to_dict() == expected_dict
        assert obj._to_dict() == expected_dict

        # Test _from_row
        obj2 = MockModel._from_row((2, "other", date(2025, 2, 2)))
        assert obj2.id == 2
        assert obj2.name == "other"
        assert obj2.expiry == date(2025, 2, 2)

        # Test _from_dict
        obj3 = MockModel._from_dict({"id": 3, "name": "third", "expiry": "2025-03-03"})
        assert obj3.id == 3
        assert obj3.name == "third"
        assert obj3.expiry == date(2025, 3, 3)

    def test_init(self, connection):
        """Test Table initialization."""
        from ducktide.table import Table

        table = Table(connection, MockModel)
        assert table.pk == "id"

    def test_init_read_only_skips_schema_creation(self):
        """A read-only Table must not issue CREATE TABLE against the connection."""
        from ducktide.table import Table

        con = duckdb.connect(":memory:")
        try:
            table = Table(con, MockModel, read_only=True)
            assert not table.exists
        finally:
            con.close()

    def test_values_from_obj_wrong_type(self, table):
        """Test _values_from_obj with an object of the wrong type."""
        with pytest.raises(DataError, match="is missing required column"):
            table._values_from_obj("not a model")

    def test_execute(self, table):
        """Test executing a raw SQL query and returning model instances."""
        table.insert(MockModel(1, "test"))
        results = table.execute("SELECT * FROM mock_table WHERE name = ?", ["test"])
        assert len(results) == 1
        assert results[0].name == "test"

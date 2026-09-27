"""Tests for the TableBase class in ducktide.table._base."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from ducktide.exceptions import DataError

from .conftest import MockModel


class TestTableBase:
    """Test Table initialization and base-level helpers."""

    def test_init(self, connection):
        """Test Table initialization."""
        from ducktide.table import Table

        table = Table(connection, MockModel, name="mock_table")
        assert table.pk == "id"
        assert table.columns == ("id", "name", "expiry")

    def test_default_table_name_is_lowercased_model_name(self, connection):
        """Without ``name``, the table is named after the model and created."""
        from ducktide.table import Table

        table = Table(connection, MockModel)
        assert table.table_name == "mockmodel"
        assert table.exists

    def test_invalid_table_name_rejected(self, connection):
        """A table name that is not a SQL identifier never reaches SQL."""
        from ducktide.exceptions import ValidationError
        from ducktide.table import Table

        with pytest.raises(ValidationError, match="Invalid table name"):
            Table(connection, MockModel, name="mock; DROP TABLE x")

    def test_of_returns_factory_binding_model_and_options(self, connection):
        """``Table.of`` defers construction until DB supplies the connection."""
        from ducktide.table import Table

        factory = Table.of(MockModel, name="mock_table")
        table = factory(connection, read_only=True)
        assert isinstance(table, Table)
        assert table.model is MockModel
        assert table.table_name == "mock_table"

    def test_reads_map_values_by_column_name(self, connection):
        """Rows are matched to fields by name, not by the table's physical column order."""
        from ducktide.table import Table

        connection.execute("CREATE TABLE shuffled AS SELECT 'n' AS name, DATE '2025-01-01' AS expiry, 7 AS id")
        table = Table(connection, MockModel, name="shuffled", read_only=True)
        assert table.select() == [MockModel(id=7, name="n", expiry=date(2025, 1, 1))]

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
        table.insert(MockModel(id=1, name="test"))
        results = table.execute("SELECT * FROM mock_table WHERE name = ?", ["test"])
        assert len(results) == 1
        assert results[0].name == "test"

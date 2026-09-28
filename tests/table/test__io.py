"""Tests for the IOMixin class in ducktide.table._io."""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import duckdb
import polars as pl
import pytest
from pydantic import BaseModel

from ducktide.table import Table

from .conftest import MockModel


class TestExportCreatesFolders:
    """Exports create a missing parent folder instead of failing inside DuckDB."""

    def test_to_csv_and_to_parquet_create_nested_folders(self, table, tmp_path):
        """to_csv and to_parquet write into folders that do not exist yet."""
        table.insert(MockModel(id=1, name="a"))
        csv_path = tmp_path / "missing" / "deeper" / "rows.csv"
        parquet_path = tmp_path / "also" / "missing" / "rows.parquet"
        table.to_csv(csv_path)
        table.to_parquet(parquet_path)
        assert csv_path.exists()
        assert parquet_path.exists()


class MockModelWithDateColumns(BaseModel):
    """A model with an explicit ``date_columns`` attribute, for testing _get_date_columns()."""

    date_columns: ClassVar[list[str]] = ["created_at"]

    id: int
    name: str | None = None
    created_at: date | None = None


class TestIOMixin:
    """Test Table export and import methods."""

    def test_to_frame(self, table):
        """Test to_frame returns a Polars DataFrame."""
        table.insert(MockModel(id=1, name="test"))
        df = table.to_frame()
        assert isinstance(df, pl.DataFrame)
        assert len(df) == 1
        assert df["name"][0] == "test"

    def test_to_csv_no_overwrite(self, table, tmp_path):
        """Test to_csv with overwrite=False and an existing file."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("existing content")

        with pytest.raises(FileExistsError):
            table.to_csv(csv_path, overwrite=False)

    def test_to_parquet_no_overwrite(self, table, tmp_path):
        """Test to_parquet with overwrite=False and an existing file."""
        pq_path = tmp_path / "test.parquet"
        pq_path.write_text("existing content")

        with pytest.raises(FileExistsError):
            table.to_parquet(pq_path, overwrite=False)

    def test_from_csv_not_found(self, table):
        """Test from_csv with a non-existent file."""
        with pytest.raises(FileNotFoundError):
            table.from_csv("nonexistent.csv")

    def test_from_parquet_not_found(self, table):
        """Test from_parquet with a non-existent file."""
        with pytest.raises(FileNotFoundError):
            table.from_parquet("nonexistent.parquet")

    def test_csv_roundtrip_with_expiry(self, table, tmp_path):
        """Test CSV export and import with a DATE column (expiry)."""
        obj = MockModel(id=1, name="test", expiry=date(2025, 3, 20))
        table.insert(obj)

        csv_path = tmp_path / "roundtrip.csv"
        table.to_csv(csv_path)

        # Clear table and import back
        table.connection.execute("DELETE FROM mock_table")
        count = table.from_csv(csv_path)
        assert count == 1

        retrieved = table.get(1)
        # to_csv wrote expiry through the CAST(expiry AS VARCHAR) branch; the
        # model validates it back into a date on read.
        assert str(retrieved.expiry) == "2025-03-20"

    def test_parquet_roundtrip_with_expiry(self, table, tmp_path):
        """Test Parquet export and import with a DATE column (expiry)."""
        obj = MockModel(id=1, name="test", expiry=date(2025, 3, 20))
        table.insert(obj)

        pq_path = tmp_path / "roundtrip.parquet"
        table.to_parquet(pq_path)

        # Clear table and import back
        table.connection.execute("DELETE FROM mock_table")
        count = table.from_parquet(pq_path)
        assert count == 1

        retrieved = table.get(1)
        assert str(retrieved.expiry) == "2025-03-20"

    def test_get_date_columns_with_explicit_date_columns(self, tmp_path):
        """Test _get_date_columns returns model's date_columns when defined."""
        # Create connection and table with schema
        connection = duckdb.connect(":memory:")
        connection.execute(
            "CREATE TABLE mock_table_with_date_cols (id INTEGER PRIMARY KEY, name TEXT, created_at DATE)"
        )

        table = Table(connection, MockModelWithDateColumns, name="mock_table_with_date_cols")

        # Insert a record with a date
        obj = MockModelWithDateColumns(id=1, name="test", created_at=date(2025, 5, 15))
        table.insert(obj)

        # Export to CSV - this triggers _get_date_columns()
        csv_path = tmp_path / "explicit_date_cols.csv"
        table.to_csv(csv_path)

        # Verify the date was exported correctly
        connection.execute("DELETE FROM mock_table_with_date_cols")
        table.from_csv(csv_path)
        retrieved = table.get(1)
        assert str(retrieved.created_at) == "2025-05-15"

        connection.close()

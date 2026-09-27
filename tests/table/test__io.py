"""Tests for the IOMixin class in ducktide.table._io."""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import duckdb
import polars as pl
import pytest

from ducktide.orm.base import ORMModel
from ducktide.table import Table

from .conftest import MockModel


class MockModelWithDateColumns(ORMModel):
    """A mock model with explicit date_columns attribute for testing _get_date_columns()."""

    _table_name: ClassVar[str] = "mock_table_with_date_cols"
    _columns: ClassVar[list[str]] = ["id", "name", "created_at"]
    _schema: ClassVar[dict[str, str]] = {
        "id": "INTEGER PRIMARY KEY",
        "name": "TEXT",
        "created_at": "DATE",
    }
    date_columns: ClassVar[list[str]] = ["created_at"]

    def __init__(self, id: int, name: str, created_at: date | str | None = None):  # noqa: A002 - mirrors the DB primary-key column `id`
        """Initialize a MockModelWithDateColumns instance."""
        self.id = id
        self.name = name
        self.created_at = date.fromisoformat(created_at) if isinstance(created_at, str) else created_at

    @classmethod
    def from_row(cls, row: tuple):
        """Create a MockModelWithDateColumns from a database row."""
        return cls(*row)

    def to_dict(self):
        """Convert the MockModelWithDateColumns to a dictionary."""
        return {"id": self.id, "name": self.name, "created_at": self.created_at}

    def _to_dict(self) -> dict[str, Any]:
        """Return the model as a dict (mock)."""
        return self.to_dict()

    @classmethod
    def _from_row(cls, row: tuple[Any, ...]) -> MockModelWithDateColumns:
        """Build a model instance from a database row (mock)."""
        return cls.from_row(row)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> MockModelWithDateColumns:
        """Build a model instance from a dict (mock)."""
        return cls(id=data["id"], name=data["name"], created_at=data.get("created_at"))


class TestIOMixin:
    """Test Table export and import methods."""

    def test_to_frame(self, table):
        """Test to_frame returns a Polars DataFrame."""
        table.insert(MockModel(1, "test"))
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
        obj = MockModel(1, "test", date(2025, 3, 20))
        table.insert(obj)

        csv_path = tmp_path / "roundtrip.csv"
        table.to_csv(csv_path)

        # Clear table and import back
        table.connection.execute("DELETE FROM mock_table")
        count = table.from_csv(csv_path)
        assert count == 1

        retrieved = table.get(1)
        # Note: when reading from CSV, expiry might be a string depending on how MockModel.from_row is implemented
        # In our MockModel, it just takes whatever is in the row.
        # DuckDB's read_csv_auto might detect it as a date or string.
        # But we want to ensure to_csv used the CAST(expiry AS VARCHAR) branch.
        assert str(retrieved.expiry) == "2025-03-20"

    def test_parquet_roundtrip_with_expiry(self, table, tmp_path):
        """Test Parquet export and import with a DATE column (expiry)."""
        obj = MockModel(1, "test", date(2025, 3, 20))
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

        table = Table(connection=connection, model_class=MockModelWithDateColumns)

        # Insert a record with a date
        obj = MockModelWithDateColumns(1, "test", date(2025, 5, 15))
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

"""Tests for the TimeSeriesBase class in ducktide.time._base."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from ducktide.exceptions import ValidationError
from ducktide.time.timeseries_db import TimeSeriesDB


class TestTimeSeriesBase:
    """Tests for the base-level connection, querying, and identifier helpers."""

    def test_timeseries_db_query(self, ts_db):
        """TimeSeriesDB.query should execute SQL and return a DataFrame."""
        df = ts_db.query("SELECT 1 as a, 2 as b")
        assert isinstance(df, pl.DataFrame)
        assert df.to_dicts() == [{"a": 1, "b": 2}]

    def test_has_table_matches_tables_listing(self, ts_db, sample_frame):
        """has_table agrees with tables() for plain, schema-qualified, view and temp relations."""
        ts_db.ingest("plain", sample_frame)
        ts_db.ingest("market.futures", sample_frame)
        ts_db.con.execute("CREATE VIEW plain_view AS SELECT * FROM plain")
        ts_db.con.execute("CREATE TEMP TABLE scratch AS SELECT 1 AS x")

        for name in ("plain", "market.futures", "plain_view", "scratch"):
            assert name in ts_db.tables()
            assert ts_db.has_table(name)

        for name in ("missing", "market.plain", "other.futures", "futures"):
            assert name not in ts_db.tables()
            assert not ts_db.has_table(name)

    def test_timeseries_db_tables_and_has_table(self, ts_db, sample_frame):
        """TimeSeriesDB should list tables and check for existence."""
        assert ts_db.tables() == []
        assert not ts_db.has_table("test_table")

        ts_db.ingest("test_table", sample_frame)
        assert "test_table" in ts_db.tables()
        assert ts_db.has_table("test_table")

    def test_timeseries_db_quote_identifier(self, ts_db):
        """Test internal identifier quoting logic."""
        assert ts_db._quote_identifier("table") == '"table"'
        assert ts_db._quote_identifier("schema.table") == '"schema"."table"'
        # Test cleaning quotes
        assert ts_db._quote_identifier('"table"') == '"table"'
        assert ts_db._quote_identifier('"schema"."table"') == '"schema"."table"'

    def test_timeseries_db_rejects_invalid_table_names(self, ts_db, sample_frame):
        """Table names must be valid SQL identifiers (optionally schema-qualified)."""
        bad_names = [
            "bad-name",
            "1starts_with_digit",
            'quo"ted',
            "table; DROP TABLE prices; --",
            "a.b.c",
            "",
        ]
        for name in bad_names:
            with pytest.raises(ValidationError, match="Invalid table name"):
                ts_db.ingest(name, sample_frame)
            with pytest.raises(ValidationError, match="Invalid table name"):
                ts_db.get_timeseries_frame(name)

    def test_context_manager(self):
        """Test that TimeSeriesDB works as a context manager."""
        with TimeSeriesDB() as db:
            df = pl.DataFrame({"timestamp": [date(2025, 1, 1)], "value": [10]})
            db.ingest("test", df)
            result = db.get_timeseries_frame("test")
            assert result.height == 1
        # Connection should be closed after exiting context
        # Attempting to use the connection would raise an error

    def test_readonly_parameter_default_false(self, tmp_path):
        """Test that read_only defaults to False for backward compatibility."""
        db_path = tmp_path / "test_ts.duckdb"

        # Default should be read-write
        db = TimeSeriesDB(db_path)
        assert db.read_only is False

        # Should be able to write
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1)],
                "instrument_id": [100],
                "price": [10.5],
            }
        )
        db.ingest("prices", df)

        # Verify write succeeded
        result = db.get_timeseries_frame("prices")
        assert result.height == 1

        db.close()

    def test_readonly_with_nonexistent_file(self, tmp_path):
        """Test that opening a non-existent file in read-only mode raises an error."""
        db_path = tmp_path / "nonexistent.duckdb"

        # Attempting to open a non-existent file in read-only mode should fail
        with pytest.raises(Exception, match=r"does not exist|cannot open"):
            TimeSeriesDB(db_path, read_only=True)

    def test_multiple_readonly_connections(self, tmp_path, sample_frame):
        """Test that multiple processes can read from the same TimeSeriesDB file simultaneously."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Open multiple read-only connections simultaneously
        db_ro1 = TimeSeriesDB(db_path, read_only=True)
        db_ro2 = TimeSeriesDB(db_path, read_only=True)

        # Both should be able to read the data
        df1 = db_ro1.get_timeseries_frame("prices")
        df2 = db_ro2.get_timeseries_frame("prices")

        assert df1.height == 3
        assert df2.height == 3
        assert df1["timestamp"].to_list() == df2["timestamp"].to_list()

        db_ro1.close()
        db_ro2.close()

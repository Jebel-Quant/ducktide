"""Tests for the TimeSeriesIngestMixin class in jqr.database.time._ingest."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from jqr.database.time import TimeSeriesDB

timestamp_lists = st.lists(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2035, 12, 31)),
    unique=True,
    min_size=1,
    max_size=8,
)


def make_frame(timestamps: list[datetime]) -> pl.DataFrame:
    """Build a minimal OHLCV-like frame with one row per timestamp."""
    n = len(timestamps)
    return pl.DataFrame(
        {
            "timestamp": sorted(timestamps),
            "instrument_id": [100] * n,
            "close": [1.0] * n,
        }
    )


class TestTimeSeriesIngestMixin:
    """Tests for incremental ingestion behavior."""

    def test_timeseries_db_ingest_and_append(self, ts_db, sample_frame):
        """TimeSeriesDB.ingest should create table and handle incremental appends."""
        # Initial ingestion
        ts_db.ingest("prices", sample_frame)
        df1 = ts_db.get_timeseries_frame("prices")
        assert df1.height == 3

        # Append duplicate data - should NOT increase height (incremental logic)
        ts_db.ingest("prices", sample_frame)
        df2 = ts_db.get_timeseries_frame("prices")
        assert df2.height == 3

        # Append new data
        new_data = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 4)],
                "instrument_id": [100],
                "price": [11.2],
            }
        )
        ts_db.ingest("prices", new_data)
        df3 = ts_db.get_timeseries_frame("prices")
        assert df3.height == 4
        assert df3["timestamp"].max() == date(2025, 1, 4)

    def test_timeseries_db_ingest_no_instrument_id(self, ts_db):
        """TimeSeriesDB.ingest should work without instrument_id using global max timestamp."""
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1), date(2025, 1, 2)],
                "value": [10, 20],
            }
        )
        ts_db.ingest("simple", df)
        assert ts_db.get_timeseries_frame("simple").height == 2

        # Append new data
        new_df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 2), date(2025, 1, 3)],
                "value": [20, 30],
            }
        )
        ts_db.ingest("simple", new_df)
        # Only 2025-01-03 should be added because 2025-01-02 is NOT strictly greater than max existing
        assert ts_db.get_timeseries_frame("simple").height == 3

    def test_ingest_incremental_with_custom_time_col(self):
        """Verify incremental ingestion with a custom time column name."""
        db = TimeSeriesDB(time_col="dt")

        # Initial ingest
        df1 = pl.DataFrame({"dt": [date(2025, 1, 1)], "value": [10]})
        db.ingest("test", df1)

        # Append new data
        df2 = pl.DataFrame({"dt": [date(2025, 1, 1), date(2025, 1, 2)], "value": [10, 20]})
        db.ingest("test", df2)

        res = db.get_timeseries_frame("test")
        assert len(res) == 2
        assert res["dt"].to_list() == [date(2025, 1, 1), date(2025, 1, 2)]

    def test_ingest_incremental_with_instrument_id_and_custom_time_col(self):
        """Verify incremental ingestion with instrument_id and custom time column."""
        db = TimeSeriesDB(time_col="dt")

        # Initial ingest
        df1 = pl.DataFrame({"dt": [date(2025, 1, 1)], "instrument_id": [1], "value": [10]})
        db.ingest("test", df1)

        # Append data (one duplicate, one new)
        df2 = pl.DataFrame({"dt": [date(2025, 1, 1), date(2025, 1, 2)], "instrument_id": [1, 1], "value": [10, 20]})
        db.ingest("test", df2)

        res = db.get_timeseries_frame("test")
        assert len(res) == 2
        assert res["dt"].to_list() == [date(2025, 1, 1), date(2025, 1, 2)]

    def test_readonly_timeseries_db_prevents_writes(self, tmp_path, sample_frame):
        """Test that read-only mode prevents write operations in TimeSeriesDB."""
        # First, create a database with some data
        db_path = tmp_path / "test_ts.duckdb"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Now open it in read-only mode
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Verify we can read the data
        df = db_ro.get_timeseries_frame("prices")
        assert df.height == 3

        # Attempting to ingest should raise an error
        new_data = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 4)],
                "instrument_id": [100],
                "price": [11.2],
            }
        )
        with pytest.raises(Exception, match=r"read-only|read_only"):
            db_ro.ingest("prices", new_data)

        db_ro.close()

    def test_ingest_with_timezone_aware_datetime(self, ts_db):
        """Test incremental ingest with timezone-aware datetime columns."""
        from datetime import datetime

        # Create initial data with timezone-aware datetime
        df1 = pl.DataFrame(
            {
                "timestamp": [datetime(2025, 1, 1, 9, 0)],
                "instrument_id": [1],
                "value": [10],
            }
        ).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        ts_db.ingest("test", df1)

        # Append more data - timezone conversion should be handled
        df2 = pl.DataFrame(
            {
                "timestamp": [datetime(2025, 1, 1, 9, 0), datetime(2025, 1, 1, 10, 0)],
                "instrument_id": [1, 1],
                "value": [10, 20],
            }
        ).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        ts_db.ingest("test", df2)

        result = ts_db.get_timeseries_frame("test")
        assert result.height == 2

    def test_ingest_first_data_for_new_instrument(self, ts_db):
        """Test ingest when instrument has no existing data (max_ts_df is empty for that instrument)."""
        from datetime import datetime

        # Create initial data for instrument 1
        df1 = pl.DataFrame(
            {
                "timestamp": [datetime(2025, 1, 1, 9, 0)],
                "instrument_id": [1],
                "value": [10],
            }
        ).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        ts_db.ingest("test", df1)

        # Now add data for a NEW instrument (instrument 2)
        # This should trigger the path where max_ts is null for the new instrument
        df2 = pl.DataFrame(
            {
                "timestamp": [datetime(2025, 1, 1, 8, 0)],  # Even earlier timestamp
                "instrument_id": [2],
                "value": [20],
            }
        ).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        ts_db.ingest("test", df2)

        result = ts_db.get_timeseries_frame("test")
        assert result.height == 2
        assert set(result["instrument_id"].to_list()) == {1, 2}

    def test_ingest_into_empty_existing_table(self, ts_db):
        """Test ingest when table exists but is empty (max_ts_df.height == 0)."""
        # Create an empty table with the expected schema
        ts_db.con.execute("""
            CREATE TABLE empty_table (
                timestamp TIMESTAMP,
                instrument_id INTEGER,
                value DOUBLE
            )
        """)

        # Verify table exists but is empty
        assert ts_db.has_table("empty_table")
        assert ts_db.get_timeseries_frame("empty_table").height == 0

        # Ingest data into the empty table - this hits the max_ts_df.height == 0 branch
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1)],
                "instrument_id": [1],
                "value": [10.0],
            }
        )
        ts_db.ingest("empty_table", df)

        result = ts_db.get_timeseries_frame("empty_table")
        assert result.height == 1

    def test_ingest_no_instrument_id_no_new_rows(self, ts_db):
        """Re-ingesting only already-known timestamps without instrument_id appends nothing."""
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1), date(2025, 1, 2)],
                "value": [10, 20],
            }
        )
        ts_db.ingest("simple", df)
        ts_db.ingest("simple", df)  # identical timestamps: nothing is strictly newer
        assert ts_db.get_timeseries_frame("simple").height == 2

    # Each example spins up its own in-memory DuckDB; cap the example count and
    # disable the per-example deadline so slow CI runners don't flake.
    @pytest.mark.property
    @settings(max_examples=25, deadline=None)
    @given(timestamps=timestamp_lists)
    def test_ingest_is_idempotent(self, timestamps):
        """Re-ingesting the same frame adds no rows."""
        frame = make_frame(timestamps)

        with TimeSeriesDB() as ts_db:
            ts_db.ingest("prices", frame)
            assert ts_db.get_timeseries_frame("prices").height == len(timestamps)

            ts_db.ingest("prices", frame)
            assert ts_db.get_timeseries_frame("prices").height == len(timestamps)

    @pytest.mark.property
    @settings(max_examples=25, deadline=None)
    @given(timestamps=timestamp_lists)
    def test_ingest_preserves_timestamps(self, timestamps):
        """The ingested table contains exactly the timestamps of the frame."""
        frame = make_frame(timestamps)

        with TimeSeriesDB() as ts_db:
            ts_db.ingest("prices", frame)
            stored = ts_db.get_timeseries_frame("prices")["timestamp"].to_list()
            assert sorted(stored) == sorted(timestamps)

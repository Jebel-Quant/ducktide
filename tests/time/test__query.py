"""Tests for the TimeSeriesQueryMixin class in ducktide.time._query."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import polars as pl
import pytest

from ducktide.exceptions import QueryError
from ducktide.time.timeseries_db import TimeSeriesDB


class TestTimeSeriesQueryMixin:
    """Tests for time series querying and query building."""

    def test_timeseries_db_get_timeseries_frame_filters(self, ts_db, sample_frame):
        """TimeSeriesDB.get_timeseries_frame should apply filters correctly."""
        ts_db.ingest("prices", sample_frame)

        # Filter by instrument_id (already 100)
        df_id = ts_db.get_timeseries_frame("prices", instrument_id=100)
        assert df_id.height == 3

        # Filter by date range
        df_range = ts_db.get_timeseries_frame("prices", start=date(2025, 1, 2), end=date(2025, 1, 2))
        assert df_range.height == 1
        assert df_range["timestamp"][0] == date(2025, 1, 2)

        # Filter with non-existent instrument_id
        df_none = ts_db.get_timeseries_frame("prices", instrument_id=999)
        assert df_none.height == 0

    def test_timeseries_db_get_timeseries_frame_missing_table(self, ts_db):
        """TimeSeriesDB.get_timeseries_frame should return empty DataFrame if table missing."""
        df = ts_db.get_timeseries_frame("non_existent")
        assert isinstance(df, pl.DataFrame)
        assert df.height == 0

    def test_timeseries_db_build_query_logic(self, ts_db):
        """Test query building logic with various combinations of filters."""
        # No filters
        q, p = ts_db._build_query("ts", None, None, None)
        assert "WHERE" not in q
        assert p == []

        # All filters; a date end bound covers the whole day
        q, p = ts_db._build_query("ts", 100, date(2025, 1, 1), date(2025, 1, 3))
        assert "WHERE instrument_id = ? AND timestamp >= ? AND timestamp < ?" in q
        assert p == [100, date(2025, 1, 1), date(2025, 1, 4)]

        # A datetime end bound is used as given
        q, p = ts_db._build_query("ts", None, None, datetime(2025, 1, 3, 12, 0))
        assert "WHERE timestamp <= ?" in q
        assert p == [datetime(2025, 1, 3, 12, 0)]

    def test_timeseries_db_query_errors_raise(self, ts_db):
        """TimeSeriesDB.get_timeseries_frame should raise QueryError on SQL failures."""
        # Force an error by mocking _build_query to return something that will fail in execute
        with patch.object(ts_db, "_build_query", return_value=("SELECT * FROM non_existent WHERE x = ?", [1])):
            # ingest a table so has_table check passes
            ts_db.ingest("fail_table", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1]}))
            with pytest.raises(QueryError, match="fail_table"):
                ts_db.get_timeseries_frame("fail_table")

        # A table without the expected time column should also raise (ORDER BY fails),
        # not silently return an empty frame
        ts_db.con.execute("CREATE TABLE bad_table (id INTEGER)")
        ts_db.con.execute("INSERT INTO bad_table VALUES (1)")

        with pytest.raises(QueryError, match="bad_table"):
            ts_db.get_timeseries_frame("bad_table")

    def test_get_timeseries_frame_is_sorted_and_flagged(self, ts_db):
        """Rows come back in time order, nulls first, with Polars' sorted flag set.

        The order comes from the query's ORDER BY rather than a second sort in
        Polars, so this pins the null placement and the flag that
        ``.sort()`` used to provide.
        """
        ts_db.ingest(
            "unordered",
            pl.DataFrame(
                {
                    "timestamp": [date(2025, 1, 3), None, date(2025, 1, 1), date(2025, 1, 2)],
                    "instrument_id": [1, 1, 1, 1],
                }
            ),
        )

        frame = ts_db.get_timeseries_frame("unordered")

        assert frame["timestamp"].to_list() == [None, date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
        assert frame["timestamp"].flags["SORTED_ASC"]

    def test_timeseries_db_query_error_can_be_handled(self, ts_db):
        """Pipelines that prefer graceful degradation can catch QueryError explicitly."""
        ts_db.con.execute("CREATE TABLE bad_table (id INTEGER)")
        ts_db.con.execute("INSERT INTO bad_table VALUES (1)")

        try:
            df = ts_db.get_timeseries_frame("bad_table")
        except QueryError:
            df = pl.DataFrame()
        assert df.height == 0

    def test_get_timeseries_frame_with_custom_time_col(self):
        """Verify that get_timeseries_frame works with a custom time column name."""
        db = TimeSeriesDB(time_col="dt")
        df = pl.DataFrame({"dt": [date(2025, 1, 1), date(2025, 1, 2)], "value": [10, 20]})
        db.ingest("test", df)

        # All data
        res = db.get_timeseries_frame("test")
        assert len(res) == 2
        assert res["dt"].to_list() == [date(2025, 1, 1), date(2025, 1, 2)]

        # Filtered
        res_filtered = db.get_timeseries_frame("test", start=date(2025, 1, 2))
        assert len(res_filtered) == 1
        assert res_filtered["dt"][0] == date(2025, 1, 2)

    def test_readonly_timeseries_db_allows_reads(self, tmp_path, sample_frame):
        """Test that read-only mode allows read operations in TimeSeriesDB."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Open in read-only mode and verify all data is accessible
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Read all data
        df_all = db_ro.get_timeseries_frame("prices")
        assert df_all.height == 3

        # Read with filters
        df_filtered = db_ro.get_timeseries_frame(
            "prices", instrument_id=100, start=date(2025, 1, 2), end=date(2025, 1, 2)
        )
        assert df_filtered.height == 1
        assert df_filtered["timestamp"][0] == date(2025, 1, 2)

        # Run queries
        df_query = db_ro.query("SELECT COUNT(*) as count FROM prices")
        assert df_query["count"][0] == 3

        db_ro.close()

    def test_readonly_timeseries_db_with_queries(self, tmp_path, sample_frame):
        """Test that read-only mode allows complex queries in TimeSeriesDB."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Open in read-only mode and run queries
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Query all prices
        all_prices = db_ro.get_timeseries_frame("prices")
        assert all_prices.height == 3

        # Execute raw SQL query
        result = db_ro.query("SELECT MAX(price) as max_price FROM prices")
        assert result["max_price"][0] == 11.0

        # Check tables
        assert "prices" in db_ro.tables()
        assert db_ro.has_table("prices")

        db_ro.close()

    def test_get_timeseries_frame_with_timezone_datetime(self, ts_db):
        """Test timezone conversion with Datetime column."""
        from datetime import datetime

        # Create data with timezone-aware datetime
        df = pl.DataFrame(
            {
                "timestamp": [
                    datetime(2025, 1, 1, 9, 0),
                    datetime(2025, 1, 1, 10, 0),
                ],
                "value": [10, 20],
            }
        ).with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        ts_db.ingest("test", df)

        # Query with timezone conversion
        result = ts_db.get_timeseries_frame("test", timezone="America/New_York")
        assert result.height == 2
        # Verify timezone was converted
        assert result["timestamp"].dtype.time_zone == "America/New_York"

    def test_get_timeseries_frame_with_timezone_date(self, ts_db):
        """Test timezone parameter with Date column (should not crash)."""
        # Create data with Date column (not Datetime)
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1), date(2025, 1, 2)],
                "value": [10, 20],
            }
        )
        ts_db.ingest("test", df)

        # Query with timezone - should not crash, just skip conversion for Date
        result = ts_db.get_timeseries_frame("test", timezone="America/New_York")
        assert result.height == 2
        # Date columns don't have timezone, so it should remain Date
        assert result["timestamp"].dtype == pl.Date

    def test_get_timeseries_frame_with_timezone_time_column(self):
        """Test timezone parameter with a temporal column that is neither Datetime nor Date."""
        from datetime import time

        ts_db = TimeSeriesDB()
        df = pl.DataFrame(
            {
                "timestamp": [time(9, 0), time(10, 0)],
                "value": [10, 20],
            }
        )
        ts_db.ingest("times", df)

        # Time columns are temporal but neither Datetime nor Date: conversion is skipped
        result = ts_db.get_timeseries_frame("times", timezone="America/New_York")
        assert result.height == 2
        assert result["timestamp"].dtype == pl.Time
        ts_db.close()


class TestDateEndBound:
    """A ``date`` end bound includes every row on that day."""

    @pytest.fixture
    def intraday(self, ts_db):
        """Two intraday rows on 2 January and one at midnight on 3 January."""
        ts_db.ingest(
            "m",
            pl.DataFrame(
                {
                    "timestamp": [datetime(2025, 1, 2, 9, 30), datetime(2025, 1, 2, 16, 0), datetime(2025, 1, 3)],
                    "instrument_id": [1, 1, 1],
                    "close": [1.0, 2.0, 3.0],
                }
            ),
        )
        return ts_db

    def test_date_end_includes_intraday_rows(self, intraday):
        """end=date(2025, 1, 2) returns both rows of that day and nothing from the next."""
        frame = intraday.get_timeseries_frame("m", end=date(2025, 1, 2))
        assert frame["close"].to_list() == [1.0, 2.0]

    def test_datetime_end_is_inclusive_to_the_instant(self, intraday):
        """A datetime end bound keeps its exact cut-off."""
        frame = intraday.get_timeseries_frame("m", end=datetime(2025, 1, 2, 9, 30))
        assert frame["close"].to_list() == [1.0]

    def test_date_start_and_end_select_one_day(self, intraday):
        """Start and end on the same date select exactly that day."""
        frame = intraday.get_timeseries_frame("m", start=date(2025, 1, 2), end=date(2025, 1, 2))
        assert frame.height == 2

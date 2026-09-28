"""Tests for the TimeSeriesIngestMixin class in ducktide.time._ingest."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ducktide.exceptions import ValidationError
from ducktide.time import TimeSeriesDB

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
        """TimeSeriesDB.ingest should create the table, then upsert without duplicating rows."""
        # Initial ingestion
        ts_db.ingest("prices", sample_frame)
        df1 = ts_db.get_timeseries_frame("prices")
        assert df1.height == 3

        # Re-ingesting the same rows upserts them in place - no new rows
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
        """Without instrument_id the frame is one series, keyed on the timestamp alone."""
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
        # 2025-01-02 is already stored and is updated in place; only 2025-01-03 is new
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
        """Timezone-aware keys match stored rows instead of duplicating them."""
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
        """Rows for a new instrument land even when they are older than every stored row."""
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
        """Ingest into a table that exists but holds no rows."""
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
        """Re-ingesting only already-known timestamps without instrument_id adds no rows."""
        df = pl.DataFrame(
            {
                "timestamp": [date(2025, 1, 1), date(2025, 1, 2)],
                "value": [10, 20],
            }
        )
        ts_db.ingest("simple", df)
        ts_db.ingest("simple", df)  # identical keys: both rows are updated in place
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


def _rows(ts_db: TimeSeriesDB, table: str, *cols: str) -> list[tuple]:
    """Return the table's rows as tuples of ``cols``, sorted."""
    return sorted(ts_db.get_timeseries_frame(table).select(cols).iter_rows())


class TestUpsert:
    """Late rows, corrections, custom keys and the MERGE edge cases."""

    def test_late_row_is_inserted(self, ts_db):
        """A row older than everything stored for its instrument still lands."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 2)], "instrument_id": [1], "close": [2.0]}))
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0]}))

        assert _rows(ts_db, "p", "timestamp", "close") == [(date(2025, 1, 1), 1.0), (date(2025, 1, 2), 2.0)]

    def test_correction_overwrites_stored_row(self, ts_db):
        """By default an incoming row replaces the stored row with the same key."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0]}))
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.5]}))

        assert _rows(ts_db, "p", "timestamp", "close") == [(date(2025, 1, 1), 1.5)]

    def test_on_conflict_ignore_keeps_stored_row(self, ts_db):
        """With on_conflict='ignore' stored rows win, but new keys (late rows too) still land."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 2)], "instrument_id": [1], "close": [2.0]}))
        ts_db.ingest(
            "p",
            pl.DataFrame(
                {"timestamp": [date(2025, 1, 1), date(2025, 1, 2)], "instrument_id": [1, 1], "close": [1.0, 9.0]}
            ),
            on_conflict="ignore",
        )

        assert _rows(ts_db, "p", "timestamp", "close") == [(date(2025, 1, 1), 1.0), (date(2025, 1, 2), 2.0)]

    def test_custom_key_separates_series(self, ts_db):
        """A multi-column key keeps series apart that share a timestamp."""
        t = datetime(2025, 1, 1)
        fx = pl.DataFrame({"timestamp": [t, t], "base": ["EUR", "GBP"], "quote": ["USD", "USD"], "rate": [1.1, 1.3]})
        ts_db.ingest("fx", fx, key=["base", "quote"])
        ts_db.ingest(
            "fx",
            pl.DataFrame({"timestamp": [t], "base": ["EUR"], "quote": ["USD"], "rate": [1.2]}),
            key=["base", "quote"],
        )

        assert _rows(ts_db, "fx", "base", "rate") == [("EUR", 1.2), ("GBP", 1.3)]

    def test_key_may_name_the_time_column(self, ts_db):
        """Listing the timestamp column in ``key`` is accepted; it is always part of the key."""
        frame = pl.DataFrame({"timestamp": [date(2025, 1, 1)], "sensor": ["a"], "v": [1]})
        ts_db.ingest("s", frame, key=["sensor", "timestamp"])
        ts_db.ingest("s", frame.with_columns(v=pl.lit(2)), key=["sensor", "timestamp"])

        assert _rows(ts_db, "s", "sensor", "v") == [("a", 2)]

    def test_explicit_empty_key_ignores_instrument_id(self, ts_db):
        """``key=[]`` makes the timestamp alone the key, even with an instrument_id column."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0]}), key=[])
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [2], "close": [2.0]}), key=[])

        assert _rows(ts_db, "p", "instrument_id", "close") == [(2, 2.0)]

    @pytest.mark.parametrize(
        ("key", "frame", "match"),
        [
            (["venue"], {"timestamp": [date(2025, 1, 1)], "v": [1]}, "missing key column"),
            (None, {"ts": [date(2025, 1, 1)], "v": [1]}, "missing key column"),
            (["venue", "venue"], {"timestamp": [date(2025, 1, 1)], "venue": ["x"]}, "repeats a column"),
        ],
    )
    def test_invalid_key_raises(self, ts_db, key, frame, match):
        """A key that cannot be resolved against the frame is rejected before anything is written."""
        with pytest.raises(ValidationError, match=match):
            ts_db.ingest("p", pl.DataFrame(frame), key=key)
        assert not ts_db.has_table("p")

    def test_invalid_on_conflict_raises(self, ts_db, sample_frame):
        """Only 'update' and 'ignore' are accepted."""
        with pytest.raises(ValidationError, match="on_conflict"):
            ts_db.ingest("p", sample_frame, on_conflict="replace")  # type: ignore[arg-type]

    def test_columns_are_matched_by_name(self, ts_db):
        """A frame whose column order differs from the table's still lands in the right columns."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0]}))
        ts_db.ingest(
            "p",
            pl.DataFrame(
                {"close": [9.0, 2.0], "instrument_id": [1, 1], "timestamp": [date(2025, 1, 1), date(2025, 1, 2)]}
            ),
        )

        assert _rows(ts_db, "p", "instrument_id", "timestamp", "close") == [
            (1, date(2025, 1, 1), 9.0),
            (1, date(2025, 1, 2), 2.0),
        ]

    def test_missing_columns_are_left_null_or_unchanged(self, ts_db):
        """Columns absent from the frame are NULL on insert and untouched on update."""
        ts_db.ingest(
            "p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0], "volume": [10]})
        )
        ts_db.ingest(
            "p",
            pl.DataFrame(
                {"timestamp": [date(2025, 1, 1), date(2025, 1, 2)], "instrument_id": [1, 1], "close": [1.5, 2.0]}
            ),
        )

        assert _rows(ts_db, "p", "timestamp", "close", "volume") == [
            (date(2025, 1, 1), 1.5, 10),
            (date(2025, 1, 2), 2.0, None),
        ]

    @pytest.mark.parametrize("existing", [False, True])
    def test_last_row_wins_within_a_frame(self, ts_db, existing):
        """Duplicate keys inside one frame collapse to the last one, on create and on upsert."""
        if existing:
            ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [0.0]}))
        dupes = pl.DataFrame({"timestamp": [date(2025, 1, 1)] * 3, "instrument_id": [1] * 3, "close": [1.0, 2.0, 3.0]})
        ts_db.ingest("p", dupes)

        assert _rows(ts_db, "p", "timestamp", "close") == [(date(2025, 1, 1), 3.0)]

    def test_null_key_matches_stored_null_key(self, ts_db):
        """A NULL series value matches a stored NULL instead of inserting a duplicate."""
        frame = pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [None], "close": [1.0]})
        ts_db.ingest("p", frame.with_columns(pl.col("instrument_id").cast(pl.Int64)))
        ts_db.ingest("p", frame.with_columns(pl.col("instrument_id").cast(pl.Int64), close=pl.lit(2.0)))

        assert _rows(ts_db, "p", "instrument_id", "close") == [(None, 2.0)]

    def test_empty_frame_is_a_no_op(self, ts_db, sample_frame):
        """An empty frame for an existing table writes nothing."""
        ts_db.ingest("p", sample_frame)
        ts_db.ingest("p", sample_frame.clear())

        assert ts_db.get_timeseries_frame("p").height == sample_frame.height

    def test_failed_merge_leaves_no_registration(self, ts_db, sample_frame):
        """A frame the table cannot take raises and leaves no batch registered on the connection."""
        ts_db.ingest("p", sample_frame)
        with pytest.raises(Exception, match="unknown"):
            ts_db.ingest("p", sample_frame.with_columns(unknown=pl.lit(1)))

        assert ts_db.get_timeseries_frame("p").height == sample_frame.height
        with pytest.raises(Exception, match="__ducktide_ingest"):
            ts_db.con.execute("SELECT * FROM __ducktide_ingest")

    # Model the store as a dict keyed on (instrument_id, timestamp): every ingest
    # is a last-write-wins update, whatever order the batches arrive in.
    @pytest.mark.property
    @settings(max_examples=25, deadline=None)
    @given(
        batches=st.lists(
            st.lists(
                st.tuples(
                    st.integers(1, 3),
                    st.dates(min_value=date(2025, 1, 1), max_value=date(2025, 1, 10)),
                    st.floats(allow_nan=False, allow_infinity=False, width=32),
                ),
                max_size=6,
            ),
            min_size=1,
            max_size=4,
        )
    )
    def test_upsert_matches_last_write_wins_model(self, batches):
        """Any sequence of batches, overlapping or out of order, ends as last-write-wins per key."""
        expected: dict[tuple[int, date], float] = {}
        with TimeSeriesDB() as ts_db:
            for batch in batches:
                frame = pl.DataFrame(
                    batch,
                    schema={"instrument_id": pl.Int64, "timestamp": pl.Date, "close": pl.Float64},
                    orient="row",
                )
                ts_db.ingest("p", frame)
                expected.update({(i, t): c for i, t, c in batch})

            stored = ts_db.get_timeseries_frame("p")
            assert sorted(stored.select("instrument_id", "timestamp", "close").iter_rows()) == sorted(
                (i, t, c) for (i, t), c in expected.items()
            )

"""Tests for the TimeSeriesIngestMixin class in ducktide.time._ingest."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ducktide.exceptions import DatabaseError, ValidationError
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
                    st.one_of(st.none(), st.integers(1, 3)),  # NULL keys mixed with real ones
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
        """Any sequence of batches, overlapping or out of order, NULL keys included, ends as last-write-wins per key."""
        expected: dict[tuple[int | None, date], float] = {}
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

            def order(row):
                """Sort NULL instrument ids last, since None does not compare with int."""
                return (row[0] is None, row[0] or 0, row[1])

            assert sorted(stored.select("instrument_id", "timestamp", "close").iter_rows(), key=order) == sorted(
                ((i, t, c) for (i, t), c in expected.items()), key=order
            )


class _RecordingRegister:
    """Delegate to a real DuckDB connection, recording every frame passed to ``register``."""

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner
        self.registered: list[pl.DataFrame] = []

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def register(self, name, frame):
        """Record the frame, then register it for real."""
        self.registered.append(frame)
        return self._inner.register(name, frame)


class TestChunkedFrames:
    """Frames assembled from many pieces reach DuckDB as one contiguous chunk."""

    @staticmethod
    def _pieces(day: int, n: int = 50) -> pl.DataFrame:
        """One day's bars for ``n`` instruments, concatenated from one-row frames (``n`` chunks)."""
        frame = pl.concat(
            [
                pl.DataFrame({"timestamp": [date(2025, 1, day)], "instrument_id": [i], "close": [float(i)]})
                for i in range(n)
            ]
        )
        assert frame.n_chunks() == n
        return frame

    @pytest.mark.parametrize("existing", [False, True])
    def test_chunked_frame_is_registered_as_one_chunk(self, ts_db, monkeypatch, existing):
        """On create and on upsert, DuckDB is handed a single-chunk frame with every row."""
        if existing:
            ts_db.ingest("p", self._pieces(1))
        recorder = _RecordingRegister(ts_db.con)
        monkeypatch.setattr(ts_db, "con", recorder)

        ts_db.ingest("p", self._pieces(2))
        monkeypatch.undo()

        assert [f.n_chunks() for f in recorder.registered] == [1]
        assert recorder.registered[0].height == 50
        assert ts_db.get_timeseries_frame("p").height == (100 if existing else 50)


class _RecordingExecute:
    """Delegate to a real DuckDB connection, recording every SQL statement executed."""

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner
        self.statements: list[str] = []

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def execute(self, statement, *args, **kwargs):
        """Record the statement, then run it for real."""
        self.statements.append(statement)
        return self._inner.execute(statement, *args, **kwargs)


class TestMergeCondition:
    """Key columns compare with ``=`` unless the incoming frame has NULLs in them."""

    def _merge(self, ts_db, monkeypatch, frame):
        """Ingest ``frame`` onto an existing table and return the MERGE statement it ran."""
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [1], "close": [1.0]}))
        recorder = _RecordingExecute(ts_db.con)
        monkeypatch.setattr(ts_db, "con", recorder)
        ts_db.ingest("p", frame)
        monkeypatch.undo()
        (merge,) = [s for s in recorder.statements if s.startswith("MERGE")]
        return merge

    def test_frame_without_nulls_uses_equality(self, ts_db, monkeypatch):
        """A batch with no NULL keys joins with plain ``=``, which lets DuckDB skip row groups."""
        frame = pl.DataFrame({"timestamp": [date(2025, 1, 2)], "instrument_id": [1], "close": [2.0]})
        merge = self._merge(ts_db, monkeypatch, frame)
        assert "IS NOT DISTINCT FROM" not in merge
        assert 't."instrument_id" = s."instrument_id"' in merge

    def test_null_key_column_is_null_safe(self, ts_db, monkeypatch):
        """Only the key column holding NULLs compares with IS NOT DISTINCT FROM."""
        frame = pl.DataFrame({"timestamp": [date(2025, 1, 2)] * 2, "instrument_id": [1, None], "close": [2.0, 3.0]})
        merge = self._merge(ts_db, monkeypatch, frame)
        assert 't."instrument_id" IS NOT DISTINCT FROM s."instrument_id"' in merge
        assert 't."timestamp" = s."timestamp"' in merge

    def test_stored_null_key_is_not_matched_by_a_real_key(self, ts_db):
        """With ``=``, a stored NULL key still never matches an incoming non-NULL key."""
        null_row = pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [None], "close": [1.0]})
        ts_db.ingest("p", null_row.with_columns(pl.col("instrument_id").cast(pl.Int64)))
        ts_db.ingest("p", pl.DataFrame({"timestamp": [date(2025, 1, 1)], "instrument_id": [7], "close": [2.0]}))

        stored = sorted(ts_db.get_timeseries_frame("p").select("instrument_id", "close").iter_rows(), key=str)
        assert stored == [(7, 2.0), (None, 1.0)]


def _physical(ts_db: TimeSeriesDB, table: str, *cols: str) -> list[tuple]:
    """Return ``cols`` in physical storage order (by rowid)."""
    names = ", ".join(cols)
    return ts_db.query(f"SELECT {names} FROM {table} ORDER BY rowid").rows()  # noqa: S608 - test-controlled names


class _FailingDelete:
    """Delegate to a real DuckDB connection but fail the ``DELETE`` of a compaction after it has run."""

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def execute(self, statement, *args, **kwargs):
        """Run the statement, then fail if it was the DELETE."""
        result = self._inner.execute(statement, *args, **kwargs)
        if statement.startswith("DELETE"):
            msg = "disk full"
            raise RuntimeError(msg)
        return result


class TestCompact:
    """Rewriting a table grouped by series key."""

    @pytest.fixture
    def interleaved(self, ts_db):
        """Ingest three days for two instruments, day by day, so storage is in time order."""
        for day in (1, 2, 3):
            ts_db.ingest(
                "p",
                pl.DataFrame(
                    {"timestamp": [date(2025, 1, day)] * 2, "instrument_id": [2, 1], "close": [20.0 + day, 10.0 + day]}
                ),
            )
        return ts_db

    def test_groups_rows_by_series_then_time(self, interleaved):
        """After compacting, each instrument's rows are stored together, in time order."""
        # Day-by-day ingestion interleaves the instruments (MERGE does not keep
        # a batch's row order, so only the interleaving is asserted).
        stored = [i for (i,) in _physical(interleaved, "p", "instrument_id")]
        assert stored != sorted(stored)

        interleaved.compact("p")

        assert _physical(interleaved, "p", "instrument_id", "timestamp") == [
            (1, date(2025, 1, 1)),
            (1, date(2025, 1, 2)),
            (1, date(2025, 1, 3)),
            (2, date(2025, 1, 1)),
            (2, date(2025, 1, 2)),
            (2, date(2025, 1, 3)),
        ]

    def test_contents_are_unchanged(self, interleaved):
        """Compaction only reorders; every row and value survives."""
        before = _rows(interleaved, "p", "instrument_id", "timestamp", "close")
        interleaved.compact("p")
        assert _rows(interleaved, "p", "instrument_id", "timestamp", "close") == before

    def test_custom_key_and_schema_qualified_table(self, ts_db):
        """A multi-column key groups by those columns, in the table they name."""
        t = [datetime(2025, 1, 1), datetime(2025, 1, 2)]
        for when in t:
            ts_db.ingest(
                "fx.rates",
                pl.DataFrame(
                    {"timestamp": [when] * 2, "base": ["GBP", "EUR"], "quote": ["USD", "USD"], "rate": [1.3, 1.1]}
                ),
                key=["base", "quote"],
            )
        ts_db.compact("fx.rates", key=["base", "quote"])

        assert _physical(ts_db, "fx.rates", "base", "timestamp") == [
            ("EUR", t[0]),
            ("EUR", t[1]),
            ("GBP", t[0]),
            ("GBP", t[1]),
        ]

    def test_without_instrument_id_sorts_by_time(self, ts_db):
        """A table with no series column is rewritten in time order."""
        ts_db.con.execute(
            "CREATE TABLE s AS SELECT * FROM (VALUES (DATE '2025-01-02', 2), (DATE '2025-01-01', 1)) v(timestamp, v)"
        )
        ts_db.compact("s")
        assert [v for (v,) in _physical(ts_db, "s", "v")] == [1, 2]

    def test_keeps_constraints(self, ts_db):
        """A table's primary key survives compaction and is still enforced."""
        ts_db.con.execute(
            "CREATE TABLE pk (timestamp DATE, instrument_id BIGINT, close DOUBLE,"
            " PRIMARY KEY (instrument_id, timestamp))"
        )
        ts_db.con.execute("INSERT INTO pk VALUES ('2025-01-02', 2, 1.0), ('2025-01-01', 1, 2.0)")
        ts_db.compact("pk")

        assert [i for (i,) in _physical(ts_db, "pk", "instrument_id")] == [1, 2]
        with pytest.raises(Exception, match=r"(?i)constraint"):
            ts_db.con.execute("INSERT INTO pk VALUES ('2025-01-01', 1, 9.0)")

    def test_missing_table_is_a_no_op(self, ts_db):
        """Compacting a table that does not exist does nothing, as reading it returns nothing."""
        ts_db.compact("nope")
        assert not ts_db.has_table("nope")

    def test_missing_key_column_raises(self, interleaved):
        """A key the table does not have is rejected before anything is rewritten."""
        before = _physical(interleaved, "p", "instrument_id", "timestamp")
        with pytest.raises(ValidationError, match="table 'p' is missing key column"):
            interleaved.compact("p", key=["venue"])
        assert _physical(interleaved, "p", "instrument_id", "timestamp") == before

    def test_failure_rolls_back(self, interleaved, monkeypatch):
        """A failure after the rows were deleted restores the table and leaves no scratch table."""
        before = _physical(interleaved, "p", "instrument_id", "timestamp", "close")
        monkeypatch.setattr(interleaved, "con", _FailingDelete(interleaved.con))
        with pytest.raises(RuntimeError, match="disk full"):
            interleaved.compact("p")
        monkeypatch.undo()

        assert _physical(interleaved, "p", "instrument_id", "timestamp", "close") == before
        assert not interleaved.has_table("__ducktide_compact")
        interleaved.con.begin()  # no transaction was left open
        interleaved.con.rollback()

    def test_read_only_raises(self, tmp_path, sample_frame):
        """A read-only database cannot be compacted, and is left intact."""
        path = tmp_path / "ro.duckdb"
        with TimeSeriesDB(path) as db:
            db.ingest("prices", sample_frame)
        with TimeSeriesDB(path, read_only=True) as db:
            with pytest.raises(Exception, match=r"(?i)read-only|read_only"):
                db.compact("prices")
            assert db.get_timeseries_frame("prices").height == sample_frame.height


class TestReadOnly:
    """A read-only store refuses ingest and compact with a ducktide error."""

    def test_ingest_and_compact_are_refused(self, tmp_path):
        """Ingest and compact raise DatabaseError, not DuckDB's InvalidInputException."""
        path = tmp_path / "ro.duckdb"
        with TimeSeriesDB(path) as writable:
            writable.ingest("prices", make_frame([datetime(2025, 1, 2)]))
        with TimeSeriesDB(path, read_only=True) as ro:
            with pytest.raises(DatabaseError, match="read-only: ingest"):
                ro.ingest("prices", make_frame([datetime(2025, 1, 3)]))
            with pytest.raises(DatabaseError, match="read-only: compact"):
                ro.compact("prices")
            assert ro.get_timeseries_frame("prices").height == 1

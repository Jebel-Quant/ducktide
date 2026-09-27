"""Tests for the TimeSeriesDB class in src/ducktide/time/timeseries_db.py."""

from __future__ import annotations

from ducktide.time.timeseries_db import TimeSeriesDB


class TestTimeSeriesDB:
    """Tests for the composed TimeSeriesDB facade."""

    def test_timeseries_db_init_memory(self):
        """TimeSeriesDB should initialize an in-memory database by default."""
        db = TimeSeriesDB()
        assert db.con is not None
        db.close()

    def test_timeseries_db_init_file(self, tmp_path):
        """TimeSeriesDB should initialize a file-based database."""
        db_path = tmp_path / "test_ts.duckdb"
        db = TimeSeriesDB(db_path)
        assert db_path.exists()
        db.close()

    def test_timeseries_db_schema_support(self, ts_db, sample_frame):
        """TimeSeriesDB should support schema-qualified table names."""
        ts_db.ingest("my_schema.prices", sample_frame)
        assert "my_schema.prices" in ts_db.tables()
        df = ts_db.get_timeseries_frame("my_schema.prices")
        assert df.height == 3

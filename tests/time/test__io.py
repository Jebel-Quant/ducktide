"""Tests for the TimeSeriesIOMixin class in ducktide.time._io."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducktide.exceptions import QueryError, ValidationError
from ducktide.time.timeseries_db import TimeSeriesDB


class TestTimeSeriesIOMixin:
    """Tests for CSV/Parquet import and export."""

    def test_timeseries_db_csv_import_export(self, ts_db, sample_frame, tmp_path):
        """TimeSeriesDB should import and export CSV files."""
        csv_path = str(tmp_path / "test.csv")
        ts_db.ingest("prices", sample_frame)

        ts_db.export_csv("prices", csv_path)
        assert Path(csv_path).exists()

        ts_db.import_csv(csv_path, "prices_copy")
        assert "prices_copy" in ts_db.tables()
        df_copy = ts_db.get_timeseries_frame("prices_copy")
        assert df_copy.height == 3

        # Exporting non-existent table should raise QueryError
        with pytest.raises(QueryError, match="Table 'ghost' does not exist"):
            ts_db.export_csv("ghost", str(tmp_path / "ghost.csv"))

    def test_timeseries_db_parquet_import_export(self, ts_db, sample_frame, tmp_path):
        """TimeSeriesDB should import and export Parquet files."""
        pq_path = str(tmp_path / "test.parquet")
        ts_db.ingest("prices", sample_frame)

        ts_db.export_parquet("prices", pq_path)
        assert Path(pq_path).exists()

        ts_db.import_parquet(pq_path, "prices_copy")
        assert "prices_copy" in ts_db.tables()
        df_copy = ts_db.get_timeseries_frame("prices_copy")
        assert df_copy.height == 3

        # Exporting non-existent table should raise QueryError
        with pytest.raises(QueryError, match="Table 'ghost' does not exist"):
            ts_db.export_parquet("ghost", str(tmp_path / "ghost.parquet"))

    def test_timeseries_db_rejects_invalid_table_names_import_export(self, ts_db, sample_frame, tmp_path):
        """Import/export should reject invalid table names before touching SQL."""
        csv_path = str(tmp_path / "test.csv")
        pq_path = str(tmp_path / "test.parquet")
        ts_db.ingest("prices", sample_frame)
        ts_db.export_csv("prices", csv_path)
        ts_db.export_parquet("prices", pq_path)

        bad = "table; DROP TABLE prices; --"
        with pytest.raises(ValidationError, match="Invalid table name"):
            ts_db.import_csv(csv_path, bad)
        with pytest.raises(ValidationError, match="Invalid table name"):
            ts_db.export_csv(bad, csv_path)
        with pytest.raises(ValidationError, match="Invalid table name"):
            ts_db.import_parquet(pq_path, bad)
        with pytest.raises(ValidationError, match="Invalid table name"):
            ts_db.export_parquet(bad, pq_path)

    def test_readonly_prevents_import_csv(self, tmp_path, sample_frame):
        """Test that read-only mode prevents CSV import."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"
        csv_path = tmp_path / "test.csv"

        # Create database with data and export to CSV
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.export_csv("prices", str(csv_path))
        db.close()

        # Open in read-only mode
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Attempting to import CSV should fail
        with pytest.raises(Exception, match=r"read-only|read_only"):
            db_ro.import_csv(str(csv_path), "new_table")

        db_ro.close()

    def test_readonly_allows_export_csv(self, tmp_path, sample_frame):
        """Test that read-only mode allows CSV export."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"
        csv_path = tmp_path / "test.csv"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Open in read-only mode
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Export should work
        db_ro.export_csv("prices", str(csv_path))
        assert Path(csv_path).exists()

        # Verify exported data
        import_db = TimeSeriesDB()
        import_db.import_csv(str(csv_path), "prices")
        df = import_db.get_timeseries_frame("prices")
        assert df.height == 3

        db_ro.close()
        import_db.close()

    def test_readonly_prevents_import_parquet(self, tmp_path, sample_frame):
        """Test that read-only mode prevents Parquet import."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"
        pq_path = tmp_path / "test.parquet"

        # Create database with data and export to Parquet
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.export_parquet("prices", str(pq_path))
        db.close()

        # Open in read-only mode
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Attempting to import Parquet should fail
        with pytest.raises(Exception, match=r"read-only|read_only"):
            db_ro.import_parquet(str(pq_path), "new_table")

        db_ro.close()

    def test_readonly_allows_export_parquet(self, tmp_path, sample_frame):
        """Test that read-only mode allows Parquet export."""
        # Create a database with test data
        db_path = tmp_path / "test_ts.duckdb"
        pq_path = tmp_path / "test.parquet"

        # Create database with data
        db = TimeSeriesDB(db_path)
        db.ingest("prices", sample_frame)
        db.close()

        # Open in read-only mode
        db_ro = TimeSeriesDB(db_path, read_only=True)

        # Export should work
        db_ro.export_parquet("prices", str(pq_path))
        assert Path(pq_path).exists()

        # Verify exported data
        import_db = TimeSeriesDB()
        import_db.import_parquet(str(pq_path), "prices")
        df = import_db.get_timeseries_frame("prices")
        assert df.height == 3

        db_ro.close()
        import_db.close()

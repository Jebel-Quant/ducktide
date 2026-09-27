"""Shared fixtures for the ducktide.time test package.

Security note: S101 (assert statements) are intentional in test code — pytest
relies on assert for test assertions and they are never executed in production.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from ducktide.time.timeseries_db import TimeSeriesDB


@pytest.fixture
def ts_db():
    """Provide an in-memory TimeSeriesDB instance."""
    db = TimeSeriesDB()
    yield db
    db.close()


@pytest.fixture
def sample_frame():
    """Provide a sample Polars DataFrame for testing ingestion."""
    return pl.DataFrame(
        {
            "timestamp": [
                date(2025, 1, 1),
                date(2025, 1, 2),
                date(2025, 1, 3),
            ],
            "instrument_id": [100, 100, 100],
            "price": [10.5, 11.0, 10.8],
        }
    )

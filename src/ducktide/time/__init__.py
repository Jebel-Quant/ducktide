"""Time series data management utilities.

This package provides specialized infrastructure for handling high-volume time series data,
separate from entity metadata. It includes:

- **TimeSeriesDB**: DuckDB-backed storage optimized for time series queries
- **TimeSeriesModel**: Abstract mixin for domain models with time series access
- **TimeSeriesRepository**: Protocol defining the time series data interface

The time series layer is designed for:
- Append-heavy workloads (continuous data ingestion)
- Time-range queries (efficient filtering by timestamp)
- High-volume numerical data (price, volume, order book, etc.)

Example:
    >>> from jqr.database.time import TimeSeriesDB
    >>> ts_db = TimeSeriesDB()
    >>> df = ts_db.get_timeseries_frame("future", instrument_id=100)
"""

from .timeseries_db import TimeSeriesDB
from .timeseries_model import TimeSeriesModel
from .timeseries_repo import TimeSeriesRepository

__all__ = ["TimeSeriesDB", "TimeSeriesModel", "TimeSeriesRepository"]

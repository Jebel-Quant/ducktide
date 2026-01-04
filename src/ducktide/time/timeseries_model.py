"""Time series accessor mixin for domain models.

This module provides a mixin class that can be used by domain models to access
time series data in a consistent way. It centralizes the code for retrieving
time series data, eliminating duplication across domain model classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import polars as pl

from .timeseries_repo import TimeSeriesRepository


class TimeSeriesModel(ABC):
    """Abstract base class for domain models exposing time series data."""

    @property
    @abstractmethod
    def table_name(self) -> str:
        """The name of the table containing this model's time series data."""
        ...

    @property
    @abstractmethod
    def instrument_id(self) -> int:
        """The ID used to identify this instrument in time series data."""
        ...

    def get_timeseries_frame(
        self,
        repo: TimeSeriesRepository,
        start: date | None = None,
        end: date | None = None,
    ) -> pl.DataFrame:
        """Retrieve time series data for this instrument as a Polars DataFrame."""
        return repo.get_timeseries_frame(
            table=self.table_name,
            instrument_id=self.instrument_id,
            start=start,
            end=end,
        )

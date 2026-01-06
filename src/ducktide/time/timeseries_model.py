"""Time series accessor mixin for domain models.

This module provides a mixin class that can be used by domain models to access
time series data in a consistent way. It centralizes the code for retrieving
time series data, eliminating duplication across domain model classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from jqr.database.exceptions import ValidationError

if TYPE_CHECKING:
    from .timeseries_repo import TimeSeriesRepository


class TimeSeriesModel(ABC):
    """Abstract base class for domain models exposing time series data.

    Subclasses must provide an `instrument_id` property and a `table_name`
    class attribute (inherited from DomainModel).
    """

    @property
    @abstractmethod
    def instrument_id(self) -> int | None:
        """The ID used to identify this instrument in time series data."""

    def get_timeseries_frame(
        self,
        repo: TimeSeriesRepository,
        start: date | None = None,
        end: date | None = None,
    ) -> pl.DataFrame:
        """Retrieve time series data for this instrument as a Polars DataFrame.

        Args:
            repo: The time series repository to query.
            start: Optional start date for filtering.
            end: Optional end date for filtering.

        Returns:
            A Polars DataFrame containing the time series data.

        Raises:
            ValidationError: If instrument_id is not set.
        """
        if self.instrument_id is None:
            msg = "Cannot get timeseries: instrument_id is not set"
            raise ValidationError(msg)

        return repo.get_timeseries_frame(
            table=self.table_name,
            instrument_id=self.instrument_id,
            start=start,
            end=end,
        )

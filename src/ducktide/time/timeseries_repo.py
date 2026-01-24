"""Time series repository protocol definition.

This module defines the protocol (interface) for time series repositories,
allowing for dependency inversion and flexible implementation of different
time series data sources without direct dependencies.
"""

from datetime import date
from typing import Protocol

import polars as pl


class TimeSeriesRepository(Protocol):
    """Protocol defining the interface for time series data repositories.

    This protocol specifies the methods that must be implemented by any
    concrete time series repository class,
    allowing for different implementations
    while maintaining a consistent interface for clients.
    """

    def get_timeseries_frame(
        self,
        table: str,
        instrument_id: int,
        start: date | None,
        end: date | None,
        timezone: str | None = None,
        every: str | None = None,
    ) -> pl.DataFrame:
        """Retrieve time series data as a Polars DataFrame.

        Args:
            table: The name of the table containing the time series data
            instrument_id: The ID of the instrument to retrieve data for
            start: Optional start date to filter the data
            end: Optional end date to filter the data
            timezone: Optional target timezone for the timestamp column
            every: Optional resampling frequency

        Returns:
            polars.DataFrame containing the time series data
        """
        ...

    def ingest(self, table: str, frame: pl.DataFrame) -> None:
        """Ingest time series data into the repository."""
        ...

"""Time series accessor mixin for domain models.

This module provides a mixin class that can be used by domain models to access
and ingest time series data in a consistent way. It centralizes the code for
retrieving and preparing time series data, eliminating duplication across
domain model classes.
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
    class attribute (inherited from DomainModel). This mixin provides
    high-level methods to query and ingest time series data associated
    with the instrument.
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
        timezone: str | None = None,
        every: str | None = None,
    ) -> pl.DataFrame:
        """Retrieve time series data for this instrument as a Polars DataFrame.

        Args:
            repo: The time series repository to query.
            start: Optional start date for filtering.
            end: Optional end date for filtering.
            timezone: Optional target timezone for the timestamp column.
            every: Optional resampling frequency (e.g., "1d", "1h").
                If provided, data will be resampled using OHLCV aggregation.

        Returns:
            A Polars DataFrame containing the time series data.

        Raises:
            ValidationError: If instrument_id is not set.
        """
        if self.instrument_id is None:
            msg = "Cannot get timeseries: instrument_id is not set"
            raise ValidationError(msg)

        table = getattr(type(self), "table_name", None)
        if table is None:
            raise AttributeError(f"{type(self).__name__} must define table_name")  # noqa: TRY003

        frame = repo.get_timeseries_frame(
            table=table,
            instrument_id=self.instrument_id,
            start=start,
            end=end,
            timezone=timezone,
        )

        if every is not None:
            frame = (
                frame.group_by_dynamic("timestamp", every=every)
                .agg(
                    pl.col("open").first(),
                    pl.col("high").max(),
                    pl.col("low").min(),
                    pl.col("close").last(),
                    pl.col("volume").sum(),
                )
                .sort("timestamp")
            )

        return frame

    def ingest(self, repo: TimeSeriesRepository, frame: pl.DataFrame) -> None:
        """Ingest time series data for this instrument.

        This method prepares the DataFrame by:
        1. Parsing 'ts_event' column into a 'timestamp' column with the UTC timezone.
        2. Adding an 'instrument_id' column.
        3. Calling the repository's ingest method.

        Args:
            repo: The time series repository to ingest into.
            frame: Polars DataFrame containing the data. Must have a 'ts_event' column.

        Raises:
            ValidationError: If instrument_id is not set.
            AttributeError: If table_name is not defined on the model.
        """
        if self.instrument_id is None:
            msg = "Cannot ingest timeseries: instrument_id is not set"
            raise ValidationError(msg)

        table = getattr(type(self), "table_name", None)
        if table is None:
            raise AttributeError(f"{type(self).__name__} must define table_name")  # noqa: TRY003

        # Parse timestamp and convert to UTC
        frame = frame.with_columns(
            pl.col("ts_event").str.to_datetime("%Y-%m-%dT%H:%M:%S%.f%z").dt.convert_time_zone("UTC").alias("timestamp")
        )

        # to the frame add the instrument_id column
        frame = frame.with_columns(instrument_id=pl.lit(self.instrument_id).cast(pl.Int64))

        repo.ingest(table=table, frame=frame)

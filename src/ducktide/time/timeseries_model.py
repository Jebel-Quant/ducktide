"""Time series accessor mixin for domain models.

This module provides a mixin class that can be used by domain models to access
and ingest time series data in a consistent way. It centralizes the code for
retrieving and preparing time series data, eliminating duplication across
domain model classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from ducktide.exceptions import ValidationError

if TYPE_CHECKING:
    from .timeseries_repo import TimeSeriesRepository


class TimeSeriesModel(ABC):
    """Abstract base class for domain models exposing time series data.

    Subclasses must provide an `instrument_id` property and a `table_name`
    class attribute (a ``ClassVar[str]``). This mixin provides
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
            end: Optional inclusive end for filtering; a ``date`` includes the whole day.
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
            time_col = repo.time_col
            frame = (
                frame.group_by_dynamic(time_col, every=every)
                .agg(
                    pl.col("open").first(),
                    pl.col("high").max(),
                    pl.col("low").min(),
                    pl.col("close").last(),
                    pl.col("volume").sum(),
                )
                .sort(time_col)
            )

        return frame

    def ingest(self, repo: TimeSeriesRepository, frame: pl.DataFrame) -> None:
        """Ingest time series data for this instrument.

        This method prepares the DataFrame by:
        1. Parsing 'ts_event' column into a 'timestamp' column with the UTC timezone.
        2. Adding an 'instrument_id' column.
        3. Calling the repository's ingest method.

        Every call is one write to the repository, whose cost barely depends on
        the frame's size; to ingest many instruments at once, use
        :meth:`ingest_many`.

        Args:
            repo: The time series repository to ingest into.
            frame: Polars DataFrame containing the data. Must have a 'ts_event' column.

        Raises:
            ValidationError: If instrument_id is not set.
            AttributeError: If table_name is not defined on the model.
        """
        table, instrument_id = self._ingest_target()
        repo.ingest(
            table=table, frame=_with_timestamp(frame).with_columns(instrument_id=pl.lit(instrument_id).cast(pl.Int64))
        )

    @classmethod
    def ingest_many(cls, repo: TimeSeriesRepository, items: Iterable[tuple[TimeSeriesModel, pl.DataFrame]]) -> None:
        """Ingest data for many instruments with one repository write per table.

        Each ``(model, frame)`` pair is prepared exactly as :meth:`ingest`
        would prepare it, then all frames bound for the same table are combined
        and written in a single ``repo.ingest`` call. The result is the same as
        calling ``model.ingest(repo, frame)`` for each pair in order, including
        which row wins when two pairs carry the same instrument and timestamp.
        It is much faster: a repository write costs about the same for one row
        as for thousands, so a day of bars for 500 instruments takes one write
        instead of 500.

        Args:
            repo: The time series repository to ingest into.
            items: ``(model, frame)`` pairs; models may be of different classes
                and tables. Each frame must have a 'ts_event' column.

        Examples:
            >>> import polars as pl
            >>> from ducktide.example import Foo
            >>> from ducktide.time import TimeSeriesDB
            >>> repo = TimeSeriesDB()
            >>> bar = {"ts_event": ["2025-01-01T09:00:00.000000+0000"], "close": [1.0]}
            >>> Foo.ingest_many(repo, [(Foo(id=i), pl.DataFrame(bar)) for i in range(3)])
            >>> repo.get_timeseries_frame("foo").height
            3

        Raises:
            ValidationError: If a model's instrument_id is not set, or frames
                bound for the same table have different columns. Every pair is
                validated before anything is written.
            AttributeError: If a model does not define table_name.

        Note:
            Tables are written one after another, so a failure writing one table
            leaves the tables before it written.
        """
        # Validate every model first, so a bad pair fails before anything is written.
        pairs_by_table: dict[str, list[tuple[int, pl.DataFrame]]] = {}
        for model, frame in items:
            table, instrument_id = model._ingest_target()
            pairs_by_table.setdefault(table, []).append((instrument_id, frame))

        for table, pairs in pairs_by_table.items():
            columns = pairs[0][1].columns
            for _, frame in pairs[1:]:
                if set(frame.columns) != set(columns):
                    raise ValidationError(  # noqa: TRY003
                        f"frames for table '{table}' have different columns: "
                        f"{sorted(columns)} vs {sorted(frame.columns)}"
                    )

        # Prepare each table's frames as one: parse ts_event once for all of them
        # and build instrument_id in one step. Per-pair Polars calls cost ~0.1 ms
        # each, which for 500 instruments would dwarf the write itself.
        for table, pairs in pairs_by_table.items():
            columns = pairs[0][1].columns
            aligned = [frame if frame.columns == columns else frame.select(columns) for _, frame in pairs]
            combined = pl.concat(aligned, how="vertical_relaxed", rechunk=True)
            counts = pl.DataFrame(
                {
                    "instrument_id": [instrument_id for instrument_id, _ in pairs],
                    "n": [frame.height for _, frame in pairs],
                },
                schema={"instrument_id": pl.Int64, "n": pl.Int64},
            )
            # empty_as_null=False: a pair with an empty frame contributes no row, not a NULL one.
            instrument_ids = counts.select(
                pl.col("instrument_id").repeat_by("n").explode(empty_as_null=False)
            ).to_series()
            repo.ingest(table=table, frame=_with_timestamp(combined).with_columns(instrument_id=instrument_ids))

    def _ingest_target(self) -> tuple[str, int]:
        """Validate the model for ingestion and return where its rows go.

        Returns:
            The model's time series table name and its instrument_id.

        Raises:
            ValidationError: If instrument_id is not set.
            AttributeError: If table_name is not defined on the model.
        """
        instrument_id = self.instrument_id
        if instrument_id is None:
            msg = "Cannot ingest timeseries: instrument_id is not set"
            raise ValidationError(msg)

        table = getattr(type(self), "table_name", None)
        if table is None:
            raise AttributeError(f"{type(self).__name__} must define table_name")  # noqa: TRY003
        return table, instrument_id


def _with_timestamp(frame: pl.DataFrame) -> pl.DataFrame:
    """Add a UTC ``timestamp`` column parsed from the frame's ISO-8601 ``ts_event`` text.

    Args:
        frame: A frame with a 'ts_event' column.

    Returns:
        The frame with the parsed 'timestamp' column appended.
    """
    return frame.with_columns(
        pl.col("ts_event").str.to_datetime("%Y-%m-%dT%H:%M:%S%.f%z").dt.convert_time_zone("UTC").alias("timestamp")
    )

"""Read-side query construction for the time-series interface.

This module defines :class:`TimeSeriesQueryMixin`, which builds parameterized,
time-ordered ``SELECT`` statements from optional instrument/time-range filters
and returns them as Polars DataFrames.
"""

from datetime import date
from typing import Any

import polars as pl
from loguru import logger

from ..exceptions import QueryError
from ..utils import sql
from ._base import TimeSeriesBase


class TimeSeriesQueryMixin(TimeSeriesBase):
    """Time-ordered querying of time-series tables."""

    def get_timeseries_frame(
        self,
        table: str,
        instrument_id: int | None = None,
        start: date | None = None,
        end: date | None = None,
        timezone: str | None = None,
    ) -> pl.DataFrame:
        """Return a time-ordered Polars DataFrame from a time series table.

        Retrieves time series data with optional filtering by instrument ID and
        time range. The result is always sorted by timestamp in ascending order.

        Args:
            table: Name of the table to read. May be schema-qualified as "schema.table".
            instrument_id: Optional filter to return rows for a specific instrument
                (e.g., future_id or contract_id).
            start: Optional inclusive lower bound for the timestamp column.
                All rows with timestamp >= start will be included.
            end: Optional inclusive upper bound for the timestamp column.
                All rows with timestamp <= end will be included.
            timezone: Optional target timezone for the timestamp column.
                If provided, naive timestamps will be converted to this timezone.

        Returns:
            pl.DataFrame: A Polars DataFrame sorted by timestamp in ascending order.
                If the table does not exist, an empty DataFrame is returned
                (a missing table means "no data yet", not an error).

        Raises:
            ValidationError: If the table name is not a valid SQL identifier.
            QueryError: If the query fails for any reason other than a missing
                table (e.g., missing time column, type errors, corrupted data).

        Examples:
            >>> from jqr.database.time import TimeSeriesDB
            >>> from datetime import date
            >>>
            >>> ts_db = TimeSeriesDB()
            >>>
            >>> # Get all data for a specific instrument
            >>> df = ts_db.get_timeseries_frame("future", instrument_id=100)
            >>>
            >>> # Get data within a date range
            >>> df = ts_db.get_timeseries_frame(
            ...     "future",
            ...     instrument_id=100,
            ...     start=date(2025, 1, 1),
            ...     end=date(2025, 12, 31)
            ... )
            >>>
            >>> # Get all data from a table
            >>> df = ts_db.get_timeseries_frame("contract")

        Note:
            Only a missing table is treated as "no data" and yields an empty
            DataFrame. All other failures raise QueryError so that callers can
            distinguish genuine errors from absent data. Pipelines that prefer
            graceful degradation should catch QueryError explicitly.
        """
        self._validate_table_name(table)
        if table not in self.tables():
            return pl.DataFrame()

        try:
            query, params = self._build_query(table, instrument_id, start, end)
            frame = self.con.execute(query, params).pl().sort(self.time_col)

            if timezone is not None and frame[self.time_col].dtype.is_temporal():
                # Polars: convert timestamp to target timezone
                # Only attempt conversion if the column is a Datetime type
                # If it's just a Date, we might want to cast it to Datetime first or skip
                # Most financial data with timezones will be Datetime.
                # dt.convert_time_zone requires Datetime.
                if isinstance(frame[self.time_col].dtype, pl.Datetime):
                    frame = frame.with_columns(pl.col(self.time_col).dt.convert_time_zone(timezone))
                elif isinstance(frame[self.time_col].dtype, pl.Date):
                    # For Date, conversion doesn't make much sense without time,
                    # but we should at least not crash.
                    # Optionally cast to datetime then convert?
                    # Usually, if user asks for timezone, they expect Datetime.
                    pass

        except Exception as exc:
            # Anything beyond a missing table is a real failure: surface it as a
            # typed error instead of masking it with an empty DataFrame.
            logger.error(f"Failed to query timeseries from '{table}': {exc}")
            raise QueryError(f"Failed to query timeseries from '{table}': {exc}") from exc  # noqa: TRY003
        else:
            return frame

    def _build_query(
        self,
        table: str,
        instrument_id: int | None,
        start: date | None,
        end: date | None,
    ) -> tuple[str, list[Any]]:
        """Build a SQL SELECT query with optional filters.

        Args:
            table: The table name to query.
            instrument_id: Optional instrument ID filter.
            start: Optional start date filter (inclusive).
            end: Optional end date filter (inclusive).

        Returns:
            A tuple of (SQL query string, list of parameters).
        """
        conditions: list[str] = []
        params: list[Any] = []

        if instrument_id is not None:
            conditions.append("instrument_id = ?")
            params.append(instrument_id)

        if start is not None:
            conditions.append(f"{self.time_col} >= ?")
            params.append(start)

        if end is not None:
            conditions.append(f"{self.time_col} <= ?")
            params.append(end)

        where = " AND ".join(conditions)
        # For read queries, keep identifiers unquoted to match test expectations
        # and produce simpler SQL strings (e.g., FROM schema.table).
        #
        # table is validated by _validate_table_name (matched against
        # _IDENTIFIER_RE) before this method is called, and time_col is the
        # configured column name (code, not user data). All filter values
        # (instrument_id, start, end) are bound via params.
        query = sql.select_ordered(table, where=where, order_by=f"{self.time_col} ASC")
        return query, params

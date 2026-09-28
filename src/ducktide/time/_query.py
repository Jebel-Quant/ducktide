"""Read-side query construction for the time-series interface.

This module defines :class:`TimeSeriesQueryMixin`, which builds parameterized,
time-ordered ``SELECT`` statements from optional instrument/time-range filters
and returns them as Polars DataFrames.
"""

from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

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
                A ``datetime`` includes all rows with timestamp <= end. A
                ``date`` includes the whole day: all rows with timestamp
                before the following midnight.
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
            >>> from ducktide.time import TimeSeriesDB
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
        if not self.has_table(table):
            return pl.DataFrame()

        try:
            query, params = self._build_query(table, instrument_id, start, end)
            # The query's ORDER BY already sorts the rows; flag the column as
            # sorted for Polars (as .sort() would) rather than sorting again.
            frame = self.con.execute(query, params).pl().set_sorted(self.time_col)
            frame = self._apply_timezone(frame, timezone)

        except Exception as exc:
            # Anything beyond a missing table is a real failure: surface it as a
            # typed error instead of masking it with an empty DataFrame.
            raise QueryError(f"Failed to query timeseries from '{table}': {exc}") from exc  # noqa: TRY003
        else:
            return frame

    def _apply_timezone(self, frame: pl.DataFrame, timezone: str | None) -> pl.DataFrame:
        """Convert the timestamp column to a target timezone when applicable.

        Args:
            frame: The queried DataFrame.
            timezone: Optional target timezone. If None, the frame is returned
                unchanged.

        Returns:
            The frame with its timestamp column converted, or the original frame
            when no conversion applies.

        Note:
            Conversion only happens for a ``Datetime`` column, since
            ``dt.convert_time_zone`` requires one. A ``Date`` column is left
            unchanged rather than raising; most timezone-aware financial data is
            ``Datetime``.
        """
        if timezone is None or not frame[self.time_col].dtype.is_temporal():
            return frame
        if isinstance(frame[self.time_col].dtype, pl.Datetime):
            return frame.with_columns(pl.col(self.time_col).dt.convert_time_zone(timezone))
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

        if isinstance(end, datetime):
            conditions.append(f"{self.time_col} <= ?")
            params.append(end)
        elif end is not None:
            # A date means the whole day; "<= date" would stop at its midnight
            # and drop every intraday row on the end day.
            conditions.append(f"{self.time_col} < ?")
            params.append(end + timedelta(days=1))

        where = " AND ".join(conditions)
        # For read queries, keep identifiers unquoted to match test expectations
        # and produce simpler SQL strings (e.g., FROM schema.table).
        #
        # table is validated by _validate_table_name (matched against
        # _IDENTIFIER_RE) before this method is called, and time_col is the
        # configured column name (code, not user data). All filter values
        # (instrument_id, start, end) are bound via params.
        # NULLS FIRST matches Polars' sort order, which the sorted flag set on
        # the result assumes.
        query = sql.select_ordered(table, where=where, order_by=f"{self.time_col} ASC NULLS FIRST")
        return query, params

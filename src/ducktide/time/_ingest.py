"""Ingestion (append-only) for the time-series interface.

This module defines :class:`TimeSeriesIngestMixin`, which creates tables on
first write and appends only rows newer than the current maximum timestamp
(per-instrument when an ``instrument_id`` column is present, else globally),
avoiding duplicate observations.
"""

import logging

import polars as pl

from ..utils import sql
from ._base import TimeSeriesBase

logger = logging.getLogger(__name__)


class TimeSeriesIngestMixin(TimeSeriesBase):
    """Table creation and append-only ingestion for time-series data."""

    def ingest(self, table: str, frame: pl.DataFrame) -> None:
        """Ingest time series data from a Polars DataFrame into a table.

        Automatically creates the table if it doesn't exist, using the schema
        inferred from the DataFrame. When appending to an existing table, only
        new rows (timestamp strictly greater than existing max timestamp) are
        inserted to avoid duplicates.

        Args:
            table: Name of the destination table. May be schema-qualified as
                "schema.table". If a schema is specified and doesn't exist, it
                will be created automatically.
            frame: Polars DataFrame containing the data to ingest. Must include
                a timestamp column (default name: "timestamp"). The DataFrame
                schema will be used to create the table if it doesn't exist.

        Examples:
            >>> import polars as pl
            >>> from ducktide.time import TimeSeriesDB
            >>> from datetime import datetime
            >>>
            >>> ts_db = TimeSeriesDB()
            >>>
            >>> # Create sample OHLCV data
            >>> df = pl.DataFrame({
            ...     'timestamp': [datetime(2025, 1, 1, 9, 0)],
            ...     'instrument_id': [100],
            ...     'open': [100.0],
            ...     'high': [105.0],
            ...     'low': [99.0],
            ...     'close': [103.0],
            ...     'volume': [1000]
            ... })
            >>>
            >>> # Ingest into 'future' table
            >>> ts_db.ingest("future", df)
            >>>
            >>> # Ingest into schema-qualified table
            >>> ts_db.ingest("market_data.futures", df)

        Raises:
            ValidationError: If the table name is not a valid SQL identifier.

        Note:
            - The function uses the timestamp column specified during TimeSeriesDB
              initialization (default: "timestamp").
            - When appending, only rows with timestamps strictly greater than the
              current maximum are inserted, preventing duplicate data.
            - Table creation is automatic and uses DuckDB's schema inference from
              the Polars DataFrame.
        """
        self._validate_table_name(table)
        self._ensure_schema(table)

        # Create table if missing, otherwise append only new rows.
        if not self.has_table(table):
            self._create_table_from_frame(table, frame)
            return

        if "instrument_id" in frame.columns:
            self._append_new_per_instrument(table, frame)
        else:
            self._append_new_global(table, frame)

    def _ensure_schema(self, table: str) -> None:
        """Create the table's schema if the name is schema-qualified.

        Args:
            table: The (possibly schema-qualified) destination table name.

        Note:
            ``table`` is validated by :meth:`_validate_table_name`, and the
            schema part is further stripped of quote characters by
            ``_quote_unquoted``; not user data.
        """
        if "." in table:
            schema, _ = table.split(".", 1)
            self.con.execute(sql.create_schema_if_not_exists(self._quote_unquoted(schema)))

    def _create_table_from_frame(self, table: str, frame: pl.DataFrame) -> None:
        """Create a new table from a Polars DataFrame using DuckDB inference.

        Args:
            table: The destination table name.
            frame: The DataFrame whose schema and rows seed the new table.

        Note:
            ``quoted_table`` is produced by ``_quote_identifier``; data rows come
            from the registered ``temp_ingest`` relation, not string
            interpolation.
        """
        self.con.register("temp_ingest", frame)
        quoted_table = self._quote_identifier(table)
        self.con.execute(sql.create_table_as(quoted_table, sql.select_all("temp_ingest")))
        self.con.unregister("temp_ingest")

    def _append_new_per_instrument(self, table: str, frame: pl.DataFrame) -> None:
        """Append rows newer than each instrument's current max timestamp.

        Uses the per-instrument max timestamp from the database to filter the
        incoming frame before ingestion, avoiding an expensive
        ``WHERE NOT EXISTS`` subquery for every row.

        Args:
            table: The destination table name.
            frame: The DataFrame to append (must contain ``instrument_id``).
        """
        logger.info("Ingesting %d rows into '%s'...", len(frame), table)

        # quoted_table is produced by _quote_identifier from a name already
        # validated by _validate_table_name, and time_col is the configured
        # column name; no user data is interpolated.
        quoted_table = self._quote_identifier(table)
        max_ts_df = self.con.execute(sql.select_max_per_instrument(quoted_table, self.time_col)).pl()
        new_frame = self._filter_new_per_instrument(frame, max_ts_df)

        if new_frame.height > 0:
            logger.info("Appending %d new rows to '%s'...", len(new_frame), table)
            self._append(table, new_frame)
        else:
            logger.info("No new rows to append to '%s'.", table)

    def _filter_new_per_instrument(self, frame: pl.DataFrame, max_ts_df: pl.DataFrame) -> pl.DataFrame:
        """Return only the rows newer than the existing per-instrument maxima.

        Args:
            frame: The incoming DataFrame to filter.
            max_ts_df: Existing max timestamps per instrument (column ``max_ts``).

        Returns:
            The subset of ``frame`` with timestamps strictly greater than the
            existing maximum (or with no existing data for that instrument).
        """
        if max_ts_df.height == 0:
            return frame

        # Join and filter in Polars (usually faster than complex SQL anti-joins
        # in this context). Ensure time zones match for comparison if we have
        # a timezone-aware Datetime column.
        dtype = frame.schema[self.time_col]
        if isinstance(dtype, pl.Datetime) and dtype.time_zone:
            max_ts_df = max_ts_df.with_columns(pl.col("max_ts").dt.convert_time_zone(dtype.time_zone))

        return (
            frame.join(max_ts_df, on="instrument_id", how="left")
            .filter((pl.col("max_ts").is_null()) | (pl.col(self.time_col) > pl.col("max_ts")))
            .drop("max_ts")
        )

    def _append_new_global(self, table: str, frame: pl.DataFrame) -> None:
        """Append rows newer than the table's single global max timestamp.

        Used when the frame has no ``instrument_id`` column.

        Args:
            table: The destination table name.
            frame: The DataFrame to append.

        Note:
            ``quoted_table`` is ``_quote_identifier`` output from a validated
            name and ``time_col`` is the configured column name; the
            ``'1970-01-01'`` epoch is a fixed literal.
        """
        quoted_table = self._quote_identifier(table)
        result = self.con.execute(sql.select_coalesce_max(quoted_table, self.time_col)).fetchone()
        max_ts = result[0] if result else "1970-01-01"
        new = frame.filter(pl.col(f"{self.time_col}") > max_ts)
        if new.height:
            self._append(table, new)

    def _append(self, table: str, df: pl.DataFrame) -> None:
        """Append rows from a DataFrame to an existing table.

        Args:
            table: The destination table name.
            df: The Polars DataFrame containing rows to append.
        """
        quoted_table = self._quote_identifier(table)
        self.con.register("temp", df)
        # quoted_table is _quote_identifier output from a validated name; data
        # rows come from the registered temp relation, not string interpolation.
        self.con.execute(sql.insert_from_query(quoted_table, sql.select_all("temp")))
        self.con.unregister("temp")

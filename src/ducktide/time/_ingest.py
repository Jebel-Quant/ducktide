"""Ingestion (append-only) for the time-series interface.

This module defines :class:`TimeSeriesIngestMixin`, which creates tables on
first write and appends only rows newer than the current maximum timestamp
(per-instrument when an ``instrument_id`` column is present, else globally),
avoiding duplicate observations.
"""

import polars as pl
from loguru import logger

from ..utils import sql
from ._base import TimeSeriesBase


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
            >>> from jqr.database.time import TimeSeriesDB
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

        # Ensure schema exists when provided. table is validated by
        # _validate_table_name above, and the schema part is further stripped of
        # quote characters by _quote_unquoted; not user data.
        if "." in table:
            schema, _ = table.split(".", 1)
            self.con.execute(sql.create_schema_if_not_exists(self._quote_unquoted(schema)))

        # Create table if missing
        if not self.has_table(table):
            # register and create table from Polars df. quoted_table is produced
            # by _quote_identifier; data rows come from the registered
            # temp_ingest relation, not string interpolation.
            self.con.register("temp_ingest", frame)
            quoted_table = self._quote_identifier(table)
            self.con.execute(sql.create_table_as(quoted_table, sql.select_all("temp_ingest")))
            self.con.unregister("temp_ingest")
            return

        # Table exists: append only new rows
        quoted_table = self._quote_identifier(table)

        if "instrument_id" in frame.columns:
            # Optimized approach: Get max timestamp per instrument from the database
            # to filter the incoming frame before ingestion.
            # This avoids the expensive WHERE NOT EXISTS subquery for every row.
            logger.info(f"Ingesting {len(frame)} rows into '{table}'...")

            # 1. Get existing max timestamps per instrument. quoted_table is
            # produced by _quote_identifier from a name already validated by
            # _validate_table_name, and time_col is the configured column name;
            # no user data is interpolated.
            max_ts_df = self.con.execute(sql.select_max_per_instrument(quoted_table, self.time_col)).pl()

            if max_ts_df.height > 0:
                # 2. Join and filter in Polars (usually faster than complex SQL anti-joins in this context)
                # Ensure time zones match for comparison if we have Datetime
                dtype = frame.schema[self.time_col]
                if isinstance(dtype, pl.Datetime) and dtype.time_zone:
                    df_tz = dtype.time_zone
                    max_ts_df = max_ts_df.with_columns(pl.col("max_ts").dt.convert_time_zone(df_tz))

                new_frame = frame.join(max_ts_df, on="instrument_id", how="left")
                new_frame = new_frame.filter(
                    (pl.col("max_ts").is_null()) | (pl.col(self.time_col) > pl.col("max_ts"))
                ).drop("max_ts")
            else:
                new_frame = frame

            if new_frame.height > 0:
                logger.info(f"Appending {len(new_frame)} new rows to '{table}'...")
                self._append(table, new_frame)
            else:
                logger.info(f"No new rows to append to '{table}'.")
        else:
            # No instrument_id: global max timestamp. quoted_table is
            # _quote_identifier output from a validated name and time_col is the
            # configured column name; the '1970-01-01' epoch is a fixed literal.
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

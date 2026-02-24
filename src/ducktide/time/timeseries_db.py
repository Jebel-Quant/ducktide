"""Time series database for high-volume append-heavy numerical data.

This module provides a separate database layer optimized for time series data,
which is fundamentally different from entity data.

Key Differences from ORM Database:
- **Time series data**: Raw numerical observations, high-volume, append-heavy
- **Entity data (ORM)**: Static metadata with identity, relationships, infrequent updates

Architecture:
    - TimeSeriesDB: Optimized for time series ingestion and querying
    - Database (ORM): Optimized for entity relationships and metadata

The separation allows:
1. Different optimization strategies for each data type
2. Independent scaling of time series vs. metadata storage
3. Clean separation of concerns
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from loguru import logger

from jqr.database.exceptions import QueryError
from jqr.database.utils.path_validation import escape_path_for_sql, validate_file_path


@dataclass
class TimeSeriesDB:
    """Database for time-series data (read & utility layer).

    This class provides optimized operations for time series data, which is
    fundamentally different from entity data. Time series data is:
    - High-volume numerical observations
    - Append-heavy with frequent updates
    - Queried by time ranges and instrument IDs
    - Not entities with identity or relationships

    This implements the TimeSeriesRepository protocol for use with domain models.

    Example:
        # Separate databases for different concerns
        # metadata_db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
        # ts_db = TimeSeriesDB()
        # ts_db.ingest(Foo.table_name, price_data)
        # df = foo.get_timeseries_frame(ts_db)
    """

    def __init__(self, path: str | Path | None = None, time_col: str = "timestamp", read_only: bool = False):
        """Initialize a DuckDB-backed time series database.

        Args:
            path: Optional filesystem path to a DuckDB database file. If None,
                an in-memory database is created (":memory:").
            time_col: Name of the column containing time information (default: "timestamp").
            read_only: If True, open the database in read-only mode. This prevents
                all write operations and allows multiple processes to safely read from
                the same file without locks.
        """
        self.con = duckdb.connect(path or ":memory:", read_only=read_only)
        self.time_col = time_col
        self.read_only = read_only

    # ------------------
    # Utility operations
    # ------------------
    def query(self, sql: str, *args: Any) -> pl.DataFrame:
        """Execute an arbitrary SQL query and return the result as a DataFrame.

        Args:
            sql: The SQL string to execute. May include placeholders supported by DuckDB.
            *args: Positional parameters to bind to the SQL statement.

        Returns:
            A Polars DataFrame containing the query result.
        """
        return self.con.execute(sql, args).pl()

    def tables(self) -> list[str]:
        """Return tables (schema.table or table)."""
        rows = self.con.execute("SHOW ALL TABLES").fetchall()
        out: list[str] = []
        for _, schema, name, *_ in rows:  # catalog, schema, name, type, ...
            out.append(name if schema == "main" else f"{schema}.{name}")
        return sorted(out)

    def has_table(self, table: str) -> bool:
        """Return True if the given table exists in the database.

        Args:
            table: A table name, optionally schema-qualified as "schema.table".

        Returns:
            True if the table exists, False otherwise.
        """
        return table in self.tables()

    # ---------------------
    # Data access
    # ---------------------
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
                If the table does not exist or an error occurs, an empty DataFrame
                is returned.

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
            This method gracefully handles errors by returning an empty DataFrame
            rather than raising exceptions. This is intentional to support robust
            data pipelines that can continue even when data is missing.
        """
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
            # Graceful error handling: on any error (SQL, invalid params, or
            # internal build errors), return an empty DataFrame.
            logger.warning(f"Failed to query timeseries from '{table}': {exc}")
            return pl.DataFrame()
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

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # For read queries, keep identifiers unquoted to match test expectations
        # and produce simpler SQL strings (e.g., FROM schema.table).
        table_ref = table

        query = f"SELECT * FROM {table_ref} {where} ORDER BY {self.time_col} ASC"  # nosec B608  # noqa: S608
        return query, params

    def _quote_identifier(self, ident: str) -> str:
        """Quote a table or schema identifier for safe SQL use.

        Args:
            ident: The identifier to quote, optionally schema-qualified (e.g., "schema.table").

        Returns:
            A quoted identifier string safe for use in SQL statements.
        """
        # duckdb compatible quoting
        if "." in ident:
            schema, name = ident.split(".", 1)
            schema_clean = schema.replace('"', "")
            name_clean = name.replace('"', "")
            return f'"{schema_clean}"."{name_clean}"'
        ident_clean = ident.replace('"', "")
        return f'"{ident_clean}"'

    # ---------------------
    # Ingestion
    # ---------------------
    def _quote_unquoted(self, ident: str) -> str:
        """Sanitize an identifier by removing any embedded quotes.

        Args:
            ident: The identifier to sanitize.

        Returns:
            The identifier with all double-quote characters removed.
        """
        return ident.replace('"', "")

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

        Note:
            - The function uses the timestamp column specified during TimeSeriesDB
              initialization (default: "timestamp").
            - When appending, only rows with timestamps strictly greater than the
              current maximum are inserted, preventing duplicate data.
            - Table creation is automatic and uses DuckDB's schema inference from
              the Polars DataFrame.
        """
        # Ensure schema exists when provided
        if "." in table:
            schema, _ = table.split(".", 1)
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {self._quote_unquoted(schema)}")  # nosec B608

        # Create table if missing
        if not self.has_table(table):
            # register and create table from Polars df
            self.con.register("temp_ingest", frame)
            quoted_table = self._quote_identifier(table)
            self.con.execute(f"CREATE TABLE {quoted_table} AS SELECT * FROM temp_ingest")  # nosec B608  # noqa: S608
            self.con.unregister("temp_ingest")
            return

        # Table exists: append only new rows
        quoted_table = self._quote_identifier(table)

        if "instrument_id" in frame.columns:
            # Optimized approach: Get max timestamp per instrument from the database
            # to filter the incoming frame before ingestion.
            # This avoids the expensive WHERE NOT EXISTS subquery for every row.
            logger.info(f"Ingesting {len(frame)} rows into '{table}'...")

            # 1. Get existing max timestamps per instrument
            sql = f"""
                SELECT instrument_id, MAX({self.time_col}) as max_ts
                FROM {quoted_table}
                GROUP BY instrument_id
            """  # nosec B608  # noqa: S608
            max_ts_df = self.con.execute(sql).pl()

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
            # No instrument_id: global max timestamp
            result = self.con.execute(
                f"SELECT COALESCE(MAX({self.time_col}),'1970-01-01') FROM {quoted_table}"  # nosec B608  # noqa: S608
            ).fetchone()
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
        self.con.execute(f"INSERT INTO {quoted_table} SELECT * FROM temp")  # nosec B608  # noqa: S608
        self.con.unregister("temp")

    def import_csv(self, csv_path: str | Path, table: str) -> None:
        """Create or replace a table from a CSV file.

        Args:
            csv_path: Path to the CSV file to import.
            table: Name of the destination table.

        Raises:
            FileNotFoundError: If the CSV file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(csv_path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        self.con.execute(f"DROP TABLE IF EXISTS {table_q}")  # nosec B608
        self.con.execute(
            f"""
            CREATE TABLE {table_q} AS
            SELECT * FROM read_csv_auto('{escaped_path}')
            """  # nosec B608  # noqa: S608
        )

    def export_csv(self, table: str, csv_path: str | Path) -> None:
        """Export a table to a CSV file.

        Args:
            table: Name of the table to export.
            csv_path: Path to the output CSV file.

        Raises:
            QueryError: If the table doesn't exist.
            ValidationError: If the path is invalid.
        """
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")  # noqa: TRY003

        validated_path = validate_file_path(csv_path)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        self.con.execute(f"COPY (SELECT * FROM {table_q}) TO '{escaped_path}' (HEADER, DELIMITER ',')")  # nosec B608  # noqa: S608

    def import_parquet(self, pq_path: str | Path, table: str) -> None:
        """Create or replace a table from a Parquet file.

        Args:
            pq_path: Path to the Parquet file to import.
            table: Name of the destination table.

        Raises:
            FileNotFoundError: If the Parquet file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(pq_path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        self.con.execute(f"DROP TABLE IF EXISTS {table_q}")  # nosec B608
        self.con.execute(
            f"""
            CREATE TABLE {table_q} AS
            SELECT * FROM read_parquet('{escaped_path}')
            """  # nosec B608  # noqa: S608
        )

    def export_parquet(self, table: str, pq_path: str | Path) -> None:
        """Export a table to a Parquet file.

        Args:
            table: Name of the table to export.
            pq_path: Path to the output Parquet file.

        Raises:
            QueryError: If the table doesn't exist.
            ValidationError: If the path is invalid.
        """
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")  # noqa: TRY003

        validated_path = validate_file_path(pq_path)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        self.con.execute(
            f"""
            COPY (SELECT * FROM {table_q})
            TO '{escaped_path}' (FORMAT 'PARQUET')
            """  # nosec B608  # noqa: S608
        )

    def __enter__(self) -> "TimeSeriesDB":
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit the runtime context related to this object."""
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self.con.close()

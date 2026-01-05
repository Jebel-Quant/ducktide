"""Time series database for high-volume append-heavy numerical data.

This module provides a separate database layer optimized for time series data,
which is fundamentally different from entity data (Publisher, Future, Contract).

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

from jqr.database.exceptions import QueryError


@dataclass
class TimeSeriesDB:
    """Database for time-series data (read & utility layer).

    This class provides optimized operations for time series data, which is
    fundamentally different from entity data. Time series data is:
    - High-volume numerical observations
    - Append-heavy with frequent updates
    - Queried by time ranges and instrument IDs
    - Not entities with identity or relationships

    This implements the TimeSeriesRepository protocol for use with domain models
    like Future and Contract.

    Example:
        # Separate databases for different concerns
        metadata_db = Database()  # ORM for entities
        ts_db = TimeSeriesDB()    # Time series data

        # Create entity
        future = Future(future_id=100, name="E-mini S&P 500", ticker="ES")
        metadata_db.futures.insert(future)

        # Ingest time series data
        ts_db.ingest("future", price_data)

        # Query time series through entity
        df = future.get_timeseries_frame(ts_db)
    """

    def __init__(self, path: str | Path | None = None, time_col="timestamp"):
        """Initialize a DuckDB-backed time series database.

        Args:
            path: Optional filesystem path to a DuckDB database file. If None,
                an in-memory database is created (":memory:").
            time_col: Name of the column containing time information (default: "timestamp").
        """
        self.con = duckdb.connect(path or ":memory:")
        self.time_col = time_col

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
    ) -> pl.DataFrame:
        """Return a time-ordered Polars DataFrame from a table.

        Args:
            table: Name of the table to read. May be schema-qualified as "schema.table".
            instrument_id: Optional filter to return rows for a specific instrument.
            start: Optional inclusive lower bound for the ``timestamp`` column.
            end: Optional inclusive upper bound for the ``timestamp`` column.

        Returns:
            A Polars DataFrame sorted by ``timestamp`` ascending. If the table
            does not exist, an empty DataFrame is returned.
        """
        if table not in self.tables():
            return pl.DataFrame()

        try:
            query, params = self._build_query(table, instrument_id, start, end)
            return self.con.execute(query, params).pl().sort(self.time_col)
        except Exception:
            # Graceful error handling: on any error (SQL, invalid params, or
            # internal build errors), return an empty DataFrame.
            return pl.DataFrame()

    def _build_query(
        self,
        table: str,
        instrument_id: int | None,
        start: date | None,
        end: date | None,
    ) -> tuple[str, list[Any]]:
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

        query = f"SELECT * FROM {table_ref} {where} ORDER BY {self.time_col} ASC"
        return query, params

    def _quote_identifier(self, ident: str) -> str:
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
        # Return safe unquoted identifier (avoid double quotes in input)
        return ident.replace('"', "")

    def ingest(self, table: str, frame: pl.DataFrame) -> None:
        """Ingest data from a Polars DataFrame into `table`.

        Creates the table when missing. When appending, only new rows are
        inserted (timestamp strictly greater than existing max timestamp).
        """
        # Ensure schema exists when provided
        if "." in table:
            schema, _ = table.split(".", 1)
            self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {self._quote_unquoted(schema)}")

        # Create table if missing
        if not self.has_table(table):
            # register and create table from Polars df
            self.con.register("temp_ingest", frame)
            quoted_table = self._quote_identifier(table)
            self.con.execute(f"CREATE TABLE {quoted_table} AS SELECT * FROM temp_ingest")
            self.con.unregister("temp_ingest")
            return

        # Table exists: append only new rows
        quoted_table = self._quote_identifier(table)

        if "instrument_id" in frame.columns:
            # Vectorized single-SQL approach: insert rows from temp where
            # timestamp > coalesce(max(timestamp) for that instrument)
            self.con.register("temp_ingest", frame)
            insert_sql = f"""
                INSERT INTO {quoted_table}
                SELECT * FROM temp_ingest t
                WHERE NOT EXISTS (
                SELECT 1 FROM {quoted_table} x
                WHERE x.instrument_id = t.instrument_id AND x.{self.time_col} >= t.{self.time_col}
                )
            """
            self.con.execute(insert_sql)
            self.con.unregister("temp_ingest")
        else:
            # No instrument_id: global max timestamp
            max_ts = self.con.execute(
                f"SELECT COALESCE(MAX({self.time_col}),'1970-01-01') FROM {quoted_table}"
            ).fetchone()[0]
            new = frame.filter(pl.col(f"{self.time_col}") > max_ts)
            if new.height:
                self._append(table, new)

    def _append(self, table: str, df: pl.DataFrame):
        quoted_table = self._quote_identifier(table)
        self.con.register("temp", df)
        self.con.execute(f"INSERT INTO {quoted_table} SELECT * FROM temp")
        self.con.unregister("temp")

    def import_csv(self, csv_path: str, table: str) -> None:
        """Create or replace a table from a CSV file."""
        table_q = self._quote_identifier(table)
        self.con.execute(f"DROP TABLE IF EXISTS {table_q}")
        self.con.execute(
            f"""
            CREATE TABLE {table_q} AS
            SELECT * FROM read_csv_auto('{csv_path}')
            """
        )

    def export_csv(self, table: str, csv_path: str) -> None:
        """Export a table to a CSV file."""
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")

        table_q = self._quote_identifier(table)
        self.con.execute(f"COPY (SELECT * FROM {table_q}) TO '{csv_path}' (HEADER, DELIMITER ',')")

    def import_parquet(self, pq_path: str, table: str) -> None:
        """Create or replace a table from a Parquet file."""
        table_q = self._quote_identifier(table)
        self.con.execute(f"DROP TABLE IF EXISTS {table_q}")
        self.con.execute(
            f"""
            CREATE TABLE {table_q} AS
            SELECT * FROM read_parquet('{pq_path}')
            """
        )

    def export_parquet(self, table: str, pq_path: str) -> None:
        """Export a table to a Parquet file."""
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")

        table_q = self._quote_identifier(table)
        self.con.execute(
            f"""
            COPY (SELECT * FROM {table_q})
            TO '{pq_path}' (FORMAT 'PARQUET')
            """
        )

    def close(self):
        """Close the database connection."""
        self.con.close()

"""Base state and shared helpers for :class:`~ducktide.time.TimeSeriesDB`.

This module defines :class:`TimeSeriesBase`, which owns the DuckDB connection
and the configured timestamp column, plus the small validation/quoting helpers
and catalog lookups shared by every time-series mixin (query, ingest and
import/export). The concrete :class:`~ducktide.time.TimeSeriesDB` composes
this base with those mixins.
"""

from pathlib import Path
from typing import Any, Self

import duckdb
import polars as pl

from ..utils import sql


class TimeSeriesBase:
    """Connection ownership and shared helpers for the time-series mixins.

    Holds the active DuckDB connection and the configured timestamp column, and
    provides identifier validation/quoting plus catalog lookups used across the
    query, ingest and import/export mixins.

    Attributes:
        con: Active DuckDB connection.
        time_col: Name of the timestamp column.
        read_only: Whether the connection was opened read-only.
    """

    def __init__(self, path: str | Path | None = None, time_col: str = "timestamp", read_only: bool = False) -> None:
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
        # ``time_col`` is interpolated directly into SQL (identifiers cannot be
        # bound as parameters), so validate it at the object boundary — this is
        # the sole user-supplied identifier reaching the SQL builders.
        self.time_col = sql.validate_identifier(time_col)
        self.read_only = read_only

    # ------------------
    # Utility operations
    # ------------------
    def _validate_table_name(self, table: str) -> str:
        """Validate a table name, optionally schema-qualified as "schema.table".

        Args:
            table: The table name to validate.

        Returns:
            The validated table name, unchanged.

        Raises:
            ValidationError: If the table or schema name is not a valid SQL identifier.
        """
        # Single audited validator lives in the SQL-composition module so the
        # "caller validated it" contract is enforced next to the interpolation.
        return sql.validate_identifier(table, kind="table name")

    def _quote_identifier(self, ident: str) -> str:
        """Quote a table or schema identifier for safe SQL use.

        Args:
            ident: The identifier to quote, optionally schema-qualified (e.g., "schema.table").

        Returns:
            A quoted identifier string safe for use in SQL statements.
        """
        # duckdb-compatible quoting; stripping embedded quotes makes the result
        # injection-safe by construction (validation is enforced separately by
        # :meth:`_validate_table_name` before any name reaches here).
        if "." in ident:
            schema, name = ident.split(".", 1)
            schema_clean = schema.replace('"', "")
            name_clean = name.replace('"', "")
            return f'"{schema_clean}"."{name_clean}"'
        ident_clean = ident.replace('"', "")
        return f'"{ident_clean}"'

    def _quote_unquoted(self, ident: str) -> str:
        """Sanitize an identifier by removing any embedded quotes.

        Args:
            ident: The identifier to sanitize.

        Returns:
            The identifier with all double-quote characters removed.
        """
        return ident.replace('"', "")

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
        # A targeted catalog lookup: listing every table (``SHOW ALL TABLES``)
        # costs more than the typical point query it guards.
        schema, _, name = table.rpartition(".")
        return self.con.execute(sql.TABLE_EXISTS, [schema or "main", name]).fetchone() is not None

    def __enter__(self) -> Self:
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit the runtime context related to this object."""
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self.con.close()

"""Generic database connection management.

This module provides the base DB class for managing DuckDB connections,
executing raw queries, and supporting context manager patterns.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb


class DB:
    """Generic DuckDB database wrapper.

    Provides basic connection management, query execution, and context manager
    support. This class is intended to be used as a base for more specialized
    database implementations and does not contain any model or table specific logic.
    """

    def __init__(self, tables_map: dict[str, type], db_path: str = ":memory:", read_only: bool = False):
        """Initialize the DB with either in-memory or persistent storage.

        :param tables_map: Mapping of attribute names to table classes
            to be initialized automatically.
        :param db_path: Path to the database file, or ":memory:" for in-memory.
        :param read_only: If True, open the database in read-only mode.
        """
        self.db_path = db_path
        self.read_only = read_only
        self.connection = duckdb.connect(self.db_path, read_only=read_only)
        self._model_to_table: dict[type, Any] = {}

        self._initialize_tables(tables_map)

    def insert(self, *objs: Any):
        """Insert one or more objects into their respective tables.

        Parameters
        ----------
        *objs:
            Objects to be inserted.
        """
        for obj in objs:
            table = self._model_to_table.get(type(obj))
            if table is None:
                raise TypeError(f"Invalid object type: {type(obj)}.")
            table.insert(obj)

    def _initialize_tables(self, tables_map: dict[str, type]):
        """Initialize table interfaces as attributes of this database instance."""
        for attr, table_cls in tables_map.items():
            table = table_cls(self.connection, read_only=self.read_only)
            setattr(self, attr, table)

            # Map domain model and ORM model to the table instance for insert()
            self._model_to_table[table.model_class] = table
            if hasattr(table.model_class, "_domain_model") and table.model_class._domain_model:
                self._model_to_table[table.model_class._domain_model] = table

    def execute_query(self, query: str, params: Sequence | None = None):
        """Execute a SQL query against the underlying connection.

        Parameters
        ----------
        query:
            SQL query string with optional placeholders.
        params:
            Positional parameters for the query, if any.

        Returns:
        -------
        duckdb.DuckDBPyConnection
            The DuckDB cursor-like object after execution.
        """
        return self.connection.execute(query, params)

    def close(self) -> None:
        """Close the underlying database connection."""
        self.connection.close()

    def cursor(self):
        """Return a DB-API compatible cursor from the underlying connection."""
        return self.connection.cursor()

    def commit(self) -> None:
        """Commit the current transaction on the underlying connection."""
        return self.connection.commit()

    def drop_all_tables(self) -> None:
        """Drop all tables in the database (idempotent)."""
        tables = self.connection.execute("SHOW TABLES").fetchall()
        for (table_name,) in tables:
            self.connection.execute(f"DROP TABLE IF EXISTS {table_name}")

    def __enter__(self):
        """Enter the runtime context for the DB object."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the runtime context for the DB object."""
        self.close()

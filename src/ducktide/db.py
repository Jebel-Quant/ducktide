"""Generic database connection management.

This module provides the base DB class for managing DuckDB connections,
executing raw queries, and supporting context manager patterns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import duckdb


class DB:
    """Generic DuckDB database wrapper.

    Provides basic connection management, query execution, and context manager
    support. This class is intended to be used as a base for more specialized
    database implementations and does not contain any model or table specific logic.

    Example:
        >>> from functools import partial
        >>> from jqr.database import DB, Table
        >>> from jqr.database.orm.example import FooORM, Foo
        >>>
        >>> # Initialize with a mapping of attribute names to table classes
        >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
        >>>
        >>> # Tables are accessible as attributes
        >>> isinstance(db.table[Foo], Table)
        True
        >>>
        >>> # Insert domain models directly
        >>> db.insert(Foo(id=1, name="apple"))
        >>> len(db.foo.select())
        1
    """

    def __init__(
        self, tables_map: Mapping[str, Callable[..., Any]], db_path: str | Path = ":memory:", read_only: bool = False
    ) -> None:
        """Initialize the DB with either in-memory or persistent storage.

        Args:
            tables_map: Mapping of attribute names to table classes
                to be initialized automatically. These are typically
                `partial(Table, model_class=ModelORM)`.
            db_path: Path to the database file, or ":memory:" for in-memory.
            read_only: If True, open the database in read-only mode.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>> db.db_path
            ':memory:'
        """
        self.db_path = db_path
        self.read_only = read_only
        self.connection = duckdb.connect(self.db_path, read_only=read_only)
        self._model_to_table: dict[type, Any] = {}

        self._initialize_tables(tables_map)

    def insert(self, *objs: Any) -> None:
        """Insert one or more objects into their respective tables.

        The method automatically routes each object to the correct table based
        on its type (either domain model or ORM model).

        Args:
            *objs: One or more model instances to be inserted.

        Raises:
            TypeError: If an object's type is not registered in any table.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM, Foo
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>>
            >>> # Insert multiple objects (mix of domain and ORM models)
            >>> db.insert(Foo(id=1, name="apple"), FooORM(id=2, name="banana"))
            >>> len(db.foo.select())
            2
        """
        for obj in objs:
            table = self._model_to_table.get(type(obj))
            if table is None:
                raise TypeError(f"Invalid object type: {type(obj)}.")  # noqa: TRY003
            table.insert(obj)

    def _initialize_tables(self, tables_map: Mapping[str, Callable[..., Any]]) -> None:
        """Initialize table interfaces as attributes of this database instance.

        This is an internal method called during `__init__`. It instantiates
        each table class and maps both domain and ORM models to the table
        instance for routing in `insert()`.

        Args:
            tables_map: Mapping of attribute names to table classes.
        """
        for attr, table_cls in tables_map.items():
            table = table_cls(self.connection, read_only=self.read_only)
            setattr(self, attr, table)

            # Map domain model and ORM model to the table instance for insert()
            self._model_to_table[table.model_class] = table
            if hasattr(table.model_class, "_domain_model") and table.model_class._domain_model:
                self._model_to_table[table.model_class._domain_model] = table

    @property
    def table(self) -> dict[type, Any]:
        """Return a mapping of model classes to table instances.

        This allows looking up a table interface by its associated model class
        (either the domain model or the ORM model).

        Returns:
            dict[type, Any]: Mapping of model classes to Table instances.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM, Foo
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>> db.table[Foo] == db.foo
            True
            >>> db.table[FooORM] == db.foo
            True
        """
        return self._model_to_table

    def execute_query(self, query: str, params: Sequence[Any] | None = None) -> duckdb.DuckDBPyConnection:
        """Execute a SQL query against the underlying connection.

        Args:
            query: SQL query string with optional placeholders (`?`).
            params: Positional parameters for the query, if any.

        Returns:
            duckdb.DuckDBPyConnection: The DuckDB connection object after execution.

        Example:
            >>> from jqr.database.db import DB
            >>> db = DB(tables_map={})
            >>> res = db.execute_query("SELECT 1 as val")
            >>> res.fetchone()
            (1,)
        """
        return self.connection.execute(query, params)

    def close(self) -> None:
        """Close the underlying database connection.

        Once closed, no further queries can be executed.
        """
        self.connection.close()

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """Return a DB-API compatible cursor from the underlying connection.

        Returns:
            duckdb.DuckDBPyConnection: A cursor for executing database operations.
        """
        return self.connection.cursor()

    def commit(self) -> None:
        """Commit the current transaction on the underlying connection."""
        self.connection.commit()

    def drop_all_tables(self) -> None:
        """Drop all tables in the database (idempotent).

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>> db.drop_all_tables()
            >>> # No tables left
            >>> db.execute_query("SHOW TABLES").fetchall()
            []
        """
        tables = self.connection.execute("SHOW TABLES").fetchall()
        for (table_name,) in tables:
            # Safe interpolation (B608): table_name is an identifier from the DuckDB catalog
            # (SHOW TABLES), never user input; safe to interpolate.
            self.connection.execute(f"DROP TABLE IF EXISTS {table_name}")  # nosec B608

    def __enter__(self) -> Self:
        """Enter the runtime context for the DB object.

        Returns:
            Self: The database instance itself.

        Example:
            >>> from jqr.database.db import DB
            >>> with DB(tables_map={}) as db:
            ...     res = db.execute_query("SELECT 42")
            ...     res.fetchone()
            (42,)
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the runtime context for the DB object, closing the connection.

        Args:
            exc_type: The exception type if an exception was raised, or None.
            exc_value: The exception instance if an exception was raised, or None.
            traceback: The traceback if an exception was raised, or None.
        """
        self.close()

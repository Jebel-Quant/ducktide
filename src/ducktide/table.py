"""Database table interface for the JQR ORM system.

This module provides the Table class, which serves as a repository-pattern
interface for performing database operations on specific tables.
"""

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import polars as pl

from .exceptions import DataError
from .utils.path_validation import escape_path_for_sql, validate_file_path

if TYPE_CHECKING:
    from .orm.base import ORMModel


class Table:
    """Table interface for database operations following the Repository pattern.

    This class provides a consistent API for all CRUD operations on a database
    table. Each table is associated with a model class and provides methods
    for inserting, querying, and exporting data.

    All database operations in this ORM go through Table instances, which are
    accessed via the Database class (e.g., db.table_name).
    Models themselves do NOT have persistence methods.

    Key Methods:
        insert(*objs): Insert one or more model instances
        bulk_insert(objs): Efficiently insert many instances
        select(where_clause, params): Query with optional filtering
        all(): Get all rows as tuples
        to_frame(): Export to Polars DataFrame
        to_csv(path): Export to CSV
        to_parquet(path): Export to Parquet
        from_csv(path): Import from CSV
        from_parquet(path): Import from Parquet

    Example:
        db = DB(tables_map={...})
        model = ModelClass(id=1, name="Example", ...)

        # Insert
        db.insert(model)

        # Query
        # table = db.get_table(ModelClass)
        # all_items = table.select()
        # filtered = table.select("status = ?", ["active"])

        # Export
        # table.to_csv("data.csv")
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, model_class: "type[ORMModel]", read_only: bool = False):
        """Initialize a generic Table helper.

        Parameters
        ----------
        connection:
            Active DuckDB connection used to execute queries.
        model_class:
            The ORM model class (e.g., ``ModelORM``) providing
            ``_table_name``, ``_columns``, ``_primary_key``,
            ``generate_create_table_sql()`` and ``from_row(...)``.
        read_only:
            If True, skip schema initialization.
        """
        self.connection = connection
        self.model_class = model_class
        self.table_name = model_class._table_name
        self.columns = tuple(model_class._columns)
        self.pk = model_class._primary_key

        # Initialize schema if not read-only
        if not read_only:
            self.connection.execute(model_class.generate_create_table_sql())

    # -----------------------------------------------------------------

    def _get_single_result(self, results: list[Any], identifier: str, value: Any) -> Any:
        """Return a single result from a list, raising KeyError if not found.

        Args:
            results: List of query results.
            identifier: Name of the identifier field (for error message).
            value: Value of the identifier (for error message).

        Returns:
            The first (and expected only) result from the list.

        Raises:
            KeyError: If the results list is empty.
        """
        if not results:
            raise KeyError(f"No row found for {identifier} = {value}")  # noqa: TRY003
        return results[0]

    def _values_from_obj(self, obj: Any) -> tuple[Any, ...]:
        # Check if obj is an instance of model_class or its base domain class
        # This allows both domain models and ORM models to be inserted into a Table
        # We check if the object has all required columns as attributes.
        # For simplicity and robustness, we allow any object that has all required columns as attributes.
        try:
            return tuple(getattr(obj, col) for col in self.columns)
        except AttributeError as exc:
            raise DataError(f"Object {type(obj).__name__} is missing required column: {exc}") from exc  # noqa: TRY003

    # ---------------------------
    # Insert / Bulk Insert
    # ---------------------------
    def insert(self, *objs: Any) -> None:
        """Insert one or more model instances into the table.

        This is the primary method for adding data to the database. For a single
        object, it performs a simple INSERT. For multiple objects, it delegates
        to bulk_insert() for better performance.

        Args:
            *objs: One or more model instances.
                Can be either domain models or their ORM equivalents.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>> foo1 = FooORM(id=1, name="apple")
            >>> foo2 = FooORM(id=2, name="banana")
            >>> db.insert(foo1, foo2)
            >>>
            >>> # Verify insertion
            >>> table = db.table[FooORM]
            >>> len(table.select())
            2

        Note:
            When inserting multiple objects, consider using bulk_insert() directly
            for optimal performance with large datasets.
        """
        if not objs:
            return

        if len(objs) == 1:
            # Single row insert
            obj = objs[0]
            placeholders = ", ".join("?" for _ in self.columns)
            cols = ", ".join(self.columns)
            sql = f"INSERT INTO {self.table_name} ({cols}) VALUES ({placeholders})"  # nosec B608

            self.connection.execute(sql, self._values_from_obj(obj))

        else:
            # Multiple rows → delegate to bulk_insert
            self.bulk_insert(objs)

    def bulk_insert(self, objs: Iterable[Any]) -> None:
        """Insert multiple objects into the table in one efficient operation.

        This method is optimized for inserting many records at once, using
        DuckDB's executemany() for batch processing. It's significantly faster
        than calling insert() in a loop for large datasets.

        Parameters
        ----------
        objs:
            An iterable of model instances whose attributes map to the
            table's column order defined in ``self.columns``.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>>
            >>> # Create multiple Foo instances
            >>> foos = [FooORM(id=i, name=f"item_{i}") for i in range(1, 101)]
            >>>
            >>> # Bulk insert for efficient batch processing
            >>> table = db.table[FooORM]
            >>> table.bulk_insert(foos)
            >>>
            >>> # Verify all items were inserted
            >>> len(table.select())
            100

        Performance:
            For inserting 1000+ records, bulk_insert() can be 10-100x faster
            than individual insert() calls due to reduced SQL parsing and
            transaction overhead.
        """
        objs = list(objs)
        if not objs:
            return

        placeholders = ", ".join("?" for _ in self.columns)
        cols = ", ".join(self.columns)

        sql = f"""
        INSERT INTO {self.table_name} ({cols})
        VALUES ({placeholders})
        """  # nosec B608

        values = [self._values_from_obj(obj) for obj in objs]
        self.connection.executemany(sql, values)

    def execute(self, query: str, params: Sequence[Any] | None = None) -> list[Any]:
        """Execute a SQL query against the underlying connection.

        Args:
            query: SQL query string with optional placeholders.
            params: Parameter values for the query placeholders.

        Returns:
            List of model instances created from the query results.
        """
        rows = self.connection.execute(query, params).fetchall()
        return [self.model_class.from_row(row) for row in rows]

    def select(
        self,
        where_clause: str | None = None,
        where_params: Sequence[Any] | None = None,
    ) -> list[Any]:
        """Select rows from the table and return model instances.

        Query the table with optional filtering via SQL WHERE clauses. Always
        uses parameterized queries to prevent SQL injection.

        Parameters
        ----------
        where_clause:
            Optional SQL WHERE clause (without the ``WHERE`` keyword). Use ``?``
            as placeholders for parameters. If omitted, all rows are returned.
        where_params:
            Optional parameter values for the WHERE clause placeholders. Must
            match the number of ``?`` in where_clause.

        Returns:
        -------
        list[model_class]
            A list of instantiated domain/ORM model objects created via
            ``model_class.from_row``.

        Example:
            >>> from functools import partial
            >>> from jqr.database.db import DB
            >>> from jqr.database.orm.example import FooORM
            >>> from jqr.database.table import Table
            >>>
            >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
            >>> db.insert(FooORM(id=1, name="apple"), FooORM(id=2, name="banana"), FooORM(id=3, name="cherry"))
            >>>
            >>> table = db.table[FooORM]
            >>> # Select all items
            >>> all_foos = table.select()
            >>> len(all_foos)
            3
            >>>
            >>> # Select with filter using parameterized query
            >>> filtered = table.select("name = ?", ["apple"])
            >>> filtered[0].name
            'apple'
            >>>
            >>> # Select with ORDER BY
            >>> ordered = table.select("id > ? ORDER BY name DESC", [0])
            >>> [f.name for f in ordered]
            ['cherry', 'banana', 'apple']

        Note:
        ----
        Always use parameterized queries (``?`` placeholders) rather than string
        concatenation to prevent SQL injection vulnerabilities.
        """
        where_clause = where_clause or "1 = 1"
        where_params = where_params or []

        sql = f"""
        SELECT *
        FROM {self.table_name}
        WHERE {where_clause}
        """  # nosec B608

        rows = self.connection.execute(sql, where_params).fetchall()
        return [self.model_class.from_row(row) for row in rows]

    def get_by(self, key: str, value: Any) -> Any:
        """Return a single row from the table by a given key.

        Args:
            key: The column name to filter by.
            value: The value to match.

        Returns:
            The model instance matching the given key-value pair.

        Raises:
            KeyError: If no row is found for the given key-value pair.
        """
        result = self.select(f"{key} = ?", [value])
        return self._get_single_result(result, key, value)

    def get(self, id: int | None = None) -> Any:
        """Return a single row from the table as a model instance.

        Args:
            id: The primary key value to look up. If None, returns None.

        Returns:
            The model instance matching the given ID, or None if id is None.

        Raises:
            KeyError: If no row is found for the given ID.
        """
        if id is None:
            return None

        result = self.select(f"{self.pk} = ?", [id])
        return self._get_single_result(result, self.pk, id)

    @property
    def exists(self) -> bool:
        """Return True if the table exists in the database, False otherwise."""
        # Use SHOW TABLES to check if the table exists
        rows = self.connection.execute("SHOW TABLES").fetchall()
        table_names = [row[0] for row in rows]
        return self.table_name in table_names

    @property
    def empty(self) -> bool:
        """Return True if the table is empty, False otherwise."""
        if not self.exists:
            return True
        result = self.connection.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()  # nosec B608
        return bool(result is None or result[0] == 0)

    def __len__(self) -> int:
        """Return the number of rows in the table."""
        if not self.exists:
            return 0
        result = self.connection.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()  # nosec B608
        return int(result[0]) if result else 0

    def __bool__(self) -> bool:
        """Return True if the table is not empty, False otherwise."""
        return not self.empty

    def __iter__(self) -> Iterator[Any]:
        """Iterate over all rows in the table as model instances."""
        yield from self.select()

    def __getitem__(self, key: Any) -> Any:
        """Return a single row from the table by its primary key.

        Parameters
        ----------
        key:
            The primary key value of the row to retrieve.

        Returns:
        -------
        Any
            The model instance corresponding to the given primary key.

        Raises:
        ------
        KeyError:
            If no row is found for the given primary key.
        """
        result = self.select(f"{self.pk} = ?", [key])
        if len(result) == 0:
            raise KeyError(f"No row found for {self.pk} = {key}")  # noqa: TRY003

        return result[0]

    def to_frame(self) -> pl.DataFrame:
        """Return the table as a Polars DataFrame.

        Returns:
        -------
        pl.DataFrame
            A Polars DataFrame containing all rows from the table with
            their column names preserved.
        """
        return self.connection.execute(f"SELECT * FROM {self.table_name}").pl()  # nosec B608

    def _get_date_columns(self) -> set[str]:
        """Return the set of date columns that need special handling.

        Override in subclasses or configure via model_class to customize
        which columns are treated as dates for CSV/Parquet export.

        Returns:
            Set of column names that should be cast to VARCHAR for export.
        """
        # Check if model class has date_columns defined
        if hasattr(self.model_class, "date_columns"):
            return set(self.model_class.date_columns)
        # Default: common date column names
        return {"expiry", "date", "timestamp"}

    def to_csv(
        self,
        path: str | Path,
        *,
        delimiter: str = ",",
        header: bool = True,
        overwrite: bool = True,
    ) -> None:
        """Export the table to a CSV file using DuckDB's native writer.

        Parameters
        ----------
        path:
            Output CSV path.
        delimiter:
            Field delimiter (default: ',').
        header:
            Whether to include column headers.
        overwrite:
            Whether to overwrite an existing file.

        Raises:
            FileExistsError: If the file exists and overwrite is False.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path)

        if validated_path.exists() and not overwrite:
            raise FileExistsError(validated_path)

        escaped_path = escape_path_for_sql(validated_path)

        # COPY TO options use standard syntax (no '=' required)
        options = [
            f"DELIMITER '{delimiter}'",
            f"HEADER {str(header).upper()}",
        ]

        # Ensure date-like columns are serialized as ISO strings
        date_columns = self._get_date_columns()
        select_cols = []
        for col in self.columns:
            if col in date_columns:
                select_cols.append(f"CAST({col} AS VARCHAR) AS {col}")
            else:
                select_cols.append(col)

        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{escaped_path}'
        ({", ".join(options)})
        """  # nosec B608

        self.connection.execute(sql)

    def to_parquet(
        self,
        path: str | Path,
        *,
        compression: str = "snappy",
        overwrite: bool = True,
    ) -> None:
        """Export the table to a Parquet file using DuckDB's native writer.

        Parameters
        ----------
        path:
            Output Parquet path.
        compression:
            Parquet compression codec (snappy, zstd, gzip, uncompressed).
        overwrite:
            Whether to overwrite an existing file.

        Raises:
            FileExistsError: If the file exists and overwrite is False.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path)

        if validated_path.exists() and not overwrite:
            raise FileExistsError(validated_path)

        escaped_path = escape_path_for_sql(validated_path)

        # Ensure date-like columns are serialized as ISO strings
        date_columns = self._get_date_columns()
        select_cols = []
        for col in self.columns:
            if col in date_columns:
                select_cols.append(f"CAST({col} AS VARCHAR) AS {col}")
            else:
                select_cols.append(col)

        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{escaped_path}'
        (FORMAT PARQUET, COMPRESSION '{compression}')
        """  # nosec B608

        self.connection.execute(sql)

    def from_csv(
        self,
        path: str | Path,
        *,
        delimiter: str = ",",
        header: bool = True,
    ) -> int:
        """Load data from a CSV file into the table using DuckDB.

        The CSV must match the table schema (column names & types).

        Parameters
        ----------
        path:
            Path to the CSV file.
        delimiter:
            Field delimiter character.
        header:
            Whether the CSV has a header row.

        Returns:
            int: Number of rows imported.

        Raises:
            FileNotFoundError: If the CSV file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)

        # read_csv_auto options require KEY=VALUE form
        options = [
            f"DELIM='{delimiter}'",
            f"HEADER={str(header).upper()}",
        ]

        # Count rows first (for return value), then insert
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_csv_auto(
            '{escaped_path}',
            {", ".join(options)}
        )
        """  # nosec B608

        result = self.connection.execute(count_sql).fetchone()
        row_count = int(result[0]) if result else 0

        _sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_csv_auto(
            '{escaped_path}',
            {", ".join(options)}
        )
        """  # nosec B608

        self.connection.execute(_sql)
        return row_count

    def from_parquet(self, path: str | Path) -> int:
        """Load data from a Parquet file into the table and return imported row count.

        Parameters
        ----------
        path:
            Path to the Parquet file.

        Returns:
            int: Number of rows imported.

        Raises:
            FileNotFoundError: If the Parquet file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)

        # Count rows first for return value
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_parquet('{escaped_path}')
        """  # nosec B608

        result = self.connection.execute(count_sql).fetchone()
        row_count = int(result[0]) if result else 0

        insert_sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_parquet('{escaped_path}')
        """  # nosec B608

        self.connection.execute(insert_sql)
        return row_count

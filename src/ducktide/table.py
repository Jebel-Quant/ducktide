"""Database table interface for the JQR ORM system.

This module provides the Table class, which serves as a repository-pattern
interface for performing database operations on specific tables.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path

import duckdb
import polars as pl

from .exceptions import DataError


class Table:
    """Table interface for database operations following the Repository pattern.

    This class provides a consistent API for all CRUD operations on a database
    table. Each table is associated with a model class (Publisher, Future, or
    Contract) and provides methods for inserting, querying, and exporting data.

    All database operations in this ORM go through Table instances, which are
    accessed via the Database class (e.g., db.publisher, db.futures, db.contracts).
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
        db = Database()
        publisher = Publisher(publisher_id=1, name="CME", dataset="GLBX.MDP3", venue="GLBX")

        # Insert
        db.publisher.insert(publisher)

        # Query
        all_pubs = db.publisher.select()
        glbx_pubs = db.publisher.select("venue = ?", ["GLBX"])

        # Export
        db.publisher.to_csv("publishers.csv")
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, model_class: type, read_only: bool = False):
        """Initialize a generic Table helper.

        Parameters
        ----------
        connection:
            Active DuckDB connection used to execute queries.
        model_class:
            The ORM model class (e.g., ``PublisherORM``) providing
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

        # def _initialize_schema(self) -> None:
        # for orm in (PublisherORM, FutureORM, ContractORM):
        if not read_only:
            self.connection.execute(model_class.generate_create_table_sql())

    # -----------------------------------------------------------------

    def _values_from_obj(self, obj) -> tuple:
        # Check if obj is an instance of model_class or its base domain class
        # This allows both Publisher and PublisherORM to be inserted into a Table(model_class=PublisherORM)
        # We check the __mro__ of model_class to find the domain model (which is a base of ORM model)
        # or just check if it has the required attributes.
        # For simplicity and robustness, we allow any object that has all required columns as attributes.
        try:
            return tuple(getattr(obj, col) for col in self.columns)
        except AttributeError as exc:
            raise DataError(f"Object {type(obj).__name__} is missing required column: {exc}") from exc

    # ---------------------------
    # Insert / Bulk Insert
    # ---------------------------
    def insert(self, *objs) -> None:
        """Insert one or more objects.

        Args:
            objs: One or more model instances.
        """
        if not objs:
            return

        if len(objs) == 1:
            # Single row insert
            obj = objs[0]
            placeholders = ", ".join("?" for _ in self.columns)
            cols = ", ".join(self.columns)
            sql = f"INSERT INTO {self.table_name} ({cols}) VALUES ({placeholders})"

            self.connection.execute(sql, self._values_from_obj(obj))

        else:
            # Multiple rows → delegate to bulk_insert
            self.bulk_insert(objs)

    def bulk_insert(self, objs: Iterable) -> None:
        """Insert multiple objects into the table in one operation.

        Parameters
        ----------
        objs:
            An iterable of model instances whose attributes map to the
            table's column order defined in ``self.columns``.
        """
        objs = list(objs)
        if not objs:
            return

        placeholders = ", ".join("?" for _ in self.columns)
        cols = ", ".join(self.columns)

        sql = f"""
        INSERT INTO {self.table_name} ({cols})
        VALUES ({placeholders})
        """

        values = [self._values_from_obj(obj) for obj in objs]
        self.connection.executemany(sql, values)

    def execute(self, query: str, params: Sequence | None = None):
        """Execute a SQL query against the underlying connection."""
        rows = self.connection.execute(query, params).fetchall()
        return [self.model_class.from_row(row) for row in rows]

    def select(
        self,
        where_clause: str | None = None,
        where_params: Sequence | None = None,
    ):
        """Select rows from the table and return model instances.

        Parameters
        ----------
        where_clause:
            Optional SQL WHERE clause (without ``WHERE``). If omitted,
            all rows are returned.
        where_params:
            Optional parameter values for the WHERE clause.

        Returns:
        -------
        list[model_class]
            A list of instantiated domain/ORM model objects created via
            ``model_class.from_row``.
        """
        where_clause = where_clause or "1 = 1"
        where_params = where_params or []

        sql = f"""
        SELECT *
        FROM {self.table_name}
        WHERE {where_clause}
        """

        rows = self.connection.execute(sql, where_params).fetchall()
        return [self.model_class.from_row(row) for row in rows]

    def get(self, id=None):
        """Return a single row from the table as a model instance."""
        if id is None:
            return None

        result = self.select(f"{self.pk} = ?", [id])

        if result is None or len(result) == 0:
            raise KeyError(f"No row found for {self.pk} = {id}")

        return result[0]

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
        return self.connection.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0] == 0

    def __len__(self) -> int:
        """Return the number of rows in the table."""
        if not self.exists:
            return 0
        return self.connection.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]

    def __bool__(self) -> bool:
        """Return True if the table is not empty, False otherwise."""
        return not self.empty

    def __iter__(self):
        """Iterate over all rows in the table as model instances."""
        yield from self.select()

    def __getitem__(self, key):
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
            raise KeyError(f"No row found for {self.pk} = {key}")

        return result[0]

    def to_frame(self) -> pl.DataFrame:
        """Return the table as a Polars DataFrame.

        Returns:
        -------
        pl.DataFrame
            A Polars DataFrame containing all rows from the table with
            their column names preserved.
        """
        return self.connection.execute(f"SELECT * FROM {self.table_name}").pl()

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
        """
        from pathlib import Path

        path = Path(path)

        if path.exists() and not overwrite:
            raise FileExistsError(path)

        # COPY TO options use standard syntax (no '=' required)
        options = [
            f"DELIMITER '{delimiter}'",
            f"HEADER {str(header).upper()}",
        ]

        # Ensure date-like columns (e.g., expiry) are serialized as ISO strings
        select_cols = []
        for col in self.columns:
            if col == "expiry":
                select_cols.append("CAST(expiry AS VARCHAR) AS expiry")
            else:
                select_cols.append(col)

        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{path}'
        ({", ".join(options)})
        """

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
        """
        from pathlib import Path

        path = Path(path)

        if path.exists() and not overwrite:
            raise FileExistsError(path)

        # Ensure date-like columns (e.g., expiry) are serialized as ISO strings
        select_cols = []
        for col in self.columns:
            if col == "expiry":
                select_cols.append("CAST(expiry AS VARCHAR) AS expiry")
            else:
                select_cols.append(col)

        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{path}'
        (FORMAT PARQUET, COMPRESSION '{compression}')
        """

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
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(path)

        # read_csv_auto options require KEY=VALUE form
        options = [
            f"DELIM='{delimiter}'",
            f"HEADER={str(header).upper()}",
        ]

        # Count rows first (for return value), then insert
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_csv_auto(
            '{path}',
            {", ".join(options)}
        )
        """

        row_count = self.connection.execute(count_sql).fetchone()[0]

        _sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_csv_auto(
            '{path}',
            {", ".join(options)}
        )
        """

        self.connection.execute(_sql)
        return row_count

    def from_parquet(self, path: str | Path) -> int:
        """Load data from a Parquet file into the table and return imported row count.

        Parameters
        ----------
        path:
            Path to the Parquet file.
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(path)

        # Count rows first for return value
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_parquet('{path}')
        """

        row_count = self.connection.execute(count_sql).fetchone()[0]

        insert_sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_parquet('{path}')
        """

        self.connection.execute(insert_sql)
        return row_count

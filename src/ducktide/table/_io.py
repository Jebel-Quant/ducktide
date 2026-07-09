"""Import/export and DataFrame conversion for the table interface.

This module defines :class:`IOMixin`, which moves data between the table and
external formats: Polars DataFrames plus CSV and Parquet files, using DuckDB's
native readers and writers. Date-like columns are serialized as ISO strings on
export for round-trip stability.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import cast

import polars as pl

from ..utils import sql
from ..utils.path_validation import escape_path_for_sql, validate_file_path
from ._base import TableBase


class IOMixin(TableBase):
    """DataFrame conversion and CSV/Parquet import/export for a table."""

    def to_frame(self) -> pl.DataFrame:
        """Return the table as a Polars DataFrame.

        Returns:
            pl.DataFrame: A Polars DataFrame containing all rows from the table with
                their column names preserved.
        """
        return self.connection.execute(sql.select_all(self.table_name)).pl()

    def _get_date_columns(self) -> set[str]:
        """Return the set of date columns that need special handling.

        Override in subclasses or configure via model_class to customize
        which columns are treated as dates for CSV/Parquet export.

        Returns:
            Set of column names that should be cast to VARCHAR for export.
        """
        # Check if model class has date_columns defined
        if hasattr(self.model_class, "date_columns"):
            return set(cast(Iterable[str], self.model_class.date_columns))
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

        Args:
            path: Output CSV path.
            delimiter: Field delimiter (default: ',').
            header: Whether to include column headers.
            overwrite: Whether to overwrite an existing file.

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

        # table_name and column names come from the ORM model class definition;
        # escaped_path is sanitized via escape_path_for_sql; the COPY options are
        # literal SQL keywords, not bindable parameters in DuckDB.
        statement = sql.copy_select_to(", ".join(select_cols), self.table_name, escaped_path, ", ".join(options))

        self.connection.execute(statement)

    def to_parquet(
        self,
        path: str | Path,
        *,
        compression: str = "snappy",
        overwrite: bool = True,
    ) -> None:
        """Export the table to a Parquet file using DuckDB's native writer.

        Args:
            path: Output Parquet path.
            compression: Parquet compression codec (snappy, zstd, gzip, uncompressed).
            overwrite: Whether to overwrite an existing file.

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

        # table_name and column names come from the ORM model class definition;
        # escaped_path is sanitized via escape_path_for_sql; FORMAT and
        # COMPRESSION are literal COPY options, not bindable parameters.
        options = f"FORMAT PARQUET, COMPRESSION '{compression}'"
        statement = sql.copy_select_to(", ".join(select_cols), self.table_name, escaped_path, options)

        self.connection.execute(statement)

    def from_csv(
        self,
        path: str | Path,
        *,
        delimiter: str = ",",
        header: bool = True,
    ) -> int:
        """Load data from a CSV file into the table using DuckDB.

        The CSV must match the table schema (column names & types).

        Args:
            path: Path to the CSV file.
            delimiter: Field delimiter character.
            header: Whether the CSV has a header row.

        Returns:
            int: Number of rows imported.

        Raises:
            FileNotFoundError: If the CSV file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)

        # read_csv_auto options require KEY=VALUE form. escaped_path is sanitized
        # via escape_path_for_sql; the options are literal SQL keywords and
        # table_name comes from the ORM model class definition.
        options = ", ".join([f"DELIM='{delimiter}'", f"HEADER={str(header).upper()}"])
        reader = sql.read_csv_expr(escaped_path, options)

        # Count rows first (for return value), then insert.
        result = self.connection.execute(sql.count_all(reader)).fetchone()
        row_count = int(result[0]) if result else 0

        self.connection.execute(sql.insert_from_query(self.table_name, sql.select_all(reader)))
        return row_count

    def from_parquet(self, path: str | Path) -> int:
        """Load data from a Parquet file into the table and return imported row count.

        Args:
            path: Path to the Parquet file.

        Returns:
            int: Number of rows imported.

        Raises:
            FileNotFoundError: If the Parquet file doesn't exist.
            ValidationError: If the path is invalid.
        """
        validated_path = validate_file_path(path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)

        # escaped_path is sanitized via escape_path_for_sql; table_name comes from
        # the ORM model class definition.
        reader = sql.read_parquet_expr(escaped_path)

        # Count rows first for return value, then insert.
        result = self.connection.execute(sql.count_all(reader)).fetchone()
        row_count = int(result[0]) if result else 0

        self.connection.execute(sql.insert_from_query(self.table_name, sql.select_all(reader)))
        return row_count

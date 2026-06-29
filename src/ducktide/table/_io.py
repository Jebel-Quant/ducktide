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
        # Safe interpolation (B608): table_name comes from the ORM model class definition (code,
        # not user data); no data values are interpolated.
        return self.connection.execute(f"SELECT * FROM {self.table_name}").pl()  # nosec B608  # noqa: S608

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

        # Safe interpolation (B608): table_name and column names come from the ORM model class
        # definition; escaped_path is sanitized via escape_path_for_sql; the COPY
        # options are literal SQL keywords, not bindable parameters in DuckDB.
        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{escaped_path}'
        ({", ".join(options)})
        """  # nosec B608  # noqa: S608

        self.connection.execute(sql)

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

        # Safe interpolation (B608): table_name and column names come from the ORM model class
        # definition; escaped_path is sanitized via escape_path_for_sql; FORMAT
        # and COMPRESSION are literal COPY options, not bindable parameters.
        sql = f"""
        COPY (
            SELECT {", ".join(select_cols)}
            FROM {self.table_name}
        )
        TO '{escaped_path}'
        (FORMAT PARQUET, COMPRESSION '{compression}')
        """  # nosec B608  # noqa: S608

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

        # read_csv_auto options require KEY=VALUE form
        options = [
            f"DELIM='{delimiter}'",
            f"HEADER={str(header).upper()}",
        ]

        # Count rows first (for return value), then insert
        # Safe interpolation (B608): escaped_path is sanitized via escape_path_for_sql and the
        # read_csv_auto options are literal SQL keywords, not bindable parameters.
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_csv_auto(
            '{escaped_path}',
            {", ".join(options)}
        )
        """  # nosec B608  # noqa: S608

        result = self.connection.execute(count_sql).fetchone()
        row_count = int(result[0]) if result else 0

        # Safe interpolation (B608): table_name comes from the ORM model class definition;
        # escaped_path is sanitized via escape_path_for_sql; read_csv_auto options
        # are literal SQL keywords, not bindable parameters.
        _sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_csv_auto(
            '{escaped_path}',
            {", ".join(options)}
        )
        """  # nosec B608  # noqa: S608

        self.connection.execute(_sql)
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

        # Count rows first for return value
        # Safe interpolation (B608): escaped_path is sanitized via escape_path_for_sql; no data
        # values are interpolated.
        count_sql = f"""
        SELECT COUNT(*)
        FROM read_parquet('{escaped_path}')
        """  # nosec B608  # noqa: S608

        result = self.connection.execute(count_sql).fetchone()
        row_count = int(result[0]) if result else 0

        # Safe interpolation (B608): table_name comes from the ORM model class definition;
        # escaped_path is sanitized via escape_path_for_sql.
        insert_sql = f"""
        INSERT INTO {self.table_name}
        SELECT *
        FROM read_parquet('{escaped_path}')
        """  # nosec B608  # noqa: S608

        self.connection.execute(insert_sql)
        return row_count

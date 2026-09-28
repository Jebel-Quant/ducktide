"""CSV/Parquet import and export for the time-series interface.

This module defines :class:`TimeSeriesIOMixin`, which creates-or-replaces
tables from CSV/Parquet files and exports tables back out, using DuckDB's
native readers/writers with validated, escaped paths.
"""

from pathlib import Path

from ..exceptions import QueryError
from ..utils import sql
from ..utils.path_validation import escape_path_for_sql, validate_file_path
from ._base import TimeSeriesBase


class TimeSeriesIOMixin(TimeSeriesBase):
    """CSV/Parquet import and export for time-series tables."""

    def import_csv(self, csv_path: str | Path, table: str) -> None:
        """Create or replace a table from a CSV file.

        Args:
            csv_path: Path to the CSV file to import.
            table: Name of the destination table.

        Raises:
            FileNotFoundError: If the CSV file doesn't exist.
            ValidationError: If the path or table name is invalid.
        """
        self._validate_table_name(table)
        self._require_writable("import_csv")
        validated_path = validate_file_path(csv_path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        # table_q is _quote_identifier output from a validated name; escaped_path
        # is sanitized via escape_path_for_sql.
        self.con.execute(sql.drop_table_if_exists(table_q))
        self.con.execute(sql.create_table_as(table_q, sql.select_all(sql.read_csv_expr(escaped_path))))

    def export_csv(self, table: str, csv_path: str | Path) -> None:
        """Export a table to a CSV file.

        Args:
            table: Name of the table to export.
            csv_path: Path to the output CSV file.

        Raises:
            QueryError: If the table doesn't exist.
            ValidationError: If the path or table name is invalid.
        """
        self._validate_table_name(table)
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")  # noqa: TRY003

        validated_path = validate_file_path(csv_path)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        # table_q is _quote_identifier output from a validated name, escaped_path
        # is sanitized via escape_path_for_sql, and HEADER/DELIMITER are literal
        # COPY options, not user data.
        self.con.execute(sql.copy_select_to("*", table_q, escaped_path, "HEADER, DELIMITER ','"))

    def import_parquet(self, pq_path: str | Path, table: str) -> None:
        """Create or replace a table from a Parquet file.

        Args:
            pq_path: Path to the Parquet file to import.
            table: Name of the destination table.

        Raises:
            FileNotFoundError: If the Parquet file doesn't exist.
            ValidationError: If the path or table name is invalid.
        """
        self._validate_table_name(table)
        self._require_writable("import_parquet")
        validated_path = validate_file_path(pq_path, must_exist=True)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        # table_q is _quote_identifier output from a validated name; escaped_path
        # is sanitized via escape_path_for_sql.
        self.con.execute(sql.drop_table_if_exists(table_q))
        self.con.execute(sql.create_table_as(table_q, sql.select_all(sql.read_parquet_expr(escaped_path))))

    def export_parquet(self, table: str, pq_path: str | Path) -> None:
        """Export a table to a Parquet file.

        Args:
            table: Name of the table to export.
            pq_path: Path to the output Parquet file.

        Raises:
            QueryError: If the table doesn't exist.
            ValidationError: If the path or table name is invalid.
        """
        self._validate_table_name(table)
        if not self.has_table(table):
            raise QueryError(f"Table '{table}' does not exist")  # noqa: TRY003

        validated_path = validate_file_path(pq_path)
        escaped_path = escape_path_for_sql(validated_path)
        table_q = self._quote_identifier(table)
        # table_q is _quote_identifier output from a validated name, escaped_path
        # is sanitized via escape_path_for_sql, and FORMAT 'PARQUET' is a literal
        # COPY option, not user data.
        self.con.execute(sql.copy_select_to("*", table_q, escaped_path, "FORMAT 'PARQUET'"))

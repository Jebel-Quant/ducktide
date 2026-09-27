"""Base state and shared helpers for the :class:`~ducktide.table.Table`.

This module defines :class:`TableBase`, which owns the connection, the bound
model class and the cached table metadata (name, columns, primary key) shared
by every table mixin. It also provides the small helpers used across the
query, write and import/export mixins.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import duckdb

from ..exceptions import DataError

if TYPE_CHECKING:
    from ..orm.base import ORMModel


class TableBase:
    """Shared state and helpers for the table mixins.

    Holds the active connection and the metadata derived from the bound model
    class. The concrete :class:`~ducktide.table.Table` composes this base
    with the query, write and import/export mixins.

    Attributes:
        connection: Active DuckDB connection used to execute queries.
        model_class: The bound ORM model class.
        table_name: The model's database table name.
        columns: The model's columns, in declaration order.
        pk: The model's primary-key column name.
    """

    def __init__(
        self, connection: duckdb.DuckDBPyConnection, model_class: "type[ORMModel]", read_only: bool = False
    ) -> None:
        """Initialize a generic Table helper.

        Args:
            connection: Active DuckDB connection used to execute queries.
            model_class: The ORM model class (e.g., ``ModelORM``) providing
                ``_table_name``, ``_columns``, ``_primary_key``,
                ``generate_create_table_sql()`` and ``from_row(...)``.
            read_only: If True, skip schema initialization.
        """
        self.connection = connection
        self.model_class = model_class
        self.table_name = model_class._table_name
        self.columns = tuple(model_class._columns)
        self.pk = model_class._primary_key

        # Initialize schema if not read-only
        if not read_only:
            self.connection.execute(model_class.generate_create_table_sql())

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
        """Extract column values from an object as a tuple.

        Args:
            obj: A model instance with attributes matching the table columns.

        Returns:
            A tuple of values in column order.

        Raises:
            DataError: If the object is missing a required column attribute.
        """
        # Check if obj is an instance of model_class or its base domain class
        # This allows both domain models and ORM models to be inserted into a Table
        # We check if the object has all required columns as attributes.
        # For simplicity and robustness, we allow any object that has all required columns as attributes.
        try:
            return tuple(getattr(obj, col) for col in self.columns)
        except AttributeError as exc:
            raise DataError(f"Object {type(obj).__name__} is missing required column: {exc}") from exc  # noqa: TRY003

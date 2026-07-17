"""Read-side query construction and lookup for the table interface.

This module defines :class:`QueryMixin`, which builds parameterized ``SELECT``
statements from keyword filters and raw WHERE clauses, exposes single-row
lookups (:meth:`~QueryMixin.get`, :meth:`~QueryMixin.get_by`, item access) and
the collection protocol (length, truthiness, iteration, existence and
emptiness checks).
"""

from collections.abc import Iterator, Sequence
from typing import Any

from ..exceptions import ValidationError
from ..utils import sql
from ._base import TableBase

# Suffixes recognized by the keyword filter API, mapped to SQL comparison
# operators. Checked only after an exact column-name match fails, so a column
# literally named e.g. "valid_before" still filters by equality.
_FILTER_SUFFIXES = {
    "_before": "<",
    "_after": ">",
    "_at_or_before": "<=",
    "_at_or_after": ">=",
}


class QueryMixin(TableBase):
    """Read-side querying, lookups and the collection protocol for a table."""

    def _resolve_filter(self, name: str) -> tuple[str, str]:
        """Resolve a keyword filter name to a (column, operator) pair.

        Args:
            name: The filter keyword, either a plain column name (equality) or
                a column name with a comparison suffix such as ``expiry_before``.

        Returns:
            A tuple of (validated column name, SQL comparison operator).

        Raises:
            ValidationError: If the name is not a column of this table, with or
                without a recognized suffix.
        """
        if name in self.columns:
            return name, "="
        # Longest suffix first so "_at_or_before" wins over its "_before" tail.
        for suffix in sorted(_FILTER_SUFFIXES, key=len, reverse=True):
            column = name.removesuffix(suffix)
            if column != name and column in self.columns:
                return column, _FILTER_SUFFIXES[suffix]
        raise ValidationError(  # noqa: TRY003
            f"Unknown filter '{name}' for table '{self.table_name}'. "
            f"Valid columns: {', '.join(self.columns)}. "
            f"Comparison suffixes: {', '.join(sorted(_FILTER_SUFFIXES))}"
        )

    def _build_filter_conditions(self, filters: dict[str, Any]) -> tuple[list[str], list[Any]]:
        """Translate keyword filters into SQL conditions and bound parameters.

        Args:
            filters: Column-based filters, each name resolved via
                :meth:`_resolve_filter`. A ``None`` value with the equality
                operator becomes an ``IS NULL`` test rather than a bound param.

        Returns:
            A tuple of (list of condition fragments, list of parameter values).
        """
        conditions: list[str] = []
        params: list[Any] = []

        for name, value in filters.items():
            column, op = self._resolve_filter(name)
            if value is None and op == "=":
                conditions.append(f"{column} IS NULL")
            else:
                conditions.append(f"{column} {op} ?")
                params.append(value)

        return conditions, params

    def select(
        self,
        where_clause: str | None = None,
        where_params: Sequence[Any] | None = None,
        **filters: Any,
    ) -> list[Any]:
        """Select rows from the table and return model instances.

        Query the table with optional filtering, either via keyword filters
        (the preferred form) or via a raw SQL WHERE clause (the escape hatch
        for anything the keywords cannot express). Both forms always use
        parameterized queries to prevent SQL injection.

        Keyword filters match a column name for equality (``venue="GLBX"``) or
        a column name plus a comparison suffix: ``_before`` (<), ``_after``
        (>), ``_at_or_before`` (<=), ``_at_or_after`` (>=). Filter names are
        validated against the table's columns; an unknown name raises
        ``ValidationError``. Passing ``None`` filters for SQL ``NULL``.
        Multiple filters are combined with AND.

        Args:
            where_clause: Optional raw SQL WHERE clause (without the ``WHERE``
                keyword). Use ``?`` as placeholders for parameters. May be
                combined with keyword filters (joined with AND, appended last
                so trailing clauses like ``ORDER BY`` keep working).
            where_params: Optional parameter values for the WHERE clause placeholders. Must
                match the number of ``?`` in where_clause.
            **filters: Column-based filters validated against the model, e.g.
                ``venue="GLBX"`` or ``expiry_before=date(2026, 1, 1)``.

        Returns:
            list[model_class]: A list of instantiated domain/ORM model objects created via
                ``model_class.from_row``.

        Raises:
            ValidationError: If a keyword filter does not resolve to a column
                of this table.

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
            >>> # Select with a keyword filter (validated against the model)
            >>> filtered = table.select(name="apple")
            >>> filtered[0].name
            'apple'
            >>>
            >>> # Comparison suffixes for ranges
            >>> early = table.select(id_before=3)
            >>> sorted(f.name for f in early)
            ['apple', 'banana']
            >>>
            >>> # Raw WHERE clause as the escape hatch (e.g. for ORDER BY)
            >>> ordered = table.select("id > ? ORDER BY name DESC", [0])
            >>> [f.name for f in ordered]
            ['cherry', 'banana', 'apple']

        Note:
            Prefer keyword filters; they are validated against the model. When
            using the raw form, always use parameterized queries (``?``
            placeholders) rather than string concatenation to prevent SQL
            injection vulnerabilities.
        """
        conditions, params = self._build_filter_conditions(filters)

        # Raw clause goes last (unparenthesized) so trailing SQL such as
        # ORDER BY / LIMIT stays at the end of the statement.
        if where_clause:
            conditions.append(where_clause)
            params.extend(where_params or [])

        combined = " AND ".join(conditions) or "1 = 1"

        # table_name is from the ORM model class definition; filter column names
        # and operators come from _resolve_filter (validated against
        # self.columns), and any raw where_clause is a caller-supplied SQL
        # fragment by contract. All data values are bound via params below.
        statement = sql.select_ordered(self.table_name, where=combined)

        rows = self.connection.execute(statement, params).fetchall()
        return [self.model_class.from_row(row) for row in rows]

    def get_by(self, key: str, value: Any) -> Any:
        """Return a single row from the table by a given key.

        Args:
            key: The column name to filter by. Must be one of the table's columns.
            value: The value to match.

        Returns:
            The model instance matching the given key-value pair.

        Raises:
            ValidationError: If key is not a column of this table.
            KeyError: If no row is found for the given key-value pair.
        """
        # The column name is interpolated into SQL, so reject anything that is
        # not a known column of this table before building the query.
        if key not in self.columns:
            raise ValidationError(  # noqa: TRY003
                f"Unknown column '{key}' for table '{self.table_name}'. Valid columns: {', '.join(self.columns)}"
            )
        result = self.select(f"{key} = ?", [value])
        return self._get_single_result(result, key, value)

    def get(self, id: int | None = None) -> Any:  # noqa: A002 — public API: look up a row by its primary-key `id`
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
        result = self.connection.execute(sql.count_all(self.table_name)).fetchone()
        return bool(result is None or result[0] == 0)

    def __len__(self) -> int:
        """Return the number of rows in the table."""
        if not self.exists:
            return 0
        result = self.connection.execute(sql.count_all(self.table_name)).fetchone()
        return int(result[0]) if result else 0

    def __bool__(self) -> bool:
        """Return True if the table is not empty, False otherwise."""
        return not self.empty

    def __iter__(self) -> Iterator[Any]:
        """Iterate over all rows in the table as model instances."""
        yield from self.select()

    def __getitem__(self, key: Any) -> Any:
        """Return a single row from the table by its primary key.

        Args:
            key: The primary key value of the row to retrieve.

        Returns:
            Any: The model instance corresponding to the given primary key.

        Raises:
            KeyError: If no row is found for the given primary key.
        """
        result = self.select(f"{self.pk} = ?", [key])
        if len(result) == 0:
            raise KeyError(f"No row found for {self.pk} = {key}")  # noqa: TRY003

        return result[0]

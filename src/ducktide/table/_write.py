"""Write-side operations (insert / bulk insert) for the table interface.

This module defines :class:`WriteMixin`, which turns model instances into
parameterized ``INSERT`` statements. Multi-row inserts go through a Polars
frame and a single ``INSERT ... SELECT``; DuckDB's ``executemany`` runs one
statement per row, which is orders of magnitude slower.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

import duckdb
import polars as pl
from polars.datatypes import DataTypeClass

from ..exceptions import QueryError
from ..utils import sql
from ._base import TableBase

# Name under which a bulk-insert batch is registered on the connection for the
# duration of one ``INSERT ... SELECT``.
_BULK_SOURCE = "__ducktide_bulk_insert"

# Polars dtypes that do not survive the Arrow handoff to DuckDB: ``Object`` has
# no Arrow equivalent and 128-bit integers are rejected by DuckDB's reader.
_NON_ARROW_DTYPES = (pl.Object, pl.Int128, pl.UInt128)


def _arrow_compatible(dtype: pl.DataType | DataTypeClass) -> bool:
    """Return True if ``dtype``, including any nested dtypes, reaches DuckDB intact.

    Args:
        dtype: A Polars column dtype.

    Returns:
        False if the dtype or anything nested in it is one of ``_NON_ARROW_DTYPES``.
    """
    if isinstance(dtype, pl.Struct):
        return all(_arrow_compatible(field.dtype) for field in dtype.fields)
    if isinstance(dtype, pl.List | pl.Array):
        return _arrow_compatible(dtype.inner)
    return not any(dtype == bad for bad in _NON_ARROW_DTYPES)


def _uuids_as_text(column: list[Any]) -> list[Any]:
    """Return a UUID column as canonical strings, or the column unchanged.

    Polars has no UUID dtype and would hold UUIDs as ``Object``, which cannot
    reach DuckDB. As text they travel over Arrow, and DuckDB casts them back on
    insert: into a ``UUID`` column exactly, and into a ``VARCHAR`` column as the
    same canonical string a bound UUID parameter would produce.

    Args:
        column: One column's values; ``None`` marks a NULL.

    Returns:
        The column with every UUID replaced by ``str(uuid)`` if all its non-null
        values are UUIDs, else the column as given.
    """
    first = next((value for value in column if value is not None), None)
    if not isinstance(first, UUID) or not all(value is None or isinstance(value, UUID) for value in column):
        return column
    return [None if value is None else str(value) for value in column]


class WriteMixin(TableBase):
    """Insert and bulk-insert operations for a table."""

    def insert(self, *objs: Any) -> None:
        """Insert one or more model instances into the table.

        This is the primary method for adding data to the database. For a single
        object, it performs a simple INSERT. For multiple objects, it delegates
        to bulk_insert() for better performance.

        Args:
            *objs: One or more model instances.
                Can be either domain models or their ORM equivalents.

        Example:
            >>> from ducktide.db import DB
            >>> from ducktide.example import Foo
            >>> from ducktide.table import Table
            >>>
            >>> db = DB(tables_map={"foo": Table.of(Foo)})
            >>> foo1 = Foo(id=1, name="apple")
            >>> foo2 = Foo(id=2, name="banana")
            >>> db.insert(foo1, foo2)
            >>>
            >>> # Verify insertion
            >>> table = db.table[Foo]
            >>> len(table.select())
            2

        Raises:
            QueryError: If a database constraint (e.g., foreign key or primary key)
                is violated.

        Note:
            When inserting multiple objects, consider using bulk_insert() directly
            for optimal performance with large datasets.
        """
        self._require_writable("insert")
        if not objs:
            return

        if len(objs) == 1:
            # Single row insert
            obj = objs[0]
            placeholders = ", ".join("?" for _ in self.columns)
            cols = ", ".join(self.columns)
            # table_name and column names come from the ORM model class definition
            # (code, not user data); row values are bound via placeholders below.
            statement = sql.insert_row(self.table_name, cols, placeholders)

            try:
                self.connection.execute(statement, self._values_from_obj(obj))
            except duckdb.ConstraintException as exc:
                raise QueryError(f"Constraint violation inserting into '{self.table_name}': {exc}") from exc  # noqa: TRY003

        else:
            # Multiple rows → delegate to bulk_insert
            self.bulk_insert(objs)

    def bulk_insert(self, objs: Iterable[Any]) -> None:
        """Insert multiple objects into the table in one efficient operation.

        The rows are gathered into a Polars DataFrame and written with a
        single ``INSERT ... SELECT``, so the cost is dominated by building the
        frame rather than by per-row statement execution.

        Args:
            objs: An iterable of model instances whose attributes map to the
                table's column order defined in ``self.columns``.

        Example:
            >>> from ducktide.db import DB
            >>> from ducktide.example import Foo
            >>> from ducktide.table import Table
            >>>
            >>> db = DB(tables_map={"foo": Table.of(Foo)})
            >>>
            >>> # Create multiple Foo instances
            >>> foos = [Foo(id=i, name=f"item_{i}") for i in range(1, 101)]
            >>>
            >>> # Bulk insert for efficient batch processing
            >>> table = db.table[Foo]
            >>> table.bulk_insert(foos)
            >>>
            >>> # Verify all items were inserted
            >>> len(table.select())
            100

        Raises:
            QueryError: If a database constraint (e.g., foreign key or primary key)
                is violated. The batch is atomic, so no rows from a failed call
                remain in the table.

        Performance:
            UUID columns are sent as text and cast back by DuckDB. Values
            Polars cannot hand to DuckDB (ints beyond 64 bits, nested UUIDs,
            or a column mixing incompatible types) fall back to
            ``executemany``, which is correct but runs one statement per row.

        Atomicity:
            The whole batch is wrapped in an explicit transaction. DuckDB
            autocommits each statement otherwise, which would leave the rows
            written before a mid-batch constraint violation committed while the
            caller only saw the exception — and the obvious retry of the same
            batch would then collide on the primary keys it had just written.
        """
        self._require_writable("bulk_insert")
        objs = list(objs)
        if not objs:
            return

        cols = ", ".join(self.columns)
        values = [self._values_from_obj(obj) for obj in objs]
        frame = self._frame_from_values(values)

        self.connection.begin()
        try:
            if frame is None:
                placeholders = ", ".join("?" for _ in self.columns)
                self.connection.executemany(sql.insert_row(self.table_name, cols, placeholders), values)
            else:
                self.connection.register(_BULK_SOURCE, frame)
                try:
                    self.connection.execute(sql.insert_columns_from(self.table_name, cols, _BULK_SOURCE))
                finally:
                    self.connection.unregister(_BULK_SOURCE)
        except duckdb.ConstraintException as exc:
            self.connection.rollback()
            raise QueryError(f"Constraint violation inserting into '{self.table_name}': {exc}") from exc  # noqa: TRY003
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()

    def _frame_from_values(self, values: list[tuple[Any, ...]]) -> pl.DataFrame | None:
        """Build a column-wise DataFrame from row tuples, if Polars can hold them.

        Args:
            values: Row tuples in ``self.columns`` order.

        Returns:
            The DataFrame, or None when a column has values Polars cannot
            represent in a form DuckDB can read (inference fails, or yields a
            dtype in ``_NON_ARROW_DTYPES``). UUID columns are sent as text; see
            :func:`_uuids_as_text`.
        """
        data = {col: _uuids_as_text([row[i] for row in values]) for i, col in enumerate(self.columns)}
        try:
            frame = pl.DataFrame(data, strict=True)
        except (TypeError, ValueError, OverflowError, pl.exceptions.PolarsError):
            return None
        return frame if all(_arrow_compatible(dtype) for dtype in frame.dtypes) else None

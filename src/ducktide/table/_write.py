"""Write-side operations (insert / bulk insert) for the table interface.

This module defines :class:`WriteMixin`, which turns model instances into
parameterized ``INSERT`` statements, delegating multi-row inserts to DuckDB's
batch ``executemany`` for efficiency.
"""

from collections.abc import Iterable
from typing import Any

import duckdb

from ..exceptions import QueryError
from ._base import TableBase


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

        Raises:
            QueryError: If a database constraint (e.g., foreign key or primary key)
                is violated.

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
            sql = f"INSERT INTO {self.table_name} ({cols}) VALUES ({placeholders})"  # nosec B608  # noqa: S608

            try:
                self.connection.execute(sql, self._values_from_obj(obj))
            except duckdb.ConstraintException as exc:
                raise QueryError(f"Constraint violation inserting into '{self.table_name}': {exc}") from exc  # noqa: TRY003

        else:
            # Multiple rows → delegate to bulk_insert
            self.bulk_insert(objs)

    def bulk_insert(self, objs: Iterable[Any]) -> None:
        """Insert multiple objects into the table in one efficient operation.

        This method is optimized for inserting many records at once, using
        DuckDB's executemany() for batch processing. It's significantly faster
        than calling insert() in a loop for large datasets.

        Args:
            objs: An iterable of model instances whose attributes map to the
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

        Raises:
            QueryError: If a database constraint (e.g., foreign key or primary key)
                is violated.

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
        """  # nosec B608  # noqa: S608

        values = [self._values_from_obj(obj) for obj in objs]
        try:
            self.connection.executemany(sql, values)
        except duckdb.ConstraintException as exc:
            raise QueryError(f"Constraint violation inserting into '{self.table_name}': {exc}") from exc  # noqa: TRY003

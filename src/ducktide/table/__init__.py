"""Database table interface for the ducktide ORM system.

This package provides the Table class, which serves as a repository-pattern
interface for performing database operations on specific tables.

The implementation is split across cohesive submodules, all composed into the
single public :class:`Table` class:

- :mod:`._base` — shared connection/metadata state and helpers.
- :mod:`._query` — read-side query construction, lookups and the collection protocol.
- :mod:`._write` — insert and bulk-insert operations.
- :mod:`._io` — DataFrame conversion and CSV/Parquet import/export.
"""

from ._io import IOMixin
from ._query import QueryMixin
from ._write import WriteMixin

__all__ = ["Table"]


class Table(WriteMixin, QueryMixin, IOMixin):
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

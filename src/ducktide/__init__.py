"""Database management and persistence utilities.

This package provides the core database infrastructure for JQR, including:

- **DB**: Base database connection management with DuckDB
- **Table**: Repository-pattern interface for CRUD operations
- **Exceptions**: Custom exception hierarchy for database errors
- **Context**: Context-scoped default database management
- **ORM Base**: Base classes for ORM model definitions
- **Time Series**: Specialized time series data management

The database layer follows a two-database architecture:
1. **Entity Database** (via `DB`): For entity metadata with relational structure
2. **Time Series Database** (via `TimeSeriesDB`): For high-volume numerical data

Example:
    >>> from functools import partial
    >>> from jqr.database import DB, Table
    >>> from jqr.database.orm.example import FooORM, Foo
    >>>
    >>> # Create database with FooORM table
    >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
    >>> foo = Foo(id=1, name="example")
    >>> db.insert(foo)
    >>>
    >>> # Query the data
    >>> table = db.table[Foo]
    >>> result = table.select()
    >>> len(result)
    1
    >>> result[0].name
    'example'

Note:
    This is a low-level database layer. For high-level operations with
    specific domain models, consider using a higher-level package that builds
    on top of this infrastructure.
"""

from . import context, exceptions, orm
from .db import DB
from .table import Table
from .time import TimeSeriesDB, TimeSeriesModel, TimeSeriesRepository

__all__ = ["DB", "TimeSeriesDB", "TimeSeriesModel", "TimeSeriesRepository", "Table", "context", "exceptions", "orm"]

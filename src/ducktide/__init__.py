"""Database management and persistence utilities.

This package provides the core database infrastructure for ducktide, including:

- **DB**: Base database connection management with DuckDB
- **Table**: Repository-pattern interface for CRUD operations
- **Exceptions**: Custom exception hierarchy for database errors
- **Context**: Context-scoped default database management
- **DomainModel**: Optional frozen base for the Pydantic models tables are built from
- **Time Series**: Specialized time series data management

The database layer follows a two-database architecture:
1. **Entity Database** (via `DB`): For entity metadata with relational structure
2. **Time Series Database** (via `TimeSeriesDB`): For high-volume numerical data

Example:
    >>> from ducktide import DB, Table
    >>> from ducktide.example import Foo
    >>>
    >>> # One model is both the domain object and the table definition
    >>> db = DB(tables_map={"foo": Table.of(Foo)})
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

from . import context, exceptions
from .db import DB
from .model import DomainModel
from .table import Table
from .time import TimeSeriesDB, TimeSeriesModel, TimeSeriesRepository

__all__ = [
    "DB",
    "DomainModel",
    "Table",
    "TimeSeriesDB",
    "TimeSeriesModel",
    "TimeSeriesRepository",
    "context",
    "exceptions",
]

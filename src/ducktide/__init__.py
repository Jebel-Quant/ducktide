"""Database management and persistence utilities.

This package provides the core database infrastructure for JQR, including:

- **DB**: Base database connection management with DuckDB
- **Table**: Repository-pattern interface for CRUD operations
- **Exceptions**: Custom exception hierarchy for database errors
- **Context**: Context-scoped default database management
- **ORM Base**: Base classes for ORM model definitions
- **Time Series**: Specialized time series data management

The database layer follows a two-database architecture:
1. **Entity Database** (via `Database`): For Publisher, Future, Contract metadata
2. **Time Series Database** (via `TimeSeriesDB`): For high-volume numerical data

Example:
    >>> from jqr.orm import Database
    >>> from jqr.orm.models import Publisher
    >>> db = Database()
    >>> publisher = Publisher(publisher_id=1, name="CME", dataset="GLBX.MDP3", venue="GLBX")
    >>> db.publisher.insert(publisher)
"""

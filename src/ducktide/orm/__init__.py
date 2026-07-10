"""Object-Relational Mapping (ORM) utilities.

This package provides the base infrastructure for the lightweight ORM system
used throughout JQR. It includes:

- **ORMModel**: Base class for all ORM models with schema definitions
- Schema generation and SQL statement construction
- Row-to-object mapping utilities

The ORM layer is intentionally minimal and avoids heavy dependencies like
SQLAlchemy or SQLModel, providing just enough structure to support the
Repository pattern used in JQR.

Note on naming (`jqr.database.orm` vs `jqr.orm.models`):
    This package (`jqr.database.orm`) is the **generic, domain-agnostic ORM
    framework** — the reusable ``ORMModel``/``DomainModel`` base classes plus
    schema/SQL machinery. It knows nothing about futures.

    The **domain models** that build on top of it — ``Publisher``, ``Future``,
    ``Contract`` — live in :mod:`jqr.orm.models`. Both packages share the "orm"
    token but sit at different layers: ``jqr.database.orm`` is infrastructure,
    ``jqr.orm.models`` is the futures-specific application layer that subclasses
    it.

Note:
    Models do NOT have save(), find(), or delete() methods. All database
    operations must go through the Database table interface, following the
    Repository pattern.
"""

from . import example
from .base import DomainModel, ORMModel

__all__ = ["DomainModel", "ORMModel", "example"]

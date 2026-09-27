"""Object-Relational Mapping (ORM) utilities.

This package provides the base infrastructure for ducktide's lightweight ORM
system. It includes:

- **ORMModel**: Base class for all ORM models with schema definitions
- Schema generation and SQL statement construction
- Row-to-object mapping utilities

The ORM layer is intentionally minimal and avoids heavy dependencies like
SQLAlchemy or SQLModel, providing just enough structure to support the
Repository pattern.

This package is domain-agnostic: applications define their own models by
subclassing ``DomainModel`` (the immutable domain object) and ``ORMModel``
(its table mapping). See :mod:`ducktide.orm.example` for a minimal pair.

Note:
    Models do NOT have save(), find(), or delete() methods. All database
    operations must go through the Database table interface, following the
    Repository pattern.
"""

from .base import DomainModel, ORMModel

__all__ = ["DomainModel", "ORMModel"]

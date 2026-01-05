"""Object-Relational Mapping (ORM) utilities.

This package provides the base infrastructure for the lightweight ORM system
used throughout JQR. It includes:

- **ORMModel**: Base class for all ORM models with schema definitions
- Schema generation and SQL statement construction
- Row-to-object mapping utilities

The ORM layer is intentionally minimal and avoids heavy dependencies like
SQLAlchemy or SQLModel, providing just enough structure to support the
Repository pattern used in JQR.

Note:
    Models do NOT have save(), find(), or delete() methods. All database
    operations must go through the Database table interface, following the
    Repository pattern.
"""

"""Base ORM class for database operations.

This module provides a lightweight object-relational mapping (ORM) system
for interacting with databases using a DB-API 2.0 compatible interface
(PEP 249), without external dependencies like SQLAlchemy or SQLModel.

API Design
----------
This ORM follows the **Repository/Table Pattern** where all database operations
are performed through table interfaces provided by the Database class:

    from jqr.orm import Database, Publisher

    db = Database()

    # Create model instances
    publisher = Publisher(publisher_id=1, name="CME", dataset="GLBX.MDP3", venue="GLBX")

    # Perform operations via table interface
    db.publisher.insert(publisher)         # Insert
    all_pubs = db.publisher.select()        # Query all
    filtered = db.publisher.select("venue = ?", ["GLBX"])  # Query with filter

Models are immutable Pydantic dataclasses that represent domain entities.
They do NOT have save(), find(), or delete() methods. All persistence
operations go through the Database table interfaces.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class for domain models.

    Provides a generic `from_row` method for creating instances from database rows.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Self:
        """Create a model instance from a database row.

        Args:
            row: Tuple of values from a database query.

        Returns:
            A new instance of the model.
        """
        # If we have _columns (from ORMModel mixin), use them.
        # Otherwise, fall back to pydantic model_fields.
        if hasattr(cls, "_columns"):
            columns = cls._columns
        else:
            columns = list(cls.model_fields.keys())

        return cls(**dict(zip(columns, row)))


class ORMModel(ABC):
    """Base class for ORM models with schema definitions.

    This class provides schema and metadata for database tables. It is used
    internally by the Database/Table interface and should not be instantiated
    directly by users.

    **Important**: All database operations must be performed through the Database
    table interface. Model classes do NOT
    provide save(), find(), find_one(), or delete() methods. This is an intentional
    design decision to maintain a clear separation between domain models and
    persistence logic, following the Repository pattern.

    Usage Example:
        from jqr.orm import Database, Publisher

        db = Database()
        publisher = Publisher(publisher_id=1, dataset="GLBX.MDP3", venue="GLBX")

        # ✓ Correct: Use table interface
        db.publisher.insert(publisher)
        all_publishers = db.publisher.select()

        # ✗ Incorrect: Models don't have these methods
        # publisher.save()  # This will NOT work
        # Publisher.find()  # This will NOT work

    Attributes:
        _table_name: Name of the database table (must be set by subclasses).
        _primary_key: Name of the primary key field (default: 'id').
        _schema: Schema definition mapping field names to SQL types.
        _columns: List of column names in database order.
    """

    _table_name: ClassVar[str] = ""
    _primary_key: ClassVar[str] = "id"

    _schema: ClassVar[dict[str, str]]  # schema definition
    _columns: ClassVar[list[str]]  # column order in the database
    _domain_model: ClassVar[type | None] = None  # domain model class

    def __init_subclass__(cls, **kwargs):
        """Initialize subclass and automatically set _columns if not provided."""
        super().__init_subclass__(**kwargs)

        # Automatically determine _columns from _schema keys if not explicitly defined
        if not hasattr(cls, "_columns") or cls._columns is getattr(ORMModel, "_columns", None):
            if hasattr(cls, "_schema"):
                # Filter out entries that are not columns (e.g., FOREIGN KEY constraints)
                cls._columns = [k for k in cls._schema.keys() if " " not in k and "(" not in k]

    @classmethod
    def generate_create_table_sql(cls):
        """Generate a CREATE TABLE SQL statement from the model's fields."""
        table_name = cls._table_name
        fields = cls._schema

        field_definitions = []
        for field_name, field_type in fields.items():
            field_definitions.append(f"{field_name} {field_type}")

        field_definitions_str = ",\n    ".join(field_definitions)
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n    {field_definitions_str}\n);"

    @classmethod
    def _from_row(cls, row: tuple[Any, ...]) -> Self:
        """Create a model instance from a database row.

        Args:
            row: Tuple of values from a database query.

        Returns:
            A new instance of the model.
        """
        if hasattr(cls, "from_row"):
            return cls.from_row(row)

        return cls(**dict(zip(cls._columns, row)))

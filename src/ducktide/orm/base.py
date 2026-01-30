"""Base ORM class for database operations.

This module provides a lightweight object-relational mapping (ORM) system
for interacting with databases using a DB-API 2.0 compatible interface
(PEP 249), without external dependencies like SQLAlchemy or SQLModel.

API Design
----------
This ORM follows the **Repository/Table Pattern** where all database operations
are performed through table interfaces provided by the Database class.

Key Features:
    - Schema-driven table creation
    - Automatic column inference from schema
    - Type-safe row-to-object conversion
    - SQL generation for table initialization
    - Separation of domain models and persistence logic

Example:
    >>> from functools import partial
    >>> from jqr.database.db import DB
    >>> from jqr.database.orm.example import FooORM, Foo
    >>> from jqr.database.table import Table
    >>>
    >>> # Create database and insert data
    >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
    >>> foo = Foo(id=1, name="widget")
    >>> db.insert(foo)
    >>>
    >>> # Query the data
    >>> table = db.table[FooORM]
    >>> results = table.select()
    >>> results[0].name
    'widget'
    >>>
    >>> # Generate SQL for schema inspection
    >>> sql = FooORM.generate_create_table_sql()
    >>> "CREATE TABLE" in sql
    True

Design Philosophy:
    Models are immutable Pydantic dataclasses that represent domain entities.
    They do NOT have save(), find(), or delete() methods. All persistence
    operations go through the Database table interfaces, maintaining a clean
    separation between domain logic and data access.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class for domain models.

    This class provides a common base for all domain models in JQR,
    ensuring consistent configuration and automatic table name inference.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


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

    Example:
        >>> from functools import partial
        >>> from jqr.database import DB
        >>> from jqr.database.orm.example import FooORM
        >>> from jqr.database.table import Table
        >>>
        >>> # FooORM is a concrete implementation of ORMModel
        >>> db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
        >>> foo1 = FooORM(id=1, name="alpha")
        >>> foo2 = FooORM(id=2, name="beta")
        >>> db.insert(foo1, foo2)
        >>>
        >>> # Access via table interface
        >>> for foo in db.table[FooORM]:
        ...     print(foo.id)
        1
        2

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

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Initialize subclass and automatically set _columns if not provided.

        This hook is called when a new subclass of ORMModel is created. It
        automatically infers the _columns list from the _schema dictionary,
        filtering out non-column entries like FOREIGN KEY constraints.

        Example:
            >>> from jqr.database.orm.base import ORMModel
            >>>
            >>> # Define a model with _schema but no _columns
            >>> class BarORM(ORMModel):
            ...     _table_name = "bar"
            ...     _schema = {
            ...         "id": "INTEGER PRIMARY KEY",
            ...         "value": "REAL",
            ...         "FOREIGN KEY (id)": "REFERENCES foo(id)"
            ...     }
            ...     def __init__(self, id, value):
            ...         self.id = id
            ...         self.value = value
            >>>
            >>> # _columns is automatically set, excluding FOREIGN KEY
            >>> BarORM._columns
            ['id', 'value']

        Note:
            This is an internal method called automatically during class
            definition. Users don't need to call it directly.
        """
        super().__init_subclass__(**kwargs)

        # Automatically determine _table_name if not explicitly defined or is empty
        if not cls._table_name:
            # Infer from class name with suffix stripping
            name = cls.__name__.lower()
            for suffix in ("ormmodel", "model", "orm"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            cls._table_name = name

        # Automatically determine _columns from _schema keys if not explicitly defined
        if not hasattr(cls, "_columns") or cls._columns is getattr(ORMModel, "_columns", None):
            if hasattr(cls, "_schema"):
                # Filter out entries that are not columns (e.g., FOREIGN KEY constraints)
                cls._columns = [k for k in cls._schema.keys() if " " not in k and "(" not in k]

    @classmethod
    def generate_create_table_sql(cls) -> str:
        """Generate a CREATE TABLE SQL statement from the model's schema definition.

        This method constructs a SQL CREATE TABLE statement using the model's
        _schema and _table_name class variables. It's used internally during
        database initialization to set up tables.

        Returns:
            str: A SQL CREATE TABLE IF NOT EXISTS statement.

        Example:
            >>> from jqr.database.orm.example import FooORM
            >>> sql = FooORM.generate_create_table_sql()
            >>> print(sql)  # doctest: +NORMALIZE_WHITESPACE
            CREATE TABLE IF NOT EXISTS foo (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );

        Note:
            This is an internal method typically called by the Database class
            during initialization. Users don't need to call it directly.
        """
        table_name = cls._table_name
        fields = cls._schema

        field_definitions = []
        for field_name, field_type in fields.items():
            field_definitions.append(f"{field_name} {field_type}")

        field_definitions_str = ",\n    ".join(field_definitions)
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n    {field_definitions_str}\n);"

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Self:
        """Create a model instance from a database row tuple.

        This method is used internally by the Table class to convert raw
        database query results into model instances.

        Args:
            row: Tuple of values from a database query, in the same order
                as the model's _columns definition.

        Returns:
            Self: A new instance of the model class populated with values
                from the database row.

        Example:
            >>> from typing import ClassVar
            >>> from pydantic import BaseModel
            >>> class ModelClass(ORMModel, BaseModel):
            ...     id: int
            ...     name: str
            ...     _primary_key: ClassVar[str] = "id"
            ...     _schema: ClassVar[dict[str, str]] = {"id": "int", "name": "str"}
            >>> # Simulate a database row result
            >>> row = (42, "test_name")
            >>> foo = ModelClass.from_row(row)
            >>> foo.id
            42
            >>> foo.name
            'test_name'

        Note:
            This is an internal method typically called by Table.select().
            Users don't need to call it directly - use the Table interface instead.
        """
        columns = cls._columns
        return cls(**dict(zip(columns, row, strict=False)))

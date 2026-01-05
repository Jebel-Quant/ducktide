"""Example ORM model for testing and demonstration."""

from typing import ClassVar

from ..time import TimeSeriesModel
from .base import DomainModel, ORMModel


class Foo(DomainModel, TimeSeriesModel):
    """A simple domain model representing a generic instrument.

    This model serves as a demonstration of how to combine Pydantic's
    `BaseModel` (via `DomainModel`) with `TimeSeriesModel` for
    time-series data access.

    Example:
        >>> foo = Foo(id=1, name="Widget")
        >>> foo.id
        1
        >>> foo.name
        'Widget'
        >>> foo.table_name
        'foo'
        >>> foo.instrument_id
        1
    """

    id: int = 1
    name: str = ""

    @property
    def instrument_id(self) -> int | None:
        """Return the canonical numeric identifier for this instrument."""
        return self.id


class FooORM(ORMModel, Foo):
    """ORM representation of the Foo model.

    This class provides the database schema and mapping for the `Foo` domain
    model, enabling persistence via the `Table` and `Database` interfaces.

    Example:
        >>> # Create an ORM instance
        >>> foo_orm = FooORM(id=42, name="Persistence")
        >>> foo_orm.id
        42
        >>> # Row-to-object mapping
        >>> row = (100, "Mapped")
        >>> foo = FooORM.from_row(row)
        >>> foo.name
        'Mapped'
    """

    _domain_model: ClassVar[type] = Foo
    _primary_key: ClassVar[str] = "id"
    _schema: ClassVar[dict[str, str]] = {
        "id": "INTEGER PRIMARY KEY",
        "name": "TEXT NOT NULL",
    }

"""Example model for testing and demonstration."""

from typing import ClassVar

from .model import DomainModel
from .time import TimeSeriesModel


class Foo(DomainModel, TimeSeriesModel):
    """A simple domain model representing a generic instrument.

    One class serves as both the domain object and the table: its fields are the
    columns, and rows read back from ``Table.of(Foo)`` are ``Foo`` instances.
    ``TimeSeriesModel`` adds time-series access keyed by ``instrument_id``.

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

    table_name: ClassVar[str] = "foo"

    id: int = 1
    name: str = ""

    @property
    def instrument_id(self) -> int | None:
        """Return the canonical numeric identifier for this instrument."""
        return self.id

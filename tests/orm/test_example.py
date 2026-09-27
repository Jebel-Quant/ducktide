"""Unit tests for the example.py models (Foo and FooORM).

This module tests the example domain model and ORM model that are used
for demonstration and testing purposes throughout the codebase.
"""

from __future__ import annotations

from functools import partial

import pytest

from ducktide.db import DB
from ducktide.orm.example import Foo, FooORM
from ducktide.table import Table


@pytest.fixture
def db():
    """Provide a fresh in-memory database with FooORM table."""
    tables_map = {
        "foo": partial(Table, model_class=FooORM),
    }
    with DB(tables_map=tables_map) as db:
        yield db


class TestFoo:
    """Tests for the Foo domain model."""

    def test_foo_domain_model_creation(self):
        """Foo domain model should accept basic fields and preserve values."""
        foo = Foo(id=1, name="Widget")
        assert foo.id == 1
        assert foo.name == "Widget"

    def test_foo_domain_model_defaults(self):
        """Foo domain model should use default values when not provided."""
        foo = Foo()
        assert foo.id == 1
        assert foo.name == ""

    def test_foo_table_name(self):
        """Foo should have correct table_name set automatically."""
        foo = Foo(id=1, name="Test")
        assert foo.table_name == "foo"

    def test_foo_instrument_id(self):
        """Foo.instrument_id should return the id field."""
        foo = Foo(id=42, name="Test")
        assert foo.instrument_id == 42

    def test_foo_instrument_id_default(self):
        """Foo.instrument_id should return default id value."""
        foo = Foo()
        assert foo.instrument_id == 1

    def test_foo_immutability(self):
        """Foo domain model should be immutable (frozen)."""
        foo = Foo(id=1, name="Test")
        try:
            foo.name = "Modified"
            raise AssertionError("Expected ValueError when trying to modify frozen model")  # noqa: TRY003
        except (ValueError, TypeError):
            # Pydantic raises one of these for frozen models
            pass


class TestFooORM:
    """Tests for the FooORM persistence model."""

    def test_foo_orm_creation(self):
        """FooORM should be instantiable with basic fields."""
        foo_orm = FooORM(id=42, name="Persistence")
        assert foo_orm.id == 42
        assert foo_orm.name == "Persistence"

    def test_foo_orm_from_row(self):
        """FooORM.from_row should correctly map database row to object."""
        row = (100, "Mapped")
        foo = FooORM.from_row(row)
        assert foo.id == 100
        assert foo.name == "Mapped"

    def test_foo_orm_schema(self):
        """FooORM should have correct schema definition."""
        assert FooORM._schema == {
            "id": "INTEGER PRIMARY KEY",
            "name": "TEXT NOT NULL",
        }

    def test_foo_orm_primary_key(self):
        """FooORM should have correct primary key defined."""
        assert FooORM._primary_key == "id"

    def test_foo_orm_domain_model(self):
        """FooORM should reference the correct domain model class."""
        assert FooORM._domain_model is Foo

    def test_foo_orm_model_dump(self):
        """FooORM should correctly serialize to dictionary."""
        foo_orm = FooORM(id=1, name="Test")
        d = foo_orm.model_dump()
        assert d["id"] == 1
        assert d["name"] == "Test"

    def test_foo_orm_insert_roundtrip(self, db):
        """Insert and fetch Foo via the database table interface."""
        # Insert a Foo domain model
        foo = Foo(id=1, name="Widget")
        db.foo.insert(foo)

        # Verify insert by selecting
        got_list = db.foo.select(where_clause="id = ?", where_params=[1])
        assert len(got_list) == 1
        got = got_list[0]
        assert got is not None
        assert got.id == 1
        assert got.name == "Widget"

    def test_foo_orm_insert_multiple(self, db):
        """Insert multiple Foo instances and query all."""
        db.foo.insert(Foo(id=1, name="Alpha"))
        db.foo.insert(Foo(id=2, name="Beta"))
        db.foo.insert(Foo(id=3, name="Gamma"))

        all_foos = db.foo.select()
        assert len(all_foos) == 3

        # Check that all entries are present
        names = {f.name for f in all_foos}
        assert names == {"Alpha", "Beta", "Gamma"}

    def test_foo_orm_select_with_filter(self, db):
        """Insert multiple and query with where clause."""
        db.foo.insert(Foo(id=1, name="Widget"))
        db.foo.insert(Foo(id=2, name="Gadget"))
        db.foo.insert(Foo(id=3, name="Widget"))

        # Select only "Widget" entries
        widgets = db.foo.select(where_clause="name = ?", where_params=["Widget"])
        assert len(widgets) == 2
        assert all(f.name == "Widget" for f in widgets)

        # Select by id
        gadgets = db.foo.select(where_clause="id = ?", where_params=[2])
        assert len(gadgets) == 1
        assert gadgets[0].name == "Gadget"

    def test_foo_orm_empty_select(self, db):
        """Select from empty table should return empty list."""
        all_foos = db.foo.select()
        assert len(all_foos) == 0
        assert all_foos == []

    def test_foo_orm_inheritance(self):
        """FooORM should inherit from both ORMModel and Foo."""
        foo_orm = FooORM(id=1, name="Test")

        # Check it's an instance of Foo (domain model)
        assert isinstance(foo_orm, Foo)

        # Check it has ORM capabilities
        assert hasattr(FooORM, "_schema")
        assert hasattr(FooORM, "_primary_key")
        assert hasattr(FooORM, "_domain_model")

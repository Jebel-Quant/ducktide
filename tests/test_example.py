"""Unit tests for the example Foo model and the table built from it.

Foo is both the domain object and the table definition, so the round-trip
tests check that rows come back as ``Foo`` instances.
"""

from __future__ import annotations

import pytest

from ducktide.db import DB
from ducktide.example import Foo
from ducktide.model import column_definitions
from ducktide.table import Table


@pytest.fixture
def db():
    """Provide a fresh in-memory database with a table for Foo."""
    with DB(tables_map={"foo": Table.of(Foo)}) as db:
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


class TestFooTable:
    """Tests for the table derived from Foo."""

    def test_foo_table_schema(self):
        """The schema is derived from Foo's fields."""
        assert column_definitions(Foo) == {"id": "BIGINT PRIMARY KEY", "name": "VARCHAR NOT NULL"}

    def test_foo_table_insert_roundtrip(self, db):
        """Insert and fetch Foo via the database table interface."""
        # Insert a Foo domain model
        foo = Foo(id=1, name="Widget")
        db.foo.insert(foo)

        # Verify insert by selecting
        got_list = db.foo.select(where_clause="id = ?", where_params=[1])
        assert len(got_list) == 1
        got = got_list[0]
        assert type(got) is Foo
        assert got.id == 1
        assert got.name == "Widget"

    def test_foo_table_insert_multiple(self, db):
        """Insert multiple Foo instances and query all."""
        db.foo.insert(Foo(id=1, name="Alpha"))
        db.foo.insert(Foo(id=2, name="Beta"))
        db.foo.insert(Foo(id=3, name="Gamma"))

        all_foos = db.foo.select()
        assert len(all_foos) == 3

        # Check that all entries are present
        names = {f.name for f in all_foos}
        assert names == {"Alpha", "Beta", "Gamma"}

    def test_foo_table_select_with_filter(self, db):
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

    def test_foo_table_empty_select(self, db):
        """Select from empty table should return empty list."""
        all_foos = db.foo.select()
        assert len(all_foos) == 0
        assert all_foos == []

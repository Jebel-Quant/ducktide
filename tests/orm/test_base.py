"""Tests for the ORMModel abstract base class in ducktide.base."""

from __future__ import annotations

from abc import ABC
from typing import ClassVar

from ducktide.orm.base import DomainModel, ORMModel


class MockORMModel(ORMModel, DomainModel):
    """A concrete implementation of ORMModel for testing."""

    test_id: int | None = None
    name: str = ""
    value: float = 0.0

    _primary_key: ClassVar[str] = "test_id"
    _schema: ClassVar[dict[str, str]] = {
        "test_id": "INTEGER PRIMARY KEY",
        "name": "TEXT NOT NULL",
        "value": "REAL",
    }


class TestDomainModel:
    """Tests for the DomainModel base class."""

    def test_mock_model_io(self):
        """Verify basic IO methods of the mock implementation."""
        model = MockORMModel(test_id=1, name="test", value=1.5)

        # test _to_dict
        assert model.model_dump() == {"test_id": 1, "name": "test", "value": 1.5}

        # test from_row directly
        model2b = MockORMModel.from_row((2, "other", 2.5))
        assert model2b.test_id == 2
        assert model2b.name == "other"
        assert model2b.value == 2.5


class TestORMModel:
    """Tests for the ORMModel abstract base class."""

    def test_orm_model_abstract(self):
        """Verify that ORMModel is an ABC."""
        assert issubclass(ORMModel, ABC)

    def test_generate_create_table_sql(self):
        """Verify that generate_create_table_sql produces correct SQL."""
        expected_sql = (
            "CREATE TABLE IF NOT EXISTS mock (\n"
            "    test_id INTEGER PRIMARY KEY,\n"
            "    name TEXT NOT NULL,\n"
            "    value REAL\n"
            ");"
        )
        assert MockORMModel.generate_create_table_sql() == expected_sql

    def test_default_primary_key(self):
        """Verify that _primary_key defaults to 'id'."""

        class DefaultPKModel(ORMModel, DomainModel):
            """Minimal model used to verify the default primary key."""

            id: int = 1
            _schema: ClassVar[dict[str, str]] = {"id": "INTEGER PRIMARY KEY"}

        assert DefaultPKModel._primary_key == "id"
        assert DefaultPKModel._table_name == "defaultpk"

        model = DefaultPKModel()
        assert model.id == 1

    def test_table_name_without_known_suffix(self):
        """Verify table-name inference when the class name has no ORM/Model suffix."""

        class Gadget(ORMModel, DomainModel):
            """Model with a name lacking a known suffix for table-name inference."""

            gadget_id: int = 1
            _primary_key: ClassVar[str] = "gadget_id"
            _schema: ClassVar[dict[str, str]] = {"gadget_id": "INTEGER PRIMARY KEY"}

        # No suffix to strip: the lowercased class name is used as-is
        assert Gadget._table_name == "gadget"

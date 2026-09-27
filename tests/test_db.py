"""Tests for the ducktide.db.DB class."""

from __future__ import annotations

from typing import Any, ClassVar

import duckdb
import pytest

from ducktide.db import DB
from ducktide.orm.base import ORMModel
from ducktide.table import Table


class MockORMModel(ORMModel):
    """A minimal mock ORM model for testing."""

    _table_name: ClassVar[str] = "test_table"
    _primary_key: ClassVar[str] = "id"
    _columns: ClassVar[list[str]] = ["id", "name"]
    _schema: ClassVar[dict[str, str]] = {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
    _domain_model: ClassVar[type | None] = object  # Mock domain model

    def __init__(self, id: int = 1, name: str = "test"):
        """Initialize the MockORMModel."""
        self.id = id
        self.name = name

    def _to_dict(self) -> dict[str, Any]:
        """Return the model as a dict (mock)."""
        return {}

    @classmethod
    def _from_row(cls, row: tuple[Any, ...]) -> MockORMModel:
        """Build a model instance from a database row (mock)."""
        return cls()

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> MockORMModel:
        """Build a model instance from a dict (mock)."""
        return cls()


class MockTable(Table):
    """A minimal mock table for testing."""

    def __init__(self, connection, read_only=False):
        """Initialize the MockTable.

        :param connection: The database connection.
        :param read_only: Whether the table is read-only.
        """
        super().__init__(connection, MockORMModel, read_only=read_only)


class NoDomainORMModel(ORMModel):
    """A mock ORM model without an associated domain model."""

    _table_name: ClassVar[str] = "no_domain_table"
    _primary_key: ClassVar[str] = "id"
    _columns: ClassVar[list[str]] = ["id"]
    _schema: ClassVar[dict[str, str]] = {"id": "INTEGER PRIMARY KEY"}
    _domain_model: ClassVar[type | None] = None

    def __init__(self, id: int = 1):
        """Initialize the NoDomainORMModel."""
        self.id = id

    def _to_dict(self) -> dict[str, Any]:
        """Return the model as a dict (mock)."""
        return {"id": self.id}

    @classmethod
    def _from_row(cls, row: tuple[Any, ...]) -> NoDomainORMModel:
        """Build a model instance from a database row (mock)."""
        return cls(*row)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> NoDomainORMModel:
        """Build a model instance from a dict (mock)."""
        return cls(id=data["id"])


class NoDomainTable(Table):
    """Table for NoDomainORMModel."""

    def __init__(self, connection, read_only=False):
        """Initialize the NoDomainTable.

        :param connection: The database connection.
        :param read_only: Whether the table is read-only.
        """
        super().__init__(connection, NoDomainORMModel, read_only=read_only)


class TestDB:
    """Tests for the generic DB wrapper."""

    def test_init_memory(self):
        """Test initializing an in-memory database."""
        db = DB(tables_map={}, db_path=":memory:")
        assert db.db_path == ":memory:"
        assert db.read_only is False
        assert isinstance(db.connection, duckdb.DuckDBPyConnection)
        db.close()

    def test_init_file(self, tmp_path):
        """Test initializing a file-based database."""
        db_path = tmp_path / "test.duckdb"
        db = DB(tables_map={}, db_path=str(db_path))
        assert db.db_path == str(db_path)
        assert db_path.exists()
        db.close()

    def test_init_readonly(self, tmp_path):
        """Test initializing a read-only database."""
        db_path = tmp_path / "test_ro.duckdb"
        # Create it first
        duckdb.connect(str(db_path)).close()

        db = DB(tables_map={}, db_path=str(db_path), read_only=True)
        assert db.read_only is True

        # Verify read-only by trying to write
        with pytest.raises(duckdb.InvalidInputException):
            db.execute_query("CREATE TABLE test (id INTEGER)")

        db.close()

    def test_execute_query(self):
        """Test executing a query with and without parameters."""
        db = DB(tables_map={}, db_path=":memory:")
        db.execute_query("CREATE TABLE test (id INTEGER, name TEXT)")

        # Without params
        db.execute_query("INSERT INTO test VALUES (1, 'alice')")

        # With params
        db.execute_query("INSERT INTO test VALUES (?, ?)", [2, "bob"])

        res = db.execute_query("SELECT * FROM test ORDER BY id").fetchall()
        assert len(res) == 2
        assert res[0] == (1, "alice")
        assert res[1] == (2, "bob")
        db.close()

    def test_cursor(self):
        """Test cursor method."""
        db = DB(tables_map={}, db_path=":memory:")
        cursor = db.cursor()
        assert hasattr(cursor, "execute")
        db.close()

    def test_commit(self):
        """Test commit method (DuckDB handles transactions, but we expose the method)."""
        db = DB(tables_map={}, db_path=":memory:")
        # Should not raise
        db.commit()
        db.close()

    def test_context_manager(self, tmp_path):
        """Test context manager support."""
        db_path = tmp_path / "ctx.duckdb"
        with DB(tables_map={}, db_path=str(db_path)) as db:
            assert isinstance(db, DB)
            db.execute_query("CREATE TABLE t (id INT)")
            # connection is open
            db.execute_query("SELECT 1")

        # connection should be closed after exit
        # DuckDB connections don't have a simple 'is_closed' attribute that is updated immediately in all versions
        # but trying to use it should fail if it's truly closed.
        with pytest.raises(duckdb.ConnectionException):
            db.execute_query("SELECT 1")

    def test_close(self):
        """Test manual close."""
        db = DB(tables_map={}, db_path=":memory:")
        db.close()
        with pytest.raises(duckdb.ConnectionException):
            db.execute_query("SELECT 1")

    def test_drop_all_tables(self):
        """Verify that drop_all_tables removes all tables from the database."""
        with DB(tables_map={}) as db:
            db.execute_query("CREATE TABLE t1 (id INTEGER)")
            db.execute_query("CREATE TABLE t2 (id INTEGER)")
            assert "t1" in [r[0] for r in db.execute_query("SHOW TABLES").fetchall()]
            assert "t2" in [r[0] for r in db.execute_query("SHOW TABLES").fetchall()]

            db.drop_all_tables()

            tables = db.execute_query("SHOW TABLES").fetchall()
            assert len(tables) == 0

    def test_initialize_tables_and_model_mapping(self):
        """Verify that tables are initialized and _model_to_table is populated."""
        tables_map = {"test_table": MockTable}
        with DB(tables_map=tables_map) as db:
            assert hasattr(db, "test_table")
            assert isinstance(db.test_table, MockTable)
            # Check model mapping (ORM model)
            assert db._model_to_table[MockORMModel] == db.test_table
            # Check model mapping (Domain model)
            assert db._model_to_table[object] == db.test_table

    def test_insert_valid_object(self):
        """Test inserting a valid object."""
        tables_map = {"test_table": MockTable}
        with DB(tables_map=tables_map) as db:
            obj = MockORMModel()
            # This should call table.insert(obj)
            db.insert(obj)
            # Verify insertion (via raw query since we are testing DB.insert)
            res = db.execute_query("SELECT COUNT(*) FROM test_table").fetchone()[0]
            assert res == 1

    def test_insert_invalid_type(self):
        """Test inserting an object with an unregistered type."""
        with DB(tables_map={}) as db, pytest.raises(TypeError, match="Invalid object type"):
            db.insert("unregistered string object")

    def test_init_tables_without_domain_model(self):
        """Test that only the ORM class is registered when _domain_model is unset."""
        with DB(tables_map={"no_domain": NoDomainTable}) as db:
            assert NoDomainORMModel in db.table
            # No second (domain-model) key was registered for this table
            keys = [k for k, v in db.table.items() if v is db.table[NoDomainORMModel]]
            assert keys == [NoDomainORMModel]

            db.insert(NoDomainORMModel(id=7))
            assert db.execute_query("SELECT COUNT(*) FROM no_domain_table").fetchone()[0] == 1

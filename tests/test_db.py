"""Tests for the ducktide.db.DB class."""

from __future__ import annotations

import duckdb
import pytest
from pydantic import BaseModel

from ducktide.db import DB
from ducktide.table import Table


class Item(BaseModel):
    """A minimal model backing the test table."""

    id: int = 1
    name: str = "test"


ITEMS = Table.of(Item, name="test_table")


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
        """Verify that tables are initialized and the model maps to its table."""
        with DB(tables_map={"test_table": ITEMS}) as db:
            assert isinstance(db.test_table, Table)
            assert db.table == {Item: db.test_table}

    def test_insert_valid_object(self):
        """Test inserting a valid object."""
        with DB(tables_map={"test_table": ITEMS}) as db:
            db.insert(Item())
            # Verify insertion (via raw query since we are testing DB.insert)
            res = db.execute_query("SELECT COUNT(*) FROM test_table").fetchone()[0]
            assert res == 1

    def test_insert_invalid_type(self):
        """Test inserting an object with an unregistered type."""
        with DB(tables_map={}) as db, pytest.raises(TypeError, match="Invalid object type"):
            db.insert("unregistered string object")


class TestReadOnlyDB:
    """A read-only DB refuses to drop tables."""

    def test_drop_all_tables_is_refused(self, tmp_path):
        """drop_all_tables raises DatabaseError on a read-only database."""
        from ducktide.exceptions import DatabaseError

        path = tmp_path / "ro.duckdb"
        DB(tables_map={"items": ITEMS}, db_path=path).close()
        with (
            DB(tables_map={"items": ITEMS}, db_path=path, read_only=True) as db,
            pytest.raises(DatabaseError, match="read-only: drop_all_tables"),
        ):
            db.drop_all_tables()

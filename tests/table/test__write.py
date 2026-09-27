"""Tests for the WriteMixin class in ducktide.table._write."""

from __future__ import annotations

from datetime import date

import pytest

from ducktide.exceptions import QueryError

from .conftest import MockModel


class _FailingExecutemany:
    """Delegate to a real DuckDB connection but fail every ``executemany``.

    Used to exercise the non-constraint failure path in ``bulk_insert``, where a
    rollback must still happen. ``begin``, ``rollback`` and every other call pass
    straight through to the real connection so the transaction is genuine.
    """

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def executemany(self, *_args, **_kwargs):
        """Fail with an error that is not a ConstraintException."""
        msg = "connection lost"
        raise RuntimeError(msg)


class TestWriteMixin:
    """Test Table insertion methods."""

    def test_insert_empty(self, table):
        """Test insert with no objects (should do nothing)."""
        table.insert()
        assert len(table) == 0

    def test_insert_single(self, table):
        """Test inserting a single object."""
        obj = MockModel(id=1, name="test", expiry=date(2025, 1, 1))
        table.insert(obj)
        assert len(table) == 1
        retrieved = table.get(1)
        assert retrieved.name == "test"

    def test_insert_single_constraint_violation_raises(self, table):
        """A duplicate primary key on a single-row insert surfaces as QueryError."""
        table.insert(MockModel(id=1, name="a"))
        with pytest.raises(QueryError, match="Constraint violation inserting into 'mock_table'"):
            table.insert(MockModel(id=1, name="duplicate"))
        assert len(table) == 1

    def test_insert_multiple(self, table):
        """Test inserting multiple objects (delegates to bulk_insert)."""
        objs = [MockModel(id=1, name="a"), MockModel(id=2, name="b")]
        table.insert(*objs)
        assert len(table) == 2

    def test_bulk_insert_empty(self, table):
        """Test bulk_insert with an empty iterable."""
        table.bulk_insert([])
        assert len(table) == 0

    def test_bulk_insert_constraint_violation_raises(self, table):
        """A duplicate primary key inside the batch surfaces as QueryError."""
        with pytest.raises(QueryError, match="Constraint violation inserting into 'mock_table'"):
            table.bulk_insert([MockModel(id=1, name="a"), MockModel(id=1, name="duplicate")])

    def test_bulk_insert_is_atomic_on_constraint_violation(self, table):
        """A batch whose final row violates the primary key leaves no rows behind.

        Without an explicit transaction DuckDB autocommits each row, so the rows
        preceding the violation would stay committed while the caller saw only the
        exception.
        """
        table.insert(MockModel(id=1, name="existing"))

        with pytest.raises(QueryError):
            table.bulk_insert([MockModel(id=2, name="b"), MockModel(id=3, name="c"), MockModel(id=1, name="collides")])

        # Only the pre-existing row survives: none of the batch was applied.
        assert len(table) == 1
        assert table.get(1).name == "existing"

    def test_bulk_insert_retry_succeeds_after_failed_batch(self, table):
        """The obvious retry of a corrected batch succeeds.

        This is the consequence that made non-atomicity bite: a partially applied
        batch would make the retry collide on the primary keys it had itself
        written a moment earlier.
        """
        batch = [MockModel(id=1, name="a"), MockModel(id=2, name="b"), MockModel(id=2, name="duplicate")]
        with pytest.raises(QueryError):
            table.bulk_insert(batch)

        table.bulk_insert([MockModel(id=1, name="a"), MockModel(id=2, name="b"), MockModel(id=3, name="c")])
        assert len(table) == 3

    def test_bulk_insert_rolls_back_on_non_constraint_error(self, table, monkeypatch):
        """A non-constraint failure also rolls back and propagates unchanged.

        The transaction must not be left open on a long-lived connection just
        because the error was not a constraint violation. DuckDB connection
        attributes are read-only, so the failure is injected with a delegating
        proxy rather than by patching the method in place.
        """
        table.insert(MockModel(id=1, name="existing"))
        real_connection = table.connection
        monkeypatch.setattr(table, "connection", _FailingExecutemany(real_connection))

        with pytest.raises(RuntimeError, match="connection lost"):
            table.bulk_insert([MockModel(id=2, name="b"), MockModel(id=3, name="c")])

        monkeypatch.undo()

        # The rollback leaves the connection usable rather than stuck in a
        # dangling transaction, so a subsequent write still works.
        assert len(table) == 1
        table.insert(MockModel(id=4, name="after"))
        assert len(table) == 2

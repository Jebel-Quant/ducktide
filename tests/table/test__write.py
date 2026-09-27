"""Tests for the WriteMixin class in ducktide.table._write."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, ClassVar

import duckdb
import polars as pl
import pytest

from ducktide.exceptions import QueryError
from ducktide.orm.base import ORMModel
from ducktide.table import Table
from ducktide.table._write import _BULK_SOURCE, _arrow_compatible

from .conftest import MockModel


class _FailingInsert:
    """Delegate to a real DuckDB connection but fail every ``INSERT``.

    Used to exercise the non-constraint failure path in ``bulk_insert``, where a
    rollback must still happen. ``begin``, ``rollback`` and every other call pass
    straight through to the real connection so the transaction is genuine. Both
    the frame path (``execute``) and the fallback path (``executemany``) fail.
    """

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def execute(self, statement, *args, **kwargs):
        """Fail on INSERT statements; forward everything else."""
        if statement.startswith("INSERT"):
            msg = "connection lost"
            raise RuntimeError(msg)
        return self._inner.execute(statement, *args, **kwargs)

    def executemany(self, *_args, **_kwargs):
        """Fail with an error that is not a ConstraintException."""
        msg = "connection lost"
        raise RuntimeError(msg)


class TokenModel(ORMModel):
    """A model with a UUID column, which Polars cannot hand to DuckDB via Arrow."""

    _table_name: ClassVar[str] = "token"
    _schema: ClassVar[dict[str, str]] = {"id": "INTEGER PRIMARY KEY", "token": "UUID"}

    def __init__(self, id: int, token: uuid.UUID):  # noqa: A002 - mirrors the DB primary-key column `id`
        """Initialize a TokenModel instance."""
        self.id = id
        self.token = token

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TokenModel:
        """Create a TokenModel from a database row."""
        return cls(*row)


@pytest.fixture
def token_table(connection):
    """Provide a Table whose rows take the executemany fallback path."""
    return Table(connection=connection, model_class=TokenModel)


class TestWriteMixin:
    """Test Table insertion methods."""

    def test_insert_empty(self, table):
        """Test insert with no objects (should do nothing)."""
        table.insert()
        assert len(table) == 0

    def test_insert_single(self, table):
        """Test inserting a single object."""
        obj = MockModel(1, "test", date(2025, 1, 1))
        table.insert(obj)
        assert len(table) == 1
        retrieved = table.get(1)
        assert retrieved.name == "test"

    def test_insert_single_constraint_violation_raises(self, table):
        """A duplicate primary key on a single-row insert surfaces as QueryError."""
        table.insert(MockModel(1, "a"))
        with pytest.raises(QueryError, match="Constraint violation inserting into 'mock_table'"):
            table.insert(MockModel(1, "duplicate"))
        assert len(table) == 1

    def test_insert_multiple(self, table):
        """Test inserting multiple objects (delegates to bulk_insert)."""
        objs = [MockModel(1, "a"), MockModel(2, "b")]
        table.insert(*objs)
        assert len(table) == 2

    def test_bulk_insert_empty(self, table):
        """Test bulk_insert with an empty iterable."""
        table.bulk_insert([])
        assert len(table) == 0

    def test_bulk_insert_constraint_violation_raises(self, table):
        """A duplicate primary key inside the batch surfaces as QueryError."""
        with pytest.raises(QueryError, match="Constraint violation inserting into 'mock_table'"):
            table.bulk_insert([MockModel(1, "a"), MockModel(1, "duplicate")])

    def test_bulk_insert_is_atomic_on_constraint_violation(self, table):
        """A batch whose final row violates the primary key leaves no rows behind.

        Without an explicit transaction DuckDB autocommits each row, so the rows
        preceding the violation would stay committed while the caller saw only the
        exception.
        """
        table.insert(MockModel(1, "existing"))

        with pytest.raises(QueryError):
            table.bulk_insert([MockModel(2, "b"), MockModel(3, "c"), MockModel(1, "collides")])

        # Only the pre-existing row survives: none of the batch was applied.
        assert len(table) == 1
        assert table.get(1).name == "existing"

    def test_bulk_insert_retry_succeeds_after_failed_batch(self, table):
        """The obvious retry of a corrected batch succeeds.

        This is the consequence that made non-atomicity bite: a partially applied
        batch would make the retry collide on the primary keys it had itself
        written a moment earlier.
        """
        batch = [MockModel(1, "a"), MockModel(2, "b"), MockModel(2, "duplicate")]
        with pytest.raises(QueryError):
            table.bulk_insert(batch)

        table.bulk_insert([MockModel(1, "a"), MockModel(2, "b"), MockModel(3, "c")])
        assert len(table) == 3

    def test_bulk_insert_rolls_back_on_non_constraint_error(self, table, monkeypatch):
        """A non-constraint failure also rolls back and propagates unchanged.

        The transaction must not be left open on a long-lived connection just
        because the error was not a constraint violation. DuckDB connection
        attributes are read-only, so the failure is injected with a delegating
        proxy rather than by patching the method in place.
        """
        table.insert(MockModel(1, "existing"))
        real_connection = table.connection
        monkeypatch.setattr(table, "connection", _FailingInsert(real_connection))

        with pytest.raises(RuntimeError, match="connection lost"):
            table.bulk_insert([MockModel(2, "b"), MockModel(3, "c")])

        monkeypatch.undo()

        # The rollback leaves the connection usable rather than stuck in a
        # dangling transaction, so a subsequent write still works.
        assert len(table) == 1
        table.insert(MockModel(4, "after"))
        assert len(table) == 2

    def test_bulk_insert_round_trips_values(self, table):
        """The frame path stores every value, including NULLs and dates, unchanged."""
        table.bulk_insert(
            [MockModel(1, "a", date(2025, 1, 1)), MockModel(2, None), MockModel(3, "c", date(2025, 3, 3))]
        )

        rows = table.connection.execute("SELECT id, name, expiry FROM mock_table ORDER BY id").fetchall()
        assert rows == [(1, "a", date(2025, 1, 1)), (2, None, None), (3, "c", date(2025, 3, 3))]

    def test_bulk_insert_unregisters_source(self, table):
        """The batch frame is not left registered on the connection, even after a failure."""
        table.bulk_insert([MockModel(1, "a"), MockModel(2, "b")])
        with pytest.raises(QueryError):
            table.bulk_insert([MockModel(3, "c"), MockModel(3, "duplicate")])

        with pytest.raises(duckdb.CatalogException):
            table.connection.execute(f"SELECT * FROM {_BULK_SOURCE}")  # noqa: S608 - constant relation name

    def test_bulk_insert_falls_back_for_non_arrow_values(self, token_table):
        """Values Polars cannot hand to DuckDB (UUIDs) go through executemany."""
        tokens = [uuid.UUID(int=1), uuid.UUID(int=2)]
        assert token_table._frame_from_values([(1, tokens[0]), (2, tokens[1])]) is None

        token_table.bulk_insert([TokenModel(1, tokens[0]), TokenModel(2, tokens[1])])
        assert [t.token for t in token_table.select()] == tokens

    def test_bulk_insert_falls_back_for_mixed_types(self, table):
        """A column mixing incompatible Python types falls back and is cast by DuckDB."""
        assert table._frame_from_values([(1, 7, None), (2, "b", None)]) is None

        table.bulk_insert([MockModel(1, 7), MockModel(2, "b")])  # type: ignore[arg-type]
        assert [m.name for m in table.select()] == ["7", "b"]

    def test_bulk_insert_fallback_is_atomic(self, token_table):
        """The executemany fallback keeps the all-or-nothing guarantee."""
        token_table.insert(TokenModel(1, uuid.UUID(int=1)))
        with pytest.raises(QueryError, match="Constraint violation inserting into 'token'"):
            token_table.bulk_insert([TokenModel(2, uuid.UUID(int=2)), TokenModel(1, uuid.UUID(int=3))])
        assert len(token_table) == 1

    def test_bulk_insert_fallback_rolls_back_on_non_constraint_error(self, token_table, monkeypatch):
        """A non-constraint failure on the fallback path also rolls back."""
        monkeypatch.setattr(token_table, "connection", _FailingInsert(token_table.connection))
        with pytest.raises(RuntimeError, match="connection lost"):
            token_table.bulk_insert([TokenModel(1, uuid.UUID(int=1)), TokenModel(2, uuid.UUID(int=2))])
        monkeypatch.undo()

        assert len(token_table) == 0
        token_table.insert(TokenModel(3, uuid.UUID(int=3)))
        assert len(token_table) == 1


@pytest.mark.parametrize(
    ("dtype", "expected"),
    [
        (pl.Int64(), True),
        (pl.List(pl.Utf8()), True),
        (pl.Struct({"a": pl.Date()}), True),
        (pl.Object(), False),
        (pl.Int128(), False),
        (pl.UInt128(), False),
        (pl.List(pl.Int128()), False),
        (pl.Array(pl.Int128(), 2), False),
        (pl.Struct({"a": pl.Int64(), "b": pl.List(pl.UInt128())}), False),
    ],
)
def test_arrow_compatible(dtype, expected):
    """Dtypes DuckDB cannot read over Arrow are rejected, however deeply nested."""
    assert _arrow_compatible(dtype) is expected

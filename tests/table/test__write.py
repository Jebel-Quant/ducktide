"""Tests for the WriteMixin class in ducktide.table._write."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import duckdb
import polars as pl
import pytest
from pydantic import BaseModel

from ducktide.exceptions import QueryError
from ducktide.table import Table
from ducktide.table._write import _BULK_SOURCE, _arrow_compatible, _uuids_as_text

from .conftest import MockModel


class _FailingInsert:
    """Delegate to a real DuckDB connection but fail every ``INSERT`` after it has run.

    Used to exercise the non-constraint failure path in ``bulk_insert``, where a
    rollback must still happen. The real statement executes first, so the rows
    are written inside the open transaction and only a rollback removes them.
    ``begin``, ``rollback`` and every other call pass straight through to the
    real connection so the transaction is genuine. Both the frame path
    (``execute``) and the fallback path (``executemany``) fail.
    """

    def __init__(self, inner):
        """Wrap the real connection."""
        self._inner = inner

    def __getattr__(self, name):
        """Forward every other attribute to the wrapped connection."""
        return getattr(self._inner, name)

    def execute(self, statement, *args, **kwargs):
        """Run the statement, then fail if it was an INSERT."""
        result = self._inner.execute(statement, *args, **kwargs)
        if statement.startswith("INSERT"):
            msg = "connection lost"
            raise RuntimeError(msg)
        return result

    def executemany(self, *args, **kwargs):
        """Run the batch, then fail with an error that is not a ConstraintException."""
        self._inner.executemany(*args, **kwargs)
        msg = "connection lost"
        raise RuntimeError(msg)


def _assert_no_open_transaction(connection):
    """Fail if a transaction was left open (DuckDB rejects a nested BEGIN)."""
    connection.begin()
    connection.rollback()


class TokenModel(BaseModel):
    """A model with a nullable UUID column, which bulk_insert sends to DuckDB as text."""

    id: int
    token: uuid.UUID | None = None


class BigModel(BaseModel):
    """A model whose HUGEINT column takes values Polars cannot hand to DuckDB via Arrow."""

    id: int
    big: int


class LooseModel(BaseModel):
    """A model whose untyped field lets one column mix Python types."""

    id: int
    value: Any


@pytest.fixture
def token_table(connection):
    """Provide a Table with a UUID column."""
    return Table(connection, TokenModel, name="token")


@pytest.fixture
def big_table(connection):
    """Provide a Table whose rows beyond 64 bits take the executemany fallback path."""
    return Table(connection, BigModel, name="big", sql_types={"big": "HUGEINT NOT NULL"})


def _big(id: int) -> BigModel:  # noqa: A002 - mirrors the DB primary-key column `id`
    """Return a BigModel whose value only fits in 128 bits."""
    return BigModel(id=id, big=2**70 + id)


@pytest.fixture
def loose_table(connection):
    """Provide a Table with a VARCHAR column fed by an untyped field."""
    return Table(connection, LooseModel, name="loose", sql_types={"value": "VARCHAR"})


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
        monkeypatch.setattr(table, "connection", _FailingInsert(real_connection))

        with pytest.raises(RuntimeError, match="connection lost"):
            table.bulk_insert([MockModel(id=2, name="b"), MockModel(id=3, name="c")])

        monkeypatch.undo()

        # The batch's rows were written before the failure, so only a rollback
        # removes them; it also closes the transaction rather than leaving it
        # dangling, so a subsequent write still works.
        _assert_no_open_transaction(table.connection)
        assert len(table) == 1
        table.insert(MockModel(id=4, name="after"))
        assert len(table) == 2

    def test_bulk_insert_round_trips_values(self, table):
        """The frame path stores every value, including NULLs and dates, unchanged."""
        table.bulk_insert(
            [
                MockModel(id=1, name="a", expiry=date(2025, 1, 1)),
                MockModel(id=2, name=None),
                MockModel(id=3, name="c", expiry=date(2025, 3, 3)),
            ]
        )

        rows = table.connection.execute("SELECT id, name, expiry FROM mock_table ORDER BY id").fetchall()
        assert rows == [(1, "a", date(2025, 1, 1)), (2, None, None), (3, "c", date(2025, 3, 3))]

    def test_bulk_insert_unregisters_source(self, table):
        """The batch frame is not left registered on the connection, even after a failure."""
        table.bulk_insert([MockModel(id=1, name="a"), MockModel(id=2, name="b")])
        with pytest.raises(QueryError):
            table.bulk_insert([MockModel(id=3, name="c"), MockModel(id=3, name="duplicate")])

        with pytest.raises(duckdb.CatalogException):
            table.connection.execute(f"SELECT * FROM {_BULK_SOURCE}")  # noqa: S608 - constant relation name

    def test_bulk_insert_sends_uuids_as_text(self, token_table):
        """A UUID column takes the frame path as text and reads back as UUIDs, NULLs included."""
        tokens = [uuid.UUID(int=1), None, uuid.uuid4()]
        frame = token_table._frame_from_values([(i, t) for i, t in enumerate(tokens)])
        assert frame is not None
        assert frame.schema["token"] == pl.String

        token_table.bulk_insert([TokenModel(id=i, token=t) for i, t in enumerate(tokens)])
        assert [t.token for t in token_table.select()] == tokens

    def test_bulk_insert_uuid_into_varchar_is_canonical_text(self, connection):
        """Into a VARCHAR column a UUID lands as its canonical string, as a bound parameter would."""
        table = Table(connection, TokenModel, name="token_text", sql_types={"token": "VARCHAR"})
        token = uuid.UUID(int=0xABC)
        table.bulk_insert([TokenModel(id=1, token=token), TokenModel(id=2)])

        assert connection.execute("SELECT token FROM token_text ORDER BY id").fetchall() == [(str(token),), (None,)]

    def test_bulk_insert_falls_back_for_non_arrow_values(self, big_table):
        """Values Polars cannot hand to DuckDB (ints beyond 64 bits) go through executemany."""
        assert big_table._frame_from_values([(1, 2**70)]) is None

        big_table.bulk_insert([_big(1), _big(2)])
        assert [m.big for m in big_table.select()] == [2**70 + 1, 2**70 + 2]

    def test_bulk_insert_falls_back_for_mixed_types(self, loose_table):
        """A column mixing incompatible Python types falls back and is cast by DuckDB."""
        assert loose_table._frame_from_values([(1, 7), (2, "b")]) is None

        loose_table.bulk_insert([LooseModel(id=1, value=7), LooseModel(id=2, value="b")])
        assert [m.value for m in loose_table.select()] == ["7", "b"]

    def test_bulk_insert_falls_back_for_uuids_mixed_with_other_values(self, loose_table):
        """UUIDs are only sent as text when every non-null value in the column is one."""
        token = uuid.UUID(int=5)
        assert loose_table._frame_from_values([(1, token), (2, "b")]) is None

        loose_table.bulk_insert([LooseModel(id=1, value=token), LooseModel(id=2, value="b")])
        assert [m.value for m in loose_table.select()] == [str(token), "b"]

    def test_bulk_insert_fallback_is_atomic(self, big_table):
        """The executemany fallback keeps the all-or-nothing guarantee."""
        big_table.insert(_big(1))
        with pytest.raises(QueryError, match="Constraint violation inserting into 'big'"):
            big_table.bulk_insert([_big(2), _big(1)])
        assert len(big_table) == 1

    def test_bulk_insert_fallback_rolls_back_on_non_constraint_error(self, big_table, monkeypatch):
        """A non-constraint failure on the fallback path also rolls back."""
        monkeypatch.setattr(big_table, "connection", _FailingInsert(big_table.connection))
        with pytest.raises(RuntimeError, match="connection lost"):
            big_table.bulk_insert([_big(1), _big(2)])
        monkeypatch.undo()

        _assert_no_open_transaction(big_table.connection)
        assert len(big_table) == 0
        big_table.insert(_big(3))
        assert len(big_table) == 1


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


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ([uuid.UUID(int=1), None], ["00000000-0000-0000-0000-000000000001", None]),
        ([None, None], [None, None]),
        ([], []),
        ([uuid.UUID(int=1), "b"], [uuid.UUID(int=1), "b"]),
        (["a", uuid.UUID(int=1)], ["a", uuid.UUID(int=1)]),
        ([[uuid.UUID(int=1)]], [[uuid.UUID(int=1)]]),
    ],
)
def test_uuids_as_text(column, expected):
    """Only a column of nothing but UUIDs (and NULLs) is converted; anything else is left as given."""
    assert _uuids_as_text(column) == expected

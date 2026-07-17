"""Tests for the database context utilities in jqr.database.context."""

from __future__ import annotations

import pytest

from jqr.database.context import (
    clear_default_db,
    get_default_db,
    set_default_db,
    use_db,
)


def test_set_get_clear_default_db():
    """Test setting, getting, and clearing the default database."""
    # Ensure it's clear initially
    clear_default_db()

    # Getting when not set should raise RuntimeError
    with pytest.raises(RuntimeError, match="No default Database set for this context"):
        get_default_db()

    # Set a mock database object
    mock_db = object()
    set_default_db(mock_db)

    # Getting should now return the mock_db
    assert get_default_db() is mock_db

    # Clear it
    clear_default_db()

    # Should raise RuntimeError again
    with pytest.raises(RuntimeError, match="No default Database set for this context"):
        get_default_db()


def test_use_db_context_manager():
    """Test the use_db context manager."""
    clear_default_db()

    db1 = object()
    db2 = object()

    # Case 1: Simple usage
    with use_db(db1):
        assert get_default_db() is db1

    # Should be cleared after context
    with pytest.raises(RuntimeError):
        get_default_db()

    # Case 2: Nesting
    with use_db(db1):
        assert get_default_db() is db1
        with use_db(db2):
            assert get_default_db() is db2
        # Should restore db1
        assert get_default_db() is db1

    # Should be cleared after outer context
    with pytest.raises(RuntimeError):
        get_default_db()


def test_use_db_restores_on_exception():
    """Test that use_db restores the previous value even if an exception occurs."""
    clear_default_db()
    db1 = object()
    db2 = object()

    with use_db(db1):
        try:
            with use_db(db2):
                assert get_default_db() is db2
                raise ValueError("Boom")  # noqa: TRY301
        except ValueError:
            pass

        # Should be back to db1
        assert get_default_db() is db1

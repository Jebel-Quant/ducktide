"""Scoped default Database accessor using contextvars.

This module provides a ContextVar-based mechanism for managing a default Database
instance within a specific execution context. This supports both synchronous and
asynchronous code, with proper isolation per task/thread.

Usage:
    # Set globally for current context
    from jqr.orm.context import set_default_db, get_default_db, use_db
    set_default_db(db)

    # Or use as context manager (preferred in tests/examples)
    with use_db(db):
        contract.get_future()  # will use the context default

    # Public APIs should still accept `db: Database | None = None` and do:
    db = db or get_default_db()

Design Notes:
    - The context is stored using Python's contextvars module, which provides
      proper isolation for async tasks and threads
    - When no default is set, get_default_db() raises RuntimeError with a
      helpful message
    - The use_db() context manager properly restores the previous value on exit
    - Type hints use `object` to avoid circular imports; runtime checks can use
      the actual Database type if needed
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from jqr.database.db import DB

# Type hint as object to avoid circular import; use actual Database type in runtime checks if needed
_default_db: ContextVar[object | None] = ContextVar("_default_db", default=None)


def set_default_db(db: DB | object) -> None:
    """Permanently set the default DB for the current context (overwrite).

    Parameters
    ----------
    db:
        The Database instance to set as the default for this context.
    """
    _default_db.set(db)


def clear_default_db() -> None:
    """Clear the default DB for the current context (set to None).

    Example:
        >>> from jqr.database.context import clear_default_db
        >>> clear_default_db()
    """
    _default_db.set(None)


def get_default_db() -> DB | object:
    """Return the default DB for the current context.

    Returns:
    -------
    Database
        The Database instance set for this context.

    Raises:
    ------
    RuntimeError:
        If no default Database has been set for this context.
    """
    db = _default_db.get()
    if db is None:
        raise RuntimeError(
            "No default Database set for this context. "
            "Pass a Database explicitly or use `jqr.orm.context.use_db(db)` / set_default_db(db)."
        )
    return db


@contextmanager
def use_db(db: DB | object) -> Generator[None, None, None]:
    """Temporarily set the default DB for the duration of the context manager.

    This is the preferred way to set a default Database in tests and examples,
    as it properly restores the previous value on exit.

    Parameters
    ----------
    db:
        The Database instance to use as the default within this context.

    Yields:
    ------
    None

    """
    token = _default_db.set(db)
    try:
        yield
    finally:
        _default_db.reset(token)

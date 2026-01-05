"""Scoped default Database accessor using contextvars.

This module provides a ContextVar-based mechanism for managing a default Database
instance within a specific execution context. This supports both synchronous and
asynchronous code, with proper isolation per task/thread.

Key Benefits:
    - Reduces verbosity in tests and examples
    - Maintains proper context isolation (thread-safe, async-safe)
    - Optional convenience without breaking explicit API patterns
    - Clean context manager pattern for scoped usage

Usage Patterns:
    1. **Context Manager (Recommended):**
        >>> from jqr.orm import Database, use_db
        >>> from jqr.orm.models import Contract
        >>> from datetime import date
        >>> db = Database()
        >>> contract = Contract(contract_id=1, ticker="ESH25", expiry=date(2025, 3, 20))
        >>> with use_db(db):
        ...     # Methods can omit db parameter
        ...     pass # future = contract.get_future()  # uses context default

    2. **Global Setting:**
        >>> from jqr.database.context import set_default_db
        >>> db = Database()
        >>> set_default_db(db)
        >>> # Now all methods use this db by default

    3. **Explicit (Always Works):**
        >>> from jqr.orm.models import Contract
        >>> from datetime import date
        >>> db = Database()
        >>> contract = Contract(contract_id=1, ticker="ESH25", expiry=date(2025, 3, 20))
        >>> # future = contract.get_future(db=db)  # explicit parameter

Design Notes:
    - The context is stored using Python's contextvars module, which provides
      proper isolation for async tasks and threads
    - When no default is set, get_default_db() raises RuntimeError with a
      helpful message
    - The use_db() context manager properly restores the previous value on exit
    - Type hints use `object` to avoid circular imports; runtime checks can use
      the actual Database type if needed
    - Public APIs should still accept `db: Database | None = None` and do:
      `db = db or get_default_db()`

Examples:
    >>> from jqr.orm import Database, use_db
    >>> from jqr.orm.models import Publisher, Future, Contract
    >>> from datetime import date
    >>>
    >>> # Setup
    >>> db = Database()
    >>> publisher = Publisher(publisher_id=1, name="CME", dataset="GLBX.MDP3", venue="GLBX")
    >>> db.publisher.insert(publisher)
    >>>
    >>> future = Future(future_id=100, name="E-mini S&P 500", ticker="ES", publisher_id=1)
    >>> db.futures.insert(future)
    >>>
    >>> contract = Contract(contract_id=1001, future_id=100, ticker="ESH25",
    ...                     expiry=date(2025, 3, 20))
    >>> db.contracts.insert(contract)
    >>>
    >>> # Use context to avoid passing db everywhere
    >>> with use_db(db):
    ...     # Get related entities without explicit db parameter
    ...     publisher_obj = future.get_publisher()  # uses context db
    ...     contracts = future.get_contracts()  # uses context db
    ...     parent_future = contract.get_future()  # uses context db
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

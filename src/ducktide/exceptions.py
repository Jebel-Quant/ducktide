"""Custom exceptions for ducktide.

This module defines the exception hierarchy raised by ducktide. Using custom
exceptions makes it easier to:
- Write specific error handlers
- Distinguish between different error scenarios
- Provide better error messages to users
- Debug issues more effectively

Exception Hierarchy:
    DucktideError (base)
    ├── ValidationError (data validation failures)
    ├── DatabaseError (database operations)
    │   ├── DatabaseConnectionError (database connection issues)
    │   └── QueryError (query execution failures)
    └── DataError (data processing/type errors)
"""


class DucktideError(Exception):
    """Base exception for all ducktide errors.

    Every exception raised by ducktide inherits from this class, so any
    ducktide error can be caught with a single except clause.
    """


class ValidationError(DucktideError):
    """Raised when data validation fails.

    This exception is used when input data does not meet expected
    validation requirements, such as invalid field values, missing
    required fields, or constraint violations.

    Examples:
        - Invalid publisher_id format
        - Missing required fields
        - Value out of acceptable range
    """


class DatabaseError(DucktideError):
    """Raised when database operations fail.

    This is a general exception for database-related errors including
    connection issues, query failures, and other database operation problems.
    More specific database exceptions inherit from this class.
    """


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails.

    This exception is used when the system cannot establish or maintain
    a connection to the database, or when operating in an invalid mode
    (e.g., trying to write to a read-only database).

    Examples:
        - Unable to connect to database server
        - API key not found for external data sources
        - Read-only database connection preventing writes
    """


class QueryError(DatabaseError):
    """Raised when a database query fails to execute.

    This exception is used when a query is syntactically valid but
    fails during execution, such as when tables don't exist, data
    integrity is violated, or the query times out.

    Examples:
        - Table does not exist
        - Foreign key constraint violation
        - Query timeout
    """


class DataError(DucktideError):
    """Raised when there are data processing or type errors.

    This exception is used for type mismatches, unexpected data formats,
    or other data processing issues that don't fit into validation or
    database error categories.

    Examples:
        - Wrong model type passed to ORM method
        - Unexpected data structure in response
        - Multiple entries found when only one expected
    """

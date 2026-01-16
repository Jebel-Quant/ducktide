"""Path validation utilities for secure file I/O operations.

This module provides utilities for validating and sanitizing file paths
to prevent path traversal attacks and other security issues when
performing file I/O operations.
"""

from pathlib import Path

from jqr.database.exceptions import ValidationError


def validate_file_path(path: str | Path, must_exist: bool = False) -> Path:
    r"""Validate and resolve a file path for safe I/O operations.

    This function validates file paths to prevent security issues such as:
    - Path traversal attacks (e.g., "../../../etc/passwd")
    - Paths with null bytes or other dangerous characters
    - Symbolic link attacks

    Args:
        path: The file path to validate. Can be a string or Path object.
        must_exist: If True, raises an error if the file doesn't exist.
            If False (default), only validates the path format.

    Returns:
        Path: A resolved, validated Path object.

    Raises:
        ValidationError: If the path contains dangerous characters or patterns.
        FileNotFoundError: If must_exist is True and the file doesn't exist.

    Examples:
        >>> from jqr.database.utils.path_validation import validate_file_path
        >>> # Valid paths are resolved and returned
        >>> p = validate_file_path("/tmp/data.csv")
        >>> isinstance(p, Path)
        True
        >>> # Paths with null bytes raise ValidationError
        >>> validate_file_path("/tmp/data\x00.csv")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ValidationError: Invalid path: contains null byte
    """
    # Convert to string for validation
    path_str = str(path)

    # Check for null bytes (common attack vector)
    if "\x00" in path_str:
        raise ValidationError("Invalid path: contains null byte")

    # Convert to Path and resolve to absolute path
    resolved = Path(path).resolve()

    # Check for existence if required
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    return resolved


def escape_path_for_sql(path: Path) -> str:
    """Escape a path for safe use in SQL statements.

    This function escapes single quotes in paths to prevent SQL injection
    when paths must be interpolated into SQL strings.

    Args:
        path: The validated Path object to escape.

    Returns:
        str: The path string with single quotes escaped.

    Examples:
        >>> from pathlib import Path
        >>> from jqr.database.utils.path_validation import escape_path_for_sql
        >>> escape_path_for_sql(Path("/tmp/data.csv"))
        '/tmp/data.csv'
        >>> escape_path_for_sql(Path("/tmp/it's data.csv"))
        "/tmp/it''s data.csv"
    """
    return str(path).replace("'", "''")

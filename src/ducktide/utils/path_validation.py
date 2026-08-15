"""Path validation utilities for secure file I/O operations.

This module provides utilities for validating and sanitizing file paths
to prevent path traversal attacks and other security issues when
performing file I/O operations.
"""

from pathlib import Path

from jqr.database.exceptions import ValidationError


def validate_file_path(path: str | Path, must_exist: bool = False, base_dir: str | Path | None = None) -> Path:
    r"""Validate and resolve a file path for safe I/O operations.

    What this function guarantees:

    * **Null bytes are rejected.** A null byte truncates the path at the C
      library boundary, so it is refused outright.
    * **The path is resolved to an absolute path.** Relative segments are
      normalised away and symlinks are followed, so the returned path is the
      real location that will be opened.
    * **Confinement, but only when ``base_dir`` is given.** With ``base_dir``
      set, the *resolved* path must lie inside the *resolved* base directory or
      a :class:`~jqr.database.exceptions.ValidationError` is raised. Because the
      comparison happens after resolution, this rejects both ``../`` traversal
      and symlinks that point out of the base directory.

    What it does **not** guarantee: without ``base_dir`` there is no confinement
    of any kind. ``Path.resolve()`` *normalises* ``../`` rather than rejecting
    it and *follows* symlinks rather than refusing them, so
    ``validate_file_path("../../etc/passwd")`` returns ``/etc/passwd`` and
    reports it as valid. Callers handling untrusted input must pass
    ``base_dir``; callers handling paths supplied by their own operator (the
    usual case for this library's import/export helpers) need not.

    Args:
        path: The file path to validate. Can be a string or Path object.
        must_exist: If True, raises an error if the file doesn't exist.
            If False (default), only validates the path format.
        base_dir: Optional directory to confine the path to. When given, the
            resolved path must lie inside the resolved ``base_dir``.

    Returns:
        Path: A resolved, validated Path object.

    Raises:
        ValidationError: If the path contains a null byte, or if ``base_dir``
            is given and the resolved path falls outside it.
        FileNotFoundError: If must_exist is True and the file doesn't exist.

    Examples:
        >>> from pathlib import Path
        >>> from jqr.database.utils.path_validation import validate_file_path
        >>> # Valid paths are resolved and returned
        >>> p = validate_file_path("data.csv")
        >>> isinstance(p, Path)
        True
        >>> # Paths with null bytes raise ValidationError
        >>> validate_file_path("data\x00.csv")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ValidationError: Invalid path: contains null byte
        >>> # Without base_dir, traversal is normalised rather than rejected
        >>> validate_file_path("../data.csv") == Path.cwd().parent / "data.csv"
        True
        >>> # With base_dir, escaping the base directory is rejected
        >>> validate_file_path("../data.csv", base_dir=Path.cwd())  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ValidationError: Invalid path: ... is outside base directory ...
    """
    # Convert to string for validation
    path_str = str(path)

    # Check for null bytes (common attack vector)
    if "\x00" in path_str:
        raise ValidationError("Invalid path: contains null byte")  # noqa: TRY003

    # Convert to Path and resolve to absolute path
    resolved = Path(path).resolve()

    # Confine to base_dir when one is supplied. Comparing *after* resolution is
    # what makes this cover symlinks as well as "../": a symlink inside the base
    # directory that points outside it resolves outside and is rejected here.
    if base_dir is not None:
        resolved_base = Path(base_dir).resolve()
        if not resolved.is_relative_to(resolved_base):
            msg = f"Invalid path: {resolved} is outside base directory {resolved_base}"
            raise ValidationError(msg)

    # Check for existence if required
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")  # noqa: TRY003

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
        Relative, separator-free paths are used here deliberately: ``str(Path(...))``
        renders separators per-platform, so a POSIX literal would fail this doctest
        on Windows.

        >>> from pathlib import Path
        >>> from jqr.database.utils.path_validation import escape_path_for_sql
        >>> escape_path_for_sql(Path("data.csv"))
        'data.csv'
        >>> escape_path_for_sql(Path("it's data.csv"))
        "it''s data.csv"
    """
    return str(path).replace("'", "''")

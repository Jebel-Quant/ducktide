"""Tests for path validation utilities."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jqr.database.exceptions import ValidationError
from jqr.database.utils.path_validation import escape_path_for_sql, validate_file_path


def test_validate_file_path_returns_resolved_path(tmp_path):
    """Test that validate_file_path returns the resolved path."""
    p = tmp_path / "data.csv"
    p.touch()
    result = validate_file_path(p)
    assert result == p.resolve()


def test_validate_file_path_null_byte_raises(tmp_path):
    """Test that a path containing a null byte raises ValidationError."""
    with pytest.raises(ValidationError, match="null byte"):
        validate_file_path(str(tmp_path / "data") + "\x00.csv")


def test_validate_file_path_must_exist_missing_raises(tmp_path):
    """Test that must_exist=True raises FileNotFoundError for missing files."""
    with pytest.raises(FileNotFoundError):
        validate_file_path(tmp_path / "nonexistent.csv", must_exist=True)


def test_validate_file_path_must_exist_present(tmp_path):
    """Test that must_exist=True succeeds when the file exists."""
    p = tmp_path / "data.csv"
    p.touch()
    result = validate_file_path(p, must_exist=True)
    assert result == p.resolve()


def test_validate_file_path_without_base_dir_normalises_traversal(tmp_path):
    """Without base_dir, "../" is normalised rather than rejected.

    This pins the documented *non*-guarantee. The docstring used to claim this
    call prevented path traversal; it does not, and the only thing stopping that
    claim from creeping back is a test that asserts the real behaviour.
    """
    escaped = validate_file_path(tmp_path / ".." / "outside.csv")
    assert escaped == (tmp_path.parent / "outside.csv").resolve()


def test_validate_file_path_base_dir_accepts_contained_path(tmp_path):
    """A path inside base_dir is accepted and returned resolved."""
    p = tmp_path / "nested" / "data.csv"
    assert validate_file_path(p, base_dir=tmp_path) == p.resolve()


def test_validate_file_path_base_dir_rejects_traversal(tmp_path):
    """A path escaping base_dir via "../" raises ValidationError."""
    with pytest.raises(ValidationError, match="outside base directory"):
        validate_file_path(tmp_path / ".." / "outside.csv", base_dir=tmp_path)


def test_validate_file_path_base_dir_rejects_escaping_symlink(tmp_path):
    """A symlink inside base_dir that points outside it is rejected.

    Confinement is checked after resolution, which is what makes it cover
    symlinks and not just textual "../" segments.
    """
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.csv"
    outside.touch()

    link = base / "link.csv"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without symlink privilege
        pytest.skip("symlink creation not permitted on this platform")

    with pytest.raises(ValidationError, match="outside base directory"):
        validate_file_path(link, base_dir=base)


def test_escape_path_for_sql_no_quotes(tmp_path):
    """Test that a path without quotes is returned unchanged."""
    p = tmp_path / "data.csv"
    assert escape_path_for_sql(p) == str(p)


def test_escape_path_for_sql_with_quotes(tmp_path):
    """Test that single quotes in a path are escaped by doubling them."""
    p = tmp_path / "it's data.csv"
    escaped = str(p).replace("'", "''")
    assert escape_path_for_sql(p) == escaped


# Null bytes are rejected by Path itself; exclude them so the strategy only
# produces constructible paths. Build paths from components so we explicitly
# cover single-segment, multi-segment, and absolute-like inputs.
path_component = st.text(
    alphabet=st.characters(exclude_characters="\x00/\\"),
    min_size=1,
)
path_names = st.one_of(
    path_component,
    st.lists(path_component, min_size=2).map("/".join),
    st.lists(path_component, min_size=1).map(lambda parts: "/" + "/".join(parts)),
)


@pytest.mark.property
@given(name=path_names)
def test_escaped_path_never_terminates_sql_literal(name):
    """Every single quote in the escaped output is doubled.

    Removing all doubled quotes must leave no lone quote behind — a lone
    quote would terminate the SQL string literal the path is embedded in.
    """
    escaped = escape_path_for_sql(Path(name))
    assert "'" not in escaped.replace("''", "")


@pytest.mark.property
@given(name=path_names)
def test_escaping_is_reversible(name):
    """Collapsing doubled quotes recovers the original path string."""
    escaped = escape_path_for_sql(Path(name))
    assert escaped.replace("''", "'") == str(Path(name))


# Classic SQL-injection payloads a hostile path/identifier might carry. Each is
# fed through escape_path_for_sql and then embedded in a real single-quoted SQL
# literal to prove the payload cannot break out of the literal.
ADVERSARIAL_PAYLOADS = [
    "'; DROP TABLE prices; --",
    "' OR '1'='1",
    "'); DELETE FROM prices; --",
    "data.csv'--",
    "'' UNION SELECT * FROM secrets --",
    "a' || (SELECT password FROM users) || '",
    "back\\slash'quote",
    "naïve'café.csv",  # non-ASCII plus a quote
    "'" * 7,  # odd run of quotes
]


@pytest.mark.property
@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
def test_adversarial_payload_stays_inside_sql_literal(payload):
    """An escaped payload embedded in a SQL literal cannot terminate it early.

    Building ``'<escaped>'`` and stripping the wrapping quotes plus every
    doubled quote must leave a balanced string — i.e. the payload never
    introduces a lone quote that would close the literal and expose the
    trailing text as executable SQL.
    """
    escaped = escape_path_for_sql(Path(payload))
    literal = f"'{escaped}'"
    # Strip the opening/closing delimiter, then all escaped quotes; nothing that
    # could terminate the literal may remain.
    inner = literal[1:-1]
    assert "'" not in inner.replace("''", "")


@pytest.mark.property
@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
def test_adversarial_payload_round_trips(payload):
    """Escaping preserves the exact path text (no data loss on hostile input)."""
    escaped = escape_path_for_sql(Path(payload))
    assert escaped.replace("''", "'") == str(Path(payload))

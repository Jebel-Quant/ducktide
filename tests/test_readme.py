"""Run the README's ``pycon`` examples as doctests.

The rhiza README check only executes ``python`` fences, so the ``pycon``
transcripts in README.md are run here instead: every fence in order, in one
shared namespace, so later examples see the names earlier ones defined.
"""

import doctest
import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"
PYCON = re.compile(r"^```pycon\n(.*?)^```", re.DOTALL | re.MULTILINE)


def test_readme_has_pycon_examples():
    """README.md carries pycon examples, so the doctest below checks something."""
    assert PYCON.findall(README.read_text(encoding="utf-8"))


def test_readme_pycon_examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every pycon fence in README.md produces its documented output.

    The examples run from a temporary directory, so a relative path in one
    cannot write into the repo root.
    """
    monkeypatch.chdir(tmp_path)
    parser = doctest.DocTestParser()
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    globs: dict[str, object] = {}
    for number, block in enumerate(PYCON.findall(README.read_text(encoding="utf-8")), start=1):
        test = parser.get_doctest(block, globs, f"README.md pycon fence {number}", str(README), 0)
        runner.run(test, clear_globs=False)
        globs = test.globs  # DocTest copies its globs; carry this fence's names forward
    result = runner.summarize(verbose=False)
    assert result.attempted > 0
    assert result.failed == 0, f"{result.failed} README example(s) failed; see the doctest report above"

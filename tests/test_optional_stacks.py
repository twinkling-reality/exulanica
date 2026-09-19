"""A test that cannot run without an optional stack says which one, and how to install it.

A fresh clone following README.md runs `uv sync`, which installs none of the four optional
extras, and every test belonging to those stacks then skips. A skip is silent, so the only thing a
reader gets is the reason string, and "could not import 'scipy'" does not tell anybody which of
four extras carries scipy.

MEASURED 2026-09-19 at main f3a5d521, before this file existed: of the 17 `pytest.importorskip`
calls under `tests/`, 3 passed a reason and 14 passed none.

WHAT IS CHECKED AND WHAT IS NOT, because the reason strings assert two different things and only
one of them is checkable here. That an extra NAMED in a reason exists is checked below against
`pyproject.toml`, which catches the failure that actually happens: an extra is renamed or dropped
and fifteen skip messages keep sending readers to install something that is not there. That the
named extra is the one CARRYING that module is prose, and stays prose: resolving a module name to
a distribution name (cv2 to opencv-python-headless, PIL to pillow) needs a resolve this test has
no business doing. It is recorded here rather than left implied, because a justification naming a
fact is a second claim.

Parsed rather than grepped. Every one of these calls is written across several lines, so a line
based search for `importorskip(` without `reason=` reports all 19 as bare, including the ones
this file was written to add.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

#: The extras this project declares, read from the file that declares them.
EXTRAS = frozenset(
    tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
)


def _skip_calls() -> list[tuple[str, int, ast.Call]]:
    found: list[tuple[str, int, ast.Call]] = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "importorskip"
            ):
                found.append((path.relative_to(ROOT).as_posix(), node.lineno, node))
    return found


def _reason(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def test_every_optional_import_skip_says_what_is_missing():
    """A reason on every one, and a floor under the count so an empty parse cannot pass."""
    calls = _skip_calls()
    assert len(calls) >= 18, (
        f"only {len(calls)} importorskip calls were parsed out of tests/, which was 18 on "
        "2026-09-19; a parse that finds fewer is checking less than it says"
    )
    silent = [f"{path}:{line}" for path, line, call in calls if not (_reason(call) or "").strip()]
    assert not silent, (
        "these skip without saying what is missing, so a reader is told a module name and "
        "nothing about how to get it:\n  " + "\n  ".join(silent)
    )


def test_every_extra_named_in_a_skip_reason_is_an_extra_this_project_declares():
    """The half of the reason strings that pyproject.toml can settle.

    The two lists are held together rather than agreeing by coincidence: the extras come out of
    `[project.optional-dependencies]` and the names come out of the reason strings, so renaming an
    extra fails here instead of leaving fifteen messages pointing at nothing.
    """
    assert EXTRAS, "pyproject.toml declares no extras, so this rule has nothing to hold"
    named: list[tuple[str, int, str]] = []
    for path, line, call in _skip_calls():
        reason = _reason(call) or ""
        for token in reason.replace("`", " ").split():
            if token.startswith("--extra="):
                named.append((path, line, token.removeprefix("--extra=")))
        words = reason.replace("`", " ").split()
        named += [
            (path, line, words[index + 1])
            for index, word in enumerate(words[:-1])
            if word == "--extra"
        ]
    # A reason may legitimately name no extra: psycopg is a hard dependency, not an optional one.
    # What cannot happen is that NONE of them names one, which would make this test vacuous while
    # still passing, so the floor is here rather than in a comment.
    assert len(named) >= 10, (
        f"only {len(named)} skip reasons name an extra, which was 14 on 2026-09-19; this check "
        "passes trivially when reasons stop naming extras"
    )
    unknown = sorted({f"{path}:{line} names --extra {extra}" for path, line, extra in named
                      if extra not in EXTRAS})
    assert not unknown, (
        f"pyproject.toml declares the extras {sorted(EXTRAS)}, and these skip reasons send a "
        "reader to install something else:\n  " + "\n  ".join(unknown)
    )

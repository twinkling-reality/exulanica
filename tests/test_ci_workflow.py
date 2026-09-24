"""What the continuous integration workflow runs, held to the sources it is derived from.

``scripts/run_backend_suite.py`` splits the backend suite in two. Phase 1 is every test not marked
``reference_copy``; phase 2 runs those against the retained reference copy on port 5433, which
exists only on the machine that holds the retained data. A hosted runner can pass phase 1 and
cannot pass phase 2, so ``.github/workflows/check.yml`` runs phase 1's selection, and this file
holds that selection to the runner's own in both directions: a workflow that runs a
``reference_copy`` test fails every push for a reason unrelated to the change, and one that leaves
anything else out reports a pass for tests that never ran.

The workflow is read as text, as ``tests/test_deployment.py`` reads it and for the reason given
there: the dev dependency closure has no YAML parser. The reader understands the shapes a ``run``
command takes in a workflow, a plain or quoted scalar on the key's line or a block scalar below
it, and reports a mention of pytest it cannot account for instead of passing over it, so a
workflow it cannot read fails rather than reading as a workflow with nothing to check.
"""

from __future__ import annotations

import contextlib
import functools
import io
import json
import re
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_backend_suite as runner  # noqa: E402

WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")

#: The environment variable that turns an unreachable database into a failure instead of a skip.
REQUIRE_POSTGRES = "EXULANICA_REQUIRE_POSTGRES"

_RUN = re.compile(r"^(?P<indent> *)(?P<item>- +)?run: *(?P<value>.*)$")
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?$")
_DOUBLE_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
_SINGLE_QUOTED = re.compile(r"'((?:[^']|'')*)'")
_PYTEST = re.compile(r"\bpytest\b")
_NAME = re.compile(r"^(- +)?name:")
#: Shell control operators, each of which ends one simple command and begins the next.
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", ";;"})


@dataclass(frozen=True)
class Command:
    """One ``run`` value: the text the shell receives, where it is, and the step it belongs to."""

    line: int
    text: str
    #: Every line number the value occupies, the key's line included.
    lines: range
    #: The lines of the step the command runs in, which is where its environment is declared.
    step: tuple[str, ...]


def _indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _scalar(value: str, *, where: str) -> str:
    """A scalar written on its key's line, unquoted. A trailing comment is not part of it."""
    for quoted in (_DOUBLE_QUOTED, _SINGLE_QUOTED):
        if value[:1] != quoted.pattern[0]:
            continue
        match = quoted.match(value)
        rest = value[match.end() :].strip() if match else None
        if match is None or (rest and not rest.startswith("#")):
            raise ValueError(f"{where}: cannot read the quoted value {value!r}")
        if quoted is _DOUBLE_QUOTED:
            return json.loads(match.group(0))
        return match.group(1).replace("''", "'")
    return re.split(r"\s#", value, maxsplit=1)[0].strip()


def _step(lines: Sequence[str], index: int, key_indentation: int) -> tuple[str, ...]:
    """The step holding line ``index``: from its ``- `` item to the next line as shallow."""
    start = index
    while start > 0 and not (
        lines[start].lstrip(" ").startswith("- ") and _indentation(lines[start]) < key_indentation
    ):
        start -= 1
    item = _indentation(lines[start])
    end = start + 1
    while end < len(lines) and not (lines[end].strip() and _indentation(lines[end]) <= item):
        end += 1
    return tuple(lines[start:end])


def run_commands(text: str) -> list[Command]:
    """Every ``run`` value in a workflow, in order."""
    lines = text.splitlines()
    commands = []
    for index, line in enumerate(lines):
        match = _RUN.match(line)
        if match is None:
            continue
        key_indentation = len(match["indent"]) + len(match["item"] or "")
        value = match["value"].strip()
        last = index
        if _BLOCK_SCALAR.match(value):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if following.strip() and _indentation(following) <= key_indentation:
                    break
                body.append(following)
            while body and not body[-1].strip():
                body.pop()
            last = index + len(body)
            depth = min((_indentation(row) for row in body if row.strip()), default=0)
            rows = [row[depth:] for row in body]
            command = "\n".join(rows) if value.startswith("|") else " ".join(rows)
        else:
            command = _scalar(value, where=f"line {index + 1}")
        commands.append(
            Command(
                line=index + 1,
                text=command,
                lines=range(index + 1, last + 2),
                step=_step(lines, index, key_indentation),
            )
        )
    return commands


def pytest_arguments(command: str) -> list[list[str]]:
    """The arguments of every pytest run in one shell command, however pytest is started.

    Raises ``ValueError`` for a command the shell's own quoting rules cannot split.
    """
    found = []
    for logical in re.sub(r"\\\n", " ", command).splitlines():
        lexer = shlex.shlex(logical, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        simple: list[list[str]] = [[]]
        for token in lexer:
            if token in _OPERATORS:
                simple.append([])
            else:
                simple[-1].append(token)
        for words in simple:
            for position, word in enumerate(words):
                if word == "pytest" or word.endswith("/pytest"):
                    found.append(words[position + 1 :])
                    break
                if word == "-m" and words[position + 1 : position + 2] == ["pytest"]:
                    found.append(words[position + 2 :])
                    break
    return found


def _declared(step: Sequence[str], name: str) -> str | None:
    """The value a step's lines give ``name``, as a string, or None when they give none."""
    for line in step:
        match = re.match(rf"^ *{re.escape(name)}: *(?P<value>.*)$", line)
        if match is not None:
            return _scalar(match["value"].strip(), where=name)
    return None


@functools.cache
def phase_one() -> tuple[str, ...]:
    """The selection the backend runner gives phase 1, read from the runner's own plan.

    Read from what the runner prints for ``--plan`` rather than rebuilt from its marker's name, so
    a change to how the runner selects phase 1 changes what this file expects. With no pytest
    arguments of its own, the plan line is ``pytest -n <jobs>`` followed by the selection alone.
    """
    jobs = "1"
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert runner.main(["--plan", "--without-reference-copy", "--jobs", jobs]) == 0
    plan = [line for line in printed.getvalue().splitlines() if line.startswith("phase 1: ")]
    assert len(plan) == 1, printed.getvalue()
    head = f"phase 1: pytest -n {jobs} -m "
    assert plan[0].startswith(head), (
        f"the runner no longer selects phase 1 by one marker expression: {plan[0]!r}; this file "
        "reads the selection from that shape and has to learn the new one"
    )
    return ("-m", plan[0].removeprefix(head))


def phase_one_requirement() -> str:
    """The value the backend runner gives :data:`REQUIRE_POSTGRES` in phase 1."""
    environment = runner.phase_environment(private_servers=True, copy_url=runner.DEFAULT_COPY_URL)
    return environment[REQUIRE_POSTGRES]


def selection_problems(text: str) -> list[str]:
    """Every way a workflow's backend run differs from the runner's phase 1, as sentences."""
    problems: list[str] = []
    commands = run_commands(text)
    invocations: list[tuple[Command, list[str]]] = []
    for command in commands:
        try:
            found = pytest_arguments(command.text)
        except ValueError as error:
            problems.append(f"line {command.line}: cannot read {command.text!r}: {error}")
            continue
        if _PYTEST.search(command.text) and not found:
            problems.append(
                f"line {command.line} mentions pytest in a command this file cannot read as a "
                f"pytest run: {command.text!r}"
            )
        invocations.extend((command, arguments) for arguments in found)
    accounted = {number for command in commands for number in command.lines}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if number in accounted or stripped.startswith("#") or _NAME.match(stripped):
            continue
        if _PYTEST.search(stripped):
            problems.append(f"line {number} mentions pytest outside any run command: {stripped!r}")
    if len(invocations) != 1:
        problems.append(
            f"the workflow runs pytest {len(invocations)} times; it runs the backend suite once, "
            "with the runner's phase 1 selection"
        )
    expected = list(phase_one())
    required = phase_one_requirement()
    for command, arguments in invocations:
        if arguments != expected:
            problems.append(
                f"line {command.line} runs pytest with {shlex.join(arguments)!r}; the runner's "
                f"phase 1 selects with {shlex.join(expected)!r} and nothing else, so every test "
                "not marked reference_copy runs and none marked reference_copy does"
            )
        declared = _declared(command.step, REQUIRE_POSTGRES)
        if declared != required:
            problems.append(
                f"the step running pytest on line {command.line} sets {REQUIRE_POSTGRES} to "
                f"{declared!r}; the runner's phase 1 sets {required!r}, without which a missing "
                "server skips every PostgreSQL test instead of failing"
            )
    return problems


def test_the_workflow_runs_the_backend_runners_phase_one_and_nothing_narrower():
    assert selection_problems(WORKFLOW_TEXT) == []


def test_the_reader_finds_the_one_pytest_run_the_workflow_makes():
    """The guard on the guard: no problems means something only if the reader saw the pytest run
    and the selection it passes."""
    runs = [
        arguments
        for command in run_commands(WORKFLOW_TEXT)
        for arguments in pytest_arguments(command.text)
    ]
    assert runs == [list(phase_one())]


def test_the_expected_selection_is_read_from_the_runner():
    """Positive control for :func:`phase_one`: what it reads is not empty and names the marker."""
    option, expression = phase_one()
    assert option == "-m"
    assert runner.REFERENCE_MARKER in expression.split()
    assert phase_one_requirement() == "1"


_THE_RUN = 'run: uv run pytest -m "not reference_copy"'


@pytest.mark.parametrize(
    ("replacement", "refusal"),
    [
        pytest.param("run: uv run pytest", "phase 1 selects", id="runs-the-reference-copy-tests"),
        pytest.param(
            'run: uv run pytest -m "not reference_copy and not postgres"',
            "phase 1 selects",
            id="leaves-out-a-second-marker",
        ),
        pytest.param(
            'run: uv run pytest -m "not reference_copy" --deselect tests/test_api.py::test_x',
            "phase 1 selects",
            id="deselects-a-test",
        ),
        pytest.param(
            'run: uv run pytest -m "not reference_copy" -k api',
            "phase 1 selects",
            id="narrows-by-keyword",
        ),
        pytest.param(
            'run: uv run pytest -m "not reference_copy" tests/test_api.py',
            "phase 1 selects",
            id="narrows-to-a-path",
        ),
        pytest.param(
            "run: uv run python -m pytest -m reference_copy",
            "phase 1 selects",
            id="starts-pytest-as-a-module",
        ),
        pytest.param("run: ./scripts/ci-tests.sh", "runs pytest 0 times", id="hides-pytest"),
        pytest.param(
            'run: uv run pytest -m "not reference_copy" && uv run pytest -m reference_copy',
            "runs pytest 2 times",
            id="runs-pytest-twice",
        ),
        pytest.param(
            'run: uv run pytest -m "not reference_copy', "cannot read", id="leaves-a-quote-open"
        ),
    ],
)
def test_a_workflow_that_selects_anything_else_is_refused(replacement, refusal):
    """Positive controls: each change to the one pytest run is caught, and caught by name."""
    assert _THE_RUN in WORKFLOW_TEXT, "the control edits a line the workflow no longer has"
    changed = WORKFLOW_TEXT.replace(_THE_RUN, replacement)
    assert changed != WORKFLOW_TEXT
    problems = selection_problems(changed)
    assert any(refusal in problem for problem in problems), problems


def test_a_workflow_that_lets_a_missing_server_skip_the_database_tests_is_refused():
    needle = f'          {REQUIRE_POSTGRES}: "1"\n'
    assert needle in WORKFLOW_TEXT
    problems = selection_problems(WORKFLOW_TEXT.replace(needle, ""))
    assert any(REQUIRE_POSTGRES in problem for problem in problems), problems


def test_a_pytest_run_outside_a_run_command_is_refused():
    """A step that runs pytest through an action is invisible to the reader, so it is reported."""
    changed = WORKFLOW_TEXT.replace(
        "      - run: uv run lint-imports\n",
        "      - run: uv run lint-imports\n      - uses: someone/pytest-action@v1\n",
    )
    assert changed != WORKFLOW_TEXT
    problems = selection_problems(changed)
    assert any("outside any run command" in problem for problem in problems), problems


def test_a_block_scalar_run_is_read_like_a_one_line_run():
    """The reader is not limited to the shape the workflow has today."""
    block = '        run: |\n          uv run pytest -m "not reference_copy"\n'
    changed = WORKFLOW_TEXT.replace(f"        {_THE_RUN}\n", block)
    assert changed != WORKFLOW_TEXT
    assert selection_problems(changed) == []
    wrong = changed.replace(block, "        run: |\n          uv run pytest\n")
    assert wrong != changed
    assert any("phase 1 selects" in problem for problem in selection_problems(wrong))


def test_the_web_job_installs_the_pnpm_its_workspace_declares():
    """pnpm/action-setup reads ./package.json unless told otherwise, and the repository root has
    none, so without this the web job stops at "No pnpm version is specified"."""
    lines = WORKFLOW_TEXT.splitlines()
    uses = [index for index, line in enumerate(lines) if "uses: pnpm/action-setup@" in line]
    assert len(uses) == 1, uses
    step = _step(lines, uses[0], _indentation(lines[uses[0]]) + len("- "))
    declared = _declared(step, "package_json_file")
    assert declared is not None, "the pnpm setup step names no package.json"
    package = json.loads((ROOT / declared).read_text(encoding="utf-8"))
    assert str(package.get("packageManager", "")).startswith("pnpm@"), declared

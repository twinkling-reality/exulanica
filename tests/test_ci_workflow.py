"""What the continuous integration workflow runs, held to the sources it is derived from.

``scripts/run_backend_suite.py`` splits the backend suite in two. Phase 1 is every test not marked
``reference_copy``; phase 2 runs those against the retained reference copy on port 5433, which
exists only on the machine that holds the retained data. A hosted runner can pass phase 1 and
cannot pass phase 2, so ``.github/workflows/check.yml`` runs phase 1's selection, and this file
holds that selection to the runner's own in both directions: a workflow that runs a
``reference_copy`` test fails every push for a reason unrelated to the change, and one that leaves
anything else out reports a pass for tests that never ran. How many workers run the selection is
not part of it, as it is not in the runner's own plan: ``-n`` decides which process runs a test,
never whether it runs. Nor is how many jobs share it, when the run takes ``--part`` from the job's
matrix and the matrix lists every part once: ``tests/conftest.py`` gives each test to exactly one
part, so between them the jobs run the selection once. A part written any other way, or a matrix
that misses or repeats one, is refused, and so is anything in the job that would let a part stop
counting while the run stays green: a matrix entry excluded or included beside the list, or an
error the job is told to continue past.

The run's skips are held to ``tests/expected_skips.toml`` by the runner's own check. The pytest run
writes a junit file and a later step hands it to ``run_backend_suite.py --check-skips``, which fails
on a skip the manifest does not accept. A workflow that stops writing the file, stops checking it,
checks another one or runs the check where its failure cannot fail the job would let every skip
through unasked, so each is refused here, and the check the workflow names is run as it names it
against pytest's own junit file for a planted skip nothing accepts, which it must fail.

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
import os
import re
import shlex
import subprocess
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
#: The backend runner, whose --check-skips holds a run's junit file to the expected-skips manifest.
RUNNER_SCRIPT = "run_backend_suite.py"
#: pytest-xdist's worker count, written as an option with its value as the next argument.
_WORKERS = frozenset({"-n", "--numprocesses"})
#: tests/conftest.py's option for one part of the selection, written K/N.
_PART = "--part"
#: The one value a run may give it: the job's own part from the matrix, of a count written there.
_MATRIX_PART = re.compile(r"\$\{\{ *matrix\.part *\}\}/(?P<parts>[0-9]+)")
#: The matrix line that lists the parts, as a flow sequence: ``part: [1, 2, 3]``.
_MATRIX_PARTS = re.compile(r"^ *part: *\[(?P<listed>[^\]]*)\] *(#.*)?$")
#: The job that runs the backend suite, and the keys that would let one of its parts stop counting
#: while the run stays green: a matrix entry removed or added beside the part list, and an error
#: the job or a step is told to continue past.
_SUITE_JOB = "python"
_PART_ESCAPES = ("exclude", "include", "continue-on-error")


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


def _tokens(command: str) -> list[list[str]]:
    """Each logical line of a shell command as the shell splits it, its operators included.

    Raises ``ValueError`` for a command the shell's own quoting rules cannot split.
    """
    lines = []
    for logical in re.sub(r"\\\n", " ", command).splitlines():
        lexer = shlex.shlex(logical, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lines.append(list(lexer))
    return lines


def _simple_commands(command: str) -> list[list[str]]:
    """The words of each simple command in one shell command."""
    simple: list[list[str]] = []
    for tokens in _tokens(command):
        simple.append([])
        for token in tokens:
            if token in _OPERATORS:
                simple.append([])
            else:
                simple[-1].append(token)
    return [words for words in simple if words]


def pytest_arguments(command: str) -> list[list[str]]:
    """The arguments of every pytest run in one shell command, however pytest is started.

    Raises ``ValueError`` for a command the shell's own quoting rules cannot split.
    """
    found = []
    for words in _simple_commands(command):
        for position, word in enumerate(words):
            if word == "pytest" or word.endswith("/pytest"):
                found.append(words[position + 1 :])
                break
            if word == "-m" and words[position + 1 : position + 2] == ["pytest"]:
                found.append(words[position + 2 :])
                break
    return found


def without_workers(arguments: Sequence[str]) -> list[str]:
    """Pytest arguments without the worker count, which decides where a test runs and not whether.

    Every spelling pytest-xdist reads is taken out, ``-n 4``, ``-n4``, ``--numprocesses 4`` and
    ``--numprocesses=4``, so a count written differently cannot pass for a selection.
    """
    rest: list[str] = []
    expecting = False
    for argument in arguments:
        if expecting:
            expecting = False
        elif argument in _WORKERS:
            expecting = True
        elif not argument.startswith("--numprocesses=") and not re.fullmatch(r"-n\S+", argument):
            rest.append(argument)
    return rest


def without_part(arguments: Sequence[str]) -> tuple[str | None, list[str]]:
    """The ``--part`` value among pytest arguments, the last as pytest reads it, and the rest."""
    rest: list[str] = []
    part: str | None = None
    expecting = False
    for argument in arguments:
        if expecting:
            part, expecting = argument, False
        elif argument == _PART:
            expecting = True
        elif argument.startswith(f"{_PART}="):
            part = argument.split("=", 1)[1]
        else:
            rest.append(argument)
    return part, rest


def selection(arguments: Sequence[str]) -> list[str]:
    """What one pytest run selects, its jobs taken together: its arguments without the junit file,
    the worker count and the part, which part_problems holds to the matrix."""
    _, rest = runner._without_junit(arguments)
    _, rest = without_part(rest)
    return without_workers(rest)


def runner_arguments(command: str) -> list[list[str]]:
    """The arguments of every run of the backend runner in one shell command."""
    found = []
    for words in _simple_commands(command):
        for position, word in enumerate(words):
            if Path(word).name == RUNNER_SCRIPT:
                found.append(words[position + 1 :])
                break
    return found


def checked_junit(arguments: Sequence[str]) -> str | None:
    """The junit file whose skips one run of the backend runner checks, or None."""
    for position, argument in enumerate(arguments):
        if argument == "--check-skips":
            return arguments[position + 1] if position + 1 < len(arguments) else None
        if argument.startswith("--check-skips="):
            return argument.removeprefix("--check-skips=")
    return None


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
        # The junit file is where the skips are checked from, as it is in the runner, and selects
        # nothing; skip_check_problems holds it to the step that reads it. The worker count selects
        # nothing either.
        if selection(arguments) != expected:
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


def skip_check_problems(text: str) -> list[str]:
    """Every way a workflow lets its backend run's skips pass unchecked, as sentences.

    The one pytest run writes a junit file, and one later step runs the backend runner's
    --check-skips on that file, as the whole of its command and with neither a condition nor
    continue-on-error, so the job fails whenever the check does. A check placed in another job
    cannot read the file and fails the job, so it is not the silent case this looks for.
    """
    readable = []
    for command in run_commands(text):
        try:
            readable.append(
                (command, pytest_arguments(command.text), runner_arguments(command.text))
            )
        except ValueError:
            continue  # selection_problems reports a command the shell could not split
    runs = [(command, arguments) for command, found, _ in readable for arguments in found]
    if len(runs) != 1:
        return []  # selection_problems reports the count; there is no one run to hold to a check
    run, arguments = runs[0]
    junit, _ = runner._without_junit(arguments)
    if junit is None:
        return [
            f"line {run.line} runs pytest without --junitxml, so no file records its skips and "
            f"nothing holds them to {runner.EXPECTED_SKIPS}"
        ]
    checks = [
        (command, checked)
        for command, _, found in readable
        for runner_run in found
        if (checked := checked_junit(runner_run)) is not None
    ]
    if len(checks) != 1:
        return [
            f"{len(checks)} steps run {RUNNER_SCRIPT} --check-skips; one step after the run on "
            f"line {run.line} checks the skips it writes to {junit}"
        ]
    check, checked = checks[0]
    problems = []
    if checked != junit:
        problems.append(
            f"line {check.line} checks the skips recorded in {checked}; the run on line "
            f"{run.line} writes them to {junit}"
        )
    if check.line < run.line:
        problems.append(
            f"line {check.line} checks skips before the run on line {run.line} has written any"
        )
    tokens = [token for line in _tokens(check.text) for token in line]
    if len(_simple_commands(check.text)) != 1 or _OPERATORS.intersection(tokens):
        problems.append(
            f"line {check.line} runs more than the check, {check.text!r}, so the step's exit "
            "is not the check's"
        )
    for key in ("if", "continue-on-error"):
        declared = _declared(check.step, key)
        if declared is not None:
            problems.append(
                f"the step checking skips on line {check.line} declares {key}: {declared}, "
                "which lets the job pass without the check passing"
            )
    return problems


def part_problems(text: str) -> list[str]:
    """Every way the jobs a matrix makes could leave a part of the selection unrun, as sentences.

    A run that takes ``--part`` runs one part, and the parts add up to the selection only when the
    job's matrix lists each of them once: 1 to N for ``${{ matrix.part }}/N``. A part written as a
    number runs that part in every job and the others in none.
    """
    runs = []
    for command in run_commands(text):
        try:
            runs.extend((command, arguments) for arguments in pytest_arguments(command.text))
        except ValueError:
            continue  # selection_problems reports a command the shell could not split
    if len(runs) != 1:
        return []  # selection_problems reports the count
    run, arguments = runs[0]
    _, rest = runner._without_junit(arguments)
    part, _ = without_part(rest)
    listed = [match for line in text.splitlines() if (match := _MATRIX_PARTS.match(line))]
    if part is None:
        if listed:
            return [
                f"the matrix lists parts and the run on line {run.line} takes none, so every job "
                "runs the whole selection"
            ]
        return []
    written = _MATRIX_PART.fullmatch(part)
    if written is None:
        return [
            f"line {run.line} runs part {part!r}; a run takes its job's own part, "
            "${{ matrix.part }}/N, so that between them the jobs run every part"
        ]
    parts = int(written["parts"])
    if len(listed) != 1:
        return [f"{len(listed)} matrix lines list parts; one lists the parts 1 to {parts}"]
    numbers = [number.strip() for number in listed[0]["listed"].split(",")]
    if numbers != [str(number) for number in range(1, parts + 1)]:
        return [
            f"the matrix lists parts [{listed[0]['listed']}], and the run on line {run.line} "
            f"splits the selection into {parts}, so each of 1 to {parts} must be listed once, in "
            "order"
        ]
    return []


def job_lines(text: str, job: str) -> list[tuple[int, str]]:
    """The numbered lines of one job, from its key to the next job's or the end of the file."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line == f"  {job}:"), None)
    if start is None:
        return []
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^  \S", lines[index])),
        len(lines),
    )
    return [(index + 1, lines[index]) for index in range(start, end)]


def escape_problems(text: str) -> list[str]:
    """Every key in the suite's job that lets a part stop counting without failing the run."""
    problems = []
    for number, line in job_lines(text, _SUITE_JOB):
        stripped = line.strip()
        for key in _PART_ESCAPES:
            if re.match(rf"^(- +)?{re.escape(key)}:", stripped):
                problems.append(
                    f"line {number} declares {key} in the {_SUITE_JOB} job, which lets a part of "
                    "the selection go unrun, or fail, while the run reports a pass"
                )
    return problems


def test_the_workflow_runs_the_backend_runners_phase_one_and_nothing_narrower():
    assert selection_problems(WORKFLOW_TEXT) == []
    assert part_problems(WORKFLOW_TEXT) == []
    assert escape_problems(WORKFLOW_TEXT) == []


def test_the_reader_finds_the_suites_job_and_its_one_pytest_run():
    """The guard on the guard for escapes: the lines it reads are the job that runs the suite."""
    lines = [line for _, line in job_lines(WORKFLOW_TEXT, _SUITE_JOB)]
    assert lines and lines[0] == f"  {_SUITE_JOB}:"
    assert sum(1 for line in lines if _PYTEST.search(line) and "run:" in line) == 1


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        pytest.param(
            "part: [1,",
            "exclude:\n          - part: 3\n        part: [1,",
            "exclude",
            id="excludes-a-part",
        ),
        pytest.param(
            "part: [1,",
            "include:\n          - part: 7\n        part: [1,",
            "include",
            id="includes-an-entry",
        ),
        pytest.param(
            f"  {_SUITE_JOB}:\n    runs-on: ubuntu-latest\n",
            f"  {_SUITE_JOB}:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n",
            "continue-on-error",
            id="continues-past-a-failed-part",
        ),
        pytest.param(
            "      - name: pytest\n",
            "      - name: pytest\n        continue-on-error: true\n",
            "continue-on-error",
            id="continues-past-a-failed-pytest-step",
        ),
    ],
)
def test_a_part_that_could_stop_counting_while_the_run_passes_is_refused(old, new, key):
    """Positive controls: each way a part could go missing or turn green is caught by name."""
    assert WORKFLOW_TEXT.count(old) == 1, f"the control edits {old!r}, which the workflow lacks"
    changed = WORKFLOW_TEXT.replace(old, new)
    problems = escape_problems(changed)
    assert any(f"declares {key}" in problem for problem in problems), problems


def test_the_reader_finds_the_one_pytest_run_the_workflow_makes():
    """The guard on the guard: no problems means something only if the reader saw the pytest run
    and the selection it passes."""
    runs = [
        arguments
        for command in run_commands(WORKFLOW_TEXT)
        for arguments in pytest_arguments(command.text)
    ]
    assert [selection(arguments) for arguments in runs] == [list(phase_one())]


def test_the_workflow_checks_the_skips_of_its_run_with_the_runner():
    assert skip_check_problems(WORKFLOW_TEXT) == []


def test_the_reader_finds_the_one_check_and_the_file_it_reads():
    """The same guard for the skips: the check it found reads the file the run writes."""
    commands = run_commands(WORKFLOW_TEXT)
    (arguments,) = [found for c in commands for found in pytest_arguments(c.text)]
    junit, _ = runner._without_junit(arguments)
    checked = [checked_junit(found) for c in commands for found in runner_arguments(c.text)]
    assert junit is not None
    assert checked == [junit]


def test_the_expected_selection_is_read_from_the_runner():
    """Positive control for :func:`phase_one`: what it reads is not empty and names the marker."""
    option, expression = phase_one()
    assert option == "-m"
    assert runner.REFERENCE_MARKER in expression.split()
    assert phase_one_requirement() == "1"


_JUNIT = '"$RUNNER_TEMP/backend-suite.xml"'
_THE_RUN = (
    f'run: uv run pytest -n "$WORKERS" --part "${{{{ matrix.part }}}}/6" -m "not reference_copy" '
    f"--junitxml={_JUNIT}"
)
_THE_CHECK = f"run: uv run python scripts/run_backend_suite.py --check-skips {_JUNIT}"
_CHECK_STEP = f"      - name: skips\n        {_THE_CHECK}\n"


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
            'run: uv run pytest -n "$WORKERS" -m "not reference_copy" -k api',
            "phase 1 selects",
            id="narrows-beside-a-worker-count",
        ),
        pytest.param(
            'run: uv run pytest -n4 -m "not reference_copy" tests/test_api.py',
            "phase 1 selects",
            id="narrows-beside-a-joined-worker-count",
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


@pytest.mark.parametrize(
    "workers", ["", "-n 4", "-n4", "--numprocesses 4", "--numprocesses=4", "-n auto"]
)
def test_a_worker_count_however_written_selects_nothing(workers):
    """The other half of the controls above: the count alone leaves the run phase 1's."""
    changed = WORKFLOW_TEXT.replace(
        _THE_RUN, f'run: uv run pytest {workers} -m "not reference_copy" --junitxml={_JUNIT}'
    )
    assert _THE_RUN in WORKFLOW_TEXT, "the control edits a line the workflow no longer has"
    assert selection_problems(changed) == []
    assert skip_check_problems(changed) == []


def _the_parts() -> tuple[str, int]:
    """The matrix line that lists the parts, and how many the run splits the selection into."""
    (line,) = [line for line in WORKFLOW_TEXT.splitlines() if _MATRIX_PARTS.match(line)]
    (arguments,) = [
        found for c in run_commands(WORKFLOW_TEXT) for found in pytest_arguments(c.text)
    ]
    part, _ = without_part(runner._without_junit(arguments)[1])
    assert part is not None, "the workflow's run takes no part"
    written = _MATRIX_PART.fullmatch(part)
    assert written is not None, part
    return line, int(written["parts"])


def test_the_reader_finds_the_parts_the_matrix_lists_and_the_run_takes():
    """The guard on the guard for parts: no problems means something only if both were read."""
    line, parts = _the_parts()
    assert parts > 1
    listed = _MATRIX_PARTS.match(line)["listed"]
    assert [int(number) for number in listed.split(",")] == list(range(1, parts + 1))


@pytest.mark.parametrize(
    ("edit", "refusal"),
    [
        pytest.param(
            lambda line, parts: line.replace(f", {parts}]", "]"),
            "must be listed once",
            id="misses-the-last-part",
        ),
        pytest.param(
            lambda line, parts: line.replace("[1,", "[1, 1,"),
            "must be listed once",
            id="repeats-a-part",
        ),
        pytest.param(
            lambda line, parts: line.replace("[1,", "[0, 1,"),
            "must be listed once",
            id="lists-a-part-that-is-not-one",
        ),
    ],
)
def test_a_matrix_that_misses_or_repeats_a_part_is_refused(edit, refusal):
    line, parts = _the_parts()
    changed = WORKFLOW_TEXT.replace(line, edit(line, parts))
    assert changed != WORKFLOW_TEXT
    problems = part_problems(changed)
    assert any(refusal in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("edit", "refusal"),
    [
        pytest.param(
            lambda written, parts: f"1/{parts}", "a run takes its job's own part", id="a-fixed-part"
        ),
        pytest.param(
            lambda written, parts: written.replace(f"/{parts}", f"/{parts + 1}"),
            "must be listed once",
            id="more-parts-than-the-matrix-lists",
        ),
        pytest.param(lambda written, parts: None, "takes none", id="no-part-beside-a-matrix"),
    ],
)
def test_a_run_whose_part_the_matrix_does_not_cover_is_refused(edit, refusal):
    _, parts = _the_parts()
    written = f'"${{{{ matrix.part }}}}/{parts}"'
    option = f" {_PART} {written}"
    assert option in _THE_RUN and _THE_RUN in WORKFLOW_TEXT
    replaced = edit(written, parts)
    changed = WORKFLOW_TEXT.replace(
        _THE_RUN, _THE_RUN.replace(option, "" if replaced is None else f" {_PART} {replaced}")
    )
    assert changed != WORKFLOW_TEXT
    problems = part_problems(changed)
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
    block = f'        run: |\n          uv run pytest -m "not reference_copy" --junitxml={_JUNIT}\n'
    changed = WORKFLOW_TEXT.replace(f"        {_THE_RUN}\n", block)
    assert changed != WORKFLOW_TEXT
    assert selection_problems(changed) == []
    assert skip_check_problems(changed) == []
    wrong = changed.replace(block, "        run: |\n          uv run pytest\n")
    assert wrong != changed
    assert any("phase 1 selects" in problem for problem in selection_problems(wrong))


def _check_before_the_run(text: str) -> str:
    lint = "      - run: uv run lint-imports\n"
    return text.replace(_CHECK_STEP, "").replace(lint, lint + _CHECK_STEP)


@pytest.mark.parametrize(
    ("edit", "refusal"),
    [
        pytest.param(
            lambda text: text.replace(f" --junitxml={_JUNIT}", ""),
            "runs pytest without --junitxml",
            id="writes-no-junit",
        ),
        pytest.param(
            lambda text: text.replace(_CHECK_STEP, ""), "0 steps run", id="checks-nothing"
        ),
        pytest.param(
            lambda text: text.replace(_CHECK_STEP, _CHECK_STEP * 2),
            "2 steps run",
            id="checks-twice",
        ),
        pytest.param(
            lambda text: text.replace(_THE_CHECK, _THE_CHECK.replace("backend-suite", "other")),
            "checks the skips recorded in",
            id="checks-another-file",
        ),
        pytest.param(_check_before_the_run, "before the run", id="checks-before-the-run"),
        pytest.param(
            lambda text: text.replace(_THE_CHECK, f"{_THE_CHECK} || true"),
            "runs more than the check",
            id="swallows-the-exit",
        ),
        pytest.param(
            lambda text: text.replace(_THE_CHECK, f"{_THE_CHECK} &"),
            "runs more than the check",
            id="backgrounds-the-check",
        ),
        pytest.param(
            lambda text: text.replace(
                _CHECK_STEP, f"{_CHECK_STEP}        continue-on-error: true\n"
            ),
            "declares continue-on-error: true",
            id="continues-on-error",
        ),
        pytest.param(
            lambda text: text.replace(
                _CHECK_STEP, _CHECK_STEP.replace("\n", "\n        if: false\n", 1)
            ),
            "declares if: false",
            id="runs-on-a-condition",
        ),
    ],
)
def test_a_workflow_that_lets_its_skips_pass_unchecked_is_refused(edit, refusal):
    """Positive controls: each way the check can stop holding the run's skips is caught by name."""
    assert _THE_RUN in WORKFLOW_TEXT and _CHECK_STEP in WORKFLOW_TEXT, (
        "the control edits lines the workflow no longer has"
    )
    changed = edit(WORKFLOW_TEXT)
    assert changed != WORKFLOW_TEXT
    problems = skip_check_problems(changed)
    assert any(refusal in problem for problem in problems), problems


def _write_junit(probe: Path, junit: Path) -> None:
    """The junit file pytest itself writes for the probe, where the workflow's run writes it."""
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--rootdir={probe}",
            f"--junitxml={junit}",
            "tests",
        ],
        cwd=probe,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


def test_the_workflows_check_fails_a_planted_skip_nothing_accepts(tmp_path, monkeypatch, capsys):
    """The check run as the workflow runs it, on the file the workflow's pytest run names.

    The probe is a module at the path of a test the manifest accepts a skip of, reporting that
    skip for the accepted reason, so the check passes it as it passes the real one; then a skip
    planted beside it, which no entry and no cause names, must fail the check by name.
    """
    commands = run_commands(WORKFLOW_TEXT)
    (arguments,) = [found for c in commands for found in pytest_arguments(c.text)]
    (check,) = [
        found for c in commands for found in runner_arguments(c.text) if checked_junit(found)
    ]
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    written, _ = runner._without_junit(arguments)
    assert written is not None
    junit = Path(os.path.expandvars(written))
    expanded = [os.path.expandvars(argument) for argument in check]

    plain = [
        entry
        for entry in runner.expected_skips().values()
        if entry.only_without is None and entry.test.count("::") == 1 and "[" not in entry.test
    ]
    assert plain, (
        f"{runner.EXPECTED_SKIPS} accepts no plain test's skip, so nothing is planted beside one"
    )
    module, name = plain[0].test.split("::")
    probe = tmp_path / "probe"
    (probe / module).parent.mkdir(parents=True)
    accepted = f"import pytest\n\n\ndef {name}():\n    pytest.skip({plain[0].reason!r})\n"
    (probe / module).write_text(accepted)
    _write_junit(probe, junit)
    assert runner.main(expanded) == 0
    assert f"the run skipped 1 test, and {runner.EXPECTED_SKIPS} accepts every one" in (
        capsys.readouterr().out
    )

    planted = "test_a_skip_nobody_decided_on"
    (probe / module).write_text(
        f"{accepted}\n\ndef {planted}():\n    pytest.skip('planted, and named by nothing')\n"
    )
    _write_junit(probe, junit)
    assert runner.main(expanded) == runner.UNNAMED_SKIP
    assert (
        f"  {module}::{planted}: planted, and named by nothing\n"
        "    refused: no entry names this test, and no cause names its reason"
    ) in capsys.readouterr().out


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

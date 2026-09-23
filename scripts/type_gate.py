"""A ratchet on one kind of type error, run offline with the mypy the uv cache already holds.

    uv run python scripts/type_gate.py                    # compare with the baseline; 1 on a rise
    uv run python scripts/type_gate.py --write-baseline   # record today's counts as the baseline

WHY UNION-ATTR. This repository has no type checker in CI, and a whole-package mypy run reports
thousands of errors, most of them psycopg call-overload noise. One code is worth holding the line
on: ``union-attr``, an attribute read from a value that may be another kind, which is how a read
of ``region.ground.half_width_mm`` on an endless ground was found. So the gate counts that code
per file, compares the counts with scripts/type_gate_baseline.json, and fails when the total or
any one file's count rises. A file is compared on its own so that a fix in one file cannot pay
for a new error in another. A fall passes and is printed, so the baseline can be lowered in the
same change.

WHY THE UV CACHE. mypy is not a dependency of this project and nothing here may download it. uv
keeps unpacked wheels in its archive cache, and a mypy another project installed there runs as it
is: this finds the mypy version the baseline was measured with, the interpreter its wheel was
built for, and the distributions its metadata requires, and puts them on PYTHONPATH. Where there
is none it says so and exits CANNOT_CHECK; it never reports a count it did not measure.

A CHECK THAT COULD RETURN SILENCE. Before the real run, the same mypy is run over a two-line
module holding one union-attr error, and a checker that does not report exactly that one is
refused. A mypy that crashed, or could not import, or was told not to show that code reports
nothing at all, which would otherwise read as a clean tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
#: The code this gate holds, and where its counts are kept, relative to ROOT.
CODE = "union-attr"
BASELINE = "scripts/type_gate_baseline.json"
BASELINE_PROFILE = "exulanica.type-gate-baseline/v1"
#: What mypy checks and how. These are the arguments the baseline was measured with, and a baseline
#: that records others is refused rather than compared.
TARGET = "exulanica"
ARGUMENTS = ("--python-version", "3.11", "--ignore-missing-imports", "--no-pretty")
#: Exit codes of this script, distinct from mypy's own.
RISEN = 1
CANNOT_CHECK = 70
#: How long a whole-package mypy run may take before it is treated as hung. MEASURED 2026-09-23 on
#: this repository's Mac: 38 to 51 seconds with an empty cache, while other suites were running.
TIMEOUT_SECONDS = 900

#: One error line of ``mypy --no-pretty``: path, line, optional column, message, code. A note that
#: an ignore comment names a code, such as ``type: ignore[union-attr]``, is not an error of it.
_ERROR = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::\d+)?: error: (?P<message>.*)  \[(?P<code>[a-z0-9-]+)\]$")
#: mypy's last line, which says that it checked anything at all.
_SUMMARY = re.compile(
    r"^(?:Found (?P<errors>\d+) errors? in \d+ files? \(checked (?P<checked>\d+) source files?\)"
    r"|Success: no issues found in (?P<clean>\d+) source files?)$"
)
#: The positive control: one read of an attribute from a value that may be None.
_PROBE = "def probe(value: int | None) -> int:\n    return value.bit_length()\n"


class CannotCheck(RuntimeError):
    """The gate could not measure, and says why; it never stands in for a count."""


class CheckerAbsent(CannotCheck):
    """No runnable mypy is on this machine: the one refusal that says nothing about the tree."""


@dataclass(frozen=True)
class Distribution:
    """One unpacked wheel in the uv archive cache."""

    name: str
    version: Version
    #: The directory that goes on PYTHONPATH, and the dist-info inside it.
    directory: Path
    info: Path
    #: The wheel's tags, such as ``cp314-cp314-macosx_11_0_arm64`` or ``py3-none-any``.
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Checker:
    """A runnable mypy: the interpreter its wheel needs and the path its imports resolve on."""

    version: str
    python: str
    path: tuple[Path, ...]


@dataclass(frozen=True)
class Measurement:
    """What one mypy run reported: every error, and how many source files it checked."""

    errors: tuple[tuple[str, str, str], ...]
    checked: int

    def counts(self, code: str = CODE) -> dict[str, int]:
        """The number of errors of ``code`` in each file that has any."""
        return dict(sorted(Counter(path for path, found, _ in self.errors if found == code).items()))


def uv_archive() -> Path:
    """The directory where uv keeps unpacked wheels, as uv itself reports it."""
    configured = os.environ.get("UV_CACHE_DIR")
    if configured:
        return Path(configured) / "archive-v0"
    if shutil.which("uv"):
        found = subprocess.run(["uv", "cache", "dir"], capture_output=True, text=True, check=False)
        if found.returncode == 0 and found.stdout.strip():
            return Path(found.stdout.strip()) / "archive-v0"
    return Path.home() / ".cache" / "uv" / "archive-v0"


def distributions(archive: Path) -> dict[str, list[Distribution]]:
    """Every unpacked wheel in the archive, by canonical name, newest first."""
    found: dict[str, list[Distribution]] = {}
    for info in archive.glob("*/*.dist-info"):
        name, _, version = info.name.removesuffix(".dist-info").rpartition("-")
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        wheel = info / "WHEEL"
        tags = ()
        if wheel.is_file():
            tags = tuple(
                line.split(":", 1)[1].strip()
                for line in wheel.read_text(encoding="utf-8").splitlines()
                if line.startswith("Tag:")
            )
        found.setdefault(canonicalize_name(name), []).append(
            Distribution(canonicalize_name(name), parsed, info.parent, info, tags)
        )
    for candidates in found.values():
        candidates.sort(key=lambda item: item.version, reverse=True)
    return found


def _interpreter_tag(distribution: Distribution) -> str | None:
    """``cp314`` for a wheel built for one CPython, None for a pure one."""
    for tag in distribution.tags:
        python = tag.split("-", 1)[0]
        if python.startswith("cp"):
            return python
    return None


def _runs_on(distribution: Distribution, interpreter: str | None) -> bool:
    tag = _interpreter_tag(distribution)
    return tag is None or tag == interpreter


def find_checker(archive: Path, version: str | None = None) -> Checker:
    """The cached mypy of ``version``, or the newest, with its interpreter and its dependencies."""
    available = distributions(archive)
    held = available.get("mypy", [])
    candidates = [item for item in held if version is None or str(item.version) == version]
    if not candidates:
        wanted = f"mypy {version}" if version else "mypy"
        listing = ", ".join(str(item.version) for item in held) or "no version of it"
        raise CheckerAbsent(f"the uv archive cache at {archive} holds no {wanted}, only {listing}")
    mypy = candidates[0]
    tag = _interpreter_tag(mypy)
    if tag is None:
        python = sys.executable
    else:
        name = f"python{tag[2]}.{tag[3:]}"
        python = shutil.which(name) or ""
        if not python:
            raise CheckerAbsent(f"mypy {mypy.version} is built for {tag}, and no {name} is on PATH")
    # Markers are read for the interpreter mypy will run on, not the one running this script.
    environment = {"python_version": f"{tag[2]}.{tag[3:]}"} if tag else {}
    path = [mypy.directory]
    for requirement in _requirements(mypy.info / "METADATA"):
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        match = next(
            (
                item
                for item in available.get(canonicalize_name(requirement.name), [])
                if item.version in requirement.specifier and _runs_on(item, tag)
            ),
            None,
        )
        # A requirement the cache does not hold is left out here; if mypy needs it to start, the
        # positive control below fails and says what it could not import.
        if match is not None:
            path.append(match.directory)
    return Checker(str(mypy.version), python, tuple(path))


def _requirements(metadata: Path) -> list[Requirement]:
    """The distributions a wheel's metadata requires, without any extra's."""
    requirements = []
    for line in metadata.read_text(encoding="utf-8").splitlines():
        if line.startswith("Requires-Dist:"):
            requirement = Requirement(line.split(":", 1)[1].strip())
            if requirement.marker is not None and "extra" in str(requirement.marker):
                continue
            requirements.append(requirement)
    return requirements


def parse(output: str) -> Measurement:
    """Every error in mypy's output, refusing output that does not end in mypy's own summary."""
    errors = []
    checked = None
    for line in output.splitlines():
        if match := _ERROR.match(line):
            errors.append((match["path"], match["code"], match["message"]))
        elif match := _SUMMARY.match(line):
            checked = int(match["checked"] or match["clean"])
    if checked is None:
        tail = "\n".join(output.splitlines()[-5:])
        raise CannotCheck(f"mypy did not finish with its summary, so nothing was measured:\n{tail}")
    return Measurement(tuple(errors), checked)


def run_mypy(checker: Checker, targets: Sequence[str], *, cwd: Path, cache: Path) -> Measurement:
    """One mypy run over ``targets``, read back as a measurement."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(str(item) for item in checker.path)
    command = [
        checker.python,
        "-m",
        "mypy",
        *ARGUMENTS,
        "--python-executable",
        sys.executable,
        "--cache-dir",
        str(cache),
        *targets,
    ]
    try:
        finished = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CannotCheck(f"mypy did not finish in {TIMEOUT_SECONDS} seconds") from error
    if finished.returncode not in (0, 1):
        raise CannotCheck(f"mypy exited {finished.returncode}:\n{finished.stderr[-2000:]}")
    return parse(finished.stdout)


def control(checker: Checker) -> None:
    """Refuse a checker that cannot see the one union-attr error a two-line module holds."""
    with tempfile.TemporaryDirectory(prefix="type-gate-control-") as scratch:
        (Path(scratch) / "union_attr_probe.py").write_text(_PROBE, encoding="utf-8")
        measured = run_mypy(
            checker, ["union_attr_probe.py"], cwd=Path(scratch), cache=Path(scratch) / "cache"
        )
    if measured.counts() != {"union_attr_probe.py": 1}:
        raise CannotCheck(
            f"mypy {checker.version} did not report the one {CODE} error it was shown, so its "
            f"silence about this tree would mean nothing: {measured.errors}"
        )


def _cache_for(root: Path) -> Path:
    """mypy's incremental cache for one checkout, outside every source tree."""
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "exulanica-type-gate" / digest


def measure(root: Path = ROOT, version: str | None = None) -> tuple[Checker, Measurement]:
    """Find the checker, prove it can see the code, and count the code across the package."""
    checker = find_checker(uv_archive(), version)
    control(checker)
    return checker, run_mypy(checker, [TARGET], cwd=root, cache=_cache_for(root))


def read_baseline(path: Path) -> dict:
    """The baseline, refused when it was measured some other way than this gate measures."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("profile") != BASELINE_PROFILE:
        raise CannotCheck(f"{path} has profile {document.get('profile')!r}, not {BASELINE_PROFILE}")
    measured = document.get("checker", {})
    if (document.get("code"), measured.get("target"), tuple(measured.get("arguments", ()))) != (
        CODE,
        TARGET,
        ARGUMENTS,
    ):
        raise CannotCheck(
            f"{path} counts {document.get('code')!r} over {measured.get('target')!r} with "
            f"{measured.get('arguments')}, and this gate counts {CODE!r} over {TARGET!r} with "
            f"{list(ARGUMENTS)}; measure a new baseline rather than compare the two"
        )
    return document


def compare(
    counts: Mapping[str, int], baseline: Mapping[str, int]
) -> tuple[list[str], list[str]]:
    """The rises and the falls, each as a sentence naming the file, the baseline and the count."""
    rises, falls = [], []
    for path in sorted(set(counts) | set(baseline)):
        now, before = counts.get(path, 0), baseline.get(path, 0)
        if now > before:
            rises.append(f"{path}: {now}, baseline {before}")
        elif now < before:
            falls.append(f"{path}: {now}, baseline {before}")
    total, allowed = sum(counts.values()), sum(baseline.values())
    if total > allowed:
        rises.append(f"total: {total}, baseline {allowed}")
    elif total < allowed:
        falls.append(f"total: {total}, baseline {allowed}")
    return rises, falls


def baseline_document(checker: Checker, measurement: Measurement) -> dict:
    return {
        "profile": BASELINE_PROFILE,
        "code": CODE,
        "checker": {"mypy": checker.version, "target": TARGET, "arguments": list(ARGUMENTS)},
        "counts": measurement.counts(),
    }


def _print(lines: Iterable[str]) -> None:
    for line in lines:
        print(f"  {line}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--write-baseline", action="store_true", help=f"record this run's counts in {BASELINE}"
    )
    known = parser.parse_args(list(argv) if argv is not None else None)
    path = ROOT / BASELINE
    try:
        # A new baseline is measured with the newest cached mypy; a comparison uses the version the
        # baseline was measured with, because another version reports other errors.
        baseline = None if known.write_baseline or not path.is_file() else read_baseline(path)
        version = None if baseline is None else baseline["checker"]["mypy"]
        checker, measurement = measure(ROOT, version)
    except CannotCheck as refusal:
        print(f"type_gate: nothing was measured, because {refusal}", flush=True)
        return CANNOT_CHECK
    counts = measurement.counts()
    print(
        f"type_gate: mypy {checker.version} checked {measurement.checked} source files and "
        f"reported {len(measurement.errors)} errors, {sum(counts.values())} of them {CODE}"
    )
    if known.write_baseline:
        path.write_text(json.dumps(baseline_document(checker, measurement), indent=2) + "\n")
        print(f"type_gate: wrote {BASELINE}")
        return 0
    if baseline is None:
        print(f"type_gate: {BASELINE} is missing; write it with --write-baseline")
        return CANNOT_CHECK
    rises, falls = compare(counts, baseline["counts"])
    if falls:
        print(f"type_gate: fewer {CODE} errors than {BASELINE} allows; lower it with --write-baseline:")
        _print(falls)
    if rises:
        print(f"type_gate: more {CODE} errors than {BASELINE} allows:")
        _print(rises)
        return RISEN
    print(f"type_gate: no file has more {CODE} errors than its baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

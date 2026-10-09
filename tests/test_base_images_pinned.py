"""Every image a build starts from, and every published image a composition runs, names a digest.

A tag moves: the same Dockerfile built twice can start from two different bases, and resolving a
tag needs the registry, so a registry outage stops a build whose bases are already held (seen
2026-10-09: Docker Hub's token endpoint answered 504 to every tag lookup). So each ``FROM`` in a
tracked Dockerfile names its base as ``name:tag@sha256:<digest>``, an earlier stage of the same
file, a named build context the composition passes (``backend``), or a build argument (whose value
the caller states, by digest where its own documentation says so); and each ``image:`` in a
composition is either such a reference or an image this repository builds (``exulanica-*``). The
continuous integration's PostgreSQL is the same pinned image the compositions run.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^[a-z0-9./_-]+(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$")
#: Contexts a composition hands a Dockerfile by name (``additional_contexts`` in compose.yaml).
NAMED_CONTEXTS = frozenset({"backend"})


def _tracked(*patterns: str) -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--", *patterns], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in listed]


DOCKERFILES = [p for p in _tracked("*Dockerfile*") if not p.name.endswith(".dockerignore")]
COMPOSITIONS = _tracked("compose.yaml", "deploy/*.yaml", "deploy/**/*.yaml")


def _from_lines(path: Path) -> list[tuple[str, str | None]]:
    """Each ``FROM``'s reference and the stage it names, in order."""
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(
            r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?\s*$", line, re.I
        )
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def test_the_scan_sees_every_dockerfile_and_composition():
    assert {p.relative_to(ROOT).as_posix() for p in DOCKERFILES} >= {
        "Dockerfile",
        "deploy/installation/client.Dockerfile",
        "deploy/installation/maintenance.Dockerfile",
        "deploy/installation/tiles.Dockerfile",
        "deploy/judge/web.Dockerfile",
    }
    assert {p.relative_to(ROOT).as_posix() for p in COMPOSITIONS} >= {
        "compose.yaml",
        "deploy/judge/compose.yaml",
        "deploy/judge/edge.yaml",
        "deploy/public/public.yaml",
    }


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_base_a_dockerfile_starts_from_is_named_by_digest(path: Path):
    stages: set[str] = set()
    for reference, stage in _from_lines(path):
        assert (
            DIGEST.match(reference)
            or reference in stages
            or reference in NAMED_CONTEXTS
            or re.fullmatch(r"\$\{?[A-Z_]+\}?", reference)
        ), f"{path.name}: FROM {reference} names no digest"
        if stage:
            stages.add(stage)


@pytest.mark.parametrize("path", COMPOSITIONS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_image_a_composition_runs_is_built_here_or_named_by_digest(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s+image:\s*(\S+)\s*$", line)
        if match is None:
            continue
        image = match.group(1).strip("'\"")
        assert image.startswith("exulanica-") or DIGEST.match(image), f"{path.name}: {image}"


def test_continuous_integration_runs_the_pinned_postgresql():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    (pinned,) = re.findall(r"^    image: (pgvector/pgvector:\S+)$", compose, re.M)
    assert DIGEST.match(pinned)
    workflow = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
    named = re.findall(r"pgvector/pgvector:[^\s\\]+", workflow)
    assert named and set(named) == {pinned}

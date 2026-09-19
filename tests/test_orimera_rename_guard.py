"""Orimera may appear in this tree only on an explicit reviewed allowlist.

ADR-0011 withdrew the pre-release name. Current product identifiers say Exulanica.
A new occurrence is a defect unless it is added here with a reviewed reason.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ORIMERA = re.compile(r"orimera", re.IGNORECASE)

#: Prefixes whose entire tracked contents may mention Orimera. Do not edit them
#: merely to rename; the paths and bytes are historical evidence.
ALLOWED_PREFIXES: dict[str, str] = {
    "docs/evaluation/": ("immutable evaluation records and bound artifacts; ADR-0011 class 6"),
    "exulanica/migrations/": ("applied historical SQL; checksummed bytes stay as written"),
    "tests/fixtures/scene-segments-production/": (
        "captured measurement commands that name the historical checkout path"
    ),
}

#: Tracked files that may mention Orimera, and why the mention is still required.
ALLOWED_PATHS: dict[str, str] = {
    ".dockerignore": "names the gitignored .orimera working area as build-context bulk",
    ".gitignore": (
        "keeps the private .orimera/ tree out of git and records the sibling "
        "orimera-person-consent worktree layout"
    ),
    "deploy/gsplat/run-scene-worker.sh": (
        "REPO_DIR prefers ~/exulanica and falls back to ~/orimera on existing GPU hosts"
    ),
    "docs/adr/0011-exulanica-namespace.md": (
        "accepted rename decision, evidence table, and identifier matrix"
    ),
    "docs/deployment.md": ("documents that EXULANICA_DATA_DIR does not look at .orimera/"),
    "docs/development-setup.md": (
        "documents the withdrawn Orimera names and that the store ignores .orimera/"
    ),
    "docs/evaluation-corpus-contract.md": (
        "records a dated local-discovery result that searched private .orimera "
        "state and found the synthetic orimera-corpus fixture"
    ),
    "docs/frontier-roadmap.md": (
        "states the cutover exit gate: Orimera survives only as historical SQL, "
        "git history, and the ADR evidence table"
    ),
    "docs/person-presentation-consent.md": (
        "records a corrected pre-rename launch configuration that still named "
        "ORIMERA_ and orimera.api.app"
    ),
    "docs/retained-reference-workflow.md": (
        "documents ~/exulanica as the new host checkout and ~/orimera as the existing layout"
    ),
    "docs/world-memory-package.md": (
        "records that the pre-release orimera-wmp-1.0 profile was withdrawn"
    ),
    "exulanica/env.py": (
        "states that withdrawn Orimera names are not read, the store ignores "
        ".orimera, and operator briefs fall back to .orimera/briefs"
    ),
    "exulanica/orchestration/judge_seed.py": (
        "explains why consent_record filters on tenant_id rather than the "
        "historical orimera.tenant_id GUC from migration 0001"
    ),
    "exulanica/orchestration/person_withdrawal.py": ("rejects evaluation stores under .orimera"),
    "scripts/migrate_preview_point_map.py": (
        "legacy parser that rewrites the withdrawn orimera-point-map format"
    ),
    "scripts/reference_instance.py": (
        "strips inherited ORIMERA_ variables so they cannot leak into a child"
    ),
    "tests/test_documentation_links.py": (
        "records why the gitignored .orimera working area is not a source of references"
    ),
    "tests/test_exulanica_identity.py": (
        "asserts that ORIMERA_ names, .orimera paths, orimera- CLIs, and "
        "X-Orimera headers are not live writers"
    ),
    "tests/test_frontier_preflight.py": (
        "rejects the historical postgresql://localhost:5433/orimera URL"
    ),
    "tests/test_living_world_preview.py": (
        "verifies the documented legacy .orimera/briefs fallback for existing operator state"
    ),
    "tests/test_models_client.py": (
        "uses ORIMERA as an arbitrary model-output token, not a product identifier"
    ),
    "tests/test_orimera_rename_guard.py": "this allowlist and the scan that enforces it",
    "tests/test_person_withdrawal_evaluation.py": (
        "rejects orimera_spine_test URLs and .orimera evaluation stores"
    ),
    "web/packages/atlas-react/test/generated-tile-bench/evidence/plan-clip.README.txt": (
        "names this guard's own file while explaining a redaction this guard required; any "
        "honest note about this scan has to spell the scan's name"
    ),
    "web/packages/app/test/preview.test.ts": (
        "rejects the withdrawn orimera-point-map format header"
    ),
    "web/packages/landing/test/viewport-boundary.test.ts": (
        "rejects leftover orimera viewport-test titles"
    ),
}

_SKIP_SUFFIXES = {
    ".bin",
    ".image",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".ico",
    ".mp4",
    ".wasm",
    ".woff",
    ".woff2",
}


def _tracked_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode()
    return [relative for relative in listed.split("\0") if relative]


def _reason_for(relative: str) -> str | None:
    for prefix, reason in ALLOWED_PREFIXES.items():
        if relative.startswith(prefix):
            return reason
    return ALLOWED_PATHS.get(relative)


def test_orimera_occurs_only_on_the_reviewed_allowlist() -> None:
    unexpected: list[str] = []
    seen_allowed: set[str] = set()
    relatives = set(_tracked_files())
    relatives.add("tests/test_orimera_rename_guard.py")
    for relative in sorted(relatives):
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        reason = _reason_for(relative)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _ORIMERA.search(text) is None:
            continue
        if reason is None:
            lines = [
                f"    {index}: {line.rstrip()}"
                for index, line in enumerate(text.splitlines(), start=1)
                if _ORIMERA.search(line)
            ]
            unexpected.append(f"{relative}\n" + "\n".join(lines[:8]))
            continue
        if relative in ALLOWED_PATHS:
            seen_allowed.add(relative)
    unused = sorted(set(ALLOWED_PATHS) - seen_allowed)
    assert not unexpected, (
        "Orimera appears outside the reviewed allowlist. Either replace the "
        "current branding or add the path with a reason:\n" + "\n".join(unexpected)
    )
    assert not unused, (
        "allowlisted files no longer mention Orimera; remove them from "
        "ALLOWED_PATHS:\n  " + "\n  ".join(unused)
    )


def test_every_allowlisted_path_states_why_it_remains() -> None:
    assert all(reason.strip() for reason in ALLOWED_PATHS.values())
    assert all(reason.strip() for reason in ALLOWED_PREFIXES.values())

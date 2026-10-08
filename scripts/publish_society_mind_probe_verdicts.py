#!/usr/bin/env python3
"""Publish the verdicts of the candidate mind probe, and nothing else of it.

    uv run python scripts/publish_society_mind_probe_verdicts.py

``scripts/measure_society_mind_probe.py`` asks candidate open models a being's choices and writes
its record beside the worktree, untracked, because a per-model record of a hosted provider's models
is published only once the provider's terms allow it. The manifest admits a model to a chosen role
only by a retained record whose verdict verified it, so this writes the one part the manifest
needs: per model and mechanism whether it was verified and whether it answers a choice that takes a
line, the rule each verdict was read by, the answering the manifest takes from them, and the digests
that bind it to the full record, its pre-registration, the script that asked and the cases asked.
No count, time or cost is copied. It refuses a full record that does not match its own digest or
name its pre-registration, and a probe script whose bytes are not the ones that asked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import measure_society_mind_probe as probe  # noqa: E402
from measure_society_person_models import _read_record, _sha256, _write_new  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402

VERDICTS: Final = "docs/evaluation/2026-10-08-society-mind-probe-verdicts.json"
#: How the manifest's answering is read from the verdicts, where it is stricter than the
#: pre-registered clause.
ANSWERING_RULE: Final = (
    "A model's answering names each mechanism verified for it; where at least one of its verified "
    "mechanisms answers lines, only those that answer lines. A contract asks a model by the first "
    "mechanism of its order for every choice, a choice that takes a line included, and the "
    "person's contract ranks a forced call first, so a mechanism that answers only choices without "
    "a line would fail every choice that takes one wherever it is ranked first."
)
DEVIATION: Final = (
    "The pre-registered manifest clause admits every mechanism that answers. This answering admits "
    "fewer: a verified mechanism that does not answer lines is left out for a model another "
    "mechanism serves for lines."
)


def answering(verdicts: dict[str, dict[str, dict[str, Any]]]) -> dict[str, list[str]]:
    """Per model, the mechanisms the manifest names for it, by :data:`ANSWERING_RULE`."""
    found: dict[str, list[str]] = {}
    for model_id, by in sorted(verdicts.items()):
        verified = sorted(mechanism for mechanism, held in by.items() if held["verified"])
        lines = [mechanism for mechanism in verified if by[mechanism]["answers_lines"]]
        found[model_id] = lines or verified
    return found


def main() -> None:
    record = _read_record(probe.RECORD)
    registered = _read_record(probe.PREREGISTRATION)
    if record["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit("the record does not name this pre-registration")
    script = (ROOT / probe.SCRIPT).read_bytes()
    if _sha256(script) != record["script_sha256"]:
        raise SystemExit(f"{probe.SCRIPT} is not the script that asked")
    if record["stopped"] is not None:
        raise SystemExit(f"the probe stopped before it asked everything: {record['stopped']}")
    verdicts = {
        model_id: {
            mechanism: {
                "verified": bool(held["verified"]),
                "answers_lines": bool(held["answers_lines"]),
            }
            for mechanism, held in sorted(by.items())
        }
        for model_id, by in sorted(record["verdicts"].items())
    }
    _write_new(
        VERDICTS,
        {
            "question": registered["question"],
            "candidates": registered["candidates"],
            "mechanisms": registered["mechanisms"],
            "verdict_rule": registered["verdict_rule"],
            "verdicts": verdicts,
            "answering": answering(verdicts),
            "answering_rule": ANSWERING_RULE,
            "deviation": DEVIATION,
            "measured": {
                "tree_head": record["tree"]["head"],
                "record_sha256": _sha256(canonical_json(record)),
                "preregistration_record_sha256": record["preregistration_record_sha256"],
                "script": probe.SCRIPT,
                "script_sha256": record["script_sha256"],
                "contexts_sha256": registered["contexts_sha256"],
                "manifest_sha256": record["manifest_sha256"],
                "prompt_version": registered["prompt_version"],
                "contract": registered["contract"],
            },
            "full_record": (
                "Kept untracked beside the worktree that measured it, with every call, until the "
                "provider's terms allow publishing per-model figures; record_sha256 above binds it."
            ),
            "publisher_sha256": _sha256(Path(__file__).read_bytes()),
        },
    )


if __name__ == "__main__":
    main()

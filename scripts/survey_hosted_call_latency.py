"""Measure each hosted role's latency from the calls the retained evaluation records hold.

    uv run python scripts/survey_hosted_call_latency.py            # print the per-role basis
    uv run python scripts/survey_hosted_call_latency.py --write    # also write the record

Reads the tracked files under ``docs/evaluation`` and the model manifest, and nothing else: no
network, no key, no database. Only tracked files, because a working tree can hold local campaigns
a clone does not, and a basis read from those would be one nobody else can reproduce. Every number
it reports comes from a record in the repository, so a clone reproduces it. The manifest's ``timeout_basis`` for each role quotes the record this writes, and
:func:`exulanica.models.manifest.parse_manifest` refuses a timeout that the basis and the
manifest's ``timeout_rule`` do not produce.

Four shapes of record carry a hosted call's latency, and each is read for what it is:

*   **A call row**: a ``role`` and an integer ``latency_ms`` beside the model the response named
    (``served_model``, else ``requested_model``). One request when ``attempts`` is 1. ``attempts``
    0 is a cache hit and is skipped; 2 or more includes a retry or a failover and is reported
    separately, because a per-request timeout cuts each attempt and not their sum. An embedding
    row records no attempt count and is one request: the embedding role has no fallback and the
    API client makes one attempt.
*   **A per-question arm** in the model-selection outcome: one model's answer to one question,
    naming the model in ``served_models``. One composer call, or two when ``repaired`` is true.
*   **A per-photograph row** in a vision place-proposal outcome: one or two vision calls
    (``calls``) on one photograph. These records disabled the fallback in both arms, so the
    vision primary served every call.
*   **An ingest event**, ``capture_succeeded`` with model calls in its cost: the whole capture,
    vision calls and the rest of the stage.

A row covering more than one call, or more work than one call, bounds that call from above and is
counted as such. The longest measured latency of a role's primary is what the timeout rule reads.
A call is counted once however many records copy it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest_from

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "docs" / "evaluation"
OUT = EVALUATION / "2026-09-24-hosted-call-latency.json"
#: A record whose file name says so holds replies a test script fed the client: no request left.
_NO_NETWORK = re.compile(r"scripted|dry-run")
_VISION_PROPOSAL = re.compile(r"vision-place-proposal.*-outcome\.json$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _whole(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _rows(relative: str, document: Any, primaries: Mapping[str, str]) -> Iterator[dict[str, Any]]:
    """Every latency this record holds, as (role, model, ms, requests it covers, shape, identity)."""
    vision_proposal = bool(_VISION_PROPOSAL.search(relative))
    for node in _walk(document):
        latency = _whole(node.get("latency_ms"))
        role = node.get("role")
        if latency is not None and isinstance(role, str) and role in primaries:
            attempts = node.get("attempts")
            if attempts == 0:
                continue
            model = node.get("served_model") or node.get("requested_model")
            if not isinstance(model, str):
                continue
            yield {
                "role": role,
                "model": model,
                "ms": latency,
                "requests": 1 if attempts is None else attempts,
                "shape": "call",
                "identity": (
                    role,
                    latency,
                    node.get("prompt_tokens"),
                    node.get("completion_tokens"),
                    node.get("usd"),
                ),
            }
            continue
        served = node.get("served_models")
        if latency is not None and isinstance(served, list) and len(set(served)) == 1:
            model = served[0]
            for bound_role, primary in primaries.items():
                if primary == model:
                    yield {
                        "role": bound_role,
                        "model": model,
                        "ms": latency,
                        "requests": 2 if node.get("repaired") else 1,
                        "shape": "per_question_arm",
                        "identity": ("arm", model, latency, node.get("micro_usd")),
                    }
            continue
        if vision_proposal and latency is not None and isinstance(node.get("file"), str):
            calls = _whole(node.get("calls"))
            yield {
                "role": str(Role.VISION),
                "model": primaries[str(Role.VISION)],
                "ms": latency,
                "requests": calls if calls is not None else 1,
                "shape": "per_photograph",
                "identity": ("photograph", node["file"], latency, node.get("micro_usd")),
            }
            continue
        cost = node.get("cost")
        duration = _whole(node.get("duration_ms"))
        if (
            node.get("event_type") == "capture_succeeded"
            and isinstance(cost, Mapping)
            and (_whole(cost.get("model_calls")) or 0) > 0
            and duration is not None
        ):
            yield {
                "role": str(Role.VISION),
                "model": primaries[str(Role.VISION)],
                "ms": duration,
                # The stage did more than its model calls, so this bounds the call from above.
                "requests": max(2, _whole(cost.get("model_calls")) or 0),
                "shape": "ingest_capture",
                "identity": ("capture", node.get("event_id")),
            }


def _percentile(sorted_ms: list[int], fraction: float) -> int:
    """Nearest rank, no interpolation: a value that was measured, never one between two."""
    rank = -(-len(sorted_ms) * round(fraction * 100) // 100)
    return sorted_ms[max(rank, 1) - 1]


def _tracked_records() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", EVALUATION.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode()
    return sorted(ROOT / name for name in listed.split("\0") if name.endswith(".json"))


def survey() -> dict[str, Any]:
    manifest = load_manifest_from(MANIFEST_PATH)
    # Every role the manifest binds to a model. A chosen role has no model of its own to survey.
    bound = [role for role in Role if role in manifest.roles]
    primaries = {str(role): manifest[role].primary.model_id for role in bound}
    fallbacks = {
        str(role): (manifest[role].fallback.model_id if manifest[role].fallback else None)
        for role in bound
    }
    seen: set[tuple[Any, ...]] = set()
    rows: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    for path in _tracked_records():
        relative = path.relative_to(ROOT).as_posix()
        if path == OUT or _NO_NETWORK.search(relative):
            continue
        data = path.read_bytes()
        try:
            document = json.loads(data)
        except json.JSONDecodeError:
            continue
        found = False
        for row in _rows(relative, document, primaries):
            if row["identity"] in seen:
                continue
            seen.add(row["identity"])
            rows.append({**row, "source": relative})
            found = True
        if found:
            sources[relative] = _sha256(data)

    by_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[(row["role"], row["model"])].append(row)

    roles: dict[str, Any] = {}
    for role in bound:
        name = str(role)
        entry: dict[str, Any] = {"primary": primaries[name], "fallback": fallbacks[name]}
        for which in ("primary", "fallback"):
            model = entry[which]
            # A retried call's latency includes an attempt that ended on the timeout in force
            # then, so it measures that timeout rather than a response. Reported below instead.
            measured = [
                r
                for r in (by_model.get((name, model), []) if model else [])
                if not (r["shape"] == "call" and r["requests"] > 1)
            ]
            single = sorted(r["ms"] for r in measured if r["requests"] == 1)
            covering = sorted(r["ms"] for r in measured)
            longest = max(measured, key=lambda r: r["ms"]) if measured else None
            entry[f"{which}_measured"] = (
                None
                if not measured
                else {
                    "rows": len(covering),
                    "single_request_rows": len(single),
                    "p50_ms": _percentile(covering, 0.5),
                    "p99_ms": _percentile(covering, 0.99),
                    "longest_ms": covering[-1],
                    "longest_source": longest["source"] if longest else None,
                    "longest_shape": longest["shape"] if longest else None,
                    "longest_covers_requests": longest["requests"] if longest else None,
                    "shapes": dict(sorted(_count(r["shape"] for r in measured).items())),
                }
            )
        retried = sorted(
            (r["ms"], r["requests"], r["source"])
            for r in rows
            if r["role"] == name and r["shape"] == "call" and r["requests"] > 1
        )
        entry["retried_calls"] = [
            {"latency_ms": ms, "attempts": attempts, "source": source}
            for ms, attempts, source in retried
        ]
        roles[name] = entry
    return {"manifest_sha256": _sha256(MANIFEST_PATH.read_bytes()), "roles": roles, "sources": sources}


def _count(values: Iterator[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(ROOT)}")
    args = parser.parse_args()
    measured = survey()
    body = {
        "measured": measured,
        "measured_with_sha256": _sha256(Path(__file__).read_bytes()),
        "profile_note": (
            "Per-role latency of hosted model calls, read from the retained evaluation records by "
            "scripts/survey_hosted_call_latency.py. The model manifest's timeout_basis quotes "
            "longest_ms for each role's primary."
        ),
        "not_established": [
            "Latency on real personal photographs: every vision row is a synthetic drawing.",
            "Latency under concurrent load: each record asked one question at a time.",
            "What the provider bills for a request the client stopped waiting for.",
        ],
    }
    for name, entry in measured["roles"].items():
        primary = entry["primary_measured"]
        print(
            f"{name}: primary {entry['primary']} "
            + (
                "unmeasured"
                if primary is None
                else f"rows {primary['rows']} p50 {primary['p50_ms']} p99 {primary['p99_ms']} "
                f"longest {primary['longest_ms']} ({primary['longest_shape']})"
            )
        )
    if args.write:
        document = {
            "profile": "exulanica.digest-bound-record/v1",
            "record": body,
            "record_sha256": _sha256(canonical_json(body)),
        }
        OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{OUT.relative_to(ROOT)} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()

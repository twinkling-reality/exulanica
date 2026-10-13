"""Plain-word account of what changed between two selected checkpoints.

The sentences describe only the selected checkpoint fields. The raw field diff from `changes`
stays the authority; these words are a reading aid placed above it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.world_package.projects.checkpoint import changes, document


def _names(things: list[dict[str, Any]]) -> dict[str, str]:
    """Call a thing by its shipped kind when that kind is unique in the selection."""
    kinds = Counter(
        thing["kind"].get("kind") for thing in things if thing["kind"].get("kind") is not None
    )
    names = {}
    for thing in things:
        kind = thing["kind"].get("kind")
        names[thing["thing_id"]] = (
            f"the {kind.replace('_', ' ')}"
            if kind is not None and kinds[kind] == 1
            else thing["thing_id"]
        )
    return names


def _metres(mm: int) -> str:
    value = abs(mm) / 1000
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} m"


def _movement(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Region-local x grows east, z grows south and y grows up (millimetres)."""
    parts = []
    for axis, positive, negative in (
        ("x_mm", "east", "west"),
        ("z_mm", "south", "north"),
        ("y_mm", "up", "down"),
    ):
        delta = after[axis] - before[axis]
        if delta:
            parts.append(f"{_metres(delta)} {positive if delta > 0 else negative}")
    return parts


def _turn(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    delta = after["yaw_microradians"] - before["yaw_microradians"]
    if not delta:
        return None
    degrees = round(math.degrees(delta / 1_000_000))
    return f"{abs(degrees)} degrees" if degrees else "slightly"


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


def summarize(before: Any | None, after: Any) -> list[str]:
    """Sentences for each meaningful selected change, in a stable order; empty when unchanged."""
    new = document(after)
    if before is None:
        parts = [
            _plural(len(new["things"]), "thing"),
            _plural(len(new["models"]), "model assignment"),
            *([_plural(len(new["decisions"]), "decision record")] if new["decisions"] else []),
        ]
        return [f"started project {new['project_id']} with {', '.join(parts[:-1])} and {parts[-1]}"]
    old = document(before)
    lines: list[str] = []
    if old["project_id"] != new["project_id"]:
        lines.append(f"renamed the project from {old['project_id']} to {new['project_id']}")
    if old["forked_from"] != new["forked_from"] and new["forked_from"] is not None:
        lines.append(f"forked from project {new['forked_from']['project_id']}")
    if old["source"] != new["source"]:
        lines.append(f"moved to source world version {new['source']['version_id']}")

    names = {**_names(old["things"]), **_names(new["things"])}
    before_things = {t["thing_id"]: t for t in old["things"]}
    after_things = {t["thing_id"]: t for t in new["things"]}
    for thing_id in sorted(after_things.keys() - before_things.keys()):
        lines.append(f"added {names[thing_id]}")
    for thing_id in sorted(before_things.keys() - after_things.keys()):
        lines.append(f"dropped {names[thing_id]} from the selection")
    for thing_id in sorted(before_things.keys() & after_things.keys()):
        was, now = before_things[thing_id], after_things[thing_id]
        name = names[thing_id]
        if was["removed"] != now["removed"]:
            lines.append(f"{'removed' if now['removed'] else 'restored'} {name}")
        if was["region_id"] != now["region_id"]:
            lines.append(f"moved {name} to region {now['region_id']}")
        else:
            movement = _movement(was["transform"], now["transform"])
            if movement:
                lines.append(f"moved {name} {' and '.join(movement)}")
        turn = _turn(was["transform"], now["transform"])
        if turn:
            lines.append(f"turned {name} {turn}")
        if was["kind"] != now["kind"]:
            lines.append(f"changed what kind of thing {name} is")
        if was["origin"] != now["origin"]:
            lines.append(f"changed the origin of {name}")

    before_models = {m["thing_id"]: m for m in old["models"]}
    after_models = {m["thing_id"]: m for m in new["models"]}
    for thing_id in sorted(after_models.keys() | before_models.keys()):
        was, now = before_models.get(thing_id), after_models.get(thing_id)
        name = names.get(thing_id, thing_id)
        if was is None and now is not None:
            lines.append(f"assigned {now['model_id']} to {name}")
        elif now is None and was is not None:
            lines.append(f"unassigned {was['model_id']} from {name}")
        elif was != now and was is not None and now is not None:
            if was["model_id"] != now["model_id"]:
                lines.append(f"changed {name} from {was['model_id']} to {now['model_id']}")
            else:
                lines.append(f"changed how {name} is bound to {now['model_id']}")

    before_records = {d["record_id"]: d for d in old["decisions"]}
    after_records = {d["record_id"]: d for d in new["decisions"]}
    added = len(after_records.keys() - before_records.keys())
    dropped = len(before_records.keys() - after_records.keys())
    edited = sum(
        1
        for key in before_records.keys() & after_records.keys()
        if before_records[key] != after_records[key]
    )
    if added:
        lines.append(f"added {_plural(added, 'decision record')}")
    if dropped:
        lines.append(f"dropped {_plural(dropped, 'decision record')}")
    if edited:
        lines.append(f"edited {_plural(edited, 'decision record')}")

    before_deps = {d["sha256"] for d in old["dependencies"]}
    after_deps = {d["sha256"] for d in new["dependencies"]}
    for verb, count in (
        ("added", len(after_deps - before_deps)),
        ("dropped", len(before_deps - after_deps)),
    ):
        if count:
            lines.append(f"{verb} {_plural(count, 'dependency', 'dependencies')}")
    if old["region_ids"] != new["region_ids"] and not lines:
        lines.append("changed the selected regions")
    if not lines and old != new:
        lines.append("changed selected details; see the field diff")
    return lines


def report(before: Any | None, after: Any) -> dict[str, Any]:
    """Words first, the raw field diff underneath."""
    return {"summary": summarize(before, after), "diff": changes(before, after)}


def subject(before: Any | None, after: Any, evidence: Sequence[str] = ()) -> str:
    """A one-line commit subject drawn from the first sentences of the summary."""
    lines = [*summarize(before, after), *evidence]
    if not lines:
        return ""
    text = lines[0]
    for index, line in enumerate(lines[1:], start=1):
        if len(text) + len(line) + 2 > 100:
            text += f", and {_plural(len(lines) - index, 'more change')}"
            break
        text += f", {line}"
    return (text[0].upper() + text[1:])[:120]


def evidence_summary(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Sentences about decision evidence. Evidence is what happened, never part of the world."""
    lines = []
    for name in sorted(after.keys() | before.keys()):
        old, new = before.get(name), after.get(name)
        if new is None:
            lines.append(f"dropped the evidence file {name}")
            continue
        session = new["session_id"]
        known = {d["record_id"] for d in old["decisions"]} if old is not None else set()
        added = sum(1 for d in new["decisions"] if d["record_id"] not in known)
        if old is None:
            lines.append(f"recorded {_plural(added, 'decision record')} from session {session}")
        elif added:
            lines.append(
                f"recorded {_plural(added, 'more decision record')} from session {session}"
            )
        elif old != new:
            lines.append(f"changed the evidence of session {session}")
    return lines

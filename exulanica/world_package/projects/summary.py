"""Plain-word account of what changed between two selected checkpoints.

The sentences describe only the selected checkpoint fields, in the workspace's words
(:mod:`exulanica.world_package.projects.words`): build mode's words for moves and removals, a
character by its name or its kind, a model by the name the workspace gives it. Each sentence
starts with what was done ("Moved", "Changed", "Recorded"), never with a name, and holds no
identity, digest or code. The raw field diff from `changes` stays the authority; these words are
a reading aid placed above it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.world_package.projects.checkpoint import changes, document
from exulanica.world_package.projects.words import (
    capital,
    model_name,
    names,
    part_names,
    plural,
    possessive,
    quoted,
)

#: What a thing follows when no model decides for it, as the workspace says it.
ROUTINE = "Routine"


def thing_names(things: list[dict[str, Any]]) -> dict[str, str]:
    """What each of `things` is called, by its kind (a checkpoint's own names need its
    characters: use `words.names` with the checkpoint)."""
    return names([{"things": things}])


def metres(mm: int) -> str:
    value = abs(mm) / 1000
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} m"


def movement(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Region-local x grows east, z grows south and y grows up (millimetres)."""
    parts = []
    for axis, positive, negative in (
        ("x_mm", "east", "west"),
        ("z_mm", "south", "north"),
        ("y_mm", "up", "down"),
    ):
        delta = after[axis] - before[axis]
        if delta:
            parts.append(f"{metres(delta)} {positive if delta > 0 else negative}")
    return parts


def turn(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """A turn as build mode says it: "90°", half a turn "round", "slightly" under a degree."""
    delta = after["yaw_microradians"] - before["yaw_microradians"]
    if not delta:
        return None
    degrees = round(math.degrees(delta / 1_000_000)) % 360
    degrees = 360 - degrees if degrees > 180 else degrees
    if degrees == 180:
        return "round"
    return f"{degrees}°" if degrees else "slightly"


def _part_turn(before: int, after: int) -> str | None:
    """A made part turns in whole quarter turns: "90°" either way, half a turn "round"."""
    quarters = (after - before) % 4
    return {0: None, 1: "90°", 2: "round", 3: "90°"}[quarters]


def parts_changed(
    old: Mapping[str, Any] | None, new: Mapping[str, Any], *, kept: bool = True
) -> list[str]:
    """Build mode's words for a made world's parts: moved, turned, raised or lowered, removed and
    put back. With
    `kept`, a checkpoint that keeps its parts for the first time says so in one sentence."""
    after = {p["part_id"]: p for p in new.get("parts") or []}
    if not after:
        return []
    before = {p["part_id"]: p for p in (old or {}).get("parts") or []}
    if not before:
        standing = sum(1 for p in after.values() if not p["removed"])
        return [f"Kept the {plural(standing, 'part')} this world was made with"] if kept else []
    called = part_names([old, new])
    lines = []
    for part_id in sorted(after):
        was, now = before.get(part_id), after[part_id]
        if was is None or was == now:
            continue
        name = called[part_id]
        if now["removed"] != was["removed"]:
            lines.append(f"Removed {name}" if now["removed"] else f"Put {name} back")
            continue
        if now["removed"]:
            continue
        moved = []
        for axis, positive, negative in ((0, "east", "west"), (1, "north", "south")):
            delta = now["centre_mm"][axis] - was["centre_mm"][axis]
            if delta:
                moved.append(f"{metres(delta)} {positive if delta > 0 else negative}")
        turned = _part_turn(was["quarter_turns"], now["quarter_turns"])
        if moved:
            lines.append(
                f"Moved {name} {' and '.join(moved)}" + (f", turned {turned}" if turned else "")
            )
        elif turned:
            lines.append(f"Turned {name} {turned}")
        storeys = (was.get("storeys"), now.get("storeys"))
        if None not in storeys and storeys[0] != storeys[1]:
            verb = "Raised" if storeys[1] > storeys[0] else "Lowered"
            lines.append(f"{verb} {name} to {plural(storeys[1], 'storey')}")
    return lines


def _moved(name: str, before: dict[str, Any], after: dict[str, Any]) -> str | None:
    moved, turned = movement(before, after), turn(before, after)
    if moved:
        return f"Moved {name} {' and '.join(moved)}" + (f", turned {turned}" if turned else "")
    return f"Turned {name} {turned}" if turned else None


def _characters(
    old: Mapping[str, Any] | None, new: Mapping[str, Any], called: Mapping[str, str], quote: bool
) -> list[str]:
    """What the world's owner wrote for each being. With the words kept: named, renamed,
    wrote, changed or cleared; without them only that a record was written."""
    before = {c["thing_id"]: c for c in (old or {}).get("characters") or []}
    after = {c["thing_id"]: c for c in new.get("characters") or []}
    lines = []
    for thing_id in sorted(after):
        was, now = before.get(thing_id), after[thing_id]
        if was is not None and was["revision"] == now["revision"]:
            continue
        name = called.get(thing_id, "a character")
        if "words" not in now:
            lines.append(f"{'Wrote' if was is None else 'Changed'} {possessive(name)} personality")
            continue
        old_words = (was or {}).get("words") or {}
        new_words = now["words"]
        old_name, new_name = old_words.get("name"), new_words.get("name")
        if old_name != new_name:
            if new_name is None:
                lines.append(f"Cleared the name {old_name}")
            elif old_name is None:
                lines.append(f"Named {_unnamed(thing_id, new, old)} {new_name}")
            else:
                lines.append(f"Renamed {old_name} to {new_name}")
        old_about, new_about = old_words.get("about"), new_words.get("about")
        if old_about != new_about:
            if new_about is None:
                lines.append(f"Cleared {possessive(name)} personality")
            else:
                verb = "Wrote" if old_about is None else "Changed"
                lines.append(
                    f"{verb} {possessive(name)} personality"
                    + (f": {quoted(new_about)}" if quote else "")
                )
    return lines


def _unnamed(thing_id: str, new: Mapping[str, Any], old: Mapping[str, Any] | None) -> str:
    """What a thing was called before its owner named it: its kind."""
    kept = [c for c in new.get("characters") or [] if c["thing_id"] != thing_id]
    return names([old, {**new, "characters": kept}]).get(thing_id, "a character")


def _models(
    old: Mapping[str, Any] | None, new: Mapping[str, Any], called: Mapping[str, str]
) -> list[str]:
    before = {m["thing_id"]: m for m in (old or {}).get("models", [])}
    after = {m["thing_id"]: m for m in new["models"]}
    lines = []
    for thing_id in sorted(after.keys() | before.keys()):
        was, now = before.get(thing_id), after.get(thing_id)
        name = called.get(thing_id, "a character")
        if was == now:
            continue
        if now is None:
            lines.append(f"Changed {possessive(name)} model to {ROUTINE}")
        elif was is None or was["model_id"] != now["model_id"]:
            lines.append(f"Changed {possessive(name)} model to {model_name(now['model_id'])}")
        else:
            lines.append(f"Updated the details of {possessive(name)} model")
    return lines


def summarize(before: Any | None, after: Any, *, quote: bool = False) -> list[str]:
    """Sentences for each meaningful selected change, in a stable order; empty when unchanged.

    With `quote`, a personality's sentence quotes the words its owner wrote, where the project
    kept them (a pull request's world section); a commit subject never carries them."""
    new = document(after)
    old = None if before is None else document(before)
    called = names([old, new])
    if old is None:
        return [
            f"Started the project with {plural(len(new['things']), 'thing')}",
            *parts_changed(None, new),
            *_characters(None, new, called, quote),
            *_models(None, new, called),
            *(
                [f"Recorded {plural(len(new['decisions']), 'decision')}"]
                if new["decisions"]
                else []
            ),
        ]
    lines: list[str] = []
    if old["project_id"] != new["project_id"]:
        lines.append("Renamed the project")
    if old["forked_from"] != new["forked_from"] and new["forked_from"] is not None:
        lines.append("Started this project as a copy of another")
    # Every edit changes the version's state: only another version is worth a sentence; the edit
    # itself is said by what it changed.
    if old["source"]["version_id"] != new["source"]["version_id"]:
        lines.append("Followed another version of the world")
    if old.get("title") != new.get("title") and new.get("title") is not None:
        lines.append(
            f"Kept the world's name, {new['title']}"
            if old.get("title") is None
            else f"Renamed the world to {new['title']}"
        )

    before_things = {t["thing_id"]: t for t in old["things"]}
    after_things = {t["thing_id"]: t for t in new["things"]}
    for thing_id in sorted(after_things.keys() - before_things.keys()):
        lines.append(f"Added {called[thing_id]}")
    for thing_id in sorted(before_things.keys() - after_things.keys()):
        lines.append(f"Stopped keeping {called[thing_id]} in the project")
    for thing_id in sorted(before_things.keys() & after_things.keys()):
        was, now = before_things[thing_id], after_things[thing_id]
        name = called[thing_id]
        if was["removed"] != now["removed"]:
            lines.append(f"Removed {name}" if now["removed"] else f"Put {name} back")
        if was["region_id"] != now["region_id"]:
            lines.append(f"Moved {name} to another part of the world")
        else:
            moved = _moved(name, was["transform"], now["transform"])
            if moved:
                lines.append(moved)
        if was["kind"] != now["kind"]:
            lines.append(f"Changed what kind of thing {name} is")
        if was["origin"] != now["origin"]:
            lines.append(f"Changed where {name} came from")
    lines += parts_changed(old, new)
    lines += _characters(old, new, called, quote)
    lines += _models(old, new, called)

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
        lines.append(f"Recorded {plural(added, 'decision')}")
    if dropped:
        lines.append(f"Dropped {plural(dropped, 'decision')}")
    if edited:
        lines.append(f"Changed {plural(edited, 'decision')}")
    if old["region_ids"] != new["region_ids"] and not lines:
        lines.append("Changed which parts of the world the project keeps")
    if not lines and old != new:
        lines.append("Changed some details; the files show them")
    return lines


def report(before: Any | None, after: Any) -> dict[str, Any]:
    """Words first, the raw field diff underneath."""
    return {"summary": summarize(before, after), "diff": changes(before, after)}


def subject(before: Any | None, after: Any, evidence: Sequence[str] = ()) -> str:
    """A one-line commit subject drawn from the first sentences of the summary. Every sentence
    starts with what was done, so the ones after the first are joined in lower case."""
    lines = [*summarize(before, after), *evidence]
    if not lines:
        return ""
    text = lines[0]
    for index, line in enumerate(lines[1:], start=1):
        if len(text) + len(line) + 2 > 100:
            text += f", and {plural(len(lines) - index, 'more change')}"
            break
        text += f", {line[:1].lower()}{line[1:]}"
    # A written name may hold what a commit subject may not: a dash a commit refuses, or a
    # control character.
    text = "".join(" " if ord(c) < 32 else c for c in text).replace("\N{EM DASH}", "-")
    return capital(text)[:120]


def run_numbers(*sessions: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """Each living run's number in the project, in the order the runs opened."""
    held: dict[str, Mapping[str, Any]] = {}
    for files in sessions:
        held.update(files)
    living = sorted(
        (session["living_session"]["opened"]["at"], session["session_id"], name)
        for name, session in held.items()
        if session.get("living_session")
    )
    return {name: index + 1 for index, (_, _, name) in enumerate(living)}


def evidence_summary(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Sentences about decision evidence. Evidence is what happened, never part of the world."""
    numbers = run_numbers(before, after)
    lines = []
    for name in sorted(after.keys() | before.keys(), key=lambda n: (numbers.get(n, 0), n)):
        old, new = before.get(name), after.get(name)
        run = f"run {numbers[name]}" if name in numbers else None
        if new is None:
            lines.append(f"Dropped the record of {run}" if run else "Dropped a record of decisions")
            continue
        known = {d["record_id"] for d in old["decisions"]} if old is not None else set()
        added = sum(1 for d in new["decisions"] if d["record_id"] not in known)
        if old is None:
            decisions = plural(added, "decision")
            lines.append(f"Recorded {run}: {decisions}" if run else f"Recorded {decisions}")
        elif added:
            more = plural(added, "more decision")
            lines.append(f"Recorded {more} from {run}" if run else f"Recorded {more}")
        elif old != new:
            lines.append(f"Changed the record of {run}" if run else "Changed a record of decisions")
    return lines

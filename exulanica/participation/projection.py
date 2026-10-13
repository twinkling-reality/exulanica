"""Positive projections for an observer who controls no being and hears no conversation."""

from __future__ import annotations

from collections.abc import Mapping


def _point(value: object) -> list[int] | None:
    if (
        isinstance(value, (list, tuple))
        and len(value) in (2, 3)
        and all(type(part) is int for part in value)
    ):
        return list(value)
    return None


def _kind(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    digest = value.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return None
    if value.get("source") == "workspace":
        return {"source": "workspace", "sha256": digest}
    if isinstance(value.get("kind"), str) and type(value.get("version")) is int:
        return {"kind": value["kind"], "version": value["version"], "sha256": digest}
    return None


def inhabitant(value: Mapping) -> dict:
    """Visible motion and kind only: never names, memories, intentions, lines or actor links."""
    location = value.get("location", {})
    indoors = isinstance(location, Mapping) and location.get("indoors") is True
    return {
        "id": value["id"],
        "kind": _kind(value.get("kind")),
        "position_mm": None if indoors else _point(value.get("position_mm")),
        "indoors": indoors,
        "motion_path_mm": []
        if indoors
        else [
            point for item in value.get("motion_path_mm", ()) if (point := _point(item)) is not None
        ],
    }


def society(row: Mapping) -> dict:
    """An actual world state, with the stored snapshot's digest as a change token only."""
    state = row["state"]
    return {
        "society_id": str(row["society_id"]),
        "profile": row["engine_version"],
        "current_tick": row["current_tick"],
        "tick_seconds": row["tick_seconds"],
        "state_sha256": row["state_sha256"],
        "inhabitants": [inhabitant(person) for person in state.get("inhabitants", ())],
    }


def decider(value: Mapping) -> dict:
    """A decider's public kind and model identity, never a person's or another grant's id."""
    kind = value.get("kind")
    if kind == "model":
        return {"kind": "model", "provider": value["provider"], "model_id": value["model_id"]}
    if kind in ("routine", "person", "external"):
        return {"kind": kind}
    raise ValueError("unsupported participant decider")

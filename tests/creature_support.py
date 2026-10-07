"""Creatures for the tests: the hand-written fixture recipes, and the flat form a model would fill.

The recipes are ``tests/fixtures/creatures/creatures.v1.json``. :func:`form_of` turns one into the
drafter's flat form from the recipe's own fields, independently of the code that reads the form.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "creatures" / "creatures.v1.json").read_text("utf-8")
)


def form_of(name: str, *, label: str, moves: list[str] | None = None) -> dict[str, Any]:
    """The flat form a model would fill for a fixture's recipe, written from the recipe's own
    fields: its heads are alike, so the first head stands for all."""
    recipe = copy.deepcopy((FIXTURES["development"] | FIXTURES["held_out"])[name]["recipe"])
    extent = recipe["extent_mm"]
    counts = {limb["role"]: (limb["count"], limb["segments"]) for limb in recipe["limbs"]}
    moves = ["walking"] if moves is None else moves
    form: dict[str, Any] = {
        "label": label,
        "summary": "A creature of the hills that walks slowly and watches everything.",
        "appearance": recipe["appearance"],
        "posture": recipe["posture"],
        "spine": recipe["spine"],
        "upper_body": recipe["upper_body"],
        "heads": len(recipe["heads"]),
        "neck_bones": recipe["heads"][0]["neck"],
        "jaws": recipe["heads"][0]["jaw"],
        "tail": recipe["tail"],
        "length_mm": extent["length"],
        "width_mm": extent["width"],
        "height_mm": extent["height"],
        "span_mm": extent["span"],
        "holds_with": recipe["holds_with"],
    }
    for role in ("leg", "arm", "wing", "fin", "tentacle"):
        count, segments = counts.get(role, (0, 0))
        form[f"{role}s"] = count
        form[f"{role}_segments"] = segments
    colours = [*recipe["colours"], "amber", "amber"][:4]
    for field, colour in zip(
        ("colour_body", "colour_belly", "colour_accent", "colour_eyes"), colours, strict=True
    ):
        form[field] = colour
    for movement in ("burrowing", "climbing", "flight", "swimming", "walking"):
        form[f"moves_{movement}"] = movement in moves
    abilities = {"wait": 300, "stand": 200, "follow": 0, "say": None}
    for ability in (
        "wait",
        "stand",
        "talk",
        "rest",
        "visit",
        "pick_up",
        "put_down",
        "give",
        "take",
        "follow",
        "say",
    ):
        form[f"can_{ability}"] = ability in abilities
        if ability != "say":
            form[f"weight_{ability}"] = abilities.get(ability) or 0
    for offer in ("talk_to", "hear", "receive", "let_take", "be_followed"):
        form[f"offers_{offer}"] = offer in ("talk_to", "hear", "be_followed")
    return form

"""What the product sends to have a creature's sculpted look made: the creature look request.

``creature_look_request`` writes ``exulanica.creature-look-request/v1``, which the generation job in
``ml/appearance`` reads, from a creature's built body, its recipe and its sketch: the plan's key,
version, digest, bones and chains; each bone's joint, end and thickness at rest in whole
millimetres; the sketch container's digest and length (the container travels beside it); the
recipe's appearance words and its colours by role, each a colour word and its sRGB. Nothing about
who asked: no account, workspace or person's words. The product and the job meet only at this
document, so neither imports the other.

Given a picture kept with the creature, it writes ``exulanica.creature-look-request/v2``: v1 and
the picture's digest and length (the picture travels beside it, as the sketch does), for route P
to make the 3D model from that picture. Without one the bytes are v1's, so a request asked before
is the same document with the same digest. Which pictures may be named is the caller's to decide:
a picture showing a person, or one the person has no right to send to a model, is never named.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from exulanica_pieces.canonical import canonical_bytes

from exulanica.things.bodies import BodyGrammar, BodyRecipe, BuiltBody, body_grammar
from exulanica.things.sketch import colour_names

__all__ = ["COLOUR_ROLES", "REQUEST_PROFILE", "REQUEST_PROFILE_V2", "creature_look_request"]

REQUEST_PROFILE: Final = "exulanica.creature-look-request/v1"
REQUEST_PROFILE_V2: Final = "exulanica.creature-look-request/v2"
#: The roles of a creature's colours, in the order :func:`colour_names` gives them.
COLOUR_ROLES: Final = ("body", "belly", "accent", "eyes")


def _srgb(hex_colour: str) -> list[int]:
    return [int(hex_colour[index : index + 2], 16) for index in (1, 3, 5)]


def creature_look_request(
    *,
    built: BuiltBody,
    recipe: BodyRecipe,
    plan_sha256: str,
    sketch: bytes,
    grammar: BodyGrammar | None = None,
    picture: bytes | None = None,
) -> bytes:
    """The request's canonical bytes for ``built``, whose plan document digests to
    ``plan_sha256``, its sketch container ``sketch`` and, for v2, the kept ``picture``."""
    grammar = grammar or body_grammar()
    plan = built.plan
    document: dict[str, Any] = {
        "profile": REQUEST_PROFILE,
        "plan": {
            "key": plan["key"],
            "version": plan["version"],
            "sha256": plan_sha256,
            "bones": [{"name": bone["name"], "parent": bone["parent"]} for bone in plan["bones"]],
            "limbs": [dict(limb) for limb in plan["limbs"]],
        },
        "rest": {
            bone["name"]: {
                "joint_mm": list(built.joints[bone["name"]]),
                "end_mm": list(built.ends[bone["name"]]),
                "radius_mm": built.radii[bone["name"]][0],
            }
            for bone in plan["bones"]
        },
        "sketch": {"sha256": hashlib.sha256(sketch).hexdigest(), "bytes": len(sketch)},
        "appearance": recipe.appearance,
        "colours": {
            role: {"word": grammar.words[name], "srgb": _srgb(grammar.colours[name])}
            for role, name in zip(COLOUR_ROLES, colour_names(recipe), strict=True)
        },
    }
    if picture is not None:
        document["profile"] = REQUEST_PROFILE_V2
        document["picture"] = {"sha256": hashlib.sha256(picture).hexdigest(), "bytes": len(picture)}
    return canonical_bytes(document)

"""The looks this repository authors, as parts, and the containers they write.

Each look here is original geometry authored for this repository and dedicated to the public domain
under CC0 1.0, like the world object catalog's furniture: a blocky figure in two palettes (a
traveller and a knight in plate), and a sword, a lantern, a well and a gate. Their containers are
written by :mod:`exulanica.things.pieces` and never committed: the bytes are reproducible, and the
look documents under ``assets/catalogs/things/looks`` pin each one's digest, held to these recipes
by a test that writes them again.

A blocky figure is rigid parts on the humanoid plan's named bones (look kind ``rigid_on_bones``):
the joint nodes stand where a 1,700 mm figure's joints stand in the T-pose, the character facing +y
with its left at -x, and every part is a box on the joint it moves with. An upper arm, a lower arm
and a hand are three boxes, so the elbow bends; a blocky figure from a game with one box per limb
would map its arm onto the upper arm alone and say so in its translation manifest.

Pure: no connection, no store.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from types import MappingProxyType
from typing import Final

from exulanica.things.pieces import Node, Part, write_container

__all__ = ["AUTHORED_LOOKS", "BLOCKY_HEIGHT_MM", "container_of", "nodes_of"]

#: How tall the blocky figures stand: the top of the head in the T-pose.
BLOCKY_HEIGHT_MM: Final = 1700
#: Where each joint of the humanoid plan stands in a 1,700 mm blocky figure's T-pose, in the slot
#: frame: the 15 required bones, with chest and neck, which every figure here dresses.
_JOINTS: Final[Mapping[str, tuple[int, int, int]]] = MappingProxyType(
    {
        "hips": (0, 0, 900),
        "spine": (0, 0, 1000),
        "chest": (0, 0, 1150),
        "neck": (0, 0, 1400),
        "head": (0, 0, 1450),
        "leftUpperLeg": (-90, 0, 860),
        "leftLowerLeg": (-90, 0, 460),
        "leftFoot": (-90, 0, 80),
        "rightUpperLeg": (90, 0, 860),
        "rightLowerLeg": (90, 0, 460),
        "rightFoot": (90, 0, 80),
        "leftUpperArm": (-200, 0, 1350),
        "leftLowerArm": (-460, 0, 1350),
        "leftHand": (-700, 0, 1350),
        "rightUpperArm": (200, 0, 1350),
        "rightLowerArm": (460, 0, 1350),
        "rightHand": (700, 0, 1350),
    }
)


def _blocky(palette: Mapping[str, str]) -> tuple[Node, ...]:
    """A blocky figure's joints and parts in ``palette``: skin, hair, shirt, trousers, shoes and
    eyes, or a knight's plate, which colours them all."""

    def box(
        name: str, size: tuple[int, int, int], centre: tuple[int, int, int], colour: str
    ) -> Part:
        return Part(name, "box", size, centre, palette[colour])

    parts: dict[str, tuple[Part, ...]] = {
        "hips": (box("pelvis", (340, 190, 150), (0, 0, -25), "trousers"),),
        "spine": (box("waist", (330, 190, 150), (0, 0, 75), "shirt"),),
        "chest": (box("torso", (360, 200, 250), (0, 0, 125), "shirt"),),
        "neck": (box("throat", (120, 120, 60), (0, 0, 20), "skin"),),
        "head": (
            box("head", (250, 250, 250), (0, 0, 125), "skin"),
            box("hair", (260, 260, 60), (0, 0, 230), "hair"),
            box("left-eye", (30, 10, 30), (-55, 126, 140), "eyes"),
            box("right-eye", (30, 10, 30), (55, 126, 140), "eyes"),
        ),
        "leftUpperLeg": (box("left-thigh", (150, 160, 400), (0, 0, -200), "trousers"),),
        "leftLowerLeg": (box("left-shin", (140, 150, 380), (0, 0, -190), "trousers"),),
        "leftFoot": (box("left-shoe", (150, 260, 80), (0, 50, -40), "shoes"),),
        "rightUpperLeg": (box("right-thigh", (150, 160, 400), (0, 0, -200), "trousers"),),
        "rightLowerLeg": (box("right-shin", (140, 150, 380), (0, 0, -190), "trousers"),),
        "rightFoot": (box("right-shoe", (150, 260, 80), (0, 50, -40), "shoes"),),
        "leftUpperArm": (box("left-upper-arm", (260, 130, 130), (-130, 0, 0), "shirt"),),
        "leftLowerArm": (box("left-forearm", (240, 120, 120), (-120, 0, 0), "skin"),),
        "leftHand": (box("left-hand", (110, 110, 110), (-55, 0, 0), "skin"),),
        "rightUpperArm": (box("right-upper-arm", (260, 130, 130), (130, 0, 0), "shirt"),),
        "rightLowerArm": (box("right-forearm", (240, 120, 120), (120, 0, 0), "skin"),),
        "rightHand": (box("right-hand", (110, 110, 110), (55, 0, 0), "skin"),),
    }
    return tuple(Node(f"bone:{bone}", at, parts.get(bone, ())) for bone, at in _JOINTS.items())


_TRAVELLER: Final = {
    "skin": "#e0b58a",
    "hair": "#5b3a29",
    "shirt": "#3e8e7e",
    "trousers": "#3b4a8a",
    "shoes": "#3a2a20",
    "eyes": "#2b2b2b",
}
_KNIGHT: Final = {
    "skin": "#a9b4bf",
    "hair": "#8d99a6",
    "shirt": "#8d99a6",
    "trousers": "#6f7b88",
    "shoes": "#4a525c",
    "eyes": "#1f2428",
}


def _sword() -> tuple[Node, ...]:
    return (
        Node(
            "sword",
            (0, 0, 0),
            (
                Part("pommel", "box", (50, 40, 40), (0, 0, 20), "#b08d57"),
                Part("grip", "box", (30, 30, 140), (0, 0, 110), "#6b4a2b"),
                Part("guard", "box", (120, 40, 30), (0, 0, 195), "#b08d57"),
                Part("blade", "box", (50, 10, 790), (0, 0, 605), "#d9dee3"),
            ),
        ),
    )


def _lantern() -> tuple[Node, ...]:
    return (
        Node(
            "lantern",
            (0, 0, 0),
            (
                Part("base", "box", (180, 180, 30), (0, 0, 15), "#3a2a20"),
                Part("glass", "box", (150, 150, 200), (0, 0, 130), "#fff2b0", glow="#ffd76a"),
                Part("cap", "box", (180, 180, 30), (0, 0, 245), "#3a2a20"),
                Part("ring", "box", (50, 8, 40), (0, 0, 280), "#3a2a20"),
            ),
        ),
    )


def _well() -> tuple[Node, ...]:
    return (
        Node(
            "well",
            (0, 0, 0),
            (
                Part("wall", "cylinder", (1400, 1400, 700), (0, 0, 350), "#9a8f84"),
                Part("water", "cylinder", (1200, 1200, 20), (0, 0, 600), "#2f5d7c"),
                Part("left-post", "box", (100, 100, 1500), (-650, 0, 1050), "#7a5a3c"),
                Part("right-post", "box", (100, 100, 1500), (650, 0, 1050), "#7a5a3c"),
                Part("crossbar", "box", (1400, 80, 80), (0, 0, 1650), "#7a5a3c"),
                Part("roof", "box", (1600, 1000, 100), (0, 0, 2150), "#a0522d"),
            ),
        ),
    )


def _gate() -> tuple[Node, ...]:
    return (
        Node(
            "gate",
            (0, 0, 0),
            (
                Part("left-post", "box", (300, 400, 3000), (-1350, 0, 1500), "#7a5a3c"),
                Part("right-post", "box", (300, 400, 3000), (1350, 0, 1500), "#7a5a3c"),
                Part("lintel", "box", (3000, 400, 300), (0, 0, 2850), "#5c4129"),
            ),
        ),
    )


#: Every look this repository authors, by look key, with what writes its container.
AUTHORED_LOOKS: Final = MappingProxyType(
    {
        "blocky-traveller": lambda: _blocky(_TRAVELLER),
        "blocky-knight": lambda: _blocky(_KNIGHT),
        "primitive-sword": _sword,
        "primitive-lantern": _lantern,
        "primitive-well": _well,
        "primitive-gate": _gate,
    }
)


def nodes_of(look: str) -> tuple[Node, ...]:
    return AUTHORED_LOOKS[look]()


@cache
def container_of(look: str) -> bytes:
    """The container an authored look draws: the same bytes on every machine."""
    return write_container(nodes_of(look))

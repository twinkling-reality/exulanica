"""The arrangements the corpus photographs: three places, and the objects that travel between them.

Two kinds of thing live here and the distinction is the whole point of the corpus.

*   A **place** is a fixed arrangement that does not move between visits. Photographing it twice,
    months apart, is what gives scene grouping two clusters to separate and continuity something
    to recognise.
*   A **subject** is a small object that appears in more than one place and in more than one
    visit. It is what an identity path has to link across captures, and it is deliberately not a
    person: `docs/privacy-consent-threat-model.md` section 10 leaves the biometric question to a
    human, and a synthetic corpus that shipped synthetic faces would prejudge it by supplying the
    training input for the very thing that has not been decided.

**Every solid is convex and no two interpenetrate.** That is what makes the painter's algorithm
in `render.py` exact rather than approximate, and it is a property of the arrangements below
rather than of the renderer. Adding a solid that intersects another one changes the correctness
of the renderer, so it is recorded in both files.

Colours are muted and slightly desaturated on purpose. A saturated primary reads as a rendering,
and while nothing here pretends to be a photograph, a corpus whose every frame screams "computer
graphics" would exercise the vision stage on input unlike anything the product will ever see.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from exulanica.corpus.render import Face, Vec3

__all__ = [
    "PLACES",
    "SUBJECTS",
    "SUBJECT_BUILDERS",
    "Place",
    "box",
    "prism",
]


def _rotate_z(point: Vec3, radians: float, about: Vec3) -> Vec3:
    cosine, sine = math.cos(radians), math.sin(radians)
    x, y, z = point[0] - about[0], point[1] - about[1], point[2]
    return (about[0] + x * cosine - y * sine, about[1] + x * sine + y * cosine, z)


def box(
    centre: Vec3,
    size: Vec3,
    colour: tuple[int, int, int],
    *,
    yaw_degrees: float = 0.0,
) -> list[Face]:
    """An axis-aligned box, optionally spun about its own vertical axis.

    The six faces are wound counter-clockwise seen from outside, which is what backface culling
    reads. Getting that right once here is why no caller of this module ever thinks about
    winding.
    """
    half = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
    corners = {
        (sx, sy, sz): (centre[0] + sx * half[0], centre[1] + sy * half[1], centre[2] + sz * half[2])
        for sx in (-1, 1)
        for sy in (-1, 1)
        for sz in (-1, 1)
    }
    radians = math.radians(yaw_degrees)
    if radians:
        corners = {key: _rotate_z(value, radians, centre) for key, value in corners.items()}

    def quad(*signs: tuple[int, int, int]) -> Face:
        return Face(tuple(corners[sign] for sign in signs), colour)

    return [
        quad((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),      # top, +Z
        quad((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),  # bottom, -Z
        quad((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),  # -Y
        quad((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)),      # +Y
        quad((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),      # +X
        quad((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),  # -X
    ]


def prism(
    centre: Vec3,
    radius: float,
    height: float,
    sides: int,
    colour: tuple[int, int, int],
    *,
    yaw_degrees: float = 0.0,
) -> list[Face]:
    """A regular n-gon prism standing on its base. Convex for every n >= 3.

    A prism rather than a sphere because a sphere is not convex under any tractable
    approximation that also stays cheap, and the corpus needs convexity for the depth sort to be
    exact. Twelve sides reads as round at the sizes used here.
    """
    if sides < 3:
        raise ValueError("a prism needs at least three sides")
    base_z = centre[2] - height / 2.0
    top_z = centre[2] + height / 2.0
    offset = math.radians(yaw_degrees)
    ring = [
        (
            centre[0] + radius * math.cos(offset + 2.0 * math.pi * index / sides),
            centre[1] + radius * math.sin(offset + 2.0 * math.pi * index / sides),
        )
        for index in range(sides)
    ]
    faces = [
        Face(tuple((x, y, top_z) for x, y in ring), colour),
        Face(tuple((x, y, base_z) for x, y in reversed(ring)), colour),
    ]
    for index in range(sides):
        ax, ay = ring[index]
        bx, by = ring[(index + 1) % sides]
        side = ((ax, ay, base_z), (bx, by, base_z), (bx, by, top_z), (ax, ay, top_z))
        faces.append(Face(side, colour))
    return faces


def _satchel(base: Vec3, yaw: float) -> list[Face]:
    """A shoulder bag, resting on the surface at `base`.

    Every subject builder takes the point the object RESTS ON rather than its own centre, so a
    place can name a shelf height once and put any of the three objects on it. Objects of
    different heights sharing one centre would each be sunk or floating by their own half height,
    which is a small lie about geometry in a corpus whose whole purpose is that the geometry is
    consistent.
    """
    x, y, z = base
    body = box((x, y, z + 0.13), (0.34, 0.22, 0.26), (150, 58, 52), yaw_degrees=yaw)
    flap = box((x, y, z + 0.28), (0.36, 0.24, 0.04), (122, 44, 40), yaw_degrees=yaw)
    return body + flap


def _thermos(base: Vec3, yaw: float) -> list[Face]:
    x, y, z = base
    body = prism((x, y, z + 0.15), 0.055, 0.30, 12, (58, 132, 148), yaw_degrees=yaw)
    cap = prism((x, y, z + 0.325), 0.048, 0.05, 12, (36, 92, 106), yaw_degrees=yaw)
    return body + cap


def _lantern(base: Vec3, yaw: float) -> list[Face]:
    x, y, z = base
    body = prism((x, y, z + 0.09), 0.10, 0.18, 6, (196, 148, 62), yaw_degrees=yaw)
    handle = box((x, y, z + 0.195), (0.02, 0.16, 0.03), (108, 88, 44), yaw_degrees=yaw)
    return body + handle


#: The three travelling objects, keyed by what the manifest calls them. The builders are held in
#: a plain mapping rather than on a dataclass because a subject is data and its geometry is a
#: function, and conflating them would make the manifest carry code.
SUBJECT_BUILDERS = {
    "satchel": _satchel,
    "thermos": _thermos,
    "lantern": _lantern,
}

SUBJECTS: dict[str, str] = {
    "satchel": "a carmine shoulder bag with a darker flap",
    "thermos": "a slim teal vacuum flask with a darker cap",
    "lantern": "a squat amber six-sided lantern with a wire handle",
}

#: What a detector might reasonably CALL each subject, so the manifest's vocabulary and the
#: pipeline's can be joined at all.
#:
#: **This is the corpus's claim about words, not its ground truth about geometry.** The manifest
#: knows exactly which subject the generator placed in which frame, because it placed it. It
#: cannot know what a model will call a low-poly carmine box: "satchel", "red bag", "red cube",
#: "maroon box". Everything else in MANIFEST.json is a fact the generator produced; this is the
#: one entry that is a guess, and it is written down here, in a reviewed diff, rather than
#: buried in a scorer, for the same reason `exulanica/epistemics/vocabulary.py` exists.
#:
#: **What the mapping measures, which is not what it was added for.** It was added so M6 could be
#: scored against the corpus, and M6 turned out not to be a corpus metric at all: it filters on
#: confirmed entity ids and an entity exists only where a person confirmed one. The mapping is
#: what measures why a manifest-derived filter metric would not have been worth having anyway.
#: :func:`exulanica.evaluation.coverage.what_the_corpus_cannot_support` runs it on every evaluation
#: and reports, per subject, how much of the generator's own placement a detector recovered. That
#: is a disclosure and never a score: a low number is a fact about a vocabulary, and reporting it
#: as a filter defect is the "blocked" and "scored zero" conflation the whole report refuses.
#:
#: The appearance words are here because the shapes ARE boxes and prisms: a model looking at a
#: carmine box and saying "red box" is describing the frame correctly, and refusing to join that
#: to `satchel` would be scoring the model down for being right about pixels.
SUBJECT_LABELS: dict[str, tuple[str, ...]] = {
    "satchel": ("satchel", "shoulder bag", "bag", "red box", "red cube", "carmine box"),
    "thermos": ("thermos", "vacuum flask", "flask", "teal cylinder", "teal prism", "bottle"),
    "lantern": ("lantern", "amber prism", "hexagonal prism", "amber lantern", "gold cube"),
}


@dataclass(frozen=True, slots=True)
class Place:
    """A fixed arrangement, with where a camera can stand and where a subject can be put.

    `orbit_centre` and `orbit_radius` describe an arc the capture plan walks so that consecutive
    frames overlap. Overlap is the property reconstruction needs and the property a randomly
    scattered camera would not have.
    """

    key: str
    label: str
    indoors: bool
    faces: tuple[Face, ...]
    orbit_centre: Vec3
    orbit_radius: float
    eye_height: float
    subject_positions: tuple[Vec3, ...]
    sky_top: tuple[int, int, int]
    sky_bottom: tuple[int, int, int]
    light_direction: Vec3
    #: A weaker second direction, for the bounce that lights an interior ceiling. `None`
    #: outdoors, where the sky already does that job and a second light would flatten the
    #: shading that tells the shapes apart.
    fill_direction: Vec3 | None = None
    fill_weight: float = 0.0


def _courtyard() -> Place:
    ground = box((0.0, 0.0, -0.25), (26.0, 26.0, 0.5), (146, 140, 126))
    wall_north = box((0.0, 6.4, 1.1), (13.0, 0.5, 2.2), (178, 168, 150))
    wall_east = box((6.4, 0.0, 1.1), (0.5, 13.0, 2.2), (170, 160, 143))
    fountain_base = prism((0.0, 0.0, 0.28), 1.5, 0.56, 8, (158, 152, 140))
    fountain_stem = prism((0.0, 0.0, 0.86), 0.32, 0.60, 8, (140, 134, 122))
    planters = [
        face
        for index, offset in enumerate(((-3.6, 3.4), (3.6, 3.4), (-3.6, -3.4)))
        for face in box(
            (offset[0], offset[1], 0.3),
            (1.1, 1.1, 0.6),
            (122, 112, 96),
            yaw_degrees=index * 12.0,
        )
    ]
    hedges = [
        face
        for offset in ((-3.6, 3.4), (3.6, 3.4), (-3.6, -3.4))
        for face in box((offset[0], offset[1], 0.86), (0.9, 0.9, 0.52), (86, 108, 78))
    ]
    bench = box((0.0, -4.4, 0.44), (2.4, 0.5, 0.12), (132, 106, 74)) + [
        face
        for x in (-1.0, 1.0)
        for face in box((x, -4.4, 0.19), (0.14, 0.44, 0.38), (108, 86, 60))
    ]
    return Place(
        key="courtyard",
        label="a walled courtyard with a fountain",
        indoors=False,
        faces=tuple(
            ground
            + wall_north
            + wall_east
            + fountain_base
            + fountain_stem
            + planters
            + hedges
            + bench
        ),
        orbit_centre=(0.0, 0.0, 0.9),
        orbit_radius=5.2,
        eye_height=1.62,
        # The fountain rim, at radius 1.15 to 1.41 from its axis: outside the stem and well
        # inside the base, so a subject stands ON the rim rather than through it.
        subject_positions=((1.15, 0.55, 0.56), (-1.05, -0.85, 0.56), (0.60, 1.28, 0.56)),
        sky_top=(148, 172, 198),
        sky_bottom=(206, 210, 206),
        light_direction=(-0.42, 0.36, 0.83),
    )


def _harbour() -> Place:
    water = box((0.0, 9.0, -0.32), (40.0, 22.0, 0.4), (74, 96, 106))
    quay = box((0.0, -3.0, -0.15), (30.0, 14.0, 0.5), (134, 130, 122))
    edge = box((0.0, 3.9, 0.14), (30.0, 0.5, 0.28), (150, 146, 136))
    bollards = [
        face
        for x in (-4.2, -0.4, 3.4)
        for face in prism((x, 3.2, 0.42), 0.20, 0.84, 12, (78, 76, 74))
    ]
    crates = [
        face
        for index, spot in enumerate(((-6.2, 0.4, 0.45), (-6.2, 0.4, 1.35), (-5.0, 1.1, 0.45)))
        for face in box(spot, (0.9, 0.9, 0.9), (144, 118, 82), yaw_degrees=index * 9.0)
    ]
    mast = box((5.8, 1.6, 2.6), (0.16, 0.16, 5.2), (188, 184, 176))
    hull = box((5.8, 1.6, 0.24), (3.4, 1.2, 0.6), (162, 84, 70), yaw_degrees=6.0)
    return Place(
        key="harbour",
        label="a stone quay with bollards and a moored boat",
        indoors=False,
        faces=tuple(water + quay + edge + bollards + crates + mast + hull),
        orbit_centre=(0.0, 0.4, 0.9),
        orbit_radius=6.4,
        eye_height=1.58,
        # A bollard top and two spots on the quay, all within three metres of where the
        # camera orbits, so a subject is actually in frame rather than a speck at the back.
        subject_positions=((-0.4, 3.2, 0.84), (2.2, -1.2, 0.10), (-2.4, 1.2, 0.10)),
        sky_top=(126, 154, 186),
        sky_bottom=(198, 206, 210),
        light_direction=(0.55, 0.28, 0.79),
    )


def _kitchen() -> Place:
    """The one interior. Bigger than it needs to look, for a reason.

    The camera orbits inside this room, so the room's half width has to exceed the largest orbit
    radius by a comfortable margin or the camera ends up standing in a wall. It is 4.4 metres to
    each wall against a largest orbit radius of 2.7, which leaves the camera at least 1.3 metres
    of air on every frame.

    The table sits well off the orbit centre for the same class of reason: an object between the
    camera and the point it is looking at fills the near field on every frame that passes it, and
    a corpus of tabletops is not a corpus of a kitchen.
    """
    floor = box((0.0, 0.0, -0.1), (9.0, 9.0, 0.2), (150, 132, 112))
    ceiling = box((0.0, 0.0, 2.72), (9.0, 9.0, 0.2), (212, 208, 202))
    wall_far = box((0.0, 4.4, 1.31), (9.0, 0.2, 2.62), (198, 194, 186))
    wall_near = box((0.0, -4.4, 1.31), (9.0, 0.2, 2.62), (192, 188, 180))
    wall_left = box((-4.4, 0.0, 1.31), (0.2, 9.0, 2.62), (190, 186, 178))
    wall_right = box((4.4, 0.0, 1.31), (0.2, 9.0, 2.62), (190, 186, 178))
    # Set into the far wall's inner face rather than floating in front of it. Sharing a plane is
    # not interpenetration, and the brighter panel reads as daylight without a second light.
    window = box((0.0, 4.28, 1.62), (2.0, 0.04, 1.15), (228, 232, 230))
    counter = box((0.0, 3.85, 0.45), (5.2, 0.8, 0.9), (172, 164, 152))
    table_top = box((-0.4, -1.9, 0.74), (2.0, 1.1, 0.08), (152, 120, 80))
    legs = [
        face
        for x in (-1.27, 0.47)
        for y in (-2.38, -1.42)
        for face in box((x, y, 0.35), (0.09, 0.09, 0.7), (122, 96, 64))
    ]
    shelf = box((-4.24, 0.6, 1.72), (0.34, 2.4, 0.06), (160, 146, 124))
    stool = prism((1.9, -1.4, 0.26), 0.28, 0.52, 10, (134, 128, 118))
    return Place(
        key="kitchen",
        label="a kitchen with a window over the counter and a table under it",
        indoors=True,
        faces=tuple(
            floor
            + ceiling
            + wall_far
            + wall_near
            + wall_left
            + wall_right
            + window
            + counter
            + table_top
            + legs
            + shelf
            + stool
        ),
        orbit_centre=(0.0, 0.4, 1.25),
        orbit_radius=2.3,
        eye_height=1.56,
        # The table top, the shelf and the counter top. Three real surfaces at three heights,
        # which is what makes the resting-point convention in the subject builders worth having.
        subject_positions=((-0.4, -1.9, 0.78), (-4.24, 0.6, 1.75), (1.4, 3.85, 0.90)),
        # Indoors the gradient is the room's own light rather than a sky, and the light comes
        # from close to overhead, which is what a ceiling fitting does. A grazing light indoors
        # leaves every wall on ambient and the whole room reads as unlit.
        sky_top=(206, 202, 196),
        sky_bottom=(172, 164, 152),
        light_direction=(0.16, 0.42, 0.89),
        fill_direction=(0.0, -0.24, -0.97),
        fill_weight=0.34,
    )


PLACES: dict[str, Place] = {place.key: place for place in (_courtyard(), _harbour(), _kitchen())}

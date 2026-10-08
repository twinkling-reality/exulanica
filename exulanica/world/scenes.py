"""Scenes: things placed from where a person arrives, and the open model each being's mind is.

A scene (``exulanica.scene/v1``) is data a server lays into a saved world: each thing by its shipped
kind and version, placed from where a person arrives in the world (``right_mm`` to their right,
``forward_mm`` ahead and ``turn_microradians`` counterclockwise seen from above, where a turn of 0
faces the person arriving, as an object a person places in front of themselves turns to face them),
the open model each of its beings is given as a mind, the society engine it lives on, and
optionally the gate travellers come through with the mind they are given there. Placing from the
arrival lets one document dress any saved world of the ground it was laid out for; the world's own
arrival comes from its saved entry (:func:`scene_arrival`). Nothing here names a scene, a kind or a
thing.

Every version this repository ships is a file ``assets/catalogs/scenes/<scene>.v<N>.json`` and a
line in ``scenes.lock.json`` with its digest, the SHA-256 of its canonical JSON
(:func:`~exulanica.canonical.canonical_json`); a shipped version never changes, so a world dressed
with one names it by digest, and a changed scene is a new version and a new line. The demo's own
builder (``scripts/demo/build_scene.py``) reads these documents from outside, through the public
routes, with the same arithmetic; ``tests/test_scenes.py`` holds the two equal.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.documents import read_json
from exulanica.models.manifest import load_manifest
from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.things.origin import OriginRefused, read_origin
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.generated_worlds import GeneratedGround, GeneratedSite
from exulanica.world.objects import MAX_YAW_MICRORADIANS, Transform
from exulanica.world.placed_things import (
    PLACED_THING_ID_PATTERN,
    UNSCALED_MILLI,
    placeable_by_author,
)
from exulanica.world.society_engines import (
    RetiredSocietyEngine,
    UnknownSocietyEngine,
    creatable_engine,
)
from exulanica.world.starter import AuthoredStarterScene

__all__ = [
    "SCENES_DIRECTORY",
    "SCENES_LOCK",
    "SCENE_LOCK_PROFILE",
    "SCENE_PROFILE",
    "Scene",
    "SceneArrival",
    "SceneRefused",
    "places",
    "read_scene",
    "read_scene_lock",
    "scene_arrival",
    "shipped_scene",
    "shipped_scenes",
]

SCENE_PROFILE: Final = "exulanica.scene/v1"
SCENE_LOCK_PROFILE: Final = "exulanica.scene-lock/v1"
SCENES_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "assets/catalogs/scenes"
SCENES_LOCK: Final = SCENES_DIRECTORY / "scenes.lock.json"
#: The grounds a scene is laid out for, as a saved world's entry states its arrival: a starter's
#: spawn, a generated town's arrival point, or a site made from a world kind.
GROUNDS: Final = frozenset({"starter", "generated", "site"})
#: The most things one scene places, and the farthest it places one from the arrival.
THINGS_MAXIMUM: Final = 64
REACH_MM: Final = 1_000_000
_KEY = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
_THING_ID = re.compile(PLACED_THING_ID_PATTERN)
_TOP: Final = frozenset(
    {
        "profile",
        "scene",
        "version",
        "title",
        "summary",
        "words",
        "ground",
        "things",
        "minds",
        "engine",
        "origin",
    }
)
_OPTIONAL_TOP: Final = frozenset({"travellers"})
_NOTHING: Final[frozenset[str]] = frozenset()
_PLACE: Final = frozenset({"right_mm", "forward_mm", "turn_microradians"})
_LOCK_LINE: Final = frozenset({"scene", "version", "sha256"})


class SceneRefused(ValueError):
    """A scene this reader will not take, or one that does not fit the world it is laid into, by a
    code a caller can act on and the place in the document that failed."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _invalid(where: str, message: str) -> SceneRefused:
    return SceneRefused("invalid_scene", f"{where} {message}")


def _closed(
    where: str, value: object, keys: frozenset[str], optional: frozenset[str] = _NOTHING
) -> Mapping:
    if not isinstance(value, Mapping):
        raise _invalid(where, "is an object")
    unknown = set(value) - keys - optional
    missing = keys - set(value)
    if unknown or missing:
        raise _invalid(where, f"holds exactly {sorted(keys)} (and may hold {sorted(optional)})")
    return value


def _text(where: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= maximum:
        raise _invalid(where, f"is text of 1 to {maximum} characters")
    return value


def _int(where: str, value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise _invalid(where, f"is a whole number from {low} to {high}")
    return value


@dataclass(frozen=True, slots=True)
class Scene:
    """A checked scene: its key, version and digest, the ground it is laid out for and the
    document itself, which callers read by its fields."""

    scene: str
    version: int
    sha256: str
    ground: str
    document: Mapping[str, Any]

    def reference(self) -> dict[str, Any]:
        return {"scene": self.scene, "version": self.version, "sha256": self.sha256}


def _model(where: str, value: object) -> dict[str, str]:
    model = _closed(where, value, frozenset({"provider", "model_id"}))
    provider = _text(f"{where}.provider", model["provider"], 100)
    model_id = _text(f"{where}.model_id", model["model_id"], 200)
    manifest = load_manifest()
    if model_id not in manifest.models or manifest.spec(model_id).provider != provider:
        raise _invalid(where, "names a model the model manifest declares, by its provider")
    return {"provider": provider, "model_id": model_id}


def read_scene(
    document: object, *, kinds: Mapping[tuple[str, int], ThingKind] | None = None
) -> Scene:
    """``document`` as a scene, every field checked, or :class:`SceneRefused`: each thing once, of
    a shipped kind at a shipped version, placed within reach of the arrival; minds only for its own
    beings, by a decider their kind allows and a model the manifest declares; a travellers' gate
    that is one of its things and offers arrival; an engine the engine table states; an origin."""
    top = _closed("scene", document, _TOP, _OPTIONAL_TOP)
    if top["profile"] != SCENE_PROFILE:
        raise _invalid("profile", f"is {SCENE_PROFILE}")
    key = _text("scene", top["scene"], 64)
    if _KEY.fullmatch(key) is None:
        raise _invalid("scene", "is lowercase letters, digits and hyphens")
    version = _int("version", top["version"], 1, 10_000)
    _text("title", top["title"], 200)
    _text("summary", top["summary"], 1000)
    _text("words", top["words"], 1000)
    ground = _closed("ground", top["ground"], frozenset({"kind", "frame"}))
    if ground["kind"] not in GROUNDS:
        raise _invalid("ground.kind", f"is one of {sorted(GROUNDS)}")
    _text("ground.frame", ground["frame"], 1000)
    library = shipped_thing_kinds() if kinds is None else kinds
    things = top["things"]
    if not isinstance(things, list) or not 0 < len(things) <= THINGS_MAXIMUM:
        raise _invalid("things", f"is a list of 1 to {THINGS_MAXIMUM} things")
    placed: dict[str, ThingKind] = {}
    for index, raw in enumerate(things):
        at = f"things[{index}]"
        thing = _closed(at, raw, frozenset({"thing_id", "kind", "place"}))
        thing_id = _text(f"{at}.thing_id", thing["thing_id"], 200)
        if _THING_ID.fullmatch(thing_id) is None:
            raise _invalid(f"{at}.thing_id", "is a placed thing's id (lowercase, digits and :._-)")
        if thing_id in placed:
            raise _invalid(f"{at}.thing_id", "names each thing once")
        reference = _closed(f"{at}.kind", thing["kind"], frozenset({"kind", "version"}))
        if type(reference["kind"]) is not str or type(reference["version"]) is not int:
            raise _invalid(f"{at}.kind", "names a kind by its key and version number")
        found = library.get((reference["kind"], reference["version"]))
        if found is None:
            raise SceneRefused(
                "scene_kind_unshipped",
                f"{at}.kind names no shipped kind: {reference['kind']} {reference['version']}",
            )
        try:
            placeable_by_author(found)
        except InvalidThingPlacement as exc:
            raise SceneRefused("scene_kind_not_placeable", f"{at}.kind: {exc}") from exc
        place = _closed(f"{at}.place", thing["place"], _PLACE)
        _int(f"{at}.place.right_mm", place["right_mm"], -REACH_MM, REACH_MM)
        _int(f"{at}.place.forward_mm", place["forward_mm"], -REACH_MM, REACH_MM)
        _int(f"{at}.place.turn_microradians", place["turn_microradians"], 0, MAX_YAW_MICRORADIANS)
        placed[thing_id] = found
    minds = top["minds"]
    if not isinstance(minds, list):
        raise _invalid("minds", "is a list")
    minded: set[str] = set()
    for index, raw in enumerate(minds):
        at = f"minds[{index}]"
        mind = _closed(at, raw, frozenset({"thing_id", "decider"}))
        kind = placed.get(mind["thing_id"]) if type(mind["thing_id"]) is str else None
        if kind is None or mind["thing_id"] in minded:
            raise _invalid(f"{at}.thing_id", "names one of the scene's things, once")
        minded.add(mind["thing_id"])
        decider = mind["decider"]
        if not isinstance(decider, Mapping) or decider.get("kind") not in ("model", "routine"):
            raise _invalid(f"{at}.decider", "is the routine or a model")
        allowed = (kind.document.get("deciders") or {}).get("allowed", ())
        if kind.klass != "being" or decider["kind"] not in allowed:
            raise _invalid(f"{at}.decider", f"is one a {kind.kind} may be decided for by")
        if decider["kind"] == "model":
            _model(
                f"{at}.decider",
                {k: v for k, v in decider.items() if k != "kind"},
            )
        elif set(decider) != {"kind"}:
            raise _invalid(f"{at}.decider", "names nothing but the routine")
    if "travellers" in top:
        travellers = _closed("travellers", top["travellers"], frozenset({"gate", "model"}))
        gate = placed.get(travellers["gate"]) if type(travellers["gate"]) is str else None
        offers = () if gate is None else [offer["key"] for offer in gate.document["offers"]]
        if "arrive_through" not in offers:
            raise _invalid("travellers.gate", "names one of the scene's things that offers arrival")
        if travellers["model"] is not None:
            _model("travellers.model", travellers["model"])
    try:
        engine = creatable_engine(top["engine"])
    except (UnknownSocietyEngine, RetiredSocietyEngine) as exc:
        raise _invalid(
            "engine", "is a society engine the engine table states and still makes"
        ) from exc
    if minds and engine.state_family != "things":
        # Only a society of things seats the beings a scene places, so only it can give them minds.
        raise _invalid("engine", "is a society of things when the scene gives its beings minds")
    try:
        read_origin(top["origin"])
    except OriginRefused as exc:
        raise _invalid("origin", f"is an origin record ({exc})") from exc
    return Scene(
        scene=key,
        version=version,
        sha256=sha256_of_canonical(dict(top)).hex(),
        ground=ground["kind"],
        document=top,
    )


def read_scene_lock(path: Path = SCENES_LOCK) -> dict[tuple[str, int], str]:
    """The lock's digest for each shipped scene version, or :class:`SceneRefused`."""
    lock = _closed(path.name, read_json(path), frozenset({"profile", "reason", "scenes"}))
    if lock["profile"] != SCENE_LOCK_PROFILE:
        raise _invalid(f"{path.name}.profile", f"is {SCENE_LOCK_PROFILE}")
    locked: dict[tuple[str, int], str] = {}
    for index, raw in enumerate(lock["scenes"]):
        entry = _closed(f"{path.name}.scenes[{index}]", raw, _LOCK_LINE)
        key = (entry["scene"], entry["version"])
        if key in locked:
            raise _invalid(f"{path.name}.scenes[{index}]", "names each scene version once")
        locked[key] = entry["sha256"]
    return locked


def shipped_scenes(
    directory: Path = SCENES_DIRECTORY, *, lock: Path = SCENES_LOCK
) -> dict[tuple[str, int], Scene]:
    """Every scene this repository ships, by key and version, each read and checked; a file named
    for another scene or version than it states is refused, and so is one the lock does not name
    at its digest, or a version the lock names with no file."""
    found: dict[tuple[str, int], Scene] = {}
    for path in sorted(directory.glob("*.v*.json")):
        scene = read_scene(read_json(path))
        if path.name != f"{scene.scene}.v{scene.version}.json":
            raise _invalid(path.name, "names the scene and version it states")
        found[(scene.scene, scene.version)] = scene
    locked = read_scene_lock(lock)
    for key, scene in found.items():
        if locked.get(key) != scene.sha256:
            raise SceneRefused(
                "scene_not_locked",
                f"{scene.scene}.v{scene.version}.json is not the document {lock.name} locks",
            )
    for key, version in sorted(set(locked) - set(found)):
        raise SceneRefused("scene_not_locked", f"{lock.name} names {key} {version}, with no file")
    return found


def shipped_scene(scene: str, version: int, sha256: str) -> Scene:
    """The shipped scene a reference names, at exactly its digest, or :class:`SceneRefused`."""
    found = shipped_scenes().get((scene, version))
    if found is None or found.sha256 != sha256:
        raise SceneRefused(
            "scene_unshipped", f"no scene {scene} version {version} is shipped at that digest"
        )
    return found


@dataclass(frozen=True, slots=True)
class SceneArrival:
    """Where a person arrives in a world's region and the way they face, in the region's frame:
    east, height and south in millimetres, and a facing vector east then south."""

    ground: str
    region_id: str
    at_mm: tuple[int, int, int]
    facing: tuple[float, float]

    def pose(self, place: Mapping[str, int]) -> Transform:
        """A place stated from this arrival, as a pose in the region's frame, at its kind's own
        size. A placed object's own z axis points south at yaw 0 and its yaw turns counterclockwise
        seen from above, as the renderer turns every placed object, so at a turn of 0 the thing
        faces the person arriving."""
        east, south = self.facing
        length = math.hypot(east, south)
        forward = (east / length, south / length)
        right = (-forward[1], forward[0])
        x = self.at_mm[0] + place["right_mm"] * right[0] + place["forward_mm"] * forward[0]
        z = self.at_mm[2] + place["right_mm"] * right[1] + place["forward_mm"] * forward[1]
        facing = round(math.atan2(-forward[0], -forward[1]) * 1_000_000)
        yaw = (place["turn_microradians"] + facing) % (MAX_YAW_MICRORADIANS + 1)
        return Transform(round(x), self.at_mm[1], round(z), yaw, UNSCALED_MILLI)


def scene_arrival(entry: Any) -> SceneArrival:
    """The arrival a saved world's entry states: a generated town's or a site's arrival point and
    facing, or a starter's spawn; :class:`SceneRefused` for a world that states none."""
    ground = getattr(entry, "generated_ground", None)
    if isinstance(ground, GeneratedGround):
        return SceneArrival(
            "generated", ground.region_id, tuple(ground.arrival_mm), tuple(ground.arrival_facing_mm)
        )
    site = getattr(entry, "generated_site", None)
    if isinstance(site, GeneratedSite):
        return SceneArrival(
            "site", site.region_id, tuple(site.arrival_mm), tuple(site.arrival_facing_mm)
        )
    starter = getattr(entry, "authored_scene", None)
    if isinstance(starter, AuthoredStarterScene):
        spawn = starter.region.spawn
        theta = spawn.yaw_microradians / 1_000_000
        return SceneArrival(
            "starter",
            starter.region.region_id,
            (spawn.x_mm, spawn.y_mm, spawn.z_mm),
            (-math.sin(theta), -math.cos(theta)),
        )
    raise SceneRefused(
        "scene_world_has_no_arrival", "the saved world states no arrival to place from"
    )


def places(
    scene: Scene, arrival: SceneArrival
) -> Sequence[tuple[str, Mapping[str, Any], Transform]]:
    """Each of the scene's things with its pose from ``arrival``, in the scene's order, or
    :class:`SceneRefused` when the scene is laid out for another ground than the world's."""
    if scene.ground != arrival.ground:
        raise SceneRefused(
            "scene_ground_mismatch",
            f"the scene is laid out for a {scene.ground} world, not a {arrival.ground} one",
        )
    return [
        (thing["thing_id"], thing["kind"], arrival.pose(thing["place"]))
        for thing in scene.document["things"]
    ]

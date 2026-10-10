"""A world's setting: the hour and sky, the colours it restates, what lies on its roofs and ground
and the ground beyond it, stated once for one world and drawn over the look the world wears.

A style pack (:mod:`exulanica.world.style_packs`) is shared and says how a world is drawn. A
setting (``exulanica.world-setting/v1``) is one world's own: changes to one of its pack's light
presets, the colour some look roles are drawn in, the colour of their upward faces, swatches of the
pack restated, and the ground beyond the world. Like a pack it never says where anything is.

**Nothing of a person.** A world's appearance versions are history no erasure rewrites, and a
setting is stored on one. So a setting holds whole numbers, colours and identifiers only: catalog
keys, look roles, swatch keys and, when a model drafted it, that call's model id, prompt version
and execution id. It never holds a person's words or a digest of them; the reader refuses any
other key and any value that is not shaped as an identifier.

**Checked against the pack it is drawn over.** A setting is read for its shape
(:func:`read_setting`) and then applied to its pack with the pack's base chain resolved
(:func:`apply_setting`). Applying it is the check: the light preset it changes is read again by
the pack reader's own rule for a preset, so a setting can state no light a pack could not; a
swatch, a preset or a surface it names must be the pack's; and what it draws is held to two
legibility rules, a person in the open lit enough to be seen and a town's ground surfaces still
told apart. What a setting may change in a preset, the rules' figures and the bounds are data
(``assets/style-packs/settings/setting-rules.v1.json``), read by this reader and the browser's
(``web/packages/atlas-core/src/world-setting.ts``); the shared case file
``assets/style-packs/settings/setting-cases.v1.json`` holds both to the same verdict on every case:
the same refusal by reason and path, or the same digest of the setting and of the pack as drawn.

**Named parts.** ``assets/style-packs/settings/setting-parts.v1.json`` lists parts a person or a
model may choose by name, one an axis (a sky, a ground, a cover), each stated for any pack.
:func:`compose_setting` turns the chosen parts into the exact setting for one pack: a part's
swatch the pack does not have is left out, its colour for a family's upward faces becomes one
entry for each surface of that family the pack dresses, and its light is the first of its
alternatives whose preset the pack states. The setting stores the figures, not the names, so a
later version of the parts never changes a world.

INTEGERS ONLY, as a pack: a setting's identity is the SHA-256 of its canonical bytes.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.world.style_packs import (
    _KEY,
    StylePackContext,
    StylePackRefused,
    _integer,
    _light_preset,
    _list,
    _literal,
    _nullable,
    _object,
    _one_of,
    _Optional,
    _pattern,
    _record,
    _srgb8,
    _text,
    canonical_json,
    split_look_role,
)

__all__ = [
    "CHAIN_MAXIMUM",
    "PARTS_PROFILE",
    "PROFILE",
    "RULES_PROFILE",
    "SETTINGS_DIRECTORY",
    "AppliedSetting",
    "ResolvedPack",
    "SettingParts",
    "SettingRefused",
    "SettingRules",
    "applied_sha256",
    "apply_setting",
    "bound_setting",
    "compose_setting",
    "load_setting_parts",
    "load_setting_rules",
    "read_setting",
    "resolve_chain",
    "setting_parts",
    "setting_rules",
    "setting_sha256",
    "settings_listing",
]

PROFILE: Final = "exulanica.world-setting/v1"
RULES_PROFILE: Final = "exulanica.world-setting-rules/v1"
PARTS_PROFILE: Final = "exulanica.world-setting-parts/v1"
#: The profile of the parts as ``GET /world/style-packs`` lists them.
LISTING_PROFILE: Final = "exulanica.world-setting-part-list/v1"
#: The most manifests a pack resolves through, itself and its bases, as the browser's
#: ``resolveStylePack`` holds.
CHAIN_MAXIMUM: Final = 4
SETTINGS_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "style-packs", "settings")
)
#: A setting is authored (a person chose it, or its named parts) or drafted by a model.
ORIGINS: Final = ("authored", "drafted")
#: The swatch keys a setting adds for the roles and upward faces it colours. A pack that already
#: states a key with one of these prefixes cannot take such a setting.
SURFACE_SWATCH: Final = "setting_surface_"
UP_SWATCH: Final = "setting_up_"
#: A swatch a setting adds: matt, as a pack's painted surfaces are.
_ROUGHNESS_PERMILLE: Final = 900
#: What a drafted setting says of the call that drafted it: identifiers, each of a shape that holds
#: no sentence. A world's appearance is history no erasure rewrites, so a setting states nothing of
#: a person: not their words and not a digest of them. An execution id is a UUID as the host writes
#: one, and none of the three may be 64 hexadecimal characters, the shape of a SHA-256.
_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_PROMPT_VERSION: Final = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
_EXECUTION_ID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DIGEST_SHAPED: Final = re.compile(r"[0-9a-f]{64}")
_IDENTIFIERS: Final = ("model_id", "prompt_version", "execution_id")


class SettingRefused(ValueError):
    """A setting refused by name: the reason, and the path of the first fault."""

    def __init__(self, reason: str, path: str, detail: str) -> None:
        self.reason = reason
        self.path = path
        super().__init__(f"{path or 'setting'}: {detail}")


def _fail(reason: str, path: str, detail: str) -> Any:
    raise SettingRefused(reason, path, detail)


@dataclass(frozen=True, slots=True)
class SettingRules:
    """What a setting may change and what it is held to, as the rules file states them."""

    #: The values of a light preset a setting may state, each a dotted path replaced whole.
    light_changes: tuple[str, ...]
    #: The least light a person in the open stands in (:func:`open_light`).
    open_light_minimum: int
    #: Pairs of look roles whose colours must stay apart, and by how much, in parts per thousand.
    ground_pairs: tuple[tuple[str, str], ...]
    ground_contrast_minimum_permille: int
    #: The named parts a setting may say it was composed from: each axis in order, and its parts.
    #: A setting's ``parts`` holds no other name, so it holds no word of a caller's own.
    part_names: Mapping[str, tuple[str, ...]]
    #: The most entries each part of a setting holds.
    maximum_parts: int
    maximum_surfaces: int
    maximum_up: int
    maximum_swatches: int
    #: ``assets/colour/srgb8-linear16.v1.json``: every sRGB byte's linear value times 65535.
    linear: tuple[int, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class ResolvedPack:
    """A pack with its base chain applied, as much of it as a setting reads and changes."""

    light: Mapping[str, Any]
    edge: Mapping[str, Any] | None
    swatches: Mapping[str, Mapping[str, Any]]
    surfaces: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class AppliedSetting:
    """A pack as a world with a setting is drawn: the pack's own where the setting is silent."""

    pack: ResolvedPack
    #: The preset the world is drawn in: the setting's, or the pack's default.
    preset: Mapping[str, Any]


def resolve_chain(chain: Sequence[Mapping[str, Any]]) -> ResolvedPack:
    """Apply a pack's base chain, the pack first and its furthest base last, as the browser's
    ``resolveStylePack`` does: a swatch, a surface or a light a nearer manifest states replaces the
    base's, and what it leaves out is the base's."""
    if not 1 <= len(chain) <= CHAIN_MAXIMUM:
        raise StylePackRefused("reference", "base", "a pack resolves through one to four manifests")
    swatches: dict[str, Mapping[str, Any]] = {}
    surfaces: dict[str, Mapping[str, Any]] = {}
    light: Mapping[str, Any] | None = None
    edge: Mapping[str, Any] | None = None
    for manifest in reversed(chain):
        for swatch in manifest["palette"]["swatches"]:
            swatches[swatch["key"]] = swatch
        surfaces.update(manifest["surfaces"])
        if manifest["light"] is not None:
            light = manifest["light"]
        if manifest["base"] is None or manifest["edge"] is not None:
            edge = manifest["edge"]
    if light is None:
        raise StylePackRefused("reference", "light", "no manifest of the chain states a light")
    return ResolvedPack(light=light, edge=edge, swatches=swatches, surfaces=surfaces)


def _rule_key(key: str, path: str) -> None:
    if _KEY.fullmatch(key) is None:
        _fail("shape", path, "must be a key")


def _role_key(key: str, path: str) -> None:
    split_look_role(key, path)


def _provenance(value: Any, path: str) -> dict[str, Any]:
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind == "authored":
        return _object(value, path, {"kind": _literal("authored")})
    if kind == "drafted":
        drafted = _object(
            value,
            path,
            {
                "kind": _literal("drafted"),
                "model_id": _pattern(_MODEL_ID, "a model id"),
                "prompt_version": _pattern(_PROMPT_VERSION, "a prompt version"),
                "execution_id": _pattern(_EXECUTION_ID, "an execution id"),
            },
        )
        for name in _IDENTIFIERS:
            if _DIGEST_SHAPED.fullmatch(drafted[name]) is not None:
                _fail("shape", f"{path}.{name}", "must not have the shape of a digest")
        return drafted
    return _fail("range", f"{path}.kind", f"must be one of {', '.join(ORIGINS)}")


def _colour(value: Any, path: str) -> dict[str, Any]:
    return _object(
        value, path, {"srgb8": _srgb8, "emission_permille": _Optional(_integer(0, 1000))}
    )


def _restated(value: Any, path: str) -> dict[str, Any]:
    swatch = _object(
        value,
        path,
        {"srgb8": _Optional(_srgb8), "emission_permille": _Optional(_integer(0, 1000))},
    )
    if not swatch:
        _fail("shape", path, "must state a colour or an emission")
    return swatch


def read_setting(value: Any, rules: SettingRules) -> dict[str, Any]:
    """Read a setting's shape, or refuse it with the first rule it breaks, by reason and path.

    What it names in a pack is checked when it is applied (:func:`apply_setting`)."""

    def change_key(key: str, path: str) -> None:
        if key not in rules.light_changes:
            _fail("reference", path, "is not a value of a light preset a setting may change")

    def anything(item: Any, _path: str) -> Any:
        return item

    try:
        setting = _object(
            value,
            "",
            {
                "profile": _literal(PROFILE),
                "origin": _one_of(ORIGINS),
                "provenance": _provenance,
                "parts": _list(
                    lambda v, p: _object(
                        v, p, {"axis": _pattern(_KEY, "a key"), "key": _pattern(_KEY, "a key")}
                    ),
                    0,
                    rules.maximum_parts,
                ),
                "light": _nullable(
                    lambda v, p: _object(
                        v,
                        p,
                        {
                            "from": _pattern(_KEY, "a preset key"),
                            "changes": _record(change_key, anything, len(rules.light_changes)),
                        },
                    )
                ),
                "surfaces": _record(_role_key, _colour, rules.maximum_surfaces),
                "up": _record(_role_key, _nullable(_srgb8), rules.maximum_up),
                "swatches": _record(_rule_key, _restated, rules.maximum_swatches),
                "edge": _nullable(lambda v, p: _object(v, p, {"ground": _srgb8})),
            },
        )
    except StylePackRefused as refused:
        raise SettingRefused(
            refused.reason, refused.path, str(refused).partition(": ")[2]
        ) from None
    if setting["provenance"]["kind"] != setting["origin"]:
        _fail("reference", "provenance.kind", "must equal the origin")
    axes: set[str] = set()
    for index, part in enumerate(setting["parts"]):
        if part["axis"] not in rules.part_names:
            _fail("reference", f"parts[{index}].axis", "is not an axis the rules list")
        if part["key"] not in rules.part_names[part["axis"]]:
            _fail("reference", f"parts[{index}].key", "is not a part the rules list for its axis")
        if part["axis"] in axes:
            _fail("duplicate", f"parts[{index}].axis", f"repeats {json.dumps(part['axis'])}")
        axes.add(part["axis"])
    return setting


def setting_sha256(setting: Mapping[str, Any]) -> str:
    """The setting's identity: the SHA-256 of its canonical bytes."""
    return hashlib.sha256(canonical_json(setting).encode("ascii")).hexdigest()


def _luma(colour: Sequence[int], rules: SettingRules) -> int:
    """Rec. 709 luminance of an sRGB colour, linear, 0 to 65535."""
    red, green, blue = (rules.linear[channel] for channel in colour)
    return (2126 * red + 7152 * green + 722 * blue) // 10000


def _sine_permille(millidegrees: int) -> int:
    """The sine of an angle from 0 to 180 degrees, per mille, by Bhaskara's rational form in whole
    numbers, so both readers reach the same figure: within two per mille of the sine."""
    product = millidegrees * (180_000 - millidegrees)
    return 4000 * product // (40_500_000_000 - product)


def open_light(preset: Mapping[str, Any], rules: SettingRules) -> int:
    """How much light a person standing in the open is drawn in under ``preset``: the sun on level
    ground plus the sky's image light, through the exposure. A whole number with no unit of its
    own, compared only with the rules' floor; it is a guard against a setting nobody can see in,
    not a model of the renderer."""
    sun = preset["sun"]
    sky = preset["sky"]
    direct = (
        sun["intensity_permille"]
        * _luma(sun["colour"], rules)
        * _sine_permille(sun["elevation_mdeg"])
        // 1_000_000
    )
    above = (_luma(sky["zenith"], rules) + _luma(sky["horizon"], rules)) // 2
    ambient = (
        preset["environment"]["intensity_permille"] * sky["intensity_permille"] * above // 1_000_000
    )
    return int(preset["exposure_permille"] * (direct + ambient) // 1000)


def _role_colour(pack: ResolvedPack, role: str) -> Sequence[int] | None:
    """The colour a town's surface of ``role`` is drawn in: its leaf's swatch, else its family's
    default's; None when the pack draws it from a texture set or does not dress it."""
    family = role.partition(".")[0]
    for name in (role, f"{family}.default"):
        surface = pack.surfaces.get(name)
        if surface is not None:
            swatch = pack.swatches.get(surface["swatch"]) if "swatch" in surface else None
            return None if swatch is None else swatch["srgb8"]
    return None


def contrast_permille(first: Sequence[int], second: Sequence[int], rules: SettingRules) -> int:
    """The lighter colour's luminance over the darker's, each raised by a twentieth of white as the
    WCAG contrast ratio raises them, in parts per thousand: 1000 for two colours equally light."""
    one, other = _luma(first, rules), _luma(second, rules)
    return 1000 * (max(one, other) + 3277) // (min(one, other) + 3277)


def apply_setting(
    pack: ResolvedPack, setting: Mapping[str, Any], context: StylePackContext, rules: SettingRules
) -> AppliedSetting:
    """``pack`` as a world with ``setting`` is drawn, or the first rule the setting breaks.

    ``setting`` is one :func:`read_setting` returned. In order: its swatches, the roles it colours,
    their upward faces, the ground beyond, its light, then the two legibility rules over what it
    changed: a pair of colours the setting left as the look has them is the look's own."""
    swatches: dict[str, Mapping[str, Any]] = dict(pack.swatches)
    surfaces: dict[str, Mapping[str, Any]] = dict(pack.surfaces)
    for part, prefix in (("surfaces", SURFACE_SWATCH), ("up", UP_SWATCH)):
        taken = sorted(key for key in swatches if key.startswith(prefix))
        if setting[part] and taken:
            _fail(
                "duplicate",
                part,
                f"the look states a swatch {json.dumps(taken[0])}, a key a setting's own take",
            )
    for key, stated in sorted(setting["swatches"].items()):
        if key not in pack.swatches:
            _fail("reference", f"swatches.{key}", "names no swatch of the look")
        swatches[key] = {**pack.swatches[key], **stated}
    for index, (role, colour) in enumerate(sorted(setting["surfaces"].items())):
        family = context.families.get(role.partition(".")[0])
        if family is None:
            _fail("reference", f"surfaces.{role}", "names no look family")
        elif family.dressing not in ("surface", "both"):
            _fail("reference", f"surfaces.{role}", "names a family no surface dresses")
        key = f"{SURFACE_SWATCH}{index}"
        swatches[key] = {
            "key": key,
            "srgb8": colour["srgb8"],
            "roughness_permille": _ROUGHNESS_PERMILLE,
            "metalness_permille": 0,
            "emission_permille": colour.get("emission_permille", 0),
        }
        held = surfaces.get(role)
        surfaces[role] = {"swatch": key, "up": None if held is None else held["up"]}
    for index, (role, colour) in enumerate(sorted(setting["up"].items())):
        held = surfaces.get(role)
        if held is None:
            _fail("reference", f"up.{role}", "names no surface the look or the setting dresses")
            continue
        if colour is None:
            surfaces[role] = {**held, "up": None}
            continue
        key = f"{UP_SWATCH}{index}"
        swatches[key] = {
            "key": key,
            "srgb8": colour,
            "roughness_permille": _ROUGHNESS_PERMILLE,
            "metalness_permille": 0,
            "emission_permille": 0,
        }
        surfaces[role] = {**held, "up": key}
    edge = pack.edge
    if setting["edge"] is not None:
        if edge is None:
            _fail("reference", "edge", "the look draws no ground beyond the world")
        else:
            edge = {**edge, "ground": setting["edge"]["ground"]}
    light = pack.light
    preset: Mapping[str, Any] = light["presets"][light["default_preset"]]
    stated = setting["light"]
    if stated is not None:
        if stated["from"] not in light["presets"]:
            _fail("reference", "light.from", "names no preset of the look")
        changed = copy.deepcopy(dict(light["presets"][stated["from"]]))
        for path, value in stated["changes"].items():
            *parents, leaf = path.split(".")
            holder = changed
            for parent in parents:
                holder = holder[parent]
            holder[leaf] = copy.deepcopy(value)
        try:
            preset = _light_preset(changed, "")
        except StylePackRefused as refused:
            raise SettingRefused(
                refused.reason,
                f"light.changes.{refused.path}",
                str(refused).partition(": ")[2],
            ) from None
        light = {
            "default_preset": stated["from"],
            "presets": {**light["presets"], stated["from"]: preset},
        }
        lit = open_light(preset, rules)
        if lit < rules.open_light_minimum:
            _fail(
                "legibility",
                "light",
                f"a person in the open stands in {lit} of light, below the least a setting may "
                f"leave, {rules.open_light_minimum}",
            )
    applied = ResolvedPack(light=light, edge=edge, swatches=swatches, surfaces=surfaces)
    if setting["surfaces"] or setting["swatches"]:
        for first, second in rules.ground_pairs:
            one, other = _role_colour(applied, first), _role_colour(applied, second)
            if one is None or other is None:
                continue
            if (one, other) == (_role_colour(pack, first), _role_colour(pack, second)):
                # The look's own colours, which the setting left as they are.
                continue
            apart = contrast_permille(one, other, rules)
            if apart < rules.ground_contrast_minimum_permille:
                _fail(
                    "legibility",
                    "surfaces",
                    f"{first} and {second} are {apart} per mille apart in lightness, nearer than "
                    f"the least a setting may leave, {rules.ground_contrast_minimum_permille}",
                )
    return AppliedSetting(pack=applied, preset=preset)


def applied_sha256(applied: AppliedSetting) -> str:
    """The SHA-256 of what a setting changes of a pack as it is drawn: the preset, the ground
    beyond, every swatch in key order and every surface. The browser's reader writes the same
    bytes, so one digest holds both to the same drawing."""
    drawn = {
        "edge": applied.pack.edge,
        "preset": applied.preset,
        "surfaces": applied.pack.surfaces,
        "swatches": [applied.pack.swatches[key] for key in sorted(applied.pack.swatches)],
    }
    return hashlib.sha256(canonical_json(drawn).encode("ascii")).hexdigest()


def load_setting_rules(directory: Path = SETTINGS_DIRECTORY) -> SettingRules:
    """The rules file, read strictly: a file that states anything else is refused."""
    text = directory.joinpath("setting-rules.v1.json").read_bytes()
    document = json.loads(text)
    whole = _integer(0, 2**31 - 1)
    words = _text(600)
    stated = _object(
        document,
        "",
        {
            "profile": _literal(RULES_PROFILE),
            "about": words,
            "light_changes": lambda v, p: _object(
                v, p, {"paths": _list(_text(80), 1, 64), "reason": words}
            ),
            "open_light": lambda v, p: _object(
                v, p, {"minimum": whole, "class": words, "reason": words, "source": words}
            ),
            "ground_contrast": lambda v, p: _object(
                v,
                p,
                {
                    "pairs": _list(_list(_text(80), 2, 2), 1, 16),
                    "minimum_permille": whole,
                    "class": words,
                    "reason": words,
                    "source": words,
                },
            ),
            "part_names": lambda v, p: _object(
                v,
                p,
                {
                    "names": _record(_rule_key, _list(_pattern(_KEY, "a key"), 1, 64), 16),
                    "class": words,
                    "reason": words,
                },
            ),
            "bounds": lambda v, p: _object(
                v,
                p,
                {
                    "parts": whole,
                    "surfaces": whole,
                    "up": whole,
                    "swatches": whole,
                    "class": words,
                    "reason": words,
                },
            ),
        },
    )
    table = json.loads(
        directory.parents[1].joinpath("colour", "srgb8-linear16.v1.json").read_text("utf-8")
    )
    return SettingRules(
        light_changes=tuple(stated["light_changes"]["paths"]),
        open_light_minimum=stated["open_light"]["minimum"],
        ground_pairs=tuple((a, b) for a, b in stated["ground_contrast"]["pairs"]),
        ground_contrast_minimum_permille=stated["ground_contrast"]["minimum_permille"],
        part_names={axis: tuple(keys) for axis, keys in stated["part_names"]["names"].items()},
        maximum_parts=stated["bounds"]["parts"],
        maximum_surfaces=stated["bounds"]["surfaces"],
        maximum_up=stated["bounds"]["up"],
        maximum_swatches=stated["bounds"]["swatches"],
        linear=tuple(table["values"]),
        sha256=hashlib.sha256(text).hexdigest(),
    )


@functools.cache
def setting_rules() -> SettingRules:
    """The committed rules, read once."""
    return load_setting_rules()


@dataclass(frozen=True, slots=True)
class SettingParts:
    """The named parts a person or a model chooses a setting from."""

    version: int
    sha256: str
    #: Each axis, in the order a setting's parts are stated and applied: its key and title.
    axes: tuple[tuple[str, str], ...]
    #: Every part by axis and key, as the file states it.
    parts: Mapping[tuple[str, str], Mapping[str, Any]]

    def listed(self) -> list[dict[str, str]]:
        """Every part as a chooser is shown it: its axis, key, title and description."""
        return [
            {
                "axis": axis,
                "key": key,
                "title": part["title"],
                "description": part["description"],
            }
            for (axis, key), part in self.parts.items()
        ]


def load_setting_parts(
    directory: Path = SETTINGS_DIRECTORY, rules: SettingRules | None = None
) -> SettingParts:
    """The parts file, read strictly."""
    rules = setting_rules() if rules is None else rules
    text = directory.joinpath("setting-parts.v1.json").read_bytes()
    key = _pattern(_KEY, "a key")
    words = _text(600)

    def change_key(name: str, path: str) -> None:
        if name not in rules.light_changes:
            raise StylePackRefused("reference", path, "is not a value a setting may change")

    def anything(item: Any, _path: str) -> Any:
        return item

    def alternative(value: Any, path: str) -> dict[str, Any]:
        return _object(
            value,
            path,
            {
                "from": _nullable(key),
                "changes": _record(change_key, anything, len(rules.light_changes)),
            },
        )

    def part(value: Any, path: str) -> dict[str, Any]:
        return _object(
            value,
            path,
            {
                "axis": key,
                "key": key,
                "title": _text(60),
                "description": _text(200),
                "reason": words,
                "light": _list(alternative, 0, 4),
                "surfaces": _record(_role_key, _colour, rules.maximum_surfaces),
                "up_families": _record(_rule_key, _srgb8, 16),
                "swatches": _record(_rule_key, _restated, rules.maximum_swatches),
                "edge": _nullable(_srgb8),
            },
        )

    stated = _object(
        json.loads(text),
        "",
        {
            "profile": _literal(PARTS_PROFILE),
            "version": _integer(1, 1_000_000),
            "about": words,
            "licence": lambda v, p: _object(
                v, p, {"id": _literal("CC0-1.0"), "origin": _literal("authored"), "by": _text(120)}
            ),
            "axes": _list(
                lambda v, p: _object(v, p, {"key": key, "title": _text(60)}),
                1,
                rules.maximum_parts,
            ),
            "parts": _list(part, 1, 256),
        },
    )
    axes = tuple((axis["key"], axis["title"]) for axis in stated["axes"])
    parts: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, one in enumerate(stated["parts"]):
        name = (one["axis"], one["key"])
        if one["axis"] not in dict(axes):
            raise StylePackRefused("reference", f"parts[{index}].axis", "names no axis")
        if name in parts:
            raise StylePackRefused("duplicate", f"parts[{index}].key", "repeats a part of its axis")
        parts[name] = one
    # The rules name every part a stored setting may state, and the two files never differ.
    named = {axis: tuple(key for one, key in parts if one == axis) for axis, _ in axes}
    if named != dict(rules.part_names) or list(named) != list(rules.part_names):
        raise StylePackRefused("reference", "parts", "are not the part names the rules list")
    return SettingParts(
        version=stated["version"],
        sha256=hashlib.sha256(text).hexdigest(),
        axes=axes,
        parts=parts,
    )


@functools.cache
def setting_parts() -> SettingParts:
    """The committed parts, read once."""
    return load_setting_parts()


def compose_setting(
    chosen: Mapping[str, str],
    pack: ResolvedPack,
    context: StylePackContext,
    parts: SettingParts,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The setting the ``chosen`` parts (a key for each axis named) make for ``pack``.

    Parts are applied in the axes' order, a later one's colour for a role replacing an earlier
    one's. A part's swatch the pack does not state is left out; its colour for a family's upward
    faces becomes one entry for each surface of that family the pack or an earlier part dresses;
    its light is the first alternative whose preset the pack states (None names the pack's
    default), and a second part's light adds its changes to the first's. A part that is not
    listed is refused by name. The result is unchecked: :func:`apply_setting` checks it."""
    for axis, key in chosen.items():
        if (axis, key) not in parts.parts:
            _fail("reference", f"parts.{axis}", f"names no part {json.dumps(key)}")
    setting: dict[str, Any] = {
        "profile": PROFILE,
        "origin": "authored" if provenance is None else provenance["kind"],
        "provenance": {"kind": "authored"} if provenance is None else dict(provenance),
        "parts": [],
        "light": None,
        "surfaces": {},
        "up": {},
        "swatches": {},
        "edge": None,
    }
    for axis, _title in parts.axes:
        if axis not in chosen:
            continue
        part = parts.parts[(axis, chosen[axis])]
        setting["parts"].append({"axis": axis, "key": chosen[axis]})
        for alternative in part["light"]:
            source = alternative["from"] or pack.light["default_preset"]
            if source not in pack.light["presets"]:
                continue
            if setting["light"] is None:
                setting["light"] = {"from": source, "changes": {}}
            setting["light"]["changes"].update(copy.deepcopy(alternative["changes"]))
            break
        for role, colour in part["surfaces"].items():
            setting["surfaces"][role] = dict(colour)
        dressed = sorted({*pack.surfaces, *setting["surfaces"]})
        for family, colour in part["up_families"].items():
            if family not in context.families:
                _fail("reference", f"parts.{axis}", f"names no look family {json.dumps(family)}")
            for role in dressed:
                if role.partition(".")[0] == family:
                    setting["up"][role] = list(colour)
        for key, restated in part["swatches"].items():
            if key in pack.swatches:
                setting["swatches"][key] = {**setting["swatches"].get(key, {}), **restated}
        if part["edge"] is not None and pack.edge is not None:
            setting["edge"] = {"ground": list(part["edge"])}
    return setting


def bound_setting(
    chain: Sequence[Mapping[str, Any]],
    context: StylePackContext,
    *,
    document: Any = None,
    chosen: Mapping[str, str] | None = None,
    rules: SettingRules | None = None,
    parts: SettingParts | None = None,
) -> str | None:
    """The setting a world's appearance may name over the pack ``chain`` resolves to, as its
    canonical JSON, or the first rule it breaks: ``document`` read and applied, or the ``chosen``
    parts composed for that pack and then held to the same rules. None when neither is stated, and
    when the parts chosen change nothing of this pack, so a world never names an empty setting."""
    rules = setting_rules() if rules is None else rules
    pack = resolve_chain(chain)
    if document is None:
        if chosen is None:
            return None
        document = compose_setting(
            chosen, pack, context, setting_parts() if parts is None else parts
        )
    setting = read_setting(document, rules)
    apply_setting(pack, setting, context, rules)
    if not (
        setting["parts"]
        or setting["light"]
        or setting["surfaces"]
        or setting["up"]
        or setting["swatches"]
        or setting["edge"]
    ):
        return None
    return canonical_json(setting)


def settings_listing(parts: SettingParts | None = None) -> dict[str, Any]:
    """The named parts as a page lists them for a person to choose: the axes in order, and each
    part's axis, key, title and description. The figures stay on the server, which composes."""
    parts = setting_parts() if parts is None else parts
    return {
        "profile": LISTING_PROFILE,
        "version": parts.version,
        "axes": [{"key": key, "title": title} for key, title in parts.axes],
        "parts": parts.listed(),
    }

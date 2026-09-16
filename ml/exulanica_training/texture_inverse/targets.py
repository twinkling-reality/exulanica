"""What the network predicts, derived from the makers' own manifests and nothing else.

A record's recipe becomes, for its maker:

- one number in [0, 1] per integer control, its value placed within the control's own range;
- the mean of an integer list the same way, since lists vary in length;
- one index per choice control, predicted as a class;
- three numbers per colour, each channel over 255, and the mean colour of a colour list.

The maker itself is a class too. The layout is a pure function of the manifests, which are read
by digest from the published object store and checked against it, so two runs with the same
export build the same layout. Decoding a prediction back into a recipe, repairing it and checking
it against the maker is the product's job, and a proposal is only ever a recipe that check
accepts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica_training.texture_inverse.export import ExportRefused, canonical_bytes

__all__ = ["MakerLayout", "TargetLayout", "encode", "load_layout"]


@dataclass(frozen=True, slots=True)
class MakerLayout:
    """One maker's targets: the scalar slots in order, and each choice with its options."""

    maker_id: str
    version: int
    scalars: tuple[str, ...]
    choices: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class TargetLayout:
    makers: tuple[MakerLayout, ...]

    def index(self, maker_id: str, version: int) -> int:
        for position, maker in enumerate(self.makers):
            if (maker.maker_id, maker.version) == (maker_id, version):
                return position
        raise ExportRefused(f"{maker_id} version {version} is not in this layout")


def _manifest(objects: Path, digest: str) -> Mapping[str, Any]:
    raw = (objects / f"{digest}.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ExportRefused(f"maker object {digest} does not hash to its name")
    document = json.loads(raw)
    if canonical_bytes(document) != raw or document.get("profile") != "exulanica.texture-maker/v1":
        raise ExportRefused(f"object {digest} is not a canonical maker manifest")
    return document


def _maker_layout(manifest: Mapping[str, Any]) -> MakerLayout:
    scalars: list[str] = []
    choices: list[tuple[str, tuple[str, ...]]] = []
    for control in manifest["controls"]:
        key, kind = control["key"], control["kind"]
        if kind in ("integer", "integer_list"):
            scalars.append(key)
        elif kind in ("srgb", "srgb_list"):
            scalars.extend(f"{key}.{channel}" for channel in ("red", "green", "blue"))
        elif kind == "choice":
            choices.append((key, tuple(control["options"])))
        else:
            raise ExportRefused(
                f"{manifest['maker_id']} has a control kind {kind!r} with no target"
            )
    return MakerLayout(
        maker_id=manifest["maker_id"],
        version=manifest["version"],
        scalars=tuple(scalars),
        choices=tuple(choices),
    )


def load_layout(
    makers: Sequence[tuple[str, int, str]], objects: Path
) -> tuple[TargetLayout, dict[tuple[str, int], Mapping[str, Any]]]:
    """The layout for these makers, read from the object store by digest, sorted by identity."""
    manifests: dict[tuple[str, int], Mapping[str, Any]] = {}
    for maker_id, version, digest in sorted(makers):
        manifest = _manifest(objects, digest)
        if (manifest["maker_id"], manifest["version"]) != (maker_id, version):
            raise ExportRefused(f"object {digest} is not {maker_id} version {version}")
        manifests[(maker_id, version)] = manifest
    layout = TargetLayout(makers=tuple(_maker_layout(m) for m in manifests.values()))
    return layout, manifests


def _unit(value: int, control: Mapping[str, Any]) -> float:
    low, high = control["minimum"], control["maximum"]
    return 0.0 if high == low else (value - low) / (high - low)


def encode(
    recipe: Mapping[str, Any], layout: TargetLayout, manifests: Mapping[tuple[str, int], Any]
) -> tuple[int, list[float], list[int]]:
    """``(maker index, scalar targets, choice indexes)`` for one recipe."""
    identity = (recipe["maker"]["id"], recipe["maker"]["version"])
    position = layout.index(*identity)
    controls = {control["key"]: control for control in manifests[identity]["controls"]}
    parameters = recipe["parameters"]
    scalars: list[float] = []
    for slot in layout.makers[position].scalars:
        key, _, channel = slot.partition(".")
        control = controls[key]
        value = parameters[key]
        if control["kind"] == "integer":
            scalars.append(_unit(value, control))
        elif control["kind"] == "integer_list":
            scalars.append(sum(_unit(item, control) for item in value) / len(value))
        else:
            index = ("red", "green", "blue").index(channel)
            colours = [value] if control["kind"] == "srgb" else value
            scalars.append(sum(colour[index] for colour in colours) / (255 * len(colours)))
    choices = [options.index(parameters[key]) for key, options in layout.makers[position].choices]
    return position, scalars, choices

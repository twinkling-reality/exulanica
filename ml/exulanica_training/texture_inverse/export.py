"""A synthetic texture dataset export, read back and verified before a single picture is used.

``web/packages/loom-texture`` exports a plan into ``images/<set id>.rgb`` shards,
``records.jsonl`` and ``dataset.json``, and the repository commits only ``dataset.json``
(``web/packages/loom-texture/dataset/manifests/``). A training run is given the export and the
committed manifest, and refuses unless:

- the export's ``dataset.json`` is the committed manifest, byte for byte;
- the manifest says ``"truth": "invented"`` and ``"licence_id": "CC0-1.0"``, so nothing observed
  and nothing private to a workspace is ever trained on by this path;
- every shard and the records file have the length and sha256 the manifest names;
- every record is canonical JSON, numbered in order, and names a shard offset that exists.

This module is plain Python: it runs, and its tests run, without torch.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DATASET_FILE",
    "DATASET_PROFILE",
    "ExportRefused",
    "Record",
    "VerifiedExport",
    "canonical_bytes",
    "verify_export",
]

DATASET_PROFILE: Final = "exulanica.texture-dataset/v1"
DATASET_FILE: Final = "dataset.json"
RECORDS_FILE: Final = "records.jsonl"
#: The only licence this path trains on. A workspace's private bakes are never a training input.
TRAINABLE_LICENCE: Final = "CC0-1.0"
_SHA256_HEX: Final = frozenset("0123456789abcdef")


class ExportRefused(RuntimeError):
    """The export is not the dataset its committed manifest describes."""


def canonical_bytes(value: Any) -> bytes:
    """The repository's canonical JSON: sorted keys, no spaces, integers only."""

    def check(node: Any, path: str) -> None:
        if isinstance(node, float):
            raise ExportRefused(f"{path} is a float, which no dataset object holds")
        if isinstance(node, Mapping):
            for key, item in node.items():
                check(item, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                check(item, f"{path}[{index}]")

    check(value, "$")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256_HEX


def _strict(raw: bytes, where: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise ExportRefused(f"{where} repeats the key {key!r}")
            result[key] = item
        return result

    def refuse_float(literal: str) -> Any:
        raise ExportRefused(f"{where} holds the non-integer {literal}")

    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=refuse_float
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportRefused(f"{where} is not JSON") from error
    if canonical_bytes(document) != raw:
        raise ExportRefused(f"{where} is not canonical JSON")
    return document


@dataclass(frozen=True, slots=True)
class Record:
    """One training pair: where its picture is, and the recipe the picture was baked from."""

    index: int
    set_id: str
    offset: int
    recipe: Mapping[str, Any]
    recipe_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedExport:
    """An export whose every file matched its committed manifest."""

    directory: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    image_size: int
    records: tuple[Record, ...]
    #: Shard path by set id, relative to the directory.
    shards: Mapping[str, str]

    def maker_objects(self) -> tuple[tuple[str, int, str], ...]:
        """``(maker id, version, manifest object sha256)`` for every maker the records use."""
        return tuple(
            (maker["maker_id"], maker["version"], maker["object_sha256"])
            for maker in self.manifest["makers"]
        )

    def picture(self, record: Record) -> bytes:
        """The record's sRGB bytes, rows top to bottom, read from its shard."""
        pixels = self.image_size * self.image_size * 3
        with (self.directory / self.shards[record.set_id]).open("rb") as handle:
            handle.seek(record.offset * pixels)
            data = handle.read(pixels)
        if len(data) != pixels:
            raise ExportRefused(f"record {record.index} runs past its shard")
        return data


def _file(directory: Path, relative: str, size: int, digest: str) -> None:
    path = directory / relative
    if path.is_symlink() or not path.is_file():
        raise ExportRefused(f"{relative} is not a regular file in the export")
    if path.stat().st_size != size:
        raise ExportRefused(f"{relative} is {path.stat().st_size} bytes, not {size}")
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ExportRefused(f"{relative} does not hash to its manifest's digest")


def verify_export(directory: Path, committed_manifest: Path) -> VerifiedExport:
    """The export at ``directory``, checked file by file against ``committed_manifest``."""
    committed = committed_manifest.read_bytes()
    exported = (directory / DATASET_FILE).read_bytes()
    if exported != committed:
        raise ExportRefused(f"{DATASET_FILE} is not the committed manifest, byte for byte")
    manifest = _strict(committed, DATASET_FILE)
    if manifest.get("profile") != DATASET_PROFILE:
        raise ExportRefused(f"the manifest is not {DATASET_PROFILE}")
    if manifest.get("truth") != "invented":
        raise ExportRefused("only invented pictures are trained on by this path")
    if manifest.get("licence_id") != TRAINABLE_LICENCE:
        raise ExportRefused(f"only {TRAINABLE_LICENCE} data is trained on by this path")
    image = manifest["image"]
    if image.get("channels") != 3 or image.get("width") != image.get("height"):
        raise ExportRefused("pictures are square and three-channel")
    size = image["width"]
    shards: dict[str, str] = {}
    counts: dict[str, int] = {}
    for shard in manifest["shards"]:
        if not _is_sha256(shard["sha256"]) or shard["path"] != f"images/{shard['set_id']}.rgb":
            raise ExportRefused(f"shard {shard['set_id']} is not named as the exporter names it")
        if shard["byte_size"] != shard["records"] * size * size * 3:
            raise ExportRefused(f"shard {shard['set_id']} is not whole pictures")
        _file(directory, shard["path"], shard["byte_size"], shard["sha256"])
        shards[shard["set_id"]] = shard["path"]
        counts[shard["set_id"]] = shard["records"]
    listing = manifest["records"]
    _file(directory, listing["path"], listing["byte_size"], listing["sha256"])
    lines = (directory / listing["path"]).read_bytes().split(b"\n")
    if lines[-1] != b"" or len(lines) - 1 != listing["count"]:
        raise ExportRefused("the records file does not hold the counted records, one per line")
    records: list[Record] = []
    for index, line in enumerate(lines[:-1]):
        document = _strict(line, f"record {index}")
        recipe = document["recipe"]
        if (
            document["index"] != index
            or document["set_id"] not in shards
            or not 0 <= document["offset"] < counts[document["set_id"]]
            or _sha256(canonical_bytes(recipe)) != document["recipe_sha256"]
        ):
            raise ExportRefused(f"record {index} does not agree with its position or its recipe")
        records.append(
            Record(
                index=index,
                set_id=document["set_id"],
                offset=document["offset"],
                recipe=recipe,
                recipe_sha256=document["recipe_sha256"],
            )
        )
    return VerifiedExport(
        directory=directory,
        manifest=manifest,
        manifest_sha256=_sha256(committed),
        image_size=size,
        records=tuple(records),
        shards=shards,
    )


def iter_split(export: VerifiedExport, *, held_out_every: int) -> Iterator[tuple[str, Record]]:
    """Each record with ``train`` or ``held_out``, decided by its number and nothing else."""
    for record in export.records:
        yield ("held_out" if record.index % held_out_every == 0 else "train"), record

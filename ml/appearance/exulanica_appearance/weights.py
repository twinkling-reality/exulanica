"""``exulanica.appearance-weights/v1``: one model repository's weights, pinned file by file.

A weights manifest names a Hugging Face repository at a 40-hex revision, the licence its card
declares at that revision (held to ``docs/license-matrix.md`` section 6), where each component that
came from elsewhere came from and under what licence, which files a generation loads, and every
one of those files by size and digest:

- a file stored through Git LFS (every weights file) by the sha256 the Hub reports for it;
- a small file stored in git itself (configs, tokenizer text) by its git blob id, which is what the
  Hub reports for it, so building a manifest never downloads a byte of the repository.

The manifest is built on the operator's machine from metadata alone
(``scripts/fetch-hf-metadata.sh``). On the rented machine the weights are downloaded at that
revision and :func:`verify_directory` checks every listed file before a model loads. Its sha256 is
what a generation record, and a model-made maker, name the weights by.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_revision,
    is_sha256,
    is_text,
    parse_canonical,
    sha256_hex,
)
from exulanica_appearance.licences import ALLOWED, RULE, licence_id

__all__ = [
    "WEIGHTS_PROFILE",
    "MetadataDirectory",
    "build_weights",
    "git_blob_sha1",
    "read_weights",
    "verify_directory",
]

WEIGHTS_PROFILE: Final = "exulanica.appearance-weights/v1"
_KEYS: Final = (
    "files",
    "licence",
    "lineage",
    "profile",
    "read_on",
    "repository",
    "revision",
    "selection",
    "total_bytes",
)
_CARD_KEYS: Final = ("license", "license_name", "license_link")
_REPOSITORY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_DATE: Final = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]")
_PATH: Final = re.compile(r"[A-Za-z0-9_.@+-]+(/[A-Za-z0-9_.@+-]+)*")
_SHA1: Final = re.compile(r"[0-9a-f]{40}")
_CHUNK: Final = 1 << 20


def git_blob_sha1(raw: bytes) -> str:
    """The id git gives a file's bytes, which is what the Hub reports for a file not in LFS."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class MetadataDirectory:
    """What ``fetch-hf-metadata.sh`` wrote for one repository at one revision."""

    repository: str
    revision: str
    card: Mapping[str, Any]
    tree: Sequence[Mapping[str, Any]]
    card_sha256: str

    @classmethod
    def read(cls, directory: Path) -> MetadataDirectory:
        source = (directory / "source.txt").read_text(encoding="ascii").split()
        if len(source) != 2 or not is_revision(source[1]):
            raise Refused(f"{directory} does not name a repository and a 40-hex revision")
        revision = json.loads((directory / "revision.json").read_bytes())
        if revision.get("id") != source[0] or revision.get("sha") != source[1]:
            raise Refused(f"{directory}: revision.json is not {source[0]} at {source[1]}")
        tree = json.loads((directory / "tree.json").read_bytes())
        if not isinstance(tree, list):
            raise Refused(f"{directory}: tree.json is not a file list")
        return cls(
            repository=source[0],
            revision=source[1],
            card=revision.get("cardData") or {},
            tree=tree,
            card_sha256=sha256_hex((directory / "README.md").read_bytes()),
        )

    def files(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entry in self.tree:
            if entry.get("type") != "file":
                continue
            path = entry["path"]
            lfs = entry.get("lfs")
            if lfs:
                out[path] = {"path": path, "sha256": lfs["oid"], "size": lfs["size"]}
            else:
                out[path] = {"git_blob_sha1": entry["oid"], "path": path, "size": entry["size"]}
        return out


def _declared(card: Mapping[str, Any]) -> dict[str, str]:
    return {key: card[key] for key in _CARD_KEYS if isinstance(card.get(key), str)}


def build_weights(
    spec: Mapping[str, Any], read_on: str, metadata: Mapping[tuple[str, str], MetadataDirectory]
) -> bytes:
    """A weights manifest's canonical bytes, from one spec entry and the fetched metadata.

    ``spec`` names ``repository``, ``revision``, ``include`` (glob patterns over repository paths,
    ``*`` crossing ``/``), ``reason`` and ``lineage``. Every pattern must select at least one file,
    so a typo cannot silently leave a component out.
    """
    key = (spec["repository"], spec["revision"])
    if key not in metadata:
        raise Refused(f"no metadata was fetched for {key[0]} at {key[1]}")
    own = metadata[key]
    files = own.files()
    chosen: dict[str, dict[str, Any]] = {}
    for pattern in spec["include"]:
        matched = [path for path in files if fnmatch.fnmatchcase(path, pattern)]
        if not matched:
            raise Refused(f"{own.repository}: the pattern {pattern!r} selects no file")
        for path in matched:
            chosen[path] = files[path]
    lineage = []
    for entry in spec["lineage"]:
        lineage.append(_lineage(own, entry, metadata))
    document = {
        "files": [chosen[path] for path in sorted(chosen)],
        "licence": {
            "card": _declared(own.card),
            "card_sha256": own.card_sha256,
            "id": licence_id(own.card),
            "rule": RULE,
        },
        "lineage": sorted(lineage, key=lambda item: (item["component"], item["source"])),
        "profile": WEIGHTS_PROFILE,
        "read_on": read_on,
        "repository": own.repository,
        "revision": own.revision,
        "selection": {"include": list(spec["include"]), "reason": spec["reason"]},
        "total_bytes": sum(item["size"] for item in chosen.values()),
    }
    raw = canonical_bytes(document)
    read_weights(raw)
    return raw


def _lineage(
    own: MetadataDirectory,
    entry: Mapping[str, Any],
    metadata: Mapping[tuple[str, str], MetadataDirectory],
) -> dict[str, str]:
    kind = entry["kind"]
    if kind == "publisher-statement":
        return {
            "component": entry["component"],
            "evidence": entry["evidence"],
            "licence_id": entry["licence_id"],
            "source": entry["source"],
            "source_sha256": entry["source_sha256"],
        }
    other_key = (entry["repository"], entry["revision"])
    if other_key not in metadata:
        raise Refused(f"no metadata was fetched for lineage {other_key[0]} at {other_key[1]}")
    other = metadata[other_key]
    if kind == "identical-bytes":
        mine = own.files().get(entry["own_path"], {})
        theirs = other.files().get(entry["path"], {})
        if "sha256" not in mine or mine.get("sha256") != theirs.get("sha256"):
            raise Refused(
                f"{own.repository}/{entry['own_path']} is not byte-identical to "
                f"{other.repository}/{entry['path']}"
            )
    elif kind != "card":
        raise Refused(f"lineage kind {kind!r} is not card, identical-bytes or publisher-statement")
    return {
        "component": entry["component"],
        "evidence": entry["evidence"],
        "licence_id": licence_id(other.card),
        "source": f"https://huggingface.co/{other.repository}/tree/{other.revision}",
        "source_sha256": other.card_sha256,
    }


def read_weights(raw: bytes) -> dict[str, Any]:
    """A weights manifest, refused unless it is exactly this profile's shape."""
    where = "the weights manifest"
    document = exact_keys(parse_canonical(raw, where), _KEYS, where)
    if document["profile"] != WEIGHTS_PROFILE:
        raise Refused(f"{where}: profile is {WEIGHTS_PROFILE}")
    if not isinstance(document["repository"], str) or not _REPOSITORY.fullmatch(
        document["repository"]
    ):
        raise Refused(f"{where}: repository is an owner and a name")
    if not is_revision(document["revision"]):
        raise Refused(f"{where}: revision is 40 lowercase hex")
    if not isinstance(document["read_on"], str) or not _DATE.fullmatch(document["read_on"]):
        raise Refused(f"{where}: read_on is a date, YYYY-MM-DD")
    licence = exact_keys(
        document["licence"], ("card", "card_sha256", "id", "rule"), f"{where}: licence"
    )
    card = licence["card"]
    if not isinstance(card, dict) or not set(card) <= set(_CARD_KEYS) or "license" not in card:
        raise Refused(
            f"{where}: licence card holds the card's license, and its name and link if any"
        )
    if licence["id"] not in ALLOWED or licence_id(card) != licence["id"]:
        raise Refused(f"{where}: licence id is the one {RULE} allows for what the card declares")
    if licence["rule"] != RULE or not is_sha256(licence["card_sha256"]):
        raise Refused(f"{where}: licence names {RULE} and the card's sha256")
    _read_lineage(document["lineage"], where)
    selection = exact_keys(document["selection"], ("include", "reason"), f"{where}: selection")
    include = selection["include"]
    if (
        not isinstance(include, list)
        or not include
        or not all(is_text(pattern) for pattern in include)
        or not is_text(selection["reason"])
    ):
        raise Refused(f"{where}: selection has at least one pattern and its reason")
    files = document["files"]
    if not isinstance(files, list) or not files:
        raise Refused(f"{where}: files lists at least one file")
    paths = []
    for index, item in enumerate(files):
        at = f"{where}: files[{index}]"
        if not isinstance(item, dict):
            raise Refused(f"{at} is an object")
        if set(item) == {"path", "sha256", "size"}:
            if not is_sha256(item["sha256"]):
                raise Refused(f"{at}: sha256 is 64 lowercase hex")
        elif set(item) == {"git_blob_sha1", "path", "size"}:
            if not isinstance(item["git_blob_sha1"], str) or not _SHA1.fullmatch(
                item["git_blob_sha1"]
            ):
                raise Refused(f"{at}: git_blob_sha1 is 40 lowercase hex")
        else:
            raise Refused(f"{at} has a path, a size and exactly one of sha256 or git_blob_sha1")
        if (
            not isinstance(item["path"], str)
            or not _PATH.fullmatch(item["path"])
            or ".." in item["path"].split("/")
        ):
            raise Refused(f"{at}: path is a relative repository path")
        if not is_count(item["size"]):
            raise Refused(f"{at}: size is a byte count")
        if not any(fnmatch.fnmatchcase(item["path"], pattern) for pattern in include):
            raise Refused(f"{at}: {item['path']} is not selected by any pattern")
        paths.append(item["path"])
    if paths != sorted(set(paths)):
        raise Refused(f"{where}: files are sorted by path, each once")
    if document["total_bytes"] != sum(item["size"] for item in files):
        raise Refused(f"{where}: total_bytes is the sum of the files' sizes")
    return document


def _read_lineage(lineage: object, where: str) -> None:
    if not isinstance(lineage, list):
        raise Refused(f"{where}: lineage is a list")
    order = []
    for index, item in enumerate(lineage):
        at = f"{where}: lineage[{index}]"
        entry = exact_keys(
            item, ("component", "evidence", "licence_id", "source", "source_sha256"), at
        )
        if not all(is_text(entry[key]) for key in ("component", "evidence", "source")):
            raise Refused(f"{at}: component, evidence and source are printable ASCII")
        if not entry["source"].startswith("https://"):
            raise Refused(f"{at}: source is an https address pinned to a revision or commit")
        if entry["licence_id"] not in ALLOWED:
            raise Refused(
                f"{at}: {entry['component']} comes under {entry['licence_id']}, which {RULE} does not allow"
            )
        if not is_sha256(entry["source_sha256"]):
            raise Refused(f"{at}: source_sha256 is 64 lowercase hex")
        order.append((entry["component"], entry["source"]))
    if order != sorted(set(order)):
        raise Refused(f"{where}: lineage is sorted by component and source, each once")


def verify_directory(raw_manifest: bytes, directory: Path) -> int:
    """Check every listed file under ``directory``; return the bytes checked, or refuse."""
    manifest = read_weights(raw_manifest)
    root = directory.resolve()
    checked = 0
    for item in manifest["files"]:
        path = (root / item["path"]).resolve()
        if root not in path.parents:
            raise Refused(f"{item['path']} resolves outside {directory}")
        if not path.is_file():
            raise Refused(f"{item['path']} is missing from {directory}")
        size = path.stat().st_size
        if size != item["size"]:
            raise Refused(f"{item['path']} is {size} bytes, not {item['size']}")
        if "sha256" in item:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while block := handle.read(_CHUNK):
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise Refused(f"{item['path']} does not have the sha256 its manifest names")
        elif git_blob_sha1(path.read_bytes()) != item["git_blob_sha1"]:
            raise Refused(f"{item['path']} does not have the git blob id its manifest names")
        checked += size
    return checked

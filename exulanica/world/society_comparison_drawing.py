"""A completed comparison run's drawing, verified once and stored, and what makes it current.

A run is read by replaying it from its stored requests and receipts and holding the replay to the
digests its outcome recorded
(:func:`~exulanica.world.society_comparison_result.verified_replay`), which takes seconds for a
town. The host that plays a run does that once, after the run's outcome is recorded, and stores the
document the page draws (:func:`~exulanica.world.society_comparison_result.replay_document`),
compressed, in migration 0121's ``society_comparison_replay``, keyed by the run and
:func:`drawing_sha256`. A read serves the stored document only under the drawing digest of the
code reading it, and replays where there is none. The inputs' rights are asked on every read either
way, by the route, before anything drawn from them is answered.

**What makes a stored drawing current.** The document is what the replay and the drawing code make
of the run's stored records, which never change. So it stays the document a replay would draw for
as long as that code and the catalogs it reads stay the same: :data:`DRAWING_MODULES` names every
module of this package a verified replay and its drawing execute, and the plan's builder, and
:func:`drawing_sha256` covers their bytes, the society catalogs' bytes and the drawing's profile.
Any change to them is a new digest, under which nothing is stored until a host draws the run
again; ``tests/test_comparison_drawing.py`` traces a verified replay and fails on a module it runs
that the list leaves out.

**What is not stored.** A model's name is the manifest's (``Manifest.model_name``), which may name
a model differently later, so a stored drawing names each model by its id alone and a read fills
the name in (:func:`with_names`). Nothing stored carries a seed or a raw state; the document is the
one the route has always served.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib
import importlib.util
import io
import json
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.movement.registry import MODULES_PATH
from exulanica.world.decision_roles import REGISTRY_DIRECTORY
from exulanica.world.society_catalogs import ROUTINE_DIRECTORY
from exulanica.world.society_engines import ENGINES_PATH

__all__ = [
    "CODE_SHA256",
    "DRAWING_MODULES",
    "DrawingCorrupt",
    "StoredDrawing",
    "decode",
    "drawing_data",
    "drawing_sha256",
    "encode",
    "with_names",
]

#: Every module of this package whose code a verified replay and its drawing execute, found by
#: tracing one, with the builder of the plan they replay: a change to any of them may change what
#: is drawn, so each is covered by :func:`drawing_sha256`.
DRAWING_MODULES: Final = (
    "exulanica.canonical",
    "exulanica.movement.registry",
    "exulanica.movement.steps",
    "exulanica.movement.walking",
    "exulanica.world.deciders",
    "exulanica.world.decision_roles",
    "exulanica.world.role_decisions",
    "exulanica.world.roles.person",
    "exulanica.world.society",
    "exulanica.world.society_catalogs",
    "exulanica.world.society_choice",
    "exulanica.world.society_comparison",
    "exulanica.world.society_comparison_drawing",
    "exulanica.world.society_comparison_living_drawing",
    "exulanica.world.society_comparison_repository",
    "exulanica.world.society_comparison_result",
    "exulanica.world.society_decision_contract",
    "exulanica.world.society_engines",
    "exulanica.world.society_input_policy",
    "exulanica.world.society_legacy",
    "exulanica.world.society_living",
    "exulanica.world.society_living_decisions",
    "exulanica.world.society_model_decisions",
    "exulanica.world.society_planner",
    "exulanica.world.society_person_label",
    "exulanica.world.society_place",
    "exulanica.world.society_score",
)
#: What a stored drawing names in place of a model's name: the name is filled in on read.
_NAME_FILLED_ON_READ: Final = ""
#: gzip's own level for the stored bytes: a drawing is written once and read many times, and at
#: the highest level a 48-person town's drawing shrinks furthest for a write that happens once.
_GZIP_LEVEL: Final = 9


def _module_path(name: str) -> Path:
    """Where a module's source is, found without importing it: this module is imported by modules
    the list names, so importing them here would import it again half made."""
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        raise ImportError(f"no source for {name}")
    return Path(spec.origin)


def drawing_data() -> tuple[Path, ...]:
    """Every data file a verified replay and its drawing read: the society catalogs, the movement
    modules walking reads, the society engines and the decision role registry and catalogs."""
    return tuple(
        sorted(
            {
                *ROUTINE_DIRECTORY.glob("*.json"),
                MODULES_PATH,
                ENGINES_PATH,
                *REGISTRY_DIRECTORY.glob("*.json"),
            }
        )
    )


def _code_sha256() -> str:
    digest = hashlib.sha256()
    for name in DRAWING_MODULES:
        digest.update(name.encode("utf-8") + b"\0" + _module_path(name).read_bytes() + b"\0")
    for file in drawing_data():
        digest.update(file.name.encode("utf-8") + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()


#: The digest of the drawing code and the data it reads, taken once when this module is imported:
#: a process reads under the code it started with, whatever changes on disk after it.
CODE_SHA256: Final = _code_sha256()


def drawing_sha256(profile: str) -> str:
    """The digest a drawing of ``profile`` is stored and found under: the drawing's profile and
    :data:`CODE_SHA256`, every module of :data:`DRAWING_MODULES` and every file of
    :func:`drawing_data`, by name and bytes."""
    return hashlib.sha256(profile.encode("utf-8") + b"\0" + CODE_SHA256.encode("ascii")).hexdigest()


class StoredDrawing:
    """A drawing as it is stored: its canonical bytes compressed, and the SHA-256 and length of
    the bytes before compression."""

    __slots__ = ("document_bytes", "document_gzip", "document_sha256")

    def __init__(self, document_gzip: bytes, document_sha256: str, document_bytes: int) -> None:
        self.document_gzip = document_gzip
        self.document_sha256 = document_sha256
        self.document_bytes = document_bytes


def _without_names(document: Mapping[str, Any]) -> dict[str, Any]:
    stored = dict(document)
    stored["people"] = [
        {
            **person,
            "decider": {**person["decider"], "name": _NAME_FILLED_ON_READ}
            if person["decider"]["kind"] == "model"
            else person["decider"],
        }
        for person in document["people"]
    ]
    return stored


def encode(document: Mapping[str, Any]) -> StoredDrawing:
    """A drawing as it is stored, its models named by id alone."""
    raw = canonical_json(_without_names(document))
    return StoredDrawing(
        gzip.compress(raw, compresslevel=_GZIP_LEVEL, mtime=0),
        hashlib.sha256(raw).hexdigest(),
        len(raw),
    )


class DrawingCorrupt(ValueError):
    """Stored bytes that are not the drawing their digest names."""


def decode(stored: StoredDrawing) -> dict[str, Any]:
    """The stored drawing, held to its digest and length; anything else, bytes that are not gzip,
    a stream cut short, or more bytes than the drawing states, is refused by name. At most one
    byte past the stated length is ever decompressed."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(stored.document_gzip)) as stream:
            raw = stream.read(stored.document_bytes + 1)
    except (EOFError, OSError, zlib.error) as exc:
        raise DrawingCorrupt("run_drawing_corrupt") from exc
    if len(raw) != stored.document_bytes or hashlib.sha256(raw).hexdigest() != (
        stored.document_sha256
    ):
        raise DrawingCorrupt("run_drawing_corrupt")
    document: dict[str, Any] = json.loads(raw)
    return document


def with_names(document: dict[str, Any], model_name: Callable[[str], str]) -> dict[str, Any]:
    """The stored drawing with each model named as ``model_name`` names it now."""
    for person in document["people"]:
        decider = person["decider"]
        if decider["kind"] == "model":
            decider["name"] = model_name(decider["model_id"])
    return document

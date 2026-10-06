"""Each origin vocabulary that already exists, read into the one origin record.

Pieces made before the origin record carry their origin in a vocabulary of their own, and keep
their bytes: a world kind (``origin``, ``provenance``, ``licence``), a style pack (``origin``,
``provenance``, ``licence``, ``authors``), a generated piece's receipt (``origin``, ``truth``,
``licence``), a person's prepared asset (its rights declaration), a reviewed asset's import
manifest, a people catalog family (its licence and sources), and a catalog entry's licence. One
reader for each turns it into ``exulanica.origin/v1`` (:mod:`exulanica.things.origin`), checked by
the record's own reader, so whatever shows where a piece came from reads one shape, and each
format's next version can write the record natively. Nothing here rewrites a stored document.

Three vocabularies are not read into the record, by design: a placed object's ``origin.kind`` and
``origin.role`` (always authored; fictional or personal, a claim the person makes about the object's
meaning) is how a thing came to be placed, kept beside the record; a character's per-trait origin
(observed, authored, generated) and a representation's (inferred, authored, generated, external)
describe evidence for traits, read in the browser where they live; and an assertion's provenance
(capture, inference, user, external) answers who supports an assertion, another axis
(docs/world-memory-model.md, section 3.1).

Pure: no connection, no store.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from exulanica.canonical import sha256_of_canonical
from exulanica.things.origin import ORIGIN_PROFILE, OWN_WORK, Origin, read_origin

__all__ = [
    "OWN_WORK",
    "origin_of_catalog_entry",
    "origin_of_character_family",
    "origin_of_generated_piece",
    "origin_of_reviewed_import",
    "origin_of_style_pack",
    "origin_of_workspace_asset",
    "origin_of_world_kind",
]


def _licence(
    spdx: str,
    *,
    attribution: str | None = None,
    verdict: str | None = None,
    text_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "spdx": spdx,
        "verdict": verdict or ("SHIP-ATTRIB" if attribution else "SHIP"),
        "attribution": attribution,
        "share_alike": "-SA-" in f"{spdx}-",
        "licence_url": None,
        "licence_text_sha256": text_sha256,
    }


def _record(
    klass: str,
    by: Mapping[str, Any],
    licence: Mapping[str, Any],
    *,
    sources: list[dict[str, Any]] | None = None,
    authors: list[str] | None = None,
    ingredients: list[str] | None = None,
    receipts: list[str] | None = None,
    distribution: str = "public",
) -> Origin:
    return read_origin(
        {
            "profile": ORIGIN_PROFILE,
            "class": klass,
            "by": dict(by),
            "sources": sources or [],
            "licence": dict(licence),
            "authors": authors or [],
            "lineage": {
                "ingredients": ingredients or [],
                "receipts": receipts or [],
                "translation_manifest_sha256": None,
            },
            "distribution": distribution,
        }
    )


def _model(
    model_id: str | None,
    *,
    provider: str | None = None,
    prompt_version: str | None = None,
    prompt_sha256: str | None = None,
    words_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "model",
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "words_sha256": words_sha256,
        "execution_sha256": None,
    }


def _account(text: object) -> dict[str, Any]:
    """An uploader named as ``account <id>``, as a world kind's provenance records one."""
    if isinstance(text, str) and text.startswith("account "):
        return {"kind": "account", "account_id": str(uuid.UUID(text.removeprefix("account ")))}
    return {"kind": "project"}


def origin_of_world_kind(document: Mapping[str, Any], *, distribution: str = "public") -> Origin:
    """A world kind's ``origin``, ``provenance`` and ``licence`` (``exulanica.world-kind/v1``)."""
    klass, provenance = str(document["origin"]), document["provenance"]
    if klass == "drafted":
        by = _model(
            provenance["model"],
            prompt_version=provenance["prompt_version"],
            prompt_sha256=provenance["prompt_sha256"],
            words_sha256=provenance["words_sha256"],
        )
    elif klass == "uploaded":
        by = _account(provenance.get("by"))
    else:
        by = {"kind": "project"}
    sources = (
        [
            {
                "reference": str(provenance["by"]),
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
        ]
        if klass == "imported"
        else None
    )
    return _record(
        klass,
        by,
        _licence(document["licence"]["spdx"], verdict=document["licence"]["verdict"]),
        sources=sources,
        distribution=distribution,
    )


def origin_of_style_pack(manifest: Mapping[str, Any], *, distribution: str = "public") -> Origin:
    """A style pack's ``origin``, ``provenance``, ``licence`` and ``authors``
    (``exulanica.style-pack/v1``)."""
    klass, provenance = str(manifest["origin"]), manifest["provenance"]
    licence = manifest["licence"]
    receipts: list[str] = []
    sources = None
    if klass == "drafted":
        by = _model(
            provenance["model_id"],
            prompt_version=provenance["prompt_version"],
            words_sha256=provenance["words_sha256"],
        )
    elif klass == "generated":
        by = _model(None)
        receipts = list(provenance["receipts"])
    elif klass == "uploaded":
        by = {"kind": "project"} if distribution == "public" else _account(None)
    else:
        by = {"kind": "project"}
    if klass == "imported":
        sources = [
            {
                "reference": str(provenance["source_reference"]),
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
        ]
    return _record(
        klass,
        by,
        _licence(str(licence["id"]), attribution=licence["attribution"]),
        sources=sources,
        authors=list(manifest["authors"]),
        receipts=receipts,
        distribution=distribution,
    )


def origin_of_generated_piece(receipt: Mapping[str, Any], *, distribution: str) -> Origin:
    """A generated piece's receipt (``exulanica.generated-asset/v1``): generated by the shape
    model it names, under CC0, the receipt itself its lineage."""
    if receipt["origin"] != "generated" or receipt["truth"] != "invented":
        raise ValueError("a generated piece's receipt states it was generated and invented")
    return _record(
        "generated",
        _model(None),
        _licence(str(receipt["licence"])),
        ingredients=[str(receipt["request_sha256"])],
        receipts=[sha256_of_canonical(dict(receipt)).hex()],
        distribution=distribution,
    )


def origin_of_workspace_asset(rights: Mapping[str, Any], *, account_id: uuid.UUID) -> Origin:
    """A person's prepared asset's rights declaration: their own work, or licensed with its
    attribution; uploaded by them, used in their workspace only."""
    if rights["basis"] == "own_work":
        licence = _licence(OWN_WORK, verdict="USE-ONLY")
    else:
        licence = _licence(str(rights["licence_id"]), attribution=rights.get("attribution"))
    reference = rights.get("source_reference")
    sources = (
        [
            {
                "reference": str(reference),
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
        ]
        if reference
        else None
    )
    return _record(
        "uploaded",
        {"kind": "account", "account_id": str(account_id)},
        licence,
        sources=sources,
        distribution="private",
    )


def origin_of_reviewed_import(manifest: Mapping[str, Any]) -> Origin:
    """A reviewed asset's import manifest (``exulanica.reviewed-asset-import/v1``): imported by
    this project from its pinned source, CC0, its bytes the ingredient."""
    return _record(
        "imported",
        {"kind": "project"},
        _licence(str(manifest["licence_id"]), text_sha256=str(manifest["licence_sha256"])),
        sources=[
            {
                "reference": str(manifest["source_url"]),
                "retrieved_on": None,
                "revision": str(manifest["source_revision"]),
                "licence_page_sha256": None,
            }
        ],
        ingredients=[str(manifest["content_sha256"])],
    )


def origin_of_character_family(family: Mapping[str, Any], definition: Mapping[str, Any]) -> Origin:
    """A people catalog family (``exulanica.character-catalog/v1``'s entry and its
    ``exulanica.character-family-definition/v1``): imported by this project from the sources its
    definition names, under the licence the catalog states, the licence text pinned by digest."""
    licence = family["licence"]
    if definition["familyId"] != family["familyId"] or definition["licence"]["id"] != licence["id"]:
        raise ValueError("a family's definition is the catalog family's, under its licence")
    return _record(
        "imported",
        {"kind": "project"},
        _licence(str(licence["id"]), text_sha256=str(licence["sha256"])),
        sources=[
            {
                "reference": str(source["url"]),
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
            for _name, source in sorted(definition["sources"].items())
        ],
    )


def origin_of_catalog_entry(licence: Mapping[str, Any]) -> Origin:
    """A catalog entry's licence (``{spdx, verdict, origin, licence_source, content_source}``):
    original work of this project, or derived from the source it names."""
    if licence["origin"] == "original":
        return _record("authored", {"kind": "project"}, _licence(str(licence["spdx"])))
    return _record(
        "imported",
        {"kind": "project"},
        _licence(
            str(licence["spdx"]),
            verdict=str(licence["verdict"]),
            attribution=str(licence["content_source"])
            if licence["verdict"] == "SHIP-ATTRIB"
            else None,
        ),
        sources=[
            {
                "reference": str(licence["content_source"]),
                "retrieved_on": None,
                "revision": None,
                "licence_page_sha256": None,
            }
        ],
    )

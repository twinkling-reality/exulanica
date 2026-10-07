"""The reference catalogs: sources, note aspects and the outgoing-query screen.

``assets/catalogs/reference-sources/`` holds each as a versioned, licensed catalog in the house
envelope (:mod:`exulanica.grammar.catalogs`):

* ``reference-source.v1.json``: every source a reference may come from. Each states whether it
  returns leads (words for drafting, never kept) or records (admissible facts), the one origin it
  is reached at, the environment variable holding its credential, the terms as read (address, the
  date the provider states, the date read and the digest of the text read), which classes of its
  data are kept, shown and exported, whether it is offered to everyone or to the operator only,
  its cost per call and the one request shape its adapter may send. Adding or replacing a source
  is an entry here plus one adapter in :mod:`exulanica.references.adapters`.
* ``reference-aspect.v1.json``: what a note may be about, the closed list the planner, the reader
  and the vision read write against.
* ``reference-query-screen.v1.json``: words no outgoing query may carry, by category, each with
  the term or reason that rules them out.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from exulanica.grammar.catalogs import (
    CatalogSchema,
    FieldCheck,
    FieldValue,
    integer_field,
    key_list_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError
from exulanica.models.egress import declared_origin

__all__ = [
    "AVAILABILITIES",
    "CATALOG_DIRECTORY",
    "DATA_CLASSES",
    "KINDS",
    "LEAD_DATA_CLASSES",
    "Aspect",
    "ReferenceCatalogs",
    "ReferenceSource",
    "load_reference_catalogs",
    "web_source",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "reference-sources")
)
#: A leads source returns words for drafting that are never kept; a records source returns facts
#: whose licence allows keeping, showing and exporting them.
KINDS: Final = ("leads", "records")
AVAILABILITIES: Final = ("operator_only", "everyone")
#: Every class of data a source's exchange carries. ``query`` and ``request_record`` are ours: the
#: words we sent and our record of sending them (provider, time, credits, request id, count).
DATA_CLASSES: Final = (
    "query",
    "request_record",
    "result_text",
    "result_title",
    "result_address",
    "image_address",
    "image_description",
    "generated_answer",
)
#: The only classes a leads source may keep, show or export: our own.
LEAD_DATA_CLASSES: Final = ("query", "request_record")
COST_UNITS: Final = ("credit",)
SEARCH_DEPTHS: Final = ("basic", "fast", "ultra-fast")

_ENV_NAME: Final = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_PATH: Final = re.compile(r"/[a-z0-9/_-]{0,63}")


def _choice(values: tuple[str, ...]) -> FieldCheck:
    def check(where: str, value: object) -> FieldValue:
        if value not in values:
            raise CatalogError(f"{where} is one of {list(values)}, got {value!r}")
        return cast(FieldValue, value)

    return check


def _matching(pattern: re.Pattern[str], what: str) -> FieldCheck:
    def check(where: str, value: object) -> FieldValue:
        text = cast(str, text_field(where, value))
        if pattern.fullmatch(text) is None:
            raise CatalogError(f"{where} is {what}, got {text!r}")
        return text

    return check


def _origin(where: str, value: object) -> FieldValue:
    text = cast(str, text_field(where, value))
    try:
        spelled = declared_origin(text)
    except ValueError as error:
        raise CatalogError(f"{where} is an origin: {error}") from error
    if spelled != text or not text.startswith("https://"):
        raise CatalogError(f"{where} is an https origin written as {spelled!r}, got {text!r}")
    return text


def _terms_address(where: str, value: object) -> FieldValue:
    text = cast(str, text_field(where, value))
    if not text.startswith("https://") or any(character.isspace() for character in text):
        raise CatalogError(f"{where} is an https address, got {text!r}")
    return text


def _data_classes(where: str, value: object) -> FieldValue:
    classes = cast(tuple[str, ...], key_list_field(where, value))
    unknown = sorted(set(classes) - set(DATA_CLASSES))
    if unknown:
        raise CatalogError(f"{where} names data classes outside {list(DATA_CLASSES)}: {unknown}")
    return classes


def _source_check(where: str, values: dict[str, FieldValue]) -> None:
    kept = set(cast(tuple[str, ...], values["kept"]))
    shown = set(cast(tuple[str, ...], values["shown"]))
    exported = set(cast(tuple[str, ...], values["exported"]))
    if not shown <= kept or not exported <= kept:
        raise CatalogError(f"{where}: what is shown or exported is kept first")
    if values["kind"] == "leads" and not kept <= set(LEAD_DATA_CLASSES):
        raise CatalogError(
            f"{where}: a leads source keeps only our own {list(LEAD_DATA_CLASSES)}, never "
            f"anything it returned, got {sorted(kept)}"
        )
    if values["kind"] == "records":
        raise CatalogError(
            f"{where}: no records source is admitted yet; a records source arrives with the "
            "admission that resolves and stores its facts"
        )


_SOURCE_SCHEMA: Final = CatalogSchema(
    catalog_id="reference-source",
    catalog_version=1,
    fields=(
        ("label", text_field),
        ("kind", _choice(KINDS)),
        ("egress_origin", _origin),
        ("endpoint_path", _matching(_PATH, "a path from the origin")),
        ("credential_env", _matching(_ENV_NAME, "an environment variable name")),
        ("terms_url", _terms_address),
        ("terms_updated", _matching(_DATE, "a date YYYY-MM-DD")),
        ("terms_read", _matching(_DATE, "a date YYYY-MM-DD")),
        ("terms_sha256", _matching(_SHA256, "a lowercase sha256")),
        ("kept", _data_classes),
        ("shown", _data_classes),
        ("exported", _data_classes),
        ("availability", _choice(AVAILABILITIES)),
        ("cost_unit", _choice(COST_UNITS)),
        ("cost_per_call", integer_field(1, 100)),
        ("search_depth", _choice(SEARCH_DEPTHS)),
        ("max_results", integer_field(1, 20)),
        ("calls_per_minute", integer_field(1, 600)),
        ("reason", text_field),
    ),
    entry_check=_source_check,
)


def _bounded_text(maximum: int) -> FieldCheck:
    def check(where: str, value: object) -> FieldValue:
        text = cast(str, text_field(where, value))
        if len(text) > maximum:
            raise CatalogError(f"{where} is at most {maximum} characters, got {len(text)}")
        return text

    return check


_ASPECT_SCHEMA: Final = CatalogSchema(
    catalog_id="reference-aspect",
    catalog_version=1,
    fields=(
        ("label", _bounded_text(40)),
        ("description", _bounded_text(160)),
        ("reason", text_field),
    ),
)


def _screen_words(where: str, value: object) -> FieldValue:
    words = key_list_field(where, value)
    if not words:
        raise CatalogError(f"{where} names at least one word")
    return words


_SCREEN_SCHEMA: Final = CatalogSchema(
    catalog_id="reference-query-screen",
    catalog_version=1,
    fields=(("words", _screen_words), ("reason", text_field)),
)


@dataclass(frozen=True, slots=True)
class ReferenceSource:
    """One source, as its catalog entry states it."""

    key: str
    label: str
    kind: str
    egress_origin: str
    endpoint_path: str
    credential_env: str
    terms_url: str
    terms_updated: str
    terms_read: str
    terms_sha256: str
    kept: tuple[str, ...]
    shown: tuple[str, ...]
    exported: tuple[str, ...]
    availability: str
    cost_unit: str
    cost_per_call: int
    search_depth: str
    max_results: int
    calls_per_minute: int

    @property
    def endpoint(self) -> str:
        return self.egress_origin + self.endpoint_path


@dataclass(frozen=True, slots=True)
class Aspect:
    key: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class ReferenceCatalogs:
    """The three catalogs, read and checked together."""

    sources: Mapping[str, ReferenceSource]
    aspects: Mapping[str, Aspect]
    #: Each screened phrase as its words (a key ``social_security`` is the two words in order),
    #: mapped to the category that rules it out.
    screened: Mapping[tuple[str, ...], str]


@functools.cache
def load_reference_catalogs(directory: Path = CATALOG_DIRECTORY) -> ReferenceCatalogs:
    """Read and check the reference catalogs; cached per directory."""
    sources = load_catalog(directory / "reference-source.v1.json", _SOURCE_SCHEMA)
    aspects = load_catalog(directory / "reference-aspect.v1.json", _ASPECT_SCHEMA)
    screen = load_catalog(directory / "reference-query-screen.v1.json", _SCREEN_SCHEMA)
    read_sources: dict[str, ReferenceSource] = {}
    for entry in sources.entries:
        values = dict(entry.values)
        values.pop("reason")
        read_sources[entry.key] = ReferenceSource(key=entry.key, **values)  # type: ignore[arg-type]
    read_aspects = {
        entry.key: Aspect(
            entry.key,
            label=str(dict(entry.values)["label"]),
            description=str(dict(entry.values)["description"]),
        )
        for entry in aspects.entries
    }
    screened: dict[tuple[str, ...], str] = {}
    for entry in screen.entries:
        for word in cast(tuple[str, ...], dict(entry.values)["words"]):
            phrase = tuple(word.split("_"))
            if phrase in screened:
                raise CatalogError(
                    f"reference-query-screen: {word!r} is in both {screened[phrase]!r} and "
                    f"{entry.key!r}"
                )
            screened[phrase] = entry.key
    return ReferenceCatalogs(
        sources=MappingProxyType(read_sources),
        aspects=MappingProxyType(read_aspects),
        screened=MappingProxyType(screened),
    )


def web_source(catalogs: ReferenceCatalogs | None = None) -> ReferenceSource | None:
    """The web source this product searches: the catalog's first leads source, in file order, or
    None when the catalog holds none. Replacing the source is a catalog entry and an adapter."""
    catalogs = catalogs if catalogs is not None else load_reference_catalogs()
    for source in catalogs.sources.values():
        if source.kind == "leads":
            return source
    return None

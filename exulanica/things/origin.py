"""Where a piece came from, in one record: the origin every thing kind, look and crossing carries.

A thing kind, a look and a crossing each carry ``origin``, profile ``exulanica.origin/v1``: how the
piece came to exist here (``class``), who or what made it (``by``), the sources it was taken from,
its licence with what that licence asks (attribution, share-alike), who made it as they are
credited, its lineage (ingredients by digest, generation receipts, a translation manifest) and
where it may be shown (``distribution``). New pieces write the record natively. Pieces that already
carry an origin of their own (a world kind, a style pack, a generated piece, a person's prepared
asset, a reviewed asset, a catalog entry) keep their bytes; :mod:`exulanica.things.vocabularies`
reads each into this record, so a reader asks one shape. No ninth vocabulary is added.

What it is not: who supports an assertion about evidence (``capture``, ``inference``, ``user``,
``external``) and what kind of world content a result is (memory, admitted source, authored,
simulation) are other axes (docs/world-memory-model.md, section 3.1), kept where they are and never
folded into this record.

Pure: no connection, no store.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.materials.workspace import PrivateLicenceRefused, refuse_private_licence

__all__ = [
    "ADAPTER_VERSION",
    "BY_KINDS",
    "CLASSES",
    "DISTRIBUTIONS",
    "ORIGIN_PROFILE",
    "OWN_WORK",
    "Origin",
    "OriginRefused",
    "read_origin",
]

ORIGIN_PROFILE: Final = "exulanica.origin/v1"
#: How a piece came to exist here.
CLASSES: Final = ("authored", "drafted", "generated", "uploaded", "imported", "crossed")
#: Who or what made it: this project, a person's account, a model, or an outside program.
BY_KINDS: Final = ("project", "account", "model", "program")
#: Where it may be shown: anywhere this product is, only in its own workspace, or never in a
#: public artefact.
DISTRIBUTIONS: Final = ("public", "private", "restricted")
#: The licence a person's own work carries, which no SPDX list names: theirs, used in their
#: workspace only.
OWN_WORK: Final = "LicenseRef-Exulanica-Own-Work"
_SPDX_EXPRESSION: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9.+-]*( (AND|OR|WITH) [A-Za-z0-9][A-Za-z0-9.+-]*)*"
)
_VERDICTS: Final = ("SHIP", "SHIP-ATTRIB", "USE-ONLY", "SEGREGATE", "CONDITIONAL")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: An outside program's adapter version, as a decision receipt records it: whole numbers joined by
#: dots, so no name can ride in it (``exulanica.world.deciders.ADAPTER_VERSION``, which a test holds
#: equal; this package may not import the world).
ADAPTER_VERSION: Final = re.compile(r"[0-9]{1,6}(\.[0-9]{1,6}){0,3}")
_DATE: Final = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]")
_TOP: Final = frozenset(
    {"profile", "class", "by", "sources", "licence", "authors", "lineage", "distribution"}
)
_LICENCE: Final = frozenset(
    {"spdx", "verdict", "attribution", "share_alike", "licence_url", "licence_text_sha256"}
)
_SOURCE: Final = frozenset({"reference", "retrieved_on", "revision", "licence_page_sha256"})
_LINEAGE: Final = frozenset({"ingredients", "receipts", "translation_manifest_sha256"})
_BY_FIELDS: Final = {
    "project": frozenset({"kind"}),
    "account": frozenset({"kind", "account_id"}),
    "model": frozenset(
        {
            "kind",
            "provider",
            "model_id",
            "prompt_version",
            "prompt_sha256",
            "words_sha256",
            "execution_sha256",
        }
    ),
    "program": frozenset({"kind", "bridge", "adapter_version", "mapping_sha256", "grant_id"}),
}
#: Which makers each class admits: a piece authored here was made by this project or a person; a
#: drafted or generated one by a model; an uploaded one by a person; an imported one by this
#: project (a reviewed import) or a person; a crossed one by the program it came through.
_CLASS_BY: Final = {
    "authored": ("project", "account"),
    "drafted": ("model",),
    "generated": ("model",),
    "uploaded": ("account",),
    "imported": ("project", "account"),
    "crossed": ("program",),
}


class OriginRefused(ValueError):
    """An origin record this code will not read, by the field at fault."""

    code: Final = "origin_invalid"


def _fail(where: str, message: str) -> OriginRefused:
    return OriginRefused(f"{where}: {message}")


def _text(where: str, value: object, maximum: int) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise _fail(where, "is non-empty text with no surrounding space")
    if len(value) > maximum or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in value):
        raise _fail(where, f"is one line of at most {maximum} characters")
    return value


def _hex(where: str, value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise _fail(where, "is a SHA-256 digest in lowercase hex")
    return value


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _fail(where, f"states exactly {sorted(keys)}")
    return value


@dataclass(frozen=True, slots=True)
class Origin:
    """A read origin record: the record as stated, and its class and licence for readers."""

    document: Mapping[str, Any]

    @property
    def klass(self) -> str:
        return str(self.document["class"])

    @property
    def spdx(self) -> str:
        return str(self.document["licence"]["spdx"])

    @property
    def share_alike(self) -> bool:
        return bool(self.document["licence"]["share_alike"])


def _by(where: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("kind") not in BY_KINDS:
        raise _fail(f"{where}.kind", f"is one of {list(BY_KINDS)}")
    by = _closed(where, value, _BY_FIELDS[str(value["kind"])])
    if by["kind"] == "account":
        _uuid(f"{where}.account_id", by["account_id"])
    if by["kind"] == "model":
        # A record made before this one may name its model only through its receipts: either
        # field is then none, never invented.
        if by["provider"] is not None:
            _text(f"{where}.provider", by["provider"], 64)
        if by["model_id"] is not None:
            _text(f"{where}.model_id", by["model_id"], 200)
        for key in ("prompt_version",):
            if by[key] is not None:
                _text(f"{where}.{key}", by[key], 64)
        for key in ("prompt_sha256", "words_sha256", "execution_sha256"):
            if by[key] is not None:
                _hex(f"{where}.{key}", by[key])
    if by["kind"] == "program":
        _text(f"{where}.bridge", by["bridge"], 32)
        version = by["adapter_version"]
        if type(version) is not str or ADAPTER_VERSION.fullmatch(version) is None:
            raise _fail(
                f"{where}.adapter_version", "is whole numbers joined by dots, such as 0.1.0"
            )
        _hex(f"{where}.mapping_sha256", by["mapping_sha256"])
        _uuid(f"{where}.grant_id", by["grant_id"])
    return by


def _uuid(where: str, value: object) -> None:
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError(value)
    except ValueError as exc:
        raise _fail(where, "is a UUID in its canonical lowercase text") from exc


def _licence(where: str, value: object) -> Mapping[str, Any]:
    licence = _closed(where, value, _LICENCE)
    spdx = licence["spdx"]
    if type(spdx) is not str or _SPDX_EXPRESSION.fullmatch(spdx) is None:
        raise _fail(f"{where}.spdx", "is an SPDX expression or a LicenseRef- identifier")
    if licence["verdict"] not in _VERDICTS:
        raise _fail(f"{where}.verdict", f"is one of the licence matrix's {list(_VERDICTS)}")
    if type(licence["share_alike"]) is not bool:
        raise _fail(f"{where}.share_alike", "is true or false")
    attribution = licence["attribution"]
    if attribution is not None:
        _text(f"{where}.attribution", attribution, 400)
    if licence["verdict"] == "SHIP-ATTRIB" and attribution is None:
        raise _fail(where, "a licence asking for attribution states the attribution")
    if spdx == "CC0-1.0" and attribution is not None:
        raise _fail(where, "a CC0 dedication states no attribution")
    if licence["share_alike"] != ("-SA-" in f"{spdx}-"):
        raise _fail(where, "a share-alike licence, and only one, is marked share-alike")
    url = licence["licence_url"]
    if url is not None and (
        type(url) is not str or not url.startswith("https://") or len(url) > 400
    ):
        raise _fail(f"{where}.licence_url", "is an https address")
    if licence["licence_text_sha256"] is not None:
        _hex(f"{where}.licence_text_sha256", licence["licence_text_sha256"])
    return licence


def read_origin(raw: object, *, where: str = "origin") -> Origin:
    """``raw`` as an origin record, every field checked, or :class:`OriginRefused`."""
    record = _closed(where, raw, _TOP)
    if record["profile"] != ORIGIN_PROFILE:
        raise _fail(f"{where}.profile", f"is {ORIGIN_PROFILE}")
    klass = record["class"]
    if klass not in CLASSES:
        raise _fail(f"{where}.class", f"is one of {list(CLASSES)}")
    by = _by(f"{where}.by", record["by"])
    if by["kind"] not in _CLASS_BY[str(klass)]:
        raise _fail(f"{where}.by", f"a {klass} piece is made by {list(_CLASS_BY[str(klass)])}")
    sources = record["sources"]
    if not isinstance(sources, list) or len(sources) > 32:
        raise _fail(f"{where}.sources", "is a list of at most 32 sources")
    for index, raw_source in enumerate(sources):
        at = f"{where}.sources[{index}]"
        source = _closed(at, raw_source, _SOURCE)
        _text(f"{at}.reference", source["reference"], 400)
        if source["retrieved_on"] is not None and (
            type(source["retrieved_on"]) is not str
            or _DATE.fullmatch(source["retrieved_on"]) is None
        ):
            raise _fail(f"{at}.retrieved_on", "is a date, YYYY-MM-DD")
        if source["revision"] is not None:
            _text(f"{at}.revision", source["revision"], 128)
        if source["licence_page_sha256"] is not None:
            _hex(f"{at}.licence_page_sha256", source["licence_page_sha256"])
    if klass == "imported" and not sources:
        raise _fail(f"{where}.sources", "an imported piece names where it was taken from")
    _licence(f"{where}.licence", record["licence"])
    authors = record["authors"]
    if not isinstance(authors, list) or len(authors) > 16:
        raise _fail(f"{where}.authors", "is a list of at most 16 names as credited")
    for index, author in enumerate(authors):
        _text(f"{where}.authors[{index}]", author, 120)
    lineage = _closed(f"{where}.lineage", record["lineage"], _LINEAGE)
    for key in ("ingredients", "receipts"):
        values = lineage[key]
        if not isinstance(values, list) or len(values) > 512:
            raise _fail(f"{where}.lineage.{key}", "is a list of at most 512 digests")
        for index, value in enumerate(values):
            _hex(f"{where}.lineage.{key}[{index}]", value)
    if klass == "generated" and not lineage["receipts"]:
        raise _fail(f"{where}.lineage.receipts", "a generated piece names its receipts")
    manifest = lineage["translation_manifest_sha256"]
    if manifest is not None:
        _hex(f"{where}.lineage.translation_manifest_sha256", manifest)
    if klass == "crossed" and manifest is None:
        raise _fail(f"{where}.lineage", "a crossing names its translation manifest")
    if record["distribution"] not in DISTRIBUTIONS:
        raise _fail(f"{where}.distribution", f"is one of {list(DISTRIBUTIONS)}")
    if record["distribution"] == "public":
        if klass == "uploaded" or record["licence"]["spdx"] == OWN_WORK:
            raise _fail(f"{where}.distribution", "a person's upload is never public by its origin")
        try:
            refuse_private_licence(record["licence"]["spdx"], f"{where}.licence.spdx")
        except PrivateLicenceRefused as exc:
            raise _fail(f"{where}.distribution", str(exc)) from exc
    return Origin(MappingProxyType(dict(record)))

"""Character catalogs the host publishes, and how a saved look finds the one it is drawn from.

A publication is one canonical document of a profile this module knows, named by the SHA-256 of
its canonical JSON (migration 0131). The host publishes it with the administration command in
:mod:`exulanica.world.character_catalog_publication`; nothing a request sends ever does. Every
publication the host has not withdrawn is served: the newest revision of each catalog is its
**current** publication and older ones are **retained**, so a look saved over an older revision
keeps its catalog.

A saved look pins the exact family revision it was saved over (``family_sha256``). It is drawn
from the newest served publication that derives that exact family, and from nothing else: when no
served publication derives it, the look is unavailable, by name, with its history intact. A family
is never matched by its name or its id, and a look is never moved onto another family's defaults,
which would put a different person where the saved one stood.

Two kinds are known, each through a fixed adapter chosen by the document's profile, never by
anything a document or a request says about code:

* ``layered-people`` (:data:`LAYERED_PROFILE`): today's ``catalog.json`` and ``looks.json`` held
  together. Its families are derived by
  :func:`~exulanica.world.character_appearance.catalog_recipe_families`, unchanged, so every family
  digest a saved look already holds is the digest the first publication of that catalog derives.
* ``parametric-body`` (:data:`PARAMETRIC_PROFILE`): a family of declared body controls whose
  bodies are prepared per recipe (:mod:`exulanica.world.character_parametric`).
"""

from __future__ import annotations

import datetime
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.world.character_appearance import (
    CHARACTER_CATALOG_PROFILE,
    CHARACTER_LOOKS_PROFILE,
    CharacterFamily,
    catalog_recipe_families,
    document_sha256,
)

__all__ = [
    "KINDS",
    "LAYERED_PROFILE",
    "PARAMETRIC_PROFILE",
    "PROFILES",
    "CatalogPublication",
    "CatalogRegistry",
    "PublicationRefused",
    "ServedCatalogs",
    "layered_bundle",
    "publication_families",
    "read_publication_document",
]

#: A layered people catalog and its designed looks, held as one document.
LAYERED_PROFILE: Final = "exulanica.character-catalog-bundle/v1"
#: A family of declared body controls whose bodies are prepared per recipe.
PARAMETRIC_PROFILE: Final = "exulanica.parametric-character-catalog/v1"
#: The one place a profile is tied to a kind. Migration 0131 checks the same pairs.
PROFILES: Final[Mapping[str, str]] = {
    LAYERED_PROFILE: "layered-people",
    PARAMETRIC_PROFILE: "parametric-body",
}
KINDS: Final = tuple(sorted(set(PROFILES.values())))
_CATALOG_ID = r"^[a-z][a-z0-9.-]{0,99}$"


class PublicationRefused(ValueError):
    """A document is not a catalog this host can serve, and says why."""


@dataclass(frozen=True, slots=True)
class CatalogPublication:
    """One published catalog: its identity, its document and the families it derives."""

    catalog_sha256: str
    catalog_id: str
    profile: str
    kind: str
    revision: int
    document: Mapping[str, Any]
    families: tuple[CharacterFamily, ...]
    published_at: datetime.datetime | None = None

    @property
    def family_digests(self) -> frozenset[str]:
        return frozenset(family.sha256 for family in self.families)

    def pin(self) -> dict[str, Any]:
        """What a saved revision or a read names this publication by."""
        return {
            "catalog_sha256": self.catalog_sha256,
            "catalog_id": self.catalog_id,
            "revision": self.revision,
        }


def layered_bundle(catalog: Mapping[str, Any], looks: Mapping[str, Any]) -> dict[str, Any]:
    """The publication document of a layered catalog and its designed looks."""
    return {"profile": LAYERED_PROFILE, "catalog": dict(catalog), "looks": dict(looks)}


def _identity(document: Mapping[str, Any]) -> tuple[str, str, int]:
    """The profile, catalog id and revision a document declares, or a refusal naming the field."""
    profile = document.get("profile")
    if profile not in PROFILES:
        raise PublicationRefused(f"no reader for catalog profile {profile!r}")
    if profile == LAYERED_PROFILE:
        if set(document) != {"profile", "catalog", "looks"}:
            raise PublicationRefused("a layered catalog bundle holds exactly its catalog and looks")
        catalog, looks = document["catalog"], document["looks"]
        if not isinstance(catalog, Mapping) or catalog.get("profile") != CHARACTER_CATALOG_PROFILE:
            raise PublicationRefused("the bundle's catalog is not a character catalog v1")
        if not isinstance(looks, Mapping) or looks.get("profile") != CHARACTER_LOOKS_PROFILE:
            raise PublicationRefused("the bundle's looks are not character looks v1")
        catalog_id, revision = catalog.get("catalogId"), catalog.get("revision")
    else:
        catalog_id, revision = document.get("catalogId"), document.get("revision")
    if not isinstance(catalog_id, str) or re.fullmatch(_CATALOG_ID, catalog_id) is None:
        raise PublicationRefused("a catalog id is lowercase letters, digits, dots and hyphens")
    if type(revision) is not int or revision < 1:
        raise PublicationRefused("a catalog revision is a positive integer")
    return profile, catalog_id, revision


def publication_families(document: Mapping[str, Any]) -> tuple[CharacterFamily, ...]:
    """Every family a document derives, through the adapter its profile names."""
    profile, _catalog_id, _revision = _identity(document)
    try:
        if profile == LAYERED_PROFILE:
            return catalog_recipe_families(document["catalog"], document["looks"])
        from exulanica.world.character_parametric import parametric_recipe_families

        return parametric_recipe_families(document)
    except PublicationRefused:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationRefused(f"the catalog does not derive its families: {exc}") from exc


def read_publication_document(document: Mapping[str, Any]) -> CatalogPublication:
    """A document checked and derived as a publication would be, before anyone publishes it."""
    profile, catalog_id, revision = _identity(document)
    try:
        digest = document_sha256(document)
    except TypeError as exc:
        raise PublicationRefused(
            "a catalog is canonical JSON of integers and strings only"
        ) from exc
    return CatalogPublication(
        catalog_sha256=digest,
        catalog_id=catalog_id,
        profile=profile,
        kind=PROFILES[profile],
        revision=revision,
        document=document,
        families=publication_families(document),
    )


@dataclass(frozen=True, slots=True)
class ServedCatalogs:
    """Every publication the host serves at one moment, and the families they derive.

    Built per request from the registry, so a publication or withdrawal the host makes is served
    from the next request on, and two worlds can hold looks over two revisions at once.
    """

    publications: tuple[CatalogPublication, ...]
    withdrawn: frozenset[str] = frozenset()

    @property
    def families(self) -> dict[str, CharacterFamily]:
        """Every served family by its digest; one family derived by two revisions is one entry."""
        served: dict[str, CharacterFamily] = {}
        for publication in self.publications:
            for family in publication.families:
                served.setdefault(family.sha256, family)
        return served

    def serves(self, family_sha256: str) -> bool:
        return any(family_sha256 in p.family_digests for p in self.publications)

    def resolve(self, family_sha256: str) -> CatalogPublication | None:
        """The newest served publication deriving exactly this family, or None."""
        deriving = [p for p in self.publications if family_sha256 in p.family_digests]
        return max(deriving, key=lambda p: p.revision) if deriving else None

    def current(self) -> tuple[CatalogPublication, ...]:
        """The newest served revision of each catalog, by catalog id."""
        newest: dict[str, CatalogPublication] = {}
        for publication in self.publications:
            held = newest.get(publication.catalog_id)
            if held is None or publication.revision > held.revision:
                newest[publication.catalog_id] = publication
        return tuple(newest[catalog_id] for catalog_id in sorted(newest))

    def state(self, publication: CatalogPublication) -> str:
        current = {p.catalog_sha256 for p in self.current()}
        return "current" if publication.catalog_sha256 in current else "retained"

    def by_digest(self, catalog_sha256: str) -> CatalogPublication | None:
        return next((p for p in self.publications if p.catalog_sha256 == catalog_sha256), None)

    def listing(self) -> list[dict[str, Any]]:
        """The served publications as the catalog list read answers them, oldest catalog first."""
        rows = []
        for publication in sorted(self.publications, key=lambda p: (p.catalog_id, -p.revision)):
            rows.append(
                {
                    **publication.pin(),
                    "profile": publication.profile,
                    "kind": publication.kind,
                    "state": self.state(publication),
                    "published_at": publication.published_at,
                }
            )
        return rows


_SUMMARY = (
    "select p.catalog_sha256,p.catalog_id,p.profile,p.kind,p.revision,p.published_at,"
    "w.catalog_sha256 is not null as withdrawn "
    "from character_catalog_publication p "
    "left join character_catalog_withdrawal w using (catalog_sha256)"
)


class CatalogRegistry:
    """Reads publications through any connection and derives each document once per process.

    A publication is immutable, so what is derived from its document is kept by digest for the
    life of the process; which publications are served, and whether one was withdrawn, is read
    again on every call. A stored document whose canonical digest is not its key is not served:
    a row the schema holds is not believed until its bytes say what the key says.
    """

    def __init__(self) -> None:
        self._derived: dict[str, CatalogPublication] = {}
        self._corrupt: set[str] = set()
        self._lock = threading.Lock()

    def _derive(self, connection: psycopg.Connection, digests: Iterable[str]) -> None:
        missing = sorted(
            d for d in set(digests) if d not in self._derived and d not in self._corrupt
        )
        if not missing:
            return
        rows = connection.execute(
            "select catalog_sha256,catalog_id,profile,kind,revision,document,published_at "
            "from character_catalog_publication where catalog_sha256 = any(%s)",
            (missing,),
        ).fetchall()
        for row in rows:
            document = row["document"]
            try:
                if document_sha256(document) != row["catalog_sha256"]:
                    raise PublicationRefused("stored document digest disagrees with its key")
                derived = read_publication_document(document)
                if (derived.catalog_id, derived.profile, derived.kind, derived.revision) != (
                    row["catalog_id"],
                    row["profile"],
                    row["kind"],
                    row["revision"],
                ):
                    raise PublicationRefused("stored identity disagrees with its document")
            except (PublicationRefused, ValueError, TypeError):
                with self._lock:
                    self._corrupt.add(row["catalog_sha256"])
                continue
            with self._lock:
                self._derived[row["catalog_sha256"]] = CatalogPublication(
                    catalog_sha256=derived.catalog_sha256,
                    catalog_id=derived.catalog_id,
                    profile=derived.profile,
                    kind=derived.kind,
                    revision=derived.revision,
                    document=derived.document,
                    families=derived.families,
                    published_at=row["published_at"],
                )

    def served(self, connection: psycopg.Connection) -> ServedCatalogs:
        """Every publication not withdrawn, each with the families it derives."""
        rows = connection.execute(_SUMMARY).fetchall()
        live = [row for row in rows if not row["withdrawn"]]
        self._derive(connection, (row["catalog_sha256"] for row in live))
        publications = tuple(
            self._derived[row["catalog_sha256"]]
            for row in live
            if row["catalog_sha256"] in self._derived
        )
        withdrawn = frozenset(row["catalog_sha256"] for row in rows if row["withdrawn"])
        return ServedCatalogs(publications=publications, withdrawn=withdrawn)

    def document(
        self, connection: psycopg.Connection, catalog_sha256: str
    ) -> tuple[CatalogPublication | None, bool]:
        """One publication by digest and whether it was withdrawn; (None, False) when unknown."""
        row = connection.execute(
            _SUMMARY + " where p.catalog_sha256 = %s", (catalog_sha256,)
        ).fetchone()
        if row is None:
            return None, False
        self._derive(connection, (catalog_sha256,))
        return self._derived.get(catalog_sha256), bool(row["withdrawn"])

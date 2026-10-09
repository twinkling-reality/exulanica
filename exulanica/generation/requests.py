"""From an ask to piece requests: which pieces, in which look, and what they will cost.

An ask names thing kinds (shipped kind versions) and a look (a committed style pack version, by
its id, version and manifest digest). Each kind becomes one piece request
(``exulanica.generated-asset-request/v2``, :mod:`exulanica_pieces.records`) built from:

- the kind's own document through :func:`exulanica_pieces.recipes.recipe_for_kind` and the newest
  recipe catalog version, so a measured description, variant count or fill bar applies;
- the widest section a hand closes around, from the body plan catalog, for a kind a hand holds;
- the look's palette (its manifest's swatches) and the style words the piece style catalog states
  for its pack;
- the piece budgets file the style pack format reads.

The words a request carries come only from catalogs: a recipe's measured description, or the
kind's own look role. A person's own words are not taken here, so a request holds no text a person
typed. Every request is therefore catalog content (``cache_scope`` "catalog"): the same kind in the
same look version is the same request, made once and shared.

The estimate comes from the piece compute catalog: every request's first variant first, then the
rest, each item at its typical seconds, and the worst case at its bounding seconds, priced at the
listed rate; a cold session adds its measured start.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica_pieces.budgets import PieceBudgets, read_budgets
from exulanica_pieces.canonical import Refused, sha256_hex
from exulanica_pieces.compute import ComputeEntry, PieceCompute, load_compute
from exulanica_pieces.recipes import (
    OBJECT_ROUTE,
    PieceRecipes,
    load_recipe_versions,
    load_recipes,
    recipe_for_kind,
    recipe_words,
)
from exulanica_pieces.records import build_request, cache_scope, read_request
from exulanica_pieces.styles import PieceStyles, load_styles

from exulanica.things.catalogs import thing_catalogs
from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.world.style_pack_library import StylePackLibrary

__all__ = [
    "GPU_PROVIDER",
    "MAXIMUM_KINDS",
    "Estimate",
    "GenerationCatalogs",
    "LookReference",
    "PieceAskRefused",
    "PlannedRequest",
    "assert_catalog_words",
    "estimate",
    "generation_catalogs",
    "plan_requests",
]

#: The spending ledger's provider for GPU generation on Nebius AI Cloud (design-7, ruling D).
GPU_PROVIDER: Final = "nebius_ai_cloud_gpu"
#: What a person reads for each spending provider an estimate names: the service that runs the GPU.
PROVIDER_LABELS: Final = {GPU_PROVIDER: "Nebius AI Cloud"}
#: Kinds one ask may name: a world's things fill in a few at a time.
MAXIMUM_KINDS: Final = 16
_ROOT: Final = Path(__file__).resolve().parents[2]


class PieceAskRefused(ValueError):
    """An ask no piece request can be built from, with a code a problem body names."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class LookReference:
    """A committed style pack at one version, named by its manifest's digest."""

    pack_id: str
    version: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PlannedRequest:
    """One piece request built for one thing kind in one look."""

    kind_key: str
    kind_version: int
    kind_sha256: str
    look_role: str
    variants: int
    #: The request's canonical bytes and their digest.
    request: bytes
    request_sha256: str
    #: "catalog": the words are catalog content, so the piece is shared by every workspace.
    cache_scope: str


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a set of requests will take: items, seconds and dollars."""

    items: int
    #: Seconds from a warm session taking the requests to every request's first variant, and to
    #: every variant, at the typical seconds an item.
    first_seconds_warm: int
    all_seconds_warm: int
    #: The measured seconds before a session that is not running takes its first request.
    cold_start_seconds: int
    usd_typical: Decimal
    usd_worst_case: Decimal
    provider: str
    #: Where the item figures come from (``measured_runs`` with its counts), or ``fixed_table`` for
    #: an entry that does not say, so a page never states a typical figure as measured when it is
    #: not.
    basis: dict[str, Any] = field(default_factory=lambda: {"kind": "fixed_table"})

    def document(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "first_seconds_warm": self.first_seconds_warm,
            "all_seconds_warm": self.all_seconds_warm,
            "cold_start_seconds": self.cold_start_seconds,
            "usd_typical": str(self.usd_typical),
            "usd_worst_case": str(self.usd_worst_case),
            "provider": self.provider,
            "provider_label": PROVIDER_LABELS.get(self.provider, self.provider),
            "basis": dict(self.basis),
        }


@dataclass(frozen=True, slots=True)
class GenerationCatalogs:
    """The committed catalogs a request is built and priced from."""

    budgets: PieceBudgets
    recipes: PieceRecipes
    styles: PieceStyles
    compute: PieceCompute
    hand_section_mm: int
    #: Every committed recipe catalog version, so a request's recipe resolves in the one it names.
    recipe_versions: Mapping[int, PieceRecipes]


@cache
def generation_catalogs(repository: Path = _ROOT) -> GenerationCatalogs:
    """The catalogs this process reads, once."""
    sections = {
        socket.grip_section_mm_maximum
        for plan in thing_catalogs().plans.values()
        for socket in plan.sockets
        if socket.grip_section_mm_maximum is not None
    }
    if not sections:
        raise Refused("no body plan states the widest section a hand closes around")
    return GenerationCatalogs(
        budgets=read_budgets(repository),
        recipes=load_recipes(repository),
        styles=load_styles(repository),
        compute=load_compute(repository),
        # The narrowest hand any body plan states, so a held piece fits every hand.
        hand_section_mm=min(sections),
        recipe_versions=load_recipe_versions(repository),
    )


def _pack(look: LookReference, library: StylePackLibrary, styles: PieceStyles) -> dict[str, Any]:
    if not library.holds(look.pack_id, look.version, look.manifest_sha256):
        raise PieceAskRefused(
            "look_not_served",
            f"this server serves no {look.pack_id} version {look.version} with that digest",
        )
    style = styles.words.get(look.pack_id)
    if style is None:
        raise PieceAskRefused(
            "look_without_style_words", f"no piece is generated for {look.pack_id} yet"
        )
    served = library.content.get(look.manifest_sha256)
    if served is None:  # held by version and digest, so its bytes are served
        raise PieceAskRefused("look_not_served", f"{look.pack_id}'s manifest is not served")
    manifest = json.loads(served.data)
    return {
        "id": look.pack_id,
        "palette": [swatch["srgb8"] for swatch in manifest["palette"]["swatches"]],
        "sha256": look.manifest_sha256,
        "style": style,
        "version": look.version,
    }


def plan_requests(
    kinds: Sequence[tuple[str, int]],
    look: LookReference,
    *,
    library: StylePackLibrary,
    catalogs: GenerationCatalogs | None = None,
    shipped: Mapping[tuple[str, int], ThingKind] | None = None,
) -> list[PlannedRequest]:
    """One request per kind, in the order asked; refused whole when any kind cannot have one."""
    if not 1 <= len(kinds) <= MAXIMUM_KINDS:
        raise PieceAskRefused("too_many_kinds", f"an ask names 1 to {MAXIMUM_KINDS} thing kinds")
    if len(set(kinds)) != len(kinds):
        raise PieceAskRefused("kind_repeated", "an ask names each thing kind once")
    catalogs = catalogs or generation_catalogs()
    shipped = shipped if shipped is not None else shipped_thing_kinds()
    pack = _pack(look, library, catalogs.styles)
    planned = []
    for key, version in kinds:
        kind = shipped.get((key, version))
        if kind is None:
            raise PieceAskRefused("kind_unknown", f"no shipped thing kind {key} version {version}")
        try:
            recipe = recipe_for_kind(
                kind.document,
                kind.sha256,
                catalogs.recipes,
                section_mm_maximum=catalogs.hand_section_mm,
            )
            arguments = recipe.request_arguments()
            raw = build_request(
                pack=pack, route=OBJECT_ROUTE, budgets=catalogs.budgets, **arguments
            )
        except Refused as refused:
            raise PieceAskRefused("kind_without_piece", str(refused)) from refused
        request = read_request(raw, catalogs.budgets)
        planned.append(
            PlannedRequest(
                kind_key=key,
                kind_version=version,
                kind_sha256=kind.sha256,
                look_role=request["look_role"],
                variants=request["variants"],
                request=raw,
                request_sha256=sha256_hex(raw),
                cache_scope=cache_scope(
                    request, catalogs.recipes.words_of(request.get("recipe") or {})
                ),
            )
        )
    return planned


def assert_catalog_words(request: Mapping[str, Any], catalogs: GenerationCatalogs) -> None:
    """Refuse a request whose words are not the catalogs' own: its description, when it has one,
    is the words of the recipe entry it names, in the catalog version it names, and its style words
    are the piece style catalog's for its pack. So a stored request holds no text a person typed,
    whatever built it."""
    description = request.get("description")
    if description is not None:
        recipe = request.get("recipe")
        if recipe is None or recipe_words(recipe, catalogs.recipe_versions) != description:
            raise PieceAskRefused(
                "words_not_from_catalog", "a request's description is a recipe catalog's words"
            )
    pack = request["pack"]
    if catalogs.styles.words.get(pack["id"]) != pack["style"]:
        raise PieceAskRefused(
            "words_not_from_catalog", "a request's style words are the piece style catalog's"
        )


def estimate(planned: Sequence[PlannedRequest], compute: ComputeEntry) -> Estimate:
    """The time and money ``planned`` will take on ``compute``."""
    items = sum(request.variants for request in planned)
    return Estimate(
        items=items,
        first_seconds_warm=len(planned) * compute.item_seconds_typical,
        all_seconds_warm=items * compute.item_seconds_typical,
        cold_start_seconds=compute.cold_start_seconds,
        usd_typical=compute.typical_usd(items),
        usd_worst_case=compute.worst_case_usd(items),
        provider=compute.provider,
        basis={"kind": "fixed_table"} if compute.basis is None else compute.basis.document(),
    )

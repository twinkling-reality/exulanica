"""Grammar: a generated subject is a pure function of a seed, a version and a catalog.

**ADR-0008 is structural here.** This package sits below ``exulanica.evidence`` in the
exhaustive import-linter layer order and a forbidden contract names ``exulanica.evidence``,
``exulanica.store``, ``exulanica.db``, ``exulanica.ingest``, ``exulanica.identity`` and
``exulanica.selection``. It may import ``exulanica.canonical``, ``exulanica.errors`` and
``exulanica.env`` and nothing else in this repository. A generator that cannot construct a
citation cannot return one, however it is later changed by somebody who never read this
sentence.

That absence is what lets a generated world exist beside a remembered one without borrowing its
truth status. Seeded is not sampled: every value a grammar emits is recomputable, byte for byte,
from the seed, the grammar version and the catalog digest, so nothing here is a model output and
nothing here is an observation.

**A generator system, not a city generator.** The modules at this level are the generic
contract and know nothing about what any grammar makes: ``seed`` validates a seed, ``draw``
holds the one draw, ``parameters`` the closed schema and the cascade, ``records`` the canonical
form, ``contract`` the grammar, its stages and its receipt, ``registry`` the lookup, and
``catalogs`` the versioned, licensed vocabulary files, and ``textures`` the published texture
sets a vocabulary entry may pin. Grammars live under
``exulanica.grammar.grammars`` and nothing at this level imports them. The city is the first and
largest; the box exists to prove the contract carries something that is not architecture.

**What is not here yet.** No city stage generates anything; each emits ``not_implemented``. No
geometry and no vertices are produced by this package at all. See ``docs/grammar-package.md``.
"""

from __future__ import annotations

from exulanica.grammar.catalogs import Catalog, CatalogSchema, catalog_digest, load_catalog
from exulanica.grammar.contract import (
    ADMISSIBLE_USES,
    PLANE,
    DeclaredSemantics,
    Generation,
    Grammar,
    GrammarKey,
    GrammarReceipt,
    Stage,
    StageContext,
    StageEmission,
    UnimplementedStage,
    generate,
)
from exulanica.grammar.draw import DomainCursor, draw_integer
from exulanica.grammar.parameters import (
    CascadeBinding,
    ParameterCascade,
    ParameterSchema,
    ParameterSpec,
    ResolvedParameters,
)
from exulanica.grammar.registry import GrammarRegistry
from exulanica.grammar.seed import require_seed
from exulanica.grammar.textures import TextureSet, read_texture_manifest

__all__ = [
    "ADMISSIBLE_USES",
    "PLANE",
    "CascadeBinding",
    "Catalog",
    "CatalogSchema",
    "DeclaredSemantics",
    "DomainCursor",
    "Generation",
    "Grammar",
    "GrammarKey",
    "GrammarReceipt",
    "GrammarRegistry",
    "ParameterCascade",
    "ParameterSchema",
    "ParameterSpec",
    "ResolvedParameters",
    "Stage",
    "StageContext",
    "StageEmission",
    "TextureSet",
    "UnimplementedStage",
    "catalog_digest",
    "draw_integer",
    "generate",
    "load_catalog",
    "read_texture_manifest",
    "require_seed",
]

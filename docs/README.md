# Exulanica documentation

Developer documentation for world state, reconstruction, creation, API contracts, and
runtime capabilities. Start from the [product roadmap](product-direction.md) and
[development setup](development-setup.md). The generated [catalog](all-documents.md)
lists the living contracts, capability guides, and decision records.

## Start here

**Product.** [product-direction.md](product-direction.md) is the roadmap and delivery
order. [world-composition-contract.md](world-composition-contract.md) is the intended
world semantics: memories, permitted real-world selections, and authored variations
in one interactive world. [product-specification.md](product-specification.md)
sections 1 to 4 and 11 retain research-backed limits. Those pages are subordinate
to the roadmap.

**Use the product.** The [capability guides](#capability-guides) describe what exists
and what remains. [world-memory-package.md](world-memory-package.md) is the portable
package profile.

**Build or extend it.** [architecture-overview.md](architecture-overview.md) sections
1 to 3 for system shape. [model-and-service-selection.md](model-and-service-selection.md)
section 0 for the implemented model stack; sections 1 to 8 are historical rationale.
[domain-and-evidence-model.md](domain-and-evidence-model.md) sections 1 and 4 for the
evidence address and schema. [runtime-verification.md](runtime-verification.md) before
client code: it records platform behaviour that otherwise causes silent bugs.

**Decisions.** The [decision records](#decision-records) in number order, then
[license-matrix.md](license-matrix.md) for ship and do-not-ship verdicts.

## Capability guides

- [Scene reconstruction](capabilities/scene-reconstruction.md)
- [World creation](capabilities/world-creation.md)
- [Companion](capabilities/companion.md)
- [Simulation runtime](capabilities/simulation.md)
- [World API](capabilities/world-api.md)
- [World Memory Package](world-memory-package.md)

## Capability status

The ordinary World Memory Package profile is `exulanica-wmp-1.0`; the separate opt-in
training dataset profile is `exulanica-wmp-training-1.1`. Neither supplies the planned
simulation runtime. World Read serves scene and place bundles; World Write records
generation receipts. Authored object add, move, remove, undo, and alternate versions
have code and synthetic checks. General structural language editing and simulation
remain roadmap work. This status describes the current implementation separately from
the product experience in the root README.

## Contracts

These are the living specifications. Edit them when the system changes.

| Document | Role |
| --- | --- |
| [world-composition-contract.md](world-composition-contract.md) | Memories, imported geography, and authored variations |
| [world-objects-contract.md](world-objects-contract.md) | Alternate versions and authored objects |
| [world-memory-package.md](world-memory-package.md) | Portable signed world snapshot |
| [personal-admission.md](personal-admission.md) | `POST /intake` and screening |
| [privacy-consent-threat-model.md](privacy-consent-threat-model.md) | Consent, deletion, and threat model |
| [domain-and-evidence-model.md](domain-and-evidence-model.md) | Evidence address and schema |
| [architecture-overview.md](architecture-overview.md) | Modular monolith and deployment shape |
| [interaction-model.md](interaction-model.md) | Spatial and interaction design |
| [deployment.md](deployment.md) | Deployment topology |
| [evaluation-methodology.md](evaluation-methodology.md) | How measurements are defined |
| [evaluation-corpus-contract.md](evaluation-corpus-contract.md) | Private evaluation input boundary |
| [evaluation-harness.md](evaluation-harness.md) | Replay and archive commands |

Scene, Atlas, screening, and reconstruction wire contracts live at `docs/` root and
appear in the [catalog](all-documents.md).

## How documents are filed

Documents are filed by how they change over time.

| Directory | Contents | Later edits |
| --- | --- | --- |
| `docs/` | Living contracts and reference | Yes |
| `capabilities/` | Guides for people choosing to use the product | Yes |
| `adr/` | Numbered decisions with alternatives | Status may change; the number never does |
| `evaluation/` | Digest-bound evidence | Never |

**Where a new document goes**, first yes wins:

1. Machine-readable evidence with a digest? A script writes `evaluation/`. Do not
   hand-edit a record.
2. A numbered architectural decision? `adr/`, next free number, never reused.
3. Written for somebody choosing to use the product? `capabilities/`.
4. Otherwise it is a living contract or reference table at `docs/` root.

**`evaluation/` is immutable.** Records bind their predecessor and cited artifacts by
sha256. Correcting a path inside a record would change its digest and cascade through
the chain. A document named inside a record is pinned at that path. Measured
2026-09-12: 75 non-evaluation paths.
[tests/test_documentation_links.py](../tests/test_documentation_links.py) fails if a
pinned path disappears.

The [catalog](all-documents.md) is generated by `scripts/generate_docs_index.py`.
A test fails if it drifts. It lists living contracts, capability guides, and decision
records. It does not list evaluation artifacts.

## Decision records

`adr/` holds the decisions expensive enough to record with their alternatives. The
number is the identifier and is never reused.
[tests/test_documentation_links.py](../tests/test_documentation_links.py) fails if a
record is missing from this table.

| Record | Decision | Status |
| --- | --- | --- |
| [adr/0002-model-routing.md](adr/0002-model-routing.md) | NVIDIA text Nemotron as the reasoning core, with a non-NVIDIA vision sensor | ACCEPTED |
| [adr/0003-renderer-selection.md](adr/0003-renderer-selection.md) | Renderer bake-off, resolved on matched-resolution measurement. PlayCanvas wins on 1% low frame pacing and covers both reconstruction rungs natively | ACCEPTED: PlayCanvas |
| [adr/0004-exif-orientation-normalisation.md](adr/0004-exif-orientation-normalisation.md) | Normalise EXIF orientation once at ingest so every downstream stage works from upright pixels, and record that the transform happened | ACCEPTED |
| [adr/0005-unified-selection-model.md](adr/0005-unified-selection-model.md) | One Selection primitive across person, object, place, time and trip, reached from four equal entry points | ACCEPTED |
| [adr/0006-desktop-viewport-boundary.md](adr/0006-desktop-viewport-boundary.md) | Desktop/laptop-only Atlas with an explicit 60rem viewport boundary | ACCEPTED |
| [adr/0007-world-composition-and-customization.md](adr/0007-world-composition-and-customization.md) | Passive module/recipe catalogs, deterministic composition, stable provenance-bearing topology, and protected customization transactions | ACCEPTED; appearance backend implemented, structural editing open |
| [adr/0008-generated-geometry.md](adr/0008-generated-geometry.md) | Generatively completed geometry is refused from the reconstruction ladder, with the checklist that a later admission would have to satisfy | ACCEPTED: refused, with a stated path |
| [adr/0009-the-ladder-above-rung-3.md](adr/0009-the-ladder-above-rung-3.md) | A layered gate composes receipts into rungs 1 and 2, rung 2 no longer requires a splat, a model-derived scale never opens the query path, and a posed multi-view set is a rung 3 sub-state | ACCEPTED; production rung 3 implemented, rung 2 and rung 1 producers blocked on real measurements and compute |
| [adr/0010-opm-2.md](adr/0010-opm-2.md) | The point-map container evolves to version 2 with an authoritative section list, a 4-byte tags section, a declared alpha meaning, and placement kept outside the file | ACCEPTED and implemented |
| [adr/0011-exulanica-namespace.md](adr/0011-exulanica-namespace.md) | `exulanica` is the canonical backend package namespace, cut over in one release rather than aliased | ACCEPTED and implemented |
| [adr/0012-upright-display-space.md](adr/0012-upright-display-space.md) | A photograph's display space is its upright pixel space: all eight EXIF orientations are admitted, `img` regions carry `display.rotation = 0`, and `media_track.rotation` means "still to apply" | ACCEPTED; closes the section 9.1 orientation freeze blocker |
| [adr/0013-region-encoding.md](adr/0013-region-encoding.md) | The parts-per-million integer grid is the canonical region encoding, enforced by the schema rather than described in a comment | ACCEPTED; closes a section 9.1 ratification item |
| [adr/0014-digest-encodings.md](adr/0014-digest-encodings.md) | Lowercase hex, absent keys rather than nulls, no quote context in `text_anchor`, and the hash algorithm identified by `span_format_version`; ratified against an independent non-Python reader | ACCEPTED; closes a section 9.1 ratification item |
| [adr/0015-timebase-rounding.md](adr/0015-timebase-rounding.md) | `round_half_down` is ties toward zero and quantises measurements only; the tick-to-nanosecond conversion rounds up so the tick round trip is exact, corrected while it was still free | ACCEPTED; closes two section 9.1 items |
| [adr/0016-ocr-is-a-region.md](adr/0016-ocr-is-a-region.md) | Text read off a photograph is a `frame_region` span carrying an `ocr_text_is` assertion; `transcript_text` is reserved for time-anchored transcripts and refused on the image track | ACCEPTED; closes the last section 9.1 address blocker |
| [adr/0017-exact-recomputation.md](adr/0017-exact-recomputation.md) | Exact recomputation covers the deterministic stages only; a model-produced artifact is invalidated and removed, never regenerated identically, and the type refuses to let a model stage claim otherwise | ACCEPTED; narrows A-24 |
| [adr/0018-contextual-provisional-links.md](adr/0018-contextual-provisional-links.md) | Automatic identity proposals organize as explicit guesses, written from context alone | ACCEPTED |
| [adr/0019-offline-restore-tombstone-replay.md](adr/0019-offline-restore-tombstone-replay.md) | A declared offline restore replays every sealed tombstone before it serves or starts a worker | ACCEPTED for the local mechanism; production rehearsal OPEN |
| [adr/0020-manifest-gold-question-evaluation.md](adr/0020-manifest-gold-question-evaluation.md) | Gold answers are derived from the manifest before retrieval, and model and declared-plan measurements stay separate | ACCEPTED |
| [adr/0021-observed-recomputation-scope.md](adr/0021-observed-recomputation-scope.md) | Exactness belongs to observed content; the wider closure stays open | ACCEPTED |
| [adr/0022-withdrawal-at-evidence-serving.md](adr/0022-withdrawal-at-evidence-serving.md) | Every evidence entrypoint checks withdrawal before reading stored bytes | ACCEPTED |
| [adr/gsplat-training-and-recorded-rung.md](adr/gsplat-training-and-recorded-rung.md) | Gaussian optimization and the recorded scene rung are separate decisions, so a nonmetric scene can be trained honestly | ACCEPTED for implementation; unnumbered, deliberately |

## Current state

[runtime-verification.md](runtime-verification.md) overrides every other document on
conflict about executed platform behaviour. The evidence spine is implemented:
migration `exulanica/migrations/0001_spine.sql` and the `exulanica/evidence/` modules.
The browser renderer is PlayCanvas Engine 2.21.4
([adr/0003-renderer-selection.md](adr/0003-renderer-selection.md)). Delivery status
belongs in [product-direction.md](product-direction.md). Quote a suite count only with
a date and a commit, or do not quote one.

## Conventions

Every claim carries exactly one epistemic status:

- **VERIFIED** cites a primary source URL and the retrieval date, or the execution
  that produced a runtime fact.
- **DECISION** records a choice together with the rejected alternative.
- **ASSUMPTION** is unvalidated and names the experiment that would settle it.
- **OPEN** is unresolved and says what would resolve it.
- **CLOSED** names the ADR that settled it, the artefact that enforces it, and the
  test that fails when it is violated. A decision recorded only in prose is not CLOSED.
- **CORRECTED** marks a claim rewritten against what was built, naming the artefact
  and the test that forced the correction.

Two rules govern those statuses:

- Every consequential technical claim cites a primary source with a retrieval date.
- Agreement between sources is not evidence. Two summaries repeating an unverified
  claim leave it unverified until a primary source or an execution settles it.

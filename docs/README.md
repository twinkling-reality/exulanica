# Exulanica documentation

Exulanica is a persistent, programmable personal world model. Create from imagination, personal
media or permitted imports; inspect and reshape the world; populate it with synthetic life; and
build applications, simulations and experiments using its supported data and actions.
The [root README](../README.md) introduces the experience and preview setup.

## Start here

| Goal | Read |
| --- | --- |
| Understand the product and delivery order | [Product roadmap](product-direction.md) |
| Run the application or contribute code | [Development setup](development-setup.md) and [architecture overview](architecture-overview.md) |
| Understand world data and model boundaries | [Personal world model architecture](world-memory-model.md) and [composition contract](world-composition-contract.md) |
| Build against a world | [World API](capabilities/world-api.md), [developer client](capabilities/developer-client.md) and [World Memory Package](world-memory-package.md) |
| Find a supported feature | [Capability guides](#capability-guides) and their owning [contracts](#contracts) |

The **Companion** is the person's AI partner within the world, helping with exploration, creation
and understanding events. Its [guide](capabilities/companion.md) separates that role from the
implemented tools. Synthetic inhabitants have their own state and behavior, described in the
[society contract](synthetic-society-contract.md).

Living contracts define supported behavior. The [product roadmap](product-direction.md) owns
scope and priorities; the [catalog](all-documents.md) inventories public documents. The
[product research archive](product-specification.md) preserves research constraints, and the
[engineering archive](frontier-roadmap.md) retains earlier dependencies. Neither archive is a
second product specification.

For engineering work, consult [model selection](model-and-service-selection.md) for implemented
callers and evaluation evidence, [domain and evidence](domain-and-evidence-model.md) for schema
and source addresses, [runtime verification](runtime-verification.md) for executed platform
behavior, and [security](security-floor.md) for the permission vocabulary. Reusable models and
assets also follow the [license matrix](license-matrix.md).

## Capability guides

Written for somebody choosing to use the product. Implementation limits belong in the guide and
in the matching contract, not in a brief.

- [Scene reconstruction](capabilities/scene-reconstruction.md)
- [World creation](capabilities/world-creation.md)
- [Companion](capabilities/companion.md)
- [Simulation runtime](capabilities/simulation.md)
- [World API](capabilities/world-api.md)
- [Developer client](capabilities/developer-client.md)

## Capability boundaries

The capability guides and living contracts describe implemented operations and material limits.
Scoped [evaluation records](evaluation/) identify what each execution demonstrated. A fixture or
local test establishes its stated mechanics; it does not establish deployment, visual quality or
the full product journey. A signed package is a partial, capability-declared snapshot, not proof
that another application can run every behavior.

## Contracts

These are the living specifications. Edit them when the system changes. The table is the spine,
not a claim that every other root document is secondary law.

| Document | Role |
| --- | --- |
| [world-memory-model.md](world-memory-model.md) | Personal world model architecture and research program |
| [world-composition-contract.md](world-composition-contract.md) | Personal media, permitted imports and authored worlds |
| [world-objects-contract.md](world-objects-contract.md) | Alternate versions and authored objects |
| [saved-world-entry.md](saved-world-entry.md) | Durable personal-world selection and exact version reopening |
| [world-memory-package.md](world-memory-package.md) | Portable signed world snapshot |
| [owned-district-and-admission.md](owned-district-and-admission.md) | Licensed geographic source, interpretation, and renderer boundary |
| [synthetic-society-contract.md](synthetic-society-contract.md) | Synthetic identity, replay, retrieval, and representation limits |
| [society-experiments.md](society-experiments.md) | Controlled society definition, attempt, and compact result API |
| [character-representation-contract.md](character-representation-contract.md) | Shared human form, identity bindings, appearance and movement quality |
| [personal-admission.md](personal-admission.md) | `POST /intake` and screening |
| [privacy-consent-threat-model.md](privacy-consent-threat-model.md) | Consent, deletion, and threat model |
| [domain-and-evidence-model.md](domain-and-evidence-model.md) | Evidence address and schema |
| [architecture-overview.md](architecture-overview.md) | Modular monolith and deployment shape |
| [interaction-model.md](interaction-model.md) | Spatial and interaction design |
| [deployment.md](deployment.md) | Deployment topology |
| [evaluation-methodology.md](evaluation-methodology.md) | How measurements are defined |
| [evaluation-corpus-contract.md](evaluation-corpus-contract.md) | Private evaluation input boundary |
| [evaluation-harness.md](evaluation-harness.md) | Replay and archive commands |

## Subject map

The catalog lists every public document. This map groups the remaining living documents by
subject so a reader does not have to scan seventy titles. It does not add a filing taxonomy;
new documents still follow [Document filing](#document-filing).

| Subject | Documents |
| --- | --- |
| Atlas and appearance | [atlas-frontend-integration.md](atlas-frontend-integration.md), [atlas-reconstruction-inspection.md](atlas-reconstruction-inspection.md), [atlas-spatial-architecture.md](atlas-spatial-architecture.md), [atlas-visual-language.md](atlas-visual-language.md), [atlas-world-customization-contract.md](atlas-world-customization-contract.md), [world-style-backend.md](world-style-backend.md), [spatial-world-authority.md](spatial-world-authority.md) |
| Reconstruction and scenes | [scene-reconstruction-operations.md](scene-reconstruction-operations.md), [scene-segments.md](scene-segments.md), [scene-splat-publication.md](scene-splat-publication.md), [scene-placement-alignment.md](scene-placement-alignment.md), [gsplat-scene-jobs.md](gsplat-scene-jobs.md), [reconstruction-quality-gate.md](reconstruction-quality-gate.md), [reconstruction-findings.md](reconstruction-findings.md), [retained-reference-workflow.md](retained-reference-workflow.md), [capture-overlap-and-recovery-state.md](capture-overlap-and-recovery-state.md) |
| World Read wire | [world-read-posed-views.md](world-read-posed-views.md), [world-read-recipient-evidence.md](world-read-recipient-evidence.md), [asset-read-currency.md](asset-read-currency.md), [screening-currency.md](screening-currency.md) |
| Generated city | [grammar-package.md](grammar-package.md), [generated-corridor-street.md](generated-corridor-street.md), [generated-tile-runtime.md](generated-tile-runtime.md), [generated-appearance.md](generated-appearance.md), [texture-package.md](texture-package.md), [lettering.md](lettering.md), [corridor-navigation-artifacts.md](corridor-navigation-artifacts.md), [traffic-contract.md](traffic-contract.md) |
| Visual gate | [visual-gate-targets.md](visual-gate-targets.md), [visual-gate-rubric.md](visual-gate-rubric.md), [visual-gate-corridor-walk.md](visual-gate-corridor-walk.md), [visual-gate-third-authentication-condition.md](visual-gate-third-authentication-condition.md) |
| Companion and people | [companion-question.md](companion-question.md), [person-presentation-consent.md](person-presentation-consent.md), [place-identity.md](place-identity.md), [world-variation-and-segments.md](world-variation-and-segments.md) |
| Interaction and streaming | [interaction-policy-backend.md](interaction-policy-backend.md), [physical-streaming-runtime.md](physical-streaming-runtime.md) |
| Operations and demo | [derivative-worker-operations.md](derivative-worker-operations.md), [demo-integrity.md](demo-integrity.md), [demo-runbook.md](demo-runbook.md), [platform-findings.md](platform-findings.md), [representation-decisions.md](representation-decisions.md) |

## Document filing

Documents are filed by how they change over time.

| Directory | Contents | Later edits |
| --- | --- | --- |
| `docs/` | Living contracts and reference | Yes |
| `capabilities/` | Guides for people choosing to use the product | Yes |
| `adr/` | Numbered decisions with alternatives | Status may change; the number never does |
| `evaluation/` | Digest-bound evidence | Never |

**Where a new document goes**, first yes wins:

1. Dispatch brief, handoff, procurement, or personal-run note? Write it under
   `.exulanica/briefs/` and do not `git add` it. Keep existing private note directories
   at their recorded paths. These notes are not part of the public reading
   surface. Public documents do not link to `docs/briefs/` as if a clone contained those files.
2. Machine-readable evidence with a digest? A script may write `evaluation/` on
   disk. Do not hand-edit a record. Do not `git add` a new campaign unless it
   belongs on the public catalog.
3. A numbered architectural decision? `adr/`, next free number, never reused.
4. Written for somebody choosing to use the product? `capabilities/`.
5. Otherwise it is a living contract or reference table at `docs/` root. Prefer editing an
   existing contract over adding another file.

**`evaluation/` is immutable.** Records bind their predecessor and cited artifacts by
sha256. Correcting a path inside a record would change its digest and cascade through
the chain. A document named inside a record is pinned at that path. Measured
2026-09-12: 75 non-evaluation paths.
[tests/test_documentation_links.py](../tests/test_documentation_links.py) fails if a
pinned path disappears.

The [catalog](all-documents.md) is generated by `scripts/generate_docs_index.py`.
A test fails if it drifts. It lists living contracts, capability guides, and decision
records. It does not list evaluation artifacts, briefs, records, or patches.

## Decision records

`adr/` holds rejected alternatives and the path a later change must supersede. It is not the
product spec and the numbers are not a reading order. A newcomer starts at the living contract.
The number is a stable identifier, never the name of the decision.

A record stays in this tree when the decision still constrains the system. Read one when you
need the alternatives or the admission checklist, not to learn what the product is.

| What it still governs | Read this first | Alternatives record |
| --- | --- | --- |
| Reconstruction does not invent unseen space | [product-specification.md](product-specification.md) section 5, [scene reconstruction](capabilities/scene-reconstruction.md) | [0008](adr/0008-generated-geometry.md) |
| How a reconstructed place earns a quality level | [product-specification.md](product-specification.md) section 5 | [0009](adr/0009-the-ladder-above-rung-3.md), [0010](adr/0010-opm-2.md), [gsplat](adr/gsplat-training-and-recorded-rung.md) |
| World memory is typed state, not one mesh | [world-memory-model.md](world-memory-model.md) | [0023](adr/0023-epistemically-typed-world-memory.md) |
| Atlas 3D renderer is PlayCanvas | [architecture-overview.md](architecture-overview.md) | [0003](adr/0003-renderer-selection.md) |
| Desktop Atlas only, 60rem boundary | [interaction-model.md](interaction-model.md) | [0006](adr/0006-desktop-viewport-boundary.md) |
| One Selection primitive | [interaction-model.md](interaction-model.md) | [0005](adr/0005-unified-selection-model.md) |
| Composition and appearance authority | [world-composition-contract.md](world-composition-contract.md) | [0007](adr/0007-world-composition-and-customization.md) |
| Evidence encoding, orientation, OCR, digests | [domain-and-evidence-model.md](domain-and-evidence-model.md) | [0004](adr/0004-exif-orientation-normalisation.md), [0012](adr/0012-upright-display-space.md), [0013](adr/0013-region-encoding.md), [0014](adr/0014-digest-encodings.md), [0015](adr/0015-timebase-rounding.md), [0016](adr/0016-ocr-is-a-region.md) |
| Exact recomputation and withdrawal | [domain-and-evidence-model.md](domain-and-evidence-model.md) | [0017](adr/0017-exact-recomputation.md), [0019](adr/0019-offline-restore-tombstone-replay.md), [0021](adr/0021-observed-recomputation-scope.md), [0022](adr/0022-withdrawal-at-evidence-serving.md) |
| Identity proposals stay guesses | [domain-and-evidence-model.md](domain-and-evidence-model.md) | [0018](adr/0018-contextual-provisional-links.md) |
| Model routing | [model-and-service-selection.md](model-and-service-selection.md) | [0002](adr/0002-model-routing.md) |
| Package namespace is `exulanica` | [world-memory-package.md](world-memory-package.md) | [0011](adr/0011-exulanica-namespace.md) |
| Coordinates are exact integers at a declared quantum | [representation-decisions.md](representation-decisions.md) | [0024](adr/0024-declared-coordinate-quantum.md) |
| A recessed doorway is a notch in the building | Not yet folded into a living contract; the record itself is the specification | [0025](adr/0025-a-doorway-is-a-notch-in-the-building.md) |
| Evaluation gold comes from the manifest | [evaluation-methodology.md](evaluation-methodology.md) | [0020](adr/0020-manifest-gold-question-evaluation.md) |

The numbered inventory below exists so every record stays findable.
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
| [adr/0023-epistemically-typed-world-memory.md](adr/0023-epistemically-typed-world-memory.md) | World memory is epistemically typed state; no mesh, graph, field, or latent representation is the whole world | ACCEPTED as architecture; research claims open |
| [adr/0024-declared-coordinate-quantum.md](adr/0024-declared-coordinate-quantum.md) | Coordinates are exact integers at a quantum a document declares and a reader refuses on mismatch | ACCEPTED |
| [adr/0025-a-doorway-is-a-notch-in-the-building.md](adr/0025-a-doorway-is-a-notch-in-the-building.md) | A recessed doorway is a notch in the building's footprint, so a person standing in one stands outside it | ACCEPTED |
| [adr/gsplat-training-and-recorded-rung.md](adr/gsplat-training-and-recorded-rung.md) | Gaussian optimization and the recorded scene rung are separate decisions, so a nonmetric scene can be trained honestly | ACCEPTED for implementation; unnumbered, deliberately |

## Runtime authority

[runtime-verification.md](runtime-verification.md) overrides every other document on
conflict about executed platform behaviour. The evidence spine is implemented:
migration `exulanica/migrations/0001_spine.sql` and the `exulanica/evidence/` modules.
The browser renderer is PlayCanvas Engine 2.21.4. The bake-off record is
[adr/0003-renderer-selection.md](adr/0003-renderer-selection.md). Delivery status
belongs in [product-direction.md](product-direction.md). Quote a suite count only with
a date and a commit, or do not quote one.

## Conventions

Prose follows [documentation-standard.md](documentation-standard.md): identify a
thing by what it is, not by when you looked at it.

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

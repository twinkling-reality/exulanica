# Exulanica documentation

The developer documentation covers world state, reconstruction, creation, API contracts, and
runtime capabilities. The [product roadmap](product-direction.md) records delivery milestones and
implementation status. [Development setup](development-setup.md) contains operating instructions.

## Capability guides

- [Scene reconstruction](capabilities/scene-reconstruction.md)
- [World creation](capabilities/world-creation.md)
- [Companion](capabilities/companion.md)
- [Simulation runtime](capabilities/simulation.md)
- [World API](capabilities/world-api.md)
- [World Memory Package](world-memory-package.md)

## Capability status

The ordinary World Memory Package profile is `exulanica-wmp-1.0`; the separate opt-in training
dataset profile is `exulanica-wmp-training-1.1`. Neither supplies the planned simulation runtime.
World Read serves scene/place
bundles; World Write records generation receipts. General object editing, alternate-world versions,
and simulation require the extensions in the roadmap. The application preview does not demonstrate
those extensions. This status describes the current implementation separately from the product
experience presented in the root README.

## Start here

**Evaluating the project.** Read [product-direction.md](product-direction.md) first, then [product-specification.md](product-specification.md) sections 1 to 4 for
what the product is and what the demonstration shows, then section 11 for the known limitations,
and then [runtime-verification.md](runtime-verification.md) for what the platform actually did when
it was called.

**Running or extending it.** [architecture-overview.md](architecture-overview.md) sections 1 to 3 for
system shape, the platform split and the deployment topology; then
[model-and-service-selection.md](model-and-service-selection.md) section 2 for the exact model
identifiers, their fallbacks and the routing rules; then
[domain-and-evidence-model.md](domain-and-evidence-model.md) sections 1 and 4 for the evidence
address and the schema the migration creates. Read
[runtime-verification.md](runtime-verification.md) before writing client code: it records the
platform behaviours that will otherwise cause silent bugs, including the reasoning-token floor on
every call and the one structured-output mechanism that is actually honoured.

**Reviewing the technology choices.** The [decision records](#decision-records) in number order, then
[model-and-service-selection.md](model-and-service-selection.md) for the model and service matrix,
[license-matrix.md](license-matrix.md) for ship and do-not-ship verdicts per component, and
[runtime-verification.md](runtime-verification.md) for the measurements that settled the open
questions in both.

## Documents

| Document | Contents | Status |
| --- | --- | --- |
| **Product** | | |
| [product-specification.md](product-specification.md) | What Exulanica is, the defining loop, the scoped MVP, the reconstruction fallback ladder, what is excluded, and the known limitations | Mixed, labelled per claim |
| [interaction-model.md](interaction-model.md) | Atlas and coordinate model, navigation and the two platform limits that force it, the two verbs, the Companion, update proposals and confirmation tiers, World Index and Atlas Map, recomposition, formation, accessibility | Mixed, labelled per claim |
| [frontier-roadmap.md](frontier-roadmap.md) | Exit-gated plan from source media through memory, reconstruction, protected adaptation, runtime publication, independent evaluation, and the signed World Memory Package | DECISION and IMPLEMENTATION PLAN |
| **Architecture** | | |
| [architecture-overview.md](architecture-overview.md) | System shape, platform split and deployment topology, storage and one consistency domain, object storage limits, query and answer safety, prompt injection posture, the 46 day uptime obligation | DECISION, with OPEN and ASSUMPTION items inline |
| [atlas-spatial-architecture.md](atlas-spatial-architecture.md) | Grounded memory archipelago, navigation, neighborhoods, residency, Map correspondence, and phased spatial roadmap | DECISION and ACTIVE IMPLEMENTATION |
| [atlas-visual-language.md](atlas-visual-language.md) | Aeroheart source-weather thesis, source aperture, continuity-field architecture, semantic visual dictionary, opening/encounter rules, removals, validation record, and focused-fixture limitations | DECISION and IMPLEMENTED for the focused slice |
| [atlas-world-research.md](atlas-world-research.md) | Procedural-world, persistence, wayfinding, streaming, accessibility, and customization research; repository measurements; prioritized gaps and acceptance gates | VERIFIED, DECISION, and ASSUMPTION, labelled |
| [atlas-world-customization-contract.md](atlas-world-customization-contract.md) | Protected topology, appearance and structural proposal lifecycles, profile compatibility, failures, safe fallbacks, and the production frontend handshake | DECISION; global frontend/backend lifecycle implemented |
| [atlas-frontend-integration.md](atlas-frontend-integration.md) | Atlas startup hydration, wire translation, transient review, stale recovery, history, conversational handoff, and authenticated source loading | IMPLEMENTED; external proposal service and regional renderer preview remain |
| [world-style-backend.md](world-style-backend.md) | Reviewed profile/capability registry, immutable style persistence, preview/apply/discard/rollback API, concurrency errors, provenance, and source-media states | IMPLEMENTED |
| [interaction-policy-backend.md](interaction-policy-backend.md) | Reviewed comfort/navigation/disclosure/initiative registry, immutable policy versions, shared Settings/Companion review lifecycle, rollback, recommendations, and evaluation boundary | IMPLEMENTED; real-participant evaluation not run |
| [physical-streaming-runtime.md](physical-streaming-runtime.md) | Cancel-safe physical residency, authenticated fetch and Range observation, pressure downgrade, neighborhood rebasing, context recovery, disposal, and the production measurement boundary | RENDERER CONTRACT IMPLEMENTED; real asset/hardware gate blocked |
| [derivative-worker-operations.md](derivative-worker-operations.md) | Production derivative-worker process, RLS role, leases, retries, reclaim, progress, metrics, replay, shutdown, and failure recovery | IMPLEMENTED and PostgreSQL-tested 2026-08-31 |
| [scene-reconstruction-operations.md](scene-reconstruction-operations.md) | Production multi-photograph selection, leases, pose and placement receipts, graph delivery, multi-map rendering, rung disclosure, deletion, scratch cleanup, and recovery | IMPLEMENTED and PostgreSQL/browser-tested 2026-09-04; real-corpus quality run blocked |
| [evaluation/2026-09-04-readiness-and-architecture-audit.json](evaluation/2026-09-04-readiness-and-architecture-audit.json) | The post-reconstruction readiness audit: confirmed architecture, the contradictions it found, the eight identity and evidence decisions it closed, what is still open, and the entry and exit gates for the four goals that follow | Retained, digest bound, checked by `tests/test_retained_evaluation_records.py` |
| [domain-and-evidence-model.md](domain-and-evidence-model.md) | The evidence address, the epistemic model, occurrence versus entity, schemas, idempotency, deletion and tombstones, the provenance ledger, the World Memory Package | DECISION, with CORRECTED and OPEN items inline |
| [model-and-service-selection.md](model-and-service-selection.md) | The model and service matrix with exact identifiers and declared fallbacks, the 2026-08-31 deprecation, the catalog type-field hazard, routing and cost discipline, and what may be claimed about model use | VERIFIED 2026-08-27, with OPEN items listed |
| [runtime-verification.md](runtime-verification.md) | What the platform does when called rather than when read about: the archived NVIDIA provenance record, measured image token costs, reasoning-token behaviour, which structured-output mechanism works, embedding width, and the resolved spend exposure | VERIFIED by execution 2026-08-27 |
| **Compliance and safety** | | |
| [privacy-consent-threat-model.md](privacy-consent-threat-model.md) | Legal landscape, architectural guards, consent schema, deletion cascade, honest disclosure copy, prompt injection, misuse boundaries | Mixed, labelled per claim |
| [license-matrix.md](license-matrix.md) | Ship and do-not-ship verdicts per component, the NVIDIA license distinction, accidental-violation traps, third party notice obligations | VERIFIED 2026-08-27, with OPEN items listed |
| **Evaluation** | | |
| [evaluation-methodology.md](evaluation-methodology.md) | Gold corpus adapted to a photograph corpus, metrics with their measurement procedures, the honesty constraint, learning evaluation, adversarial suite | DECISION and ASSUMPTION, labelled |
| [evaluation-corpus-contract.md](evaluation-corpus-contract.md) | Private OGC-1 bundle, immutable split, consent-index, blind-access, and local blocker contract | IMPLEMENTED INPUT BOUNDARY; REAL INPUTS BLOCKED |
| [evaluation-run-archive.md](evaluation-run-archive.md) | Write-once, digest-verifiable reports with exact repository, model, stage, migration, ledger, timing, cost, and reuse provenance | IMPLEMENTED; REAL REPLAY BLOCKED |
| [evaluation-clean-replay.md](evaluation-clean-replay.md) | New-database, non-owner, purpose-scoped two-pass corpus replay and gate receipt | REPLAY MECHANICS IMPLEMENTED; REAL BASELINE BLOCKED |
| **Project** | | |
| [demo-runbook.md](demo-runbook.md) | What can be demonstrated today and what cannot, audited against the build rather than against the plan, with the remaining gaps named | Mixed, buildability audited 2026-08-28 |
| [demo-integrity.md](demo-integrity.md) | What is pre-seeded versus computed live and the prohibitions that follow, the hosted topology and its per-visitor reset, unattended operation, the failure modes with a fallback for each, and the pre-demonstration checklist | Mixed, DECISION with OPEN items inline |
| [platform-findings.md](platform-findings.md) | Findings on Token Factory, AI Cloud, the NVIDIA models and Tavily, each carrying the execution or the primary source that evidences it, ending with a prioritised list | Mixed. Sections 1 to 3 executed 2026-08-27, section 4 documentation-verified 2026-08-28 |

### Decision records

`adr/` holds the decisions that were expensive enough to be worth recording with their alternatives
and their consequences, so that a later reader can tell a considered choice from an inherited default.

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

## Current state

A real call to `nvidia/Nemotron-3_5-Lightning` on Nebius Token Factory returned HTTP 200 with the
model identifier echoed in the response body, and a real Tavily search returned HTTP 200 with its
request payload retained as evidence of data minimisation. Both were executed on 2026-08-27 and are
recorded in [runtime-verification.md](runtime-verification.md), which overrides every other document
on conflict.

The evidence spine is implemented rather than only specified: migration
`exulanica/migrations/0001_spine.sql` and the `exulanica/evidence/` modules, with tests. Building it
found errors in the committed design, and those are corrected in place and marked **CORRECTED**
rather than left for the next reader to trip over. The suite is 1447 tests, 677 of which require a
live PostgreSQL instance and skip without one. All 1445 pass against the documented target,
PostgreSQL 18 with pgvector, with nothing substituted for either, so the SQL-level guarantees are
executed rather than described. The SQLite mirror the ingest path used to write is deleted:
there is one schema.

The browser renderer is decided: PlayCanvas Engine 2.21.4, on matched-resolution measurement
([adr/0003-renderer-selection.md](adr/0003-renderer-selection.md)).

## Conventions

Every claim in this documentation set carries exactly one epistemic status, and the status is part of
the claim:

- **VERIFIED** cites a primary source URL and the date it was retrieved, or, where the fact is about
  runtime behaviour, the execution that produced it.
- **DECISION** records a choice together with the alternative that was rejected and why.
- **ASSUMPTION** is unvalidated, and names the experiment that would settle it.
- **OPEN** is unresolved, and says what would resolve it.
- **CLOSED** marks an item that was OPEN and no longer is, naming the ADR that settled it, the
  artefact that enforces it, and the test that fails when it is violated. A decision recorded only
  in prose is not CLOSED.
- **CORRECTED** marks a claim rewritten against what was actually built, naming the artefact and the
  test that forced the correction.

Two rules govern how those statuses are assigned:

- Every consequential technical claim cites a primary source with a retrieval date.
- **Agreement between sources is not evidence.** Two summaries repeating an unverified claim leave it
  unverified, and it is marked as unverified until a primary source or an execution settles it.

Some documents reference stored artifacts that are not in this repository, such as archived API
responses. Those hold account-identifying response headers and, in places, personal media, so they
are deliberately not committed; where a field in one of them matters, the document quotes it.

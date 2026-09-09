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

## Where things live

Documents are filed by **how they change over time**, not by subject. A subject folder decays
because a document can belong to two subjects; "does this get edited later" has exactly one answer.

| Directory | What is in it | May it be edited later? |
| --- | --- | --- |
| `docs/` | Living contracts and reference tables | Yes, freely, as the system changes |
| `capabilities/` | Guides for somebody choosing to use it, not build it | Yes |
| `adr/` | Numbered decisions with their alternatives | Status may change; the number never does |
| `briefs/` | What was intended, written before the work | Only while the work is undispatched |
| `evaluation/` | Machine-written, digest-bound evidence | **Never.** See below |
| `artifacts/`, `patches/` | Images and patches that documents point at | Only by the document that owns them |

**Where a new document goes**, first yes wins:

1. Machine-readable evidence with a digest? `evaluation/`, and a script writes it, not you.
2. A numbered architectural decision? `adr/`, next free number, never reusing one.
3. A plan for work not yet done? `briefs/YYYY-MM-DD-slug.md`.
4. Would editing it in a month falsify an account of what happened on a date? It is a record. Do not
   edit it afterwards: append a dated `CORRECTED` note, or write a new document that cites it.
5. Written for somebody deciding whether to use the product rather than build it? `capabilities/`.
6. Otherwise it is a living contract or a reference table, and it belongs at `docs/` root.

The distinction step 4 turns on, and the one most easily got wrong: **a record is closed, a log is
open.** [engineering-log.md](engineering-log.md), [runtime-verification.md](runtime-verification.md),
[reconstruction-findings.md](reconstruction-findings.md) and
[platform-findings.md](platform-findings.md) are appended to and read as current evidence, so they
stay at root even though their content is dated.

### Two things that cannot move

**`evaluation/` is immutable.** Its records bind their predecessor and every artifact they cite by
sha256, so correcting a path inside one would change its digest, which the next record binds in
turn, cascading through the chain. There is no way to fix a record after the fact, which is the
point of it.

**A document named inside a record is pinned at that path.** Thirty-four documents are pinned this
way today: 19 at root, 14 decision records and one patch.
[tests/test_documentation_links.py](../tests/test_documentation_links.py) fails, naming the records
that would be stranded, if one of them moves. Moving such a document is not forbidden, but it is a
decision to leave a record permanently wrong, and the test makes you take it deliberately.

### The full inventory

[all-documents.md](all-documents.md) lists every document in the tree with a one-line summary. It is
generated by `scripts/generate_docs_index.py` and a test fails if it drifts, because the table this
section replaced was hand-maintained, covered 45 of 111 files, and never mentioned `briefs/` at all.

## Decision records

`adr/` holds the decisions expensive enough to be worth recording with their alternatives and their
consequences, so a later reader can tell a considered choice from an inherited default. The number
is the identifier: ADR-0010 is cited symbolically 85 times against 3 citations by filename, so a
number is never reused and never reassigned.
[tests/test_documentation_links.py](../tests/test_documentation_links.py) fails if a record is
missing from this table.

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

A real call to `nvidia/Nemotron-3_5-Lightning` on Nebius Token Factory returned HTTP 200 with the
model identifier echoed in the response body, and a real Tavily search returned HTTP 200 with its
request payload retained as evidence of data minimisation. Both were executed on 2026-08-27 and are
recorded in [runtime-verification.md](runtime-verification.md), which overrides every other document
on conflict.

The evidence spine is implemented rather than only specified: migration
`exulanica/migrations/0001_spine.sql` and the `exulanica/evidence/` modules, with tests. Building it
found errors in the committed design, and those are corrected in place and marked **CORRECTED**
rather than left for the next reader to trip over. MEASURED 2026-09-09 at `fd84627`, against the documented target of PostgreSQL 18 with pgvector
and nothing substituted for either: **2,200 passed, 14 failed, 4 skipped**. Every one of the
fourteen is a missing optional dependency in the plain environment rather than a defect, and
they are named in [reconstruction-throughput.md](reconstruction-throughput.md). The count in
this paragraph previously said 1,447 tests of which 1,445 passed, which was stale and
internally inconsistent. Quote a suite count with the date and the head it was measured at, or
do not quote one. The SQLite mirror the ingest path used to write is deleted:
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

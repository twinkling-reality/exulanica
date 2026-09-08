# Phase 10 tickets: the memory layer for world models

Status: **PLAN AND PROGRESS, 2026-09-06**. This turns [`frontier-roadmap.md`](frontier-roadmap.md)
Phase 10 into tickets in the first-week order that phase states. It is a plan, not a claim: a
ticket is done when its exit criteria have been executed and the evidence retained, and until then
its checkbox is empty no matter how much code exists.

Progress is recorded by ticking exit criteria, never by moving a ticket to a "done" heading. A
ticket with code and no ticked criteria has code and no result.

Phase 10's five capabilities are numbered in the roadmap. Ticket ids keep that numbering
(`P10-1-*` is capability 1) so a ticket can be read against the phase without a lookup table.

## How to read a ticket

Every ticket carries four things and nothing else:

- **What** it delivers, in one sentence that names the artifact, not the activity.
- **Why now**, meaning what it unblocks or what would be false without it.
- **Exit**, a list of conditions each of which is either executed or not. "Tested" is not an exit
  condition; "a request for a scene whose member lacks likeness consent returns that person masked,
  asserted by `tests/x.py::test_y`" is.
- **Files**, so two chats working in parallel can see a collision before they cause one.

A ticket with no executed exit is open. A ticket whose exit is executed against synthetic fixtures
says so in its exit line, because the difference between a passing fixture and a real capture is
where every defect in the 2026-09-05 reconstruction runs was found.

## Ownership

Three owners, and the split is by file, not by intent.

| Owner | Branch | Owns |
| --- | --- | --- |
| Memory-layer chat | `semantic-answers-and-memory-lifecycle` | P10-1, P10-2, P10-A (Atlas), P10-3 design, P10-I (infrastructure) |
| Privacy chat | `person-consent-masking` | P10-5 in full, and every file under "Reserved" below |
| Neither yet | | P10-4, and the parts of P10-3 that need a second real capture |

**Reserved for the privacy chat.** Do not edit these from the memory-layer branch:
`exulanica/consent/*`, `exulanica/graph/person_regions.py`, `exulanica/ingest/privacy.py`,
`exulanica/ingest/spine/privacy.py`, `exulanica/ingest/masking.py`,
`exulanica/ingest/masked_geometry.py`, `exulanica/ingest/masked_inputs.py`,
`exulanica/ingest/person_detectors.py`, `exulanica/ingest/person_receipts.py`,
`exulanica/ingest/stages/person_regions.py`, `exulanica/ingest/stages/masked_source.py`,
`exulanica/ingest/reference_admission.py`, `exulanica/api/routes/reconstruction_admission.py`,
`exulanica/db/session.py`, `web/packages/graph-client/src/person-presentation.ts`,
`exulanica/migrations/0037_a_person_is_hidden_until_they_consent.sql`, and the person tests
(`tests/test_person_*.py`, `tests/test_masked_*.py`).

**Shared, edit with care.** `exulanica/graph/payload.py`, `exulanica/graph/reconstruction_scenes.py`,
`exulanica/ingest/stages/__init__.py`, `web/packages/graph-client/src/wire.ts` and
`web/packages/graph-client/src/index.ts` are already modified on both branches. Additions here go at
the end of their model or interface, away from the person fields, so the merge is textual rather
than semantic.

**Merge state, checked 2026-09-06.** `git merge-tree --write-tree` against the privacy chat's
committed tip is clean, and both branches' required payload fields are satisfied at both
construction sites of `ReconstructionSceneRow` and `ReconstructionSceneMemberRow` (`_scene_row`
and `_fallback` in `reconstruction_scenes.py`), because both branches edited both.

It was not clean at first, and the fix is worth recording because the same thing will happen again.
Both branches inserted at the identical point in two files: into `buildStatus` right after the
registration paragraph in `web/packages/app/src/ui/status.ts`, and between the `GraphPayload` and
`IslandOf` exports in `web/packages/graph-client/src/index.ts`. Neither insertion cared where it
went. This branch moved both of its hunks away, with a comment at each saying why, and the trial
merge is clean. **In a shared file, put a new block somewhere the other branch is not, and say so
in a comment;** a conflict over an ordering nobody has an opinion about is pure cost.

Two things a clean trial merge still does not cover:

- The privacy worktree holds uncommitted work the trial merge cannot see, so this check is against
  its committed tip and will need repeating.
- `exulanica/graph/read_consent.py` detects the privacy layer by importing
  `exulanica.graph.person_regions`, so the merge flips `PERSON_CONSENT_AVAILABLE` on its own and
  `test_the_release_state_is_internal_only_until_person_consent_lands` fails by design. That
  failure is the handover: the release rule then has to be decided from the per-person receipts
  rather than inherited from the coarse screening receipt.

### The migration number, which is a hard constraint

`tests/test_migration.py::test_the_migrations_are_numbered_and_ordered` asserts the applied
versions are exactly `0001..N` with no gaps. `0037` exists only on `person-consent-masking`.
**A migration numbered `0038` on the memory-layer branch fails that test until `0037` merges**, so
the memory-layer tickets below are deliberately designed to need no migration at all. That is not a
workaround: adding a stage and an artifact kind has never needed SQL in this repository
(`scene_splat_training` and `scene_splat_delivery` were added across 28 files and zero migrations),
because `artifact.kind` and `stage_definition.stage_key` are unconstrained text guarded by the
`tg_pipeline_event_uses_registered_stage` trigger over the Python registry.

If a memory-layer ticket ever does need SQL, it waits for `0037` to merge and takes `0038`. It does
not renumber the privacy chat's file.

---

## P10-1 World Read API

Roadmap capability 1. The interface a generative world model conditions on.

### P10-1-a The bundle and its digest

**What.** `exulanica/graph/world_read.py` assembling one `WorldReadBundle` for one scene: the posed
views with their exact COLMAP calibration, the geometry references (point-map placements and, when
published, trained geometry) with their content digests and bearer hrefs, the region graph slice the
scene sits in, the recorded and displayed rung with their reasons, and the consent state of every
member. Canonically serialised through `exulanica.canonical` and carrying its own
`bundle_sha256` over that canonical form.

**Why now.** Every other Phase 10 capability is either a producer for this or a consumer of it. The
write API's conditioning digests are digests *of this bundle*; without it a generated artifact
cannot record what it was conditioned on, and the tier is unfalsifiable.

**Exit.**

- [x] A clean client recomputes `bundle_sha256` from the returned canonical bytes offline, with no
      database and no repository code, asserted by a test that reimplements the hash in the test
      file rather than calling the production function.
- [x] `exulanica.canonical.canonical_json` accepts the bundle, which means no float reaches the
      digest input. Focal lengths, principal points and transforms are encoded as fixed-precision
      decimal strings (`exulanica/graph/wire_numbers.py`, following the existing precedent in
      `exulanica/evaluation/synthetic_multiview.py`) rather than as quantised integers with a
      `_micro`/`_milli` suffix, which is what this criterion first said. Decimal strings were
      chosen because a transform has no natural unit to name; the precision is stated in the
      bundle's own `number_encoding`, and a value the grid cannot represent is refused rather than
      encoded.
- [x] Mutating one byte of any referenced artifact digest changes `bundle_sha256`.
- [x] The bundle names its own profile, `exulanica.world-read-bundle/v1`.
- [x] Nothing derived is presented as evidence: the bundle's geometry entries carry the rung that
      produced them and no `support_span_ids`, and a test asserts that no key named for evidence
      appears under a geometry entry.

**Files.** New: `exulanica/graph/world_read.py`, `tests/test_world_read_bundle.py`. Read-only use
of `exulanica/graph/reconstruction_scenes.py`, `exulanica/graph/scene_geometry.py`,
`exulanica/world/structure_repository.py`.

**Non-goals.** Addressing by place or by time. The roadmap's "for an entity, a place and a time"
needs the `place` entity from P10-3, which does not exist. v1 addresses a scene, which is a set of
photographs of one place at one capture, and the bundle says that is what it is.

### P10-1-b The authenticated route

**What.** `GET /world-read/scenes/{scene_id}`, on the read-only connection, returning the bundle.

**Why now.** A bundle no one can fetch proves nothing about workspace isolation, which is the
property a third party will ask about first.

**Exit.**

- [x] A bearer for workspace A requesting a scene in workspace B receives 404, not 403, matching the
      existing rule that the surface is not an existence oracle (`exulanica/api/app.py`, M10).
- [x] An unauthenticated request receives 401 and the route appears in the `routable_paths`
      authorisation sweep in `tests/test_api.py`.
- [x] A withdrawn scene returns 410 through the existing `tombstone_blocks_scene` path, not an empty
      bundle.
- [x] The route is registered in `create_app` and its `summary` states what it serves.

**Files.** New: `exulanica/api/routes/world_read.py`. Edit: `exulanica/api/app.py` (import and one
`include_router` line), `tests/test_api.py`.

### P10-1-c Honest release state

**What.** The bundle carries a `release` block naming the basis on which its consent state rests and
what that permits.

**Why now.** Phase 10 capability 5 says no third party sees an export before per-person consent
lands. Today the only gate is the coarse named-human screening receipt, which the 2026-09-05 bowl
run showed to be too coarse: the reviewer stated no visible people and the frames contain diners'
arms and hands at the edges. A bundle that omitted this would be the exact false claim the phase
exists to prevent.

**Exit.**

- [x] `release.state` is `internal_only` whenever the per-person consent layer is absent, and the
      bundle says which basis it used (`human-screening-receipt`) and what that basis does not
      establish.
- [x] A test asserts `internal_only` is what the current tree produces, so the day the privacy
      branch lands, that test fails and forces the value to be reconsidered rather than inherited.
      **It fired on 2026-09-07** when `person-consent-masking` merged, along with 36 other
      failures from one `NotImplementedError`. The decision it forced is below.

**Files.** `exulanica/graph/world_read.py`, `tests/test_world_read_bundle.py`.

### P10-1-c-2 The release state, decided against the per-person receipts

**Decided 2026-09-07, on the merged tree.** `release.state` stays `internal_only` for every scene.
That is a decision and not the old default, and the reason is a new one.

**Why not a more permissive state.** The bundle carries no state for any individual person.
`_view()` returns the camera, the exclusion reason and the capture's screening record, and nothing
per person; the member rows behind it carry `person_regions` and `person_review_state`, and the
bundle drops both. A recipient holding these bytes therefore cannot check a claim that the people
in these photographs agreed to anything. A release state whose own recipient cannot verify it is
the failure this bundle exists to prevent, and it does not become acceptable because the facts
exist somewhere else in the system.

**Why the answer is nevertheless computed.** `release_state()` now takes the per-capture consent
records the bundle publishes, and folds them. It reports how many photographs have been screened
for people, how many people are recorded across them, and which of the three consents from
`exulanica/consent/states.py` is unestablished and why. A scene nobody has screened and a scene
fully screened whose people the bundle cannot describe are different distances from a release, and
the single constant collapsed them.

**Why it does not read the clock, which was the trap.** `person_consent_is_granted` (migration
0037) filters on `clock_timestamp()` against `effective_at` and `valid_until`, so a person's
resolved state changes between two reads with no write in between. `release` is inside
`recorded_keys` and therefore inside both digests. **The recorded digest may not depend on the
clock**, so nothing in the release answer reads a resolved state: the two facts it does read,
whether a photograph has been screened and how many live regions it carries, are existence queries
with no time predicate. Note that
`test_two_reads_of_an_unchanged_scene_produce_the_same_digest` would NOT have caught a violation:
it compares two back-to-back in-process calls, and a consent expiring between them is not
something a test can arrange. The rule is kept by construction, not by that test.

**Why the answer is folded from the per-capture records and not from the scene row.** On the four
paths where `reconstruction_scenes._fallback` is reached, a member's `person_review_state` is
hard-set to `unscreened` whatever the database holds. A release answer folded over the members
would then contradict the `consent.per_capture` records printed beside it in the same bundle.
Folding the published records instead also means a recipient can recompute every count in
`release.people` from the bytes they hold, which is asserted by
`test_the_release_counts_are_recomputable_from_the_bundles_own_per_capture_records`.

**What was rejected, and why.**

- **A per-scene gradient with `releasable_masked`.** Blocked, and the block is now stated in the
  bundle under `release.not_yet_earnable` rather than in this document. The geometry entries carry
  the digest of the artifact produced, not of the source derivative read to produce it, so nothing
  in the bundle proves the geometry offered descends from the masked images.
- **A distinct `undecidable` state** for a scene with an unscreened member. Rejected as vocabulary
  inflation: it permits exactly what `internal_only` permits, and a state that changes no
  permission is one every consumer must learn for nothing. The decidability fact is carried in
  `release.scopes[*].reason` and `release.people` instead, where it does not have to be branched on.
- **Keeping `internal_only` unconditionally and deleting the raise.** Rejected: it would have left
  the value inherited rather than decided, and would not have removed the contradiction below.

**The second decision, made in the same change.** `person_consent_state()` answered a different
question from the per-capture records under one word. It said whether the *build* contained a
person layer; each capture said whether that *photograph* had a decision. On the merged tree the
first returned `available` while every capture under it said `unavailable`, so the bundle
contradicted itself. Both now describe photographs, in one vocabulary: `unscreened` (nobody has
looked) or `recorded` (people are located and carry receipts). Neither is ever "there is nobody
here", which is the statement the 2026-09-05 bowl screening made falsely and this layer exists to
retire. The scene-level answer is the weakest of its members.

**Exit.**

- [x] `release.state` is `internal_only` for every scene and says, per scene, which consent is
      unestablished and why, asserted by
      `tests/test_world_read_bundle.py::test_the_release_state_is_internal_only_while_no_person_state_reaches_the_bundle`.
- [x] The release counts are recomputable by a stranger from `consent.per_capture` in the same
      bundle, asserted by
      `test_the_release_counts_are_recomputable_from_the_bundles_own_per_capture_records`.
- [x] The scene-level and per-capture person answers speak one vocabulary and the scene fold is
      the restrictive one, asserted by
      `test_the_scene_consent_answer_is_the_weakest_of_its_photographs`. Its first version was
      killed by a surviving `all`-to-`any` mutant and strengthened with a mixed-state case.
- [x] Three executed negative controls, all killed:
      `the_release_state_is_internal_only_without_person_consent`,
      `an_unscreened_photograph_is_never_reported_as_one_with_decisions`, and
      `one_unscreened_photograph_makes_the_whole_scene_unscreened`
      (`docs/evaluation/2026-09-07-world-read-negative-controls.json`, 15 of 15 killed).
- [x] Re-recorded against the three retained real scenes:
      `docs/evaluation/2026-09-07-phase-10-read-paths.json`, bound by `predecessor_record` to the
      2026-09-06 record it follows.
- [x] The tripwire was moved forward rather than deleted. It now pins the ABSENCE of per-person
      state in the views, so the day somebody adds it, they must decide the gradient with the
      clock problem in front of them.

**Files.** `exulanica/graph/read_consent.py`, `exulanica/graph/world_read.py`,
`tests/test_world_read_bundle.py`, `tests/test_scene_observations.py`,
`scripts/verify_world_read_controls.py`, `scripts/record_world_read_evidence.py`.

---

## P10-2 World Write API and the generated tier

Roadmap capability 2. Content a world model imagines, stored below every recorded rung.

### P10-2-a The stage and the artifact kind

**What.** A `generated_scene` stage in the registry with output kind `generated_scene`,
`deterministic=False`, whose receipt records the generating model, its version, the prompt digest,
and the exact conditioning digests it received (the `bundle_sha256` of the P10-1 bundle plus the
digest of every artifact that bundle referenced).

**Why now.** It defines the product boundary. Without a tier below rung 4, a generative model's
output has nowhere to go but into the record.

**Exit.**

- [x] The stage is in `STAGES` and registers a `stage_definition` row, so a `pipeline_event` naming
      it is accepted by `tg_pipeline_event_uses_registered_stage`.
- [x] `deterministic=False`, and `docs/domain-and-evidence-model.md`'s list of
      non-exactly-recomputable stages names it, because `tests/test_exact_recomputation.py` derives
      that set from the registry and asserts the document matches. A generated artifact is
      **removed, not regenerated** on deletion, per ADR-0017.
- [x] The model identity, model version, prompt digest and conditioning digests are bound into the
      artifact's `input_digest`, so swapping the model produces a different artifact rather than
      silently reusing the old one. `generation_input_digest` covers the whole receipt document,
      not only its provenance: the narrower first version made two runs of one model collide, and
      the second run's bytes were discarded while its caller was handed a digest naming bytes
      nobody had stored (`tests/test_generated_tier.py::test_two_generations_for_one_scene_are_both_visible`).
      Asserted at the digest level by `test_a_model_swap_produces_a_different_artifact_identity`
      and at the artifact-id level by the two-generation test.
- [x] `model_role` is **not** set. `model_role` names a role the platform routes through its own
      reviewed model manifest, and a third-party world model supplied per request is not that.
      Setting it would also change `sorted(key for key, spec in STAGES.items() if spec.model_role)`,
      which `tests/test_unblocked_program_record.py` asserts against the digest-bound record
      `docs/evaluation/2026-09-05-unblocked-goal-d.json`. Amending a retained record to accommodate
      a new field would be the wrong direction of causation. The reason is recorded in the stage's
      own comment so a later reader does not "fix" it.

**Files.** Edit: `exulanica/ingest/stages/__init__.py` (append at the end of `STAGES`),
`docs/domain-and-evidence-model.md`. New: `exulanica/reconstruction/generated.py`,
`tests/test_generated_tier.py`.

**Scope note.** A generated artifact is scene-subject, because `artifact` requires exactly one
subject (`source_blob_sha256` xor `scene_id`) and generated content has no source blob. So v1
generates *around* an existing scene. Generating for a place with no scene at all needs a subject
that does not exist yet and is not in this ticket.

### P10-2-b `generated_geometry`, separate from recorded geometry

**What.** A `generated_geometry` field on the reconstruction scene payload, structurally distinct
from `trained_geometry`, carrying the model, version, prompt digest, conditioning digests and the
seam between generated and recorded.

**Exit.**

- [x] `generated_geometry` is a different field from `trained_geometry` in
      `exulanica/graph/payload.py` and in `web/packages/graph-client/src/wire.ts`, and no code path
      assigns one from the other.
- [ ] The scene status names the model and the seam, in the same sentence style as the display-frame
      disclosure.

**Files.** Edit: `exulanica/graph/payload.py`, `exulanica/graph/reconstruction_scenes.py`,
`web/packages/graph-client/src/wire.ts`, `web/packages/graph-client/src/read-model.ts`,
`web/packages/graph-client/src/snapshot.ts`. New: `exulanica/graph/generated_geometry.py`.

### P10-2-c A generated scene can never satisfy a gate

**What.** Tests and executed mutation controls establishing that generated content cannot promote a
rung, cannot be cited, and cannot enter a receipt chain.

**Why now.** This is the whole claim. Everything else in P10-2 is plumbing.

**Exit.**

- [x] `SceneReceipt.kind` remains `pose|placement|scale|coverage|corridor|splat`, so a generated
      artifact is structurally unable to enter `decide_scene_rung`. A test constructs a generated
      artifact and asserts the scene's rung is unchanged.
- [x] A generated artifact cannot become an assertion's support span, and the reason is structural
      rather than enforced: `evidence_span` references `blob`, and a generated artifact has no
      source blob at all, so there is no span that could name it.
      `test_a_generation_cannot_become_an_assertion_support_span` asserts that absence. It does not
      attempt the write, because there is nothing to attempt.
- [x] An executed mutation control per invariant, in `scripts/verify_world_read_controls.py`
      following the shape of `scripts/verify_gsplat_controls.py`: the mutant must be killed by a
      named test selector, the unmutated baseline must pass first, and the record is written
      digest-bound under `docs/evaluation/`. EXECUTED 2026-09-06: fourteen controls, fourteen
      killed, baseline and restored suite green
      (`docs/evaluation/2026-09-06-world-read-negative-controls.json`). One earlier control
      survived and was a correct result: it removed the supersession filter, which makes the read
      more permissive, and the test it named filed nothing superseded. It was replaced by the
      mutation that reinstates the original defect, plus a second control and a second test for
      supersession itself.

**Files.** New: `scripts/verify_generated_tier_controls.py`, `tests/test_generated_tier.py`.

---

## P10-A Atlas: showing the tier

Roadmap: "a proof lens (colour by tier), click-to-evidence, and the generated tier drawn under the
lens."

### P10-A-a Proof lens

**What.** A viewer mode colouring each region by what produced what it is looking at: photographed,
reconstructed, generated.

**Why now.** The read and write APIs make the tier a fact in the data. The lens is what makes a
person able to check it without reading JSON.

**Exit.**

- [x] Colour is decided in `@exulanica/presentation`, not inside `atlas-react`. `pnpm boundaries`
      passes, which is what enforces this. What crosses is `AtlasBinding.setProofLens`, taking one
      already-resolved RGBA per region; the binding indexes no palette and knows no tier.
- [x] The lens has a legend naming each tier in words, because a colour without a legend is a claim
      nobody can check. The status panel prints the tier label and its sentence per scene
      (`proofTierDisclosure`), and the lens section prints all four tiers with the swatch the
      renderer is actually given (`proofLensSwatch` reads the same palette row), which is also what
      a screen reader and a screenshot get.
- [x] **The 3D view is coloured.** EXECUTED 2026-09-06 against the retained real trained bowl in a
      headless browser at 1280x720
      (`docs/evaluation/2026-09-06-phase-10-atlas.json`, captures `lens-off`, `lens-on`,
      `lens-off-again`). Two delivery paths, because the flagship scene needed the second: the
      point-map shader takes a `uLens` vec4 written in the existing per-frame `uIsland` block, and
      trained Gaussian geometry takes the same four numbers through a per-component work-buffer
      modifier (`PROOF_LENS_SPLAT_MODIFIER`), which is the only hook that is genuinely per region
      under unified gsplat rendering. A lens wired to the point clouds alone would have shown
      nothing at all on the bowl, because `atlas-binding.ts` disables an island's point cloud for
      any scene whose trained geometry loaded.
- [x] A region whose scene is not drawn keeps its existing "Not drawn" disclosure under the lens
      rather than being coloured as though it were showing something. The retained run has exactly
      this case: the 40-photograph bowl scene is passed over for the 51-photograph trained one, and
      it reports `unavailable` while the drawn scene reports `reconstructed`.
- [x] Toggling the lens changes no scene, no rung and no receipt. There is a toggle now, so this is
      testable and tested: `web/packages/app/test/proof-lens-toggle.test.ts` toggles three times and
      asserts the scene records are unchanged by value, every rung disclosure's rendered markup is
      identical, and the switch's only outward effect is the callback. The visible half is in the
      retained captures: `lens-off-again` is a byte-identical encoded frame to `lens-off`.
- [x] The lens leaves a photograph alone, and says so. A region showing an original photograph is
      showing evidence, and tinting evidence would alter what is being offered as evidence, so the
      `photographed` tier is named in the legend and paints nothing. The legend states that in
      words rather than leaving the absence to be discovered.

**Files.** `web/packages/presentation/src/proof-lens.ts`, `web/packages/app/src/ui/proof-lens.ts`,
tests under `web/packages/presentation/test/` and `web/packages/app/test/`. Edited:
`web/packages/atlas-react/src/playcanvas/atlas-binding.ts` (the per-frame `uIsland` block, plus
`setProofLens`), `point-shader.ts`, `point-cloud.ts`, `scene-splats.ts`,
`web/packages/app/src/ui/status.ts`, `web/packages/app/src/main.ts`.

**Two findings the run produced that are not this ticket's to fix.**

- The work buffer behind trained Gaussian geometry has to be held open for about two and a half
  seconds after a lens change, not for one frame. `WORKBUFFER_UPDATE_ONCE` asks for a single refill
  and the tint took several seconds to appear or did not appear at all: this application runs with
  `autoRender` off, and installing the modifier rebuilds a shader whose link is deferred, so a
  single requested refill can run through the shader that has no lens in it and nothing asks again.
  `PROOF_LENS_SETTLE_SECONDS` is that window and it closes itself.
- MEASURED and reproduced on the unmodified tree at HEAD `104e415`: in a headless browser the
  representation pressure controller reaches level 3 about thirteen seconds after arrival, which
  caps the region's residency at its stub, and the trained scene stops being drawn until something
  forces it resident again. Opening the inspector does force it, which is why the retained captures
  include a second lens pair taken from a recovered camera. This is a pre-existing behaviour of the
  arrival path; nothing here fixed it and nothing here caused it.

### P10-A-b Click-to-evidence

**What.** Select a surface, and see the photographs whose cameras observed that point, with their
consent states.

**Why now.** It is the shortest path from a rendered pixel to the original bytes, which is the
product's whole epistemic claim made physical.

**Exit.**

- [x] The gesture lives in the **reconstruction inspector**, not in traverse mode. Traverse holds
      Pointer Lock, which freezes cursor coordinates
      (`web/packages/atlas-react/src/playcanvas/controls.ts`), and the focus solver's header states
      that it must never take a screen-space input. The inspector already exits pointer lock and
      already stands on a calibrated recovered camera, so a click there has real coordinates and a
      real projection.
- [x] The answer is **recorded provenance, not inference**: it comes from
      `quality.cameras[].sparse_observations` inside the pose receipt, whose rows are
      `[point id, source x, source y, world x, world y, world z, reprojection error, track length]`
      and whose `point id` is COLMAP's global `points3D` id shared across every image in the model.
- [x] The retained observation set is capped at 4096 per image, hash-ordered by point id
      (`exulanica/reconstruction/pose.py`). The UI therefore reports the point's full
      `track_length` beside the number of observations actually held, and says the held set is a
      bounded sample. A UI that showed "3 photographs" for a point with a track length of 40 would
      be lying by omission.
- [x] Clicking trained (SOG) geometry, which carries no per-splat provenance, resolves through the
      same sparse points and says that is what it did: the panel states that the point is the
      nearest one COLMAP recorded and not the surface under the pointer, and gives the pixel
      distance. It never reprojects into cameras and presents the result as though it were
      recorded observation; the photographs listed are the ones whose observations of that point
      the receipt holds. EXECUTED 2026-09-06 over the trained bowl.
- [x] Each listed observation carries the photograph's consent state, from the same seam the World
      Read bundle uses (`consent_for_captures`).
- [ ] A photograph whose person state forbids it is not offered. **Still open on 2026-09-07, and
      the reason changed.** The vocabulary now exists: an observation reports `person_consent`
      as `unscreened` or `recorded` rather than the flat `unavailable` it reported before the
      person layer merged, so a caller can tell a photograph nobody examined from one whose people
      are on file. What it still cannot do is filter, because no state for an individual person
      reaches an observation, and putting one there means putting a clock-dependent value inside a
      digest-bound answer. That is the same blocker P10-1-c-2 records, and it is one decision
      rather than two.
- [x] A new authenticated route serving pose-receipt observations, guarded by
      `tombstone_blocks_scene` (not `tombstone_blocks_capture`, which is the wrong reduction for a
      fact about N photographs) and `person_withdrawal_blocks_artifact`.

- [x] **The inspector listens for a click.** EXECUTED 2026-09-06 against the retained real trained
      bowl: a click at (599, 435) on a 1280x720 canvas resolved to sparse point 114 and listed the
      fifteen photographs the receipt holds for it, each with its consent state
      (`docs/evaluation/2026-09-06-phase-10-atlas.json`). The gesture is bound to the world canvas
      under the mount's own `AbortController` and guarded on the inspector being open, so traverse
      is untouched.
- [x] The pick is inverted through the RAW recovered camera from the graph snapshot, not the
      display-frame-composed one the renderer is given, because the observation graph's world
      coordinates are the recovered COLMAP frame and are composed with nothing. MEASURED
      2026-09-06: reprojecting every retained observation of the first photograph through that
      transform reproduces COLMAP's own recorded pixel to a median of 2.83 px and a maximum of
      9.88 px on a 3060x4080 original, which is the SIMPLE_RADIAL distortion the camera declares
      as `pinhole-approximation` and this projection does not apply.
- [x] A null pick is shown as an answer rather than swallowed, with the tolerance stated in both
      screen and source pixels. It is a common answer and not an edge case: at an eight-screen-pixel
      tolerance a grid of clicks over the retained scene resolved roughly a third of the time.
- [x] The gesture has a keyboard-reachable equivalent inside the inspector, because the world
      canvas carries `aria-hidden="true"` by deliberate decision and a gesture that exists only as
      a click on it exists only for sighted mouse users.

**Files.** New: `exulanica/graph/observations.py`, `exulanica/api/routes/world_read.py` (second
route), `web/packages/atlas-core/src/observation-pick.ts`,
`web/packages/app/src/observations-api.ts`, tests in both workspaces. Edited:
`web/packages/app/src/ui/reconstruction-inspector.ts`, `web/packages/app/src/main.ts`.

---

## P10-3 One place across captures and time

Roadmap capability 3, and experiment FR-2 made product.

**What.** Cross-scene alignment through shared sparse features links separate captures of one place
into a `place` entity versioned by capture time.

**Why now, partly.** It is what makes the memory persistent rather than a pile of scenes. But its
exit needs two consented captures of one real place weeks apart, and the repository has one real
place captured once. So this week delivers the design and the fixture, and the exit stays open.

**Exit.**

- [x] A design note `docs/place-identity.md`: the alignment method, what a `place` entity is, the
      forward migration, how Atlas merges regions and exposes time, and the refusal conditions.
- [x] A numeric test fixture: two synthetic captures of one synthetic place with a known ground-truth
      relative transform, so the aligner can be measured before real captures exist.
- [ ] **Open until real data.** Two consented captures of one real place, weeks apart, share one
      frame within a stated tolerance, and the world shows both versions in place. Not achievable
      this week and not claimed.

**Files.** New: `docs/place-identity.md`, `exulanica/reconstruction/place_alignment.py`,
`tests/test_place_alignment.py`. No `tests/fixtures/` additions: the fixture is generated in the
test module (one camera ring, transformed by a known similarity), not committed as data.

---

### P10-3-a The place plane, decided before it is written

**What.** The vocabulary decision recorded in `docs/place-identity.md`, "What a place is in the
schema": a place is a new durable plane of `place`, `place_version` and `place_alignment`, it is not
an `entity`, not a `region`, and not a column on `reconstruction_scene`.

**Why now.** It names a durable entity that the existing code will have to address, and three
things already mean something like it. Nothing downstream can start until the word resolves to one
table.

**Exit.**

- [x] The decision written down with what it rejected and why, in `docs/place-identity.md`.
- [x] Option C refuted against the live schema rather than on taste. MEASURED 2026-09-07:
      `tg_reconstruction_scene_append_only` permits exactly one UPDATE on `reconstruction_scene`,
      advancing `current_job_id` to a succeeded job, so setting a `place_id` on an existing scene
      row is refused by the database.
- [x] The `occurrence_class` collision closed by giving the two meanings two planes rather than one
      plane and a prohibition. The first draft refused an `entity` of class `'place'` outright and
      was wrong to: `exulanica/ingest/stages/vision.py:323-343` emits place occurrences and
      `exulanica/identity/decisions.py:107` copies an occurrence's class onto the entity a user
      names, so that entity is a live product path and the refusal would have deleted it.

**Files.** Edited: `docs/place-identity.md`, `docs/phase-10-tickets.md`.

---

### P10-3-b Migration 0038, the place plane

**What.** `place`, `place_version` and `place_alignment`, each under FORCE row-level security keyed
on `current_workspace()`, and a widened `an_artifact_names_one_subject` so an artifact may name a
place.

**Why now.** Every other part of capability 3 addresses a `place_id` that does not exist yet.

**Exit.**

- [x] Migration `0038` applied to the permitted test instance and the migration suite green.
      EXECUTED 2026-09-07: `tests/test_migration.py` 197 passed.
- [x] The workspace-keyed FORCE row-level security count updated in the three files that state it
      in prose, with `test_the_prose_count_of_workspace_isolated_tables_matches_the_schema` passing
      against the live schema rather than against a remembered number. MEASURED 2026-09-07: the
      count moved from 62 to 65, and the assertion caught the stale number before the update, which
      is the whole point of it being a measurement. A fourth stale number was found in the same
      pass: `tests/test_ingest_persistence.py` also said "keeps that 32 a measurement rather than a
      memory", a count nothing checks, and it now says "that number".
- [x] An `artifact` naming two subjects, or none, is refused, asserted by
      `tests/test_place_plane.py::test_an_artifact_naming_a_scene_and_a_place_is_refused` and
      `::test_an_artifact_naming_no_subject_at_all_is_refused`, with
      `::test_an_artifact_naming_only_a_place_is_accepted` so the pair cannot pass on a schema that
      refuses everything.
- [x] A `place_version` for a scene already in another place is refused, asserted by
      `tests/test_place_plane.py::test_a_scene_claimed_by_two_places_is_refused`.
- [x] A place with no anchor, and a place whose anchor's photographs were withdrawn, are both
      blocked, asserted by `tests/test_place_plane.py::test_a_place_with_no_anchor_is_blocked` and
      `::test_a_place_whose_anchor_capture_was_deleted_is_blocked`. The empty case fails closed.
- [x] `place` is probed for workspace isolation under a non-owner role, added to
      `tests/test_row_level_security.py::test_a_workspace_reads_its_own_rows_and_no_other_workspace_sees_them`.
      The owner-connected harness cannot prove isolation, because a superuser bypasses row-level
      security outright, and `tests/test_place_plane.py` says so where it asserts the catalog
      instead.
- [ ] Naming a place occurrence writes no `place` row, and accepting an alignment writes no
      `entity`, asserted by a test named for the failure it catches. This is the checkable form of
      "a label is not a measurement and geometry is not a name"; without it the two planes are a
      convention, and section 7 of the brief says a boundary nothing checks is not a boundary.
      **Open**: the second half needs the build, which is where an alignment is accepted.

**Files.** New: `exulanica/migrations/0038_a_place_is_more_than_one_capture.sql`, tests. Edited:
`exulanica/db/session.py`, `exulanica/ingest/spine/__init__.py`, `tests/test_ingest_persistence.py`
(the three prose counts only).

---

### P10-3-c The joint reconstruction build

**What.** One new stage whose subject is a pair of scenes, its artifact kind, its receipt, its
refusal path, and its own queue table, giving `exulanica/reconstruction/place_alignment.py` a
production caller.

**Why now.** `place_alignment.py` is measured against a synthetic fixture and called by nothing.
Until something calls it, the fitter is a module and not a capability.

**Exit.**

- [ ] A `place_alignment` stage in `STAGES`, with the resulting `pipeline_digest()` movement
      re-recorded rather than absorbed silently.
- [ ] The stage's correspondences are built from the two scenes' retained `pose_receipt` artifacts
      for `scene_xyz` and from the joint run for `joint_xyz`, never from a read-time join over
      receipts, which `docs/place-identity.md` establishes cannot work.
- [ ] Each of the three refusal reasons reachable and recorded as an outcome, asserted by tests
      named for the refusal they catch.
- [ ] The joint sparse model is not promoted to citable geometry; its digest is in the receipt.
- [ ] **Open until real data.** No real COLMAP joint run has happened. MEASURED 2026-09-07:
      `colmap` is not on this machine's PATH and is not installed through Homebrew, and the host is
      darwin with no CUDA, so the stage's real path is scripted here exactly as every other
      reconstruction stage's is.

**Files.** New: `exulanica/ingest/stages/place_alignment.py`, queue and worker files, tests.
Edited: `exulanica/ingest/stages/__init__.py`.

---

### P10-3-d The place read seam and the widened bundle

**What.** A graph read seam for places following `exulanica/graph/reconstruction_scenes.py`, and a
World Read bundle that addresses a place and a time.

**Why now.** The bundle currently carries a string telling every recipient that place addressing
does not exist. Deleting that string is the visible half of this capability.

**Exit.**

- [ ] `exulanica/graph/places.py` returns a place, its versions in capture order, and each
      version's transform with the receipt that measured it and how many alignments it was composed
      through.
- [ ] The bundle's `addressing` block accepts a place and a time, resolves to one version, and the
      scene address stays valid, because a scene is still a real thing after it joins a place.
- [ ] The `limitation` string is deleted, and every retained record whose digest covered it is
      re-recorded as a new dated record bound by `predecessor_record` to the one it follows.

**Files.** New: `exulanica/graph/places.py`. Edited: `exulanica/graph/world_read.py`,
`exulanica/api/routes/world_read.py`.

---

## P10-4 Persistent objects

Roadmap capability 4. Detections link into object entities across captures with user confirmation;
people are excluded from automatic linking and no biometric templates are computed.

**Deferred.** Not started this week, by the roadmap's own ordering. Recorded here so it is not
mistaken for finished. Its exit remains: an object named once is found in later captures with a
measured precision on a blind split, or the feature stays confirmation-only.

---

## P10-5 Consent on every read

Roadmap capability 5. **Owned by the privacy chat**, whose branch already carries the person region
and masked-source stages, the consent receipts, the state resolver, and the graph payload's
per-member `person_regions` and `person_review_state`.

The memory-layer branch's obligation is one seam, not an implementation:

**Exit for the memory-layer branch.**

- [x] `exulanica/graph/world_read.py` reads consent through one named function, so that when
      `person-consent-masking` merges, the change is that function's body and nothing else.
- [x] The stub is default-deny and says so: absent the privacy layer, the bundle reports
      `person_consent: unavailable` and `release.state: internal_only`. It never reports "no people"
      from the absence of a person layer, which is the exact confusion that made the 2026-09-05
      screening statement too coarse.
- [x] A test pins the stub's output so the merge cannot pass silently.

**Exit for the phase.** Held by the privacy chat: a request for a scene containing a person without
likeness consent receives that person masked, verified by test.

---

## P10-I Infrastructure, in parallel

**What.** A GPU dispatcher and an image registry, so a read of an unbuilt place can trigger its
build without an operator.

**Why now.** Every measurement in [`reference-gpu-compute.md`](reference-gpu-compute.md) says the
operator is the bottleneck: about 25 minutes and $0.45 of idle GPU per fresh host re-pulling a base
image that a private registry would serve, and a rented card that waited on a human to queue a job
and then picked up a stale one.

**Exit.**

- [ ] Both images pushed to a registry that survives instance deletion, so a fresh host skips the
      base pull and the gsplat compile. The measured saving is recorded, not estimated.
- [ ] Queue-and-claim in one step: the worker starts pinned to the job that was just queued, closing
      the `--once` drain hazard that consumed a job's final attempt on 2026-09-05.
- [ ] A spend cap is declared before the instance is created and the prepaid balance is read from
      the provider's billing page, not inferred from receipts. Per-job `usd_cost` is an upper bound
      whenever two jobs shared a card.

**Not this week** unless the read API needs a build to demonstrate against. Renting a card to prove
a dispatcher works is the wrong order.

---

## Explicitly cut

The roadmap names these; they are cut to make room and are not silently dropped:

- the volcanic collection (its point-map scene stands; it is not being retrained);
- a streamed Earth mode, kept as a later bridge view;
- viewer polish;
- metric scale, which needs independent physical validation and cannot come from any of this; and
- training any model of our own.

## Sequence

1. P10-1-a, P10-1-b, P10-1-c. The bundle, then the route, then the honest release state.
2. P10-2-a, P10-2-b, P10-2-c. The tier, then its separation in the payload, then the proof that it
   cannot promote anything.
3. P10-A-a, P10-A-b. The lens, then click-to-evidence.
4. P10-3 design and fixture, if the week allows.

P10-5's seam is written inside P10-1-a rather than after it, because a read API that has to be
retrofitted with a consent check is a read API that shipped without one.

---

## Phase 2, executed 2026-09-07 on the merged tree

Nine items, each scoped to a disjoint file set, each scoped and implemented and then checked by an
adversarial pass that was told to default to rejecting. Two were rejected and reworked; the
rejections are the useful part of this record and are written up where the work lives rather than
summarised away here.

| Item | Outcome |
| --- | --- |
| A withdrawn person's name reaches the browser | **Closed**, after the first fix closed one of four surfaces and was reported as complete. `docs/person-presentation-consent.md` |
| An unlocated person's mask is swallowed at cell (8,8) | **Closed in the pipeline, inert on the shipping detector.** One line in `person_detectors.py` remains, with a strict `xfail` armed for it |
| The bundle publishes a superseded receipt as eligible | **Closed.** 281 of 283 retained captures were affected |
| Migration numbers are first-come and unchecked | **Closed.** Enumeration refuses a duplicate version rather than forking the schema silently |
| The predecessor chain is enforced for two records by name | **Closed.** Every declared binding is checked, and the records that declare none are reported rather than failed |
| `verify_reference_controls.py` cannot run from a fresh clone | **Closed.** Its own 15-mutation run has NOT been re-executed since |
| The masked-geometry count is called by nothing | **Not wired.** Correctly refused: it needs a trained scene, and no test here runs real CUDA training. A nonfinite opacity is now refused rather than silently read as transparent |
| Consent receipts in the World Memory Package | **Not projected.** The regression guard for `exulanica-wmp-1.0` landed; the profile bump did not. A tripwire holds the blocker |
| Widen the `.exulanica` ignore rule | **Closed in both checkouts.** A working-tree edit in the main checkout cannot reach a linked worktree, which has its own file on its own branch |

**The decision this phase surfaced, taken the same day.** `record_human_screening` blocked any
screening naming a person in a masked state, which left the masking path with no honest route
through production. It now admits such a screening when every named masked region is one the
pipeline is already hiding AND the derivative is current under the key today's regions and
consents produce. Three cases are executed against a real database and each fails under a
different wrong rule, including the one this change first shipped; the reasoning and the table are
in `docs/person-presentation-consent.md`.

**What is still open after it.** Nothing puts person regions on the retained collections. The
production worker defaults its detector to `unavailable`, and the reviewer screen is imported by
nothing but its own test, so the two ways a region could arrive are both switched off. Until one
of them is wired, the screening rule change moves nothing on real data: it removes the blocker
rather than producing the regions. That is the next thing worth doing, and it is a wiring task
rather than a decision.

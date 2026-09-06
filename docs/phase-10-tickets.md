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
construction sites of `ReconstructionSceneRow` and `ReconstructionSceneMemberRow`
(`_scene_row` and `_fallback` in `reconstruction_scenes.py`), because both branches edited both.
Two things are not covered by that check:

- The privacy worktree holds uncommitted work, which the trial merge cannot see. Its
  `web/packages/app/src/ui/status.ts` inserts into `buildStatus` at the same point this branch's
  proof-tier line does. That hunk is the one place a human has to choose an order; everything else
  is textual.
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

**Files.** `exulanica/graph/world_read.py`, `tests/test_world_read_bundle.py`.

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
- [ ] An executed mutation control per invariant, in `scripts/verify_world_read_controls.py`
      following the shape of `scripts/verify_gsplat_controls.py`: the mutant must be killed by a
      named test selector, the unmutated baseline must pass first, and the record is written
      digest-bound under `docs/evaluation/`.

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
      passes, which is what enforces this. Nothing delivers it to the renderer yet; see the open
      criterion below.
- [x] The lens has a legend naming each tier in words, because a colour without a legend is a claim
      nobody can check. The status panel prints the tier label and its sentence per scene
      (`proofTierDisclosure`), which is also what a screen reader and a screenshot get.
- [ ] **The 3D view is not yet coloured.** The tier decision, its palette and its words exist and
      are tested; nothing writes the palette into the renderer's per-frame island uniform. Until
      that lands the lens is a sentence in the panel, not a colour in the world, and this ticket is
      open. The wiring point is the existing `visual.uIsland` write in `atlas-binding.ts`, and it
      cannot be covered by a test in this workspace: no test imports the engine, by the rule
      `atlas-react/test/opm.test.ts` states, so it needs the bake-off page or a real scene on
      screen.
- [x] A region whose scene is not drawn keeps its existing "Not drawn" disclosure under the lens
      rather than being coloured as though it were showing something.
- [ ] Toggling the lens changes no scene, no rung and no receipt. Untestable and unticked: there is
      no toggle. The tier line is always shown in the status panel, and `proofTierOf` is a pure
      function that writes no state at all, so there is nothing for such a test to assert on until
      a toggle exists.

**Files.** New: a lens module in `web/packages/presentation/src/`, tests under
`web/packages/presentation/test/` and `web/packages/app/test/`. Edit:
`web/packages/atlas-react/src/playcanvas/atlas-binding.ts` (the existing per-frame `uIsland`
uniform write), `web/packages/app/src/ui/status.ts`.

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
- [ ] Clicking trained (SOG) geometry, which carries no per-splat provenance, either resolves
      through the same sparse points or says it cannot. It never reprojects into cameras and
      presents the result as though it were recorded observation.
- [x] Each listed observation carries the photograph's consent state, from the same seam the World
      Read bundle uses (`consent_for_captures`).
- [ ] A photograph whose person state forbids it is not offered. Open, and it is P10-5's to close:
      no per-person state exists yet, so today every observation reports `person_consent:
      unavailable` and the caller has nothing to filter on.
- [x] A new authenticated route serving pose-receipt observations, guarded by
      `tombstone_blocks_scene` (not `tombstone_blocks_capture`, which is the wrong reduction for a
      fact about N photographs) and `person_withdrawal_blocks_artifact`.

- [ ] **The inspector does not yet listen for a click.** `pickObservedPoint` and
      `canvasToSourcePixel` are built and tested against a known camera, and
      `GET /world-read/scenes/{id}/observations` serves the recorded graph, but nothing in
      `reconstruction-inspector.ts` binds a pointer event to them or draws the result. Until that
      lands a visitor cannot click anything, and this ticket is open.

**Files.** New: `exulanica/graph/observations.py`, `exulanica/api/routes/world_read.py` (second
route), `web/packages/atlas-core/src/observation-pick.ts`, tests in both workspaces. Still to edit:
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

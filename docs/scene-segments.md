# Scene segments

Status: implemented 2026-09-11 on branch `codex/segments-backend`, backend half. The derivative
worker's environment switch for the segmenter (section 4) and the automatic lifts at publication
and after late masks (section 5) followed the same day. The frontend half (tinting, the segment
list, click resolution) is a separate task that consumes the wire shape in section 6.

The brief is [briefs/2026-09-11-scene-segments.md](briefs/2026-09-11-scene-segments.md). Recognition
used to stop at the photograph: the vision pass returns boxes, people get reviewed outlines, and
the only bridge from geometry to data was click-to-evidence. This carries what the photographs
found into the scene they reconstructed, as per-entity segments a renderer can tint and a click can
resolve to.

## 1. The two halves

| Half | Module | What it writes |
| --- | --- | --- |
| Per photograph | `exulanica/ingest/stages/segmentation.py`, stage `segmentation` | one `object_mask_list` artifact per photograph, one `frame_region` span and one `object_present` inference per mask |
| Per scene | `exulanica/ingest/scene_segments.py`, stage `scene_segments` | one `scene_segments` artifact per scene build, bound to everything it used |
| Read | `exulanica/graph/reconstruction_scenes.py`, route `GET /scene-segments/{scene_id}` | the segments this reader can stand behind right now, under the geometry asset-read policy |

## 2. No migration, and why

Object regions are carried as `frame_region` evidence spans without a schema change, with one
limit stated plainly.

* **The span is the mask's bounding rectangle.** Migration 0033's `evidence_span_region_shape`
  admits `kind = 'rect'` and nothing else, and [ADR-0013](adr/0013-region-encoding.md) keeps `kind`
  as the discriminator a polygon kind would be added under. A polygon ON the span would need a
  migration, a change to `exulanica/evidence/region.py`, new span-digest vectors and a change to
  graph-client's `EvidenceRegion`, none of which this work owns.
* **The polygon is in the stage's artifact**, as integer ppm vertices beside the digest of the span
  it belongs to, the same split [ADR-0016](adr/0016-ocr-is-a-region.md) makes for text: the pixels
  are the address and what was read off them is the value.
* **The assertion is `object_present`**, whose vocabulary entry is "a common noun for a thing in the
  frame, out of a detector's label set". The label is its object value, the segmenter's own score
  for the mask is its `raw_score`, and the model is named on the run's stage event (`model_ref`
  with provider `local`, repository, revision and licence, and `models_tried`), which is how the
  vision stage's assertions name theirs. A predicate carrying label, confidence, model and outline
  in one object value would need a migration; nothing here needed one.

`artifact.kind` is free text, and `stage_definition` rows are written by
`exulanica/ingest/spine/stage_registry.py`, so neither new artifact kind needed schema either.

## 3. Models

Pinned in the manifest's `local_models` and `local_roles` sections, beside the Token Factory
roles, by revision SHA with the licence read from the raw README frontmatter at that revision
(`docs/model-and-service-selection.md` section 2.3). `pipeline_version` moved from 2 to 3.

| Role | Checkpoint | Revision | Licence |
| --- | --- | --- | --- |
| `object_segmentation` | `facebook/sam2.1-hiera-tiny` | `de431c4043854a71d8101e17995dfe596bf101a5` | apache-2.0 |
| `open_vocabulary_detection` | `IDEA-Research/grounding-dino-tiny` | `a2bb814dd30d776dcf7e30523b00659f4f141c71` | apache-2.0 |
| fallback | `google/owlv2-base-patch16-ensemble` | `cfd3195ba4ea9592eec887ded089f4c08eff231d` | apache-2.0 |

* **The frontmatter is re-read before any weights load**, and a drift refuses. A revision is
  immutable, so this fails only when the manifest was edited by hand, which is the case it is for.
* **Grounding DINO carries a residual provenance caveat.** It was trained in part on Cap4M, whose
  terms IDEA-Research has not published; the manifest entry and
  [license-matrix.md](license-matrix.md) section 7 say so.
* **No torchvision.** transformers 5.17 imports it at module level in the SAM 2 image processor and
  the fast detector processors. The stage drives `Sam2Model` from the checkpoint's own
  `preprocessor_config.json` and uses the PIL processors for the detectors, so the `segmentation`
  extra in `pyproject.toml` needs no second platform-forked source beside torch's.
* **Local only, MPS with a CPU fallback.** MPS when the host has it and the CPU otherwise; a forward
  pass MPS refuses moves every loaded model to the CPU once, and the device string says so from
  then on (`cpu (fell back from mps: ...)`).
* **The fallback detector** runs when the primary cannot load or raises, and the artifact records
  which one ran.

Install with `uv sync --extra pose --extra reconstruction --extra segmentation`.

## 4. The stage

Runs last in `PhotoIngestPipeline._derivatives`, after depth, because it reads what the three
before it settled.

* **Prompts.** The hosted vision pass's located objects when it located any, otherwise Grounding
  DINO over the declared vocabulary in the stage parameters (thirty things, no stuff, no person
  term). Grounding DINO's own post-processor merges every token above threshold into one label
  (MEASURED: `'rock boulder cliff mountain hill'` for one box on the first volcanic photograph), so
  each vocabulary entry is scored over its own token span and a box takes the best one.
* **The person path is untouched.** The segmenter reads the masked derivative whenever anybody in
  the photograph is hidden, as depth does. People are never prompts. A detector label outside the
  vocabulary is not believed. A mask half or more inside any live person region is dropped, so an
  object outline cannot become a second, unreviewed outline of somebody.
* **Gated like the geometry it feeds.** It needs an eligible privacy screening. With none, or with a
  person-detection-only receipt, the stage is `unavailable` with the reason in the ledger rather
  than failing the run, which is deliberately softer than depth: a worker with a segmenter must
  not fail the pass that looks for people.
* **Keyed** on the intake probe, the masked derivative and consent digests when one was read, the
  hosted observation offered, and the segmenter's identity (checkpoints, revisions, licences,
  torch and transformers versions). Swapping a checkpoint re-segments; a rerun reuses.
* **Not bit-reproducible and declared so**, `deterministic = false`, with no `model_role`: the
  identity enters the input digest per photograph, the arrangement `person_regions` uses. The
  exact-recomputation sentence in [domain-and-evidence-model.md](domain-and-evidence-model.md)
  section 6 names it.

Wiring: `PhotoIngestPipeline(..., segmenter=...)` and `DerivativeWorker(..., segmenter=...)`. The
production derivative worker (`exulanica/ingest/worker_command.py`) builds a
`LocalObjectSegmenter` when `EXULANICA_SEGMENTATION_MODEL=local`, and none when the variable is
absent or `unavailable`, which is the default. `EXULANICA_SEGMENTATION_DEVICE` pins `mps`, `cuda` or
`cpu`; without it the segmenter picks MPS, then the CPU. There is no checkpoint or revision
override, because the checkpoints are the manifest's. A missing `segmentation` extra or a licence
drift is a startup failure. The segmenter is built there and nowhere else: that process already
holds torch for depth, and pycolmap and torch cannot share a process on macOS
(`exulanica/reconstruction/pycolmap_executor.py`), so the scene worker never loads one. A test
imports each worker command in a child process and holds that neither pulls in the other's
native runtime.

## 5. The lift

`publish_scene_segments(repository, store, scene_id)`, which runs at three moments.

* **As the scene publishes.** `SceneReconstructionProcessor` lifts right after the publication
  commit, in the scene worker's process and in the run that published the scene, beside the
  projection. It hands over the placement it has just validated (`ValidatedBuild`), and the lift
  uses it only when the scene's current build in the database has those exact receipts, so it does
  not validate the placement a second time; a test holds that the result is byte for byte what the
  command writes after validating the stored placement itself. The point maps are still checked
  live. A lift failure never takes the scene down, which is the projection's rule applied more
  widely: every exception is caught, not only the refusals a malformed receipt raises, because
  anything escaping after the commit would report a published scene as failed. The failure is
  `stage_failed` on `scene_segments` in that run, and a worker asked to stop records
  `stage_skipped` instead of lifting. When the build trained a delivery that was accepted, the
  lift also samples the accepted training output the delivery was compressed from, still in the
  job's scratch, and binds it as the Gaussian source: the PLY by digest and the delivery by its
  artifact digest. The trained Gaussians are one surface where the posed point maps are one
  guess per photograph, so these segments follow what a trained scene draws (section 8 says why
  that matters).
* **When masks complete after the build.** `scenes_due_segments` finds every published scene where
  every member of the current build has a live segmentation artifact and the newest segments are
  absent, unreadable, bound to another build or bound to other masks.
  `SceneReconstructionWorker.refresh_scene_segments` lifts each one in a `reprocess` run of its
  own. The scene worker command does this after a drain, at most every
  `--segments-refresh-seconds` (default 300, 0 turns it off), under `--once` as well, and never
  in a job-scoped worker. A scene is attempted once for each state it is due in, so a lift that
  fails the same way every time is not repeated on every pass. A scene whose newest segments of
  this build were lifted over trained Gaussians is reported as skipped rather than lifted: the
  accepted PLY is not retained, and lifting it from point maps alone would replace segments that
  follow the trained surface with ones that follow the per-photograph maps.
* **On demand**, from `python -m exulanica.ingest.scene_segments --workspace <uuid> --scene <uuid>`,
  which is also how a published trained scene is lifted over its Gaussians again: `--gaussian-ply`
  with a PLY decoded from the delivery, bound by `--gaussian-delivery-sha256`.

All three are numpy and nothing else, which is what lets the first two run in the pycolmap
process. All three skip a scene with nothing to lift, no object masks and no reviewed, shown
person, rather than write an empty artifact that would say somebody looked; the reader then says
`absent`, and the skip is `stage_skipped` in a caller's run or, from the command, no run at all.
A receipt, point map or mask that has gone is `stage_failed` and returned as a skip.

* **One projector.** The masked-geometry check's arithmetic, exposed from
  `exulanica/ingest/masked_geometry.py` as `camera_point`, `image_point` and `ppm_point`, which
  that check now calls itself one Gaussian at a time and the lift calls with arrays. Margin zero.
* **Samples.** Every placed member's point map, evenly subsampled to 1024 and carried into the scene
  frame by the placement's own transform, and optionally the centres of a trained Gaussian scene
  read by the check's own PLY reader (`--gaussian-ply`, bound by digest with the delivery it was
  decoded from).
* **Seen.** A sample counts as seen by a view when it projects in front of the camera, inside the
  frame, and not more than 15 per cent behind the surface that view's own placed point map records
  in that cell of a 96-cell grid.
* **Votes.** A sample joins an entity when at least 2 views put it inside one of that entity's
  regions and those are at least half of the views that saw it. A contested sample goes to the entity
  with more votes, and a tie goes to the person.
* **Entities.** A person is their subject, and only a region a human confirmed or drew, naming a
  subject whose state is `shown` (likeness granted, not withdrawn, not temporarily hidden), is
  lifted at all. An object is a label split into instances by union-find: samples in neighbouring
  cells of a grid two voxels coarse, or inside one mask in some view, are one instance. Space
  alone fragmented two sparse synthetic cubes into 29 pieces.
* **Voxels.** Occupied cells of a grid whose edge is the robust scene extent over 128, in
  millionths of a scene unit, so the artifact is integer-only canonical JSON.

The artifact binds the pose, placement and gate receipts, the member list, the placement's point
maps, the exact segmentation artifact of every member (and which members had none), every person
region by digest, and the Gaussian source. Every segment names the regions and point maps it rests
on, and its id is a digest over its kind, label, subject and voxels.

## 6. The read and the wire shape

`GET /scene-segments/{scene_id}`, `Cache-Control: private, no-store`, 404 for a scene outside the
caller's workspace. The response model is `SceneSegmentsView` in
`exulanica/api/routes/scene_segments.py`.

| `state` | Meaning |
| --- | --- |
| `available` | Bound to this build and every live check passed; `segments` is what may be drawn |
| `stale` | Bound to another build, unreadable, or a member's object masks changed since the lift; nothing served, `stale_inputs` says which |
| `absent` | Nothing has been lifted for this build |
| `unavailable` | The geometry asset-read policy denied the scene, or it has no current build; nothing served |

The reader withholds a single segment, counted in `withheld_segment_count`, when a point map it
rests on is purged, tombstone-blocked or missing its bytes, or when it is a person segment whose
region changed, whose subject changed, or who is no longer `shown`. The route then applies the
same policy the graph applies to geometry: `scene_inputs` and `scene_allowed` at the snapshot and
again under `final_check`, with `asset_artifact_live` for the segments artifact and every bound
segmentation artifact. A test checks the route against the graph's own answer for the same scene.

Each segment: `segment_id`, `kind` (`object` or `person`), `label` (objects only), `subject_id` and
`display_name` (persons only, the name only on a naming receipt), `voxel_count`, `voxels`
(`[i, j, k]` cells of `grid.voxel_size_microunits`), `bounds_microunits`, `centroid_microunits`,
`samples`, `votes` (`views`, `min`, `median`, `max`, `fraction_min_millionths`,
`fraction_median_millionths`), `regions` (capture, kind, the mask's `span_id` for click-to-evidence
or the person's `region_key`), and `occurrence_ids`, the occurrences behind hosted or local
detector masks, which are what the naming flow names.

`web/packages/graph-client/test/fixtures/scene-segments.json` is one complete served body, from the
synthetic scene in `tests/test_scene_segments.py` with one object and one reviewed, shown person.
It is stable once published: fields may be added, and no field may be renamed, retyped or removed.

## 7. Measured

On the volcanic scene, on a frozen copy of `exulanica_inspect_test` with a hardlinked copy of the
reference store, on an Apple M3 Pro with 18 GiB, MPS. The retained database and store were not
written. The digest-bound record is
[2026-09-11-scene-segments-backend.json](evaluation/2026-09-11-scene-segments-backend.json), with the
harness, the measurement, the mutation controls and both backend suite logs beside it under
`docs/evaluation/artifacts/2026-09-11-scene-segments-backend/`.

The subject turned out to be a volcanic rock photographed on a white turntable, 210 photographs of
it from around the turntable. The workspace carries no hosted vision observations on the copy, so
every photograph was prompted by Grounding DINO; the OWLv2 fallback was never needed.

| Per photograph, 210 photographs, 0 errors | Value |
| --- | --- |
| Masks | min 2, median 2, mean 2.37, max 5; 497 in all (142 photographs with 2, 61 with 3, 5 with 4, 2 with 5) |
| Labels | `boulder` 210, `plate` 181, `sign` 55, `table` 35, `statue` 7, `bridge` 4, `cup` 3, `bottle` 1, `umbrella` 1 |
| Dropped | 19 below the minimum area, 0 over a person (the set has no person regions) |
| Stage seconds, from the ledger | median 0.795, mean 0.814, p90 0.834, max 2.369 (the first photograph, which loaded Grounding DINO) |
| Wall seconds per photograph, including decoding the 12 MP original | median 0.891, mean 0.910 |
| SAM 2.1 load, weights cached | 1.6 s |

| The lift | Value |
| --- | --- |
| Cameras, samples | 210 recovered cameras; 215,040 point-map samples, 212,667 seen by at least one view, 35,428 assigned |
| Voxel edge | 24,834 millionths of a scene unit |
| `boulder` | 6,781 samples in 3,975 voxels, outlined in all 210 views; votes median 123, max 206; majority median 69.5 per cent |
| `plate` | 28,616 samples in 20,979 voxels, 179 views; votes median 7, max 110 |
| `table` | 26 samples in 20 voxels, 2 views, 2 votes each |
| Wall time | 48.6 s, most of it re-validating the placement against 210 point maps and a 107,742,795 byte pose receipt |
| Artifact | 551,491 bytes |
| Read | `available`, allowed at the snapshot and under the final lock, 0.45 s |

Two findings, both visible when the voxels are projected back into the photographs. The rock and
the turntable separate cleanly. But the turntable is one object under two labels, `plate` in 181
photographs and `table` in 35; labels are entity keys, so the lift keeps them apart, and the
majority rule leaves `table` a 26-sample fringe that cleared the thresholds by two votes of four. And
the `plate` segment carries a sparse spray of voxels past the turntable's far edge, most likely the
depth model's points along that silhouette. Neither is corrected here; both are in section 8.

## 8. Limitations and open decisions

* **The lift after a build waits for every member's masks.** Section 5 lifts a scene again only
  once every member of its build has a segmentation artifact, because a derivative worker segments
  one photograph at a time and lifting after each would lift a 210 member scene 210 times. Until
  then the reader calls the segments `stale` and serves none, and a scene whose segmentation never
  completes stays that way until the command is run for it.
* **Nothing re-lifts for people.** A person region reviewed after the lift is reported in the
  reader's `stale_inputs` while everything else is served; it reaches the scene at the next lift,
  from the sweep or the command.
* **Only publication lifts over Gaussians automatically.** The sweep has no PLY and leaves a
  trained scene whose masks changed to the command (below), and it reports that it did.
* **What the lift costs now.** MEASURED 2026-09-11 on the volcanic scene, loading what the scene
  worker hands the lift at publication from a frozen copy and timing `build_scene_segments` alone,
  with the peak taken from traced allocations (numpy's arrays included):

  | Build | Seconds | Peak |
  | --- | --- | --- |
  | Every placed point map held until the vote | 10.4 | 1,052 MiB |
  | Each view's occlusion grid built as its map is placed | 9.8 | 599 MiB |
  | Cameras read by `validated_receipt_cameras`, without the sparse observations | 5.4 | 126 MiB |

  The artifact was byte for byte the stored one every time. The 599 MiB was the pose receipt: its
  sparse observations are about 99.9 per cent of 107,742,795 bytes and the lift never reads them,
  and most of what remains is the text the parser decodes the receipt into. The light reader skips
  the receipt's digest checks, so the lift first holds the bytes to the digest its placement is
  bound to; building or validating that placement read the whole receipt. Placement validation,
  which publication skips, took 36 to 42 s of the command's run. None of this was measured inside a
  running scene worker.
* **The polygon is not on the span.** Section 2 says what that would cost.
* **Detector-prompted objects now have naming targets.** Segmentation writes an unnamed object
  occurrence only for a local-detector mask, using its bounding span. Hosted masks retain the
  hosted occurrence. The existing identity naming route creates the object entity, naming
  assertion and confirmed link only when the user confirms a name. The input contract re-keys
  older masks so a rerun supplies the missing occurrences. No identity or web change is needed.
* **Threshold evidence is tiny and provisional.** Section 9 scores three volcanic and three
  first-place photographs. The labels were traced by Codex, not reviewed by a human. These are
  tuning photographs, with no held-out set; no threshold is validated for general deployment.
  Thresholds remain stage parameters, so changing them re-keys.
* **The command and sweep read the validated projection.** They check its payload digest, all
  three receipt bindings, ordered members and point-map inputs before using its transforms. A
  missing, damaged or mismatched projection falls back to placement validation. Both paths still
  check point-map liveness and content digests. Publication keeps its already-validated build.
* **Gaussian centres need a decoded PLY after publication.** The trained delivery is SOG and no
  PLY is retained, so lifting a published trained scene again takes the decode the
  masked-geometry evaluation already performs. At publication the accepted training output is
  used instead, which differs from the delivery only by the delivery's quantisation.
* **Synonymous labels split one object** (`plate` and `table` above), and the segment floor of eight
  samples is low beside 215,040: a fringe segment clears it. Merging labels would need a
  vocabulary with synonyms or a cross-label association step; neither exists.
* **A person segment is written durably.** It carries a subject reference and never a name, it is
  re-checked on every read, and a scene tombstone reaches it as it reaches every scene artifact. A
  consent withdrawal withholds it at once; the bytes stay until the scene is rebuilt or purged.


## 9. Production follow-up, 2026-09-11

The production branch starts at `d13b01d`. The worker switch and publication hook, including the
late-mask sweep and their tests, already exist at that base. This follow-up supplies projection
reuse for later lifts and detector-only naming occurrences. The measurement record is
[2026-09-11-scene-segments-production.json](evaluation/2026-09-11-scene-segments-production.json),
with the backend record as predecessor. No migration, hosted inference, merge or push occurred.

The first comparison used the same three completed volcanic masks on both paths: 47.59 s with
placement validation, 4.49 s with projection reuse, byte-identical artifacts. Placement alone
fell from 43.026 s to 0.011 s. With 207 masks still missing that artifact contained zero segments;
the completed 210-mask comparison took **46.54 s before and 6.88 s after**, again with
byte-identical output, now containing three segments. Placement took 39.540 s versus 0.011 s.
These are single sequential wall-clock measurements, not latency percentiles or memory tests.

### Naming

A local detector mask gets one unnamed `object` occurrence standing on the mask's bounding span.
Its `prompt_span_digest` now names that backing occurrence span, just as it names a hosted
occurrence's box span for hosted masks. The existing graph reader and panel can therefore find
it without a wire-shape change. Segmentation creates no entity or confirmed link. The account
holder's confirmation through `POST /identity/name` creates the entity and records the name as a
user assertion. The hosted path does not create an additional segmentation occurrence.

### First-place and consent

The local stage ran on all three photographs of workspace
`9e69f7e8-2372-489b-8eb3-b71ea74c16b2` in `exulanica_inspect_test`. Each produced one cliff mask;
one additional mask in the close-up was dropped for person overlap. None of the retained masks
covered a pixel inside the manually traced people. Eleven reviewed regions, naming the four
consenting subjects, were offered to the real lift. It wrote zero segments in 0.025 s because
this scene has zero recovered cameras and zero placed maps. Consent does not supply geometry.

The accepted synthetic scene test proves the positive and negative cases: only a reviewed subject
with current presentation consent produces a person segment; withdrawal immediately withholds it
on read, and a new lift omits it from the durable artifact. This is **partial acceptance** of the
people requirement. No shared-scene person appearance was established for first-place, and no
per-photo coordinates were passed off as recovered shared geometry.

### Tiny threshold study

The annotation fixture records source digests and manual polygons, without photographs or faces.
The volcanic targets are the visible rock and turntable; the first-place targets are all eleven
visible people, including their clothing and held helmets. Other first-place objects are
unlabelled, so the person-overlap study does not establish object precision or recall there.
The six volcanic target-mask IoUs average 0.843: rocks 0.967, 0.949, 0.950; turntables 0.801,
0.524, 0.869. Matching is one-to-one at IoU at least 0.5. Labels such as rock/boulder and
plate/table are combined for scoring only; production still separates these labels.

| Parameter | Measured trade or remaining limit |
| --- | --- |
| Detector box threshold 300,000 | Six targets found with zero extra masks at 0.30 to 0.40. At 0.15 there are seven extras; at 0.50 four targets are lost. Retain 0.30 as the least restrictive measured optimum. |
| Duplicate box IoU 700,000 | 0.50, 0.70 and 0.90 tie at the selected detector threshold. This sample cannot distinguish the defaults; retain 0.70. Lower values suppress nearby distinct objects as well as duplicates. |
| Minimum area 500 ppm | Zero retains a speck. 500 and 2,000 tie on these targets; retain 500 to avoid increasing the small-object exclusion without evidence. |
| Person overlap drop 500,000 | At 0.25 through 0.90 all three person-dominant raw masks are dropped, together with five other masks. At 0.10 eight other masks are dropped. Retain 0.50; unlabelled objects prevent a claim about false rejections. |
| Vocabulary | Tested only for the observed targets. Held helmets are not a vocabulary term. No claim of general object recall. |
| Text threshold 250,000 | Currently unused by the per-word Grounding DINO scorer. It is not an effective independent control. |
| Fallback detector threshold 200,000 | No fallback measurement on these six photographs. Remains unvalidated. |
| Image edge 1,024, contour simplification 1,500 ppm, vertex cap 256 | Fixed for this study. Finer contours can retain detail at greater storage cost; no comparative measurement establishes an optimum. |
| Maximum prompts 24 | No selected photograph reached the cap under production defaults. No recall claim for crowded scenes. |
| Gaussian sample cap 200,000 | No trained-Gaussian ground truth in this study. Remains unvalidated. |
| Region margin 0 | Avoids deliberately enlarging boundaries. Not empirically tuned here. |
| Instance link distance 2 voxels | Connects sparse samples but can join nearby objects. No instance-separation ground truth here. |

For the scene study, all 210 cameras and masks vote over 215,040 placed samples. Of the 3,072
samples belonging to the three labelled views, 911 project inside their own recovered camera and
can be scored against a source pixel: 300 turntable, 243 rock, 368 background. The remaining 2,161
are outside the recovered frame or behind it and are excluded, never clamped to border labels.
This is a projection-based check of depth, placement, voting and voxel coverage together, not an
independent 3D ground truth or a way to attribute every miss to voting.

| Scene parameter | Measured trade |
| --- | --- |
| Vote minimum 2 | Keep the requirement for corroboration. One view admits more fringe segments; three does not improve this sample enough to justify excluding two-view support. |
| Vote fraction 500,000 | Current rock precision/recall is 1.000/0.284; turntable 0.677/0.357. Lowering to 0.40 with the proposed tolerance improves coverage but reduces precision to 0.863 for rock and 0.620 for turntable. Retain 0.50 in the proposal. |
| Occlusion tolerance 150,000 | **Propose 50,000**, not yet applied: with floor 32 and the other defaults, mean IoU rises from 0.294 to 0.476. Rock precision/recall becomes 0.954/0.601; turntable 0.734/0.423. A stricter visibility test removes conflicting views from the denominator, which also increases assignments; it is not simply a stricter mask. |
| Minimum segment samples 8 | **Propose 32**, not yet applied: removes the third fringe segment with no change to any scored sample, both at current tolerance and in the combined proposal. Smaller real objects could also disappear. |
| Samples per member 1,024 | At 512, mean IoU is 0.239; at 2,048, 0.303 versus current 0.294, with twice as many samples to vote. Retain 1,024 provisionally. |
| Voxel grid 128 | Grid 64 raises mean IoU to 0.388 through coarser occupied cells; grid 256 lowers it to 0.273. This metric rewards filled area and cannot establish boundary quality; retain 128. |
| Region raster 512 | 256 gives mean IoU 0.293 and 1,024 gives 0.290. Retain 512; this sample does not establish a meaningful improvement from either change. |
| Occlusion grid 96 | Grids 48 and 192 give mean IoU 0.293 and 0.296. Retain 96; the tiny difference does not justify a claim of better general visibility. |

The evaluation records every tested configuration, including the combined proposal. Registry
edits remain unauthorized, so these proposed values are **not deployed defaults**. General
validation and changes requiring registry edits remain open acceptance items. The full backend suite is deferred to the integration task's
single serialized run; this task reports its focused and static checks.

# Scene segments

This contract owns object and person segments for a reconstructed scene: the per-photograph
segmentation stage, the lift that carries what the photographs found into the scene they
reconstructed as per-entity segments, and the read route a renderer tints and a click resolves.
The vision pass returns boxes and people get reviewed outlines; segments are one bridge from
geometry back to that evidence. The scene pipeline is
[scene-reconstruction-operations.md](scene-reconstruction-operations.md), and person outlines and
consent are [person-presentation-consent.md](person-presentation-consent.md).

## Contents

- [1. The two halves](#1-the-two-halves)
- [2. No migration, and why](#2-no-migration-and-why)
- [3. Models](#3-models)
- [4. The stage](#4-the-stage)
- [5. The lift](#5-the-lift)
- [6. The read and the wire shape](#6-the-read-and-the-wire-shape)
- [7. Measured](#7-measured)
- [8. Parameters, limitations and open decisions](#8-parameters-limitations-and-open-decisions)

## 1. The two halves

| Half | Module | What it writes |
| --- | --- | --- |
| Per photograph | `exulanica/ingest/stages/segmentation.py`, stage `segmentation` | one `object_mask_list` artifact per photograph, one `frame_region` span and one `object_present` inference per mask |
| Per scene | `exulanica/ingest/scene_segments.py`, stage `scene_segments` | one `scene_segments` artifact per scene build, bound to everything it used |
| Read | `exulanica/graph/reconstruction_scenes.py`, route `GET /scene-segments/{scene_id}` | the segments this reader can stand behind under the geometry asset-read policy |

## 2. No migration, and why

Object regions are carried as `frame_region` evidence spans without a schema change, with one
limit stated plainly.

* **The span is the mask's bounding rectangle.** Migration 0033's `evidence_span_region_shape`
  admits `kind = 'rect'` and nothing else, and [ADR-0013](adr/0013-region-encoding.md) keeps `kind`
  as the discriminator a polygon kind would be added under. A polygon on the span would need a
  migration, a change to `exulanica/evidence/region.py`, new span-digest vectors and a change to
  graph-client's `EvidenceRegion`, none of which a segment needs.
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
`exulanica/ingest/spine/stage_registry.py`, so neither artifact kind needed schema either.

## 3. Models

Pinned in the manifest's `local_models` and `local_roles` sections, beside the Token Factory
roles, by revision SHA with the licence read from the raw README frontmatter at that revision
([license matrix](license-matrix.md) section 5).

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
  (MEASURED: `'rock boulder cliff mountain hill'` for one box on a volcanic sample photograph), so
  each vocabulary entry is scored over its own token span and a box takes the best one.
* **The person path is untouched.** The segmenter reads the masked derivative whenever anybody in
  the photograph is hidden, as depth does. People are never prompts. A detector label outside the
  vocabulary is not believed. A mask half or more inside any live person region is dropped, so an
  object outline cannot become a second, unreviewed outline of somebody.
* **Gated like the geometry it feeds.** It needs an eligible privacy screening. With none, or with a
  person-detection-only receipt, the stage is `unavailable` with the reason in the ledger rather
  than failing the run, which is deliberately softer than depth: a worker with a segmenter must
  not fail the pass that looks for people. Where the capture needs one, the stage also asks for a
  personal model right naming the segmenter and detectors ([personal-admission.md](personal-admission.md)).
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

`publish_scene_segments(repository, store, scene_id)` runs at three moments.

* **As the scene publishes.** `SceneReconstructionProcessor` lifts right after the publication
  commit, in the scene worker's process and in the run that published the scene. It hands over the
  placement it has just validated (`ValidatedBuild`), and the lift uses it only when the scene's
  current build in the database has those exact receipts, so it does not validate the placement a
  second time; a test holds that the result is byte for byte what the command writes after
  validating the stored placement itself. The point maps are still checked live. A lift failure
  never takes the scene down: every exception is caught, because anything escaping after the commit
  would report a published scene as failed. The failure is `stage_failed` on `scene_segments` in
  that run, and a worker asked to stop records `stage_skipped` instead of lifting. When the build
  trained an accepted delivery, the lift also samples the accepted training output the delivery
  was compressed from, still in the job's scratch, and binds it as the Gaussian source: the PLY by
  digest and the delivery by its artifact digest. The trained Gaussians are one surface where the
  posed point maps are one guess per photograph, so these segments follow what a trained scene
  draws.
* **When masks complete after the build.** `scenes_due_segments` finds every published scene where
  every member of the current build has a live segmentation artifact and the newest segments are
  absent, unreadable, bound to another build or bound to other masks.
  `SceneReconstructionWorker.refresh_scene_segments` lifts each one in a `reprocess` run of its
  own. The scene worker command does this after a drain, at most every
  `--segments-refresh-seconds` (default 300, 0 turns it off), under `--once` as well, and never
  in a job-scoped worker. A scene is attempted once for each state it is due in, so a lift that
  fails the same way every time is not repeated on every pass. A scene whose newest segments of
  this build were lifted over trained Gaussians is reported as skipped rather than lifted: the
  accepted PLY is not retained, and lifting from point maps alone would replace segments that
  follow the trained surface with ones that follow the per-photograph maps.
* **On demand**, from `python -m exulanica.ingest.scene_segments --workspace <uuid> --scene <uuid>`,
  which is also how a published trained scene is lifted over its Gaussians again: `--gaussian-ply`
  with a PLY decoded from the delivery, bound by `--gaussian-delivery-sha256`.

The command and the sweep read the scene's validated graph projection
([scene-reconstruction-operations.md](scene-reconstruction-operations.md) section 8) and check its
payload digest, all three receipt bindings, ordered members and point-map inputs before using its
transforms; a missing, damaged or mismatched projection falls back to placement validation. Every
path still checks point-map liveness and content digests.

All three are numpy and nothing else, which is what lets the first two run in the pycolmap
process. All three skip a scene with nothing to lift, no object masks and no reviewed, shown
person, rather than write an empty artifact that would say somebody looked; the reader then says
`absent`, and the skip is `stage_skipped` in a caller's run or, from the command, no run at all.
A receipt, point map or mask that has gone is `stage_failed` and returned as a skip.

* **One projector.** The masked-geometry check's arithmetic, exposed from
  `exulanica/ingest/masked_geometry.py` as `camera_point`, `image_point` and `ppm_point`, which
  that check calls itself one Gaussian at a time and the lift calls with arrays. Margin zero.
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
on, and its id is a digest over its kind, label, subject and voxels. A person segment carries a
subject reference and never a name, is re-checked on every read, and is reached by a scene
tombstone like every scene artifact. A consent withdrawal withholds it at once; its bytes stay until
the scene is rebuilt or purged.

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

**Naming an object.** A local detector mask gets one unnamed `object` occurrence standing on the
mask's bounding span, and its `prompt_span_digest` names that span, as it names a hosted
occurrence's box span for a hosted mask; the hosted path creates no additional occurrence.
Segmentation creates no entity and no confirmed link. The account holder's confirmation through
`POST /identity/name` creates the entity and records the name as a user assertion. The input
contract re-keys older masks, so a rerun supplies missing occurrences.

## 7. Measured

MEASURED on the retained 210-photograph volcanic collection (a rock on a white turntable, CC0) on
an Apple M3 Pro with 18 GiB and MPS, against a frozen copy of the database and store; the
digest-bound record of this run is local to the machine that ran it and is not in this repository.
The workspace had no hosted vision observations, so Grounding DINO prompted every photograph.

| Per photograph, 210 photographs, 0 errors | Value |
| --- | --- |
| Masks | min 2, median 2, mean 2.37, max 5; 497 in all |
| Labels | `boulder` 210, `plate` 181, `sign` 55, `table` 35, `statue` 7, `bridge` 4, `cup` 3, `bottle` 1, `umbrella` 1 |
| Stage seconds, from the ledger | median 0.795, p90 0.834, max 2.369 (the first photograph, which loaded Grounding DINO) |

| The lift | Value |
| --- | --- |
| Samples | 215,040 point-map samples from 210 recovered cameras; 212,667 seen by at least one view, 35,428 assigned |
| `boulder` | 6,781 samples in 3,975 voxels, outlined in all 210 views |
| `plate` | 28,616 samples in 20,979 voxels, 179 views |
| `table` | 26 samples in 20 voxels, 2 views |
| Artifact | 551,491 bytes; the read answered `available` in 0.45 s |

The rock and the turntable separate cleanly. The turntable is one object under two labels, `plate`
and `table`; labels are entity keys, so the lift keeps them apart and the majority rule leaves
`table` a small fringe. The `plate` segment also carries a sparse spray of voxels past the
turntable's far edge, most likely the depth model's points along that silhouette. Neither is
corrected; both are open in section 8.

## 8. Parameters, limitations and open decisions

Every threshold is a stage parameter, so changing one re-keys what it produced. None is validated
for general deployment: the only tuning evidence is a sample of six photographs whose target
outlines were traced without human review, with no held-out set.

| Parameter | Value | Evidence status |
| --- | --- | --- |
| Detector box threshold | 300,000 | Least restrictive value that found every traced target with no extra mask on the tuning sample |
| Detector text threshold | 250,000 | Unused by the per-word scorer; not an independent control |
| Fallback detector threshold | 200,000 | Unmeasured |
| Duplicate box IoU | 700,000 | 0.50, 0.70 and 0.90 tied on the tuning sample |
| Minimum mask area | 500 ppm | 500 and 2,000 tied; 500 excludes fewer small objects |
| Person overlap drop | 500,000 | Dropped every person-dominant mask on the tuning sample; unlabelled objects prevent a claim about false rejections |
| Maximum prompts | 24 | Never reached on the tuning sample; no recall claim for crowded scenes |
| Image edge, outline simplification, vertex cap | 1,024 px, 1,500 ppm, 256 | Fixed, not compared |
| Samples per member | 1,024 | Kept; 512 scored lower and 2,048 slightly higher at twice the samples |
| Gaussian sample cap | 200,000 | Unmeasured |
| Region margin | 0 | Chosen to avoid enlarging boundaries; not tuned |
| Occlusion grid, tolerance | 96 cells, 150,000 | 50,000 improved the projected check on the tuning sample and is not applied |
| Region raster, voxel grid | 512, 128 | Alternatives did not establish a better boundary |
| Vote minimum, vote fraction | 2, 500,000 | Kept for corroboration and precision |
| Instance link distance | 2 voxels | Can join nearby objects; no instance ground truth |
| Minimum segment samples | 8 | 32 removed a fringe segment on the tuning sample and is not applied |

* **The lift after a build waits for every member's masks.** Section 5 lifts a scene again only
  once every member of its build has a segmentation artifact, because a derivative worker segments
  one photograph at a time and lifting after each would lift a 210 member scene 210 times. Until
  then the reader calls the segments `stale` and serves none, and a scene whose segmentation never
  completes stays that way until the command is run for it.
* **Nothing re-lifts for people.** A person region reviewed after the lift is reported in the
  reader's `stale_inputs` while everything else is served; it reaches the scene at the next lift,
  from the sweep or the command.
* **Only publication lifts over Gaussians automatically.** The sweep has no PLY and leaves a
  trained scene whose masks changed to the command, and it reports that it did.
* **Gaussian centres need a decoded PLY after publication.** The trained delivery is SOG and no PLY
  is retained, so lifting a published trained scene again takes the decode the masked-geometry
  evaluation performs. At publication the accepted training output is used instead, which differs
  from the delivery only by the delivery's quantisation.
* **What the lift costs.** MEASURED on the volcanic scene, timing `build_scene_segments` alone
  from a frozen copy: 10.4 s and 1,052 MiB peak when every placed point map was held until the
  vote, 9.8 s and 599 MiB when each view's occlusion grid was built as its map was placed, and
  5.4 s and 126 MiB when cameras were read by `validated_receipt_cameras` without the sparse
  observations, which are about 99.9 per cent of the 107,742,795 byte pose receipt. The artifact
  was byte for byte the stored one every time. The light reader skips the receipt's digest checks,
  so the lift first holds the bytes to the digest its placement is bound to. None of this was
  measured inside a running scene worker.
* **The polygon is not on the span.** Section 2 says what that would cost.
* **Synonymous labels split one object** (`plate` and `table` in section 7), and the segment floor
  of eight samples is low beside 215,040, so a fringe segment clears it. Merging labels would need a
  vocabulary with synonyms or a cross-label association step; neither exists.

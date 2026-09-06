# Person regions, masking and presentation consent

Design note, 2026-09-06. **Components built and migrated; NOT connected, and this hides nobody
today.** The stages exist and are never invoked, no row is ever written to the consent tables, and
the client drops the fields it would need. See "What exists now" at the foot of this note before
relying on anything here. Written after the first real reconstructions showed
that the current gate ("a named human states there are no visible people or sensitive person
regions") is too coarse: the retained bowl photographs contain the arms, hands and clothing of
diners at the frame edge, no faces, and the reviewer's statement said no visible people. The
system needs an explicit list of person regions and a consent state per person, not a yes/no.

## Principles

- **Default deny.** A person region is hidden until a consent says otherwise. Absence of a
  decision is not consent.
- **Three separate consents.** Presence (this person was here), naming (this person is Julie),
  likeness (show this person's appearance). A person can be present and named while hidden.
- **Mask before, not only after.** Reconstruction reads a masked derivative of each photograph,
  so a hidden person never becomes depth, point maps or Gaussians. Viewer-side hiding exists only
  for the reversible "temporarily hidden" state of a person who has consented to likeness.
- **Bodies, not faces.** Clothing, tattoos, hands and posture identify people. A region covers the
  whole silhouette. Any face-like or body-like detection is a person until a human says otherwise.
- **No biometric templates.** Locating a region is allowed; computing or storing anything that
  could recognize the same person elsewhere is not. Names come from a person who labels, never
  from a model that matches. This keeps the existing constraint intact.
- **Receipts, not flags.** Every consent transition is an immutable receipt with actor, time and
  scope. The World Memory Package carries them, and a verifier that respects the format enforces
  the current state offline.

## States

| State | Meaning | Source derivative | Geometry | Atlas |
| --- | --- | --- | --- | --- |
| unknown | detected or confirmed, no decision | masked | excluded | silhouette, unnamed |
| present | presence consented, likeness not | masked | excluded | silhouette, name if naming consented |
| shown | likeness consented | original | included | visible |
| hidden (temporary) | likeness consented, hidden for now | original | included | silhouette at view time |
| withdrawn | consent revoked | masked; derived artifacts purged | excluded, rebuilt | absent |

"withdrawn" reuses the existing withdrawal and purge path; the others are new.

## Stages

1. **`person_regions`** (deterministic over exact source bytes and a pinned detector). Output: a
   digest-bound list of regions per photograph, each a polygon or box with a detector confidence
   and a `confirmed_by` field that is null until a human reviews. The review screen replaces the
   present free-text statement: the reviewer confirms, adds missed regions, and deletes false
   positives; every edit is a receipt. The stage records detector identity and version in its
   parameters so a detector change is a new stage version.
2. **`masked_source`** (deterministic over source bytes, confirmed regions and consent states at
   build time). Output: one derivative image per photograph with hidden regions filled by a
   neutral fill, plus a manifest naming which person each mask belongs to. Depth, pose, placement
   and training read this derivative when any region is hidden. Held-out evaluation uses the same
   derivative so scores never reward reproducing a hidden person. The derivative digest enters the
   scene build inputs, so a later consent change produces a new build rather than mutating one.
3. **Presentation rule in Atlas.** The graph payload carries, per member and per person, the
   current state and a silhouette outline in image coordinates. The inspector and the source veils
   draw the silhouette and the name when permitted; the world never draws pixels for a masked
   region. The status says how many people are hidden in the displayed scene.

## Checks that make it real

- A masked person leaves no geometry: after training, no Gaussian with meaningful opacity sits on
  rays through a masked region in any training view. Record the count in the evaluation bundle.
- Consistency across views: a person confirmed in one photograph and present in others must have
  a region in each, or the reviewer is asked; a single missed frame reconstructs the person.
- Consent UI for the subject, not only the owner: a link the person in the photograph can open to
  set their own state, with the receipt naming them as actor. Without this the layer is theater.
- Reflections and screens count as regions.

## Out of scope for the first pass

Automatic re-identification of the same person across photographs (would need embeddings), audio,
and generative fill of masked areas. Masked areas are neutral, and the status says so.

## Relationship to the current gate

The human screening receipt stays the gate. Its content changes from a statement of absence to a
confirmed region list with states. The two retained collections would be re-screened under the
new stage; the bowl would record two unnamed present people, hidden, and the volcanic set none.

## What exists now

**BUILT BUT NOT CONNECTED. THIS HIDES NOBODY TODAY.** Read that sentence before the table
below, because the table lists working parts and the parts are not joined to each other. An
adversarial audit on 2026-09-06 raised 83 candidate gaps and confirmed 46, thirteen of them
critical, and they converge on one fact: every component exists, is tested, and is unreachable
from the running system.

The chain breaks in five independent places, any one of which is sufficient on its own:

1. `exulanica/ingest/pipeline.py:501` runs rendition, vision and depth. Neither `person_regions`
   nor `masked_source` is invoked by anything except tests.
2. `exulanica/ingest/pipeline.py:532` hands the depth stage `prepared.upright`, the original
   image. The principle at the head of this note, that depth reads the masked derivative, is
   **not true of the code**.
3. Nothing writes a `person_region`, `person_subject` or `person_presentation_consent` row. The
   `person_regions` stage would not help if it ran: it writes an artifact, not a region row. So
   `capture_requires_masking()` is false for every capture and the geometry trigger in 0037 has
   never fired.
4. `web/packages/graph-client/src/snapshot.ts:205` drops `person_regions` and
   `person_review_state` when parsing the payload, so the fields the server sends never reach a
   draw site.
5. Nothing calls the presentation predicates. Four draw sites are ungated: the world veils, the
   reconstruction inspector, the detail-pane citation image, and `GET /evidence/{span_id}`.

**Migration 0037 also removed a guard before its replacement worked.** 0029 blocked any screening
naming a person at all. The first version of the replacement accepted a region in state `unknown`
-- somebody was seen and nobody decided -- as eligible, which is exactly the case default deny
exists for, and for several commits this branch was less safe than what it replaced. Corrected on
2026-09-06: a region in any masked state now blocks until masking is actually wired.

The suite result below says the schema and the pure functions agree. It does not say anybody is
protected: no test inserts a person region, so a stub that hides nobody passes all of it.

**Suite, 2026-09-06:** 1748 passed, 3 skipped, 0 failed against
`postgresql://localhost:5433/exulanica_spine_test`, `ruff check` clean, four import contracts
kept, web workspace green. `EXULANICA_TEST_ALLOW_DATABASE_CREATION` stayed unset.

| Piece | Where | State |
| --- | --- | --- |
| Five states, three consents, receipt fold | `exulanica/consent/states.py` | unit-tested |
| Region outlines, ppm integers, evidence-keyed | `exulanica/consent/regions.py` | unit-tested |
| Deterministic masking and dilation | `exulanica/ingest/masking.py` | unit-tested |
| Detector interface and adapters | `exulanica/ingest/person_detectors.py` | unit-tested; **the adapter reads `objects`, which the vision schema instructs the model not to put people in** |
| Immutable receipts and the two digests | `exulanica/ingest/person_receipts.py` | unit-tested |
| `person_regions`, `masked_source`, `masked_source_manifest` stages | `exulanica/ingest/stages/` | registered; **never invoked by the pipeline** |
| Masked bytes reach COLMAP | `exulanica/ingest/masked_inputs.py` | unit-tested with fakes; **never reached, because no masked derivative is ever produced** |
| Masked-geometry count | `exulanica/ingest/masked_geometry.py` | unit-tested |
| Graph payload fields | `exulanica/graph/payload.py` | sent by the server; **dropped by the client parser** |
| Atlas presentation rule | `web/packages/graph-client/src/person-presentation.ts` | unit-tested; **dead code, no draw site calls it** |
| Tables, RLS, resolver, geometry trigger | `exulanica/migrations/0037_a_person_is_hidden_until_they_consent.sql` | applied; **trigger has never fired, no writer exists for the tables** |

### Two decisions that differ from this note

**The detector is pinned in the stage parameters, and the stage stays deterministic.** This note
asks for a stage "deterministic over exact source bytes and a pinned detector". Making it
model-backed would have been the obvious reading, and `StageSpec` would then require
`deterministic=False`, which would drag `person_regions` into the exact-recomputation exclusion
sentence and into `docs/evaluation/2026-09-05-unblocked-goal-d.json`, whose bytes are digest-pinned
twice by the backend-program record. Editing a dated record of an executed measurement to
accommodate a stage that did not exist when it ran would be a false claim about what was measured.
Instead the detector's identity is a stage parameter and the stage refuses a detector that does not
match it, so a swap is a hard error rather than a corpus silently keyed as though nothing changed.

**No new detector was written, and the one that ships reads detections this system already made.**
MEASURED 2026-09-05: neither extra contains anything that finds people. torchvision, transformers,
ultralytics, mediapipe, onnxruntime, rembg and segment-anything are all absent, and
`opencv-python-headless` resolves to 5.0.0, which removed `cv2.HOGDescriptor` and ships an empty
`cv2/data`. So `RecordedObservationDetector` reads the `person_objects` the `vision` stage already
records, which are real detections with real boxes and cost no new model call. They are boxes, not
outlines; the region records `shape='box'` and nothing downstream calls it a silhouette. A real
segmenter remains the interface's purpose and is not written.

The three new tables brought the count of tables under FORCE row-level security keyed on
`current_workspace()` from 59 to 62. That number is stated in three docstrings and asserted against
the live schema, which is the gate that caught them.

### Not done, and not pretended

- **Splat training on a masked scene is refused**, in `scene_selection.py`, rather than run.
  `SplatBuildManifest` requires the held-out hashes to be a subset of the source hashes, and under
  masking those are derivative digests; relaxing that without a digest map would make the whole
  held-out set silently become training views. Pose, placement and the gate run fully masked.
- **The masked-geometry count is not yet in the evaluation bundle.** It is a function with tests,
  not a stage wired into `_train_splat`.
- **The reviewer's edit screen does not exist.** The receipt shapes it would write do.
- **No subject-facing consent link.** The receipt carries `actor_role: "subject"` so adding one is
  a route rather than a schema change, but until it exists this layer is, in this note's own word,
  theater, and the owner decides for everybody.
- **Source delivery still serves originals.** `GET /evidence/{span_id}` resolves the bytes a
  citation names, and those are the original bytes by definition; a masked sibling route and the
  three client draw sites that would use it are not written. Until then "the world never draws
  pixels for a masked region" holds for reconstructed geometry and not for the source-photograph
  fallback.
- **The two retained collections have not been re-screened.** Bumping the policy to
  `exulanica.reconstruction-privacy/v2` changes the digest embedded in every receipt, so their
  version 1 screenings are now provably old-policy, which is the intended cost.
- **Consistency across views, reflections and screens, and generative fill** remain as this note
  left them.

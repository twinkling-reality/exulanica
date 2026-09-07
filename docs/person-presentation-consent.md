# Person regions, masking and presentation consent

Design note, 2026-09-06. **Implemented and wired end to end, and exercised against a real
database.** A detected person leaves a row, the row forces a masked derivative, reconstruction
reads that derivative, the database refuses geometry over the original, and a reviewer can confirm
who is present and record what each of them agreed to. Read "What exists now" at the foot of this
note for what is still missing, which is not nothing. Written after the first real reconstructions
showed
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

**IMPLEMENTED AND DATABASE-TESTED 2026-09-06.** The chain runs: `person_regions` proposes and
writes rows, `masked_source` fills every unconsented person, `depth` reads the masked image and
records which bytes it read, the scene worker stages masked bytes for COLMAP, and
`tg_geometry_reads_the_masked_derivative` refuses a point map over the original.
`tests/test_person_masking_end_to_end.py` executes that against PostgreSQL and asserts what
landed, including the database's own refusal. A stub that hid nobody now fails four of those tests.

**Suite, 2026-09-06:** 1778 passed, 3 skipped, 0 failed in 4m33s; `ruff check` clean; four import
contracts kept; web typecheck, 343-module boundary check and 768 tests green.
`EXULANICA_TEST_ALLOW_DATABASE_CREATION` stayed unset.

| Piece | Where | State |
| --- | --- | --- |
| Five states, three consents, receipt fold | `exulanica/consent/states.py` | unit-tested |
| Region outlines, evidence-keyed | `exulanica/consent/regions.py` | unit-tested |
| Deterministic masking and dilation | `exulanica/ingest/masking.py` | unit-tested |
| Detector interface and adapters | `exulanica/ingest/person_detectors.py` | see the detector note below |
| Immutable receipts and the two digests | `exulanica/ingest/person_receipts.py` | unit-tested |
| The three stages | `exulanica/ingest/stages/` | **run in the pipeline**, database-tested |
| Region and consent writers | `exulanica/ingest/spine/person_consent.py` | database-tested |
| Depth reads the masked image | `exulanica/ingest/stages/depth.py` | database-tested |
| Masked bytes reach COLMAP | `exulanica/ingest/masked_inputs.py` | unit-tested with fakes |
| Masked-geometry count | `exulanica/ingest/masked_geometry.py` | unit-tested, never run on a trained scene |
| Graph payload and client read model | `exulanica/graph/`, `graph-client/src/snapshot.ts` | carried through to the app |
| Masked byte delivery | `GET /evidence/{span_id}/masked`, `world/repository.py` | database-tested |
| Reviewer routes | `exulanica/api/routes/person_consent.py` | database-tested |
| Reviewer screen | `web/packages/app/src/ui/person-review.ts` | unit-tested |
| Tables, RLS, resolvers, trigger | `exulanica/migrations/0037_...sql` | applied; the trigger fires |

### How a photograph is protected now

A photograph containing somebody who has not consented to their likeness cannot become geometry:
the trigger refuses the point map unless it names a masked derivative of those exact bytes. It also
cannot be shown: `/world/source-media` withholds it when a mask is required and missing, and
otherwise resolves to the masked view, and the citation image in the detail pane reads the same
masked route. `GET /evidence/{span_id}` still returns the exact bytes a citation names, because
those bytes are inside the span digest and an archived citation verifies against them.

### The performance fix worth knowing about

`region_state_for_capture` runs for every photograph on the ingest path. Asking through
`person_region_current`, a `distinct on` view, took one test file from 44 seconds to 3 minutes 28
(MEASURED 2026-09-06, with a control run isolating the query). An indexed existence check now
answers the common case of a photograph with no regions, and the view is read only for photographs
that have somebody in them.

### Two decisions that differ from this note, and one claim that was wrong

**The detector is named by a contract, not pinned to one literal, and the stage stays
deterministic.** This note asks for a stage "deterministic over exact source bytes and a pinned
detector". Making it model-backed would force `deterministic=False`, which would drag
`person_regions` into the exact-recomputation exclusion sentence and into
`docs/evaluation/2026-09-05-unblocked-goal-d.json`, whose bytes are digest-pinned twice by the
backend-program record; editing a dated record of an executed measurement to accommodate a stage
that did not exist when it ran would be a false claim about what was measured. The first attempt
pinned one detector name in the parameters, and that was wrong for a different reason: it refused
every detector but one, including the suite's own doubles. The property that actually matters is
that swapping a detector regenerates rather than reusing stale regions, and that now lives in the
stage's **input** digest, per photograph, with the parameters declaring the contract.

**CORRECTED 2026-09-06: the shipped adapter reads a field that is specified to be empty.** This
note previously recorded that `RecordedObservationDetector` reads "real detections the vision stage
already made". That was wrong, and an audit found it. `exulanica/ingest/vision.py` describes
`objects` as "Distinct things visible in the image. Do not list people here; people are handled
elsewhere and are not part of this record." `person_objects` is a defensive filter for a model that
disobeys that instruction, not a detector. So the adapter finds almost nobody, its label set is an
exact-match whitelist of singular nouns that does not match arms or hands, and the honest statement
is that **a human adding regions through the review screen is the detector today**.

MEASURED 2026-09-05, and still true: neither extra contains anything that finds people. torchvision,
transformers, ultralytics, mediapipe, onnxruntime, rembg and segment-anything are all absent, and
`opencv-python-headless` resolves to 5.0.0, which removed `cv2.HOGDescriptor` and ships an empty
`cv2/data`. Nothing was fabricated to fill the gap.

The three new tables brought the count of tables under FORCE row-level security keyed on
`current_workspace()` from 59 to 62. That number is stated in three docstrings and asserted against
the live schema, which is the gate that caught them.

### The detector, corrected 2026-09-06

The first pass shipped an adapter that read `person_objects` from the vision observation, and an
audit found that `exulanica/ingest/vision.py` instructs the model **not** to list people in
`objects`. That field is a defensive filter for a model that disobeys, not a detector, and its
label set is an exact-match whitelist of sixteen singular nouns: "arms", "hands", "diners",
"elbow" and "shoulder" match none of them. Those are precisely the traces the retained bowl
photographs contain, so the detector could not have found the thing this note was written about.

Observation schema version 2 fixes that at the source rather than by widening a whitelist:

- **People have their own array**, and the description asks for "every visible trace of a human
  being, including partial ones", naming a hand at the edge of the frame, an arm, a leg, a
  shoulder, clothing on a body, a reflection, and somebody on a screen inside the photograph.
- **The part is a closed vocabulary** (`full_body`, `partial_body`, `head`, `torso`, `arm`,
  `hand`, `leg`, `foot`, `reflection`, `on_screen`), so an unrecognised value is refused rather
  than silently dropped, and it reaches the review screen: a reviewer looking at an outline on a
  neutral field can otherwise not tell a hand from a coat on a chair.
- **The prompt tells the model a miss is worse than a false positive**, which is the right trade
  under default deny: an extra region costs a reviewer one click, a missed one reconstructs
  somebody who never agreed.
- **A person entry carries no label and no salience.** Routing people through the object list meant
  the model wrote free text about them, and "woman in a red coat" is a description of somebody who
  has not consented to being described. The occurrence quality keys went from
  `{confidence_band, salience, label, trust_tier}` to `{confidence_band, part, trust_tier}`, and
  the two biometric-boundary tests were tightened to assert `label` is absent rather than
  permitted.
- **Observations stored under version 1 still read.** `person_traces` falls back to the old object
  filter, so an existing corpus does not silently become a corpus with nobody in it, and that
  fallback also still catches a model that ignores the instruction.

The vision stage moved to version 3 and the prompt digest moved with it, so every photograph is
re-observed rather than keeping an answer given under the old question.

### The vision stage is gated, 2026-09-06

Until this change the depth stage required an eligible privacy screening for the exact bytes and
the vision stage required nothing. That is the wrong way round twice over. Vision is the **first**
stage to touch a photograph after intake, and it is the one that sends it to a hosted model, so
the ungated stage was the one with egress. It is also now the stage that enumerates every visible
trace of a person, which would have meant locating people in order to protect them by first
sending them somewhere else.

Vision now takes the same receipt depth does:

- **No screening: unavailable, not failed.** Nothing is sent, the ledger records the reason, and
  ``outcome.stages_unavailable`` gains ``vision``. Raising would have made the one-shot ingest
  path impossible rather than merely quiet, because a screening is keyed to a capture that does
  not exist until intake has committed; and an ingest that errors on every unscreened photograph
  is an ingest somebody switches off.
- **A stale, blocked or superseded receipt raises.** Having looked and been refused is not the
  same as never having asked.
- **The screening digest is deliberately NOT in vision's input digest**, unlike depth's.
  Re-recording a receipt does not change what is in the photograph, and keying on it would re-bill
  a model call every time one was superseded. The receipt id is stored on the artifact instead.
- **The derivative worker resolves the capture's current eligible receipt** and hands it to both
  paid stages, so this is production wiring and not only a parameter.

**What this costs, stated plainly.** An unscreened photograph now gets no description, no person
occurrences, no OCR and no place proposal. `exulanica-ingest ingest ./photos` will not describe
anything until somebody has screened it. That is a real change in what the product does between
upload and review, and it is the honest consequence of deciding that sending a personal photograph
to a third party needs an authorization.

The test suite absorbed it through `tests/conftest.py::ingest_observed`, which does intake,
records a synthetic authorization and exemption, then runs derivatives. That is not a bypass: the
test corpus is generated media with nobody in it, and a database trigger refuses the synthetic
exemption for benchmark or personal bytes. One measured sequence genuinely changed and was
re-recorded rather than quietly edited: the `find_artifact` order over an unscreened `ingest_file`
is now three calls instead of five, and position three is still the rendition persist, which is
the only part the sibling race test depends on.

### Looking is now a separate permission from building

Version 2 as first written created a loop with no honest way in. A screening is eligible when a
human has confirmed a region list with a consent state per person; producing that list means
looking at the photograph; and looking means showing it to a detector, which needed a screening.
For a collection like the retained bowl photographs, containing diners nobody can ask, the loop
had no entry at all: an empty region list asserts nobody is there, a list naming them is blocked,
and masking cannot help because the detector reads the original.

`person_detection_only` is the way out, and it is deliberately narrow.

- It says an actor authorized sending these exact bytes to a detector **for the purpose of finding
  the people in them**, and the purpose is recorded in the receipt.
- It is stored as `blocked`, because blocked is what it is for geometry, and the blocking reason
  says so in words.
- The split is enforced by there being **two predicates rather than one flag**.
  `privacy_screening_allows_capture` still gates geometry and does not admit this method;
  `privacy_screening_allows_observation` admits it and is what the vision stage asks. A single
  function with a boolean would eventually be called with the wrong boolean, and that failure is a
  photograph reconstructed on the strength of a receipt that only ever permitted looking at it.
- `tests/test_person_detection_screening.py` pins both directions, including that the **database**
  refuses a point map carrying a detection receipt, so a future caller cannot route around the
  Python check.

**It is not consent, and the receipt does not pretend otherwise.** Nobody in the photograph has
agreed to anything. An account holder has authorized a search for them so that they can be hidden.
`human_review_required` is false because no human reviewed the image, and `reviewed_by` names the
actor who authorized the detection, so the row never reads as a review that did not happen.

### Not done, and not pretended

- **The detector asks a hosted model, and its recall on real photographs is unmeasured.** Schema
  version 2 gives people their own field and asks for partial traces by name, so a hand at a frame
  edge is now something the model is told to report; what it actually reports on the retained bowl
  photographs has not been measured, and cannot be until somebody runs the vision stage over them.
  It is a multimodal model doing open-vocabulary detection, not a segmenter: the regions are boxes,
  recorded as `shape='box'`, and no code calls them silhouettes. A pinned local segmenter remains
  the interface's purpose and is still not written, which also means every photograph's people are
  enumerated by a hosted model rather than on this machine.
- **No subject-facing consent.** Every receipt these routes write records `actor_role: "owner"`,
  and the route refuses to let a request name its own actor or role, so the owner cannot
  manufacture the subject's decision. But the photographed person still has no way to answer for
  themselves, and until they do this layer is, in this note's own word, theater. The column and
  the receipt already admit `subject`, so adding that route is a route rather than a schema change.
- **Splat training on a masked scene is refused**, in `scene_selection.py`, rather than run.
- **The masked-geometry count has never seen a trained scene.** Its tests build PLY bytes vertex by
  vertex, and it is not wired into the evaluation bundle.
- **The two retained collections have not been re-screened, and now cannot be used until they
  are.** CORRECTED 2026-09-06: the policy bump to `exulanica.reconstruction-privacy/v2` was
  described here and in the evaluation record as making their version 1 receipts old-policy, with
  the implication that this stopped them being used. It did not.
  `privacy_screening_allows_capture` never compared `policy_version`, so every version 1 receipt
  kept passing and the invalidation existed only in prose; checked against the live bowl
  workspace, all 51 receipts still returned `allowed = true`. The resolver now compares against
  `current_privacy_policy()`, and a test binds that function to
  `exulanica.ingest.privacy.PRIVACY_POLICY_VERSION` so the two cannot drift.

  This is worth recording as a class of bug rather than a typo: the receipt had stored
  `policy_version` and `policy_params_digest` from the beginning, and storing a digest nothing
  compares is the same as not having one.
- **A revoked consent produces a new build; it does not purge the old one.** Existing geometry from
  a build made while somebody was `shown` stays until the ordinary withdrawal path reaches it.
- **Consistency across views, reflections and screens, and generative fill** remain as this note
  left them.


## Three things true of the code and false of a running deployment

VERIFIED 2026-09-07 on the merged tree, after `person-consent-masking` landed on
`semantic-answers-and-memory-lifecycle`. Everything above this heading describes code that exists
and is tested. None of it describes a deployment where a person is actually protected, and the
difference is three separate gaps. They are recorded here because "it is proven" and "it has run
here" are different claims, and this note previously made only the first.

**1. The detector defaults to none, so a default deployment writes no region at all.**
`_build_detector` in `exulanica/ingest/worker_command.py` resolves to `unavailable` unless
`EXULANICA_PERSON_DETECTOR` is set to `recorded-observation`. With no detector, no `person_region`
row is ever written, `capture_requires_masking` is false for every capture, and migration 0037's
`tg_geometry_reads_the_masked_derivative` never has anything to refuse. The database guard is
correct and inert. The default is deliberate and this note does not argue with it; what was missing
was saying out loud that the guard protects nothing until an operator opts in.

**2. A photograph with an unconsented person cannot obtain an eligible screening at all, so the
masking path has no honest route through production.** `record_human_screening` blocks any
screening listing a region in a `MASKED_STATES` state, and its only production caller,
`exulanica/ingest/reference_admission.py`, passes `sensitive_regions=[]`. So the screening
receipt's region list has no production writer, and the only way to reach the masking path today is
for the screening's region list and the `person_region` table to disagree, which is exactly what
`tests/test_person_masking_end_to_end.py`'s synthetic exemption arranges.

That block was written for a stated reason, and the reason has expired. Its own comment says: "the
masking stages are not yet wired into the pipeline, so nothing anywhere would actually hide this
person before depth read them", and "when masking is wired end to end this becomes eligible if
every masked region has a current `masked_source` derivative". **Masking is now wired end to end.**
So the rule the comment describes as the destination is now the correct one, and the conservative
rule it describes as temporary is now the thing making the feature unreachable. Changing it is a
decision with real safety weight rather than a cleanup, and it must be made before the review
screen is wired, or the reviewer will be built for a path nobody can reach honestly. It is not
made here.

**3. The reviewer screen and every client-side drawing predicate are dead code.**
`web/packages/app/src/ui/person-review.ts` is imported by nothing but
`web/packages/app/test/person-review.test.ts`. `drawsPixels`, `drawsSilhouette`,
`mayDrawPhotograph` and `hiddenRegions` are exported from `graph-client` and used by no application
source. The only symbol that reaches the app is `personPresenceSentence`, in
`web/packages/app/src/ui/status.ts`. **The browser-side "presentation rule" is a status sentence
and a server-side href swap, not a draw gate.** What actually protects a person in the browser is
that the bytes were masked before anything read them and that `/world/source-media` withholds an
unmasked derivative; the client-side predicates are a second line that is not connected.

## What the privacy feature has and has not touched

VERIFIED 2026-09-07: `public.person_region`, `public.person_subject` and
`public.person_presentation_consent` all hold **zero rows**. Migration 0037's masking trigger has
never fired against a real photograph. The two retained collections, the bowl `bdba4f95` and the
volcanic `79004d44`, are `unscreened` for people in every World Read bundle, which is why the
2026-09-07 read-paths record reports `person_consent: unscreened` and `release.state:
internal_only` for all three scenes.

The end-to-end test proves the mechanism against PostgreSQL, a real migration and a real on-disk
store, using synthetic data in a throwaway schema. Nobody has yet seen it work on a real
photograph.

## What the World Read bundle now says about people, and what it deliberately does not

DECIDED 2026-09-07, and the reasoning is in `docs/phase-10-tickets.md` under P10-1-c-2.

The bundle reports, per photograph, whether anybody has looked at it for people (`unscreened` or
`recorded`) and how many live regions it carries. It reports neither the state of any individual
person nor their outline. That is not an oversight, and the reason is the interaction between two
things this note and the migration each established separately: `person_consent_is_granted` filters
on `clock_timestamp()`, so a person's resolved state changes when a `temporary_hide` expires with
no write in between, and the World Read bundle is digest bound with `release` inside its recorded
keys. Putting a resolved state in the bundle would make the recorded digest move on a timer, and a
digest that moves when nobody wrote anything is a digest nobody can quote.

So `release.state` is `internal_only` for every scene, and the bundle says so with a per-scene
reason rather than as a constant. Resolving that tension, most likely by binding the release answer
to an explicit as-of time carried in the bundle, is what the next person to add per-person state to
a view has to do. A test is armed for exactly that moment.

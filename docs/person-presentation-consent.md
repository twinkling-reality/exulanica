# Person regions, masking and presentation consent

A photograph used to build a world can show people who never agreed to be in it. This contract
owns what happens to them: person regions and who proposes them, the masked derivative that
reconstruction reads instead of the original, the human screening that permits geometry and its
binding to current privacy inputs, and each person's presentation consent. Which model may receive
a photograph is [personal-admission.md](personal-admission.md); serving photographs, masks and
geometry under current permission, including what the World Read bundle says about people, is
[asset-read-currency.md](asset-read-currency.md); deletion is
[domain-and-evidence-model.md](domain-and-evidence-model.md) section 6.

## Contents

- [Principles](#principles)
- [States](#states)
- [Stages](#stages)
- [Who finds people](#who-finds-people)
- [The screening rule](#the-screening-rule)
- [Screening currency](#screening-currency)
- [Names and withdrawal](#names-and-withdrawal)
- [The review screen](#the-review-screen)
- [Training use is a separate consent plane](#training-use-is-a-separate-consent-plane)
- [A place's name is a separate consent plane](#a-places-name-is-a-separate-consent-plane)
- [Limits and open questions](#limits-and-open-questions)
- [Evidence](#evidence)

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
  from a model that matches. When a biometric template may exist at all is an open decision in
  [privacy-consent-threat-model.md](privacy-consent-threat-model.md) section 10.
- **Receipts, not flags.** Every consent transition is an immutable receipt with actor, time and
  scope. The World Memory Package carries them, and a verifier that respects the format enforces
  the recorded state offline.

## States

| State | Meaning | Source derivative | Geometry | What a viewer may be shown |
| --- | --- | --- | --- | --- |
| unknown | detected or confirmed, no decision | masked | excluded | outline, unnamed |
| present | presence consented, likeness not | masked | excluded | outline, name if naming consented |
| shown | likeness consented | original | included | the person |
| hidden (temporary) | likeness consented, hidden at view time | original | included | outline at view time |
| withdrawn | consent revoked | masked; derived artifacts purged | excluded, rebuilt | nothing |

`unknown`, `present` and `withdrawn` are the masked states (`MASKED_STATES` in
`exulanica/consent/states.py`), and the receipt scopes are `presence`, `naming`, `likeness` and
`temporary_hide`. `withdrawn` reuses the withdrawal and purge path.

The last column is what the graph payload permits, not what the browser draws. The application
draws no outlines: it shows a status sentence (`personPresenceSentence`), and the draw predicates
`drawsPixels`, `drawsSilhouette`, `mayDrawPhotograph` and `hiddenRegions` exported by graph-client
are used by no application code. What protects a person in a browser is that the bytes were masked
before anything read them and that the served image is the masked one.

## Stages

1. **`person_regions`**, deterministic over the exact source bytes and a detector contract. It
   writes a digest-bound list of regions per photograph, each a polygon or box with a detector
   confidence and a `confirmed_by` that stays null until a human reviews. The reviewer confirms,
   adds missed regions and deletes false positives, and every edit is a receipt. The detector's
   identity enters the stage's input digest per photograph, so swapping a detector regenerates
   regions instead of reusing stale ones, while the parameters declare the contract; the stage
   stays deterministic and outside the exact-recomputation exclusion.
2. **`masked_source`**, deterministic over the source bytes, confirmed regions and resolved consent
   states at build time. It writes one derivative per photograph with every hidden region filled
   with neutral fill, plus a manifest (`masked_source_manifest`) naming which person each mask
   belongs to. Depth, pose, placement, segmentation and training read it whenever any region is
   hidden, and held-out evaluation uses it, so scores never reward reproducing a hidden person. Its
   digest enters the scene build inputs, so a consent change produces another build rather than
   mutating one.
3. **Presentation.** The graph payload carries, per member and per person, the resolved state, the
   outline in image coordinates, and a name only on a naming receipt and never once a withdrawal
   stands (`exulanica/graph/person_regions.py`). The hidden count is computed on the server, so a
   client that failed to load the rows cannot report that nobody was hidden.

The database holds the line independently. Migration 0037's
`tg_geometry_reads_the_masked_derivative` refuses a point map over the original unless it names a
masked derivative of those exact bytes, and `person_subject`, `person_region` and
`person_presentation_consent` are under FORCE row-level security keyed on `current_workspace()`.
`/world/source-media` withholds a photograph whose required mask is missing and otherwise resolves
to the masked view, and the citation image in the detail pane reads the same masked route.
`GET /evidence/{span_id}` returns the exact bytes a citation names only when current permission
allows the original, refuses otherwise, and never substitutes a derivative.

## Who finds people

**The detector.** The derivative worker's configured person detector is off by default:
`EXULANICA_PERSON_DETECTOR` unset or `unavailable` builds none, and `recorded-observation` builds
`RecordedObservationDetector` (`_build_detector` in `exulanica/ingest/worker_command.py`). A capture
admitted for detection only (below) is processed with `RecordedObservationDetector` whatever the
worker's setting (`exulanica/ingest/worker.py`). Without either, no `person_region` row is
written, `capture_requires_masking` is false and the geometry trigger has nothing to refuse, so the
guard is correct and inert until detection runs or a reviewer adds a region by hand.

`RecordedObservationDetector` reads the people the hosted vision pass reported, so the detector is
a hosted multimodal model returning boxes (`shape='box'`), and its recall on real photographs is
unmeasured. The segmentation stage's local open-vocabulary detectors are never prompted for people
([scene-segments.md](scene-segments.md)), so there is no local person detector.

**What the vision pass is asked.** Observation schema version 2 gives people their own array and
asks for every visible trace of a human being, naming a hand at the edge of the frame, an arm, a
leg, a shoulder, clothing on a body, a reflection and somebody on a screen. The part is a closed
vocabulary (`full_body`, `partial_body`, `head`, `torso`, `arm`, `hand`, `leg`, `foot`,
`reflection`, `on_screen`), so an unrecognised value is refused, and it reaches the review screen,
where an outline on a neutral field cannot otherwise be told from a coat on a chair. The prompt
says a miss is worse than a false positive, which is the right trade under default deny. A person
entry carries no label and no salience, so the model writes no free-text description of somebody
who has not consented; a person occurrence's quality keys are `confidence_band`, `part` and
`trust_tier`. Observations stored under version 1 still read: `person_traces` falls back to the
object filter, which also catches a model that ignores the instruction. The vision stage is at
version 3, so photographs are re-observed rather than keeping an answer given under the old
question. A person the observation names without a usable box is masked as the whole frame.

**The vision stage is gated.** Vision is the first stage to send a photograph anywhere, so it takes
the same screening receipt depth does. With no screening the stage is unavailable, not failed:
nothing is sent, the ledger records the reason and the outcome lists `vision` as unavailable. A
stale, blocked or superseded receipt raises. The screening digest is deliberately not in vision's
input digest, because re-recording a receipt does not change the photograph and keying on it would
pay for a model call every time a receipt was superseded; the receipt id is stored on the artifact.
The derivative worker resolves the capture's current eligible receipt and hands it to both paid
stages, and each model call also needs a current personal model right. An unscreened photograph
therefore gets no description, person occurrences, OCR or place proposal, and
`exulanica-ingest ingest ./photos` describes nothing until a photograph is screened.

**Looking is a separate permission from building.** A screening is eligible for geometry when a
human has confirmed a region list with a state per person, and producing that list means showing
the photograph to a detector. `person_detection_only` is the narrow way in: it records that an
actor authorized sending these exact bytes to a detector to find the people in them, with the
purpose in the receipt, and it is stored as `blocked` for geometry with the reason in words. Two
predicates rather than one flag enforce the split: `privacy_screening_allows_capture` gates
geometry and does not admit this method, and `privacy_screening_allows_observation` admits it and
is what the vision stage asks. The database refuses a point map carrying a detection receipt
(`tests/test_person_detection_screening.py`). It is not consent: nobody in the photograph agreed to
anything, `human_review_required` is false because no human reviewed the image, and `reviewed_by`
names the actor who authorized the detection.

## The screening rule

The human screening receipt is the geometry gate, and its content is a confirmed region list with
a state per person rather than a statement that nobody is there. A screening naming somebody in a
masked state is eligible only when both of these hold, each checked against the database rather
than taken from the caller:

1. **Every person the screening names as masked is one the pipeline is hiding.** The named region
   keys must be present in `person_region` and resolve to a masked state. A region entry with no
   `region_key` cannot be matched to anything hidden, and blocks.
2. **The mask is current, not merely present.** `masked_source_key` folds the source bytes, the
   confirmed region set and the resolved consent states, so a derivative built before somebody
   added a region or changed their mind produces another key and stops being an answer.

The trigger behind it means an eligible screening cannot by itself put an unconsented body into
geometry, and because the consent states are inside the derivative's key, a revocation produces
another build rather than mutating an accepted one. `tests/test_person_masking_end_to_end.py`
executes the rule against PostgreSQL, a real migration and a real on-disk store:

| Case | Answer |
| --- | --- |
| A detected person, masked, derivative built, named in the screening | eligible |
| A person the reviewer names whom no detector proposed and no mask covers | blocked |
| A reviewer adds a region after the derivative was built | blocked, the mask is stale |

Each case fails under a different wrong rule: a blanket refusal of masked states, a rule that asks
only whether the capture's own mask is current, and a rule that asks only whether a
`masked_source` artifact exists.

**Sequencing.** The derivative is produced during ingest, and a benchmark admission records its
screening before derivatives run, so a photograph containing people cannot be admitted and screened
as eligible in one pass: it is admitted, ingested (which proposes regions and builds masks), and
then re-screened. That still needs a detector or a human to put regions there in the first place.

## Screening currency

Migration 0040 separates a historical review from permission for a new geometry operation. A
screening authorizes geometry only while the privacy inputs it reviewed, and the mask built from
them, are still the current ones.

**The snapshot.** `current_privacy_inputs` takes the workspace privacy lock, then evaluates at one
database clock instant. Its snapshot names the workspace, the capture, the exact original bytes, the
latest edit digest for every region key (deleted regions included), and each live region's key,
silhouette, subject, resolved state, naming permission and applicable consent digests. Edit
identities distinguish a new review input even when its pixels are identical, and keeping deleted
edit identities stops an earlier empty-inventory review reviving after an add and a delete. A
missing capture is not an empty review. Consent evaluation keeps region-specific-over-subject-wide
precedence, then sequence, and refuses when a highest-priority sequence written before 0040 is
ambiguous. Future decisions are excluded, expired receipts do not hold, an older still-valid
applicable receipt may, and a withdrawal is terminal even if a grant follows. Every scope uses the
same instant, so a future effective time or an expiry can change the snapshot without a write; no
evaluation timestamp enters the binding, so unchanged effective inputs stay reusable.

**How a mask proves its inputs.** The mask stage paints the supplied outlines with the supplied
states and records an input digest over the sorted hashes of the intake artifact's content (the
canonical EXIF and probe record, not the pixels), `person-region-set/v1` (capture id, original
source hash, sorted live keys and silhouettes) and `person-consent-state/v1` (capture id, source
hash, sorted region states, masked and naming values). The SQL predicate recomputes these digests
from the snapshot with canonical integral JSON and requires them to match the artifact's recorded
`input_digest`, exact source, current stage version and parameters; the intake artifact must match
its current stage definition, and the mask must be complete, unpurged and not marked for repair. An
UPDATE cannot relabel a mask's lineage or replace its content hash, though purge can still clear
its bytes. This is recorded producer lineage, not a cryptographic proof against a database writer
who fabricates a whole artifact row; SQL checks records, and store readers check bytes. Neither the
newest creation time nor the existence of a mask establishes currency.

**How a screening binds them.** A screening's canonical record includes the exact input snapshot
and, when masking is required, the exact mask id and content hash, and the predicate compares both
with current inputs and lineage. A review recorded without its mask cannot activate when a mask
appears later, and rebuilding a mask cannot revive a review of changed inputs: re-screen
explicitly. A same-input retry reuses the mask and the review; a same-pixel edit can reuse the mask
but needs another review. A record without the 0040 binding stays a historical fact and authorizes
no new geometry. Human screening must cover exactly the current region keys and states, a
no-person review binds an empty inventory, and a synthetic exemption requires no live person
regions. Withdrawal, capture tombstones and authorization or screening expiry still refuse geometry.

**Where the predicate is asked.** Frontier preflight and demonstration selection, scene admission,
the admission-member and scene policy triggers from migration 0029, point-map selection and exact
resolution in `exulanica/ingest/spine/artifacts.py`, and training input selection in
`exulanica/world_package/training_inputs.py` all use the shared predicate, and the Python guard
delegates mask currency to it. Scene mask declaration and resolution check current lineage and
refuse a missing declaration when a member requires masking. Selection first finds which captures
require masks, omits historical derivatives no longer needed after a deletion or a likeness
consent, and finds the matching current artifact even when an obsolete one sorts newest.
Required-but-missing masks refuse; no-person and mixed scenes keep the original bytes of members
that need no mask; an explicitly queued obsolete mask is refused rather than rebound. The point-map
trigger checks both the screening and the named masked source, checks a named mask even when
current inputs no longer require masking, and covers artifact UPDATEs as well as INSERTs. Clearing
content during purge is not a geometry operation and stays possible.

**Concurrency.** Person-region writes, consent writes, screening insertion and permission checks
take the same transaction advisory lock per workspace (`privacy_currency_lock`), so a subject-wide
consent cannot bypass a capture-only lock. The predicate takes a fresh snapshot after acquiring the
lock and requires READ COMMITTED; a repeatable-read or serializable snapshot is refused with a
serialization failure so the caller retries in a supported transaction. The consent writer
allocates `max(sequence)+1` before its insert lock, so the insert guard checks the allocated slot
after locking and gives the losing writer a serialization failure, while an exact receipt replay is
preserved. An ambiguous highest-priority sequence refuses until a resolving decision is appended.
Time-dependent consent is evaluated after waiting for the lock: the permission check is the
linearization point, not the eventual commit or a later delivery, and a permission does not promise
that a consent will never expire. The producer's read lock need not span image computation, because
its artifact records the inputs it used and later admission and write checks reject obsolete ones.
The workspace lock is deliberately coarse and can serialize otherwise independent captures.
Tombstone, purge and byte delivery keep their own ordering
([asset-read-currency.md](asset-read-currency.md)).

## Names and withdrawal

A withdrawn subject's name is removed at one boundary, resolved once per snapshot, in
`exulanica/graph/person_regions.py` for regions and `exulanica/graph/entities.py` for everything
else a graph payload carries: the entity keeps its row and loses its name, the naming assertion
keeps its row and loses its value, and the rename event keeps its actor and time and loses the name
key. A withdrawal stays visible as a withdrawal; what goes is the name. The test serialises the
entity and requires the name to be absent from it, so a surface added later fails there rather than
shipping. `person_consent_is_granted` answers whether one scope's receipt is held and carries no
withdrawal term, so every caller composes withdrawal itself.

An unlocated person, one the observation named without a box, is keyed off the photograph with no
region at all, a key no cell of the shared 16 by 16 `REGION_GRID` can produce, so a whole-frame mask
is never merged with a centred located person. The grid itself is shared with the vision stage's
person occurrences and with identity and naming memory, so changing it would re-key every
occurrence, rejection and naming decision.

## The review screen

The review panel reaches a reviewer in two places: the reconstruction inspector, under
click-to-evidence, and the journey that adds and admits a person's own photographs.
`web/packages/app/src/person-review-api.ts` is the only thing between the panel and
`exulanica/api/routes/person_consent.py`. The routes refuse to let a request name its own actor or
role, so every receipt records `actor_role: "owner"` and the account holder cannot manufacture a
subject's decision.

**Recording a consent is three requests, and that is the shape of the data.** A consent is
addressed to a subject, meaning a person, while the panel shows a region, an outline in one
photograph. A region a detector proposed has no subject, so the first consent against it creates a
subject, binds it to the outline with an ordinary `confirm` edit, and then records what the subject
agreed to. No server-side writer does the three in one.

**Nobody looked is not nobody there.** A photograph's `review_state` is `screened` when any region
has ever been proposed or recorded on it and `unscreened` otherwise, the same question the graph
payload asks, so a reviewer who deletes every false positive leaves the photograph screened. The
panel says "screened, and nobody was found" and "nobody has looked" as different sentences, and a
test renders both.

`POST /identity/subjects/link` and `POST /identity/subjects/unlink` link and unlink regions to a
subject, and `POST /person-subjects/{subject_id}/consents` records a consent decision; their
request rules are in [personal-admission.md](personal-admission.md#ordinary-api-batch-path).

## Training use is a separate consent plane

Training use (migration 0039, `training_use_consent`) is optional, default off, and scoped to one
package, one licensee, a set of model classes and an explicit term. It does not grant presence,
naming or likeness, and none of those grants it. `training_use` is not in `CONSENT_SCOPES`, because
presentation is decided per person and region while a training licence names a package and a
counterparty, and `person_consent_is_granted` is not reused, because it leaves withdrawal to its
callers. Training receipts have their own exact-term resolver: no receipts means denied, an expired
or future term is denied, a withdrawal cannot be undone by a later grant for the same subject,
package and licensee, a revocation applies to its exact terms and may be followed by another grant,
and a person's withdrawal overrides training grants. The package owner's opt-in is a receipt for
the reserved `package-owner` subject, required even when nobody is pictured, and a person's grant
never satisfies it. Export excludes an unconsented person's material unless masking is proven for
every exported representation, including geometry and source pixels. The export ledger, its locks
and the dataset profile are in [world-memory-package.md](world-memory-package.md).

This consent is not the scene training right, which decides whether a trainer may read an account
holder's own photographs ([personal-admission.md](personal-admission.md#scene-training-right)).

## A place's name is a separate consent plane

Presentation consent is about a person in a photograph and never releases anything to a model:
granting `naming` lets a name be drawn beside a person's outline, and a person's name goes to no
hosted model with or without it. A place's name is the account holder's own annotation, and where it
may go is their decision, asked for each place and each use. It follows the receipt model of this
contract: default no, each decision an appended receipt naming the account holder and the time, a
stop recorded as the next receipt rather than an edit, and the exact notice kept with the grant. The
rules, the storage in migration 0097 and the resolver are in section 4.5 of
[privacy-consent-threat-model.md](privacy-consent-threat-model.md).

## Limits and open questions

- **The no-geometry check has not measured a person.** A masked person must leave no geometry:
  after training, no Gaussian with meaningful opacity may sit on rays through a masked region in
  any training view. The count exists (`exulanica/ingest/masked_geometry.py`, run by
  `scripts/reference_instance.py evaluate-geometry`) and has run over one trained scene, the
  retained bowl, whose photographs had no recorded person regions
  ([record](evaluation/2026-09-08-bowl-retrospective-masked-geometry.json)). No retained record
  measures a trained scene containing a masked person, and the count is not part of the training
  evaluation bundle.
- **Consistency across views is not enforced.** A person confirmed in one photograph and present in
  others must have a region in each, or one missed frame reconstructs them; nothing asks the
  reviewer about the other photographs. Reflections and screens are asked for by the vision prompt
  but not checked.
- **No subject-facing consent.** The photographed person has no way to answer for themselves; every
  receipt is the account holder's. The column and the receipt already admit `subject`, so adding
  that answer is a route and a credential, not a schema change. Until it exists, presentation
  consent records the account holder's decisions, not the subject's.
- **A revoked consent produces another build; it does not purge the old one.** Geometry built while
  somebody was `shown` stays until the ordinary withdrawal path reaches it.
- **Generative fill of masked areas is out of scope.** Masked areas are neutral fill, and the status
  says so. Automatic re-identification of the same person across photographs would need embeddings
  and is excluded by the biometric rule above.
- **Open: a withdrawn person's other claims.** Only the naming value is redacted from the graph;
  whether a withdrawn person's other assertions should travel is an undecided product question about
  the ledger.

## Evidence

- [First pass](evaluation/2026-09-05-person-consent-first-pass.json): the masking chain from region
  to masked derivative to depth, pose staging and the database's own refusal of a point map over the
  original, executed against PostgreSQL.
- [Screening currency acceptance](evaluation/2026-09-08-complete-screening-currency.json) and
  [verification](evaluation/2026-09-08-verification-screening-currency.json): the 0040 binding over
  generated labelled media, the real mask stage and executed SQL mutation controls.
- `tests/test_person_masking_end_to_end.py`, `tests/test_person_detection_screening.py` and
  `tests/test_person_presentation_consent.py` hold the rules above.

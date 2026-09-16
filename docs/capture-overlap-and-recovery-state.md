# Capture overlap and recovery state

Status: 2026-09-16, recovery states shipped; the overlap verdict failed its held-out check.

The place record, its five recovery states and its read seam are in place (migration 0063,
`exulanica/graph/places.py`). The overlap verdict (policy `exulanica.capture-overlap-policy/v1`)
reproduces the four measured capture outcomes, but only inside a narrow threshold window. It is not
monotone in spacing at its threshold, and it **failed its held-out check**, so it may predict and
give advice but it is **not authorised to refuse a set**.

## What a regular person gets

Most photographs a person takes of something will not rebuild into a 3D place. Before this work,
a set like that was an absence: the product had nothing to say about it. Now it is a room of its
own photographs, with a sentence saying why it did not build and what to do next:

> Your photographs are kept here as they are. A rebuild was tried and didn't make a 3D place. None
> of the 6 photographs could be placed together. Walk around it and take one every few steps, so
> each photograph overlaps the one before it.

That sentence is built from the real receipt of a real run over six real photographs. The advice
never asks for a number of photographs, because the measurement below shows that overlap decides
and count does not.

The second half of the work was meant to tell the person this *before* anything is spent. That
half exists, it is cheap, and it is honest about its limits. On the one held-out set it would have
turned away a set that rebuilt and trained, so until a better policy passes a held-out set its
answer is advice and nothing more.

## What a verdict is, and what it is not

A **verdict** is a prediction made before any run: `exulanica.capture.assess_capture_set`
measures the photographs and returns a `CaptureVerdict` whose `predicted_ceiling` is the best
state the measured overlap leaves open. A **recovery state** is an outcome: what happened to the
set. The two are different types on purpose:

* `CaptureVerdict` has no `recovery_state`. Its only path to a state is `refusal()`, which returns
  `insufficient_overlap` or `None`, and returns `None` whenever the policy is not authorised to
  refuse.
* `RecoveryOutcome` is built only by `outcome_from_pose_receipt`, from a run's own receipt.
* The schema repeats the split. A state change names a basis, and only a `verdict` basis may
  move a record without a run, only from `not_attempted` to `insufficient_overlap`, only when the
  record's own verdict refuses the set, and only when that verdict's policy says
  `refusal_authorised: true` in its own digest-bound bytes.

The ceiling never goes above `registered_scene`. A pairwise match graph measures whether
photographs can be placed together. It says nothing about whether training will cover held-out
views: the 210-photograph volcanic set registered every photograph and was refused training on
coverage twice.

A refusal is a fact about the photographs as one policy measured them, which is why it may be
recorded without a run. A set predicted `registered_partial` is refused as well, because the pose
gate turns a partial registration into no cameras at all. The run would spend everything and
produce a correct but empty result that looks exactly like a downstream bug.

## The five states

| State | Written from | Meaning |
| --- | --- | --- |
| `not_attempted` | the record's creation | Nothing was refused and nothing was run. |
| `insufficient_overlap` | an authorised verdict, or a pose receipt that placed nothing | The photographs do not overlap enough to be placed together. |
| `registered_partial` | a pose receipt only | Photographs were placed and the pose gate did not accept the set. Usually too few were placed; the bowl's 40-photograph group placed 40 of 40 and was refused on camera translation. |
| `registered_scene` | a pose receipt only | The pose gate accepted the set. |
| `trained_radiance` | a training receipt only, with a live delivered `gaussian_splat_scene` | A trained scene was delivered for the set. |

A `withdrawal` basis may only lower a state, and must name a tombstone in the same workspace.

## The measurement the lane is calibrated against

Measured 2026-09-11 by rebuilding subsets of the 210-photograph Montserrat volcanic sample
(Mike R. James and Stuart Robson, CC0) on the CPU with pycolmap 4.2.0:

| Photographs | Spacing as first recorded | Registered | Pose gate |
| --- | --- | --- | --- |
| 6 | ~70 deg | 0 of 6, "No good initial image pair found" | no scene |
| 12 | ~11 deg | 7 of 12 | refused, 0.583 under the 0.8 floor |
| 12 | ~7 deg | 12 of 12 | accepted, 0.40 px |
| 210 | ~1.7 deg | 210 of 210 | accepted |

**Two corrections, both from the receipts rather than from arithmetic.**

The photographs each run used are named in its pose receipt by SHA-256, so the index lists
below are read, not reconstructed. The script that drew them (`small_capture.py`) keeps only the
first 113 sorted file names, the dark-backdrop series, so a list stepping through all 210 could
not have been what ran. Indices are positions in the sorted file names:

| Run | Receipt | Indices |
| --- | --- | --- |
| six | `8280728d5c8c...` | 0, 22, 45, 67, 90, 112 |
| twelve, "11 deg" | `0d4194430b77...` | 0, 4, 7, 11, 15, 18, 22, 25, 29, 33, 36, 40 (registered: 0, 4, 7, 11, 33, 36, 40) |
| twelve, "7 deg" | `e7a9145ad066...` | 0, 2, 4, 7, 9, 11, 13, 15, 17, 20, 22, 24 |
| 210 | `f44362e2840e...` | all |

The degree labels in the first table assumed those 113 frames cover one turn. The accepted
210-camera receipt shows otherwise. The dark series is a turntable at about 10 degrees a frame,
in rings of about 36 frames, with the rock turned between series. So the true spacing between
neighbouring optical axes is 20 to 30 degrees for the set that registered, 30 to 40 degrees for
the set that registered 7 of 12, and 83 to 140 degrees for the six. The ordering the table
teaches is unchanged: overlap decides, count does not. The numbers are about three times larger.
`tests/fixtures/capture-overlap/volcanic-cameras.json` carries each camera's direction as
integers, and `measured-runs.json` carries the lists with their receipt digests.

## The descriptor

`exulanica/capture/overlap.py`, standard library and Pillow only, integers from the decoded
pixels onward:

1. Decode with Pillow, refuse the four mirrored EXIF orientations and any pixel format that is not
   exact 8-bit, apply `ImageOps.exif_transpose`, and resize so the long side is 256 pixels.
2. Find corners as the minimum of four directional differences (a straight edge has no difference
   along itself), keep the 160 strongest after 5-pixel suppression, and describe each with 128
   comparisons from a fixed pattern derived from SHA-256.
3. Score a pair as the number of mutual nearest matches within 32 bits, passing a 0.8 ratio test,
   that moved more than one pixel and share a 32-pixel cell and a 32-pixel step with another such
   match. A match that did not move is dropped, because the turntable matches in every pair and
   carries no parallax.
4. Every pair is scored. Pruning with a coarse first pass was measured and lost real edges.

A photograph that cannot be measured carries a reason (`unreadable`, `undecodable`,
`decompression_limit`, `mirrored_orientation`, `unsupported_pixel_format`, `too_small`) and is
not a node. It is counted in the set, as the pose gate counts every member, and credited to the
largest group, so it can raise a ceiling and never causes a refusal. HEIF is not decoded here;
a HEIF photograph is `undecodable` under this policy.

The descriptor parameters were chosen on the pairwise angle curve of frames 0 to 112, where the
accepted receipt gives every pair's true angle. Resolutions of 192 to 512 pixels, 64 to 160
corners, two pattern shapes, three verification rules and a coarse gate were compared on that
curve. That curve contains the photographs of the four rows, so **the rows are not independent of
the design choice**. Frames 113 to 209 are a different series and were not used to choose
anything.

## The policy and its threshold

`OverlapPolicy` is recorded whole in every verdict and bound by its digest:

* `edge_min_score` = **8**. The rule: maximise the true-edge rate on calibration pairs at most 21
  degrees apart (the neighbour spacing of the set that registered 12 of 12) minus the false-edge
  rate on pairs at least 90 degrees apart. J = 9453 per ten thousand at 8, against 9395 at 7 and
  9305 at 9, over 6328 pairs (446 near, 2894 far). On the validation series the same rule gives
  8482 at 8, and its maximum would have been 8583 at 7.
* `registration_floor` = **4/5**, the pose gate's own `min_registered_fraction`, as an exact
  ratio.
* `refusal_authorised` = **false**, for the held-out result below.

At the threshold, pairs link at these rates by true angle (calibration series): 100% under 10
degrees, 95% at 10 to 20, 49% at 20 to 30, 11% at 30 to 40, and 2 to 4% beyond.

## The four rows, with their margins

A margin here is the range of edge thresholds over which the verdict stays the same.

| Row | Outcome from the receipt | Verdict at 8 | Holds for | Margin |
| --- | --- | --- | --- | --- |
| six | `insufficient_overlap` (0 of 6) | `insufficient_overlap`, scatter; no pair scores above 4 | 5 and up | three steps below, none needed above |
| twelve, 30 to 40 deg | `registered_partial` (7 of 12) | `registered_partial`, 2 groups, largest 4 | 7 to 25 | **one step below**: at 6 it recommends a run |
| twelve, 20 to 30 deg | `registered_scene` (12 of 12) | `registered_scene`, one chain | 1 to 9 | **one step above**; its weakest neighbour pair scores exactly 8 |
| 210 | `registered_scene` (210 of 210) | `registered_scene`, one chain | 1 to 15 | seven steps above |

All four agree with their outcomes only for thresholds 7, 8 and 9. The two twelves, which differ
only in overlap, are separated. They are separated by one step of threshold on each side, and a
row that passes by one step is reported as passing by one step.

## Monotonicity

The requirement: as spacing widens, the verdict must never turn a refusal back into a run. The
test fixes a start and a count (6, 8, 12 or 16), widens the frame step one at a time, and counts
the sequences in which a refusal becomes a run again:

| Threshold | Calibration (452 sequences) | Validation (388 sequences) | All four rows right |
| --- | --- | --- | --- |
| 7 | 141 | 27 | yes |
| **8 (policy)** | **89** | **11** | **yes** |
| 9 | 16 | 4 | yes |
| 10 | 0 | 2 | no: the set that registered is refused |
| 12 | 0 | 0 | no |

**By the lane's own definition, the verdict at 8 is a fit.** No threshold is both monotone and
right about the two twelves. Most of the reversals come from chance edges, pairs of coincidental
matches that pass the 2% far-pair false-edge rate and push a set over the four-fifths floor. They
are not mainly the turntable backdrop: of the far edges inside reversed sets, 242 join frames of
one ring and 74 join different rings.

Run rate by each set's true spacing to link four fifths of it, at the policy threshold:

| Spacing (deg) | 5-10 | 10-15 | 15-20 | 20-25 | 25-30 | 30-35 | 35-40 | 40+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calibration | 100% | 100% | 79% | 84% | 16% | 7% | 18% | 0 to 9% |
| validation | 100% | 100% | 34% | 52% | 3% | 0% | 3% | 0% |

The transition sits between 20 and 30 degrees, where the measured runs put it. It is not clean,
and in the validation series the 15 to 20 degree band runs less often than the 20 to 25 band.

## The held-out set

The chili salmon bowl (Charin Rungchaowarat, CC0), all 51 photographs, was measured once, after
the policy was fixed. Its outcome is read from the retained receipts, not assumed: pose receipts
`292d697b...` and `d3563ac2...` placed 51 of 51 and were accepted, and the set trained into the
delivered scene `docs/retained-reference-workflow.md` describes.

Policy v1 says `registered_partial`: 5 groups, largest 20, 5 photographs overlapping nothing, 67
edges among 1275 pairs, refused from threshold 7 upward. **It would have turned away the one real
set that trained.** Only 25 of the 50 consecutive handheld shots link at the threshold. Handheld
photographs change scale and roll between shots, and a descriptor chosen on a fixed-camera
turntable is invariant to neither.

So `refusal_authorised` is false, the schema refuses a verdict-based refusal under it, and the
read seam shows such a verdict's instructions as `advice` and never as a record's `reason`. The
bowl is now spent as a held-out set: any policy chosen after seeing this result needs a fresh one.

## Cost

The 210-photograph verdict (210 decodes, 21,945 pair scores) took 36 to 47 seconds of wall clock
on this machine across runs under varying load from other work, 69 to 82 MiB peak resident
memory. The bowl took 3.2 to 3.6 seconds. Nothing else is involved: no reconstruction, no
process, no device. `tests/test_capture_overlap.py` refuses process creation for the whole
measurement, checks that nothing heavy was imported during it, and checks in a fresh `-I`
process that importing the package and running a verdict loads none of torch, numpy, cv2,
pycolmap, psycopg, `exulanica.db`, `exulanica.store`, `exulanica.evidence`,
`exulanica.reconstruction`, `exulanica.ingest` or `exulanica.graph`. `pyproject.toml` places
`capture` beside `reconstruction` in the layer list and forbids it the storage, evidence and
numeric stack, and `lint-imports` enforces both.

## Determinism

The verdict record holds integers, strings, booleans and nulls, and no clock. `canonical_json`
accepts it, and a float injected anywhere is refused. The same photographs give byte-identical
digests in one process, twice, and in two processes with `PYTHONHASHSEED` 0 and 4242. The set is
ordered by ref, so the order photographs are given in does not matter. Not verified: identical
bytes across platforms or Pillow builds. The JPEG draft scale and the `BOX` resize compute their
coefficients in floating point inside Pillow, so the descriptor profile names what was measured
and does not claim more.

## What could not be measured: one side uncovered

Whether a chain of photographs comes back round is the natural way to say "one side of the subject
has no coverage". Two readings of it from the thresholded graph were measured against turntable
arcs of known extent. Reading the middle layer's spread misread 7 of 23 determined arcs, and
removing a middle photograph and checking whether the ends still connect misread 6 of 23. A
single chance edge makes an open arc look closed. So the graph does not report closure, and the
vocabulary entry `one_side_uncovered` exists but no current policy emits it. A pose receipt's
cameras could measure it after a run.

## The instruction vocabulary

`exulanica/capture/instructions.py`, `exulanica.capture-instructions/v1`. Closed, keyed to the
graph fault, and built only from counts the graph produced. Every entry leads with what the person
gets.

| Key | Shape | Example rendering |
| --- | --- | --- |
| `too_few_photographs` | too small to form any pair | "There is only one photograph, and a place is built from photographs that overlap one another." |
| `no_overlapping_neighbours` | neighbours too far apart end to end | "None of these 6 photographs shares enough with any other: they were taken too far apart." |
| `separate_groups` | islands with nothing bridging them | "These photographs fall into 2 separate groups, and nothing joins one group to the next." |
| `mostly_unconnected` | one group, too many left outside | "Only 2 of these 6 photographs overlap one another. The other 4 don't overlap anything..." |
| `some_unconnected` | advisory on a buildable set | "One of them doesn't overlap anything, so it won't be in it." |
| `one_side_uncovered` | one side has no coverage; not emitted (see above) | "They form one line whose two ends don't meet..." |
| `unreadable_photographs` | advisory | "2 of them couldn't be read, so they weren't compared with the others." |
| `run_placed_none` | a pose receipt that placed nothing | "None of the 6 photographs could be placed together." |
| `run_placed_some` | a pose receipt below the gate | "Only 7 of the 12 photographs could be placed together, which isn't enough to build it." |

Every refusal's action is the same sentence, or its gap-filling variant: "Walk around it and take
one every few steps, so each photograph overlaps the one before it."

## The place record in the schema

`exulanica/migrations/0063_place_recovery_state.sql`:

* `place_record`: an allocated `record_id`, the exact set's `member_digest` (unique per
  workspace), `member_count`, `recovery_state` (a check over exactly the five), `state_seq`, and
  the verdict whole or absent. The verdict is stored as its canonical bytes, the same document as
  jsonb, its SHA-256 (checked over the bytes in SQL, as 0030 checks a withdrawal receipt), and
  integer columns a constraint holds equal to the document.
* `place_record_member`: one row per capture id, append-only, admitted only for a live photograph
  nobody has withdrawn, and at most `member_count` of them. At commit, a deferred check requires
  exactly `member_count` members and a verdict that names exactly those captures.
* `place_record_state_event`: append-only, `seq`, `from_state`, `to_state`, a basis in
  (`verdict`, `pose_receipt`, `training_receipt`, `withdrawal`), and exactly the evidence that
  basis names. The guard requires the record's current state and sequence, refuses a withdrawn
  set, and requires a receipt to be a live artifact of the right kind about a scene whose members
  are exactly the record's. The event is applied to the record in the same statement, and a
  direct update of the state is refused.
* `tombstone_blocks_place_record(p_workspace, p_record)`: `language sql volatile`. It is true when
  the membership is empty or any member is deleted, tombstoned or person-withdrawn, which mirrors
  `tombstone_blocks_scene` as 0030 left it. Every read asks it in its `where` clause.
* Every table is under `enable` and `force` row-level security with `ws_isolation`. There are no
  partitions. Every guard asserts the workspace context before it reads anything.

**Alternatives rejected**, as the migration header records them:

* A column on `reconstruction_scene`. A scene row is written once a receipt exists, and a refused
  set has neither.
* A column on `place` or `place_version`. A version needs an admitted scene and a frame.
* A column on `reconstruction_scene_job`. A job exists only once a run is queued, and a refusal
  would read as a failed job.
* A member array. No cascade reaches through an array.

The identity is allocated, as `place` allocates its own, rather than derived from the members as
a scene's is. Nothing in SQL recomputes `member_digest`, the same arrangement 0024 accepted for
scenes.

## The read seam

`exulanica.graph.places.place_record(connection, workspace, record_id, store)` returns
`PlaceRecord` or `None`. `None` covers a missing record, one in another workspace, and one any
member of which was withdrawn. The record carries:

* the member photographs, each through `_viewer_photograph`, the same viewer route scene reads
  use. Each is `available` with a digest-bound href, or `unavailable` with a reason. All six real
  photographs in the test are served.
* the verdict, `verified` only when its bytes reproduce its digest and parse as canonical, else
  `invalid` with no instructions.
* the reason, for `insufficient_overlap`, `registered_partial` and any withdrawal. A pose
  receipt's reason is `stated` only when its bytes are in the store and agree with the event:
  the same photographs by SHA-256, the same counts, the same acceptance. Otherwise it is
  `unavailable` or `invalid`, with no sentence.
* `advice`: a verified verdict's instructions when the state does not rest on that verdict.
* the full state history.

`place_record_ids(connection, workspace, state)` lists readable records in a state. Nothing here
changes what `exulanica/graph/world_read.py` serialises, and that file does not import this
package.

## What is not here

* **No writer outside SQL.** Records and events are written by inserting rows, and the schema
  enforces every rule above. No pipeline stage writes them yet. That belongs to the ingest side,
  which this lane does not own.
* **A withdrawal event's tombstone is checked only for existence in the workspace**, not for being
  the cause of the lowered state.
* **No route.** The read seam has no HTTP surface yet.
* **Not built:** anchors, frames, scale, precincts, or the rendered form of a refusal.

## Evidence

* `tests/fixtures/capture-overlap/calibration.py.txt` and `calibration.log.txt`: the timed
  210-photograph verdict, the threshold curve, the four rows with their windows, the sweep and the
  two closure readings.
* `tests/fixtures/capture-overlap/held-out-bowl.py.txt` and `held-out-bowl.log.txt`: the
  held-out measurement and the bowl's receipts.
* `tests/test_capture_overlap.py`: the rules, the vocabulary, the unavailable reasons,
  determinism, cost, the rows, the sweep and the held-out failure, on the real photographs.
* `tests/test_place_recovery_state.py`: the room on six real photographs and their real receipt,
  the withdrawal cascade, the non-owner role, and every refusal.
* `tests/test_capture_overlap_migration.py`: row security from the catalog, guard order, the
  predicate's shape and the vocabularies.

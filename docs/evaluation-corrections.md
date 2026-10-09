# Corrections and negative results in the evaluation records

This reference collects what the project's [evaluation records](evaluation-methodology.md#0-how-the-project-measures)
say against themselves: claims they withdrew, checkers that passed without testing, targets missed and
left missed, and the limits each record states. Each story names the record that holds it, so every
quoted sentence and figure below can be read at its source. How a measurement is pre-registered,
recorded and bound is owned by [evaluation methodology](evaluation-methodology.md).

Exulanica builds worlds for AI agents: people make a world, open models are the minds of the beings in
it, and the engine checks every decision and stores it, so a run replays without calling a model. The
project keeps evidence about its own work the same way. Measured work is written up in
`docs/evaluation/`, one record per execution: what ran, on which code, which earlier record it follows,
what it found and what it does not show. Each record is stored beside its SHA-256 digest, a fingerprint
of its exact contents, and a test (`tests/test_retained_evaluation_records.py`) recomputes every digest
and checks that each declared predecessor still has the digest it was bound with. The records are
treated as immutable. Some early ones were amended in place while their work was under way, and one
says so in its own text (story 7); later findings are written as separate records that name what they
correct.

That is why the corrections matter: an overclaim, a broken checker or a missed target stays on file
next to the record that caught it, and a reader can follow the chain from one to the other. The nine
stories below come from those corrections, negative results and stated limits.

## Nine stories from the records

### 1. A specification is not enough to make a world

A caller can ask for a world by its specification, and the request is checked before anything is
generated: an unknown setting, a level that does not exist or a value out of range is refused by
name. The route's record still lists what it does not solve, starting with the fact that a
specification is not enough to make a world: "Measured over 40 seeds with every layout value
bound, 15 generated." ([2026-09-19-a-world-you-can-ask-for.json](evaluation/2026-09-19-a-world-you-can-ask-for.json)). A follow-up
record counted the refusal a caller is most likely to meet: of the 1,920,001 lengths in millimetres
the check admits for a side of a city, the terrain stage accepts 16, those ending on a whole 128 m
tile, a gap found by reading the route back rather than by a failing test
([2026-09-19-a-world-you-can-ask-for-v2.json](evaluation/2026-09-19-a-world-you-can-ask-for-v2.json)).

### 2. A bar set in advance, and missed

Scenes trained from real photographs were judged against thresholds written into each training
request before it ran. A volcanic rock photographed from all sides never met its coverage bar, the
share of the test photographs (ones kept back from training) that the trained scene fills in
solidly: "two runs measured coverage 0.73 and 0.63 against the predeclared 0.75"
([2026-09-05-real-reconstruction.json](evaluation/2026-09-05-real-reconstruction.json)). The record names the cause, the rock was
turned over between series against different backdrops, and no trained scene of it is delivered,
only a point cloud estimated from the photographs. The same record lists 17 defects that only real runs
exposed, each with its fix and how the fix was checked.

### 3. Failed in both arms, and left failed

One stage joins photographs taken from a single spot into one view, and must refuse a pair when
the camera moved or the scene changed between shots. Its second version was written down in
advance, frozen, and measured once on synthetic photographs set aside for the purpose, in two arms:
exact lens data, and lens data up to 3 percent off. It failed in both arms because one pair was
joined across a change ([2026-09-24-standpoint-join-v2-outcome.json](evaluation/2026-09-24-standpoint-join-v2-outcome.json)); version 3
joined no pair across a move or a change, yet failed in both arms too, because it named the reason
for a refusal wrongly or too rarely ([2026-09-25-standpoint-join-v3-outcome.json](evaluation/2026-09-25-standpoint-join-v3-outcome.json)).
Neither result was reworked afterwards, under the rule written before the measurement: "A gate that
fails is reported as failed; nothing is tuned against the held-out split, and it is not measured a
second time." ([2026-09-24-standpoint-join-v2-preregistration.json](evaluation/2026-09-24-standpoint-join-v2-preregistration.json)).

### 4. A checker that passed without testing

Birds in a world fly out from their home perches and must be back on them when each episode of
simulated time ends. The first run of the flight check reported PASSED, and its record says why
that meant nothing: "The first run reported PASSED because its checker never tested either" of the
two rules that failed ([2026-09-25-flight-bounds.json](evaluation/2026-09-25-flight-bounds.json)). The windows it checked
never crossed an episode's end, so the list of late birds it relied on was always empty, and it skipped the move
into each episode's first step, where in the crowded trees 141 of 864 bird episodes had ended away
from home and each bird was put back on its perch in one jump through the crowns. After the birds
were given routes home, the next record passed every judged rule on 12 seeds kept back for judging,
in 4 worlds ([2026-09-25-flight-bounds-v2.json](evaluation/2026-09-25-flight-bounds-v2.json)), and a third judged those seeds
again with a checker that shares none of the flight's placement code, labelling itself a
re-judgment because the seeds were already spent
([2026-09-26-flight-independent-check.json](evaluation/2026-09-26-flight-independent-check.json)).

### 5. A rule that was described but never built

Three timing records for the worker process that computes the birds' flight each said that a
timed run was thrown away if the machine was less than half idle while it ran. An erratum found
that nothing did the throwing away: the idle gate only recorded samples and left the discarding to
the timing scripts, which did none, so "the rule was not implemented"
([2026-09-26-flight-worker-erratum.json](evaluation/2026-09-26-flight-worker-erratum.json)). It then checked the 7 runs themselves,
mean idle 59.3 to 77.4 percent and none below 50, and found that no outcome changes. The same
erratum marks a cause the third record gave for a 30.9 ms pause as inferred, not measured.

### 6. A reassuring number, withdrawn

A measurement of a generated town's residents nearly reported 6 to 10 people outdoors at midday on
one tile of a street. The figure was withdrawn before it was sent: that tile's walking paths fall
into three pieces, and only 27 of its 64 residents can get from home to work, against 196 of 196
across five tiles. The cut at the tile's edge is a real effect, and it "produced a number that
would have read as reassurance about a street"
([2026-09-19-society-destination-supply.json](evaluation/2026-09-19-society-destination-supply.json)). The same record caught a ratio of
0 of 97 on an end tile that read as nobody able to reach work and meant nobody had work, found only
because the script crashed on a person with no home.

### 7. A version that nothing compared

Raising the privacy policy's version was meant to stop photographs screened under the old policy
from being used to build 3D geometry until they were screened again. An earlier version of the
record claimed the raise did that; it did not, because nothing compared the version, and all 51
bowl photographs were still reported as allowed. The comparison was added with a test that ties
the database check to the policy version, and the record gives its reason for keeping the mistake
on file: "a digest that nothing compares is the same as not having one"
([2026-09-05-person-consent-first-pass.json](evaluation/2026-09-05-person-consent-first-pass.json)). It also admits that for several
commits the change let geometry through over a person nobody had yet decided about, a net loss for
privacy that was then fixed.

### 8. A photograph that looked like 3D

While reconstruction work was being reviewed, a photograph appeared to float in the world. It was a
flat photograph with softened edges, placed in the scene for presentation and not reconstructed
geometry, so it misled anyone judging what had been reconstructed. The review view was changed to
leave such photographs out and show a plain panel saying that no 3D reconstruction is loaded, which
the record defines as "An honest unavailable state." and not as progress
([2026-09-05-source-presentation-correction.json](evaluation/2026-09-05-source-presentation-correction.json)). The same record marks its
objective as not complete and states that neither reference workspace held a reconstruction.

### 9. A street that failed, and an answer that did not count

The district shipped for walking, built from New York open-data building footprints, was scored as
shipped against the project's visual gate and failed: "54,992 walking-surface and facade triangles
were drawn and 54,992 of them are untextured"
([2026-09-15-flatiron-owned-district-baseline.json](evaluation/2026-09-15-flatiron-owned-district-baseline.json)). A later generated street
textured all 7,799 of its street and facade triangles, yet two of its eight measured checks failed,
so its record scores nothing
([2026-09-19-corridor-composed-world-judgement-refused.json](evaluation/2026-09-19-corridor-composed-world-judgement-refused.json)). Its ninth check, a
person's answer to whether the street looks finished and lived in, was refused because the
judgement lacked what the rubric requires and the asking strayed from the rubric's words; the
record does not even report the answer, since "an answer obtained outside the rubric is not an
answer". It also notes that a first write of the judgement file carried a picture digest with 16
real characters and 48 invented ones, caught by a check that printed the real digest beside it.

## The records in numbers

Counted on 2026-10-09 at commit 0bc52e2c by `scripts/count_evaluation_records.py`, which only reads the
record files and prints its counts:

- 256 records, dated 2026-09-04 to 2026-10-09 by file name. For all 256, the stored digest equals the
  SHA-256 recomputed from the record's contents.
- 155 records name at least one other record by path and digest, and each of the 268 links between
  records matches the digest of the record it names.
- 29 records carry a field named for a correction, a corrected value or an erratum.
- 99 records carry a list named `limitations` or `limits`, holding 493 items.
- 11 records have a top-level verdict or status that begins with FAIL.

Counts match field names, so a correction or a limit stated only in prose is not counted, and a name
match can include a field that names something else.

## How the product keeps this honest

The product applies the same discipline to the worlds it runs. Deterministic checks decide: the
engine validates each decision made for a person in a world, and each proposed change, against
declared rules before it takes effect, and the route in story 1 refuses a bad world specification
by name. Models only propose: an open model deciding for a person chooses among the actions its
decision contract allows, and every accepted decision is stored with the model that served it and
the observation it saw. Replays need no calls: a stored run replays exactly from those records
without calling a model, so two runs from one saved world compare fairly and every decision can be
inspected afterwards. The evaluation records hold the team's own claims to the same rule: a figure
is kept with the code, inputs and limits that produced it, and a mistake, once found, is written
down beside what it corrects.

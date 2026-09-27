# Society experiments

The society experiment surface records controlled comparisons over an existing
`exulanica-society/v4` society. It freezes the exact immutable input rows used by both arms and
reserves development attempts. Preparing or reserving a record does not run a simulation. A
comparison of the open models that decide for a saved world's people, over its
`exulanica-society/v2` society, is a record family of its own:
[comparisons of models](#comparisons-of-models).

## HTTP surface

All routes are scoped by the authenticated session's workspace, by the world the authored version
belongs to, which each request names as a `world_id` query parameter, and by the authored version in
the path. A definition is read only in the world it binds.

| Method and path | Permission | Result |
| --- | --- | --- |
| `POST /world/versions/{version_id}/society/experiments` | `world.write` | Records one immutable definition |
| `GET /world/versions/{version_id}/society/experiments/{experiment_id}` | `world.read` | Reads the compact definition |
| `POST /world/versions/{version_id}/society/experiments/{experiment_id}/attempts` | `world.write` | Reserves one development attempt |
| `GET /world/versions/{version_id}/society/experiments/{experiment_id}/attempts/{attempt_id}` | `world.read` | Reads compact attempt status and a terminal result or failure |

The client supplies idempotency UUIDs, immutable input sequence numbers, explicit workload bounds,
and a supported intervention identity. The server resolves the society and full input documents.
It verifies those documents through the configured `SocietyRuntime` authority before recording or
reading an experiment. The request cannot supply an input document, definition document,
checkpoint, execution evidence, result, or failure record.

An experiment or attempt under the wrong workspace, version, or parent experiment is an unknown
reference. A withdrawn source makes its historical experiment unavailable rather than preserving
access to stale geometry or rights.

## Definitions

The supported definitions are:

| Intervention | Input rule |
| --- | --- |
| `noop` | Baseline and treatment name the same genesis input |
| `add_rest_amenity` | The treatment is the next input and adds exactly one enabled authored rest target backed by the reviewed marker-plate asset |

The stored definition binds the source society, world and authored version, the treatment's
authored cursor, both immutable input sequence and digest pairs, the deterministic routine, the
development and held-out seed commitments, and the predeclared metrics. Public reservation accepts
only a seed from the committed development split. The held-out split cannot be reserved through
this HTTP surface.

Work is bounded to a population from 1 through 256, warm-up and follow-up lengths from 1 through
1,440 ticks each, and at most 500,000 person-ticks under the definition's paired-run accounting.
Definition records are limited to 256 KiB.

## Attempt lifecycle

An attempt reservation is an append-only fact. Its initial status is `incomplete`, which means no
terminal outcome has been recorded. Internal bounded execution may add one sealed checkpoint and
then exactly one `completed` or `failed` outcome. Reusing an experiment or attempt UUID with the
same canonical content is idempotent; reusing it with different content is a conflict.

The HTTP request path does not prepare checkpoints, advance either arm, call a worker or model, or
finalize outcomes. Those operations remain internal repository and deterministic-core work.

## Compact reads

Attempt reads return the definition, seed, checkpoint, evidence, result and failure digests that
exist for the record. A completed result includes each arm's raw metric numerators and denominators,
safety counts, evidence counts and digests, and exact signed comparisons. A failed result includes
the bounded server-defined failure code and detail. The response never includes checkpoint state or
full execution evidence.

There is no evidence download or portable experiment package endpoint. A digest in the compact
response identifies a persisted artifact but does not by itself provide an export surface.

## Independent read-only consumer

[`scripts/society_experiment_result_client.py`](../scripts/society_experiment_result_client.py)
is a small consumer of the two GET routes. It imports no Exulanica implementation. Its caller
provides an HTTP client that already owns base URL, authentication, timeout and transport policy,
then supplies the world the version belongs to and the three explicit resource identifiers:

```python
outcome = read_experiment_result(
    http,
    world_id=world_id,
    version_id=version_id,
    experiment_id=experiment_id,
    attempt_id=attempt_id,
)
```

The consumer requests the definition projection first and the nested attempt second, each in the
named world. It validates the definition's world, the path identities, lifecycle combination, digest syntax and cross-response bindings before
exposing metrics. For a completed result it independently checks the supported result profile and
canonical result digest. The compact definition digest is only an identity binding because the GET
response does not contain the full canonical definition document.

The consumer requests `Accept-Encoding: identity` and refuses a response carrying a nonidentity
`Content-Encoding` before reading its body. Identity-encoded response bodies are read in bounded
chunks through byte ceilings before JSON buffering. An over-limit or compressed lazy response is
closed without consuming the remainder. The ceiling governs work performed through the supplied
lazy streaming transport; it cannot undo buffering a caller or upstream transport completed before
the response context was returned. The consumer uses only GET, rejects duplicate JSON fields and
does not request checkpoint state or execution evidence.

The outcome status is one of `valid`, `invalid_pair`, `incomplete`, `failed` or `unavailable`.
Metric numerators and denominators remain integers exactly as served. A missing or zero denominator
marks that metric unavailable; it is not interpreted as zero effect. `left_minus_right` means the
stored treatment arm minus baseline comparison. The consumer makes no significance, held-out,
external replay, production authentication or real-human-effect claim.

## Browser result view

An authenticated saved world exposes **Recorded comparison** from the World menu. The view fixes
the authored version to the active saved-world entry and asks for the experiment and attempt UUIDs
printed on an existing record receipt. It then uses the two GET routes above to verify and present
that one compact result. The browser does not offer a record list, preparation, reservation,
execution or finalization control.

The view presents stored baseline and treatment fractions, signed server-recorded deltas, safety
summaries, exact record bindings, unsupported metrics, lifecycle failures and unavailable records
without reinterpreting them. Closing the view cancels its active read. Opening another identity
supersedes the prior read, so a late response cannot replace the current result.

## Local reserved-attempt execution

The local experiment runner accepts a current server session and one exact already-reserved
development attempt identity. It rejects held-out phases and seeds before checkpoint preparation,
arm computation or explicit abort; a held-out reservation remains incomplete. Trusted host
composition must supply current permission to execute the development reservation. The
reservation's `created_by` field remains attribution and does not grant execution. The runner also
applies the configured society runtime's current input authorization, including workspace/version
registration, immutable stored-input equality, current environment-source operation rights and
withdrawal state, required byte integrity, authored-source validity, frame and affordance registry
bindings, and reviewed-asset availability.

Checkpoint preparation and paired-arm computation run outside database transactions. Checkpoint
and result replay use an open idle autocommit connection before each short append transaction, as
required by the repository. Each phase reloads the reservation and rechecks execution and source
authorization. Checkpoint, completion and failure appends recheck execution permission again after
taking the attempt lock, including after result replay. A crash, missing authorization or other
exception before a terminal append leaves the attempt incomplete and retryable. A retry reuses the
exact sealed checkpoint. An explicit operator abort records a bounded development failure.
Competing runners may duplicate deterministic computation, but attempt locking and the append-only
outcome allow only one terminal record.

Only a pair with canonical arm evidence is recorded as completed. A core `invalid_pair` refusal has
no arm evidence, so this runner records it as a failed `execution_refused` outcome with the bounded
core refusal code and detail. The compact read schema can represent `invalid_pair`, but this runner
does not fabricate evidence or persist that state as a completed result. Execution remains a local
composition capability; there is no HTTP execution route, queue discovery or browser launch control.

## Comparisons of models

A comparison runs the same simulated hour of a saved world's purposeful society
(`exulanica-society/v2`, the one engine whose table row states `comparisons`) once for each of its
arms, and scores each run from what the engine recorded. Every run starts from the same place: the
society's genesis over its first input with a seed, its later inputs up to the one the comparison
froze consumed in the first minute, and all of its people, by identity. A comparison names one group
of those people, everybody or some of them, and an arm names who decides for the group: their
routine (the score's 1), waiting at every choice point (its 0), or a model the manifest offers the
`society_decision` role, asked as the playback host asks a person whose world's owner chose it (the
workspace's rules judged once a minute for each model, then one request per person through the
decision contract and `ask_person`), with two differences: a minute whose question the rules would
change fails the run by name (`question_changed_by_rules`) where the host asks nobody that question
and leaves those people to their routine, and each ask ends by the contract's decision deadline
alone, where the host's also ends in time for its lease. Everybody outside the group keeps, in every
arm, what their world's owner had chosen for them when the comparison was defined: a model, asked
the same way, or their routine. So two arms differ only in who decides for the group. A control arm
runs one candidate model a second time to bound what run-to-run variation alone produces. The pure
loop and its replay are `exulanica/world/society_comparison.py`; the local runner is
`exulanica/api/society_comparison_runner.py`.

**Records.** Migration 0113 appends four records, each keyed within its workspace and by a
registered world, under forced row-level security, and never changed: a definition by the caller's
comparison id, a run by an id derived from the comparison, its arm and its seed's digest, a
receipt by its run and decision sequence, and an outcome by its run:
`society_comparison` (the definition: window, phase, arms, the seeds it committed to by digest,
the registered claim and pre-registration, and the decision contract, catalogs and scoring code it
is run and scored under), `society_comparison_run` (one arm on one seed; it holds the seed a replay
needs beside the digest), `society_comparison_decision` (every request and receipt a run's model
was asked, in the host's `exulanica.society-decision/v2` form) and `society_comparison_outcome` (a
run's one terminal fact: completed, with every minute's state digest, its events and receipts
digests and the score's integer terms, or failed by a code from `RUN_FAILURE_CODES`). A run fails
by name only when the host, not the model, ended its asking: a spent budget, a refused provider or
credential, a model no longer offered or asked otherwise than the definition recorded, rules that
would change the question, or a refused request. A run a process stopped part way, found with
receipts and no outcome, is recorded as failed, `interrupted`, before anything is asked; running
it again is a new comparison. Migration 0116 admits a second-version definition
(`exulanica.society-comparison/v2`) and completed outcome beside the first, whose rows and rules it
leaves as they were. A second-version definition records its group, where the group came from
(everybody, people named, or one of the owner's choices by its sequence and digest) and every other
person's decider with the owner's choice it keeps. The repository holds each to the world's own
records before it is stored, refusing a group that is not the choice it names
(`group_not_the_choice`) and a person outside it whose decider is not the owner's latest choice for
them (`others_not_the_owners_choice`), and 0116's trigger refuses a completed outcome whose version
is not its definition's.

**Score.** A comparison is scored under the score version it was defined under. The second, declared
in `assets/catalogs/society/society-person-score.v2.json` and computed exactly by
`exulanica/world/society_score_v2.py`, scores how the group's people fared and nothing else: need
relief, the need above the recorded routine's rest threshold that a run spares them against waiting,
as a share of what their routine spares them on the same seed. Waiting scores 0 and the routine 1 by
construction; a run can score below 0 or above 1, and every reader shows the value unclipped. A seed
on which the routine spares the group less than the protocol's floor per scored person is excluded
by name (`need_below_floor`). The score reads states alone: no answer, answer time, receipt or
disposition reaches it, and an import contract in `pyproject.toml` keeps the model client, the
asking path and the API out of the scorers' and the verdict's reach. A turn a model does not answer
in time is decided by the routine, so answer time reaches the score only through what the routine
then did. Where everybody outside the group follows their routine, as a held-out comparison
requires, a model that answers no turn scores exactly the routine's 1. What each model answered is
therefore served beside every score, never in it: each of the group's turns is answered (the minute
applied the model's choice), refused (its answer was not an offered action), or left to the routine
(no answer, or an offered action the minute did not apply), each kept by the reason the receipt or
the minute recorded, and each given as a share of the run's own turns and as a rate per choice point
the routine's own run had for the group on the same seed. The runner plays a seed's anchors before
any model run of it, and a model run starts only once both of its seed's anchors completed: it is
refused by name while either has no outcome (`anchors_first`) and closed as failed before it asks
when either failed (`anchor_failed`). Where everybody outside the group follows their routine, the
anchors ask nobody, so that denominator is recorded before any model is asked and no model's answers
move it. A held-out definition that has a model decide for anybody outside its group is refused by
name (`held_out_others_not_routine`); a development one may, and its result says so
(`others_asked`), since that model is asked in every arm, the anchors included, and its answers move
the score's 1 and the rates' denominator too. In the routine's own catalog resting relieves need and
visiting relieves a little, while standing and talking relieve none: either one while rested neither
earns nor costs, and every minute a person spends above the threshold costs its excess, whatever
they do. Waiting share, walking share, minutes by activity, activities per person, first answers
refused, cost per simulated hour and latency are reported with no weight. The first version
(`society-person-score.v1.json`, computed by `exulanica/world/society_score.py`) scored need relief
less the share of turns refused and the share the model did not decide, both over the run's own
turns; the first judged comparison below was scored under it, and a first-version comparison is read
under it, with what it did not record, a split of the turns left to the routine and any rate over
the routine's choice points, served as null.

**Claim.** `assets/catalogs/society/society-comparison-protocol.v1.json` states the window, the
floor, the bootstrap, the interval level and the family error rate, and
`exulanica/world/society_comparison_claim.py` reads them: paired differences over seeds, a
percentile bootstrap drawn from SHA-256 so the same scores give the same interval anywhere, Holm's
procedure over the registered family, and the control's interval as the bound on run-to-run
variation. The server's verdict is `different` only when Holm rejects the primary difference and its
size exceeds that bound; otherwise `no_measured_difference`. A comparison on development seeds, one
read under scoring code other than the code it registered, and one with fewer than two scored seeds
are `not_judged`, each by name, and one with a run missing or failed is `incomplete`. What it
registered is its binding: the first names the three catalogs and the first scorer and claim modules
by digest; the second also names the second scorer and
`exulanica/world/society_comparison_verdict.py`, which assembles the verdict from the scores, so a
change to any of them leaves a comparison registered under it `scored_under_other_code`. A
comparison is read under the catalog versions it recorded, whichever versions a later one is defined
under, and a binding this code cannot read is refused by name. The verdict also says whether the
primary pair's answered shares differ by more than the control pair's do, a bound that adds no
constant of its own, and the page says so in the verdict's own sentence. Held-out seeds are
committed by the SHA-256 of their text: `society-comparison-seeds.v2.json` keeps the first version's
development seeds and commits twelve held-out seeds drawn afresh, none of the first version's, whose
held-out seeds the first judged comparison spent. The seeds themselves stay outside the repository
until a pre-registered comparison is judged on them.

**First record.** The
[first judged comparison](evaluation/2026-09-26-society-model-comparison.json), scored under the
first version, compared Qwen3 235B Instruct and Nemotron 3.5 Lightning deciding for the starter
world's small square and its eight people over the eight held-out seeds, with Qwen run twice as the
control, through `scripts/measure_society_comparison.py`; its
[pre-registration](evaluation/2026-09-26-society-model-comparison-preregistration.json) records
that it was written before any held-out seed was run. Holm's procedure rejected the primary
difference, Lightning's score minus Qwen's, 0.0367 on average with an interval from 0.0106 to
0.0627, but its size is no larger than the far end of the control difference's interval, 0.0537,
so the verdict is no measured difference. Qwen's people also scored below their routine (0.0488 lower on average), a difference
the family's test rejects; Lightning's did not differ from their routine by that test. Every run
replayed from its receipts with no billed call, and the two models' calls cost 0.2997 USD.

The [decomposition](evaluation/2026-09-26-society-model-comparison-decomposition.json), derived from
the judged record alone by `scripts/decompose_society_comparison.py`, splits each score into need
relief and the share of turns whose answer was not applied. People fared almost the same on need
relief under both models: 0.9880 on average in each of Qwen's two runs and 0.9893 under Lightning.
The differences between them are almost all turns: Lightning's lead of 0.0367 is 0.0013 of relief
and 0.0354 of turns, and the 0.0248 between Qwen's two runs of the same hours is all turns. Against
their routine, Qwen's people scored 0.0488 lower, 0.0120 of relief and 0.0368 of turns. The record
keeps how many turns were not applied, 24 of Qwen's 703, 9 of 770 in its second run and 2 of
Lightning's 1527, not why; the run with the most, Qwen's on `held_out_3` with 11 of 81, is the only
one whose answer time at the 95th percentile, 20,008 ms, reached the contract's 20,000 ms deadline.

**Reads.** Three routes read what a comparison recorded; none asks a model or writes anything.

| Method and path | Permission | Result |
| --- | --- | --- |
| `GET /world/versions/{version_id}/society/comparisons` | `world.read` | The version's comparisons, newest first, with their arms, the group they decide for and how far their runs got |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}` | `world.read` | Scores per seed and per arm with intervals and, beside each, what its arm's model answered; the group and who decides for everybody else; the registered differences and the server's verdict |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}` | `world.read` | One completed run replayed from its stored requests and receipts, with no model call, held to its recorded minute digests, events and receipts, naming who decides for each person; a replay that differs is refused as `run_replay_mismatch` |

No response carries a run's seed or a raw state. A comparison or run under another workspace or
world is an unknown reference, and a run whose inputs have since lost their rights is unavailable
rather than replayed from stale geometry. A comparison this code cannot read, one naming a binding,
catalogs, a definition or a score version it does not hold, or whose outcomes scored other people
than its group, is answered as a conflict (409) with the code it was refused by, such as
`binding_unknown`, never as a server error.

**Running one.** A comparison is defined and run by a local command, never from a route:

```
EXULANICA_BUDGET_USD=<bound> python -m exulanica.orchestration.compare --workspace <uuid> \
  --world <world id> --version <uuid> --actor <uuid> --model <provider>/<model id> \
  [--model <provider>/<model id>] [--control] \
  [--group-choice <n> | --group <person id> [--group <person id> ...]] \
  --seeds <file> [--seed-count <n>]
```

It defines a development comparison over the version's society as it stands, its group everybody,
the people the owner's choice `--group-choice` named, or the people `--group` names, and everybody
else keeping what the owner's latest choice for them names; reserves every run; plays them
`runs_at_once` at a time, the anchors first, with no connection held while a model is asked; and
prints each arm's score with what its model answered, the differences and the verdict. A person
outside the group whose owner chose a model is asked of it in every arm, the anchors included, and
what those asks cost is reported apart from the arm's own. It uses a seed from the file only when
its digest is one the catalog commits to the development phase, and prints none. The whole process
budget is the comparison's: the runner keeps none of it back, as the playback host keeps a share,
and a live world's hourly bounds do not apply, since a comparison writes nothing the live world
reads. A comparison runs at most the protocol's `population_maximum` people, a saved world's own
population; a larger society is refused by name.

**Browser view.** An authenticated saved world exposes **Compare models** from the World menu. It
lists the version's comparisons and opens the newest: the server's verdict in words, with the
primary pair's answered shares in the same sentence; who each arm decides for and what decides for
everybody else, with what a model outside the group means for the score where there is one; each
arm's score with its interval and, beside it, its model's share of turns answered, refused and left
to the routine, the same per choice point of the routine's own run where the comparison recorded one
or, for a first-version comparison, in words, that it did not; its cost for the hour and its answer
time; the registered differences; and every seed's scores, each with what its run's model answered.
For a chosen seed and two arms it draws both runs from above on one clock (play, pause, speed and a
minute scrubber), what each person did minute by minute on each side with a mark where the two hours
went differently, and the inspector on a person of either side, saying who decided their latest turn
and why, and for a person outside the group, that they keep that decider in every arm. The page
shows every number as the server wrote it and never decides whether two arms differ; it reads
nothing but the three routes above.

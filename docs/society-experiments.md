# Society experiments

A society experiment runs one society's simulated time more than once, changing one thing, and
records what each run did. There are two record families:

- **Comparisons of models** run the same simulated hour of a saved world's purposeful society
  (`exulanica-society/v2`) or living town (`exulanica-society/v5`) once for each model that could
  decide for a group of its people, beside their routine and waiting, and score how the group's
  people fared. This is how a world's owner sees the difference a model makes.
- **Intervention experiments** freeze two input histories of a living society
  (`exulanica-society/v4`), a baseline and a treatment such as one more rest amenity, and record
  paired development attempts over them.

How a model decides for a person, and what that spends, is the
[decision roles contract](decision-roles-contract.md)'s; the engines are the
[synthetic society contract](synthetic-society-contract.md)'s.

<details>
<summary>Sections</summary>

- [Comparisons of models](#comparisons-of-models)
  - [Records](#records)
  - [Score](#score)
  - [Claim](#claim)
  - [Judged comparisons](#judged-comparisons)
  - [Reads](#reads)
  - [Running a comparison](#running-a-comparison)
  - [Browser view](#browser-view)
- [Intervention experiments over a living society](#intervention-experiments-over-a-living-society)
  - [HTTP surface](#http-surface)
  - [Definitions](#definitions)
  - [Attempt lifecycle](#attempt-lifecycle)
  - [Compact reads](#compact-reads)
  - [Independent read-only consumer](#independent-read-only-consumer)
  - [Browser result view](#browser-result-view)
  - [Local reserved-attempt execution](#local-reserved-attempt-execution)

</details>

## Comparisons of models

A comparison runs the same simulated hour of a saved world's purposeful society
(`exulanica-society/v2`) or living town (`exulanica-society/v5`) once for each of its arms, and
scores each run from what the engine recorded. Every run starts from the same place: the
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
loop and its replay are `exulanica/world/society_comparison.py`; the runner is
`exulanica/api/society_comparison_runner.py`, and the one definition the application's start and the
local command share is `exulanica/api/society_comparison_start.py`.

### Records

Migration 0113 appends four records, each keyed within its workspace and by a
registered world, under forced row-level security, and never changed: a definition by the caller's
comparison id, a run by an id derived from the comparison, its arm and its seed's digest, a receipt
by its run and decision sequence, and an outcome by its run: `society_comparison` (the definition:
window, phase, arms, the seeds it committed to by digest, the registered claim and pre-registration,
and the decision contract, catalogs and scoring code it is run and scored under),
`society_comparison_run` (one arm on one seed; it holds the seed a replay needs beside the digest),
`society_comparison_decision` (every request and receipt a run's model was asked, in the host's
`exulanica.society-decision/v2` form) and `society_comparison_outcome` (a run's one terminal fact:
completed, with every minute's state digest, its events and receipts digests and the score's integer
terms, or failed by a code from `RUN_FAILURE_CODES`). A run fails by name only when the host, not
the model, ended its asking: a spent budget, a refused provider or credential, a model no longer
offered or asked otherwise than the definition recorded, rules that would change the question, or a
refused request. A run a process stopped part way, found with receipts and no outcome, is recorded
as failed, `interrupted`, before anything is asked; running it again is a new comparison. Migration
0116 admits a second-version definition (`exulanica.society-comparison/v2`) and completed outcome
beside the first, whose rows and rules it leaves as they were. A second-version definition records
its group, where the group came from (everybody, people named, or one of the owner's choices by its
sequence and digest) and every other person's decider with the owner's choice it keeps. The
repository holds each to the world's own records before it is stored, refusing a group that is not
the choice it names (`group_not_the_choice`) and a person outside it whose decider is not the
owner's latest choice for them (`others_not_the_owners_choice`), and 0116's trigger refuses a
completed outcome whose version is not its definition's. The mechanism a model answers a person's
choice by changes what it chooses, not only how long it takes
([the model actions probe](evaluation/2026-09-26-society-model-actions-probe.json) found Nemotron
3.5 Lightning choosing to wait in 13 of 16 answers by a JSON schema and in 2 of 16 by a forced
call), so a definition also records, for every model it names, how that model is asked: the
mechanisms in order, the one its requests use, whose order that is (the model's own, measured and
named by its manifest entry, or the contract's) and the record that measured a model's own. The
runner refuses a definition that records another answering than the contract and the manifest give
(`answering_not_the_models`), and stops a run before it asks anything when they would now ask one of
its models otherwise (`provider_configuration_changed`).

Migration 0136 records a run over a day hour by hour. `society_comparison_hour` appends each hour
of a day's run as it ends, keyed by the run and the hour within its workspace, under forced
row-level security, and never changed: the hour's document (`exulanica.society-comparison-hour/v1`:
where the hour lies in the day, its minutes' state digests, its events and receipts digests, the
fourth score's terms for the hour with the kinds each scored person did in it, what its asking took
and every person's minutes, coded as the run's drawing classifies a minute) and the state the hour
ended in, as the canonical bytes its last minute's digest names, which the database holds to that
digest by its own SHA-256. Its trigger seals an hour only of a run whose definition's window is
longer than an hour and holds that hour, only while the run has no outcome, in order from the
first, and each holding exactly the receipts the run recorded since the hour before it. A day's run
completes with a third-version outcome (`exulanica.society-comparison-run/v3`), which 0136 admits
only with every hour of the window sealed and the last holding every receipt; an hour's run never
completes as a day's, nor a day's as an hour's
([`tests/test_comparison_hour_migration.py`](../tests/test_comparison_hour_migration.py)).

### Score

A comparison is scored under the score version it was defined under. A living town is defined
under the fourth score, declared in `assets/catalogs/society/society-person-score.v4.json` and
computed by [`exulanica/world/society_score_v4.py`](../exulanica/world/society_score_v4.py).
It keeps the half need-relief and half variety weights, same-seed routine and waiting anchors,
floor, exclusions and reliability classes of the third score. Living urgency adds the excess over
each recorded routine threshold for every supported need of each scored person in each minute;
its raw unit is a sum of need-thousandths times person-minutes, so a raw urgency from the third
score cannot be compared directly with it. Missing, extra or malformed needs refuse the run, and
the stored terms record the need keys, thresholds and unit. Variety counts only performed
catalogued actions, never travel or a selected goal. A living town's day is scored under the fifth
score, declared in `assets/catalogs/society/society-person-score.v5.json` and computed by
[`exulanica/world/society_score_v5.py`](../exulanica/world/society_score_v5.py): the fourth score
over a window of a day, its weights, anchors and classes unchanged. A day's run is played and
sealed hour by hour, so its terms are assembled from its hours: each hour keeps the fourth score's
terms with the kinds each scored person did in it, held to that hour's own count of them, and the
day sums every count and unites each person's kinds, so a kind counts once per person in the day as
it counts once in an hour's window. The assembled terms are the fourth score's over every minute
of the day ([`tests/test_society_score_v5.py`](../tests/test_society_score_v5.py)). A day's raw
urgency and variety are a day's, so a day's score is never compared with an hour's. A society of
things (`exulanica-society/v7`) is defined under the sixth score, declared in
`assets/catalogs/society/society-person-score.v6.json` and computed by
[`exulanica/world/society_score_v6.py`](../exulanica/world/society_score_v6.py): the third score's
weights, anchors, floor, exclusions and reliability classes, with need relief read from the
purposeful need every being of the society carries. Its variety also counts the acts the society's
modules record for a scored person: a line said (`said`) and the hands acts (`picked_up`,
`put_down`, `gave`, `took`), each read from its event, whose subject did it, and never from a
decision's event, so no answer or disposition reaches a weighed term (the catalog states that read
as `states_and_acts`, which only a weighed term of this version may declare). A line never changes
what its speaker is doing and a hands act is recorded only by its event, so no kind counts twice;
each counts once per person, so saying many lines adds one kind. The routine never speaks or uses
its hands, so a model whose people also did scores above the routine's one. Reported with the
terms and never weighed: how many of each act the group did, how many lines it said and how many of
them nearly repeat an earlier one (a token-set Jaccard of at least a half with a line the speaker
said earlier in the run or with the line it answers, the last said to it or to everyone near it
that it heard before it spoke), and the hands acts dropped, by reason
([`tests/test_society_things_comparison.py`](../tests/test_society_things_comparison.py)). A run of
a society of things plays as its own minutes do, its things phase after the roles' events, from
its genesis, where no visitor has crossed in, and nobody crosses in during it: the door's stream is
not an arm's input, so a comparison of a world with visitors compares the world's own beings. The
plan lists only those beings, and a group naming a visitor is refused by name (`group_visitor`,
422). A run's genesis is built over the society's first input, and its first minute consumes every
input up to the frozen one, so a being its author placed in a later edit arrives a minute after the
run starts. The run holds it, and asks for it where everybody is decided for or where its owner chose
a model for it, but a group decided for from the first minute may not name it: the plan lists only
the beings genesis holds, and a group naming another is refused by name at the plan, the start and
the definition (`group_person_not_in_run`, 422). Such a comparison is priced, bounded and read by
every being its runs hold: the society's people, the beings genesis places and every being the
frozen input places, at most what the engine holds. The definition records that count as `beings`
beside `population`, which genesis still reads, and a host prices and admits the comparison's seeds
by it. It asks the society's people under the terms its engine asks them under, with lines and
hands among the options, and its models' requests record that engine's prompt version, which each
run is held to before it asks (`provider_configuration_changed`). Catalogs whose score is another
family's are refused by name when the comparison is defined (`score_engine_mismatch`), before
anything is asked. A purposeful
society is defined under the third score, declared in
`assets/catalogs/society/society-person-score.v3.json` and computed by
[`exulanica/world/society_score_v3.py`](../exulanica/world/society_score_v3.py): half need relief,
the second version's term described next, and half variety, how many different kinds of thing each
of the group's people did in the hour (resting, visiting, standing and talking, the routine's own
activities; never walking or waiting), summed over them and anchored the same way, waiting 0 and the
routine 1 on the same seed, unclipped. A kind counts once however often a person returns to it. A
seed on which the routine's people did no more kinds than waiting's is excluded by name
(`variety_not_spared`). Variety reads states alone, so what is said below of what reaches the score
holds for it too; it tells apart models whose people were spared the same need in different hours,
which need relief alone did not (in the second judged comparison every seed scored the models alike
to four places while their people spent their hours differently). Every run's integer terms (the need
above the threshold summed, the kinds summed, its turns by class and each reason under the class it
left the turn in, so a turn given no answer in time is never read as a refused one) and each term's
anchored value are served beside its score. The second score, declared
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

### Claim

`assets/catalogs/society/society-comparison-protocol.v1.json` states the window, the
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
change to any of them leaves a comparison registered under it `scored_under_other_code`; the third
also names the third score's module. A protocol version is its catalog's entries: a reader asks for
each value by name, a version that states none is refused by name (`protocol_keys`), and so is a key
no reader reads, so a later version that changes its values is a new catalog file and changes no
bound module. The verdict module on this tree is not the one the second binding names by digest
(`7114c141...`, in the
[group comparison's pre-registration](evaluation/2026-09-26-society-group-comparison-preregistration.json)),
so a comparison registered under the second binding and scored from a live database reads
`not_judged`, `scored_under_other_code`, while one on development seeds reads `development_seeds`,
as it did. The committed judged records and their outcomes stand. A
comparison is read under the catalog versions it recorded, whichever versions a later one is defined
under, and a binding this code cannot read is refused by name. The verdict also says whether the
primary pair's answered shares differ by more than the control pair's do, a bound that adds no
constant of its own, and the page says so in the verdict's own sentence. Held-out seeds are
committed by the SHA-256 of their text: `society-comparison-seeds.v2.json` keeps the first version's
development seeds and commits twelve held-out seeds drawn afresh, none of the first version's, whose
held-out seeds the first judged comparison spent. The held-out seeds themselves stay outside the
repository until a pre-registered comparison is judged on them. The third version commits each
development seed's text beside the digest the earlier versions commit it by, since a development
seed is looked at freely and never judged, and its schema holds each text to its digest; its
held-out seeds are the second version's twelve, by digest alone, which the second judged comparison
ran on, and an entry that states a held-out seed's text is refused (`held_out_seed_text`). The
fourth keeps the development seeds and their text and commits eight held-out seeds drawn afresh,
none of an earlier version's, by digest alone, which the town comparison of 2026-09-30 spent; the
fifth, which a comparison over an hour is defined under, does the same with eight more, which the
second town comparison of that day spent; and the sixth, which a comparison over a day is defined
under, does the same with eight more again, none of which a comparison registered under another
version holds ([`tests/test_comparison_development_seeds.py`](../tests/test_comparison_development_seeds.py)).

A comparison of a living town over a day is defined under the fourth protocol
(`assets/catalogs/society/society-comparison-protocol.v4.json`), the fifth score and the sixth
seeds; a comparison over an hour stays under the third protocol. The fourth's window is 1440
minutes, the town's day from its genesis to the same minute the next day, and its floor is 355,200
need-thousandths times person-minutes per scored person, in the living score's unit: a quarter of
the median need a routine's day spares each person against waiting's day, rounded down to the
hundred, over the eight development seeds on the small towns of 38 and 52 people and the market
towns of 74 and 88 that the living town's reading line was measured on, where the routine's day
spared from 1,377,094.8 to 1,467,886.4 per person, median 1,421,019.3
([record](evaluation/2026-10-02-living-day-anchors.json),
[`scripts/measure_living_day_anchors.py`](../scripts/measure_living_day_anchors.py)). Every other
value is the third's. It states no replay line, since a living town is read by its own, and only
keys the verdict already reads, so neither the verdict module nor any binding an earlier comparison
registered changes ([`tests/test_comparison_day_protocol.py`](../tests/test_comparison_day_protocol.py)).
A day's comparison registers the fifth binding, which also names the fifth score's module and its
reader, [`exulanica/world/society_comparison_verdict_v5.py`](../exulanica/world/society_comparison_verdict_v5.py).
A comparison of a society of things registers the sixth binding, which names the third score's
module beside the sixth's and its reader,
[`exulanica/world/society_comparison_verdict_v6.py`](../exulanica/world/society_comparison_verdict_v6.py),
which holds each run's terms to what they report and reads the third score's verdict over them. It
runs over an hour under the third protocol and on the development seeds every seeds version
commits; no held-out seeds have been drawn for it, so a held-out comparison of one is refused by
name (`held_out_seeds_not_drawn`) until a seeds version lands with its pre-registration.

### Judged comparisons

A judged comparison is pre-registered before any of its held-out seeds is run, and its record is
written by the measurement that registered it. Each record below replayed every run from its
receipts with no billed call. A comparison over a day is registered, played and recorded by
[`scripts/measure_day_comparison.py`](../scripts/measure_day_comparison.py), which first plays the
same design on one development seed, so the bound it registers is at least that day's spend for
every held-out seed with a quarter more. A seed is admitted only while what is left of the bound
holds what one seed needs left (the plan's suggested figure for one seed), so the bound is also at
least that spend for every seed before the last plus that figure. The run's process spends within
that bound alone (`EXULANICA_SPENDING=process`), and its record reads every hour of every run back
through the run route and every run's day through the day route.

- [2026-09-26-society-model-comparison.json](evaluation/2026-09-26-society-model-comparison.json)
  ([pre-registration](evaluation/2026-09-26-society-model-comparison-preregistration.json),
  [decomposition](evaluation/2026-09-26-society-model-comparison-decomposition.json)): Qwen3 235B
  Instruct and Nemotron 3.5 Lightning deciding for all eight people of the starter world's small
  square over eight held-out seeds, scored under the first score version, with Qwen run twice as
  the control. No measured difference: Lightning's lead over Qwen was no larger than the control's
  run-to-run variation, and the decomposition puts almost all of it in turns whose answer was not
  applied rather than in how the people fared.
- [2026-09-26-society-group-comparison.json](evaluation/2026-09-26-society-group-comparison.json)
  ([pre-registration](evaluation/2026-09-26-society-group-comparison-preregistration.json)): four of
  the square's eight people, the half the world's owner had chosen Qwen3 235B Instruct for, run by
  Qwen as the owner chose (twice, as the control), Nemotron 3.5 Lightning and Nemotron 3 Nano 30B
  while the other four kept their routine, over twelve fresh held-out seeds, scored under the
  second version. No measured difference in how the group fared, while the models answered
  different shares of the group's turns and spent the hour on different activities.
- [2026-09-30-town-comparison.json](evaluation/2026-09-30-town-comparison.json)
  ([pre-registration](evaluation/2026-09-30-town-comparison-preregistration.json)): the first twelve
  of a 52-person generated town's people, decided by Nemotron 3 Nano 30B (twice, as the control) or
  Nemotron 3.5 Lightning while everybody else kept their routine, over eight held-out seeds, scored
  under the third version. Incomplete, so it claims nothing: the process that ran it made its asks
  under its default ceiling of 2000 calls, which the pre-registration did not count, and 13 of the
  24 model runs failed before asking anything once it was reached. Its held-out seeds are spent.
- [2026-09-30-town-comparison-2.json](evaluation/2026-09-30-town-comparison-2.json)
  ([pre-registration](evaluation/2026-09-30-town-comparison-2-preregistration.json)): the same
  design over eight fresh held-out seeds, its process's call ceiling set above the most its runs
  could make. No measured difference: every run completed and seven seeds were scored, one
  excluded by the floor; Lightning's mean over Nemotron 3 Nano 30B's was 0.0064, its interval from
  -0.0206 to 0.0298 and not rejected, beside a control bound of 0.0360, while both models' people
  fared worse than their own routine by a difference each rejected.

### Reads

Five routes read what a comparison recorded or what a start of one would be; none asks a model or
writes anything.

| Method and path | Permission | Result |
| --- | --- | --- |
| `GET /world/versions/{version_id}/society/comparisons` | `world.read` | The version's comparisons, newest first, with their arms, the group they decide for, the window their runs play, how far their runs got (over a day, also how many of their hours are sealed of how many, `hours_sealed` and `hours_expected`) and, for one started from the application, its start: the bound, what its asks spent, what hosts that stopped are presumed to have spent unrecorded, and where it stands |
| `GET /world/versions/{version_id}/society/comparisons/plan` | `world.read` | What this server offers a comparison of the version's society, the roles its engine hosts with their groups and models, the windows it may run over (`windows`, an hour or a day, each with the most people a comparison over it runs and the most of the society's people a model may decide for, or why it is not offered; [what it can read](#running-a-comparison)), the society's people by id and name, from whom a named group is chosen, and for a selection over the window it names (`window`, an hour unless named) its runs, the most it can cost, what one like it typically costs, the most one decided person's run can ask and call, and how many of a minute's asks each of its models can have answered, or the refusal a start of it would meet ([running a comparison](#running-a-comparison)) |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}` | `world.read` | Scores per seed and per arm with intervals and, beside each, what its arm's model answered; the group and who decides for everybody else; the registered differences and the server's verdict |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}` | `world.read` | One completed run as the page draws it, naming who decides for each person: the drawing the host stored once it had played the comparison's runs, replaying each from its stored requests and receipts with no model call and held to its recorded minute digests, events and receipts, served while it was drawn by the code reading it and the data that code reads (the digest taken when the server started), and read as the drawing its digest names; otherwise, and for stored bytes that are not that drawing, the run replayed and held to them here, and a replay that differs is refused as `run_replay_mismatch`. A day's run is read one sealed hour at a time (`hour`, from 0, its first where none is named): the hour replayed from the state the hour before it sealed, its genesis for the first, through the receipts the hour recorded, held to the hour's record and drawn as an hour's run is, with where the hour lies in the day (`window`). An hour the window does not hold is refused (422, `hour_not_in_window`), as is any hour but the first of an hour's run, and one the run has not sealed is `run_not_completed` (409). Either way its inputs' rights are asked before anything drawn from them is answered |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}/day` | `world.read` | A day's run over the hours it sealed, from its sealed hours alone, with no replay: each hour's terms for the group and what its asking took, and every person's minutes, coded as the run's drawing classifies a minute, with the activities and places the codes name, so two runs' days can be set side by side minute by minute. Served for a run still playing or one that failed too, its inputs' rights asked before anything drawn from them is answered; a comparison over an hour is `comparison_not_a_day` (409) |

No response carries a run's seed or a raw state. A comparison or run under another workspace or
world is an unknown reference, and a run whose inputs lost their rights before or while it was
replayed is unavailable (424, `unavailable_society_input`) rather than drawn from stale geometry. A comparison this code cannot read, one naming a binding,
catalogs, a definition or a score version it does not hold, or whose outcomes scored other people
than its group, is answered as a conflict (409) with the code it was refused by, such as
`binding_unknown`, never as a server error.

### Running a comparison

A comparison is defined by one path, `exulanica/api/society_comparison_start.py`, whether its
world's owner starts it from the application or the local command defines and runs it; for every
set of the command's flags the definition is the one the command made before the application could
start one ([`tests/test_compare_command_definition.py`](../tests/test_compare_command_definition.py)).
A definition names the decision role it asks by the contract it records, which the role registry
resolves to one role, and a run asks that role.

**Starting one from the application.** `POST /world/versions/{version_id}/society/comparisons`
requires `world.write` and `model.invoke`, which in a browser only the workspace's owner holds. It
takes the group, one or two models the manifest offers the role, whether the first runs again as the
control, how many development seeds, the comparison's id and the bound in US dollars its asks may
spend. In one transaction it defines the comparison over the version's society as it stands,
reserves every run and records the start (migration 0119), who started it, its bound and its plan,
which are never changed. The id is the caller's, keyed within its workspace: the same start sent
again is answered with it, another start under that id is refused (`comparison_conflict`), and
another workspace naming the same id starts its own. A world plays one started comparison at a time
(`comparison_running`). Every other refusal is named (`START_REFUSALS`): a server whose seed
catalog commits no development seed's text (`comparisons_not_set_up`), where nothing plays the
comparisons started on it (`comparisons_not_played`), that does not ask models for the workspace
(`comparisons_not_run_here`) or that holds no model key; a society whose engine takes no comparison
or hosts no such role, which holds more people than a comparison runs
(`population_over_comparison_bound`), or of whose people a model would decide for more than a
comparison lets it (`decided_over_comparison_bound`), both below; a role not registered; a model the
role is not offered, one named twice, or one this server cannot ask now, whether for the group or
for somebody outside it whose owner chose it; a group naming nobody, somebody not here or a choice
this world does not hold; more seeds than the server holds; and a bound above the most the
comparison can cost (`bound_out_of_range`) or above what this server's model budget has left beside
the part its decision contract keeps for other work (`bound_over_budget`), or a comparison that can
make more calls than this server's model budget has left beside that part (`calls_over_budget`).
Where a durable spending authority admits this server's calls, a new start that would ask a model
whose provider's allowance is spent, for the group or for somebody outside it whose owner chose it,
is refused before anything is defined, as admission would refuse that model's first ask: 429
`budget_exceeded` with the authority's `spending` member
([model spending](model-spending-contract.md#11-what-a-client-sees)). The plan states the same
refusal for a selection whose start would meet it, as its `plan_refusal` with that `spending`
member, by the same predicate.

**Durable bounds.** Where that authority admits this server's calls, a comparison also spends under
a bound of its own at the authority, one for each provider it asks, under the workspace's grant of
that provider, with the bound its owner stated and the most calls it can make
([model spending](model-spending-contract.md#2-authorities-grants-and-bounds)). A start whose bound, or whose calls,
is more than such a grant has left is refused `bound_exceeds_grant` (409) before anything is
written; the bound is never made smaller to fit. A plan naming the bound it would start with
(`bound_usd`) states the same refusal, and one naming none judges the calls alone. The host that
plays the start opens the bounds before its first ask, or finds the ones a host before it opened,
and admits every ask under its provider's bound, so what every host that played the comparison
committed never passes its bound, a takeover's presumption that fell short included. A run the
authority refuses by its bound fails as `comparison_bound_spent` where the bound is committed, as
`comparison_cancelled` where its owner cancelled the comparison, and otherwise by the authority's
reason; a provider whose bound the authority would not open, its grant revoked or replaced, fails
its model's asks by the authority's reason, before anything is sent. The bounds are closed when the
start is finished, whatever finished it, and by the cancel, so an ask a host sends after the cancel
is refused at the authority. In a process no durable authority admits, the bound is held in the
host's process alone.

**What it can cost.** The most is derived: a run asks each subject a model decides for at most once
a minute, so its asks are at most the protocol's window times those subjects (the arm's group under
a model arm and, in every arm, anybody outside the group whose owner chose a model), and each ask
costs at most `ask_bound_usd`, every answer the contract allows at the manifest's prices for the
longest situation and answer the contract allows. What one like it typically costs is a
measurement of the kind of ground its society stands on: in the
[judged group comparison](evaluation/2026-09-26-society-group-comparison.json), on the small
square, each model's arms spent, per person and simulated hour, $0.0018 (Nemotron 3.5 Lightning),
$0.0014 (Qwen3 235B Instruct) and $0.00055 (Nemotron 3 Nano 30B), under 2 percent of the most; in
[one development comparison of a 48-person town](evaluation/2026-09-29-town-comparison-cost.json),
whose people each model asked 1.5 to 2.5 times as often as on the square, $0.00286 (Nemotron 3.5
Lightning) and $0.00132 (Nemotron 3 Nano 30B). The deployed server reads these figures from
`assets/catalogs/society-comparison-cost/society-comparison-typical-cost.v1.json`, which records
each source file's digest and extraction method. A plan reads its own ground's figures where they
cover every model it asks. For an unmeasured ground or model combination, including the living
town, it uses that model's greatest measured cost and answer time across the catalog's grounds,
names the conservative fallback and does not claim a town measurement. A society of things asks its
people under the third instruction, with hands options and the lines they heard, which none of
these measurements' runs did, so a plan of one states no typical cost or answer time, and a host
admits its seeds by what their runs can hold reserved (`held_usd`). Since every ask is held at
its model's most until its cost is known, a
bound near the typical figure stops the runs part way (`comparison_bound_spent`), so the plan also
serves the most the runs played at once can hold reserved together (`held_usd`) and, beside it,
the least bound that lets a comparison spending the typical figure finish (`suggested_usd`), and
whether that figure was measured on this society's kind of ground (`typical_matches`). The page
says "at least" that bound lets it finish only where it was; elsewhere it says where the figure was
measured and that a bound that low may stop it. The plan route and the page give all of these, and
the person states the bound, at most the most; nothing starts until they do. For the window it
names, the plan also states the most one decided person's run can ask, once a minute, and call,
every answer the contract allows (`per_person`); for each model arm, what one ask of its model holds
reserved (`ask_bound_usd`) and the most one run of it can reserve (`most_usd_per_run`); the longest
its asking can take (`seconds_most`: its runs that ask anybody, `runs_at_once` at a time, every
minute of each ending by the contract's decision deadline); and, for each provider it asks, the
calls the durable bound a start opens of it holds (`providers`).

**What it can read.** Every read of a run replays it ([reads](#reads)), and the page reads a
seed's two runs at once, which one process replays one after the other, so how many people a
comparison runs is derived from how long that takes, never stated. The protocol's third version
(`assets/catalogs/society/society-comparison-protocol.v3.json`) states the most a pair may take,
ten seconds (`pair_replay_budget_ms`, the longest a person keeps their attention on a wait they are
told about), and a cost measured with
[`scripts/measure_comparison_replay.py`](../scripts/measure_comparison_replay.py) that lies on or
above every read it measured: 241 ms for any run, 41.6 ms for each of the society's people, 93.1 ms
for each person a model decides for, whose turns the replay builds again and holds to what was
stored, and 0.131 ms more for each of those for each person of the society, since building a
decided person's options reads everybody else
([`exulanica/world/society_comparison_reading.py`](../exulanica/world/society_comparison_reading.py)).
Every run is held to half the pair's budget, so by this line a comparison runs at most 111 people,
the most for which a run where a model decides for one of them still fits; and in one run a model
may decide for all 30 people of a 30-person society, at most 29 of 44, 24 of 56 or 11 of 86, the
group under a model arm and anybody outside it whose owner chose a model counted together. This
line reads every engine but the living town's, whose own line follows: a saved world's purposeful
society, and a generated town's society made before the living town's engine, which the town keeps.
For such a town it is the bound that applies, fewer than the 128 a generated town's ground allows.
A larger
society is refused by name (`population_over_comparison_bound`), and so is a comparison whose model
would decide for more (`decided_over_comparison_bound`); the plan route serves both figures for the
version's society, and the page states the second before Start. The first two protocol versions
state `population_maximum`, eight, and bound nothing else. A run's minute asks every person it
decides for within one deadline the minute's asks share, at most the contract's concurrent calls at
once (`concurrent_calls_maximum`, `decision_deadline_ms`), so a model answers about as many of them
as those calls can take one after another at its measured answer time; the plan gives that figure
for each chosen model from the judged group comparison's 95th percentile answer times
(`answers_per_minute` in `exulanica/api/society_comparison_start.py`), and where a group is larger
the page says that in a minute when more of them have a choice the rest follow their routine. It
does not refuse such a group.

**A living town's line.** A living town (`exulanica-society/v5`), the engine a generated town's
society runs, is read by a line measured on its own replay rather than the protocol's:
[`assets/catalogs/society-comparison-cost/society-comparison-reading.v5.json`](../assets/catalogs/society-comparison-cost/society-comparison-reading.v5.json)
names it for the state family the engine reads (`living`) and binds it by path and digest to its
[measurement record](evaluation/2026-10-07-living-comparison-replay.json), which
[`scripts/measure_living_comparison_replay.py`](../scripts/measure_living_comparison_replay.py)
wrote under the quiet slot's idle gate. The record names the drawing code it measured by its digest.
Measured: the 95th percentile read at 61 points, with scripted answers the engine applies, on
generated small towns of 38 and 52 people, market towns of 74 and 88, and one stress town of 128 at
the society ground's bound, outside the admitted specification and composed only to measure a run
there; each at its own population and at stated smaller ones, with nobody or everybody decided for,
and at stated groups. The machine was 71.66 percent idle over ten seconds before the run and 71.19
percent after it, with the one-minute load under 8 before every point. Derived from those reads: the
least-margin line on or above every point, 39 ms for any run, 10608 µs for each of the society's
people, 4272 µs for each person a model decides for, and 78 µs more for each of those for each
person of the society. By that line and the protocol's ten-second pair budget (half of it for each
run), a model may decide for everybody in each measured town, up to the stress town's 128, whose
everybody-decided run the line puts at 3221592 µs; and it would let a run hold 463 people where a
model decides for one of them, more than the 128 a town's ground allows, so for a living town the
ground is the bound that applies. The plan route and a start judge a living town's society by this
line and a purposeful society by the protocol's, which stays at its third version and was measured
on one. A society of any other family the reading catalog binds no line for, a society of things
today, is refused by name (`no_reading_line`, 409) rather than read by a line measured on another
engine's runs. It reads an hour's run; a day is read by a line of its own (a day, below).

**A day.** A start and a plan name the window every run plays (`window`): `hour`, the default, or
`day`. A day is a living town's, whose engine keeps the time of day: from its genesis at 06:00 to
the same minute the next day, 1440 minutes, defined under the fourth protocol, the fifth score and
the sixth seeds ([claim](#claim)). A purposeful society keeps no time of day and is not compared
over one. A day is offered only where the reading catalog binds a line measured over the day's
window, as an entry of its own for the state family and the window (`living-1440`), since a run is
read by the hour and a town's hours differ through its day; a day of a family the catalog binds no
such line for is refused by name (`window_not_offered`, 409), and the plan states each window with
the line it is read by or the refusal it meets.
[`assets/catalogs/society-comparison-cost/society-comparison-reading.v5.json`](../assets/catalogs/society-comparison-cost/society-comparison-reading.v5.json)
binds the living town's line over a day by path and digest to its
[measurement record](evaluation/2026-10-07-living-day-replay.json), which
[`scripts/measure_living_day_replay.py`](../scripts/measure_living_day_replay.py) wrote under the
quiet slot. Measured: 25 points on the hour line's graphs, small towns of 38 and 52 people, market
towns of 74 and 88 and the stress town of 128, each at its own population with nobody, everybody and
groups of 4, 8 and 16 decided for; each day played and sealed hour by hour with scripted answers the
engine applies, then every hour read three times as the run route reads one and the day as the day
route reads it, a point's read the dearest of them. Composing and playing were neither gated nor
timed; the reads' gate passed at 83.33 percent idle, the reads' mean idle was 87.805 percent, and
the one-minute load was under 8 before and after every point, so no point was read again (a point
whose reads end with the load at 8 or over is read again, up to twice, and only its last reads
kept). Derived: the least-margin line on or above every point, 10 ms for any run, 14559 µs for
each of the society's people, 3294 µs for each person a model decides for, and 60 µs more for each of
those for each person of the society, so what a decided person adds grows with the town. Four
points set it: the town of 52 with 16 decided, the town of 88 with 16 and with everybody decided,
and the stress town with everybody decided, whose dearest reads were 0.87, 1.43, 2.04 and
3.27 s. By that line and the protocol's pair budget, a model may decide over a day for everybody
in each measured town, up to the stress town's
128, whose everybody-decided run the line puts at 3278224 µs; and it would let a run hold 341
people where a model decides for one of them, so the ground's 128 is the bound on a day's
population. The plan route and a start
judge a day of a living town's society by this line. A day's run is played hour by hour, each hour
sealed as it ends ([records](#records)) once its inputs' rights are asked again, so a run whose
inputs lost their rights fails as `input_unavailable` at the end of the hour it lost them in and
seals no later one. Each hour is read by a replay from the state the hour before it sealed
([reads](#reads)), never by one from the genesis, and no drawing of a day is stored; a read of a
run's day sets out every person's minutes from its sealed hours with no replay. A day's run asks at
most 24 times what an hour's can, which the plan states for the window it names (what it can cost,
above) ([`tests/test_comparison_day_postgres.py`](../tests/test_comparison_day_postgres.py)).

**Where it runs.** A host's comparison worker (`exulanica/api/society_comparison_worker.py`) plays
it off the request path, for the workspaces the host asks models for
(`EXULANICA_SOCIETY_CONTROL_WORKSPACES`, and under durable spending the watched workspaces every
round and every account workspace once every five minutes, so a comparison a visitor started
finishes after they leave;
[deployment](deployment.md#515-society-playback)), by the lease the playback worker claims a society by: it
claims the workspace's oldest unfinished start whose lease is free or has run out, for the control's
30 s lease, renews it before each run and after each simulated minute, and plays the runs without an
outcome through the runner, the anchors first, with no connection held while a model is asked. Where
it runs is `EXULANICA_COMPARISON_WORKER`: absent, the API's process runs it in a thread; `process`,
`python -m exulanica.orchestration.comparison_worker` runs the same worker in a process of its own
and the API only serves starts; off, nothing plays them, and the API refuses every start
(`comparisons_not_played`) rather than accept one no host would ever claim, which would keep its
world from starting another. It refuses them by the same name where it leaves them to a process of
its own that the installation's profile declares not installed, or unavailable, as the
installation's facts state the `comparison` component
([deployment](deployment.md#91-installation-profiles-and-facts)); a capability read and a plan read
say so first. The API's own thread plays them whatever its profile declares, so the default path is
unchanged. Development seeds are the seed catalog's own: from its third version
it commits their text, so a server holds them with no file beside it, and none is printed or
served.

**The bound.** Every call of a started comparison is reserved against a part of the process's model
budget whose ceiling is the bound (`BoundedBudget` in `exulanica/models/budget.py`), which passes
each reservation on to the process's own budget, so the process's ceiling holds too; the asks of a
comparison the API's process plays leave the decision contract's share of that budget for the
Companion and the live world. A run asks a minute only while one ask of the dearest model due still
fits what is left of the bound, the rule the host applies to its own budget, and each call's
reservation is held until its usage is recorded, so calls made at once never take the bound past its
ceiling between them. A run the bound no longer fits stops before the minute, and a run one of whose
calls the bound refused stops after it; either fails by name (`comparison_bound_spent`). Between seeds, a host stops rather than start runs the
bound cannot finish: it plays every seed's anchors first, then each seed's model runs one seed after
another, and admits a seed's model runs only while what is left of the bound holds what runs like
them typically cost on the society's kind of ground and what they can hold reserved at once (the
plan's `suggested_usd` for them), and while this process has calls left for the most its runs can
make, since a process that runs out of calls stops them whatever they spent. Where the society's
ground has no measured figure for a model, the dearest figure any ground has for it is used; where
none does, the seed still needs what its runs can hold reserved at once (`held_usd`), and the host
logs it. The seed's anchors play once it is admitted. A seed it does not admit closes its model runs and every later
seed's, asking nothing, as `comparison_bound_before_seed`, and the start closes by that name, so the
seeds already played are kept and scored ([`tests/test_comparison_seed_admission_postgres.py`](../tests/test_comparison_seed_admission_postgres.py)).
A run over an hour left part way with receipts is closed as `interrupted` whatever the bound
holds. A day's run left part way goes on only once its seed is admitted, and is otherwise closed
with the seed by its name, its receipts and sealed hours kept. The bound itself is unchanged: no ask
is admitted past it. An attempt
whose cost is unknown, such as one that timed out, counts at the most it can have cost, so a
provider slow to answer spends the bound faster than its answers alone would. A comparison writes no
world decision, so a live world's hourly bounds neither count nor limit it; the comparison and the
live world's decisions draw on the same process budget, and once what is left no longer fits a live
person's ask, that person follows their routine (`process_budget_spent` or `process_share_spent` on
the models route) until the process restarts.

**A host that stops.** A host that stops part way leaves its lease to run out and at most
`runs_at_once` runs with receipts and no outcome. The next claim records each of those over an hour
as failed, `interrupted`, before asking anything, and goes on with each over a day from the last
hour it sealed: every minute the run recorded after that hour is answered from what it recorded, as
a replay answers, and only the minutes after them are asked. A minute's receipts are recorded
together, in one transaction, once all of its asks are answered, so a host killed inside a minute,
between two of its asks or between two of the receipts its transaction inserts, has stored none of
that minute, and the next claim asks the whole minute again; asks of it that were sent are paid
twice, which the takeover's presumption below covers. A day's run whose stored receipts are not the
ones its minutes rebuild fails as `interrupted` before it asks the next minute. Every receipt a
day's run appends, every hour it seals and its outcome are written in a transaction that first
locks the claim's live lease token, so a host whose lease another claim took writes nothing more of
it. The next claim plays the rest, from the bound less what the comparison's
receipts say it spent and less what claims that took it over presumed. A claim that takes over a
lease that ran out cannot tell a host killed in the middle of a minute from one that stalled before
it, so it presumes the most one minute of a run can cost for as many open runs as the stopped host
may have been playing at once, since those asks may have been paid for and never recorded, and keeps
it on the start, served as `presumed_usd`, so every later claim deducts it too; it only grows. A run
given an outcome sets the count of claims in a row that finished no run back, in the transaction
that records the outcome, so a host that finished runs before it stopped, whether it let its lease
go or was killed, is never counted as one that finished none. After three claims in a row that
finished no run, the next closes the start (`claims_spent`): runs with receipts fail `interrupted`
and the rest `comparison_stopped`. A claim whose bound is spent, or which this process's model
budget cannot hold, closes the start with every run left failed by that name, asking nothing.

**Cancelling one.** `POST /world/versions/{version_id}/society/comparisons/{comparison_id}/cancel`
requires `world.write` and `model.invoke`, the grants a start takes, and never asks a model. It
cancels a comparison started from the application once: the cancellation is appended and never
changed (migration 0130), so a repeated cancel finds the first and changes nothing, and a start
that already finished keeps its own closing. A start no host holds is closed by the cancellation
itself: every run left open fails as `comparison_cancelled`, asking nothing, and where the lease
of a host that was playing it ran out, what that host may have spent unrecorded is presumed as a
claim that takes a start over presumes it. A start a host is playing is closed by that host. It
reads the cancellation before each minute's asks are sent and sends nothing more; the answers of
a minute already sent are recorded and counted like any other; its run and every run it has not
played fail as `comparison_cancelled`, keeping every receipt; and the start finishes closed by
that same code. No claim plays a finished start again. A comparison the local command defined
has no start and is not cancelled here (`comparison_not_started`). A cancellation that arrives
between a host's check and its sending lets that one minute's asks go out: they are paid,
recorded and counted.

**Progress.** The reads serve a cancelled start's cancellation (`cancel`, when it was requested)
and, for each run with no outcome yet, where it stands (`progress`): `running` while a host plays
it under the start's live lease, since a host records each run it starts (migration 0130), and
`queued` otherwise, with, for a day's run, how many of its hours it sealed (`hours_sealed`). A
cancelled day's run keeps the hours it sealed, which stay readable.

**Stored drawings.** A host draws a completed run once, when it records the run's outcome, under
the digest of the drawing code and the data that code reads (migration 0121). The code is every
module a replay runs in a process that has read nothing yet, the readers of the catalogs, kinds and
roles it reads among them, so a change to how one is read is a new digest too. A server whose drawing
code or data differ finds no drawing under its own digest and replays the run on each read instead,
held to the run's record. Nothing draws stored runs again, so every run drawn before such a change
is served by replay; the rows drawn under the earlier digest are kept. The seeds catalog is not
among the data the digest covers: a drawing names no seed and its replay reads no comparison
catalog, so a new set of held-out seeds, a new seeds file and the version
[`exulanica/world/society_comparison_seeds.py`](../exulanica/world/society_comparison_seeds.py)
names for it, leaves every stored drawing current
([`tests/test_comparison_drawing.py`](../tests/test_comparison_drawing.py)). A day's run is not
drawn: each of its hours is replayed on its read from the state the hour before it sealed.

**An earlier input.** A start may name `input_seq`, an earlier stored input of the society, to
freeze instead of its newest; the plan takes the same parameter and states the input a start of
its selection freezes (`plan.input_seq`), and the comparison's read serves the input it froze
(`input`: its sequence and digest). An input the society does not hold is refused by name
(`input_not_in_society`, 422), and one that lost its rights is answered 424
`unavailable_society_input`, as a read of the society answers it. Every run starts at the
society's genesis and consumes its inputs up to the frozen one, so two comparisons with the same
models and seeds, one frozen before an edit and one at it, differ only by that edit
([`tests/test_comparison_frozen_input_postgres.py`](../tests/test_comparison_frozen_input_postgres.py)).
Neither is a branch of the live society at the edit's tick, which would need a replay to that tick
and a new run start, and the live history is never written.

**From the local command.** The command defines and runs one in its own process:

```
EXULANICA_BUDGET_USD=<bound> python -m exulanica.orchestration.compare --workspace <uuid> \
  --world <world id> --version <uuid> --actor <uuid> --model <provider>/<model id> \
  [--model <provider>/<model id>] [--control] \
  [--group-choice <n> | --group <person id> [--group <person id> ...]] \
  [--seeds <file>] [--seed-count <n>] [--comparison <uuid>] [--window hour|day]
```

It takes one or two models. `--comparison` names the comparison's id, a fresh one when it is left
out, and `--window` the window its runs play, an hour unless named. It defines a development
comparison over the version's society as it stands, its group
everybody, the people the owner's choice `--group-choice` named, or the people `--group` names, and
everybody else keeping what the owner's latest choice for them names; reserves every run; plays them
`runs_at_once` at a time, the anchors first, with no connection held while a model is asked; and
prints each arm's score with what its model answered, the differences and the verdict. A person
outside the group whose owner chose a model is asked of it in every arm, the anchors included, and
what those asks cost is reported apart from the arm's own. It runs the first `--seed-count`
development seeds the catalog commits, or, where `--seeds` names a file, a seed from it only when
its digest is one the catalog commits to the development phase, and prints none. The whole process
budget is the comparison's: the runner keeps none of it back, as the playback host keeps a share,
and a live world's hourly bounds do not apply, since a comparison writes nothing the live world
reads. It is held to the same reading bound as a start from the application (what it can read,
above), refused by the same names.

### Browser view

An authenticated saved world exposes **Compare** from the World menu and the tool rail. It lists
the version's comparisons and opens the newest. It leads with the server's verdict in words, large,
with the primary pair's answered shares in the sentence under it; who each arm decides for and what
decides for everybody else, with what a model outside the group means for the score where there is
one, sits behind "Who it decides for". The seed and the two arms shown are chosen next. Every number
is behind one disclosure, "Every number from this comparison": each arm's score with its interval
and, beside it, its model's share of turns answered, refused and left to the routine, the same per
choice point of the routine's own run where the comparison recorded one or, for a first-version
comparison, in words, that it did not; its cost for the hour and its answer time; the registered
differences; and every seed's scores, each with what its run's model answered. For the chosen seed
each side says how its group fared, what its model answered, and what the group did: each kind of
minute (walking, waiting, or an activity the routine names, one row for the same words) and how
many of the group spent any minute in it, counted from the run's replay. Under it, both runs share
one clock (play, pause, speed and a minute scrubber) for what each person did minute by minute on
each side with a mark where the two hours went differently, the inspector on a person of either
side, saying who decided their latest turn and why, and for a person outside the group, that they
keep that decider in every arm, and each side's view from above behind "See them from above". The
rows of what each person did come in two parts, the group the two sides decide for and then
everybody else, each saying how many of its people's hours went differently and listing them by how
many minutes did, most first, with each person's count. Everybody else is folded behind that
summary until it is opened, since what the group did changes the hour around them: in a development
comparison of four of a 48-person town's people, Nemotron 3 Nano 30B against Nemotron 3.5
Lightning, all 44 others' hours went differently, 42 to 60 of their 60 minutes, while they kept
their routine on both sides. A town's page therefore opens on the group's rows. The page shows every
number as the server wrote it and never decides whether two arms differ.

Above the list, the world's owner starts a comparison from what the plan route offers: who the
models decide for (everybody, the people of one of their choices, or people they tick from the
society's people the plan lists, up to the most a model may decide for, which is how a group larger
than one choice's eight is chosen), a first and a second model
with what each typically costs and why one cannot be asked now, whether the first runs a second
time, and how many seeds. Where a model may decide for fewer than all of the society's people, it
says how many before Start. For the choice it shows the runs, the most they could cost and what one
like it typically costs, where a chosen model decides for more people than one minute's asks can
have answered, that in a busy minute the rest follow their routine, and the bound, filled with the
least that lets one like it finish until the person types their own; Start stays unavailable until
the bound is above zero and at most that most. A started comparison is listed with its progress, runs finished of
runs planned and its spend of its bound, with what a server that stopped may have spent where there
is any, read again every four seconds while it waits or runs, and opens in the view as its runs
finish; a refusal and a closed start are said in words by their codes.

## Intervention experiments over a living society

An intervention experiment records a controlled comparison over an existing
`exulanica-society/v4` society. It freezes the exact immutable input rows both arms use and
reserves development attempts; preparing or reserving a record does not run a simulation.

**Limit.** Only the living engine takes experiments (the engine table's `experiments`, read as
`EXPERIMENT_ENGINES` in `exulanica/world/society_engines.py`), and the app creates a living society
only over the owned district, which it draws only in the development preview. A saved world holds a
purposeful society, so its **Recorded comparison** view ([browser result view](#browser-result-view))
finds no record for it.

### HTTP surface

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

### Definitions

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

### Attempt lifecycle

An attempt reservation is an append-only fact. Its initial status is `incomplete`, which means no
terminal outcome has been recorded. Internal bounded execution may add one sealed checkpoint and
then exactly one `completed` or `failed` outcome. Reusing an experiment or attempt UUID with the
same canonical content is idempotent; reusing it with different content is a conflict.

The HTTP request path does not prepare checkpoints, advance either arm, call a worker or model, or
finalize outcomes. Those operations are internal repository and deterministic-core work.

### Compact reads

Attempt reads return the definition, seed, checkpoint, evidence, result and failure digests that
exist for the record. A completed result includes each arm's raw metric numerators and denominators,
safety counts, evidence counts and digests, and exact signed comparisons. A failed result includes
the bounded server-defined failure code and detail. The response never includes checkpoint state or
full execution evidence.

There is no evidence download or portable experiment package endpoint. A digest in the compact
response identifies a persisted artifact but does not by itself provide an export surface.

### Independent read-only consumer

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
named world. It validates the definition's world, the path identities, lifecycle combination,
digest syntax and cross-response bindings before exposing metrics. For a completed result it
independently checks the supported result profile and canonical result digest. The compact
definition digest is only an identity binding because the GET response does not contain the full
canonical definition document.

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

### Browser result view

An authenticated saved world exposes **Attempts** from the World menu. The view fixes
the authored version to the active saved-world entry and asks for the experiment and attempt UUIDs
printed on an existing record receipt. It then uses the two GET routes above to verify and present
that one compact result. The browser does not offer a record list, preparation, reservation,
execution or finalization control.

The view presents stored baseline and treatment fractions, signed server-recorded deltas, safety
summaries, exact record bindings, unsupported metrics, lifecycle failures and unavailable records
without reinterpreting them. Closing the view cancels its active read. Opening another identity
supersedes the prior read, so a late response cannot replace the current result. In a saved world
it finds no record, because only a living society takes experiments.

### Local reserved-attempt execution

The local experiment runner accepts a current server session and one exact already-reserved
development attempt identity. It rejects held-out phases and seeds before checkpoint preparation,
arm computation or explicit abort; a held-out reservation remains incomplete. Trusted host
composition must supply current permission to execute the development reservation. The
reservation's `created_by` field is attribution and does not grant execution. The runner also
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
does not fabricate evidence or persist that state as a completed result. Execution is a local
composition capability; there is no HTTP execution route, queue discovery or browser launch control.

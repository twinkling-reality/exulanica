# Model and service selection

This reference owns which models the product runs in each role, the evidence behind each choice,
and the candidates worth comparing. A world's people are its agents, and a world's owner chooses the
open model that decides for a person or a group; this document records how those models were
verified and compared. Model upgrades require task-specific evidence. The
[model manifest](../exulanica/models/models.manifest.json) is the configuration, and the
[product roadmap](product-direction.md#model-selection-and-compute-priorities) records the ordered
work and adoption gates.

## 0. Implemented stack and selection decision

This section is the living correction of [ADR-0002](adr/0002-model-routing.md), which remains the
accepted original decision (Nemotron Lightning as the reasoning core); the Companion caller is
Nemotron 3 Nano 30B-A3B with Lightning as fallback, and the ADR number is not reused. The research
that preceded it, with its prices and rejected alternatives, is historical rationale kept at a fixed
revision ([Historical selection rationale](#historical-selection-rationale)), not a runtime
inventory. The manifest distinguishes configured reasoning candidates from the roles that have
production callers.

### Implemented roles

Implemented means there is a production call path; it does not mean every configured model is
running, deployed or has passed a quality comparison. Provider availability and prices must be
checked again before an execution campaign.

| Role | Implementation | Evidence and boundary |
| --- | --- | --- |
| Cited Companion answers | Nebius Token Factory: Nemotron 3 Nano 30B-A3B; Lightning fallback | `exulanica/selection/question.py::compose_answer` uses `REASONING_CHEAP`. The September 9 comparison supports latency and validator conformance on four questions, not general answer quality. A pre-registered held-out comparison kept Nano against Super and Ultra: neither cleared the margin on hard grounded questions ([outcome](evaluation/2026-09-22-model-selection-outcome.json)). |
| Choosing the lines of an answer about what happened among a world's simulated people | Nebius Token Factory: Nemotron 3 Super 120B; Lightning fallback | `exulanica/selection/society_question.py::compose_society_answer` asks `ANSWER_COMPOSER` once, and once more after a refused choice while its 10 s deadline leaves time; it chooses recorded lines and writes no text. A pre-registered comparison of the five text models whose licence entries are resolved chose it by answer time: 8 of 8 choices accepted, median 6.5 s, slowest of 8 44.2 s, in a window when the provider was slow ([record](evaluation/2026-09-29-society-composer-models.json)). Eight questions over one simulated square do not establish quality on other worlds. |
| Drafting a world's specification from a person's description | Nebius Token Factory: Nemotron 3 Super 120B; Qwen3-235B-A22B-Instruct-2507 fallback | `exulanica/selection/world_drafting.py::draft_world_specification` asks `SPECIFICATION_DRAFTER` for a form built from the served specification: a preset, the values it allows, and the parts of the description it cannot say, copied word for word. The server's gate judges the draft and nothing is made until the person makes the world. A pre-registered comparison of the five text models whose licence entries are resolved chose it: 12 of 12 drafts the gate would make on the first try, 11 of 12 matching the words by rule, median 3.6 s, slowest of 12 7.8 s ([record](evaluation/2026-09-29-world-drafting-models-v2.json)). Twelve descriptions of one specification do not establish quality on other words or other specifications. |
| Drafting a creature from a person's description | Nebius Token Factory: Nemotron 3 Super 120B; Qwen3-235B-A22B-Instruct-2507 fallback | `exulanica/selection/creature_drafting.py::draft_creature` asks `CREATURE_DRAFTER` for a flat form of a body, its colours, abilities and offers, assembled into a recipe, a body plan, a sketch and a thing kind that every reader a thing passes holds, with one repair naming the check's code, field and sentence. A pre-registered measurement of three licence-resolved text models chose it by its rule (the NVIDIA model with the shortest slowest draft within 60 s, among those valid on 6 of 8 held-out descriptions and matching 5 of 8 by rule); the primary's own calls are in the [timings record](evaluation/2026-10-07-creature-drafter-timings.json), and the candidates' comparison is not published. Eight descriptions do not establish quality on other words. |
| Drafting a kind of world from a person's description | Nebius Token Factory: DeepSeek-V4-Flash-0731; no fallback | `exulanica/selection/kind_drafting.py::draft_kind` asks `KIND_DRAFTER` for a brief with no keys (zones holding their structures, rooms, areas and fixtures, each part's use where it stands), compiled by code into a kind document and held to both stages of the kind checks, with up to two repairs naming the check's code, place and sentence. A pre-registered measurement of four licence-resolved text models chose it by its rule (an eligible NVIDIA model with the shortest slowest draft within 120 s first, otherwise the eligible model with the shortest slowest draft, among those valid on 5 of 6 held-out descriptions and matching 4 of 6 by rule); it was the only eligible model, so the role has no fallback. A second pre-registered measurement of it alone on six fresh descriptions kept it at a 32,768-token ceiling (its reasoning filled 16,384 tokens before any brief on 8 of 18 development calls); the primary's own calls there are in the [timings record](evaluation/2026-10-07-kind-drafter-timings-32768.json), and the candidates' comparison is not published. No route asks it yet. Six descriptions do not establish quality on other words. |
| Request classification, search planning, appearance drafts and environment drafts | Nebius Token Factory: Qwen3-235B-A22B-Instruct-2507; DeepSeek-V4-Flash-0731 fallback | `propose_plan`, `classify_request`, `draft_appearance` and `draft_environment_operation` call `STRUCTURED_EXTRACTION`; this is an implemented role with feature-level validation of proposals. |
| Planning a reference's web searches and drafting notes from what they found | Nebius Token Factory: Qwen3-235B-A22B-Instruct-2507; DeepSeek-V4-Flash-0731 fallback | `exulanica/references/drafting.py` calls `REFERENCE_DRAFTING`, a role with `STRUCTURED_EXTRACTION`'s chain and measured timeout basis, offered for no place-name right and no personal model right ([reference notes](reference-notes-contract.md)). Each answer is a structured form validated before it is kept. No measurement on this role's own calls yet. |
| Photograph observations | Nebius Token Factory: MiniMax M3; MiniCPM-V-4_5 fallback | `exulanica/ingest/vision.py`; observation and evidence validation remain separate. On synthetic held-out photographs M3 omitted and misplaced fewer objects than MiniCPM, which also reported people who were not there ([outcome](evaluation/2026-09-22-model-selection-outcome.json)). Synthetic drawings do not establish accuracy on real photographs. |
| A person's decisions in a world | The open model the world's owner chose for that person, among those the manifest offers the person's decision role (`society_decision`, declared by the decision role registry); none unless chosen | `exulanica/api/decision_host.py` asks through `ModelClient.choose` before a minute of play, and the planner takes only a validated answer ([below](#providers-chosen-roles-and-a-persons-decisions)). Each offered model's mechanism was verified by a pre-registered probe ([record](evaluation/2026-09-25-society-person-models-probe.json)); measurements compare what four models decide, and two judged comparisons found no measured difference between the models they compared ([below](#judged-comparisons-of-models-deciding-for-people)). |
| A town's signal choices | The model its owner chose for a junction signal among models the manifest offers `junction_signal`; fixed timing when none is chosen or no answer is usable | `exulanica/api/traffic_signal_controller.py` asks at green choice points from traffic state, records the receipt and seals replayable traffic minutes. The model may keep a green for one second within the plan's bounds or switch to amber; the traffic step checks the proposal. This role has no comparative model ranking. |
| Caption/text semantic retrieval | Nebius Token Factory: Qwen3-Embedding-8B, 4096 dimensions | `exulanica/epistemics/caption_embeddings.py` and `exulanica/selection/embeddings.py`; lexical and cosine retrieval, not direct image embeddings. No model fallback is configured for embeddings. |
| Object boxes | Grounding DINO Tiny; OWLv2 Base Patch16 Ensemble fallback | `exulanica/ingest/stages/segmentation.py`; local inference when hosted observations lack suitable boxes. |
| Object masks | SAM 2.1 Hiera Tiny | Same segmentation module; masks are distinct from human identity confirmation, source rights and placement into recovered shared coordinates. |
| Single-image geometry | MoGe-2 ViT-L | `exulanica/reconstruction/moge.py` loads the v2 implementation and a pinned checkpoint. MoGe-3 is not an implemented automatic fallback. |
| Multi-view camera recovery | pycolmap 4.2.0 / COLMAP, SIFT and exhaustive matching | `exulanica/reconstruction/pycolmap_executor.py`; registration must be measured before training. MapAnything is not an implemented rescue path. |
| Scene training and compression | gsplat / PyTorch CUDA; PlayCanvas splat-transform | Production trainer and publication boundaries exist. The September 12 generated L40S check validates packaging and forward/backward execution, not personal-place quality. |
| Browser | TypeScript, Vite, DOM UI, PlayCanvas 2.21.4 | The app imports the PlayCanvas binding, and no three.js implementation is in the repository; the `atlas-react` package name does not establish a React application. |
| API, durable state and jobs | Python 3.11, FastAPI, Pydantic, PostgreSQL, pgvector, PostgreSQL-backed job leases/retries | Existing replaceable model/stage interfaces and enforced module boundaries are the extension points. No new orchestration framework is selected. |
| Original bytes and compute | Local content-addressed file store; local API/workers and Docker GPU execution; hosted model calls on Nebius | `exulanica/api/services.py` constructs `LocalContentAddressedStore`. Brev/MassedCompute L40S execution is measured; Nebius GPU hosting and an S3 store implementation are not established by that run. |

Google OIDC account resolution, deterministic society stepping and playback, typed user-directed
society actions, reviewed-asset admission, scene-surface candidate extraction, scene-run preflight,
character appearance history, native character playback and the representation inspector are
deterministic application/runtime paths. They do not invoke a model merely because a model client is
configured. One path lets a model decide for a simulated person: a purposeful society's person
whose world's owner chose a model, asked by the host's playback before a minute. It is validated
against the offered choice and replayed from stored receipts rather than recalled during stepping,
as are the explicitly requested proposals a v3 society stored before that engine was retired.
Saved towns can also give a junction signal's bounded green choice to an offered model; traffic
stores its decision receipt and keeps fixed timing when the model cannot answer in time.

Nemotron Ultra is a configured role with no production caller in the reviewed Python code;
Nemotron Super's production callers are the answer composer and the specification drafter.
Fallback in the hosted client is provider-error handling, not a quality escalation policy.
`reference_vision` (MiniCPM-V-4_5, no fallback) is a configured role with no production caller
yet: it is to read a person's own pictures into reference notes, off by default, and its timeout
rests on code-made drawings ([record](evaluation/2026-10-07-reference-vision-latency.json)),
not photographs ([reference notes](reference-notes-contract.md)).
DINOv2 appearance embeddings, YuNet/SFace biometric recognition, speech models, a learned
reranker and MapAnything appear in earlier plans or candidate discussions, not in implemented
model paths found by this review. Do not count them as delivered capabilities.

### Hosted call bounds and cost

Each hosted role waits for its own timeout, stated once in the
[model manifest](../exulanica/models/models.manifest.json) beside its measured basis. The manifest's
`timeout_rule` derives a timeout from the longest latency recorded for the role's primary: twice
that latency, rounded up to a multiple of 5 seconds. The manifest parser refuses a timeout the
rule does not produce, and refuses a basis measured on a model other than the primary. The basis
is read from the retained evaluation records by
[`scripts/survey_hosted_call_latency.py`](../scripts/survey_hosted_call_latency.py) and recorded in
[the latency record](evaluation/2026-09-24-hosted-call-latency.json); the answer composer's is its
own comparison's record ([record](evaluation/2026-09-29-society-composer-models.json)), and so is the
specification drafter's ([record](evaluation/2026-09-29-world-drafting-models-v2.json)).

| Role | Primary's longest measured call | Timeout |
| --- | --- | --- |
| `reasoning_cheap` (Companion answers) | 28,031 ms of 217 calls | 60 s |
| `answer_composer` (lines of an answer about simulated people) | 44,181 ms of 8 calls | 90 s |
| `specification_drafter` (drafts of a world's specification) | 7,771 ms of 12 calls | 20 s |
| `creature_drafter` (drafts of a creature) | 25,659 ms of 9 calls | 55 s |
| `kind_drafter` (drafts of a kind of world) | 72,565 ms of 9 calls | 150 s |
| `structured_extraction` (classification, planning, drafts) | 12,326 ms of 217 calls | 25 s |
| `embedding` (query and caption vectors) | 16,676 ms of 19 calls | 35 s |
| `vision` (photograph observations) | 11,001 ms of 137 rows, each an upper bound | 25 s |
| `reasoning_mid` | 7,528 ms of 8 answers | 20 s |
| `reasoning_hard` | 7,437 ms of 8 answers | 15 s |

The timeout is a deadline on the whole request. The transport abandons a request when it passes,
however the response stalls: name resolution, connection, or a body that arrives slowly
([transport](../exulanica/models/transport.py)). A request cut off this way reports that it timed
out. A fallback serves under its role's timeout, and no retained record measures a fallback's
latency. The vision rows are synthetic drawings, and none of the records measures latency under
concurrent load.

The API client makes one attempt per call, so a question to `/selection/ask` about photographs
waits on its model calls for at most the sum of their timeouts and the composer's deadline. A
planner call and its repair ([planner](../exulanica/selection/planner.py)) and the query vector
come to 85 seconds; the composer's calls, a repair among them, share one deadline read from the
manifest, the 99th percentile its role's timeout rests on (`library_composer_wait_seconds` in
[question](../exulanica/selection/question.py)), after which the answer is given in fixed words:
at most 110 seconds. A withdrawn primary adds the time its refusal took before the fallback is
asked, which the bound counts as one more timeout for each call whose role has a fallback: 160
seconds on the API's client.
A question about what happened among a world's simulated people takes the planner and its repair
and then the answer composer, whose calls, a repair among them, share one 10 second deadline
(`COMPOSER_WAIT_SECONDS` in [society question](../exulanica/selection/society_question.py)) far
shorter than the role's 90 second timeout: 110 seconds on the API's client by the same count.
`answer_bound_seconds` in [question](../exulanica/selection/question.py) computes the longer of the
two paths from `ModelClient.worst_case_seconds` and each path's own call counts, and the page waits for an
answer that long, in whole seconds, plus its allowance for an ordinary read;
`tests/test_companion_ask_deadline.py` fails when the page's `ASK_TIMEOUT_MS` differs from it.

Every attempt enters the process's cost ledger, failed ones included
([usage](../exulanica/models/usage.py)). A completed call is priced from the provider's usage
report. An attempt whose connection was never made costs a known zero. A timeout, an error status,
a dropped connection, or a reply without a usage report is recorded with its cost unknown and
charged the attempt's reservation, the most it can have cost, because the provider may bill work
whose result never arrived. The budget guard spends from the same ledger, so an unknown cost
counts against the ceiling at that bound and a failed attempt counts toward the call limit. The
error that reaches the caller states the cost the same way. What the provider actually bills for
an abandoned request is not observable from this side.

A request that needs its own record of what it paid for sends through a copy of the client made
for it alone (`ModelClient.with_attempts` in [the client](../exulanica/models/client.py)). The
copy keeps every policy the client has, so a client with no policy still refuses to send, and it
reserves and records through the client's own budget guard, whatever kind it is, a lens budget
included, so the budget and the report see one set of numbers; it also hands each row the guard
records to the request. A reply is recorded before the client decides whether to believe it, so a
reply later refused as truncated or outside the schema, or one with no choices, is a completed row
that returned no result. A request a policy or the budget guard refuses sends nothing and records no
row. The Companion's execution record is built this way, one copy per question or proposal, and
never read back from the process ledger
([Companion question: execution provenance](companion-question.md#execution-provenance)).

### Providers, chosen roles and a person's decisions

The [model manifest](../exulanica/models/models.manifest.json) states providers as data. Each
provider under `providers` names its OpenAI-compatible endpoint, the environment variable its
credential is read from and the catalog the preflight checks its models against; every model names
its provider and says in plain words what it is. A role's chain stays on one provider, and each
provider's egress origin is derived from its endpoint rather than written twice
([security floor](security-floor.md#3-egress-allowlist)). Nebius Token Factory is the one provider
declared.

A role whose model a world chooses has no entry in the manifest. The decision role registry
declares each such role as data
([society contract](synthetic-society-contract.md#a-person-run-by-a-model-their-worlds-owner-chose)),
with the use cases a model must declare to be offered it, and passes those requirements to the
model layer as a `ChosenRoleBinding`; the manifest's `Role` names only the roles call sites bind to
a model, and nothing in `exulanica/models` names a chosen role (`tests/test_decision_roles.py`
scans it). A person deciding what to do next has role `society_decision`; a junction signal's
green choice has role `junction_signal`. A model is offered to a role only when its catalog use
cases hold the role's and its
`answering` entry names a mechanism the client asks by, a function the request forces by name
(`tool_call`) or a strict JSON schema (`json_schema`), with the evaluation record whose probe
verified that mechanism for that model; a model with neither is offered to no role.
`tests/test_model_providers.py` reads each named record and holds the manifest to its verdicts. An
entry may also state an `answering_order`, the order that model is asked in where a
measurement found it answers better that way than in the order the decision contract prefers,
with the record that measured it and why; from the decision policy's second version the contract
asks it by the first mechanism of that order it accepts, and every other model in the policy's
order, while a request asked under the first version keeps the mechanism it recorded
(`DecisionContract.mechanism_for` in `exulanica/world/decision_roles.py`). A chosen model has no
fallback, because a choice names one model, and no manifest timeout: its role's contract bounds each
ask, the person's at 20 seconds, inside the playback lease. The host asks each model with its own
default token bound, never below its floor, so a reasoning model has room to reason before it
answers. The preflight checks every model verified to answer a choice, since a role may be offered
it; the deployment's `exulanica-preflight` command (`exulanica/orchestration/catalog_preflight.py`)
and the ingestion, orchestration and evaluation commands give it the registry's roles, so a model a
role is offered is held to that role's use cases.

Four open models were probed on six recorded choices each, once by each mechanism
([probe record](evaluation/2026-09-25-society-person-models-probe.json)), under one
[pre-registration](evaluation/2026-09-25-society-person-models-preregistration.json) that states
the probe and the measurement below, and the tree they were to measure, before either asked
anything. All four were verified by both: Nemotron 3 Nano 30B, Nemotron 3.5 Lightning, Qwen3 235B
Instruct and DeepSeek V4 Flash, and every first answer was one of the offered actions. What a model
writes before answering depends on the mechanism: on average Nemotron 3 Nano wrote 762 completion
tokens to a forced call and 222 to a schema, Nemotron 3.5 Lightning 282 and 1,222, DeepSeek V4
Flash 196 and 131, and Qwen3 16 and 17. The contract asks by a forced call whenever it is verified,
its first-ranked mechanism, unless a model's entry states an order of its own. The probe cost
0.006226 USD.

The [measurement](evaluation/2026-09-25-society-person-models.json) gave each model the eight
people of the small square for 60 simulated minutes, on one fixed development seed
(`BROWSER_SEED` in [`measure_living_world_pace.py`](../scripts/measure_living_world_pace.py)),
beside the routine alone on the same seed. Every minute was a claim of the playback worker the
application builds for the workspaces it lists: the claim, the host's decision phase, then the
minute. The harness made each claim due at once rather than waiting the host's base interval, so
the worker's own polling and pacing were not measured.

| Model | Decisions | Acted on | Not acted on | Chose to wait | Answer p50 / p95 | Cost per simulated hour |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3 235B Instruct | 91 | 89 | 2: another person took the place first | 40 | 791 / 2,803 ms | 0.0082 USD |
| DeepSeek V4 Flash | 361 | 360 | 1: another person took the place first | 347 | 1,902 / 3,887 ms | 0.0391 USD |
| Nemotron 3 Nano 30B | 148 | 141 | 7: no answer within 20 s (5), another person took the place first (2) | 106 | 6,543 / 17,615 ms | at most 0.0262 USD |
| Nemotron 3.5 Lightning | 188 | 188 | none | 151 | 1,747 / 3,679 ms | 0.0193 USD |

Measured: every model chose waiting more often than any one kind of place, and the more a model
waited, the more decisions it made. Of 480 person-minutes, the routine's people spent 69 walking,
310 at objects, 75 talking and 26 standing, and never waited; DeepSeek's spent 347 waiting and 119
at objects, Qwen's 40 waiting and 389 at objects. No person run by a model talked; Nemotron 3 Nano's
people stood for 6 person-minutes, the other models' never. That contract, the decision contract's
first version, offered places and waiting, not the routine's own talking and standing; its second
version offers both ([below](#standing-and-talking-and-where-a-decisions-time-goes)). Every claim advanced one minute, and half the
claims took at most 0.9 s for Qwen, 2.1 s for Lightning, 2.9 s for DeepSeek and 8.5 s for
Nemotron 3 Nano; a claim waits for its minute's slowest ask. Every world replayed and verified with
no billed call. The run cost at most 0.092699 USD of its 0.11 USD bound, the five calls that timed
out counted at their reservations. One square, one seed and one hour per model were measured;
whether a model's choices serve its people better than the routine is not judged.

Inferred, not measured: a person who waits reaches a choice point again a minute later, so a model
that chooses waiting more is asked more often, which fits the decision counts above; the run did
not vary waiting to test it.

### Standing and talking, and where a decision's time goes

Under the decision contract's second version a person may also stand a while nearby or stop to
talk with somebody the routine could pair them with
([society contract](synthetic-society-contract.md#a-person-run-by-a-model-their-worlds-owner-chose)).
Before measuring what models choose with it, a
[pre-registered](evaluation/2026-09-26-society-model-actions-probe-preregistration.json) probe
([record](evaluation/2026-09-26-society-model-actions-probe.json)) asked the four offered models
sixteen recorded choices of the small square each, once by each mechanism and one call at a time,
and fitted each model's answer time against the tokens it wrote. Every one of the 128 answers was
one of the offered actions.

| Model | Forced call: median tokens, answer p50 / longest | Schema: median tokens, answer p50 / longest | Time per written token |
| --- | --- | --- | --- |
| Qwen3 235B Instruct | 16, 790 / 2,186 ms | 16, 607 / 1,144 ms | none: it writes the same few tokens |
| DeepSeek V4 Flash | 149, 1,940 / 3,430 ms | 100.5, 1,268 / 2,178 ms | about 4.5 to 5.1 ms |
| Nemotron 3 Nano 30B | 596.5, 3,952 / 10,653 ms | 233, 1,853 / 2,857 ms | about 6.4 to 6.9 ms |
| Nemotron 3.5 Lightning | 239, 983 / 1,876 ms | 1,131, 3,803 / 5,921 ms | about 3.3 to 3.9 ms |

Measured: Qwen3's answer time is all provider time, since it writes about sixteen tokens either
way; the three reasoning models' time grows with what they write, and what they write depends on
the mechanism, in opposite directions for the two Nemotron models. By the probe's pre-registered
rule a model is asked by the other mechanism first when it answered as often with an offered
action, wrote at most half the median tokens and had a lower 95th-percentile answer time that way,
which held for Nemotron 3 Nano alone, so its manifest entry states `json_schema` first. No model
answered slower than three times its median without writing more, so the probe's second rule, a
per-attempt bound with one retry, selected no model and none is built. The probe cost 0.01581188 USD
of its 0.03 USD bound. Inferred, not measured: the fitted time per token treats each model's calls
as one line; how much of a call's time is queueing at the provider is not separated from the rest.

The [measurement](evaluation/2026-09-26-society-model-actions.json), under its own
[pre-registration](evaluation/2026-09-26-society-model-actions-preregistration.json) written after
the probe, gave each model the eight people of the small square for 60 simulated minutes on the
same fixed development seed, beside the routine alone, played by the playback worker as above.

| Model | Decisions | Chose: go / wait / stand / talk | Not acted on | Person-minutes talking / standing | Answer p50 / p95 | Cost per simulated hour |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3 235B Instruct | 82 | 52 / 29 / 1 / 0 | 4: another person took the place first | 0 / 3 | 980 / 2,675 ms | 0.008179 USD |
| DeepSeek V4 Flash | 93 | 20 / 16 / 12 / 45 | 11: the person it chose to talk with was busy | 155 / 33 | 1,782 / 2,343 ms | 0.011397 USD |
| Nemotron 3 Nano 30B | 87 | 37 / 33 / 6 / 11 | 11: the person it chose to talk with was busy (8), another person took the place first (2), an earlier choice took them into another conversation (1) | 18 / 18 | 1,303 / 2,297 ms | 0.005614 USD |
| Nemotron 3.5 Lightning | 138 | 31 / 71 / 18 / 18 | 10: the person it chose to talk with was busy | 60 / 38 | 1,713 / 3,841 ms | 0.014994 USD |

Measured: no answer timed out in any arm, and every first answer was one of the offered actions.
The routine's own people talked for 75 person-minutes and stood for 26; DeepSeek V4 Flash's people
talked for 155, Qwen3's never, although a conversation was offered in 58 of its 82 decisions.
Nemotron 3 Nano 30B, asked by the schema, answered within 2.5 s every time; under the first
contract, asked by a forced call, 5 of its 148 answers had not come within the 20 s deadline. Every
world replayed and verified with no billed call, and the run cost 0.0401826 USD of its 0.20 USD
bound. Inferred, not measured: every person was run by the one model, so the other person a choice
to talk named was usually at a choice point and asked by their own model in the same minute, which
is why nearly every choice to talk not acted on was refused as busy; the run did not mix models
with the routine to test it. One square, one seed and one hour per model were measured, and
whether a model's choices serve its people better than the routine's is not judged.

The measurement's tree, which its record binds, applied three rules differently from the
[society contract](synthetic-society-contract.md#a-person-run-by-a-model-their-worlds-owner-chose),
so its counts of conversations and refusals are that tree's: it judged the other person's
tiredness as the minute began rather than as the minute has it, it counted a person's own spot as
taken when drawing where they stand, and a choice to talk that came first could take in somebody
whose own model had chosen to talk with someone else.

### What a person's decisions may spend

Two bounds apply to a person's decisions. The decision contract bounds each world: at
most 600 asked decisions and 0.25 USD of their cost in its last hour, counted from its receipts with
an unknown cost at its bound and each ask already admitted that minute at its bound; past either,
the routine decides and each receipt says which. The process's budget guard (`EXULANICA_BUDGET_USD`,
`EXULANICA_BUDGET_MAX_CALLS`) bounds everything the process asks for the life of the process: it
does not refill while the process runs, and it holds each admitted call's reservation until the
call's usage is recorded, so calls admitted at once never cross it together. People's decisions may
use all of it but the contract's `process_reserve_percent`, 50, which is kept for the Companion,
photograph ingestion, vision and caption search, since they share the ceiling. By arithmetic from
the bounds, not a measurement: a world at the hourly bound asks 600 decisions, up to 1,200 calls
with the one retry, which would use the default 2,000 calls in under two hours without the share.
Decided on what the process has spent, never on what calls under way hold: once what is left, beside
the part kept for other work, fits no ask of an offered model, the host asks nobody and writes
nothing until the process restarts, and a person whose own model's ask no longer fits is not asked
either; playback keeps advancing minutes with the routine deciding, `/readyz` says which ceiling
where a playback host runs, and the models route and the page tell the world's owner. A host that
plays people run by models sizes both ceilings for how long it runs between restarts.

### Judged comparisons of models deciding for people

Two comparisons were judged under rules pre-registered before any held-out seed was run. Each ran
the product's own comparison runner on the small square of a starter world with its eight people,
one simulated hour per run: every candidate, the first candidate a second time as a control, the
routine alone and everybody waiting. A difference counts only when Holm's procedure over the
pre-registered family rejects equality and the difference is larger than the control's own
interval; otherwise the verdict is no measured difference. The runner, the score and the Compare
view are the [society experiments](society-experiments.md#comparisons-of-models) contract's, which
lists every [judged comparison](society-experiments.md#judged-comparisons).

| | [Every person](evaluation/2026-09-26-society-model-comparison.json) ([pre-registration](evaluation/2026-09-26-society-model-comparison-preregistration.json)) | [A group](evaluation/2026-09-26-society-group-comparison.json) ([pre-registration](evaluation/2026-09-26-society-group-comparison-preregistration.json)) |
| --- | --- | --- |
| Decided by a model | All eight people | Four people, the group the owner chose a model for; the other four keep their routine |
| Candidates | Qwen3 235B Instruct and Nemotron 3.5 Lightning, each asked by a forced call | Qwen3 235B Instruct (the owner's choice) and Nemotron 3.5 Lightning by a forced call, Nemotron 3 Nano 30B by a JSON schema |
| Held-out seeds | 8 | 12 |
| Score | `society-person-score.v1`: need relief against the routine's, less the turns whose answer was not applied | `society-person-score.v2`: how the people fared and nothing else |
| Mean score (routine 1, waiting 0) | Qwen 0.9512 and 0.9760 in its control run; Lightning 0.9879 | Qwen 1.0505 in both runs; Lightning 1.0505; Nano 1.0422 |
| Verdict | No measured difference | No measured difference |
| Spent | 0.2997 of a 0.38 USD bound | 0.2482 of a 0.40 USD bound |

In the comparison over every person, Lightning's mean was 0.0367 above Qwen's (interval 0.0106 to
0.0627) and Holm's procedure rejected equality, but Qwen against itself differed by up to 0.0537, so
the difference is within run-to-run variation. The
[decomposition](evaluation/2026-09-26-society-model-comparison-decomposition.json) shows where it
came from: the need people were spared was almost the same, 0.9880 in each of Qwen's runs and 0.9893
under Lightning, and 0.0354 of the 0.0367 came from turns whose answer was not applied, 3.7 percent
of the turns in Qwen's first run, 1.2 percent in its second and 0.1 percent under Lightning. The
control's own difference of 0.0248 came entirely from such turns. Against the routine, Qwen's first
run scored 0.0488 lower and Holm's procedure rejected equality; 0.0368 of that came from turns not
applied. The record keeps how many turns were not applied, not why. What people did differed: Lightning's people waited in 31 percent of
person-minutes and Qwen's in 8. Lightning answered in 4.2 seconds at the median against Qwen's 0.8,
and cost 0.0200 USD per simulated hour against 0.0088.

In the group comparison the group's people fared the same under Qwen and Lightning and slightly
less under Nano, with no difference the protocol lets a comparison claim. What each model answered
differed, and the verdict records that the answered shares differ: Qwen answered 99.3 percent of the
group's turns (99.6 in its control run), Lightning 95.8 and Nano 92.5; the rest were left to the
routine, and no answer was refused. All 35 of Lightning's turns left to the routine, and 26 of Nano's
29, chose to talk with somebody who was already busy. The behaviour differed most: Lightning's group
talked in 15 percent of person-minutes and stood in 9, close to the routine's own 15 and 4, where
Qwen's group talked and stood in 1 percent each and rested in 74; Nano's group waited in 2 percent of
person-minutes against Qwen's 13.

In both comparisons every run replayed from its stored decisions with no billed call. Each measured
one square, one hour per seed and the models named; neither establishes how the models compare in
another world or over a longer run.

### Decision and evidence

**DECISION:** retain the implemented stack as the comparison baseline. Add the evaluations in the
roadmap, then promote the model or stage that improves the declared user task within measured
runtime limits. No model family, parameter count, vendor benchmark or successful import establishes
an absolute best stack. A candidate that materially improves the task is worth additional compute
when it fits the demonstrated hardware and interaction budget; cheapest is not the selection rule.

The September 9 comparison recorded median Nano latency 3627 ms versus Lightning 18617 ms at the
selected ceiling, with zero Nano validator rejections in 24 calls. Its answer-quality measurement is
explicitly null. The September 12 Companion record prepares retrieval checks and an evaluation
corpus; it holds no live answers and no human quality judgments. The segmentation record records
masks but no positive first-place person lift because pose was absent. The GPU record establishes
generated CUDA execution and cleanup. None proves an optimal model set. These four are local-only
evaluation records a clone does not contain: `2026-09-09-companion-memory`,
`2026-09-12-companion-quality`, `2026-09-11-scene-segments-production` and
`2026-09-12-place-compute-readiness`.

The [September 22 outcome](evaluation/2026-09-22-model-selection-outcome.json) answers the
criteria [pre-registered](evaluation/2026-09-22-model-selection-preregistration.json) before any
candidate output was read. For cited answers, Super was fully correct on one more hard held-out
question than Nano and Ultra on none; the frozen margin was two, so Nano stays. Both candidates
answered an empty evidence packet by stating that the library held no photographs, which was
false, and Super exposed an internal packet field name in answer text. They were faster than
Nano and cost more. The rubric was applied by an automated reviewer rather than the blinded human
review the roadmap requires, so the answer-quality half of this comparison has not been judged by
a person. For
observations, MiniCPM had a higher combined rate of omitted and unsupported objects than M3 and
reported a person on two photographs with nobody in them, so M3 stays. On unsigned photographs
MiniCPM, the fallback, returned generic scene labels such as "outdoor urban area" as places; the
place proposal policy below refuses all three it returned, because no sign in those frames reads
any of their words.

A place proposal is the only producer of a place-class memory entity, so what it lets through is
what a person is later asked to confirm. The vision role proposes; a versioned policy in code,
[`exulanica/ingest/place_proposal.py`](../exulanica/ingest/place_proposal.py), decides whether the
proposal is written and under which label:

| Check | What it keeps or refuses |
| --- | --- |
| Label rule | The label keeps only words the observation transcribed from text it marked as signage, compared case-folded and spelled as the transcription spells them. A label left with no word refuses the proposal. |
| Sign question | Asked in a separate call only when a word survives: the probe's question, word for word, about the most prominent sign. A sign judged partly hidden or absent refuses the proposal, and so does an answer from a model the policy has not admitted, such as the fallback. |
| Pairing | Every word the label keeps must be among the words the sign question read, so the sign judged is the one carrying the name. |

A sign question that fails withholds the proposal and keeps the rest of the observation. The
stored observation keeps the model's reply verbatim, with the decision, its named outcome and the
policy's digest beside it, and the digest is part of the vision stage's reprocessing key.

Each check answers a measured failure. The production instruction, phrased as an exception inside
a prohibition, proposed no place from any of 8 legible place names while transcribing every one.
A rewrite that asks for the proposal directly proposed all 8, and also the visible word of a
partly covered board at medium confidence on 2 of 3 such boards, which its
[pre-registered gate](evaluation/2026-09-22-vision-place-proposal-preregistration.json) does not
allow ([outcome](evaluation/2026-09-22-vision-place-proposal-outcome.json)). Asked inside the
observation, as an instruction or as a schema field answered before the label, the model judged
boards with a tree in front of them whole
([second experiment](evaluation/2026-09-22-vision-place-proposal-b-outcome.json)); asked alone, it
judged all 24 boards of a [probe](evaluation/2026-09-22-sign-completeness-probe-outcome.json)
correctly. Asked alone as a second call, it caught every partly hidden board of a held-out split,
but the observation had already written "Ashcombe (partial)" as a label, a word no sign in the
frame carries ([third experiment](evaluation/2026-09-22-vision-place-proposal-c-outcome.json)).
That record also counts one whole street sign, Chestnut Road, as judged partly hidden in error.
The sign is not whole: `scripts/make_place_signage_photographs.py` draws a street blade from
`x - 190` and places that scene's post at `x = 189`, so the blade's left edge lies one pixel
outside the frame, and the judgement matched the picture.

The policy passed every gate [pre-registered](evaluation/2026-09-23-vision-place-proposal-d-preregistration.json)
for it, on a held-out split of 44 synthetic photographs scored once
([outcome](evaluation/2026-09-23-vision-place-proposal-d-outcome.json)). No photograph received a
proposal it should not have: none of 26 with a covered, cut, hidden or absent place name, or with
a product, slogan or personal name, and no wrong name on any of 18 whole place names. It wrote 14
of those 18 exactly, the registered minimum; the production instruction wrote none. Applied to the
same recorded replies without re-running any model, the observation's own proposals would have
put a place on 13 photographs that should have none or named one wrongly, the label rule alone on
12, and every check but pairing on 1: a nameplate the observation misread as "FENWAY CHAMBERS"
where the sign question read "FENWY CHAMBERS". The sign question costs about 820 input tokens a
proposing photograph; the design cost 1.28 times the production instruction on that split.

What the policy does not do. It refuses a place name whenever another sign in the frame is more
prominent: all 3 held-out scenes with a slogan banner behind a street sign lost their name. It
proposes nothing from a landmark with no
legible name, and it cannot tell a place name from other text on a sign: a product or slogan on a
board passes every check if the observation proposes it, and the observation proposed nothing on
all 6 such photographs of the experiment. The measurements are synthetic drawings of one style,
with the fallback disabled; the fallback's sign judgement is refused by name, never measured.

### Quality and runtime requirements

The living-world preview uses source-footprint building meshes and catalog-backed rigged characters,
with an abstract procedural fallback. Its appearance is not evidence of scene-generation or
character-generation quality. The district's live society (`exulanica-society/v4`) is
deterministic and refuses model decisions. A saved world's purposeful society
(`exulanica-society/v2`) follows its routine too, except for a person whose world's owner chose a
model: the host asks that model at the routine's choice points, before a minute of play. The v3
engine is retired: no society is created with it and its explicitly requested model proposals are
refused, while the proposals it stored replay without a model call. Generated dialogue between
people and memory reflection are not built. A configured model role, an expensive GPU or a working
API response does not establish these capabilities.

The quality target is the strongest demonstrated result for each user task. Compare stronger
reasoning models for grounded Companion answers and for the people of a world; compare
perception and geometry candidates against actual source failures; evaluate reusable rigged assets,
materials and animation for character quality. Rendering and collision keep their existing local
runtime. Save expensive outputs and reuse them. Track model, provider, checkpoint, quality
judgments, latency, memory and cost for each comparison. Promote quality improvements within an
explicit interactive or offline execution budget; do not select solely by model size or price.

### Candidates to compare

These are challengers for targeted comparisons, not established winners or enabled runtime roles;
the implemented baseline stands until a comparison beats it. Their sources were read on 2026-09-12
and 2026-09-13, and availability, licences and runtime compatibility must be checked again before
any comparison.

For customizable people, compare established parametric and rigged asset pipelines before training
a model solely to obtain body and wardrobe variation.
[MPFB](https://static.makehumancommunity.org/mpfb/docs.html) provides character, asset, rigging and
export workflows; its [core assets](https://static.makehumancommunity.org/about/license.html) are
CC0 while the authoring code uses a separate license.
[MHR](https://github.com/facebookresearch/MHR) provides a parametric body, skinned mesh, detail
levels and corrective shapes. The MPFB builder in the repository, and what a person's saved look
holds, are the [character contract](character-representation-contract.md)'s. Garment fit, contact,
stylization and browser performance require visual acceptance; a functioning editor is not a
measured visual-quality selection.

Pretrained inference, per-source body fitting and model training have different inputs and costs.
Evaluate inference first where an existing model addresses a real gap. TRELLIS.2 provides textured
asset generation and training code, but its image-to-GLB output alone does not establish an
animation-ready human. Fine-tuning requires a defined target failure and dataset; budget inference
hardware separately from training hardware. Retain generator versions, inputs, seeds, material and
rig dependencies and outputs for reuse and reproducibility.

The sparse-capture research candidate is a self-hosted Cosmos 3 Nano or Super comparison: rebuild
from real photographs alone versus those photographs plus generated views, with held-out real views
excluded from both runs. Pin the exact model revision, licence and runtime before an experiment; the
[license matrix](license-matrix.md#12-generated-appearance-models) records both checkpoints under
OpenMDW-1.1 and pins Cosmos 3 Nano. Generated content stays labeled as imagined and outside observed
evidence and spatial claims; it cannot increase an observed-coverage claim. Measure geometry,
reprojection and visual consistency under equal capture inputs. The comparison requires the relevant
personal model and host rights and does not authorize a deployment or compute run.

| Task | Candidates | What is not established |
| --- | --- | --- |
| Grounded Companion answers | Larger reasoning models against Nano, judged with the blinded human review the roadmap requires | The 2026-09-22 comparison kept Nano against Nemotron Super and Ultra on an automated rubric. A listing in the [Nebius public catalog](https://tokenfactory.nebius.com/api/public/models_info) does not establish inference health |
| A person's decisions | Further open models through the comparison runner ([judged comparisons](#judged-comparisons-of-models-deciding-for-people)) | A model is offered to the role only after a recorded probe verifies it answers a choice |
| Photograph understanding | M3 against [Kimi-K3](https://huggingface.co/moonshotai/Kimi-K3), listed as image-capable | Supported observations and omissions on the same authorized images; its custom licence is UNVERIFIED in the [license matrix](license-matrix.md#32-non-nvidia-models-on-nebius-token-factory) |
| Mask quality | [SAM 2.1 Base+ or Large](https://github.com/facebookresearch/sam2) against the Tiny checkpoint in use, with the same boxes; [SAM 3](https://github.com/facebookresearch/sam3) separately, for concept and detection failures | Better boundaries, or acceptable memory and latency, on our photographs. SAM 3 uses the SAM License and a different integration, and the license matrix blocks it for use in the repository. SAM 3.1's video tracking alone does not justify changing the still-image pipeline |
| Single-image geometry | [MoGe-3](https://github.com/microsoft/MoGe) against MoGe-2 on the Linux GPU path | Scale, held-out views and memory; upstream reports no macOS support, and it does not replace absent multi-view coverage |
| Multi-view pose | [MapAnything, Apache variant](https://github.com/facebookresearch/map-anything), for adequate captures that fail registration | Reliable recovered geometry on our scenes; learned predictions still need independent validation |
| Authored textured 3D assets | [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) for generated PBR assets; [SAM 3D Objects](https://github.com/facebookresearch/sam-3d-objects) for masked objects | Generated completion is not observed geometry. The TRELLIS.2 reference runtime needs Linux and at least 24 GB of NVIDIA memory; rigging and in-app visual acceptance are separate work |
| Scene-derived character bodies | [SAM 3D Body](https://github.com/facebookresearch/sam-3d-body) as a source-to-body fitting candidate | A fitted body is not an established identity, a complete texture or a finished animation pipeline. Preserve uncertainty, source lineage and existing person-link authority |
| Retrieval | [Qwen3-Reranker-8B](https://huggingface.co/Qwen/Qwen3-Reranker-8B) or [0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) for misranking; [SigLIP 2 SO400M](https://huggingface.co/google/siglip2-so400m-patch14-384) or [Base Patch16 224](https://huggingface.co/google/siglip2-base-patch16-224) for visual details captions omit | Use only after diagnosing the retrieval failure. Token Factory availability and cost; a changed vector space needs versioned re-embedding and keeps permission filtering |

Begin with a small fixed set of representative failures, ordinary tasks and cases that should
abstain. Score factual support, task success, visual, mask or geometry quality and human preference
separately from latency and cost. Include source withdrawal and branch isolation cases. The first
screening narrows candidates; it cannot prove a universal best model or establish human behavior
prediction from a fluent answer. Model-driven society decisions are stored with their inputs and
model identity, so replay consumes recorded decisions instead of repeating inference.

**Scale boundary:** exact search uses `halfvec(4096)`. Standard pgvector HNSW and IVFFlat half-vector
indexes support at most 4000 dimensions. Before claiming large-library scalability, compare indexed
reduced-dimension, subvector or quantized recall with exact full-vector reranking and permission
filtering; changing a model or vector space needs versioned re-embedding, not mixing old and new
vectors. [Primary limit](https://github.com/pgvector/pgvector#hnsw). The local file store and worker
topology also need shared-storage and concurrency evidence before a multi-host claim. Reuse their
interfaces; do not introduce infrastructure on speculation.

---

## Historical selection rationale

The earlier platform comparison, provider observations, pricing and unattended-demo assumptions
remain in the [fixed research revision](https://github.com/twinkling-reality/exulanica/blob/857cffe730dad97f9edb34535c773115277e2769/docs/model-and-service-selection.md#historical-research-context).
They are not a second routing table. The implemented stack and scoped comparisons above own model
selection; the manifest and actual callers determine which configured role executes.

[Deployment](deployment.md) owns service configuration, [security](security-floor.md) owns outbound
access and permissions, and the [license matrix](license-matrix.md) owns artifact license decisions.
A historical catalog listing is not proof of availability or permission for another execution.

# Decision roles and model decisions

Status: **ONE ROLE REGISTERED: A PERSON IN A PURPOSEFUL SOCIETY**. A role's contract is data and
one adapter module; hosting a role in a world also takes the code that
[adding a role](#adding-a-role) lists, which only the person has.

A world's owner can hand some of the choices made in their world to an open model: which model
decides for which of the world's people. This contract owns that path for every kind of thing a
model may decide for, called a decision role: the role registry and what adding a role takes, the
owner's choice of a model, the person role's contract, how the playback host asks a chosen model
before a minute and what it may spend, what each decision does in its minute, and replay. The
society's engines, routines, inputs and persistence are the
[synthetic society contract](synthetic-society-contract.md)'s; running the same hour once per model
and scoring it is [comparisons of models](society-experiments.md#comparisons-of-models)'s; which
models exist and what they were measured to do is
[model and service selection](model-and-service-selection.md)'s.

In short: before each minute of a playing world, the host asks the chosen model what each of its
people at a choice point does next, offering only what the world's own routine could start for
them then. The model answers with one offered label. The answer is stored as a receipt, the minute
checks it again and applies it or records why not, and replay applies the stored receipts without
calling a model. With no choice recorded, nothing is asked or reserved and the routine decides.

<details>
<summary>Sections</summary>

- [Roles as data](#roles-as-data)
- [Adding a role](#adding-a-role)
- [The owner's choice](#the-owners-choice)
- [The person's contract](#the-persons-contract)
- [The host's decision phase](#the-hosts-decision-phase)
- [Spend](#spend)
- [What a decision does in its minute](#what-a-decision-does-in-its-minute)
- [Replay](#replay)
- [Implementation and evidence](#implementation-and-evidence)

</details>

## Roles as data

A decision role is a kind of thing in a world that changes and chooses at choice points of its own,
whose choices a world's owner may hand to an open model. Each role is one entry of the registry
catalog `assets/catalogs/roles/decision-roles.v1.json`, read at its newest version by
`exulanica/world/decision_roles.py`. An entry states, with a licence and a reason like every catalog
entry:

| Field | What it states |
| --- | --- |
| `key` | The role's name, which every stored call record of its decisions carries |
| `subject`, `choice_subjects` | What it decides for, and the field (`people` or `subjects`) a choice names them under |
| `adapter` | Its adapter module in `exulanica/world/roles/` |
| `engines` | The society engines whose minutes consume its receipts |
| `required_use_cases` | The catalog use cases a model must declare to be offered it |
| `catalog_directory`, `action_catalog`, `policy_catalog`, `action_version`, `policy_version` | Its contract's two catalogs, and the versions a new request records |
| `own_order_from_policy_version` | The policy version from which a model is asked in its own measured answering order |
| `subjects_bound` | The policy key bounding how many of its subjects models run at once |
| `request_profile`, `receipt_profile`, `choice_profile`, `context_profile` | The profiles of its documents |
| `prompt_version`, `instruction`, `choice_description`, `not_offered` | Its prompt: the one instruction, how the one choice is described, and what a model is told when its answer was not offered |

The adapter is the only code a role has of its own: which of its subjects are at a choice point
(`subjects`, `due`), their options and what a model reads (`options`, `context`,
`option_from_record`, `messages`), how the engine checks a validated choice again, promises and
applies it through its seam, and the events it records (`apply`, `events`), with the reasons only
its own checks give (`REASONS`, never one of the generic path's). An entry names a module of that
one package by key, so catalog data never chooses an import path. Everything else is one path for
every role: requests, receipts and their checks, the minute loop and replay
(`exulanica/world/role_decisions.py`); the ask, its bounds and the host's decision phase
(`exulanica/api/decision_host.py`); the owner's choices
(`exulanica/world/society_model_choice_repository.py`); and the decision tables. The model layer
names no role: a role's requirements reach it as a `ChosenRoleBinding`, and
`tests/test_decision_roles.py` scans `exulanica/models` for role names.

The person is the one registered role: key `society_decision`, subject `person`, hosted by the
purposeful society (`exulanica-society/v2`) and the living town (`exulanica-society/v5`). Its
adapter is `exulanica/world/roles/person.py`, over its contract in
`exulanica/world/society_decision_contract.py` and its minute in
`exulanica/world/society_model_decisions.py`; a person in a living town is offered the living
engine's own answer set and applied through its choice seam, in
`exulanica/world/society_living_decisions.py`, by the state family the engine table states, and
any other family is refused by name (`person_family_unsupported`). The engines the registry names are held equal to the
engines whose `owner_model_choice` the engine table states (`tests/test_decision_roles.py`). A role
declared in test data alone, a traffic signal at a junction (`tests/decision_role_fixtures/`), runs
through the minute loop, the one hosted ask and replay with a scripted model, and replays with no
call; no society engine hosts it, so the host, the repositories and a society's step are not run
for it.

## Adding a role

What a role needs as data and one module, with no migration:

1. A registry entry, in a new registry version beside the last (`decision-roles.v<N>.json`).
   Nothing stored records the registry's version: a request records its role's own profile and
   contract.
2. An adapter module in `exulanica/world/roles/` defining `ROLE`, `KINDS`, `IDLE_KIND`, `REASONS`,
   `subjects`, `due`, `options`, `context`, `option_from_record`, `messages`, `apply` and `events`.
   The idle kind changes nothing and is offered only beside something else.
3. Its two contract catalogs, read by the shared schemas in `exulanica/world/role_catalogs.py`: an
   action catalog stating each kind once with the lowercase words a model reads and the
   placeholders its adapter fills, and a policy catalog stating exactly the generic bounds
   (`POLICY_KEYS`) and its `subjects_bound`. The loader refuses a deadline that does not end inside
   the 30 second playback lease, a policy that accepts no answering mechanism or ranks two alike,
   an `options_maximum` below two, and a reserve of the whole budget.
4. Profiles of the shapes `PROFILE_PATTERNS` states (`exulanica.<name>-decision-request/vN`,
   `-decision/vN`, `-model-choice/vN` and `-context/vN`), none shared with another role. Migration
   0117 admits any request, receipt and choice of those shapes, and a choice naming 1 to 512
   subjects under `people` or `subjects`; which role a profile names, and whether it is registered,
   the application checks when it reads the document.
5. Models for it. A model is offered to a role when its manifest catalog use cases hold the role's
   and its entry names an answering mechanism a recorded probe verified
   ([model and service selection](model-and-service-selection.md#providers-chosen-roles-and-a-persons-decisions)).
   The deployment preflight holds the models each registered role is offered to that role's use
   cases.

What a role in a world still needs in code, because only the person is built:

- **An engine that hosts it.** Only a stored society holds decisions: the decision tables bind
  every request and receipt to a society row, and the purposeful engine's and the living town's
  steps apply a hosted role's receipts (`apply_receipts`, called from
  `exulanica/world/society_repository.py`). The binding triggers admit a role's documents only in
  an `exulanica-society/v2` or `v5` society (migration 0120), and the retired social profile only
  in `v3`, so a role another engine hosts needs a migration widening them and that engine's step
  applying receipts through the generic seam. The living society over a district (`v4`) consumes
  no receipts. Flight is derived and never stored, and traffic has
  no runtime ([movement modules](movement-modules-contract.md#a-model-choosing-for-a-flyer)), so
  neither can host a role.
- **A route and a panel.** The models route and the People panel serve the one role whose subject
  is `person` (`SUBJECT` in `exulanica/api/routes/society_models.py`), and answer
  `409 role_not_registered` unless exactly one registered role decides for people.
- **Comparisons.** A comparison names the role it asks by the contract its definition records,
  which the registry resolves to one role (`RoleRegistry.for_contract`), and asks it through the
  generic path, and the start controls offer the roles the society's engine hosts. Its waiting
  anchor applies the person's wait, and migration 0113 admits only the person's request and receipt
  profiles in a comparison's decisions, so a second role's comparison needs both.
- **Words.** The page and the Companion have words for the person's reason codes only, the
  `decision_reason` entries of `assets/catalogs/society-words/society-inhabitant-words.v1.json`,
  held to the person's reasons by `tests/test_companion_decision_model.py` and
  `web/packages/app/test/society-models-words-parity.test.ts`.
- **One role per subject at a time.** A subject has at most one request a minute, whatever its
  role (`prepare_role` in `exulanica/world/society_decision_repository.py`). A request's id is
  derived from its role's subject word, the subject and the minute, so the registry refuses two
  roles that decide for one kind of subject (`role_subject_shared`), as it refuses two that state one
  profile (`role_profile_shared`). With several hosted roles, the host reserves each role's
  requests of a minute in a transaction of its own, asked again on its own after a race, and asks
  every role at once, each to its own deadline, so a race or a slow model of one role leaves the
  others' requests asked in their minute (`tests/test_decision_host_roles_postgres.py`, with two
  roles made from the person's adapter under other keys).

## The owner's choice

`POST /world/versions/{version_id}/society/models?world_id=W` records one choice,
`{idempotency_key, people: [subject_id, ...], model: {provider, model_id} | null}`, for one person or
a group; a null model is their own routine. It requires `world.write` and `model.invoke`, which in a
browser only the workspace's owner holds, because a choice commits the world's host to asking the
model. Choices are appended in order to `world_society_model_choice` (migration 0110) under the
role's choice profile (`exulanica.society-model-choice/v1`), each naming who made it, and are never
changed. A person's model is the latest choice naming them, and a society with no choice is run by
its routine alone.

A choice may name only people of this society and a model the manifest declares, offers the
person's role and the contract can ask by a verified mechanism; otherwise it is refused by name
(`CHOICE_REFUSALS`): `422` for `person_not_in_this_world`, `person_named_twice`,
`model_not_declared`, `model_not_offered`, `model_not_askable` and `too_many_model_people` (more than
`model_people_maximum` people run by models at once), and `409` for a society whose engine takes no
choice (`engine_takes_no_model_choice`) or a key reused for another choice (`choice_key_reused`). An
exact retry of a key is answered with the choice it recorded before anything else is checked, so it
still returns after its model stops being offered. Whether this process can reach the model's
provider is the host's to say, never a reason to refuse the choice: a choice outlives a deployment.

`GET` at the same path, with `world.read`, returns the models the person's role is offered, in plain
words with whether this process can ask each; whether this host asks models for the world at all,
and why not (`host_refusal`: `models_not_run_here`, `provider_credential_absent`,
`process_budget_spent` or `process_share_spent`); each person's choice, with why its model is not
asked here when it is not (`refusal`, one of `MODEL_REFUSALS`); each person's latest decision; and
per model the decisions asked, accepted and applied, why the rest were not acted on, latency and
cost, over the society's latest 2,000 decisions (`DECISIONS_READ`). Neither route asks a model.

In a saved world the People panel offers the choice for one person or for everyone and shows this
read (`web/packages/app/src/composition/society-models-mount.ts`). Where the host cannot ask a
person's model, the page says the person follows their own routine for now, and why.

## The person's contract

The person's contract is the two catalogs its registry entry names in `assets/catalogs/society/`:
the actions (`society-decision-action`) and the bounds (`society-decision-policy`). A new request
records version 2 of both; a request asked under version 1 records it and is read and replayed under
version 1.

| Action | Kind | Words a model reads | Versions |
| --- | --- | --- | --- |
| `go` | `target` | `{activity}, {metres} m away`, such as "resting on a bench, 5 m away" | 1 and 2 |
| `wait` | `wait` | "wait here a minute" | 1 and 2 |
| `stand` | `stand` | "stand a while nearby" | 2 |
| `talk` | `talk` | `talk with person {number}, {metres} m away` | 2 |

**When a person is asked.** At the routine's own choice point: when they have no goal, or their
action has completed (`at_choice_point`). A person blocked on the way to a goal keeps it, as the
routine keeps it for them, and is not asked.

**What they are offered.** Only what the routine itself could start for them then, by its own rules
(`choice_options`): each enabled place they can reach that has room for them, labelled by what the
routine calls the activity there and the walk to it; where the contract states them and the input's
routine has people stand and talk, standing a while when an open spot lies within the routine's
standing reach, and talking with each person the routine could pair them with, somebody within its
talking reach who is free to choose or standing, with two open spots beside each other both can walk
to; and waiting a minute. The nearest places and people are kept, `options_maximum` in all with
standing and waiting, and the options are shuffled by the society's seed, the person and the minute,
which the request records with their order, because the order a model reads its options in moves its
choice. Under version 1 the options are the nearest places, `options_maximum` less one, then
waiting. The model replaces the routine's draws and its preference that a tired person rests first,
never its rules of what can be done. A person with fewer than two options, or nothing but waiting,
is not asked, and neither is one whose situation is larger than `context_bytes_maximum`; nothing is
reserved for either.

**What the model reads.** The role's fixed instruction, then the person's situation (the minute,
whether they have just arrived, just finished or are waiting, their tiredness out of 1000 against
the routine's rest threshold, and the last place they used), their options, and how to answer
(`situation` in `exulanica/world/society_decision_contract.py`). Nothing in it is a name or an
account holder's text: an option is built from catalog words, a walking distance and, for somebody
to talk with, the number their simulated name ends with.

**How it answers.** Through one function, `act`, forced by name, whose one argument, `action`, is an
enum of exactly the offered labels, or through a strict JSON schema of the same enum
(`exulanica/models/choice.py`). The function's name, its argument's and its description are fixed
product values. The mechanism is the first the model's manifest entry names as verified by a
recorded probe, taken in the answering order the entry states where a measurement gave the model
one (from policy version 2) and otherwise in the policy's ranks, a forced call first. An answer that
is not an offered label is asked once more with the role's `not_offered` note; after
`answer_attempts_maximum` answers the routine decides that turn. What four open models chose under
version 2, and where a decision's time goes, is measured in
[model and service selection](model-and-service-selection.md#standing-and-talking-and-where-a-decisions-time-goes).

The bounds both policy versions state:

| Bound | Value | What it bounds |
| --- | --- | --- |
| `model_people_maximum` | 8 | People models run at once in one society |
| `options_maximum` | 24 | Options one request offers, waiting and standing included |
| `context_bytes_maximum` | 12,000 | Bytes of one person's situation |
| `answer_attempts_maximum` | 2 | Answers asked for one decision |
| `decision_deadline_ms` | 20,000 | The time every ask of a minute ends by |
| `concurrent_calls_maximum` | 8 | Asks under way at once |
| `decisions_per_world_hour_maximum` | 600 | Decisions asked of models for one world in the last hour |
| `spend_per_world_hour_microusd` | 250,000 | The cost of one world's decisions in the last hour |
| `process_reserve_percent` | 50 | The share of the process's model budget decisions leave for other work |
| `answer_rank_tool_call`, `answer_rank_json_schema` | 1, 2 | The contract's order of answering mechanisms |

## The host's decision phase

Before each minute of a playing purposeful society in a workspace the host's environment lists
(`EXULANICA_SOCIETY_CONTROL_WORKSPACES`), the playback worker's claim runs the decision phase
(`DecisionHost.before_minute` in `exulanica/api/decision_host.py`), the one path every role is asked
by. A workspace the worker plays through account-wide discovery alone is asked nothing
(`models_not_run_here`). In order:

1. **Close what an earlier host left open.** A request reserved in the last four minutes with no
   receipt, left by a host that stopped between reserving and recording, is closed as
   `unanswered_in_its_minute`; its minute already ran with the routine deciding. An older one stays
   as it is: nothing replays or waits on a request without a receipt.
2. **Decide what cannot be asked, writing nothing.** A process with no model client, or whose budget
   or share ([spend](#spend)) fits no ask of any offered model (`HOST_REFUSALS`), asks nobody. A
   person whose chosen model is no longer offered, is served by another provider than the choice
   names, is served by a provider this process refuses, or needs more for one ask than the budget
   or the share has left (`MODEL_REFUSALS`) is not asked. The models route says which, for the host
   and for each choice.
3. **Let the workspace's rules judge the question.** Once a minute, with no lock held, the
   workspace's rules judge the role's fixed choice description and every label anybody due could be
   offered, in one pass for each chosen model. A description the rules would change, as a saved
   name one of whose parts is a word of it would, asks nobody of that model and writes nothing
   (`question_changed_by_rules` on the models route). A label they would change, a place a saved
   name happens to match, is left out of that person's options.
4. **Reserve.** In one transaction for each role the host reserves a request
   (`exulanica.society-decision-request/v2`) for each person still due, bound to the state, the input
   and the options offered. A request past the world's hourly bounds is answered at once with a
   receipt naming the bound (`world_hour_decisions_spent` or `world_hour_spend_spent`), counted from
   the hour's receipts with an unknown cost at its bound and each ask admitted that minute at its
   bound.
5. **Ask with no connection held.** The host commits, closes its connection and asks the models
   concurrently, every role at once and at most a role's `concurrent_calls_maximum` of its asks at
   once. Every ask of a role ends by one time: its contract's deadline after the phase begins, and
   never later than the 30 second lease leaves the minute to commit in. A phase with no time left
   asks nobody, and an ask that could only start after that time records `no_time_to_ask`.
6. **Record.** Each receipt (`exulanica.society-decision/v2`) is recorded in its own transaction and
   checked against the state and input then: a receipt asked over another state or input is
   `stale` (`decision_context_changed`); one whose inputs can no longer be authorised is
   `unavailable` (`decision_sources_unavailable`), keeping the call it made; and an accepted answer
   whose call names another provider, model, mechanism or prompt than its request is `rejected`
   (`provider_configuration_changed`).

The claim then advances one minute, so no later choice point of a person a model runs passes
unasked. The page never asks a model, and a manual step asks nothing: it takes only receipts already
recorded.

## Spend

Two bounds hold whoever plays the world. The hourly bounds above hold each world. The process's
model budget (`EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`) is a ceiling for the life of the
process that every model call it makes shares, the Companion, photograph ingestion, vision and
caption search among them. People's decisions may use all of it but the contract's
`process_reserve_percent`, which they leave for that other work, so a world played for hours never
leaves the Companion or ingestion refused. The budget holds each admitted call's reservation until
its usage is recorded, so calls admitted at once never cross the ceiling together.

The host decides on what the process has spent, whoever spent it, never on what calls under way
hold. Once what is left, beside the part kept for other work, fits no ask, it asks nobody, and the
models route and, where the host plays workspaces its environment lists, `/readyz` say so
(`process_share_spent`, or `process_budget_spent` when the whole budget does not fit). Spending only
grows while the process runs, so either holds until it restarts. A person whose own model needs more
for one ask than is left is not asked, while a cheaper model may still be asked for others. An ask's
need is its bound (`ask_bound_usd`): every answer the contract allows, each reserved for the role's
instruction, its `not_offered` note and twice the largest situation a request may carry, at the
model's own answer bound. A call under way can still leave one ask no room for its reservation,
which that ask's receipt names.

The recorded choice is what authorises this spending: a caller who may play the world
(`world.write`) starts it by playing, without holding `model.invoke`, and never beyond these bounds.
A comparison of models run by the local command spends from its own process's budget and keeps none
of it back; one started from the application spends within the bound its owner stated, a part of
the playing process's budget, and leaves the contract's share for the process's other work. A
world's hourly bounds do not apply to either, since a comparison writes nothing the live world reads
([comparisons of models](society-experiments.md#comparisons-of-models)).

## What a decision does in its minute

The minute consumes every receipt recorded since the last one it consumed, in decision order, and
decides for each, with no model, what it does (`model_goal_policies` in
`exulanica/world/society_model_decisions.py`):

| The receipt | Disposition | Reason |
| --- | --- | --- |
| Not accepted | its status: `rejected`, `unavailable` or `stale` | the receipt's own; the routine decides that turn |
| Accepted, but asked over another state, input or branch, or for somebody no longer here | `stale` | `decision_context_changed` |
| For a person whose own direct request this minute moves them | `superseded` | `person_asked_directly` |
| A second receipt for somebody already decided this minute | `superseded` | `subject_already_decided` |
| A choice of a place, a wait or a stand that no longer holds when checked again | `rejected` | `action_in_progress`, `input_unavailable`, `target_disabled_or_removed`, `current_position_invalidated`, `known_target_unreachable`, `place_taken_this_minute` or `no_room_to_stand` |
| A choice to talk that no longer holds | `rejected` | `partner_busy`, `partner_not_free` or `no_room_to_talk` |
| Anything else | `applied` | the receipt's own, `validated_choice` |

Choices to talk are checked after every other choice of the minute, in decision order. The other
person is busy (`partner_busy`) whenever anybody decided for them in that minute: a direct request,
an applied choice, a conversation already promised, or their own model's choice of anything but this
same conversation, whichever receipt came first. They must still be free to choose or standing by
the routine's rule, judged by their tiredness as the minute will have it, and within the talk's
reach (`partner_not_free` otherwise), and two open spots beside each other must be left for the pair
(`no_room_to_talk`). Two people whose models chose each other are both applied, to one conversation.

An applied choice is the minute's goal policy for that person, promised before the minute runs and
after every direct request's, so nobody choosing for themselves in that minute takes what it holds:

- a place: the planner's goal, at the promised place, with the reason `chosen_by_their_model`;
- waiting: the person stays where they are for the minute, which the planner records as blocked
  with the reason `validated_model_wait`;
- standing: the person walks to the spot the routine's own draw picks among the open ones as the
  minute begins, and stands as long as the routine draws, with `chosen_by_their_model`;
- talking: the pair is paired before the routine's own pairs, at the spots and for the length the
  routine's pairing gives; the chooser's goal records `chosen_by_their_model` and the other
  person's `stopped_to_talk`, and the routine's own pairs take neither person nor any promised spot.

A promise that an edit and its undo inside the one minute left somebody else holding stops the
chooser with the planner's reason `route_invalidated`, and the other person is left to their
routine.

Every consumed receipt appends one `decision_applied` event after the minute's other events, naming
its `request_id`, `decision_seq`, `decision_sha256`, disposition and reason, the model as
`{provider, model_id}` and the chosen label (`chose`), and the transition binds each consumed
receipt exactly once with its disposition (`world_society_transition_decision`, migration 0055). A
receipt for somebody no longer here, one closed after its minute for a person sent away since, is
consumed by their id alone and moves nobody. `GET /world/versions/{version_id}/society/decisions/{request_id}`
reads a request and its receipt, which names the calls, tokens and cost.

Sending everyone away waits while a model decides: it is refused as `a_request_is_waiting` while a
request exists at the current minute or a receipt is unconsumed, as it is while a direct request
waits ([sending inhabitants away](synthetic-society-contract.md#sending-inhabitants-away)). The
Companion explains a goal a person's model chose from these events
([server integration](synthetic-society-contract.md#server-integration-and-http)).

## Replay

Replay applies each transition's bound receipts exactly as they were recorded and calls no model,
so the receipts, not the provider, determine the history: a model or provider that changes or is
withdrawn later changes nothing already recorded. A society replays through its stored inputs,
requests and receipts
([events, persistence and replay](synthetic-society-contract.md#events-persistence-and-replay)). A
run of minutes held outside a society, as a comparison's run or the test role's, replays through
`replay_minutes`, which rebuilds every request to the byte, answers it from the stored receipt and
holds every minute's state to its recorded digest; a difference is refused as `run_replay_mismatch`.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Registry and adapters | `assets/catalogs/roles/decision-roles.v1.json`, `exulanica/world/decision_roles.py`, `exulanica/world/role_catalogs.py`, `exulanica/world/roles/` | `tests/test_decision_roles.py`, with the test role in `tests/decision_role_fixtures/` |
| Requests, receipts, the minute loop and replay | `exulanica/world/role_decisions.py` | `tests/test_decision_roles.py` |
| The person's contract and minute | `exulanica/world/society_decision_contract.py`, `exulanica/world/society_model_decisions.py`, `assets/catalogs/society/society-decision-action.v2.json`, `assets/catalogs/society/society-decision-policy.v2.json` | `tests/test_society_person_decisions.py`, `tests/test_society_model_actions.py`, `tests/test_person_role_goldens.py` |
| One choice among labels | `exulanica/models/choice.py` | `tests/test_model_choice.py` |
| The owner's choice and its read | `exulanica/world/society_model_choice_repository.py`, `exulanica/api/routes/society_models.py`, migrations 0110 and 0117 | `tests/test_society_person_decisions_postgres.py`, `tests/test_decision_roles_postgres.py` |
| Reservations, receipts and their tables | `exulanica/world/society_decision_repository.py`, migrations 0055, 0110 and 0117 | `tests/test_society_decision_migration.py`, `tests/test_person_role_goldens_postgres.py` |
| The host's phase and spend | `exulanica/api/decision_host.py`, `exulanica/api/society_control_worker.py` | `tests/test_society_person_decisions_postgres.py`, `tests/test_society_model_actions_postgres.py` |
| Words for reasons | `assets/catalogs/society-words/society-inhabitant-words.v1.json`, `web/packages/app/src/ui/society-models.ts` | `tests/test_companion_decision_model.py`, `web/packages/app/test/society-models-words-parity.test.ts` |

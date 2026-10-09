# Decision roles and model decisions

The registry hosts two roles: `society_decision` for a person in a society and `junction_signal`
for a traffic light at a town's junction. Each role has a data contract and an adapter; its host
owns the clock, state and persistent decisions for the subject it controls.

A world's owner can hand some choices made in their world to an open model: which model decides
for a person or a traffic light. They can also hand a person to an outside program, such as a
game's bridge, under a grant they issue. This contract owns that path for every kind of thing a
decider may decide for, called a decision role: the role registry and what adding a role takes,
who decides for a subject and the owner's choice of it, the person role's contract, how the
playback host asks a chosen model or an outside program before a minute and what it may spend,
what each decision does in its minute, and replay. The
society's engines, routines, inputs and persistence are the
[synthetic society contract](synthetic-society-contract.md)'s; running the same hour once per model
and scoring it is [comparisons of models](society-experiments.md#comparisons-of-models)'s; which
models exist and what they were measured to do is
[model and service selection](model-and-service-selection.md)'s.

In short: before each minute of a playing world, the host asks the chosen model, or the outside
program the owner granted, what each of its people at a choice point does next, offering only what
the world's own routine could start for them then. The decider answers with one offered label. The
answer is stored as a receipt, the minute checks it again and applies it or records why not, and
replay applies the stored receipts without calling a model or the program. With no choice recorded,
nothing is asked or reserved and the routine decides.

<details>
<summary>Sections</summary>

- [Roles as data](#roles-as-data)
- [Adding a role](#adding-a-role)
- [Who decides: deciders and the owner's choice](#who-decides-deciders-and-the-owners-choice)
- [An outside program deciding](#an-outside-program-deciding)
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
catalog `assets/catalogs/roles/decision-roles.v<N>.json`, read at its newest version by
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
| `engine_terms` | From registry version 5: for an engine that hosts the role and asks its own questions, that engine's terms, the two catalog versions its new requests record and its own prompt (version and three texts); empty where every engine is asked under the role's own. From registry version 7 an engine's terms may also state `line_rules`, the rules beside the line rule a model's lines are held to under them (`names_no_listener`, below) |

A request is asked under the terms of the engine whose state it was asked over: the engine's own
where the entry states them, the role's otherwise (`DecisionRole.terms`). A request names its engine
in its context where the engine's terms are its own, so its prompt, its choice and its record are
read back by the same terms (`terms_of`); a request that names none was asked under the role's own.
No two roles, and no two terms of one role, share a prompt version, and an entry stating terms for
an engine that does not host it is refused by name (`role_terms_unhosted`).

A role reads its owner's choices at the profile its entry states, which a new choice records, and
at every earlier version of that profile, so a choice recorded before its role's choices moved on
is still read (`DecisionRole.reads_choice`).

The adapter defines which of its subjects are at a choice point
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

The person role has key `society_decision`, subject `person`, and is hosted by the
purposeful society (`exulanica-society/v2`), the living town (`exulanica-society/v5`) and the
society of things (`exulanica-society/v7`), whose people are asked under the society of things'
own terms ([below](#a-society-of-things-people)). Its
adapter is `exulanica/world/roles/person.py`, over its contract in
`exulanica/world/society_decision_contract.py` and its minute in
`exulanica/world/society_model_decisions.py`; a person in a living town is offered the living
engine's own answer set and applied through its choice seam, in
`exulanica/world/society_living_decisions.py`, by the state family the engine table states, and
any other family is refused by name (`person_family_unsupported`). The engines the registry names are held equal to the
engines whose `owner_model_choice` the engine table states (`tests/test_decision_roles.py`). The
signal role has key `junction_signal`, subject `signal`, and adapter
`exulanica/world/roles/junction_signal.py`. Its traffic controller holds a choice and sealed
decision in the saved world and version named by the request. No society engine hosts that role.

## Adding a role

What a role needs as data and one module:

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

What a role in a world also needs:

- **An engine that hosts it.** A stored society's decision tables bind requests and receipts to a
  society row, and the purposeful engine's and the living town's
  steps apply a hosted role's receipts (`apply_receipts`, called from
  `exulanica/world/society_repository.py`). The binding triggers admit a role's documents only in
  an `exulanica-society/v2` or `v5` society (migration 0120), and the retired social profile only
  in `v3`, so a role another engine hosts needs a migration widening them and that engine's step
  applying receipts through the generic seam. The living society over a district (`v4`) consumes
  no receipts. Traffic's separate controller persists choices, requests, receipts and segment
  continuations under the saved world and version; flight is derived and has no decision host.
- **A route and a panel.** `GET /world/versions/{version_id}/models` serves every registered role
  with offered models, subjects and choices, and the same declared semantics on each: whether a
  choice can be recorded now (`capability`, the descriptor of the choice route bound to the role),
  why this host asks no chosen model (`host_refusal`), how many subjects models may run at once
  (`model_subjects_maximum`) and the contract a new choice records (`contract`). `POST` at its
  role-key child records an owner's choice and answers a refusal with the status its code has on
  the person-specific route. Each role's host is named in code for the word its subjects are known
  by (`exulanica/api/role_hosts.py`); a registered role with no host is listed as unsupported and
  refused as `role_subject_unsupported`, so a new role is served only once its host is written. The
  Who decides panel renders the served roles. The person-specific society models route remains
  available to its existing callers.
- **Comparisons.** A comparison names the role it asks by the contract its definition records,
  which the registry resolves to one role (`RoleRegistry.for_contract`), and asks it through the
  generic path, and the start controls offer the roles the society's engine hosts. Its waiting
  anchor applies the person's wait, and migration 0113 admits only the person's request and receipt
  profiles in a comparison's decisions, so another person-hosted role's comparison needs both. The
  junction signal role is compared by its own records (migration 0132,
  [signal comparisons](traffic-contract.md#signal-comparisons)).
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

## Who decides: deciders and the owner's choice

A **decider** is what chooses a subject's next action. Its descriptor, `exulanica.decider/v1`
(`exulanica/world/deciders.py`), is one of five closed shapes:

| Descriptor | Who decides |
| --- | --- |
| `{"kind": "routine"}` | the world's own rules |
| `{"kind": "model", "provider", "model_id"}` | an open model the manifest declares |
| `{"kind": "person"}` | the world's owner, through a direct request (a place to go to or use, or in a society running the hands module a hands act), which supersedes any bound decider's answer in its minute and is never a binding of its own |
| `{"kind": "external", "bridge", "grant_id"}` | an outside program, by its bridge's key, under a grant the world's owner issued; which game, adapter version and mapping file it answers with are the grant's and each receipt's |
| `{"kind": "person", "account_id"}` | one person playing one being of a society of things ("Play this one", [below](#a-person-playing-a-being)), by the account the play route recorded, which no read shows |

A subject's decider is the latest choice naming it, and a society with no choice is run by its
rules alone. Choices are appended in order to `world_society_model_choice` (migration 0110), each
naming who made it, and are never changed. From the registry's third version a choice records its
decider under the role's choice profile `exulanica.society-model-choice/v2`; a choice of the first
profile names `model`, a model or none, and is still read as the model it names or the routine
(migration 0146 admits exactly one of the two fields). Every read of a choice gives its `decider` and
the `model` it names, none for the routine and for an outside program, so whatever asks which model
runs somebody, spending among it, reads the answer it always did.

`POST /world/versions/{version_id}/society/models?world_id=W` records one choice,
`{idempotency_key, people: [subject_id, ...], model: {provider, model_id} | null}`, for one person or
a group: a model, or with a null model their own routine. It requires `world.write` and
`model.invoke`, which in a browser only the workspace's owner holds, because a choice commits the
world's host to asking the model. An outside program is never chosen through this route: the route
that records its grant records the external choice in the grant's own transaction
(`SocietyModelChoiceRepository.record_external_choice`), and ending the grant hands every subject it
still decides for back to their routine as one choice (`release_external_choice`), read under the
society's lock, so a choice made meanwhile is never undone and a retry returns the choice it
recorded.

**A gate's travellers.** A visitor whose arrival says the world decides for it (`decided_by`
`world`, [crossings](synthetic-society-contract.md#the-society-of-things-v7)) is decided for as any
being of the world is, and a gate's travellers may be given one mind, named before any of them has
arrived: a choice of the same profile naming a group instead of people, `group: {kind:
"arrivals_under_grant", grant_id, ends_at}` with `people: []`, only in a society of things
(`engine_takes_no_traveller_choice`). The table admits exactly one of the two, and a group only of
that shape (the grant's id in canonical form, its end, which every grant has, an instant in UTC to
the second that exists on the calendar) with the world's own decider, the routine or a model
(migrations "a choice may name a gate's visitors" and "a gate's choice names its grant and a
mind"). The repository records one (`SocietyModelChoiceRepository.record_traveller_choice`, refused
as any choice of a model is) and hands a grant's travellers back to the routine
(`release_traveller_choice`). Nothing calls either yet: the door's grant route is planned to record
the choice in the grant's own transaction, to record it again with the grant's new end when that
end moves, to release it when the grant is revoked, and to need `model.invoke` for naming a model,
as naming any model does. A gate's choice decides strictly before its `ends_at`, by the database's
clock: once the grant has ended, no host reserves an ask under it for the grant's visitors, whenever
their departures are written. An ask reserved before the end still runs as reserved, and the end
does not touch the owner's own choice naming one of those visitors, which decides until the owner
changes it or the visitor leaves. Who decides for such a visitor is, in order: a choice naming
it, the latest group choice of its grant where its kind allows that decider, and the routine. The
bound on the people models run counts, in a society of things, only the beings still in it, and
holds when a minute asks: for own choices of a model, in the order they were made, past it the
routine deciding for the latest (`choice_over_bound`, as for a placed being an edit removed and an
undo restored by its id), then for a group's visitors, in the order they came, past it the routine
deciding for the rest (`travellers_over_bound`). The host and the Companion's plan read who decides
by `SocietyModelChoiceRepository.deciding`, under the contract the society's engine is asked under,
and the visitor's program is never asked. No visitor, whoever decides for it, may be handed to
another outside program (`decided_from_outside`).

A choice may name only people of this society and a model the manifest declares, offers the
person's role and the contract can ask by a verified mechanism; otherwise it is refused by name
(`CHOICE_REFUSALS`): `422` for `person_not_in_this_world`, `person_named_twice`,
`model_not_declared`, `model_not_offered`, `model_not_askable` and `too_many_model_people` (more than
`model_people_maximum` people run by models at once; an outside program's subjects are not counted),
and `409` for a society whose engine takes no choice (`engine_takes_no_model_choice`), a key reused
for another choice (`choice_key_reused`) and somebody who came into the world from outside, whose own
program decides for them (`decided_from_outside`: the owner may end its grant or send them away,
never choose for them). An exact retry of a key is answered with the choice it recorded before
anything else is checked, so it still returns after its model stops being offered. Whether this
process can reach the model's provider, or the program's door, is the host's to say, never a reason
to refuse the choice: a choice outlives a deployment.

`GET` at the same path, with `world.read`, returns the models the person's role is offered, in plain
words with whether this process can ask each; whether this host asks models for the world at all,
and why not (`host_refusal`: `models_not_run_here`, `provider_credential_absent`,
`process_budget_spent` or `process_share_spent`); each person's choice with its decider, and why its
model is not asked here when it is not (`refusal`, one of `MODEL_REFUSALS`) and where the decider
comes from (`from`: `choice`, `choice_over_bound`, `travellers` or `travellers_over_bound`); each
gate's travellers' mind (`travellers`: `{grant_id, choice_seq, decider, model}`); each person's latest
model decision;
per model the decisions asked, accepted and applied, why the rest were not acted on, latency and
cost, over the society's latest 2,000 decisions (`DECISIONS_READ`); and every subject an outside
program decides for under a grant that stands (`outside`), with what the grant view says of its
program. An outside program's decisions name no model and are neither summarised nor counted among
the models'. Each `outside` entry gives its subject's latest receipt under the entry's own grant
among those decisions (`latest`: `{decision_seq, base_tick, consumed_tick, status, reason}`, with
`consumed_tick` null until a minute consumes it), or null when none of them is one. A turn the
program left without a usable answer reads as its receipt does, such as `unavailable` with
`no_answer_in_time`: the turn the routine decided. Neither route asks a model.

In a saved world the People panel offers the choice for one person or for everyone and shows this
read (`web/packages/app/src/composition/society-models-mount.ts`). Where the host cannot ask a
person's model, the page says the person follows their own routine for now, and why.

## A person playing a being

A person holding `world.write` may play one being of a society of things whose kind lets a person
decide for it (`/world/versions/{version_id}/society/play?world_id=W`,
`exulanica/api/routes/society_play.py`). Starting records a choice naming the being with the
decider `{"kind": "person", "account_id"}`, the session's account, through this route only, and
the minute it began (`since_tick`). It is refused by name: `engine_takes_no_play` for any engine but
v7's, `being_played` where another account plays the being, `decided_from_outside` for a visitor its
own program decides for or a being under a grant, and `decider_not_allowed` for a kind that lets no
person decide (409, the last 422). While a being is played no other choice may name it
(`being_played`). Giving it back (`POST .../{subject_id}/give-back`, `not_played` where the reader
does not play it) records a choice naming the same person with `ended: given_back`; the being is
then decided for as it was before the play began, by its own earlier choice or, with none, by its
gate's group or its routine, so nothing is copied and nothing outlives a gate's release (migration
"a person plays one being" admits the person and `ended` beside it alone). Every reader of who
decides for a being reads its choices by that one rule (`latest_choices` in
`exulanica/world/society_model_choice_repository.py`): the models read, the card, the host and a
comparison's definition of everybody outside its group alike.

Each minute the being is due. `GET .../{subject_id}/turn` reads what it is offered in the minute to
come, from the stored state, as its request will offer it: each option's label, kind, the place or
being it names and whether it takes a line; the line's bound; `played_by_you`; how many quiet
minutes are left; and, where the society plays, when the minute is due and how long a minute is.
`POST .../{subject_id}/answer` takes `{base_tick, label, line}` for that minute (202): an offered
label, a line exactly where the option says something, held to the line rule, and no name the
account holder saved in the line (`line_refused_by_rules`); a minute already played is refused
`minute_passed` (409, with `current_tick`), and more than 12 answers from one account for one
minute `too_many_answers` (429). Answers are kept in `world_society_person_answer`, appended under
the workspace's row security, each naming the account that posted it, which no read shows. Only the
person playing the being answers for it or gives it back (`not_played` for anybody else, with
nothing kept), and a minute takes only that person's answer, never one another person posted
before they took the being. An answer for a being that left the world is not found (404). A line a
person types lives in their answer, the receipt's proposal, the said event and the society's state
(each hearer's heard lines and the speaker's said lines), and no tombstone reaches those records
yet: a workspace's erasure leaves them, as it leaves every society record, until a society-wide
erasure lands, which it must before any installation but a rehearsal turns societies of things on.

Before the minute the host reserves the being's request as for any decider, with the provider
record `{kind: person, contract}`, and answers it at once from the latest answer for that minute
(`answer_played` in `exulanica/world/society_play.py`): before it asks any model, and in a workspace
it asks no model for as well. Every minute stepped answers it first, however it is stepped (the
playback claim, a control's manual step or the step route all advance through
`SocietyRepository.advance`), and a being the host answered already is left as it is, so a played
being's minute never falls to its routine. Its receipt is an accepted one with `{kind: person,
answer_sha256}`, or, where none was posted, its idle option (carrying on, else waiting),
`person_no_answer`, with no digest; never the routine and never a model. A line carrying a name saved since it was posted is not said. Five such minutes in a row
(`QUIET_MINUTES`) and the host gives the being back, `ended: player_left`. The minute applies the
receipt as any decider's: its `decision_applied` event's `origin` and a line's `said` event's
`decider` read `person`. The models read shows a played being's choice as `{"kind": "person"}` with
`played_by_you` and no `chosen_by`, and the thing card's decider as `{kind: person, played_by_you,
may_change: false, refusal: being_played}`. Replay reads the receipts and needs no player.

## An outside program deciding

An outside program decides for a subject under a grant: its door (an application component the
host never imports) implements the `ExternalAsker` port of `exulanica/api/external_asking.py`, and
the application registers it with the decision host. A host with no door registered asks no
outside program and writes nothing for its subjects, and the routine decides for them, as a host
with no model client asks no model.

- **Asking.** In the decision phase the host splits each role's due subjects by decider, and
  reserves outside programs' requests before any model's, so no door's time comes out of a model's
  ask window. For each external subject it asks the door's `configuration` first, for every due
  subject at once and with no lock held, waiting no later than the role's asks must end: what the
  request records of the program as its grant stands now (`kind`, `bridge`, `grant_id`,
  `grant_seq`, `mapping_sha256` and the door's own `deadline_ms`), to which the host adds the
  contract, and a refusal decided before asking (`decider_disconnected`, `grant_revoked` or
  `grant_expired`). A statement that is malformed, names another program, gives a deadline past
  the contract's, raises or comes late leaves its own subject unasked that minute, and the routine
  decides for them. The host reserves the request as it reserves a model's, over the options the
  account holder's saved names leave sendable (no right releases a name to an outside program, so
  any saved name keeps a label out). Where a saved name is a word of the role's description, or of
  any text, in any field, of a subject's own request, nothing is sent: the request is kept and
  answered at once as `unavailable`, `saved_name_withheld`. A refused subject's request is answered
  at once as `unavailable` for its reason too, so a world counts an outside program's silence from
  its own records. The rest are asked through `answer`, from the host's
  pool beside the model asks and with no connection held, each by the sooner of the door's deadline
  from the moment it is asked and the end the lease leaves the minute. The host stops waiting then
  and never waits for a door that ignores its deadline: an answer that comes later is recorded as
  `no_answer_in_time`.
- **What is recorded.** The request's `provider_config` and the receipt's `provider` hold the
  program's record instead of a model's (`exulanica.world.deciders.EXTERNAL_CONFIG` and
  `EXTERNAL_RECORD`), each naming its kind; a model's keep exactly their fields, so every stored one
  reads as written. The receipt names the adapter's version (whole numbers joined by dots), the
  digest of the answer frame the program sent and how long it took, and no cost: an outside answer
  spends nothing. It carries no free text from the program but the line an accepted say option
  says, held to the line rule and the saved-name screen below; a correlation token, where one is
  needed, is a SHA-256 digest or none. The answer is checked as a model's is, when it arrives and
  again when it is recorded: one offered label exactly, for a reason the role records, naming the
  bridge, grant, grant revision and mapping file it was asked under, and an accepted one always
  carries the program's record. An answer that fails is recorded as `decider_disconnected`, for its
  own subject alone. A request the program did not answer ends for one of the outside reasons
  `decider_disconnected`, `no_answer_in_time`, `grant_revoked`, `grant_expired`,
  `decider_passed` or `saved_name_withheld`, whatever else changed before it was recorded, and one
  a stopped host left open closes as `no_answer_in_time`, so its receipt and its minute's event
  always name an outside program as the one deciding; the routine decides that turn. A program
  passes (`decider_passed`) when nobody there acts for its subject: the answer is recorded at once,
  with or without the program's record of the pass, and counts as the program's presence, never as
  a quiet minute. What a program
  answers when it has nothing to say is the role's idle option, `DecisionRole.idle_label(context)`:
  the label of the offered option of the adapter's idle kind (waiting a minute, for a person), read
  from the request's own context.
- **A visitor.** In a society of things, a visitor from outside is decided for by the program that
  sent it, as its arrival records: the host asks that program's door with the decider read from the
  state, no choice is recorded for it, and neither an owner's choice nor a person's direct request
  may name it (`decided_from_outside`). A visitor whose arrival said the world decides for it is not
  asked through any door: a choice naming it, or its gate's travellers' choice, decides for it as
  for any being, and only a direct request is still refused it.
- **Bounds.** External asks are outside the models' spending, the process's budget and a world's
  hourly bounds, which `world_hour` counts from model calls alone; how often a program is asked is
  its grant's to bound.
- **In the minute.** The receipt is consumed exactly as a model's, and its `decision_applied`
  event says an outside program decided (`origin: external`, `model: null`). The owner's direct
  request supersedes an outside answer for a native person that minute, as it does a model's.
- **Replay and comparisons.** Replay applies the stored receipts and never contacts the program,
  and no comparison asks one. Everybody outside a comparison's group is decided as the owner's
  latest choice names, so a subject an outside program decides for runs by their routine in every
  arm; a subject inside the group is decided by each arm's model, whoever decides for them in the
  world.

## The signal's contract

A saved town's owner may choose one offered model for each signal at a high street junction, or
restore fixed timing. The choice takes effect at a 60-second boundary at least one minute ahead,
or, in a version whose clock is coupled, one minute after the traffic it has sealed. The route
serves that target and the first sealed second at which an accepted model answer took effect
separately, with the timeline both are on (`timebase`: `unix` for shared real time, `world` for a
coupled version's traffic timeline, [world clock](world-clock-contract.md#coupled-traffic)), and
judges each choice pending, preparing, active or fixed by that timeline's present. Pending and
preparing choices do not claim that a model controls the light.

At the end of a plan's minimum green, and after each permitted one-second extension, the traffic
step derives nearby vehicle counts, queued vehicles and longest waits on the active and other
street. It asks the chosen model to keep the current green for one second or switch to amber only
when a vehicle is near. The step rechecks the recorded proposal against the plan's extension
maximum. Missing, late, refused or unavailable answers switch at the fixed timing boundary;
amber and all-red clearances still run. A choice changes neither trip draws nor a sealed minute.
The controller stores a versioned, digest-bound continuation every 60 seconds, including trip and
signal state, and replay verifies the stored decision and frame digests without a model call
(`exulanica/api/traffic_signal_controller.py`, migration 0122).

Signal models are compared over a saved town's own episodes, each model beside the plan's fixed
timing on the same seeds, with every choice point's request and receipt, the junction delay
measure, trips, unanswered points and spend kept per run
([signal comparisons](traffic-contract.md#signal-comparisons)). No benefit of a model over fixed
timing has been measured, and none is claimed: in the one paid trial the model arm's mean delay was
above fixed timing's in both towns ([signal model trial](evaluation/2026-09-30-signal-model-trial.json)).

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

### A society of things' people

A society of things' people are asked under their engine's own terms: from registry version 5,
version 3 of both catalogs and the prompt `society-person-choice/v2`; from registry version 6, the
fourth catalogs, which add the hands actions, and the third prompt; from registry version 7, the
same catalogs and the fourth prompt (below); from registry version 8, the fifth catalogs, the
fourth's actions and bounds with `context_bytes_maximum` 16,000, and the fifth prompt, which also
shows a being what it notices around it and what it remembers where its society records the notice
and memory modules ([minds contract](minds-contract.md)). Version 3 keeps version 2's actions and
bounds and adds:

| Action | Kind | Words a model reads |
| --- | --- | --- |
| `carry_on` | `carry_on` | "carry on with what you are doing" |
| `say_to` | `say_to` | `say something to the {who} (person {number}), {metres} m away` |
| `say_all` | `say_all` | "say something to everyone near you" |
| `leave` | `leave` | "leave this world" |

| Bound | Value | What it bounds |
| --- | --- | --- |
| `line_characters_maximum` | 200 | Characters of one line, as the line rule counts them (`exulanica/things/lines.py`) |
| `hearing_reach_mm` | 8,000 | How far a line carries: the routine's own reach for two people stopping to talk |
| `lines_heard_maximum` | 8 | Lines each being keeps, the oldest dropped first |
| `say_options_maximum` | 4 | Ways of saying something offered: to each of the three nearest who hear, and to everyone near |

A contract stating any of these four outside its range is refused when it loads: 1,000 to 50,000 mm,
1 to 200 characters, 1 to 64 lines and 2 to 16 ways (`POLICY_RANGES`).

**Which models they are offered.** Every model offered to the person role that answers a choice
taking a line: a model whose manifest entry says it is not offered for lines
([model selection](model-and-service-selection.md)) is not listed in a society of things' models
read, and choosing it for one of its people is refused `model_not_askable`. Nemotron 3.5 Lightning
is not offered for lines; it stays offered to the people of every other society. Nemotron 3 Super
120B is offered for lines by a strict JSON schema alone, the one mechanism its entry names: asked by
a forced call, it writes a line where the action it chose says none.

**When they are asked.** At the routine's own choice point, as every person; and also the minute
after a line was said to them, whatever is under way. A being an outside program decides for is
asked every minute.

**What they are offered.** At a choice point, the routine's options as above; and, where the being's
kind has the say ability, saying something to each of the nearest beings within hearing reach whose
kind offers hearing (named by their kind's label and the number their simulated name ends with), and
to everyone near when anybody hears; and, for a visitor whose kind has the leave ability, leaving.
While something is under way, going on with it (`carry_on`), with the ways of saying something and
leaving; a being with none of those is not asked. Going on and waiting change nothing: an outside
program's idle answer is going on where it is offered, waiting otherwise
(`DecisionRole.idle_label`).

**What the model reads.** Its terms' instruction, then the situation, which also says when
something is still under way, and the lines the being heard, oldest first, each quoted and named as
what others said, never as instructions, by who said it (kind and number), to whom and when.

**How it answers a line.** Where an option says something, the one function takes a second fixed
argument, `line`: a string of at most `line_characters_maximum` characters, or null, both arguments
required (`exulanica/models/choice.py`); `DecisionRole.line_labels` names the labels whose answer
carries a line, for a door to state. An answer naming a say option with no line, or another option
with one, is asked once more with its terms' note. Under the fourth and fifth prompts, whose
instruction asks the being to speak to the one it addresses without naming or describing them, a
line said to one being that ends with that being's name or description, as the option's words name
them (the name,
its name part, or its kind with or without an article, case and closing punctuation set aside;
`names_listener` in `exulanica/things/lines.py`), is no answer either, and is asked once more with
that prompt's note, which says so, within the attempts the contract allows; a line that ends with
the listener's kind while speaking of itself is asked again too. A receipt is held to the rule its
request's recorded prompt states (`names_its_listener`), so a request asked under an earlier prompt
reads and replays as it did. A line that breaks the line rule is
refused `line_out_of_bounds`, and one the workspace's rules would change, as they change a saved
name, `line_refused_by_rules`; either way the receipt is rejected, nothing is said and the routine
decides that turn. An accepted receipt's proposal is the label, the option and the line. A model's
line is said composed (Unicode NFC) whatever form it came in, and a line carrying any name the
account holder saved is refused `line_refused_by_rules` whatever right releases that name to the
model, since every later decider, an outside program among them, reads what was said. An outside
program's answer carries the line in its proposal too, held to the same rule: an offered say option
answered with no line, or another option with one, or a line that breaks the rule, a line not in
Unicode NFC among them (a program's line is never recomposed for it, as a model's is), is recorded
rejected `line_out_of_bounds` (the program's answer, never a quiet minute), and a line naming a name
the account holder saved is refused `line_refused_by_rules`. An outside program is never shown a
heard line that now carries a saved name (one saved after it was said): the request leaves that line
out of what it heard rather than going unsent.

**What it does in its minute.** Going on, saying and leaving set no goal: the routine goes on as it
would, and the society of things carries out the line and the leaving
([society contract](synthetic-society-contract.md#the-society-of-things-v7)).

## The host's decision phase

Before each minute of a playing purposeful society in a workspace the host asks models for, the
playback worker's claim runs the decision phase (`DecisionHost.before_minute` in
`exulanica/api/decision_host.py`), the one path every role is asked by. The host asks models for the
workspaces its environment lists (`EXULANICA_SOCIETY_CONTROL_WORKSPACES`) and, where spending is
durable and account discovery is on, for the account workspaces it plays, each ask admitted against
the workspace's own grant ([deployment](deployment.md#515-society-playback)). A workspace the
worker plays through discovery under process spending is asked nothing (`models_not_run_here`).
In order:

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
   workspace's rules judge the fixed choice description the society's engine asks by (its terms'
   own, or the role's) and every label anybody due could be offered, in one pass for each chosen
   model; a description only another engine asks by is not judged, so a saved name matching a word
   of the society of things' description stops no other engine's asks. The models route and a
   comparison's start judge a model's question the same way, by the society's engine. A description
   the rules would change, as a saved
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
recorded, besides the answers of the beings people play, which every step records first.

## Spend

Two bounds hold whoever plays the world. Both bound model calls: an outside program's asks spend
nothing and are bounded by its grant ([an outside program deciding](#an-outside-program-deciding)). The hourly bounds above hold each world. The process's
model budget (`EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`) is a ceiling for the life of the
process that every model call it makes shares, the Companion, photograph ingestion, vision and
caption search among them. People's decisions may use all of it but the contract's
`process_reserve_percent`, which they leave for that other work, so a world played for hours never
leaves the Companion or ingestion refused. The budget holds each admitted call's reservation until
its usage is recorded, so calls admitted at once never cross the ceiling together. A process that
spends durably also admits every ask through the workspace's grant under the installation's spending
authority, which a restart does not refill ([model spending](model-spending-contract.md)); a
refusal there is recorded on the receipt by its own reason (`spending_not_granted`,
`spending_revoked`, `spending_expired`, `spending_limit_reached`, `spending_suspended`,
`spending_unavailable` or `spending_scope_missing`), and ends a comparison run by that reason.
The host reads once a claim what the authority would answer the workspace's next attempt, by
provider, with each provider's remaining USD. A subject whose model's provider would be refused is
not reserved for and decides by its routine, so a spent allowance writes no receipt and takes no
admission lock. The claim's requests then spend that remainder down by each one's one-attempt
reservation, its prompt included; a request whose attempt no longer fits is recorded as
`spending_limit_reached` without asking admission, so it takes no admission lock either, the
control read sees its receipt, and a new, larger grant is asked at once.

The host decides on what the process has spent, whoever spent it, never on what calls under way
hold. Once what is left, beside the part kept for other work, fits no ask, it asks nobody, and the
models route and, where the host asks models for any workspace, `/readyz` say so
(`process_share_spent`, or `process_budget_spent` when the whole budget does not fit). Spending only
grows while the process runs, so either holds until it restarts. A person whose own model needs more
for one ask than is left is not asked, while a cheaper model may still be asked for others. An ask's
need is its bound (`ask_bound_usd`): every answer the contract allows, each reserved for the
instruction of the terms asked under that contract (an engine's own terms where it states them, so
one engine's longer prompt raises no other's bound), its `not_offered` note and twice the largest
situation a request may carry, at the model's own answer bound. The models reads judge it the same
way, under the contract the society's engine is asked under. A call under way can still leave one ask no room for its reservation,
which that ask's receipt names.

The recorded choice is what authorises this spending: a caller who may play the world
(`world.write`) starts it by playing, without holding `model.invoke`, and never beyond these bounds.
A comparison of models run by the local command spends from its own process's budget and keeps none
of it back; one started from the application spends within the bound its owner stated, a part of
the playing process's budget, and leaves the contract's share for the process's other work. A
world's hourly bounds do not apply to either, since a comparison writes nothing the live world reads
([comparisons of models](society-experiments.md#comparisons-of-models)). A comparison over a day
asks each person a model decides for at most once a minute for 1440 minutes, 24 times what an
hour's can, and its plan states that most for one decided person before anything starts
([running a comparison](society-experiments.md#running-a-comparison)).

## What a decision does in its minute

The minute consumes every receipt recorded since the last one it consumed, in decision order, and
decides for each, with no model, what it does (`model_goal_policies` in
`exulanica/world/society_model_decisions.py`):

| The receipt | Disposition | Reason |
| --- | --- | --- |
| Not accepted | its status: `rejected`, `unavailable` or `stale` | the receipt's own; the routine decides that turn |
| Accepted, but asked over another state, input or branch, or for somebody no longer here | `stale` | `decision_context_changed` |
| For a person a direct request applied this minute decides for | `superseded` | `person_asked_directly` |
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
its `request_id`, `decision_seq`, `decision_sha256`, disposition and reason, who decided (`origin`:
`model`, or `external` for an outside program, by its receipt's record or a reason only an outside
ask gives), the model as `{provider, model_id}` or null for an outside program, and the chosen label
(`chose`), and the transition binds each consumed receipt exactly once with its disposition
(`world_society_transition_decision`, migration 0055). A
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
The loop may start from a later state than a genesis, numbering its receipts on from the last one
recorded before it, and the minute that leaves the genesis alone consumes every input, so a run
played on from where its previous hour ended is that hour of the whole run. A run stopped part way
goes on through `resume_minutes`: every minute whose receipts it recorded is answered from them,
as a replay answers, and only the later minutes are asked, so nothing recorded is asked again; a
stored request the loop does not rebuild stops it by name.

## Implementation and evidence

| Part | Source | Tests |
| --- | --- | --- |
| Registry and adapters | `assets/catalogs/roles/decision-roles.v<N>.json`, `exulanica/world/decision_roles.py`, `exulanica/world/role_catalogs.py`, `exulanica/world/roles/` | `tests/test_decision_roles.py`, with the test role in `tests/decision_role_fixtures/` |
| Deciders and outside programs | `exulanica/world/deciders.py`, `exulanica/api/external_asking.py`, the host's outside path in `exulanica/api/decision_host.py`, migration 0146 | `tests/test_outside_deciders.py` (each answer and statement a door may give, late, failing or malformed, costing its own subject alone; a context carrying a saved name in any field), `tests/test_outside_deciders_postgres.py` (a request left open by a stopped host; a request carrying a saved name kept, answered at once as `saved_name_withheld` and not sent; a visitor whose program a saved name keeps unasked going home after its quiet minutes; a released grant's retry) |
| Requests, receipts, the minute loop and replay | `exulanica/world/role_decisions.py` | `tests/test_decision_roles.py` |
| The person's contract and minute | `exulanica/world/society_decision_contract.py`, `exulanica/world/society_model_decisions.py`, `assets/catalogs/society/society-decision-action.v2.json`, `assets/catalogs/society/society-decision-policy.v2.json`, `assets/catalogs/society/society-decision-action.v3.json`, `assets/catalogs/society/society-decision-policy.v3.json` | `tests/test_society_person_decisions.py`, `tests/test_society_model_actions.py`, `tests/test_person_role_goldens.py`, `tests/test_society_lines.py`, `tests/test_society_lines_postgres.py` |
| One choice among labels | `exulanica/models/choice.py` | `tests/test_model_choice.py` |
| The owner's choice and its read | `exulanica/world/society_model_choice_repository.py`, `exulanica/api/routes/society_models.py`, migrations 0110 and 0117 | `tests/test_society_person_decisions_postgres.py`, `tests/test_decision_roles_postgres.py` |
| Reservations, receipts and their tables | `exulanica/world/society_decision_repository.py`, migrations 0055, 0110 and 0117 | `tests/test_society_decision_migration.py`, `tests/test_person_role_goldens_postgres.py` |
| The host's phase and spend | `exulanica/api/decision_host.py`, `exulanica/api/society_control_worker.py` | `tests/test_society_person_decisions_postgres.py`, `tests/test_society_model_actions_postgres.py` |
| Words for reasons | `assets/catalogs/society-words/society-inhabitant-words.v1.json`, `web/packages/app/src/ui/society-models.ts` | `tests/test_companion_decision_model.py`, `web/packages/app/test/society-models-words-parity.test.ts` |

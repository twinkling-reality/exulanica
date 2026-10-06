# People and models in a world

The people in a world are its agents. They live by a routine, the world's owner can hand their
choices to an open model, and the same hour can be run again under another model to see what each
one does differently. This guide explains what works, how to use it and where it stops; the
contracts it links own the exact rules.

## Which worlds have people

A saved world has people once a society is brought into it. Each kind of saved world can hold one:

| World | Ground its people walk | Where they arrive |
| --- | --- | --- |
| Started from the empty authored starter | The ground the starter states | The starter's spawn point |
| Made from photographs | A floor the world declares in the region its society lives in, drawn as a floor | The region's origin |
| Generated from a recipe | The footways and doors the town's own records state | The town's spawn point |

In a starter or a world made from photographs the society starts with eight people on a square
about 24 metres across, routed over a 2 metre lattice; a generated town holds one person for each
place in a home its premises offer, at most 128, as the ground catalog
[`society-ground.v2.json`](../../assets/catalogs/society-ground/society-ground.v2.json) states. A
world made from photographs holds one society, in one region. The owned district built from New York
open data runs a larger living society of its own and appears only in the development preview.

Which engine runs a society is data. The engine table
[`society-engines.v2.json`](../../exulanica/world/society-engines.v2.json) states what each engine
can do. A starter or a world made from photographs is given the purposeful engine,
`exulanica-society/v2`, and a generated town the living town, `exulanica-society/v5`; both let an
owner hand people to a model and a comparison run them. A world's capability read names the engine
([World API](world-api.md#discovering-what-a-world-supports)).
The server gives every world its own seed.

## What people do

The routine is data too
([`society-purposeful-activity.v2.json`](../../assets/catalogs/society/society-purposeful-activity.v2.json)):
people rest at benches, a planter seat or a cafe table, visit a market stall or a planter tree,
stand a while and stop to talk, walking to the places they use. What a person places changes where
they go ([world creation](world-creation.md)). In the application, People nearby brings them in,
the inhabitants panel can send everyone away and bring them back, and playback advances their
minutes. They keep bounded records of what they observed or were told; they do not learn
relationships.

Small birds live in a saved world too: every planter tree hosts three, which fly and perch on the
objects that declare perches. Their flight is computed in a worker process on a clock every viewer
shares, so everyone watching a world sees the birds in the same places, and it is derived from the
world version rather than stored. Walking, flight and roads are the three built
[movement modules](../movement-modules-contract.md).

## Choosing a model for a person or a group

In the world's Who decides panel (its rail action, or R), the world's owner chooses an open model
for one person or a group, up to eight people at once. With no choice, the routine decides. Each
model's card states its served description and how its served price compares with the cheapest model
offered beside it. A model is offered when its entry in the [model
manifest](../../exulanica/models/models.manifest.json) names a verified way it answers a choice.
`GET /world/versions/{version_id}/society/models` lists the offered models and whether this host can
ask each.

At each point where the routine would choose for a chosen person, the host asks their model through
the one hosted policy boundary, which applies the egress allowlist, the budget and the person's
rights. The model sees the person's situation and options and answers with one of the actions the
decision contract offers: go somewhere, wait, stand or talk. The engine checks every answer again
before applying it; a refused answer, like a turn the model leaves unanswered, is decided by the
routine. Every request and receipt is stored, so a run replays exactly without calling a model.

How a model decides, for the person and for a town's junction signal, is the
[decision roles contract](../decision-roles-contract.md). The person's own rules, the routes and the
refusals are in the society contract's section
[a person run by a model their world's owner chose](../synthetic-society-contract.md#a-person-run-by-a-model-their-worlds-owner-chose).

## Comparing models

A comparison runs the same simulated hour of a saved world once per arm and scores each run from
what the engine recorded. An arm names who decides for one group of people: a model, their
routine, or waiting at every choice point. The routine and waiting anchor the score at 1 and 0, and
a control arm runs one model twice to bound what run-to-run variation alone produces. Everybody
outside the group keeps what their owner chose for them in every arm, so two arms differ only in
who decides for the group. Beside each arm's score, the comparison shows the share of turns its
model answered, refused or left to the routine.

The world's owner starts one from Compare in the World menu: the models, the group, the
seeds and a spending bound they state, beside the most the comparison could cost and what one like
it typically costs, after which the server plays it and the view shows its runs finishing. The same
comparison can be defined and run by a local command:

```bash
EXULANICA_BUDGET_USD=<bound> uv run python -m exulanica.orchestration.compare \
  --workspace <uuid> --world <world id> --version <uuid> --actor <uuid> \
  --model <provider>/<model id> --model <provider>/<model id> --control
```

The bound is required, and every ask of every run stays within it. `--group` or `--group-choice`
names the group; without either, the group is everybody. The command runs development seeds, and
its comparisons are never judged: a judged comparison is pre-registered on held-out seeds and
recorded under `docs/evaluation/`. In the application, Compare in the World menu shows a
comparison's verdict and numbers, and one seed's hour from above on each side. A server starts
comparisons only for the workspaces it asks models for and only where something plays them
(`EXULANICA_COMPARISON_WORKER`, [running a comparison](../society-experiments.md#running-a-comparison)),
on the development seeds the seed catalog commits, with no file of seeds.

Two judged comparisons found no measured difference in how people fared between Qwen3 235B
Instruct and Nemotron 3.5 Lightning, first deciding for all eight people of the small square
([record](../evaluation/2026-09-26-society-model-comparison.json)) and then for a group of four
([record](../evaluation/2026-09-26-society-group-comparison.json)). In the second, the group still spent its time visibly differently:
mostly resting under Qwen3 235B Instruct, and resting less while standing and talking more under
Nemotron 3.5 Lightning. The [society experiments](../society-experiments.md) contract owns the comparison
rules, the score and these results.

## Experiments

A society experiment runs paired scenarios with one supported intervention and keeps the raw
outcomes, a control and replay ([society experiments](../society-experiments.md)).

## Reading it from another program

A society, its events and replay, the owner's model choices, each stored decision and each
comparison can be read through the authenticated API; the
[World API guide](world-api.md#people-and-models) lists the routes. The
[developer client](developer-client.md#reading-a-comparison-of-models) has read a comparison
started from the application, its runs and their stored decisions with `world.read` alone
([record](../evaluation/2026-09-29-developer-client-comparison.json)).

## What is not built

- Model roles beyond a person and a junction signal. Vehicles, animals, weather and an economy are
  not run by models: the birds follow their flight module and a town's vehicles follow the roads
  module. A signal whose owner chose a model may extend its green one second at a time, with fixed
  timing deciding whenever the model does not; no evaluation record measures whether that helps
  traffic, and no improvement or ranking is claimed.
- A model choice in the owned district's living society, whose engine takes none.
- Relationships that evolve and shape later choices, and world rules a person configures.
- A retraining loop: runs are not exported for training.

The society is a deterministic simulation with bounded model choices, not a prediction of what real
people would do. The [first milestone](../product-direction.md#first-milestone) and the
[milestones after it](../product-direction.md#subsequent-milestones) state the delivery order.

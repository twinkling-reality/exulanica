# World API

A program reads and changes a world through the same authenticated routes the application uses:
its versions and objects, its people, its traffic signals and the models that decide for them. It
can ask the server which operations a world supports and which are available to it now, with the
reason for any that are not. Edits carry the version state they were made against and pass the same
permission and acceptance rules as changes made in the application.

## Routes

Every route requires `Authorization: Bearer <token>`, and a token is bound to one workspace. A
workspace can hold several worlds and the server has no default one, so every route that reads or
changes a world's content also requires the world as a `world_id` query parameter. An id the
workspace does not hold answers `404 unknown_reference`, the same answer another workspace's world
gets. The reviewed asset and behaviour registries are the same for every world and take none.

The tables below cover world state and a world's people. Appearance styles and interaction policy
(`/world/styles`, `/world/interactions`), compositions, environment instances, character appearance
and world generation are routes of their own contracts, listed with every other route in
[the pinned surface](#the-pinned-surface).

### World state

| Method and path | Responsibility |
| --- | --- |
| `GET /worlds` | The worlds the workspace holds, each with its kind, and how many of each it may hold |
| `GET /worlds/capabilities` | For each kind of world: how many the workspace holds, the count policy's limit, what the kind supports, and whether making one is available to this caller now ([discovery](#discovering-what-a-world-supports)) |
| `GET /worlds/personal-source` | Whether the account holder's reviewed photographs can make or update the personal-source world now, or be added to the made world's places with a preview, or the named refusal; writes nothing |
| `POST /worlds/personal-source` | Compose the selection that read showed, by its `topology_digest`, or add the photographs its confirmed preview showed, by its `preview_sha256`, and return the world's `world_id` |
| `GET /world-read/scenes/{scene_id}` | Read an authorized scene bundle, placed in the regions of the named world |
| `GET /world-read/places/{place_id}` | Read a place in the named world, optionally resolved at a requested time |
| `POST /world-write/scenes/{scene_id}/generated` | Record a generated-scene receipt tied to its conditioning sources |
| `GET /world/versions` | Every alternate world version in the workspace, newest first |
| `POST /world/versions` | Create an alternate version from a structural snapshot or another version |
| `GET /world/versions/{version_id}` | One version with its objects, overrides, edit history and `state_sha256` |
| `GET /world/versions/{version_id}/capabilities` | The version's kind, the regions an edit may place into, its society, and each operation it supports with its state ([discovery](#discovering-what-a-world-supports)) |
| `POST /world/versions/{version_id}/objects` | Add one authored object from the reviewed registry |
| `POST /world/versions/{version_id}/objects/{object_id}/move` | Replace one object's region-local transform |
| `POST /world/versions/{version_id}/objects/{object_id}/remove` | Store a removal |
| `POST /world/versions/{version_id}/objects/{object_id}/behaviour` | Give one object a reviewed behaviour, replace it, or take it away |
| `POST /world/versions/{version_id}/objects/undo` | Reverse the newest edit not already reversed |
| `POST /world/versions/{version_id}/arrangements/preview` | Where an arrangement's objects, such as the small square's, would stand; writes nothing |
| `POST /world/versions/{version_id}/arrangements/apply` | Add exactly the resolved objects as ordinary edits, or refuse with the reason |
| `GET /world/arrangements` | The published arrangements, each with the key and version a preview or apply names it by |
| `GET /world/assets` | The reviewed asset registry, with whether each asset's bytes are present |
| `GET /workspace-assets` | The workspace's own admitted assets, what may be admitted, and the operations on each with their state ([workspace asset admission](../workspace-asset-admission.md)) |
| `POST /workspace-assets` | Admit one static GLB the person declares the rights to; it is prepared before it may be placed |
| `GET /world/assets/{asset_key}/bytes` | The reviewed GLB bytes |
| `GET /world/behaviours` | The reviewed behaviours an object may be given, with each parameter's bounds |
| `GET /world-entries` | The workspace's saved worlds, each naming the version and state it reopens at |
| `GET /world/source-media` | Protected topology source slots, including their region ids |

The personal-source pair takes no `world_id`: the server chooses the photographs and the world,
and the write returns the `world_id` every later route is given. It needs `admission.read` beside
`world.read` or `world.write`, because it reads the review state of each photograph. Its rule and
refusals are in [saved-world-entry.md](../saved-world-entry.md#which-photographs-a-personal-source-world-is-composed-from).

The `/world-read` routes need `library.read`. World Write records provenance; it does not deliver
generated assets or execute behavior. The `/world/versions` routes are the object-editing surface,
and their full contract, including every problem code, is
[world-objects-contract.md](../world-objects-contract.md) sections 5 to 7.

### People and models

These routes read and drive a world's society, the people described in the
[people and models guide](simulation.md), a town's traffic and the models that decide for its
people and its signals, and take `world_id` like the routes above. A step and a directed action name
the tick and state digest they were made against, and a stale base is refused.

| Method and path | Responsibility |
| --- | --- |
| `POST /world/versions/{version_id}/society` | Bring a society into a saved version |
| `GET /world/versions/{version_id}/society` | Its state, with the places its people can go |
| `GET /world/versions/{version_id}/society/events` | Its recorded events, newest first, in pages: `limit` (at most 256) and `before`, the `next` cursor the previous page answered with, `null` when no older event is left |
| `GET /world/versions/{version_id}/society/inputs/{input_seq}` | One stored input's identity and the authored state it was composed after (`authored_state`: the version's `edit_seq` and state digest), never the input itself |
| `GET /world/versions/{version_id}/society/replay` | Its history replayed from stored records, calling no model |
| `GET`, `PUT /world/versions/{version_id}/society/control` | Playback: play or pause at 1x, 2x or 4x speed |
| `POST /world/versions/{version_id}/society/control/steps` | Advance a paused society by one step |
| `POST /world/versions/{version_id}/society/presence` | One recorded minute in which everyone leaves, or the same people arrive again |
| `POST /world/versions/{version_id}/society/actions` | Direct one person to go somewhere or use a place |
| `GET /world/versions/{version_id}/models` | Every registered decision role (a person, a junction signal): its subjects, offered models, choices and host refusal, with the same declared semantics on each role |
| `POST /world/versions/{version_id}/models/{role_key}` | Choose a model for some subjects of one role, or none; needs `model.invoke` beside `world.write` |
| `GET /world/versions/{version_id}/society/models` | The offered models, each person's choice and each model's decisions |
| `POST /world/versions/{version_id}/society/models` | Choose a model for some people, or their routine, as the route above does for the person role; needs `model.invoke` beside `world.write` |
| `GET /world/versions/{version_id}/traffic` | A town's vehicles, second by second, from the roads its own records state |
| `GET /world/versions/{version_id}/society/decisions/{request_id}` | One stored decision: what the model was asked and what it answered |
| `GET /world/versions/{version_id}/society/comparisons` | The comparisons of models run on this version, with the start and progress of one started from the application |
| `GET /world/versions/{version_id}/society/comparisons/plan` | What a comparison of this version may be given, and for a selection its runs, the most it can cost and what one like it typically costs |
| `POST /world/versions/{version_id}/society/comparisons` | Start a comparison within a stated bound; requires `world.write` and `model.invoke` |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}` | One comparison: its arms, scores and verdict |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}` | One run of one arm on one seed |
| `GET /world/versions/{version_id}/flight` | The birds a saved version's objects host, as steps of their flight |
| `GET`, `PUT /world/versions/{version_id}/clock` | Which timeline the version's people, traffic and birds run on and where it stands; couple them, once, to the people's minutes ([world clock](../world-clock-contract.md)) |
| `GET /world/versions/{version_id}/clock/events` | The clock's receipts, newest first |
| `GET /world/versions/{version_id}/clock/verify` | Replay a coupled version's minutes from what was stored and check them, calling no model |

In a coupled version a step may answer `409 clock_lead_exhausted` while its traffic catches up,
and a step or a playback change may pin the clock's revision (`base_clock_revision`).

A comparison started here is played by the server off the request, within the bound its owner
stated; a local command defines and runs one the same way
([running a comparison](../society-experiments.md#running-a-comparison)).
`POST .../society/decisions` refuses every request by name, because explicitly requested model
proposals are retired. The full contract, including every refusal, is the
[society contract](../synthetic-society-contract.md); paired experiments with an intervention are
[society experiments](../society-experiments.md).

### Projects

The `/world/projects` routes keep what a person chose to keep about their work in a world: a project
bound to one of the world's versions, its goals, preferences, open questions, tasks, decisions naming
accepted edits and simulated events, their corrections, what the owner shares, and a bounded context
assembled from them. They take `world_id`, read with `world.read`, write with `world.write` and
delete with `deletion.write`; every write names the project revision it read. The contract, with
every route and refusal, is [world project context](../project-context.md), and
`python -m exulanica_client.project_context` is a two-process example of keeping a project and
resuming it from another client.

### The pinned surface

The whole surface, every route with its permission rule and every schema, is pinned in
`tests/snapshots/api-routes.json` and `tests/snapshots/api-openapi.json`; a change to either reaches
review as a diff, as the [developer client guide](developer-client.md#the-contract-it-is-written-against)
describes.

## Discovering what a world supports

Three reads say what a caller can do, each from the checks the operations themselves make:
`GET /worlds/capabilities` for making each kind of world,
`GET /world/versions/{version_id}/capabilities` for one version of one world, and
`GET /workspace-assets` for admitting a person's own asset and for each admitted asset's
preparation, cancellation and withdrawal
([workspace asset admission](../workspace-asset-admission.md#capabilities)). None writes or asks a
model. All describe each operation with the same descriptor:

| Field | Meaning |
| --- | --- |
| `operation` | The route that performs it, `"METHOD /path"`, the key the pinned surface uses |
| `bind` | The path values of this subject; `world_id` is the read's own |
| `requires`, `permitted` | The permissions the route declares, and whether this caller's grant holds them all |
| `state`, `code` | `available`: the server would attempt it; `unavailable`: supported, but a dependency or state prevents it now; `unsupported`: this kind, engine or role never supports it; `unknown`: deciding it needs a fact this caller may not read. Every state but `available` carries the stable code the operation answers with |
| `subject`, `subjects` | What it acts on, and the read and field that list those subjects |
| `input`, `output` | The OpenAPI schemas of its body and answer |
| `base` | Each stale-base token its body carries, with the read and field that give the current value |
| `idempotency` | The body field that makes a retry answer with the first result |
| `preview` | The operation that shows the effect without writing, and whether the write needs it |
| `options` | The reads that list its choices, such as `GET /world/assets` or `GET /world/arrangements` |
| `writes`, `spends` | Whether success records state, and whether it may call a model or commit the world to one |
| `effects` | A later consequence this server may not produce: whether the world's people use what was placed (`society`), whether this host asks a chosen model (`decisions`), whether the world advances on its own once played (`playback`), whether an admitted asset is prepared on this installation (`preparation`) |
| `dependencies` | The installation's components the operation needs that are not configured or ready, each with the installation's state and reason (`component`, `state`, `code`) |

Availability is not permission: an operation can be available and not permitted to this caller.

Where the serving process was composed with an installation, each read also reads the
installation's facts once ([installation profiles and facts](../deployment.md#91-installation-profiles-and-facts))
and states them:
- While the installation refuses to serve because a restore is not complete, every write is
  `unavailable` by the installation's reason (`restore_pending` or `restore_state_unknown`).
- Otherwise an operation keeps its own refusal. One its own checks allow is `unavailable` by the
  first component it needs that the installation does not install, cannot run or refuses: by the
  installation's reason, or `<component>_not_installed` where it gives none.
- A comparison's start needs `comparison`. A preparation request, of a workspace asset or of a
  character's body, needs `preparation`, and the `preparation` effect takes that component's state.
  The routes themselves do not read the installation: one the read calls unavailable for a
  component may still accept a request, which waits until the installation runs that component.
- `dependencies` lists each component an operation needs that is not configured or ready. A
  `degraded` one is listed and changes nothing.
- A process without an installation profile cannot see other processes. It lists such a component
  as `not_installed` with `undeclared_installation`, which changes nothing, and states the
  `preparation` effect `unknown`. A process composed with no installation lists no dependency.
Units are part of field names across the API (`_mm`, `_ms`, `_seconds`, `_usd`, `_microradians`,
`_milli`), and bounds are the OpenAPI schema's or the domain read's; a descriptor restates neither.
Where an operation answers a family code with the reason in `detail` (`409 arrangement_refused`,
`409 composition_blocked`), the descriptor's `code` is that reason.

A version's read also states:

- `kind` and `kind_facts`: the world's kind and what the kind supports (`takes_photographs`,
  `draws_generated_tiles`, `source_independent`).
- `regions`: the regions an edit may place into, from the one check every placement makes. A
  region in the list is accepted by `POST .../objects`; any other is refused
  `422 invalid_object_data`. An invalidated source lists none, as `unavailable`.
- `society`: whether the version holds a society, and its engine, or the engine the engine table
  creates for this world's ground: `exulanica-society/v2` for a starter or a world from photographs,
  `exulanica-society/v5` for a generated town. A society creation names its engine, so a client
  sends the one named here.

What differs by kind, as the reads state it:

| Kind | Regions | Arrangements | Placed objects used by people | Society engine | Directed actions and presence | Traffic |
| --- | --- | --- | --- | --- | --- | --- |
| Authored starter | `region:starter` | available | yes, by reach | v2 | available once a society is brought | `roads_not_stated` |
| Generated town | its one generated region | `unsupported`, `arrangement_needs_authored_ground` | no, `authored_affordance_unreachable` | v5 | `unsupported` (`engine_takes_no_directed_actions`, `engine_keeps_its_people`) | available |
| From photographs | one per place | available; a world of several places names the viewer's region | yes, by reach | v2 | available once a society is brought | `roads_not_stated` |

Making worlds: a starter is refused `saved_world_conflict` once the workspace holds any saved world,
although the count policy sets no starter limit, and the read says so. A generated world is refused
`world_limit_reached` at the policy's limit. A world from photographs takes the state and code of the
`GET /worlds/personal-source` plan, which needs `admission.read`; without it the state is `unknown`.

Choosing a model for a role (`POST /world/versions/{version_id}/models/{role_key}`) answers a refused
choice with the status the person's own route gives the same code: 409 for `choice_key_reused`,
`engine_takes_no_model_choice` and `roads_unavailable`, 503 when this server cannot take a choice
now (`traffic_controller_unavailable`, `traffic_worker_unavailable`), and 422 for a body naming
something the world does not offer. A model the manifest does not hold is refused
`model_not_declared` for a person and `model_not_offered` for a signal, each role's own code. A
choice is recorded even when this host asks no model; the choice's `decisions` effect says so. A
registered role whose subject this server has no host for is listed as `unsupported` with
`role_subject_unsupported`, and a choice of it is refused by that code.

Where a durable spending authority admits this server's calls, the reads also state the workspace's
allowance, as admission would answer its next attempt. An ask reaches its chosen model's provider
alone, so a role is refused once the allowance of every provider its models are served by is spent.
A model choice's `decisions` effect is then `unavailable` by the authority's reason
(`spending_not_granted`, `spending_revoked`, `spending_expired`, `spending_suspended` or
`spending_limit_reached`), after this process's own refusal, which a call meets first. A comparison's
start is `unavailable` by the same reason, and a start that would ask a spent provider is refused 429
`budget_exceeded` with the authority's `spending` member
([model spending](../model-spending-contract.md#11-what-a-client-sees)). A cancel reads no allowance.

A society's events name the input they were played under (`document.input_seq`). The input's
provenance read gives the authored `edit_seq` it followed and the version's state digest after that
edit (`delta_sha256`), which is the `result_state_sha256` of that edit in the version's history, so
an event joins to the edit, and the object, it followed.

## Making an edit from another tool

Every mutation names the version state it was made against. Read the version, take its
`state_sha256`, and send it as `base_state_sha256`. The answer is the whole version with its new
`state_sha256`, which is the base for the next edit. If another writer changed the version first,
the edit is refused with `409 stale_object_base` and nothing changes. Read the version again,
decide whether the edit still makes sense against what is there now, and only then re-issue it
against the new token. Re-sending the same body with a fresh token without looking is the lost
update the check exists to prevent.

The [developer client](developer-client.md) in `clients/python` is a complete second client
written against the standard library only. With a token granted `world.read` and `world.write`, it
reads the person's saved world, discovers the edits, behaviours and assets the server supports,
places a reviewed object and gives it motion, has a behaviour the registry does not list refused
with the server's reason, and confirms every fact on a fresh read.

`scripts/world_client_example.py` is a second client that shows the stale-base path: it
reads a named version and its objects, adds one reviewed asset, moves it, handles a stale-base
refusal by re-reading and reconciling, and prints what changed. It uses the standard library and
httpx and imports nothing from this repository.

```bash
EXULANICA_TOKEN=<token> uv run python scripts/world_client_example.py --base-url http://127.0.0.1:8000 --title "Evening study" --origin-role fictional --demonstrate-stale-base
```

`--origin-role` is required because the person chooses whether an authored object is fictional or
personal; the server never infers it. `--demonstrate-stale-base` presents the pre-add token for the
move on purpose, so the refusal and the re-read are shown rather than asserted.

## Gaps a second tool meets

- A workspace with no saved world has no version to edit until one is made.
  `POST /world-entries/starter` creates the authored starter world and its version, which is how
  [the recorded developer-client run](../evaluation/2026-09-23-developer-client.json) began in an
  empty synthetic workspace. Otherwise a version is created from an existing structural snapshot or
  from another version.
- The regions an edit may place into are in the version's capability read, for every kind of world.
- Environment instances and photo point maps place admitted resources that no read lists for a
  world; their descriptors name no options. Styles and interaction policy are world-scoped and are
  not in the version's capability read; their own reads state what they offer.

## Carrying a version elsewhere

A World Memory Package projected with `--extension authored-world-1.0` or `authored-world-1.1`
carries alternate versions, their objects with asset digests and origins, and behaviour identifiers
with parameters, without asset bytes; 1.1 also carries the versions whose chains give, change or
take away an object's behaviour, which 1.0 withholds. `--extension environment-instances-1.0` (or
`-1.1`) carries environment-inclusive authored state for versions that have environment instances or
environment edits, the schema-v1 ancestors those parent pointers require, and schema-v1 descendants
that cannot live in authored-world 1.0 because an ancestor is environment-bearing. A loader that
lacks that capability must omit those versions rather than treat authored-world 1.0 objects as the
whole authored state. `exulanica-wmp import-check` compares a receiving loader's declared
capabilities with what the package needs and names what it cannot load; see
[world-memory-package.md](../world-memory-package.md#authored-world-extension-10) and
[environment-instances 1.0](../world-memory-package.md#environment-instances-extension-10).
No extension carries a society, its events or its decisions.

Definitions: [World Read](../../exulanica/api/routes/world_read.py),
[World Write](../../exulanica/api/routes/world_write.py),
[world versions](../../exulanica/api/routes/world_versions.py),
[authored objects](../../exulanica/api/routes/world_objects.py),
[arrangements](../../exulanica/api/routes/world_arrangements.py),
[reviewed assets](../../exulanica/api/routes/world_assets.py) and
[reviewed behaviours](../../exulanica/api/routes/world_behaviours.py), with the shared edit bodies
and problem codes in [world_edit.py](../../exulanica/api/world_edit.py); the
[capability reads](../../exulanica/api/routes/capabilities.py) and their
[descriptor](../../exulanica/api/capabilities.py); the
[decision roles](../../exulanica/api/routes/world_models.py) and the
[host of each role](../../exulanica/api/role_hosts.py);
[traffic](../../exulanica/api/routes/world_traffic.py); the
[society](../../exulanica/api/routes/society.py),
[playback control](../../exulanica/api/routes/society_control.py),
[directed actions](../../exulanica/api/routes/society_actions.py),
[model choice](../../exulanica/api/routes/society_models.py),
[comparisons](../../exulanica/api/routes/society_comparisons.py) and
[flight](../../exulanica/api/routes/world_flight.py) routes.
See [development setup](../development-setup.md) for authentication and server configuration.

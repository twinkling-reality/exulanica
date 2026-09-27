# World API

A program reads and changes a world through the same authenticated routes the application uses:
its versions and objects, its people and the models that decide for them. Edits carry the version
state they were made against and pass the same permission and acceptance rules as changes made in
the application.

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
| `GET /worlds/personal-source` | Whether the account holder's reviewed photographs can make or update the personal-source world now, or be added to the made world's places with a preview, or the named refusal; writes nothing |
| `POST /worlds/personal-source` | Compose the selection that read showed, by its `topology_digest`, or add the photographs its confirmed preview showed, by its `preview_sha256`, and return the world's `world_id` |
| `GET /world-read/scenes/{scene_id}` | Read an authorized scene bundle, placed in the regions of the named world |
| `GET /world-read/places/{place_id}` | Read a place in the named world, optionally resolved at a requested time |
| `POST /world-write/scenes/{scene_id}/generated` | Record a generated-scene receipt tied to its conditioning sources |
| `GET /world/versions` | Every alternate world version in the workspace, newest first |
| `POST /world/versions` | Create an alternate version from a structural snapshot or another version |
| `GET /world/versions/{version_id}` | One version with its objects, overrides, edit history and `state_sha256` |
| `POST /world/versions/{version_id}/objects` | Add one authored object from the reviewed registry |
| `POST /world/versions/{version_id}/objects/{object_id}/move` | Replace one object's region-local transform |
| `POST /world/versions/{version_id}/objects/{object_id}/remove` | Store a removal |
| `POST /world/versions/{version_id}/objects/{object_id}/behaviour` | Give one object a reviewed behaviour, replace it, or take it away |
| `POST /world/versions/{version_id}/objects/undo` | Reverse the newest edit not already reversed |
| `POST /world/versions/{version_id}/arrangements/preview` | Where an arrangement's objects, such as the small square's, would stand; writes nothing |
| `POST /world/versions/{version_id}/arrangements/apply` | Add exactly the resolved objects as ordinary edits, or refuse with the reason |
| `GET /world/assets` | The reviewed asset registry, with whether each asset's bytes are present |
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
[people and models guide](simulation.md), and take `world_id` like the routes above. A step and a
directed action name the tick and state digest they were made against, and a stale base is refused.

| Method and path | Responsibility |
| --- | --- |
| `POST /world/versions/{version_id}/society` | Bring a society into a saved version |
| `GET /world/versions/{version_id}/society` | Its state, with the places its people can go |
| `GET /world/versions/{version_id}/society/events` | Its recorded events |
| `GET /world/versions/{version_id}/society/replay` | Its history replayed from stored records, calling no model |
| `GET`, `PUT /world/versions/{version_id}/society/control` | Playback: play or pause at 1x, 2x or 4x speed |
| `POST /world/versions/{version_id}/society/control/steps` | Advance a paused society by one step |
| `POST /world/versions/{version_id}/society/presence` | One recorded minute in which everyone leaves, or the same people arrive again |
| `POST /world/versions/{version_id}/society/actions` | Direct one person to go somewhere or use a place |
| `GET /world/versions/{version_id}/society/models` | The offered models, each person's choice and each model's decisions |
| `POST /world/versions/{version_id}/society/models` | Choose a model for some people, or their routine; needs `model.invoke` beside `world.write` |
| `GET /world/versions/{version_id}/society/decisions/{request_id}` | One stored decision: what the model was asked and what it answered |
| `GET /world/versions/{version_id}/society/comparisons` | The comparisons of models run on this version |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}` | One comparison: its arms, scores and verdict |
| `GET /world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}` | One run of one arm on one seed |
| `GET /world/versions/{version_id}/flight` | The birds a saved version's objects host, as steps of their flight |

Comparisons are read-only here: a comparison is defined and run by a local command
([comparing models](simulation.md#comparing-models)). `POST .../society/decisions` refuses every
request by name, because explicitly requested model proposals are retired. The full contract,
including every refusal, is the [society contract](../synthetic-society-contract.md); paired
experiments with an intervention are [society experiments](../society-experiments.md).

### The pinned surface

The whole surface, every route with its permission rule and every schema, is pinned in
`tests/snapshots/api-routes.json` and `tests/snapshots/api-openapi.json`; a change to either reaches
review as a diff, as the [developer client guide](developer-client.md#the-contract-it-is-written-against)
describes.

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
- No route lists a source snapshot's regions. An authored starter world names its region in the
  saved world's `authored_scene`; otherwise a client learns a region id from an object that already
  uses one, or from `GET /world/source-media`. The server refuses a region its source lacks.
- No route starts a comparison of models. A program reads the comparisons a local command ran, and
  no recorded run of a client other than the browser has read one.

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
[society](../../exulanica/api/routes/society.py),
[playback control](../../exulanica/api/routes/society_control.py),
[directed actions](../../exulanica/api/routes/society_actions.py),
[model choice](../../exulanica/api/routes/society_models.py),
[comparisons](../../exulanica/api/routes/society_comparisons.py) and
[flight](../../exulanica/api/routes/world_flight.py) routes.
See [development setup](../development-setup.md) for authentication and server configuration.

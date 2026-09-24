# World API

Connect tools to personal world state through authenticated read and write interfaces.

The platform design allows creation tools to read a named world version and submit supported
changes. Edits carry their source version and pass the same permission and acceptance rules as
changes from the interface.

## Routes

Every route requires `Authorization: Bearer <token>`, and a token is bound to one workspace. A
workspace can hold several worlds and the server has no default one, so every route that reads or
changes a world's content also requires the world as a `world_id` query parameter. An id the
workspace does not hold answers `404 unknown_reference`, the same answer another workspace's world
gets. The reviewed asset and behaviour registries are the same for every world and take none.

| Method and path | Responsibility |
| --- | --- |
| `GET /worlds` | The worlds the workspace holds, each with its kind, and how many of each it may hold |
| `GET /worlds/personal-source` | Whether the account holder's reviewed photographs can make or update the personal-source world now, or the named refusal |
| `POST /worlds/personal-source` | Compose the selection that read showed, by its `topology_digest`, and return the world's `world_id` |
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
| `GET /world/assets` | The reviewed asset registry, with whether each asset's bytes are present |
| `GET /world/assets/{asset_key}/bytes` | The reviewed GLB bytes |
| `GET /world/behaviours` | The reviewed behaviours an object may be given, with each parameter's bounds |
| `GET /world-entries` | The workspace's saved worlds, each naming the version and state it reopens at |
| `GET /world/source-media` | Protected topology source slots, including their region ids |

The personal-source pair takes no `world_id`: the server chooses the photographs and the world,
and the write returns the `world_id` every later route is given. It needs `admission.read` beside
`world.read` or `world.write`, because it reads the review state of each photograph. Its rule and
refusals are in [saved-world-entry.md](../saved-world-entry.md#which-photographs-a-personal-source-world-is-composed-from).

World Write records provenance; it does not deliver generated assets or execute behavior. The
`/world/versions` routes are the object-editing surface, and their full contract, including every
problem code, is [world-objects-contract.md](../world-objects-contract.md) sections 5 to 7.

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

Its run against the reference copy, with the wire transcript, is retained in the developer-proof
record (`2026-09-11-developer-proof`), a local-only evaluation record a clone does not contain.

## Gaps a second tool meets

- A workspace with no saved world has no version to edit until one is made.
  `POST /world-entries/starter` creates the authored starter world and its version, which is how
  [the recorded developer-client run](../evaluation/2026-09-23-developer-client.json) began in an
  empty synthetic workspace. Otherwise a version is created from an existing structural snapshot or
  from another version.
- No route lists a source snapshot's regions. An authored starter world names its region in the
  saved world's `authored_scene`; otherwise a client learns a region id from an object that already
  uses one, or from `GET /world/source-media`. The server refuses a region its source lacks.

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

Definitions: [World Read](../../exulanica/api/routes/world_read.py),
[World Write](../../exulanica/api/routes/world_write.py),
[world versions](../../exulanica/api/routes/world_versions.py),
[authored objects](../../exulanica/api/routes/world_objects.py),
[reviewed assets](../../exulanica/api/routes/world_assets.py) and
[reviewed behaviours](../../exulanica/api/routes/world_behaviours.py), with the shared edit bodies
and problem codes in [world_edit.py](../../exulanica/api/world_edit.py).
See [development setup](../development-setup.md) for authentication and server configuration.

# World API

Connect tools to personal world state through authenticated read and write interfaces.

The platform design allows creation tools to read a named world version and submit supported
changes. Edits carry their source version and pass the same permission and acceptance rules as
changes from the interface.

## Current routes

Every route requires `Authorization: Bearer <token>`, and a token is bound to one workspace.

| Method and path | Current responsibility |
| --- | --- |
| `GET /world-read/scenes/{scene_id}` | Read an authorized scene bundle |
| `GET /world-read/places/{place_id}` | Read a place, optionally resolved at a requested time |
| `POST /world-write/scenes/{scene_id}/generated` | Record a generated-scene receipt tied to its conditioning sources |
| `GET /world/versions` | Every alternate world version in the workspace, newest first |
| `POST /world/versions` | Create an alternate version from a structural snapshot or another version |
| `GET /world/versions/{version_id}` | One version with its objects, overrides, edit history and `state_sha256` |
| `POST /world/versions/{version_id}/objects` | Add one authored object from the reviewed registry |
| `POST /world/versions/{version_id}/objects/{object_id}/move` | Replace one object's region-local transform |
| `POST /world/versions/{version_id}/objects/{object_id}/remove` | Store a removal |
| `POST /world/versions/{version_id}/objects/undo` | Reverse the newest edit not already reversed |
| `GET /world/assets` | The reviewed asset registry, with whether each asset's bytes are present |
| `GET /world/assets/{asset_key}/bytes` | The reviewed GLB bytes |
| `GET /world/source-media` | Protected topology source slots, including their region ids |

World Write records provenance; it does not deliver generated assets or execute behavior. The
`/world/versions` routes are the object-editing surface, and their full contract, including every
problem code, is [world-objects-contract.md](../world-objects-contract.md) sections 5 to 7.

## Making an edit from another tool

Every mutation names the version state it was made against. Read the version, take its
`state_sha256`, and send it as `base_state_sha256`. The answer is the whole version with its new
`state_sha256`, which is the base for the next edit. If another writer changed the version first,
the edit is refused with `409 stale_object_base` and nothing changes. Read the version again,
decide whether the edit still makes sense against what is there now, and only then re-issue it
against the new token. Re-sending the same body with a fresh token without looking is the lost
update the check exists to prevent.

`scripts/world_client_example.py` is a complete second client that does exactly this: it reads a
named version and its objects, adds one reviewed asset, moves it, handles a stale-base refusal by
re-reading and reconciling, and prints what changed. It uses the standard library and httpx and
imports nothing from this repository.

```bash
EXULANICA_TOKEN=<token> uv run python scripts/world_client_example.py --base-url http://127.0.0.1:8000 --title "Evening study" --origin-role fictional --demonstrate-stale-base
```

`--origin-role` is required because the person chooses whether an authored object is fictional or
personal; the server never infers it. `--demonstrate-stale-base` presents the pre-add token for the
move on purpose, so the refusal and the re-read are shown rather than asserted.

## Gaps a second tool meets today

- A version can be created only from an existing structural snapshot, and no route composes one.
  A workspace whose structural plane was never composed offers no version to edit.
- No route lists a source snapshot's regions. A client learns a region id from an object that
  already uses one, or from `GET /world/source-media`; the server refuses a region its source lacks.
- No route reads the behaviour registry. A client learns the one reviewed behaviour,
  `motion.bounded-path@1`, from the objects contract, and the server refuses anything outside it.

## Carrying a version elsewhere

A World Memory Package projected with `--extension authored-world-1.0` carries alternate versions,
their objects with asset digests and origins, and behaviour identifiers with parameters, without
asset bytes. `exulanica-wmp import-check` compares a receiving loader's declared capabilities with
what the package needs and names what it cannot load; see
[world-memory-package.md](../world-memory-package.md#authored-world-extension-10).

Definitions: [World Read](../../exulanica/api/routes/world_read.py),
[World Write](../../exulanica/api/routes/world_write.py) and
[world versions and assets](../../exulanica/api/routes/world.py).
See [development setup](../development-setup.md) for authentication and server configuration.

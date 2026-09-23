# Developer client

A program outside the application can use a person's world through the public API, with nothing
from the application's private state. [`clients/python`](../../clients/python) is a small client
that does it with the Python standard library alone: it reads the person's saved world, asks the
server which edits, behaviours and assets it supports, places a reviewed object, gives it bounded
motion, and checks every fact of the result on a fresh read.

It is written in Python without dependencies so that it runs anywhere Python does, with no install
step, and so that it shares no code or generated types with the browser application, which is
itself a TypeScript client of the same API. The independence is checked rather than assumed:
[`tests/test_developer_client.py`](../../tests/test_developer_client.py) runs it with
`python -S -s -E`, where no site-packages directory is importable.

## What it needs

| Need | Detail |
| --- | --- |
| Python | Tested on 3.11 (the test suite) and 3.14 (the recorded run), each with no site-packages |
| A token | A bearer token whose grant names `world.read` and `world.write` for the person's workspace, and nothing else |
| An address | The API's base URL: `https`, or plain `http` only for a loopback address |

A grant in `EXULANICA_API_TOKENS` for such a token, with the workspace and actor ids of the
deployment ([security-floor.md](../security-floor.md) describes grants):

```json
{"<token>": {"workspace_id": "<uuid>", "actor": "<uuid>", "permissions": ["world.read", "world.write"]}}
```

The client cannot read the library, upload photographs, change consent or delete anything,
because its token cannot: the server refuses those routes before they run.

## Running it

From `clients/python`, with the token in the environment. It is never printed or written.

```bash
EXULANICA_TOKEN=<token> python3 -m exulanica_client discover --base-url https://<api>
```

```bash
EXULANICA_TOKEN=<token> python3 -m exulanica_client walkthrough --base-url https://<api> \
  --origin-role fictional --place 0,0,0 --asset-key cc0.marker-cube --transcript walkthrough.json
```

| Option | Meaning |
| --- | --- |
| `--origin-role` | Required. Whether the object is `fictional` or `personal` is the person's choice; the server never infers it |
| `--place` | Required. Region-local `x,y,z` in whole millimetres |
| `--asset-key` | The reviewed asset to place. Needed when the server has more than one available |
| `--behaviour`, `--parameter` | `KEY@VERSION` and `NAME=VALUE`. The registry's declared defaults apply to any parameter not given; the behaviour is needed when the server reviews more than one |
| `--entry`, `--title` | The saved world, when the workspace has more than one |
| `--region`, `--object-id` | Defaults: the saved world's authored region, and a fresh id |
| `--transcript` | Write every exchange and every check as JSON |

The exit code is 0 when every check holds, 1 when the walkthrough stopped or a check failed, with
the server's reason, and 2 when no token is set.

## What the walkthrough does

| Step | Routes | What it establishes |
| --- | --- | --- |
| Discover | `GET /openapi.json`, `GET /world/behaviours`, `GET /world/assets` | The edits the server documents, its reviewed behaviours with their bounds, and the assets whose bytes it holds. It stops if placing an object or setting a behaviour is not among the edits |
| Read | `GET /world-entries`, `GET /world/versions/{version_id}` | The saved world and the version it opens at. It stops if the saved resume point is not the version's current state |
| Place | `POST /world/versions/{version_id}/objects` | One reviewed object, against the state just read, advancing the saved world with it |
| Motion | `POST /world/versions/{version_id}/objects/{object_id}/behaviour` | A reviewed behaviour with parameters inside the server's bounds |
| Refusal | the same route | A behaviour version the registry does not list, refused with the server's code and detail |
| Confirm | `GET /world/versions/{version_id}`, `GET /world-entries/{entry_id}` | Ten checks: the object, its asset, availability, transform, origin and motion; the refused request changed nothing; the newest edits are the client's; the saved world reopens at the result |

An edit of an authored version is recognised from the OpenAPI document rather than from a list in
the client: its request body carries `base_state_sha256` and its answer is the schema
`GET /world/versions/{version_id}` returns. Society routes also carry a `base_state_sha256`, of
the society's state, and answer with something else, so they are not counted
([`discovery.py`](../../clients/python/exulanica_client/discovery.py)).

## Using it as a library

```python
from exulanica_client import ApiRefusal, WorldClient

client = WorldClient("https://<api>", token)
world = client.saved_worlds()[0]
version = client.version(world["authored_version_id"], world_id=world["world_id"])
cube = next(asset for asset in client.assets() if asset["asset_key"] == "cc0.marker-cube")
try:
    placed = client.place_object(
        version,
        object_id="tool:lamp",
        asset_sha256=cube["content_sha256"],
        # An authored starter world names its region; a personal world's objects name theirs.
        region_id=world["authored_scene"]["region"]["region_id"],
        transform={"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1000},
        origin_role="fictional",
        saved_entry=world,
    )
except ApiRefusal as refused:
    print(refused.status, refused.code, refused.detail)
```

Every edit takes the version it was made against and answers with the whole new version, whose
`state_sha256` is the base for the next edit. Passing `saved_entry` advances the saved world in the
same transaction as the edit, as the application does, so the person's world reopens at it.
`ApiRefusal` carries the server's status, code and detail unaltered.

## The contract it is written against

The routes, their request and response shapes, statuses and permission rules are pinned in
[`tests/snapshots/api-routes.json`](../../tests/snapshots/api-routes.json), one line per route, and
[`tests/snapshots/api-openapi.json`](../../tests/snapshots/api-openapi.json), the document
`/openapi.json` serves. [`tests/test_api_surface_snapshot.py`](../../tests/test_api_surface_snapshot.py)
fails when the application differs from them, so a change to the surface a client depends on is
accepted only by rewriting them with `uv run python scripts/snapshot_api_surface.py`, and reaches
review as a diff.

## What it does not do

- It does not create saved worlds, versions or tokens. It edits the saved world the person has.
- It does not retry a refused edit. On a stale base (`409 stale_object_base`) it stops with the
  server's reason, because a blind retry is the lost update the base exists to prevent.
  [`scripts/world_client_example.py`](../../scripts/world_client_example.py) shows re-reading and
  reconciling instead.
- It does not start motion. It stores a behaviour; trigger, stop and reset are the renderer's
  controls ([world-objects-contract.md](../world-objects-contract.md#behaviours)).
- It follows no redirect and sends no token over plain `http` to another machine. urllib would
  copy the `Authorization` header to a redirect's target.

## Evidence

[`tests/test_developer_client.py`](../../tests/test_developer_client.py) serves the application
on a loopback socket, creates a saved world with the person's token, runs the walkthrough as a
separate process with a token granted only `world.read` and `world.write`, and checks the result
in the repository rather than in the client's own report.
[The recorded run](../evaluation/2026-09-23-developer-client.json) did the same against the
acceptance runtime with a synthetic workspace, and binds the transcript and the application's view
of the saved world afterwards, with the object drawn where the client placed it.

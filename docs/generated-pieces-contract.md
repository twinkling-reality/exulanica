# Generated pieces

This contract owns asking for generated pieces: new pieces of a world's look, made by open models
on a GPU, for thing kinds a person's world holds. It covers what a request is built from, what it
holds, what it will cost and how long it will take, the routes, the limits, and what a workspace
deletion does to its requests. How a piece is generated, post-processed and checked belongs to
[generated appearance](generated-appearance.md); the piece format and its budgets belong to the
[style pack contract](style-pack-contract.md); the allowance a request spends belongs to the
[model spending contract](model-spending-contract.md).

| Part | Status |
| --- | --- |
| Requests built from catalogs, their estimate, their store and routes, the workspace's limits | Implemented |
| The cost and timing figures, from two measured sessions on Nebius AI Cloud | Implemented |
| A generation session the operator starts, its queue, outputs, stored pieces and their purge | Planned |
| Admitting, dispatching and settling a request's GPU time under the spending authority | Planned |
| Passed pieces taken into the world's look as they arrive, each taken back on request | Planned |
| The page's waiting line and per-thing list, and the Companion's offer of new pieces | Planned |
| A person's own words for a piece | Not built |

## 1. What a person gets

A world opens with its look's ready-made pieces, and asking for generated pieces adds nothing to
that wait. A request for a thing kind's pieces is made once and shared: the same kind, in the same
look version, asked by any workspace, is the same request. While a request waits, the world keeps
its ready-made piece; a generated piece that passes every check takes its place as it arrives, and
asking is the consent to that. A piece that fails a check never appears.

On a running session a piece takes about 8 seconds, so the first version of every asked kind comes
first, each kind's other variants after; a session that is not running adds its start, about 11
minutes. Section 6 gives the figures and their records.

## 2. What a request is built from

An ask names a world, a committed look the pieces are made in (a style pack version this server
serves: its id, version and manifest digest) and 1 to 16 shipped thing kind versions. Taking passed
pieces into the world's own look, and so which look that is, belongs to the planned step that
applies them. Each kind becomes one request
(`exulanica.generated-asset-request/v2`), built by `exulanica.generation.requests.plan_requests`
from:

- the kind's own document, through `exulanica_pieces.recipes.recipe_for_kind` and the newest
  version of the [piece recipe catalog](../assets/catalogs/generation/piece-recipes.v2.json): the
  kind's box as the slot, its look role (`fixture.<kind>`, or `prop.<kind>` for a thing a hand
  holds), its grip and axis, and a measured description, variant count or fill bar where the
  catalog holds one;
- the widest section a hand closes around, the narrowest any body plan states;
- the look's palette (its manifest's swatches) and the style words the
  [piece style catalog](../assets/catalogs/generation/piece-styles.v1.json) states for its pack (a
  pack with no entry has no generated pieces);
- the [piece budgets](../assets/style-packs/piece-budgets.v1.json) the style pack format reads.

The words a request carries come from catalogs alone, so a request holds no text a person typed and
is catalog content (`cache_scope` `catalog`). An ask is refused whole when any kind cannot have a
piece: a kind with no box of its own (a person, a creature), an unknown kind version, a look this
server does not serve at that digest, or a pack with no style words.

## 3. What a request holds

A request (table `piece_request`) holds who asked, the world it is for, the kind version and its
digest, the look version and its digest, the look role, the variant count, the request document as
canonical JSON with its digest, its worst case in US dollars, and its state with the instants it
moved, dated when it is asked whatever its writer states. A request starts `requested`, is
`queued` when a session's queue takes it, and ends `made`, `refused` (every variant failed a check),
`failed` or `cancelled`. What was asked never changes, and a finished request never changes. Before
anything is written the store holds each request to the catalogs and to its row: its words are the
catalogs', its thing kind is the shipped kind its row names, and its pack is the look the ask names.

An ask under a caller's key is recorded (table `piece_ask`) with every request it answered with,
made then or already waiting, so the same key answers the same requests, and a key whose ask made
none is still bound to it. Every ask takes the workspace's lock first, so an ask and the
workspace's deletion never interleave (section 8). Both tables are under forced row-level security
keyed on the workspace.

## 4. Routes and refusals

| Route | What it does |
| --- | --- |
| `POST /world/piece-requests` | Asks for a world's pieces of some thing kinds. `202` with the requests, their estimate and whether a session is running; `200` with the requests the first answer held when an idempotency key names an earlier ask (answered before the allowance is weighed again), or when every piece asked is already waiting for this world. |
| `GET /world/piece-requests?world_id=` | A world's requests, newest first. |
| `GET /world/piece-requests/{piece_request_id}` | One request and where it stands. |
| `DELETE /world/piece-requests/{piece_request_id}` | Cancels a request no session has taken. |

Asking needs `world.write` and `model.invoke`; reading needs `world.read`; cancelling needs
`world.write`. Refusals use the API's problem shape:

| Status | Code | When |
| --- | --- | --- |
| 422 | `kind_unknown`, `kind_without_piece`, `kind_repeated`, `too_many_kinds`, `look_not_served`, `look_without_style_words` | The ask cannot be built (section 2). |
| 404 | `unknown_world`, `unknown_piece_request` | No such world or request in this workspace. |
| 409 | `generation_session_off` | A guest asks while no session is running. |
| 409 | `idempotency_key_reused` | The key names an earlier ask with another body. |
| 409 | `piece_request_not_cancellable` | The request was taken or has ended; the body states its state. |
| 410 | `tombstoned` | The workspace has been deleted. |
| 429 | `budget_exceeded` | Admission would refuse the workspace's next `nebius_ai_cloud_gpu` attempt, or its allowance, less what its open requests can still cost, cannot cover the worst case of the requests the ask would make (pieces already waiting are not weighed again); the `spending` member states admission's reason and scope. |
| 429 | `piece_quota_exceeded` | The workspace has made as many requests as a day allows, or holds as many open (section 7). |

## 5. Who runs the GPU, and who pays

The GPU is a Nebius AI Cloud Serverless AI job on one RTX PRO 6000 in the operator's Nebius
account; the operator creates the account, project, bucket and service account and starts a
session for a stated window. The product creates no cloud resource or credential. Every charge
lands on the operator's Nebius bill, which is the only authoritative total.

A request states its worst case at the listed rate. Under the workspace's lock, after the requests
already waiting are found, asking checks what admission would answer the workspace's next
`nebius_ai_cloud_gpu` attempt, and that the allowance left, less the worst case of every request the
workspace holds open, covers the worst case of the requests the ask would make; two concurrent asks
are weighed one after the other. It reserves nothing, because a reservation lapses within ten
minutes and a request may wait hours for a session. The worker that queues a request admits,
dispatches and settles it from the milliseconds the GPU measured for its items; a session's own
start, loading and idle time is charged to the operator, not to a workspace. A guest asks only while
a session is running.

## 6. The cost and time figures

The [piece compute catalog](../assets/catalogs/generation/piece-compute.v1.json) states, for each
GPU, the provider, platform, preset and region, the listed rate with its source and date, and what
generating took there. `tests/test_piece_compute_and_styles.py` holds the figures to the measured
runs on main (`ml/appearance/evidence/generated-assets-session-1/` and `-2/`): the rate and platform
are the run records', the typical item is their median, and the bounding item and the cold start are
chosen bounds the test checks lie above everything measured:

- the listed rate, USD 1.80 an hour;
- a typical item, 8 seconds (the median of the two sessions' 80 items, which took 6.6 to 23.0
  seconds), and a bounding item, 30 seconds, chosen above the slowest;
- a cold start, 680 seconds, chosen above what was seen: from the first starting state to the first
  batch took 596 and 608 seconds (the run records and done markers), after about 70 seconds of
  provisioning that a job watcher timed (76 and 69 seconds; no record on main states it);
- the service's shortest timeout, one hour.

An estimate states the items, the seconds to every request's first variant and to every variant on
a running session, the cold start, and the typical and worst-case dollars. Four variants of one kind
are USD 0.016 typically and USD 0.06 at worst.

## 7. Limits

A workspace may make 64 requests a day and hold 32 open at once (`piece_request_limits()`), counted
under the workspace's lock, so two concurrent asks cannot both take the last place. The same open
request for the same world is held once.

## 8. Deletion

A workspace tombstone cancels every open request of the workspace (`failure` `workspace_deleted`),
so no session makes a piece for a deleted workspace, and the workspace takes no new request. The
trigger is keyed on the tombstone's own columns, so a restored database that replays the tombstone
reaches the same requests. A request holds no person's text, only catalog keys, digests and
numbers.

An ask holds the workspace's lock (880024) from its first statement, as a deletion's own triggers
do, so the two never interleave: an ask after a deletion that has not yet committed waits for it and
is then refused as tombstoned (410), and a deletion sent while an ask holds the lock is refused at
once (migration 0137) and, sent again after the ask, cancels the request that ask made.

## 9. Supporting code and tests

| Part | Code | Tests |
| --- | --- | --- |
| Building requests and the estimate | `exulanica/generation/requests.py` | `tests/test_piece_request_planning.py` |
| The catalogs' readers | `exulanica_pieces/compute.py`, `exulanica_pieces/styles.py`, `exulanica_pieces/recipes.py` | `tests/test_piece_compute_and_styles.py`, `tests/test_piece_recipes.py` |
| The store and the migration that creates `piece_request` and `piece_ask` | `exulanica/generation/store.py` | `tests/test_piece_requests_postgres.py` |
| Deletion: the tombstone as each of its writers and through a restore, and its order with an ask | the migration's tombstone trigger, `exulanica/generation/store.py` | `tests/test_piece_request_erasure_postgres.py`, `tests/test_piece_request_tombstone_order_postgres.py` |
| The routes | `exulanica/api/routes/piece_requests.py` | `tests/test_piece_request_routes.py` |

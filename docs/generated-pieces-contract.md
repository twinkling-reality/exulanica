# Generated pieces

This contract owns asking for generated pieces: new pieces of a world's look, made by open models
on a GPU, for thing kinds a person's world holds. It covers what a request is built from, what it
holds, what it will cost and how long it will take, the routes, the limits, the generation session
and the worker that serves it, the shared store of generated pieces, and what a workspace deletion
does to its requests. How a piece is generated, post-processed and checked belongs to
[generated appearance](generated-appearance.md); the piece format and its budgets belong to the
[style pack contract](style-pack-contract.md); the allowance a request spends belongs to the
[model spending contract](model-spending-contract.md).

| Part | Status |
| --- | --- |
| Requests built from catalogs, their estimate, their store and routes, the workspace's limits | Implemented |
| The cost and timing figures, from two measured sessions on Nebius AI Cloud | Implemented |
| A generation session the operator starts and registers, the worker's queue entries, outputs and stored pieces | Implemented |
| Admitting, dispatching and settling a request's GPU time under the spending authority | Implemented |
| Answering a request from the pieces already kept, with no GPU run and no charge | Implemented |
| A session refusing to run an entry script other than the one its start command pinned | Built, not yet verified on Nebius |
| The operator's purge of stored pieces no row names | Planned |
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
minutes and a request may wait hours for a session. A guest asks only
while a session is running.

### 5.1 The session

The operator starts a session on their own account with the generation tooling
(`ml/appearance`: `assets session record --manifest`, `stage`, `start`), which writes the session's
manifest: the digest of the pinned models it loads and its container's digest. They register it
with `python -m exulanica.generation session open` (the session document, the manifest, the compute
catalog key, the provider's job id, a window of at most 24 hours and a label; a session of a route
no piece request takes is refused), close it with
`session close`, and list open ones with `session status`. The register (table
`generation_session`) is host data: only a member of the database's owner writes it, the runtime
role reads it, and once written only its close changes. Nothing in the product starts, stops or
creates a cloud resource.

A registered session reports its state by a heartbeat in the bucket every 30 seconds. It is
`starting` until its models have loaded, `warm` while its latest heartbeat is idle or working and at
most 90 seconds old, and `ended` when a heartbeat says so or they stop; with no session registered,
or past its window, it is `off`. Each session record carries a fresh nonce, so two sessions started
with the same settings have their own digests, heartbeats and markers; `session open` refuses a
record without one, and the register holds each digest once.

A session takes only the entries whose ready marker names it, never one past its not-after instant
or withdrawn by the worker, and passes over a directory that is not an entry or whose ready marker
does not read, since nothing then shows the entry is its own. It writes its last heartbeat, which
says it ended, only after every claim and done marker it will write, and the bucket mount writes
each file whole before the next is begun; the worker relies on both when it releases an entry an
ended session never claimed.

Nothing the session runs is taken from the bucket on trust. Its start command pins the digest of
the entry script beside the code archive's; the container copies the staged script to its own disk
and runs it only at that digest, and the script copies the code archive and the session record to
disk before holding each to its digest. Anyone who can write the bucket, the worker's key included,
can make a start fail but cannot make a session run other code. The check is a shell script the
service runs as the container's arguments; the sessions measured so far passed a single path there,
so this form is verified only when the next session runs.

### 5.2 The worker

`exulanica-piece-generation` serves the latest open session with the served workspaces' requests,
one pass every 15 seconds, each workspace in its own session under row-level security:

- **Answering**, only while the session is warm and the workspace has no batch in flight: a waiting
  request every variant of which the installation already keeps under the same cache key (the
  request's digest, the session's models and the post-process version: section 5.3) is answered at
  once from the kept pieces, with no GPU run, no reservation and no charge.
- **Queueing**, then: the oldest of the rest, at most 16 and only as many as the session can still
  finish (their job's stop, at the bounding item time, inside the session's own stop less two
  minutes), are each admitted under the workspace's `nebius_ai_cloud_gpu` grant at their worst
  case, in order; the first one admission refuses stays waiting with every request after it. The
  admitted requests are recorded as a batch (table `piece_batch`: the job and its digest, the
  session it went to, the instant after which no session takes it, and each request `queued` with
  its reservation), then their reservations are dispatched, then the batch is written as one queue
  entry in the bucket, named by the batch's own id: the job, with one item set for each request
  digest however many requests hold it, each request, and the ready marker last, which names the
  one session that may take the entry. A waiting request that no longer reads under the catalogs
  this server deploys (its piece budgets file changed since it was asked) ends `failed`
  (`request_unreadable`) before anything is admitted, since no session could make it. That end is
  final: a request asked under a catalog version the worker no longer runs, for instance during a
  deployment that updates the API before the worker, is asked again under the new one. Any failure
  before the ready marker ends the batch `refused` (`not_sent`) and releases its reservations, since
  no session could have taken it. The ready marker is written under the workspace's lock and only
  while the batch is still queued, so a deletion is either before it, and nothing is offered, or
  after it, and the worker withdraws the entry (`withdrawn/<entry>.json`) before it decides the
  cancelled requests' settlements. A session whose GPU the deployed compute catalog no longer
  prices is given nothing, and a batch it ran settles `unknown`.
- **Following**, every pass, for every batch still queued, each on its own, and each workspace on
  its own, so one fault never stops the rest. The worker reads only that entry's markers, and a
  marker naming another entry, job or session, or dated more than two minutes before the batch was
  queued, ends the batch `refused` (`marker_not_this_entry`). When the done marker says the session
  ran the entry, the receipts it names are read against their requests, checked at the shared
  store's boundary and kept (section 5.3), recorded (table `piece_output`: its receipt, the piece's
  digest, its cache key and whether it passed every check), and each request ends `made` when one of
  its variants passed, `refused` when none did; an output that does not read ends the batch
  `refused` (`outputs_unreadable`). When the marker says the session refused the entry, its requests
  end `failed` (`entry_refused`); a batch whose requests no longer read under the deployed
  catalogs ends `refused` (`request_unreadable`). With no done marker, a batch no session claimed
  expires two minutes after its not-after instant, or at once when its own session's last
  heartbeat says it ended, and one a session claimed expires two minutes after its claim plus its
  job's stop; its requests end `failed` (`session_ended`), and asking again makes a
  new request for a later session.
- **Settling.** Each request's settlement is decided with its batch's end (table
  `piece_settlement`) and then taken by the spending authority, retried every pass until it is: the
  listed rate times the milliseconds the GPU measured for its items, at most its reservation, and
  charged once for requests sharing a digest (to the oldest; the others settle at USD 0), when the
  entry ran, its outputs read or not; released when no session took the entry or it never reached
  the bucket, or (deleted while queued) its reservation was only admitted; and `unknown` (the whole
  reservation stays until an administrator reconciles it) when a session took it and said nothing
  more, when a marker was not the entry's or states more time than the job's stop, or when the
  workspace was deleted while it was queued with its reservation dispatched. The ask's own check of
  the allowance counts only requests that hold no reservation yet, since the allowance left already
  leaves out what a queued request reserved.

A session's own start, loading and idle time is not a request's and is charged to no workspace; it
is the operator's, on their Nebius bill. The worker holds two credentials, both from the operator's
environment, read in its own process and never written anywhere: the runtime database role, and a
key file for the bucket, whose requests put, get and list objects and delete none. The key the
operator issues for it can read and write the whole bucket; the pinned digests above, not the key,
keep it from changing what a session runs. It calls no model, and it spends through the durable
authority with the installation's spending witness, as every spending process does.

### 5.3 The shared store of generated pieces

A piece is kept once, in the `generated-pieces` namespace every workspace shares, because it is
made only from catalog content: a shipped thing kind, the recipe catalog's words or the kind's look
role, a committed look's palette and style words, the session's pinned models and a seed drawn from
the request. Its bytes hold nothing of any workspace's, so one workspace's erasure does not reach
them, and the same request asked again can be answered from them without a second GPU run.

That holds because the store's one write path checks it again, whatever the request store checked
when the request was asked (`exulanica.generation.pieces.store_piece`, which runs `admit_piece`
itself). The request must read
strictly, be catalog content and carry only the catalogs' words; its thing kind must be a shipped
kind at the digest it names and its look a committed version this server serves at its digest. The
receipt must read against the request (its digest and its variant's seed) and name the session's
components digest, and the bytes must hash to the receipt's output digest at its size. A piece
failing any of these is not written. The receipt's post-process version must be the one this code
makes pieces under, and the piece's cache key is computed there from the request's digest, the
session's models and that version. A request carrying a person's own words, should one ever be
accepted, is refused there by construction; its pieces would belong in the asking workspace's own
namespace.

Each kept piece is listed in the installation's index (table `generated_piece`: its cache key and
variant, receipt, piece digest and size). The index holds catalog content only, no workspace's: it
has no workspace column and no row-level security, its rows are never changed, and no workspace's
deletion erases them, as none erases the pieces. Each row's columns are its receipt's own, and its
cache key is computed from them, both checked by the table itself. Every output names an index
row, an output answered from the index is that row's receipt, and a request whose every variant is
indexed under its cache key is answered from it (section 5.2). A judge seed carries no generated
piece: its export refuses a workspace holding outputs, since the pieces' bytes are not in it, and a
reset of a judge stack leaves the destination's index as it is.

The namespace is bounded (`EXULANICA_GENERATED_PIECES_MAX_BYTES`, two gibibytes by default): a
piece that would take it past the bound is refused. A piece refused at the boundary, for any of
these reasons, is neither kept nor recorded as an output, and the worker logs its code; a request
none of whose pieces was kept ends `refused`, its GPU time still settled. Removing stored pieces no row names is the operator's, by a command not yet built.

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

The same tombstone erases the workspace's batches and outputs (a trigger owned by the definer role,
which may only read and delete those two tables). Its settlements are kept, since they hold only
ids, a basis and an amount and its reservations must still be settled: a request the tombstone
cancelled while queued is settled `unknown`, or released when its reservation was only admitted.
A stored piece and its index row stay, because they hold nothing of the workspace's (section 5.3).
The judge's seed export refuses a workspace that holds an open request and copies only ended
requests and batches, so a seed never carries one into another database, even one asked while the
export runs; settlements, as money rows, never travel in a seed.

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
| The session register and its commands | `exulanica/generation/__main__.py`, `exulanica/generation/batches.py` | `tests/test_generation_session_commands_postgres.py` |
| The bucket, its entries and the session's state | `exulanica/generation/bucket.py`, `exulanica/generation/entries.py`, `exulanica/generation/session.py` | `tests/test_generation_bucket.py` |
| The worker, its batches, outputs, kept-piece answers and settlements | `exulanica/generation/worker.py`, `exulanica/generation/batches.py`, `exulanica/generation/command.py` | `tests/test_piece_generation_worker_postgres.py` |
| A batch's end and its workspace's tombstone, in each order | `exulanica/generation/batches.py` | `tests/test_piece_batch_tombstone_order_postgres.py` |
| The queue format both sides read, and the session that serves it | `exulanica_pieces/queue.py`, `ml/appearance/exulanica_appearance/assets/session.py`, `ml/appearance/container/assets/job.sh` | `ml/appearance/tests/test_assets_session.py` |
| The shared store's boundary and bound | `exulanica/generation/pieces.py` | `tests/test_generated_piece_store.py` |
| Deletion of batches and outputs | the second migration's definer trigger | `tests/test_piece_request_erasure_postgres.py` |
| The index held to its receipts, one registration per session, and the output trigger's erased-workspace and kept-receipt checks | the migration `a_kept_piece_is_its_receipt` (after the one that creates batches) | `tests/test_piece_requests_postgres.py`, `tests/test_generation_session_commands_postgres.py` |

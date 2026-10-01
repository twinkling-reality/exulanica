# Model spending

This contract owns the durable spending authority: the one allowance of money for hosted model
calls that every process of an installation shares, and that neither a restart nor a database
restore replenishes. It covers authorities, workspace grants and bounds, how an attempt is admitted,
dispatched and settled, idempotency, revocation, concurrency, restore protection and
reconciliation. Each process's own safety fuse is owned by the
[security floor](security-floor.md#4-model-spend-budgets); the hosted-request boundary that decides
what a request may carry is owned by the [privacy contract](privacy-consent-threat-model.md).

Contents: [two limits](#1-two-limits-and-which-one-is-money) ·
[authorities, grants and bounds](#2-authorities-grants-and-bounds) ·
[an attempt](#3-an-attempt-from-admission-to-settlement) · [idempotency](#4-idempotency) ·
[revocation and expiry](#5-revocation-and-expiry) · [locks](#6-concurrency-and-locks) ·
[restore](#7-restore-the-spending-witness) · [reconciliation](#8-reconciliation-with-evidence) ·
[configuration](#9-configuration-and-composition) · [operator commands](#10-operator-commands) ·
[what a client sees](#11-what-a-client-sees) · [limits](#12-what-this-does-not-provide)

## 1. Two limits, and which one is money

DECISION. Two limits hold every hosted attempt, and they are not the same thing.

| Limit | Kept | Resets | For |
| --- | --- | --- | --- |
| Process fuse (`BudgetGuard`, `EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`) | In one process's memory | At every restart; every process has its own | Stopping a runaway loop |
| Durable authority (this contract) | In the database (migration 0124), with a witness outside it | Never; only an operator's recorded decision changes it | The money an installation may spend |

A process composed with the durable authority admits an attempt only when both allow it. The fuse
is not an allowance and the authority is not a loop detector; neither replaces the other.

## 2. Authorities, grants and bounds

VERIFIED (`tests/test_spending_ledger.py`). The allowance is a tree, checked at every level on every
admission:

- **Authority.** An operator issues one for one provider (`spending_authority`): a ceiling in USD,
  a call limit, a validity end, a dispatch window, and whether a witness protects it from a restore.
  Its terms change only as a new recorded epoch (`spending_authority_term`): issued, adjusted,
  reauthorized, or carried back by a restore reconciliation.
- **Workspace grant.** An operator grants one workspace an allowance under an authority
  (`spending_grant` with no parent). A workspace holds at most one live grant per provider.
- **Bound.** A piece of work (a comparison, a run) opens a bound under the workspace's grant,
  idempotently by its key, and may close it; it cannot open a grant. A comparison started from the
  application opens one for each provider it asks, keyed `comparison:<comparison id>:<provider>`,
  with the bound its owner stated and the most calls it can make, valid while the grant is, and
  admits every ask under its provider's bound; it closes them when it is finished and when it is
  cancelled (`exulanica/api/comparison_spending.py`,
  [comparisons](society-experiments.md#running-a-comparison)). A start whose bound or calls the
  grant has not left room for is refused before anything is written; it is never given a smaller
  bound. Comparisons are the only work that opens one.

Nothing is granted because a workspace exists: a workspace with no live grant refuses every attempt
as `spending_not_granted`, and no import, seed or restore creates a grant (spending tables never
travel in a workspace seed). A grant is never larger than what it is granted under, in ceiling, calls
or validity, and a trigger refuses one that would be, for every role. Because every admission is
checked against the authority, the grant and any bound, grants together never pass their authority
and a bound never passes its grant.

## 3. An attempt from admission to settlement

VERIFIED (`tests/test_spending_protocol.py`, `tests/test_spending_ledger.py`). The model client's
single hosted path (`exulanica/models/chain.py`) takes each attempt through these steps, each a
short transaction through a function migration 0124 grants the runtime:

1. **Admit.** After the process fuse reserves the attempt and its credential is found, the attempt's
   worst case (the fuse's own estimate) is held against every level, or refused before anything is
   sent. Attempts the workspace admitted and never dispatched within the dispatch window can no
   longer leave, and an admission that takes the authority's row releases them first, whatever
   its own answer; one refused before that releases nothing ([section 12](#12-what-this-does-not-provide)).
2. **Dispatch.** The durable record that the request may now leave, committed before the transport
   is given it, and on the ledger and the witness like every other step, so a restore cannot lose
   it unnoticed ([section 7](#7-restore-the-spending-witness)). An attempt past its window, under
   an authority, grant or bound suspended, revoked or expired since it was admitted, or while the
   witness disagrees with the ledger, is refused here and released, and never sent.
3. **Settle.** A reply with usage replaces the reservation with the reported tokens priced by the
   manifest. A failure proven never to have left (no connection, a refused destination) releases
   the liability and the call. Anything else after dispatch keeps the whole reservation: a timeout,
   an error status, a reply without usage, or a process stopped part way.

Each admission is named by its own attempt: the process's label, its process id and a nonce, and a
nonce for the attempt. Only that attempt dispatches, settles or releases its reservation; another
call, of the same process or another, is refused at admission and cannot release it. The name
separates attempts against accident, not sessions of the runtime role against each other: any of
them may read a reservation's holder in its workspace. The runtime is trusted to settle what it
sent; the authority bounds what it may spend.

| State | Meaning | Liability held |
| --- | --- | --- |
| `admitted` | Held, not yet allowed to leave | The reservation |
| `dispatched` | May have left; no outcome recorded | The reservation |
| `settled` | The provider reported usage | The priced report |
| `unknown` | Left, and its cost is unknown | The reservation, or more if a report said so |
| `released` | Never left | Nothing; the call is returned too |
| `reconciled` | An operator recorded its cost from evidence | The reconciled amount |

"Known usage" means provider-reported token counts priced by the manifest. It is not the provider's
bill. A report above the reservation is recorded as it is and named in the ledger
(`over_reservation`), never trimmed. A settlement the authority cannot take (its database did not
answer, or its witness disagreed with the ledger) never costs the caller a paid answer; the
reservation stays at its whole liability.

Refusals, raised as `SpendingRefused` (a `BudgetExceededError`) before anything is sent:

| Reason | Meaning |
| --- | --- |
| `spending_scope_missing` | A client composed with the authority reached a request with no workspace: a composition fault |
| `spending_not_granted` | No live grant covers the workspace and provider |
| `spending_revoked` / `spending_expired` | The authority, grant or bound was revoked or has expired; for a workspace with no live grant, as its latest grant stands, never an older one |
| `spending_limit_reached` | A ceiling of the authority, grant or bound would be crossed |
| `spending_suspended` | The authority is held closed until an operator acts ([section 7](#7-restore-the-spending-witness)) |
| `spending_unavailable` | The database or the witness did not answer; nothing was let through |
| `duplicate_request_in_flight` / `_unknown` / `_settled` | Idempotency ([section 4](#4-idempotency)) |

## 4. Idempotency

VERIFIED (`tests/test_spending_ledger.py`, `tests/test_spending_crash.py`). Every reservation has a
key unique in its workspace. A caller that would replay a whole request after a crash makes it
inside `spending_request_key(key)` (`exulanica/models/spending.py`), with its own stable identity for
the request; each attempt inside is admitted as `<key>#<n>` in order, so the replay is admitted as
the same attempts. Outside one, every attempt has a fresh key and is accounted durably but is not
deduplicated.

No production caller makes its requests inside one yet. Every attempt of the API, the workers, the
comparisons and the decision host is admitted under a fresh `auto:` key
(`exulanica/models/chain.py`). So a request a caller replays after a crash, or a job its queue runs
again, is admitted as new attempts: what each reserves is held and settled as
[section 3](#3-an-attempt-from-admission-to-settlement) says, and the authority still bounds what is
spent, but the same request can be sent, and billed, twice. The deduplication in the table holds
for a caller that passes a key, which today is the tests
([section 12](#12-what-this-does-not-provide)).

| An attempt with the key is | Asking again |
| --- | --- |
| Admitted by another attempt, of this process or another, in its window | `duplicate_request_in_flight` |
| Admitted and past its window, or released | Admitted again under the same reservation |
| Dispatched, unknown, or frozen by a restore | `duplicate_request_unknown`: it may have been sent, and is not sent again |
| Settled or reconciled | `duplicate_request_settled` |

`tests/test_spending_crash.py` stops a process with SIGKILL after its witness write and before its
commit, after admission, after dispatch, after sending, after the reply and before settlement, and
after settlement, then retries the same request, under the same key, from a new process: no request
is sent twice where the first may have left, and the restarted process never finds the liability
returned.

## 5. Revocation and expiry

VERIFIED (`tests/test_spending_ledger.py`, `tests/test_spending_operator.py`,
`tests/test_spending_witness.py`). An operator revokes an authority, a grant or a bound; a bound's
opener may close it. A revocation is an appended row under the authority's lock, and a ledger event
while the witness agrees with the ledger (while it disagrees, the row alone, so the disagreement
stays as it was): every later admission refuses, every attempt admitted and not yet dispatched is
refused at dispatch, and attempts already dispatched settle as before. Closing a bound changes
nothing committed, so it takes no state row and is not on the ledger; a dispatch reads the closure
under the state row. Nothing is deleted or updated in place. Revocations are withdrawals a restore
must not undo: the withdrawal catalog carries both revocation tables
(`exulanica/deletion/withdrawals.v2.json`), a sealed restore checkpoint refuses them, and the
witness holds the authority's and every workspace grant's for a restore made without a checkpoint.
Validity ends at the authority's current term, the grant's and the bound's own end.

An attempt admitted and never dispatched in its window is released by the next admission of its
workspace that takes the authority's row, whatever that admission's answer, and by `expire`, which
releases every workspace's. An installation runs `expire` on a schedule: until then, a workspace
that does not ask again, or whose admissions are refused before the row (its grant revoked or
expired), holds its stale admissions against the authority, which fails closed.

## 6. Concurrency and locks

VERIFIED (`tests/test_spending_race.py`, `tests/test_spending_operator.py`).

- **One lock root per authority.** Every write that changes what is committed, and every dispatch,
  takes the authority's state row first (`FOR UPDATE`), then grants, bounds and reservations. Every
  process takes the authority's witness lock before that row, runtime and operator commands alike,
  and nothing takes the row while holding a reservation or a grant, so no two steps wait in a cycle.
  Opening and closing a bound change nothing committed and take no state row.
- **Bounded waits.** Each spending transaction sets a lock timeout (5 s) and a statement timeout
  (15 s; 60 s for operator commands). A step past either refuses (`spending_unavailable`) and lets
  nothing through.
- **Turns.** Threads of one process take the witness in the order they asked; between processes the
  file lock is polled and is not first come, first served.
- **Measured.** Four separate processes (two plain clients, one built as the API builds its client
  and one as the derivative worker builds its own) race one small limit, with the witness and with
  the database row lock alone. Replayed event by event, the authority's committed liability never
  passes its ceiling; every request a transport saw was a dispatched reservation, and no refused
  attempt reached a transport.

## 7. Restore: the spending witness

DECISION. A restored database holds an older ledger with less spending in it. The witness is kept
where a restore does not reach, so a restore cannot hand the difference back.

- **What it is.** One digest-bound record per witnessed authority (`exulanica.spending-witness/v1`,
  `exulanica/spending/witness.py`): the ledger's sequence, head digest and the head before it, the
  current terms, what is committed for the authority and each workspace grant, and every revocation
  of the authority and its workspace grants.
- **When it is written.** Every step on the ledger (an admission, a dispatch, a settlement, an
  operator's decision) writes it unconfirmed before its database commit, keeping the record before
  it (`prior`), and confirmed after. A commit that failed leaves it one step ahead, unconfirmed and
  naming the ledger's head as its previous one, which is read as a step that never happened.
- **Where it lives.** `EXULANICA_SPENDING_WITNESS_DIR`, on storage outside the database's backup
  domain, shared by every spending process of the installation on one host (a local filesystem with
  POSIX advisory locks), and never restored together with the database. Copies kept in backup sets
  or custody are evidence and are marked as copies when installed. The envelope's state, never
  anything a record holds, says whether a witness is live or a copy.
- **Which directory.** The directory carries a marker naming it (`witness-directory.json`), written
  by the operator commands and never by a spending process. Every witness a process reads names its
  directory, and an authority records the directory its witness is kept in (migration 0133): at the
  first operator step whose witness agrees with its ledger, and at every reauthorization and
  reconciliation, which an operator makes from the directory the witness is kept in from then on. A
  process whose directory has no marker, or another one, cannot prove it reads the authority's
  witness: it is refused alone and suspends nobody. An authority with no recorded directory is not
  checked.

VERIFIED (`tests/test_spending_witness.py`). Each step compares the witness it read with the ledger
under the authority's row:

| The witness | Admission | Until |
| --- | --- | --- |
| Agrees, or is one unconfirmed step ahead of the ledger's head | Proceeds | |
| Is ahead of the ledger (a database restored behind it) | Refused `spending_suspended`, `ledger_behind_witness` | `reconcile-restore` |
| This process has none (`witness_not_configured`) | Refused in this process only | Configured |
| Is in a directory that is not the authority's: no marker, or another (`witness_directory_mismatch`) | Refused in this process only | The process is given the installation's directory |
| Is missing, unreadable, behind or diverged | The authority is suspended | `reauthorize` |
| Is a copy installed from custody | The authority is suspended | `reconcile-restore` when the copy is ahead, then `reauthorize` |

NOTHING IS APPENDED TO A LEDGER ITS WITNESS DISAGREES WITH. A settlement is not recorded and the
attempt keeps its whole liability; a dispatch is refused; a revocation is recorded as its row alone;
a suspension is kept in the authority's state, not as an event. So a ledger restored behind its
witness stays behind it: later steps never make it look diverged from the witness or ahead of it,
which would hide what the restore lost.

`reconcile-restore` carries a restored ledger forward to its witness, live or a copy from custody:
the authority and each workspace grant are raised to what the witness says was committed, the
difference recorded as carried. Where the witness's last step is unconfirmed, it may never have
committed, so the carry takes the larger amounts of that step and the one before it, every
revocation of either, and the tighter terms. Every attempt the restored ledger still holds open is
frozen, since its later outcome is already in what the witness carries; every bound it holds open
is closed, since bounds are not in the witness; the witness's terms and revocations are written
again; the ledger continues from the witness's head. What was spent stays spent. After a copy the
authority stays suspended (`witness_copy_only`) until reauthorized, since the copy may be older than
the live witness it stands in for; the record a reconciliation from a copy writes stays a copy until
its commit is confirmed, so one that never commits leaves a copy, and the reconciliation made again
still holds the authority. A reconciliation writes revocation rows (the witness's, and every bound
it closes), which a sealed restore checkpoint refuses as it refuses every withdrawal: it is made
after the checkpoint is unsealed.

`reauthorize` is an operator's explicit new epoch with stated terms; it clears a suspension and
writes the witness whole from the ledger. A witness or copy that may hold spending the ledger lacks
(ahead of it, diverged from it, or another authority's) is discarded only when the operator says so
(`--discard-witness`); one that is ahead is carried by `reconcile-restore` instead. A missing or
unreadable witness holds nothing to keep, and reauthorizing is the explicit decision that it does
not.

## 8. Reconciliation with evidence

An attempt that is `unknown`, or dispatched and never settled, keeps its whole liability until an
operator reconciles it to what evidence shows: `source` and `reference` labels and `observed_at`,
and nothing else (no key, account or address fits their patterns). A frozen attempt is not
reconciled; its outcome is already in what a restore carried. No provider billing interface is
read; reconciliation is an operator's act.

## 9. Configuration and composition

- `EXULANICA_SPENDING` is `durable` or `process`, and a process holding a provider's credential
  refuses to start without it. With no credential and no setting, the process asks no model.
- `durable`: `build_services` composes the API's model client (an injected one included) with the
  authority, and so does `worker_model_client` for the derivative worker; the comparison worker
  process uses `build_services`. The workspace a request spends for is the one the attached
  workspace policy names, set by the composition from the authenticated session; a client composed
  with the authority refuses a request with none.
- `process`: the process spends within its fuse alone, and `/readyz` says that a restart or another
  process starts it again at zero.
- `EXULANICA_SPENDING_WITNESS_DIR` names the witness directory; a durable process without it refuses
  to spend under a witnessed authority, and `/readyz` says so. A directory with no marker is named
  in `/readyz` too: the process refuses to spend under any authority whose directory is recorded.
- Measurement scripts and the offline commands that build a `ModelClient` directly spend within
  their own fuses and are outside the authority unless given a source (`ModelClient(spending=...)`).
- VERIFIED (`tests/test_spending_privileges.py`, `tests/test_judge_seed.py`). The runtime, the
  read-only and the judge roles read their own workspace's grants, bounds and reservations,
  row-level security keeping every other workspace's out; the runtime changes them only through the
  five runtime functions. None holds a privilege on an authority's tables or the ledger, and each
  reads an authority's state, with no amount, through `spending_authority_facts`. Migrations 0124
  and 0133 take back whatever a provisioner's default privileges gave on these tables (0133 with
  CASCADE, and MAINTAIN too), without waiting for the next provisioning.
- What the runtime process receives. The functions it executes return what its process writes to
  the witness: after each step, the authority's committed USD and calls, its terms, and the
  ledger's sequence and head (so two of its own steps show how many others happened between them),
  with the committed amounts of the grants the step touched; and a refusal by the authority's
  ceiling carries the authority's limit and committed amount. The read-only and judge roles receive
  none of it. VERIFIED (`tests/test_spending_route.py`): no HTTP answer states any of them, not a
  refusal by the authority, not `GET /spending`, not `/readyz`.

## 10. Operator commands

`python -m exulanica.spending` with an administrative database URL (a role with SUPERUSER or
BYPASSRLS) and the witness directory; each command prints one JSON document, and writes the
directory's marker first where it has none. `issue`, `adjust`,
`grant`, `revoke`, `reconcile`, `reconcile-restore`, `reauthorize`, `expire` (release every
workspace's attempts never dispatched in time; run it on a schedule), `verify` (the ledger's digest
chain), `install-witness-copy` and `status`. `--operator` is a label for the record: lower case letters,
digits and `:._-`, never a name, an address or a key. The runtime roles may not execute any of these.
`issue` names its authority on standard error before issuing it, so an answer that never arrives is
asked again with `--authority-id`, which never issues a second authority. A step that committed and
whose witness record could not then be confirmed answers done, with `"witness_confirmed": false`:
the record stays unconfirmed at the ledger's own sequence, which the next step reads as having
taken effect, so asking again would repeat the step.

## 11. What a client sees

- A refused attempt answers `429 budget_exceeded`, as a fuse refusal always has, with a `spending`
  member: `reason`, `scope`, `detail`, `retry` (`never`, `later` or `after_reauthorization`) and,
  for a workspace's grant or bound, `limit`, `committed` and `requested` as decimal strings. A
  refusal by the authority states no figure of it, since its committed amount is every workspace's
  spending together. A fuse refusal carries no `spending` member.
- `GET /spending` (`operations.read`) states the caller's own workspace's spending by provider: its
  grant and state, what is committed, in flight and unresolved, known usage and reconciled amounts,
  what is left, the authority's state (`active`, `suspended`, `expired`, `revoked`, `exhausted`)
  and whether it is witnessed, and how the serving instance spends (`mode`). It never states another
  workspace's figures or an authority's total.
- The decision host records a durable refusal on a subject's receipt by the authority's own reason
  (`spending_not_granted`, `spending_revoked`, `spending_expired`, `spending_limit_reached`,
  `spending_suspended`, `spending_unavailable` or `spending_scope_missing`), and a comparison run
  that refusal ends fails by that reason.
- Before any attempt, the workspace's own spending is projected onto the refusal admission would
  give its next attempt of each provider (`exulanica.spending.status.admission_refusal`): with no
  live grant, the latest grant's state, its authority first; with one, the authority suspended, a
  witnessed authority asked by a process with no witness directory, the authority expired or
  exhausted, then the grant's calls and money. The reason, scope, detail and retry are admission's,
  with the grant's figures; it states no requested amount, since no attempt is made, and for an
  exhausted authority neither unit. VERIFIED against a real admission in each state
  (`tests/test_spending_admission_projection.py`).
- An ask reaches its chosen model's provider alone (`ModelClient.choose` walks one model, and a
  chain falls back only on a model that is no longer served), so a refusal never falls through to
  another provider. A comparison's start, of a world's people or a town's signals, that would ask a
  model whose provider's allowance is spent is refused with that projection before anything is
  defined: the same `429 budget_exceeded` with its `spending` member. The capability reads state it
  too ([world API](capabilities/world-api.md)): the start is `unavailable` by its reason, as is a
  model choice's `decisions` effect, once every provider the role can ask is spent. VERIFIED
  (`tests/test_comparison_start_allowance_postgres.py`).
- The projection cannot foresee three refusals, which admission still gives when the attempt is
  made: a remainder above zero that one attempt's reservation does not fit, an authority whose own
  remainder (every workspace's spending together, which no workspace reads) does not fit it, and a
  witness directory that is not the authority's.

## 12. What this does not provide

- OPEN. The provider's bill is not read. Known usage is the provider's token report priced by the
  manifest, and an unknown outcome stays at its whole liability until an operator reconciles it.
  A bounded live reconciliation experiment is prepared, not run.
- OPEN. The witness is single-host. Processes on another host must run without spending, or refuse
  (`witness_not_configured`); a witness shared across hosts is later work.
- OPEN. A restore to exactly the ledger's state before its last step, taken after that step committed
  and before its witness was confirmed, cannot be told from a commit that failed; that one step's
  effect is not carried forward: an admission's reservation, a settlement above its reservation, an
  operator's reconciliation that raised a liability, a lowered ceiling, or a revocation.
- OPEN. A witness restored together with its database agrees with it and protects nothing: the
  deployment keeps it outside the backup domain.
- OPEN. Bounds are not in the witness. A restore's reconciliation closes every bound the restored
  database holds open; a bound opened after the backup is absent from it, and opening one again
  under the same key starts it at zero, still inside its grant and authority, which are carried. A
  restore that lost no ledger step needs no reconciliation, so a bound closed after its backup is
  open again unless a sealed restore checkpoint carried the closure; what it committed is accurate.
- OPEN. Deduplicating a replayed request is a delivered mechanism with no production caller: no API,
  worker or comparison path passes `spending_request_key`, so a request replayed after a crash is
  admitted as new attempts, within the allowance, and may be sent and billed again (section 4). The
  decision host, by its decision request, and derivative jobs, by job and stage, are its planned
  first users. Comparisons, which open durable bounds (section 2), pass no request key either: a
  takeover's replayed ask is admitted as a new attempt, within the comparison's bound.
- OPEN. An attempt admitted and never dispatched holds its reservation against the authority until
  an admission of its workspace takes the authority's row or an operator runs `expire`. An admission
  refused before the row (no live grant, an authority that changed or is suspended, a witness that
  disagrees) releases nothing, so a workspace whose grant was revoked or expired keeps its stale
  admissions against every workspace's allowance until `expire` (VERIFIED,
  `tests/test_spending_ledger.py`). This fails closed, never open.

# ADR-0026: A restore carries every withdrawal a person made, not only their deletions

- Status: Accepted
- Date: 2026-09-24
- Supersedes: nothing
- Related: ADR-0019, [privacy threat model section 5.4](../privacy-consent-threat-model.md#54-tombstones-that-survive-retries-and-restores), [personal admission](../personal-admission.md)

## Context

ADR-0019 makes a restore replay a sealed checkpoint of every tombstone before the database serves,
because a backup that predates a deletion holds no record of it. A tombstone is not the only way a
person ends something. Stopping a model right is `personal_model_right.withdrawn_at` (migration
0073); withdrawing a presentation or training consent, or a place name's right, is the next
decision in its chain; deleting a Companion memory sets its status; logging out revokes a session.
Each lives in the row it ends or in a row of its own, so a restore from a backup older than it
brought the thing back as current, and the tombstone replay never saw it. Measured before this
decision: a description right stopped after the backup was current again after a completed replay,
and a search right stopped after the backup kept the search entries its stop had deleted, because
the replayed stop's cascade erases only what no current right covers.

## Decision

A checkpoint of profile `exulanica.restore-tombstone-checkpoint/v2` carries every withdrawal
[`exulanica/deletion/withdrawals.v1.json`](../../exulanica/deletion/withdrawals.v1.json) names,
beside every tombstone, and the catalog's identity (its profile and the SHA-256 of its canonical
JSON). The catalog states, for each table, the rows a withdrawal writes and how a withdrawn row is
recognised, in two shapes: a column kind is a row that records its own withdrawal once and is
carried as its identity and those columns, nothing else; an event kind is a withdrawal that is a row
of its own and is carried whole.

- **Sealed the same way.** Checkpoint creation locks every catalog table against writes while it
  reads them, and migration 0107 refuses every withdrawal write while `restore_control` says
  sealed, as 0036 refuses tombstones, direct SQL included.
- **Replayed first.** Replay writes every carried withdrawal into the restored database before any
  tombstone, by the statement the product writes: a column kind sets its columns on a row whose
  withdrawal is still open, so every trigger that update fires runs; an event kind appends its row
  when the database holds what it ends and the chain does not already end withdrawn. A row the
  backup lacks needs nothing: a restore never brings back what its backup does not hold. A row held
  with another withdrawal, or an event the database refuses, refuses the replay by name. A stopped
  search or training right writes a tombstone of its own again, whose cascade erases what the stop
  erased (0104, 0082), so that erasure does not depend on the order: carried after the tombstones,
  the same entries went. Before them, each replayed tombstone's cascade reads the rights its source
  cascade read and records the same targets.
- **Refused when stale.** Tombstones and withdrawals are written once and never removed, and a
  checkpoint is sealed from the source after every backup of it, so a current checkpoint holds
  everything its restored database holds. The first attempt of a replay refuses a restored database
  holding a tombstone or a withdrawal the checkpoint lacks: the checkpoint is older than the backup.
- **Profile v1 stays readable.** It carries no withdrawal. A v1 replay refuses to complete while a
  search entry its checkpoint erased is present and was made before the deletion took effect, so a
  lost search stop is refused rather than served; a lost stop of any other kind is not visible to it.

A search entry is a row of the restored database, not stored bytes, so the replay copy's own cascade
decides which entries a replayed deletion still erases there, and the checkpoint's list of erased
entries is checked after the purge: an entry it names may be present only when it was made after the
deletion took effect, which is how a search right granted again after a stop indexes the photograph
again (0104).

## What the catalog does not carry

Every other table shaped like a withdrawal is named in the catalog's `excluded` list with its
reason, and `tests/test_restore_replay_withdrawal_catalog.py` fails on one the catalog neither
carries nor names: identity decisions and a place bridge's revocation, which a later decision or
undo reverses; a retraction, which writes two rows no trigger ties together; a photograph taken out
of a saved world, which is an authored edit; columns nothing writes; and rows a replayed tombstone
writes again. A restore returns those to the backup's state like any other authored edit.

A place name's decisions form a chain the database checks: each follows the last one exactly. When
the backup ends that chain at a grant the checkpoint's withdrawal does not follow, because a later
grant it follows was made after the backup, the replay refuses by name rather than leave the grant
current.

## Rejected alternatives

- **A tombstone per withdrawal.** A tombstone erases personal data; most withdrawals end a
  permission and erase nothing, as 0066 argued for a recipe. A tombstone does not name the row it
  ends, so replay could not write the withdrawal again.
- **Inferring a withdrawal from a replayed tombstone.** A `caption_search` tombstone implies its
  photograph's search rights were stopped, but only the two withdrawals that write tombstones would
  be covered, and the inference guesses which row and when.
- **A journal of withdrawals in the database.** A restored database rolls it back with everything
  else, which is ADR-0019's premise.
- **Copying whole rows back.** The checkpoint would carry purposes, notices and receipts the
  withdrawal never wrote, and replay would overwrite state the withdrawal never touched.
- **Refusing every backup older than a withdrawal.** Always safe, and a restore could then never
  complete after a single stop.
- **Recording the checkpoint's erased search entries as the replay copy's purge targets.** Only a
  trigger may write a target row, and a trigger fed the checkpoint's list would destroy an entry a
  search right granted after the stop indexed again. Queueing those entries as jobs without a
  target row leaves jobs no purge can claim, so the replay never completes.

## Verification

`tests/test_restore_replay_withdrawals.py` restores a real dump for a stopped description right, a
withdrawn training right, a deleted Companion memory, a withdrawn place-name right, a withdrawn
presentation consent, a withdrawn training consent, a withdrawn recipe, a logged-out session and a
disabled account, and holds the seal, the stale refusal, the catalog identity and the chain
refusal. `tests/test_restore_replay_search_entries.py` holds the search stop in both profiles. The
environment source and asset kinds and the account workspace and membership kinds are written by
the same column statement; their statements are run against the schema in
`tests/test_restore_replay_withdrawal_catalog.py`, which no real restore here repeats.

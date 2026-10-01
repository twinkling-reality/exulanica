# ADR-0028: A crash recovery replays a declared withdrawal export and refuses a stale one

- Status: Accepted
- Date: 2026-09-30
- Extends: [ADR-0019](0019-offline-restore-tombstone-replay.md) and
  [ADR-0026](0026-a-restore-carries-every-withdrawal.md), whose sealed planned restore is unchanged
- Related: [privacy threat model section 5.4](../privacy-consent-threat-model.md#54-tombstones-that-survive-retries-and-restores),
  [deployment section 9](../deployment.md#9-backups-and-recovery)

## Context

ADR-0019 restores over withdrawals by replaying a checkpoint sealed from the stopped source after the
backup. A source that is lost cannot be stopped or sealed, so after a crash no current checkpoint of
it can exist, and a restored backup alone would bring back every withdrawal made after it.

## Decision

- A running source writes **withdrawal exports** (`export_withdrawals`, profile
  `exulanica.restore-withdrawal-export/v1`): the checkpoint's record, read in one read-only
  repeatable-read snapshot, without a seal, with `covered_through`, the transaction's start. The
  restore command's `export` writes one to custody outside the content-store backup domain and
  keeps the newest few. An installation's maintenance runs it when withdrawals change and at
  least every export interval, keeping also those a retained backup names; while maintenance is
  stopped, the window is as long as the time since the last export anyone ran.
- An export is replayed only in a **declared crash recovery**: an operator's declaration names the
  export and the time the source was lost. The restore refuses unless that time is after the export
  and within the installation's bound of it, at most 24 hours. The marker records the declaration in
  full and replay validates it again, and the receipt (migration 0129) records the window.
- Withdrawals committed after the export and before the incident are **not recovered**. The window
  is stated at prepare and replay, in the marker and in the receipt, never silently.
- An export refuses a standby, a sealed or replaying source, and a declared restore not yet complete,
  because each would date old content as current. A sealed checkpoint takes no declaration, so a
  planned restore and a crash recovery never mix. Each carries its catalog identity, so a crash
  recovery runs on the release the export came from and upgrades afterwards.
- Every export records its source, derived from the database server and database, so a restored
  database is a different source from the one it came from. An export refuses a database lacking
  a tombstone the newest export of any source holds, or still holding a row whose withdrawal that
  export records as applied, so neither a restored database that has not replayed nor another
  database can date old content as current. A row the database does not hold at all (a sign-in
  session no backup carries, a row made after the backup) is honoured, so a replayed restore can
  export again. Custody keeps the pruning source's newest exports, every other source's newest one
  and every export a retained backup names, so a source that no longer writes leaves one export.
- A crash recovery replays only the newest valid export in the installation's custody directory,
  wherever the file named lies, in both restore commands. A planned restore that set its source
  aside lets that source serve again only while the restore is pending; once the restored database
  has served, the set-aside source is discarded, never resumed. The marker records every
  completed restore and carries the record forward; while it is kept, preparing, resuming or
  replaying a recorded checkpoint again is refused, and a lost marker loses that record. A source
  is set aside only when its identity proves it is the source before the seal and it is sealed for
  the checkpoint before the rename; returning to it and dropping it check that seal.
- A withdrawal whose end the installation makes again after a restore (a published character
  catalog, which the catalogs job publishes from the image) is carried even when the backup lacks
  the end (`"absent": "carry"` in the withdrawal catalog), so it is neither served again nor left
  open for the next export to refuse.
- Unattended maintenance reads as `exulanica_backup`: BYPASSRLS, SELECT only, no membership and no
  SECURITY DEFINER function, so it never holds the owner. Its read-only default is defense in depth
  only (a session can lift it); the residuals are stated below.

## Rejected alternatives

- **A synchronous external withdrawal journal**, written before a withdrawal is acknowledged. It
  would make the loss window zero, but every withdrawal route would then depend on an external
  store being reachable, and it needs a schema and a writer change in every withdrawal path. It is
  the change to make if a nonzero window becomes unacceptable.
- **An operator override of a stale export.** A recovery that could proceed past its bound would
  serve an older, more permissive state whenever someone chose to. Failing closed leaves the
  installation refusing traffic until a current authority is found; no override exists.
- **One-shot maintenance jobs holding the owner connection.** An owner can write, alter and drop;
  a job holding it unattended is the risk the backup role removes.

## Consequences and residual risks

- The window is in commit time: a withdrawal whose transaction began before `covered_through` and
  committed after it is outside the export, so its own `requested_at` can precede the window.
- An export's reads take ACCESS SHARE locks, which make a concurrent checkpoint or schema change
  wait for it; they block no writer.
- An export is a full cross-workspace copy of each withdrawal's identifying fields. Custody retention
  and its separation from backups bound how many copies exist; custody itself is operator trust.
- The backup role, with its read-only default lifted, can create temporary tables and large
  objects, which PostgreSQL grants to every role; maintenance reports any large object. It can take
  advisory locks, send NOTIFY and change its own password. It is a read-all credential.
- Backup dumps omit the rows of the two sign-in tables that hold plaintext nonces, verifiers and
  CSRF tokens, so a recovered installation signs everyone out.
- An undeclared restore (a database restored with no marker naming it) is still outside the
  protocol, as in ADR-0019; the refusal against custody's newest export covers its exports only.
- As in ADR-0019, custody writers are trusted: an export relabelled as a sealed checkpoint with a
  recomputed digest would need no declaration, because the digest is unkeyed. A keyed digest or a
  signature over custody files is later work.

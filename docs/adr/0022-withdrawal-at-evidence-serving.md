# ADR-0022: Evidence serving checks withdrawal before reading stored bytes

- Status: Accepted
- Date: 2026-09-05
- Deciders: Exulanica build, during the unblocked backend program review

## Invariant

After workspace authorization, every evidence entrypoint checks the canonical
`tombstone_blocks_span` predicate over the stored evidence address before reading original
bytes or making a region image. A covered address returns HTTP 410 while asynchronous purge
is pending, even when the content-addressed store still holds every original byte. A foreign
or nonexistent span remains HTTP 404. Original, range, region and withdrawal responses use
`Cache-Control: private, no-store` so subsequent requests must revisit the withdrawal boundary.

## Rationale

Restore testing exposed an existing serving gap: the evidence routes authenticated the owner
and verified the address, but never asked whether that address had been withdrawn. A physically
purged original returned a missing-object error; before purge, the same tombstoned original was
still delivered. Original media, region crops and permalink resolution shared the omission.
An asynchronous erasure schedule must not decide whether a committed withdrawal is visible.
The former one-hour private cache lifetime also allowed clients to reuse responses without
checking for a withdrawal during that interval.

## Canonical representation

Both evidence queries return a `withdrawn` Boolean computed by the existing database predicate
from `(workspace_id, blob_sha256, track_key, t_start_ns, t_end_ns)`. This preserves the evidence
address and the established half-open interval and deliberate-reimport rules. It adds no new
copy of the deletion policy in Python. HTTP 410 carries `evidence was withdrawn`; no stored
media bytes are read on that branch.

## Compatibility impact

No schema, migration, address, digest, browser payload or purge-role change. Clients already
handle HTTP 410 for withdrawn resources. Evidence awaiting purge changes from a successful
response to 410; physically absent tombstoned evidence changes from 404 to 410. New successful
responses stop advertising a one-hour private cache lifetime, and 410 responses cannot be
reused after a permitted reimport. Already distributed client copies
are outside server-side revocation.

A foreign workspace retaining the same original content does not make the withdrawing owner's
address readable. An intentional new live capture of the same bytes in the same workspace
continues to release an ordinary capture tombstone under the canonical rule. Hash blocklists
and interval withdrawals retain their stronger, monotonic semantics. An entity withdrawal does
not become a capture deletion: the original-photograph policy is unchanged.

## Failure behaviour

Unknown and foreign addresses are refused before the withdrawal result is revealed. A local
covered address is refused before any original or crop store read, including a range request.
Integrity failures remain integrity failures; neither a missing byte nor a valid digest substitutes
for the withdrawal predicate. The check observes committed tombstones available to its database
query; it does not retroactively cancel responses already delivered.

## Affected surfaces and verification

- API: `exulanica/api/routes/evidence.py`, covering row-id originals, regions and permalinks.
- Tests: `tests/test_evidence_withdrawal.py` covers pre-purge capture, interval and workspace
  withdrawals, foreign shared content, canonical same-workspace reimport, and cache policy.
  `tests/test_restore_replay.py` expects 410 after replay has applied the tombstone.
- Schemas, migrations, workers, exports, deletion machinery and browser representations: unchanged.
- Executed production negative controls and final verification are retained in the program record.

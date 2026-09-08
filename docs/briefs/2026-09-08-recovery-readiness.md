# Establish recovery readiness before retained-data activation

Status: proposed, not dispatched. Repository: /Users/glendonchin/dev/Technology/orimera.
Baseline: pushed main 46e106b. Product and package: Exulanica.
Create a separate worktree /Users/glendonchin/dev/Technology/exulanica-recovery-readiness on
codex/recovery-readiness from current main. Reuse an existing matching task/worktree only after
checking its scope and state. Migration: NONE. Do not allocate or modify migrations.

## Outcome

Produce a source-grounded recovery inventory and a concrete, reviewable drill/activation brief.
This is an assessment task, not authorization to back up private data or activate the deployment.
Git main is pushed. That does not back up the database, local objects, secrets, or other branches.
The last independently observed retained public schema was 0038 with 284 captures, 880 artifacts,
5 scenes and zero person regions. Treat this as a dated observation, not a fresh measurement.

Read applicable AGENTS.md, docs/deployment.md, docs/runtime-verification.md,
docs/integration-consent-timestamp-2026-09-08.md, docs/integration-asset-read-currency-2026-09-08.md,
compose.yaml, exulanica/db/migrate.py, exulanica/db/session.py, exulanica/deletion/restore.py,
exulanica/deletion/worker.py, exulanica/store/local.py, tests/test_restore_replay.py,
tests/test_deployment.py, and migrations 0036 through 0041. Follow their actual callers.
The restore test already executes pg_dump and restoration with deletion replay. Do not report
that restore machinery is absent, or equate fixture recovery with deployment recovery.

## Ownership

Only writable repository files:
- New docs/recovery-readiness-2026-09-08.md.
- New docs/briefs/2026-09-08-isolated-recovery-drill.md.
- New docs/briefs/2026-09-08-retained-activation.md.

All other files are read-only, including README.md, existing deployment documents, historical
evidence, runtime code, tests, migration files, and configuration. The separate README task owns
its work; do not edit, rebase, or integrate it. No database writes, full suites, dump/copy of
retained personal data, checkpoint sealing, restore, cloud provisioning, upload, merge or push.
Inspect only repository/configuration structure and non-sensitive local metadata. Do not print
secret values, enumerate private media contents, or search unrelated personal directories.

## Required findings

1. Inventory actual configured database/object-store/checkpoint boundaries, referencing source
   paths and functions. Distinguish configured, documented, tested on generated fixtures, and
   executed against retained data. Mark destinations or schedules unknown when evidence is absent.
2. Explain a coherent database/object snapshot procedure and how writers and purge workers are
   quiesced. Read checkpoint() before proposing its use: it seals the source and is not read-only.
   Account for deletions after a backup, the independently retained authoritative checkpoint,
   replay roles, startup refusal, and recovery when the original host is lost before a fresh
   checkpoint can be made. Identify any missing durable deletion history honestly.
3. Specify off-device destinations, retention, key custody, recovery point/time objectives,
   verification and operator inputs as decisions, not invented infrastructure facts. Keep private
   backups and credentials out of this public Git repository.
4. Draft an isolated drill using the existing machinery: uniquely named source and restore
   databases/stores, generated media first, exact compatible PostgreSQL tools, role setup,
   checksum manifests, current deletion replay, interrupted replay refusal, corrupt/missing
   object refusal, and authenticated reads after recovery. Document ownership and cleanup.
   Distinguish a fixture drill from an eventual separately authorized retained-data recovery.
5. Draft activation in explicit phases: operator-approved retained backup, isolated recovery,
   rehearsal of the actual 0038-to-0041 upgrade, evidence review, then separately authorized
   retained migration and smoke checks. Existing 0039-0041 are committed migrations, not new
   numbers to assign. Specify rollback/recovery boundaries without assuming reverse migrations.
   Address roles, writer contention/retries, workers, readiness and expected legacy refusals.
6. Return exact writable sets, proposed branch/worktree, migration NONE, suite/DB slot needs,
   executed acceptance criteria and concrete approval checkpoints for the next drill task.
   If new runtime work is indispensable, identify the smallest file/function gap before asking
   for implementation. Do not manufacture a broad backup framework by default.

Validate paths, commands against their help/source, and document contradictions with citations.
Do not run a command with side effects merely to check its help. No full-suite slot is needed
for this read-only assessment. Report what was inspected and what remains unexecuted.
Use one-line imperative commits without trailers, authorship notices or em dash characters.
Stage explicit files. Return branch/tip, findings and the two scoped successor briefs; do not merge.

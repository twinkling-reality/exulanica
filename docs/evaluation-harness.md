# Evaluation harness: clean replay and run archives

Status: **REPLAY MECHANICS AND ARCHIVES IMPLEMENTED; REAL OGC-1 BASELINE AND THE PHASE 2 GATE
REMAIN BLOCKED**.

Two halves of one shipped command, merged 2026-09-09 from `evaluation-clean-replay.md` and
`evaluation-run-archive.md`. They were separated only by history: both describe
`exulanica-eval`, both turn on the same Phase 2 exit gate, and neither was linked from anywhere in
the repository, so a reader had no way to find one from the other. Nothing below is edited except
the headings.

## 1. Clean replay

`exulanica-eval replay-bundle` admits only an already validated `CORPUS.json` bundle. It does not
create photographs, labels, consent evidence, partitions, or scores. It uses two explicit database
identities:

- `EXULANICA_EVALUATION_OWNER_DATABASE_URL` points to a newly created empty database and is used only
  to check emptiness, apply forward migrations, and provision one workspace partition; and
- `EXULANICA_DATABASE_URL` points to the same database as a non-owner runtime role without
  `BYPASSRLS`.

The command does not create or drop a database. It refuses `postgres`, `template0`, `template1`, a
current schema other than `public`, any non-system schema besides `public`, or any pre-existing user
relation. An attempted replay consumes the empty database once migrations begin, including when a
later input or runtime check fails; retry with another new database rather than erasing evidence.

Example blind replay:

```bash
export EXULANICA_EVALUATION_OWNER_DATABASE_URL='postgresql://owner:...@host/exulanica_eval_001'
export EXULANICA_DATABASE_URL='postgresql://exulanica_app:...@host/exulanica_eval_001'

uv run exulanica-eval replay-bundle \
  --corpus /private/OGC-1 \
  --purpose blind_evaluation \
  --blind-key-file /private/keys/ogc-1-blind.key \
  --actor evaluation-operator-01 \
  --access-audit /private/evaluation/audits/ogc-1-run.jsonl \
  --data-dir /private/evaluation/runtime/ogc-1-run \
  --archive-parent /private/evaluation/archives
```

The blind key is read from a file so it does not appear in shell history or process arguments. The
access audit path must not exist; the command will not append to an earlier proof. The default path
runs the live model-manifest preflight before creating a client. `--offline` is accepted only for an
explicitly synthetic contract test and is refused for a real bundle.

The replay performs two passes over the authorized split. The first runs the actual ingest pipeline.
The second must resolve existing artifacts and make zero additional model calls. The archive retains
the metadata and label files, never source media; access audit; clean-database proof; applied
migrations; stage definitions; attempts; ordered model ids tried; actual provider-reported cost;
reuse events; artifacts; and source coverage. Extra files in the corpus inventory are refused, which
prevents source media from being smuggled into the metadata archive.

The machine record contains a `phase_2_exit_gate` object. It stays blocked for a synthetic bundle, a
development rather than blind split, unsafe runtime role, ingest failure, replay model call, missing
source run, or incomplete metric baseline. Today `metric_baseline_complete` is false because the
new L0-L11 bundle has not yet been connected to every baseline scorer. That is a named remaining
implementation gap, and no successful mechanical replay is reported as the OGC-1 baseline.

## 2. Run archives

A report archive is one application write-once directory named by a run UUID. The evaluator creates
the directory exclusively, writes each member once, writes `MANIFEST.json` last, and makes the files
read-only. A second run with the same UUID is refused. The manifest inventories the exact byte count
and SHA-256 of every member and commits the manifest metadata and inventory to one root SHA-256.

This is not WORM storage and is not described as tamper-proof. A host administrator can change an
ordinary filesystem. Verification detects replacement only when the root printed at creation was
retained separately and supplied to the verifier:

```bash
uv run exulanica-eval verify-archive \
  --archive /evaluation/runs/00000000-0000-0000-0000-000000000000 \
  --root-sha256 <root printed when the archive was created>
```

The archive includes:

- the human report and `exulanica.evaluation-run/v1` machine record;
- the exact corpus manifest bytes used by the legacy evaluator;
- the full clean Git commit and tree ids; a dirty checkout is refused;
- the exact model-manifest bytes and SHA-256, every primary and fallback model id, and explicit null
  revisions because the configured serverless provider exposes no model revision;
- the reviewed current stage definitions, versions, parameters, parameter digests, and supplied
  run-time bindings;
- the exact packaged migration filenames and checksums;
- the applied migration rows actually present in the measured database;
- pipeline runs and events joined by the frozen source SHA-256 set; and
- artifacts, actual durations, attempts, retry and reuse counts, model references, and provider- or
  stage-reported costs.

Missing usage remains null. It is never estimated. Host names and error-message text are replaced by
SHA-256 values in the archive; their identity and presence remain comparable without exporting those
private strings. Migration 0019 records the ordered model identifiers tried by new model-backed
terminal events. Historical rows and a model call that fails before returning its attempt metadata
remain null, and the execution summary names those events with
`model_attempt_provenance_complete = false`; it does not reconstruct them from today's manifest.

The existing `run` command can create this archive with `--archive-parent`. That path still reads the
old synthetic `MANIFEST.json` format, so its record explicitly has no split, blind-access receipt, or
gold question fixture and cannot pass Phase 2. It exists to preserve and verify the measurements the
current harness can genuinely make while the real `CORPUS.json` bundle is unavailable.

The Phase 2 exit gate additionally needs a clean-database replay from the real OGC-1 split bundle.
No archive format can substitute for those absent inputs.

## 3. What still blocks Phase 2

Both halves end at the same place and it is worth stating once rather than twice. The exit gate
needs a clean-database replay from the real OGC-1 split bundle, and that bundle does not exist yet.
`metric_baseline_complete` is false because the L0-L11 bundle is not connected to every baseline
scorer. No archive format substitutes for an absent input, and no successful mechanical replay is
reported as the OGC-1 baseline.

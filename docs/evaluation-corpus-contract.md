# Evaluation corpus contract

This contract owns the boundary between private, user-authorised evaluation inputs and
`exulanica-eval`, the command that measures them: what an evaluation bundle must hold, how its
splits are read, how a clean replay admits it, and how a run archive is written and verified. The
metrics themselves are [evaluation methodology](evaluation-methodology.md)'s.

The repository holds synthetic contract fixtures. It does not hold an OGC-1 bundle, and none exists:
no OGC-1 metric, baseline or split claim exists, and the synthetic corpus is not a substitute for
one. The contract creates no corpus, consent record, label, split or result.

<details>
<summary>Sections</summary>

- [Commands](#commands)
- [Directory contract](#directory-contract)
- [Split access and the honest boundary](#split-access-and-the-honest-boundary)
- [Clean replay](#clean-replay)
- [Run archives](#run-archives)
- [What the exit gate still needs](#what-the-exit-gate-still-needs)

</details>

## Commands

| Command | What it does |
| --- | --- |
| `exulanica-eval inspect-corpus --corpus <dir>` | Validates a bundle's metadata and hashes without opening source media |
| `exulanica-eval replay-bundle` | Admits a validated bundle into a clean database and writes a run archive (section [Clean replay](#clean-replay)) |
| `exulanica-eval questions --corpus <dir> --out <file>` | Freezes synthetic gold questions from a synthetic corpus's `MANIFEST.json` |
| `exulanica-eval run --corpus <dir> --workspace <uuid>` | Measures what can be measured against a synthetic corpus; `--archive-parent` also writes a run archive |
| `exulanica-eval verify-archive --archive <dir> --root-sha256 <root>` | Verifies a run archive against its separately retained root |

A bundle's source directory is deliberately outside Git. The repository's contract tests create
temporary non-photographic fixtures; those prove validation and access behaviour only and are never
reported as OGC-1.

## Directory contract

An evaluation bundle has this shape. File names below are conventional except for the three names
shown in capitals, which are fixed.

```text
OGC-1/
  CORPUS.json
  SPLITS.json
  CONSENT-INDEX.json
  labels/
    L0.json
    L1.json
    L2.json
    L4.json
    L5.json
    L6.json
    L7.json
    L8.json
    L9.json
    L10.json
    L11.json
  media/                         # private and never committed
```

`CORPUS.json` has profile `exulanica.evaluation-corpus/v1`. It declares an opaque corpus id, an
explicit `synthetic` boolean, the split and consent index paths, exactly the label layers defined by
[evaluation methodology](evaluation-methodology.md#13-label-layers), and a SHA-256 inventory of
every contract and label file. It does not inventory itself because a file cannot contain its own
digest. The corpus version is the canonical SHA-256 of `CORPUS.json` plus its sorted inventory.

`SPLITS.json` has profile `exulanica.evaluation-splits/v1`. Each item has:

- an opaque `item_id`;
- component `travel` or `room`;
- split `train`, `development`, or `blind`;
- SHA-256 of the original source bytes;
- a relative private source path;
- opaque subject ids; and
- opaque consent record ids.

All three splits must exist. A source digest may occur once only. A subject appearing in the blind
split may not appear in train or development. `OGC-1/room` must be people-free. The split manifest
also stores the SHA-256 of an external blind-access key; the key itself stays outside the bundle and
Git.

`CONSENT-INDEX.json` contains no signature, name, email, phone number, or consent document. It maps an
opaque consent record id to the SHA-256 of the private record, an opaque subject id, and the exact
granted scopes. A real travel item with an identifiable subject is refused unless its consent index
covers `capture.retain_media`, `biometric.face_template`, and
`biometric.cross_capture_link`. Public-demonstration scopes remain required by the privacy policy for
anything actually shown publicly; an evaluation run alone does not manufacture or imply them.

L0 must enumerate exactly the source digests in `SPLITS.json`. The remaining layer documents are
frozen files whose detailed contents follow the methodology's label layers. The evaluator does not
infer missing labels from model output.

## Split access and the honest boundary

Source paths are exposed only by a purpose-scoped reader:

| Purpose | Visible split |
| --- | --- |
| `training` | train |
| `tuning` | development |
| `development_evaluation` | development |
| `blind_evaluation` | blind, with the external key |

Each opened source is re-hashed and appended to a hash-chained JSONL access audit. A completion event
commits the exact item set. The versioned evaluation record retains the audit digest and can prove
that no mediated training or tuning read opened a blind item.

This is an application access control, not an operating-system isolation claim. A host administrator
who can read the private directory can bypass it. A deployment that needs stronger separation must
run training and blind evaluation under different operating-system or cloud identities and give the
training identity no permission on the blind prefix. No such identity or account is chosen.

## Clean replay

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
later input or runtime check fails; retry with another empty database rather than erasing evidence.

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
the metadata and label files, never source media; the access audit; the clean-database proof; the
applied migrations; stage definitions; attempts; the ordered model ids tried; actual
provider-reported cost; reuse events; artifacts; and source coverage. Extra files in the corpus
inventory are refused, which prevents source media from being smuggled into the metadata archive.

The machine record contains a `phase_2_exit_gate` object, the gate a real OGC-1 baseline must pass.
It stays blocked for a synthetic bundle, a development rather than blind split, an unsafe runtime
role, an ingest failure, a replay model call, a missing source run, or an incomplete metric baseline.

## Run archives

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
- the exact corpus manifest bytes used by the `MANIFEST.json` evaluator;
- the full clean Git commit and tree ids; a dirty checkout is refused;
- the exact model-manifest bytes and SHA-256, every primary and fallback model id, and explicit null
  revisions because the configured serverless provider exposes no model revision;
- the reviewed stage definitions, versions, parameters, parameter digests, and supplied run-time
  bindings;
- the exact packaged migration filenames and checksums;
- the applied migration rows actually present in the measured database;
- pipeline runs and events joined by the frozen source SHA-256 set; and
- artifacts, actual durations, attempts, retry and reuse counts, model references, and provider- or
  stage-reported costs.

Missing usage remains null. It is never estimated. Host names and error-message text are replaced by
SHA-256 values in the archive; their identity and presence remain comparable without exporting those
private strings. Migration 0019 records the ordered model identifiers tried by model-backed terminal
events. Rows written before it, and a model call that fails before returning its attempt metadata,
remain null, and the execution summary names those events with
`model_attempt_provenance_complete = false`; it does not reconstruct them from the archive's manifest.

`exulanica-eval run --archive-parent` writes the same archive format from a synthetic
`MANIFEST.json` corpus, so its record has no split, blind-access receipt or gold question fixture and
cannot pass the exit gate. It preserves and verifies the measurements the harness can genuinely make
without a real bundle.

## What the exit gate still needs

The exit gate needs a clean-database replay of a real OGC-1 split bundle, and that bundle does not
exist: it must describe real inputs, with its private source media readable locally, its consent
records kept outside Git, and the blind-access key given only to the evaluation operator.
`metric_baseline_complete` is false because the L0 to L11 bundle is not connected to every baseline
scorer, and no successful mechanical replay is reported as the OGC-1 baseline. No archive format
substitutes for an absent input.

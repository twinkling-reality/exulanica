# Evaluation corpus contract

Status: **IMPLEMENTED INPUT BOUNDARY; REAL OGC-1 INPUTS NOT FOUND LOCALLY 2026-08-31**.

This contract is the boundary between private, user-authorised evaluation inputs and the code that
measures them. It does not create a corpus, a consent record, a label, a split, or a result. The
command below validates metadata and hashes without opening source media:

```bash
uv run exulanica-eval inspect-corpus --corpus /private/path/to/OGC-1
```

The source directory is deliberately outside Git. The repository contains contract tests that
create temporary non-photographic fixtures; those fixtures prove validation and access behaviour
only and are never reported as OGC-1.

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
`evaluation-methodology.md`, and a SHA-256 inventory of every contract and label file. It does not
inventory itself because a file cannot contain its own digest. The corpus version is the canonical
SHA-256 of `CORPUS.json` plus its sorted inventory.

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
frozen files whose detailed contents follow `evaluation-methodology.md` section 1.4. The evaluator
does not infer missing labels from model output.

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
run training and blind evaluation under different OS or cloud identities and give the training
identity no permission on the blind prefix. No such cloud identity or account is chosen here.

## Local discovery result and blocker

The requested local discovery searched the Exulanica checkouts and private `.orimera` state, the
project tree, Desktop, Documents, Downloads, Pictures, Codex attachments, and mounted volumes by
file and manifest name. It found:

- the generated `orimera-corpus` geometric fixture, explicitly marked synthetic;
- its `MANIFEST.json`;
- local copies used to exercise ingestion; and
- an unsigned consent-form template.

It found no OGC-1 `CORPUS.json`, L0-L11 label bundle, signed consent evidence, blind fixture, or dense
people-free room capture. Therefore no OGC-1 metric, baseline, split claim, reconstruction quality
claim, or Phase 2 exit-gate claim exists.

The external input needed to unblock the gate is one bundle satisfying this document, with its
private source media readable locally, consent records retained outside Git, and the blind access key
provided only to the evaluation operator. The bundle must describe real inputs; the synthetic corpus
is not an acceptable substitute.

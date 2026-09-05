# ADR-0020: Gold answers precede retrieval; model and declared-plan measurements stay separate

- Status: Accepted
- Date: 2026-09-05

## Invariant

Synthetic gold photo sets are derived only from `MANIFEST.json`: absolute capture instants,
object placements and place membership. They are never intersected with returned or ingested
rows. A loader binds the exact manifest bytes and re-derives the complete question document,
refusing altered gold even when someone rewrites the question file consistently. The public
scorer also re-derives gold, so constructing a question object cannot bypass the loader's check.
Evaluation requires every corpus photo exactly once in the workspace and no unrelated captures. A partial
or mixed corpus blocks the question components. A bounded result is a page and fails the full-set
diagnostic; it cannot disappear from the denominator. Its deterministic answer may still pass
grounding by stating the correct total and citing a gold subset, whose completeness is not claimed.

## Rationale

A generated plan cannot test a model planner. A deterministic answer cannot test live-model
factual support or latency. The existing M8 plan-validity component now explicitly measures
declared gold plans; a separate blocked M8 model-plan component preserves the unmeasured claim.
The validity denominator is three stage checks per executable question, with each stage recorded
separately; it is not a count of natural-language queries accepted by a model.
M1 answer grounding checks the deterministic answer's rendered count clause and value references,
historical clause tokens and gold photo addresses, and the empty-set abstention producer's actual
returned answer and reason. The count check pins the deterministic template; it does not infer
arbitrary prose semantics from the packet's unused count. It does not judge arbitrary natural-language
claims. Object appearance queries use the manifest's first appearance phrase: misses can come
from detector captions or this vocabulary as well as retrieval. They are a named pipeline
diagnostic, not identity accuracy. Places need human-confirmed entity IDs and remain unexecuted;
no evaluation code performs a user-class decision. P-1 and the person metrics stay blocked.

## Canonical representation

`exulanica.synthetic-gold-questions/v1` includes an explicit synthetic flag and `SYNTH-1` label,
the SHA-256 of the exact manifest bytes, and questions containing stable IDs, natural-language
text, context keys, answerability, sorted gold photo hashes, gold counts, optional declared plans
and a blocker for an unexecutable question. The question document's digest uses `canonical_json`.
The retained fixture is the seed-20260905, three-frames-per-trip synthetic corpus. Its manifest
contains no personal media. The generation rule is fixed before querying the product.

## Compatibility impact and failure behaviour

Existing metric IDs remain, while M8 plan validity is explicitly narrowed and new components are
added. `SCORED` and the unblocked registry change together. Reports refuse a number for either a
statically blocked component or a component blocked in this run. No model calls are introduced.
Invalid gold raises before scoring. Failed question stages are reported with evidence; missing
captions produce observed retrieval failures, never a gold-set adjustment.

## Affected surfaces

- Evaluation: question derivation/loader, question scorers, registry, report and CLI archive.
- Tests: `tests/test_gold_questions.py` and the retained manifest/question fixture.
- Schemas, migrations, APIs, workers, exports, deletion paths and browser consumers: unchanged.

## Reproduction

Generate the same synthetic corpus with `exulanica-corpus --seed 20260905 --frames-per-trip 3`.
Freeze with `exulanica-eval questions --corpus CORPUS --out QUESTIONS.json`, then pass
`--questions QUESTIONS.json` to `exulanica-eval run` against a fully ingested isolated workspace.
For the retained offline experiment, `scripts/measure_gold_questions.py --corpus CORPUS --out OUT`
creates a temporary migrated schema, ingests the real generated files with vision omitted, runs
the CLI and saves its report and per-question observations. The script refuses any database other
than `postgresql://localhost:5433/exulanica_spine_test` and must run with the exclusive test slot.
The archived run stores the complete gold document and per-question plans, answers and citation
photo mappings. Declare any omitted or scripted vision stage next to its results. With no
`NEBIUS_API_KEY`, M2, M3, M13 and model-planner validity remain blocked; OGC-1 does not exist.

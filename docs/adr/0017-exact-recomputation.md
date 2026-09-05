# ADR-0017: "Exact recomputation" excludes model-produced artifacts, and says so in the type

- Status: Accepted
- Date: 2026-09-04
- Deciders: Exulanica build

## Context

`docs/domain-and-evidence-model.md` section 6, `docs/product-specification.md` section 9 and
`docs/evaluation-methodology.md` all carry the same decision: the words "unlearning", "forgetting"
and "the model has forgotten" are banned, and the truthful phrasing is *removed from retrieval and
from future training, with every derived artifact recomputed from the remaining data*. All three
then add that because there are no trained weights at MVP, "that recomputation is exact by
construction", and call it a stronger claim than the approximate-unlearning literature can support.

The claim about the literature is verified and stands. **The claim about this system was scoped too
widely**, and the audit found the contradiction sitting in the codebase in plain sight:

- `exulanica/ingest/stages/__init__.py` declares `deterministic = False` for `vision` and `depth`,
  with the reason written out: sampled generation, and a neural forward pass that differs across
  accelerators and library versions;
- so re-running either stage produces a **different artifact**, not the same bytes;
- and A-24, "deleting an exemplar and recomputing yields a bit-identical state", was recorded
  without that exclusion, with only the general instruction that "any nondeterminism must be
  eliminated, or the exact-recomputation claim must be weakened".

Nondeterminism in a sampled generation cannot be eliminated. So the claim has to be weakened, and
the useful question is where exactly the boundary falls.

A third case turned up while drawing it. `scene_pose` declares `deterministic = True`, and
`exulanica/reconstruction/pycolmap_executor.py` says in its own module docstring that fixing
COLMAP's `random_seed` "is necessary for that and is not sufficient: RANSAC threading still admits
variation, and how much has not been measured". Both statements are correct, because the flag and
the claim are different statements.

## Decision

### 1. What `deterministic` declares

`deterministic = True` declares that **a content difference on this stage is a fault worth an
event**. That is what the flag drives: `persist_artifact` emits `nondeterminism_detected` for a
deterministic stage and stays quiet for a non-deterministic one, so a changed resampling filter is
reported and a resampled generation is not.

It is **necessary for** an exact-recomputation claim and is not the same as one. Only a stage that
is both declared deterministic **and observed to reproduce** may be described as exactly
recomputable. `scene_pose` is declared and not yet observed; that is a limitation, not a defect, and
it is recorded rather than rounded off in either direction.

### 2. A stage with a `model_role` may not be deterministic, enforced in the type

`StageSpec.__post_init__` raises if a stage names a model role and declares itself deterministic.
The exclusion therefore cannot be lost by editing a flag, and a new model-backed stage inherits it
without anyone remembering to. `dataclasses.replace` is covered too, because it re-runs
`__post_init__`.

### 3. What may be said about deletion of a model-produced artifact

Not "recomputed identically". The truthful and narrower statement, which is what the system
actually does:

> **It is invalidated and removed, not regenerated.**

`derived_artifact.stale` is set through the `dep_index` GIN index by
`exulanica/identity/recomputation.py`, and no deletion path re-runs a model. Nothing about the
account holder survives inside a caption, because the caption is gone rather than rewritten. That is
a complete answer to the question a person is actually asking, and it does not need the stronger
claim.

### 4. A-24 is narrowed, not dropped

A-24 now reads: deleting an exemplar and recomputing the **deterministic closure** yields a
bit-identical state, settled by experiment X-8. It may not be made publicly before X-8 passes, and
it may never be made about `vision` or `depth` output at all.

### 5. The banned words stay banned, and this ADR does not try to enforce them by grep

A substring ban over the repository would fail on "forgetting to bump a version" in a code comment
and would push those comments into worse English to satisfy a test. The rule is about what the
product **says about deletion**, and no user-facing string in `exulanica/` or `web/packages/*/src`
uses any of the three phrasings today. The enforceable half of the rule is the one above: the
registry decides which stages may carry an exactness claim, and the document is checked against the
registry rather than trusted.

## Compatibility impact

None. No stage flag changed, no artifact changed, no digest changed, no schema changed. `vision` and
`depth` were already `deterministic = False`; the change is that they now cannot stop being so
quietly.

## Failure behaviour

- Constructing a model-backed stage with `deterministic=True` raises `ValueError` at import,
  naming this ADR.
- A deterministic stage that produces different bytes for one idempotency key emits
  `nondeterminism_detected` and flags the row `needs_repair`, rather than repointing it at bytes the
  identity key does not name.
- A non-deterministic stage that produces different bytes emits nothing.
- A document that stops naming the excluded stages, or names the wrong ones, fails
  `tests/test_exact_recomputation.py::test_the_document_names_exactly_the_stages_the_registry_excludes`.

## What this touches

| Surface | Change |
| --- | --- |
| Workers | `StageSpec` refuses a deterministic model stage; the docstring states what the flag claims |
| Docs | `domain-and-evidence-model.md` section 6 corrected and A-24 narrowed |
| Schema, migrations, APIs, exports, deletion, browser | None |

## Tests

`tests/test_exact_recomputation.py`, including the counterpart the suite was missing: a model stage
that produces different bytes for the same idempotency key must **not** be filed as a fault, because
filing Tuesday as a fault is how a real fault gets ignored.

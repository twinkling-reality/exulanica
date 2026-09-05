# Goal brief: the unblocked backend program

Written 2026-09-05, at commit `ef73866`, immediately after the semantic-answers and
memory-lifecycle goal closed. It exists so the next session starts from a verified map rather
than rediscovering one, and so a fan-out across worktrees does not step on itself.

Every fact below was checked against the tree at `ef73866` rather than against the roadmap. Where
this brief and the code disagree, the code is right and this document is stale: say so and
correct it.

---

## 1. Read these first, in this order

1. `docs/evaluation/2026-09-04-readiness-and-architecture-audit.json`. The confirmed
   architecture, nine contradictions, the eight decisions closed by ADR-0012 through ADR-0017,
   the remaining open invariants, and `record.dependency_order`, which is the authority on what
   comes after what.
2. `docs/evaluation/2026-09-04-semantic-answers-and-memory-lifecycle.json`. The goal that just
   closed. Its `found_by_reviewing_this_goal` block lists ten defects an adversarial review
   found, eight fixed and two disclosed. The two disclosed ones are candidate work and are
   named in section 6.
3. `docs/domain-and-evidence-model.md` sections 2.3, 2.4, 3.5 and 6.4, plus
   `docs/evaluation-methodology.md` section 6 and `docs/evaluation-corpus-contract.md`.
4. ADR-0005 (one Selection primitive), ADR-0014 (digest encodings), ADR-0017 (exact
   recomputation). ADR-0012 through ADR-0016 close the evidence address and are unlikely to be
   touched again.

Do not trust `docs/frontier-roadmap.md` on status. It has uncommitted work in flight (section 7)
and its section 3 understates what exists.

---

## 2. Standing constraints, on every goal in this document

These are not per-goal. Breaking one is a defect regardless of which goal was being worked on.

* **P-1 is unanswered and stays unanswered.** No biometric template may be derived or persisted.
  `tests/test_ingest_preconditions.py` pins this with three assertions: a writer scan over every
  `*.py` and `*.sql` under `exulanica/` (which now matches partition tables, `embedding_ws_<hex>`,
  and quoted and `copy` spellings), a scan of the answer path's packages by name
  (`selection`, `graph`, `store`, `api`) for `\bembedding\b` and `\.embed\(`, and runtime row
  counts after a real ingest and after a real answer. All three must keep passing. Answering P-1
  by adding a feature is the one way it must not be answered.
* **Forward migrations only.** `0001` through `0035` are frozen. A mistake is corrected by a new
  forward file. The runner checksums every migration and the application refuses to boot on
  drift, so editing one is a silent schema fork that surfaces later as a wrong answer.
* **Preserve provenance, privacy, withdrawal and workspace isolation.** Every one of these has
  live machinery and tests; none of them is a slogan.
* **Only `postgresql://localhost:5433/exulanica_spine_test`.** Never `.orimera`, never a
  non-test database.
* **No number against an OPEN evaluation item.** `exulanica/evaluation/metrics.py` carries a
  `blocked_on` sentence per component; a component with one may not have a number published
  against it, in a report or in a retained record.
* **Do not create speculative abstractions without a demonstrated second implementation.** This
  rule did real work in the last goal: it is why no answer is persisted, why
  `Abstention.NOT_IN_MODALITY` still has no producer, and why no shared envelope helper exists
  for the five inline producers of the digest-bound record.
* **Preserve the uncommitted work.** See section 7.

---

## 3. What is blocked, and why no model can unblock it

Do not start these. Each needs something from a person, and attempting them burns a session and
produces work that cannot be accepted.

| Goal | Blocked on |
| --- | --- |
| Production rehearsal | A named person owning the weekly check through the unattended window; a chosen cloud account, project, region and domain; **A-8**, written zero-data-retention confirmation for the exact model identifiers, committed to the repository |
| Rung 2 corridor | An authorized corpus with at least two captures of one place, each with a named human screening receipt over the exact bytes; joint co-registration measured; a metric scale source that is not model-derived |
| A measured Rung 1 decision | Rung 2's pose and coverage measurements over the same corpus; a reviewed Apache-2.0 gsplat path with GPU; a held-out view split defined before training |
| Personal-media ingest | A-8, plus P-1 if any identity work is in scope |
| Video ingest | Everything on the personal-media list, plus the `v:N` `media_track` path |

The three timebase and address items that used to gate video are already closed, in advance, by
ADR-0012 through ADR-0016. That is what removed the time pressure from the day video arrives.

**One exception worth knowing.** Goal C below is listed in the audit under production rehearsal,
whose entry gates are unmet. Its *mechanism* is nonetheless buildable and testable locally
without a cloud account, and building it early is what makes the eventual rehearsal a rehearsal
rather than a first attempt. Take it as its own goal, and do not claim the rehearsal gate.

---

## 4. The program

Four goals. A and C are independent and may run concurrently from the start. B may start
concurrently but two of its metrics land only after A. D wants A merged first.

```
        A  non-biometric match proposals ──┬──► D  exact recomputation (A-24 / X-8)
                                           │
        C  restore with tombstone replay   └──► B  evaluation harness (proposal metrics)
        B  evaluation harness (answer-path half, independent)
```

Recommended order if the fan-out is narrower than four: **A first**, then C, then B, then D.
A is the one the codebase itself names as next, and it makes the largest amount of existing,
well-designed, currently unreachable code live.

---

## 5. The goals

### Goal A. Non-biometric match proposals

**The finding, verified at `ef73866`.** `repository.links.insert` is called from exactly three
places, `exulanica/identity/decisions.py:122`, `:201` and `:438`, and all three pass
`state="confirmed"`. Nothing anywhere writes `proposed` or `auto_provisional`. The `calibration`
table (`0001_spine.sql:377`) has no writer at all, so `assertion.calibrated_p` is permanently
NULL. `exulanica/identity/proposer.py` writes `match_proposal` rows and never a link.

Meanwhile `auto_provisional` is *read* in at least six places: `exulanica/graph/occurrences.py`
carries it in the read model, `exulanica/selection/plan.py` documents it as what
`EpistemicScope.INCLUDE_PROPOSALS` admits, `exulanica/selection/executor.py:_LINK_STATES` widens
on it, and `decisions.py` branches on it twice. So a large, deliberately designed surface can
never fire against a real corpus:

* `EpistemicScope.INCLUDE_PROPOSALS` cannot widen any result.
* `Abstention.AMBIGUOUS`, which fires when a Selection admitted unconfirmed links, is reachable
  only from a test.
* `confirm_link`'s `superseded_proposal` branch, `reject_link`'s transition to `rejected`, and
  `undo`'s restore-to-`proposed` are all unreachable.
* `Recomputation.mark_stale`'s predicate is over `entity:<uuid>` and `occurrence:<uuid>` strings
  that no shipping producer writes, so all eight of its call sites report a confident zero.

`exulanica/identity/decisions.py`'s module docstring names the work exactly, and names its
boundary: "Automatic proposal from non-biometric signals (time proximity, scene grouping, place,
co-occurrence) is the next rung and would write `match_proposal` rows through
`Proposals.record`; face embeddings are a separate decision with legal weight and open item P-1
has not been answered."

**Entry gates, all met.** The evidence address is closed and ratified. The answer path is
complete and cited. The withdrawal cascade reaches forward as of migration 0035. Nothing here
needs a credential, a corpus, a GPU or a decision.

**Exit gates.**

1. A non-biometric signal set produces `match_proposal` rows and, above a stated threshold, an
   `auto_provisional` link, with the signal set and its weights recorded on the proposal.
2. `EpistemicScope.INCLUDE_PROPOSALS` measurably widens a real Selection, and the packet built
   from it is still not citable, which is the existing invariant and must not move.
3. A proposal is confirmed, rejected and undone through the existing decisions, with the
   `superseded_proposal`, `rejected` and restore-to-`proposed` branches each exercised by a test
   that fails when the branch is removed.
4. `Recomputation.mark_stale` is non-vacuous: a confirm, merge or split marks a derived artifact
   stale through a `dep_index` a production writer emitted.
5. `calibration` has a writer and `calibrated_p` is populated, or the decision not to populate it
   is recorded with its reason. Two numbers, never conflated, and `0001_spine.sql:408` states the
   rule that must stay true: `raw_score` is whatever the model emitted and is **never rendered to
   a user and never thresholds a factual claim**, while `calibrated_p` stays NULL until a bin has
   enough observed confirm and reject decisions from this user. A proposal threshold may read
   `raw_score`; nothing a user sees may.
6. No biometric template. `PRODUCIBLE_MODALITIES` in `exulanica/identity/keys.py` is
   `frozenset({'context_place', 'context_cooccurrence', 'user_text'})` and that is the whole
   permitted signal vocabulary.

**Watch for.** `user_text` is currently dormant: `corroborating_modalities` takes
`annotation_text: Sequence[str] = ()` and no caller passes it, so its weight branch never fires.
Any measured claim about proposal quality has to say so. `confirmed_needs_a_human` refuses a
confirmed link without a `decided_by` and `method = 'user_confirm'`, enforced by a database
trigger; an automatic path must produce `auto_provisional` and must not be able to reach
`confirmed`.

**Affected surfaces.** `exulanica/identity/` (proposer, proposals, links, decisions, signals,
keys, undo, recomputation), `calibration` and `match_proposal` and `entity_link` in the schema, a
forward migration if `calibration` needs one, `exulanica/graph/occurrences.py`,
`exulanica/selection/executor.py`, `exulanica/api/routes/identity.py`, and
`web/packages/graph-client` if the read model gains a field.

---

### Goal B. The evaluation harness and a gold question set

**The finding.** `exulanica/evaluation/metrics.py` names the absence of a question set as the
blocker five times, for `M2.hallucination_rate`, both `M3` components, `M8` plan validity and
semantic accuracy, and `M13.answer_latency`. `exulanica/evaluation/scorers.py` exports exactly
four scorers: `score_citation_identity`, `score_provenance_completeness`,
`score_capture_time_windows`, `score_authorisation`. None of them touches an `Answer`, a clause,
an abstention or a citation token.

The synthetic corpus is richer than it looks and is enough to build against. `FramePlan` in
`exulanica/corpus/plan.py` carries `trip_key`, `place_key`, `subject_placements` (subject key,
position, rotation), `utc_instant` as the truth rather than what the file claims, `gps_e7`, and
`exif_orientation`. Subjects are objects, not people, so a question set over them does not
approach P-1.

**The hard constraint, and it is a weld.** `tests/test_evaluation.py::test_a_row_that_carries_no_sentence_is_a_row_something_scores`
asserts `{c for c in METRICS if c.blocked_on is None} == set(SCORED)`, where `SCORED` lives in
`exulanica/evaluation/cli.py:67` and currently holds four entries. Clearing `blocked_on` on any
component **requires** adding a scorer that produces a result for it, in the same change. The
test exists because a row that claimed to be runnable while nothing scored it rendered as the
literal line `NOT MEASURED: None`.

**Exit gates.**

1. A gold question set over the synthetic corpus, with its answers derived from the corpus
   manifest rather than from a run of the system, and a loader for it.
2. Scorers for the components whose `blocked_on` is cleared, with the weld above kept green.
3. Every number labelled with the corpus that produced it. The corpus is synthetic; OGC-1 does
   not exist; `docs/evaluation-corpus-contract.md` records that no CORPUS.json, label bundle,
   consent evidence or blind fixture is present. A synthetic retrieval number is a real number
   about the compiler and the SQL and is not a product claim.
4. The live-model half (`M2`, `M3`, `M13`) needs `NEBIUS_API_KEY`. If it is absent, leave those
   components blocked and say so; do not lower the bar to make them runnable.

**Do not.** Do not write a person-recall metric. `M4` and `M5` are blocked on P-1 and
`metrics.py` already records that as the right answer.

---

### Goal C. Restore with mandatory tombstone replay (X-12)

**The finding.** `X-12` is recorded OPEN and never rehearsed. The property is that a restore from
a pre-deletion backup must not resurrect deleted data: the instance replays every tombstone
before serving, and refuses traffic until replay completes.

This is the one goal whose *listed* gate is unmet (it sits under production rehearsal) and whose
*mechanism* needs nothing external. Build and test it locally. Do not claim the rehearsal gate,
and do not deploy anything.

**Exit gates.**

1. A replay path that applies every committed tombstone to a restored database, idempotently, and
   records that it ran.
2. The instance refuses traffic until replay completes. `exulanica/api/app.py`'s `_lifespan`
   already refuses to serve a schema it does not recognise and is where this belongs; the
   existing `verify_schema` refusal is the model to follow.
3. A test that restores a state containing a tombstoned capture and asserts the bytes, the spans,
   the derived artifacts and the graph rows are all absent afterwards, and that a partial replay
   leaves the instance refusing rather than serving.
4. The purge role's privileges are unchanged. `exulanica/db/roles.py` grants the purger one
   privilege nothing else has, and the runtime holds no DELETE at all.

---

### Goal D. Exact recomputation over the deterministic closure (A-24 / X-8)

**The finding.** ADR-0017 narrowed the exactness claim to the deterministic closure: a stage
carrying a `model_role` may not declare itself deterministic, enforced in
`StageSpec.__post_init__`, and a model-produced artifact is invalidated and removed rather than
regenerated. The narrowed claim is still unvalidated.

Wants goal A merged first, because A is what makes `Recomputation.mark_stale` operate on rows a
production writer emitted, and this goal is about what recomputation produces.

**Exit gates.**

1. Deleting an exemplar and recomputing the deterministic closure yields a bit-identical state,
   demonstrated over the synthetic corpus, or the ways in which it does not are recorded.
2. The claim is scoped: it may never be made about `vision` or `depth` output at all.
3. The related open item `scene-pose-residual` (COLMAP RANSAC threading admits variation beyond
   the fixed `random_seed`, and how much has not been measured) is either measured by comparing
   pose receipt digests across two runs, or left open with the reason. It needs the `pose` extra.

---

## 6. Two findings the last goal disclosed rather than fixed

Both are recorded in `found_by_reviewing_this_goal` in the semantic-answers record. Either is a
legitimate small goal; neither is urgent.

* **The embedding writer scan cannot follow composed SQL.** It is a text scan, and
  `sql.SQL("insert into {}").format(sql.Identifier("embedding"))` is the idiom
  `exulanica/db/roles.py` is written in. The scan is a tripwire on the ordinary spelling, not a
  proof. A trigger refusing every insert would be spelling-independent and would also break the
  purge path's only test, which has to create a row in order to delete one. If this is taken up,
  that tension is the design problem.
* **The 429 and 502 model responses echo the raw exception string**, so a budget refusal states
  this instance's spend, its ceiling and the environment variable that sets them. It is the
  convention every other handler in `app.py` follows, including the integrity failure that echoes
  span ids and digests, and the caller is an authenticated workspace owner. Changing it is a
  decision about the whole error surface rather than about one handler.

---

## 7. Coordination, and hazards measured first-hand

The last session ran two multi-agent workflows against this repository. Everything in this
section was observed, not anticipated.

* **One test database, and concurrent runs corrupt each other's results.** Every suite here uses
  `postgresql://localhost:5433/exulanica_spine_test`. Two agents running `pytest` at the same
  time produced six failures in `tests/test_ingest_cli.py` that vanished on a quiet machine.
  A green run means nothing unless it was the only run in flight. Either **serialize every
  verification run**, or give each worktree its own database and set
  `EXULANICA_TEST_DATABASE_URL` per worktree. Serializing is simpler and was the fallback that
  worked.
* **Migration numbers collide across worktrees.** `0035` is taken. If two worktrees each add a
  migration they will both reach for `0036` and the merge is a silent schema fork of exactly the
  kind the checksum machinery exists to prevent. **Assign number ranges up front**, one block per
  worktree, before any of them writes SQL.
* **Sweep for agent leftovers before every commit.** Review agents left, in the working tree: a
  **modified historical migration** (`0030`, which violates the forward-only rule), a stray
  `0036_zzz_scratch_broaden_cascade.sql`, and `tests/test_zzz_scratch_finding15.py`. All three
  were caught, two of them by tests written in that same session. Run `git status --short` and
  `git diff --stat <base> HEAD -- exulanica/migrations/` before committing, every time.
* **The uncommitted work must survive.** At `ef73866` the tree carries in-flight edits to
  `README.md`, `docs/frontier-roadmap.md`, `docs/demo-runbook.md`, `web/README.md` and
  `web/packages/landing/**`, including a deleted `ladder-figure.ts`, `manifesto.ts` and
  `method.ts` and an untracked `purpose.ts`. It is deliberate and belongs to someone else. Do not
  edit, stage, stash or "tidy" any of it. Stage files by name, never `git add -A`.
* **`pytest -q` swallows the summary line** through a pipe in this repository. Run plain
  `uv run pytest` when the pass count matters.

---

## 8. Verification, and what green looks like

Run all of it. The counts below are the state at `ef73866`, on a quiet machine.

```bash
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest
```

```bash
uv run ruff check . && uv run lint-imports
```

```bash
cd web && pnpm run typecheck && pnpm run boundaries && pnpm run test
```

| Gate | At `ef73866` |
| --- | --- |
| Backend | 1479 passed, 2 skipped, 3 warnings (1481 collected) |
| ruff | clean |
| Import contracts | 4 kept, 0 broken |
| Web | 87 files, 670 tests, typecheck and boundaries clean |
| Migrations | `0001` through `0035`; `0001` through `0034` byte identical to `1623219` |

`uv run lint-imports` is exhaustive: a new top-level package absent from the contract breaks the
build and names itself. That is deliberate.

---

## 9. What every goal owes at the end

Follow the shape the last two goals used, because the tests over `docs/evaluation/` enforce most
of it automatically.

For every decision, state the **invariant**, the **rationale**, the **canonical representation**,
the **compatibility impact** and the **failure behaviour**; identify affected schemas,
migrations, APIs, workers, exports, deletion paths and browser consumers; add focused tests that
fail when the invariant is violated; and make only the bounded changes that make the decision
durable.

**Every test needs an executed negative control.** Mutate the production code so the invariant is
violated, watch the test fail, revert. Do not reason about whether it would fail. The last
session found by this method that a digest check had never been observed to fire, that an
embedding row count could not fail because the table had no partition, and that a chosen probe
digit was one the old rule already caught.

**Retain a record** under `docs/evaluation/` in the `exulanica.digest-bound-record/v1` envelope:
`{"profile": ..., "record": {...}, "record_sha256": sha256(canonical_json(record)).hexdigest()}`.
Bind it by digest to its predecessor. State which corpus produced every number, and distinguish
plumbing exercised from accuracy measured. `canonical_json` refuses floats, so quantise to
integers first. `tests/test_retained_evaluation_records.py` validates every file in that
directory the moment it lands, and several of its checks were added specifically because a record
was checking itself against its own literals rather than against the repository.

**Commit in small independently green commits.** One decision per commit where the decisions
separate cleanly.

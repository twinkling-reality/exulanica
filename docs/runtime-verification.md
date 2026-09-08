# Runtime verification

Status: VERIFIED by execution on 2026-08-27.
Reproduce with `uv run scripts/verify_platform.py`.

The archived responses hold account-identifying response headers, so they are stored in the
gitignored internal workspace rather than committed. Every field that carries a finding is quoted
below.

This document records what was learned by actually calling the platform, as opposed to reading its
documentation. Where it contradicts an earlier document, this one wins.

## 1. The NVIDIA claim is now evidenced

**VERIFIED.** A real call to `nvidia/Nemotron-3_5-Lightning` returned HTTP 200 in 0.52 s, and the
response body echoes `"model": "nvidia/Nemotron-3_5-Lightning"`. The full body and all response
headers are archived at `.exulanica/experiments/platform/x0a_nvidia_provenance.json`.

Per the project's own stop rule ("do not claim Nano Omni/Ultra use until the real model ID and
runtime call are verified"), the project may now truthfully state that it runs NVIDIA Nemotron on
Nebius Token Factory. Before this file existed, it could not.

## 2. Catalog preflight passes

**VERIFIED.** All five model identifiers in the manifest resolve against the live catalog
(30 ids total). No role is currently pointing at a removed model.

## 3. MiniMax-M3 accepts images. The catalog `type` field is wrong.

**VERIFIED, and this closes an OPEN question from `model-and-service-selection.md`.**

`MiniMaxAI/MiniMax-M3` is typed `text2text` in the catalog JSON and labelled "Text-to-text" in the
Token Factory web console. Both are misleading. It accepts an `image_url` content part and returns a
correct description of the image.

Test image: a generated PNG containing a red vertical block and a horizontal black bar. The model
returned "Red rectangle ... solid, bright red colour" and "Black rectangle ... long, horizontal".
It is genuinely seeing the image, not merely accepting the request without error.

**Operating rule: `use_cases` is authoritative, `type` is not.** Any future model evaluation must
test capability rather than trust the type field.

## 4. Image token cost, measured

**VERIFIED.**

| Image size | `prompt_tokens` |
| --- | --- |
| 256 x 256 | 277 |
| 768 x 768 | 772 |

Token count is strongly sub-linear in pixel area: 9x the area costs 2.8x the tokens. Higher
resolution is therefore cheaper than a naive per-pixel model suggests, which removes the incentive to
aggressively downscale and lose detail.

**Measured ingestion cost: about $0.83 per 1000 photographs** at 768 px on `MiniMaxAI/MiniMax-M3`,
assuming roughly 500 output tokens per image.

This replaces the earlier estimate of roughly $1.20 per 1000. The estimate was the right order of
magnitude and slightly pessimistic.

## 5. Nemotron emits reasoning tokens on every call, and they cannot be switched off

**VERIFIED, and it is the finding most likely to cause a silent bug.**

`nvidia/Nemotron-3_5-Lightning` is a reasoning model. Every observed call spent roughly 200
`reasoning_tokens` before producing any answer, including for a trivial one-line question.

Two properties that matter:

- The thinking text appears **inline in `message.content`**, while `message.reasoning_content` is
  `null`. Anything parsing `content` naively will parse the model's scratch work.
- Setting `chat_template_kwargs: {"thinking": false}` did **not** disable it (202 reasoning tokens
  still spent). There is no known way to turn it off.

**Consequence: `max_tokens` must clear roughly 600, or responses truncate mid-reasoning with
`finish_reason: "length"` and an empty answer.** The first version of the verification harness set
`max_tokens: 200` and recorded a false negative on structured output for exactly this reason.

Cost impact is small at Lightning prices (200 tokens at $0.24/M is about $0.00005 per call) but it is
a floor on every call, not a variable, and it should be assumed in latency budgets too.

## 6. Structured output works, but only by one mechanism

**VERIFIED.** Measured with `max_tokens: 2000`:

| Mechanism | Result |
| --- | --- |
| `response_format: {type: json_schema, strict: true}` | **Valid JSON.** Use this. |
| `response_format: {type: json_object}` | Valid JSON |
| Top-level `guided_json` parameter | **Silently ignored**, returned prose. Do not use. |
| No `response_format` | Prose, as expected |

The silent failure of `guided_json` is the dangerous one: it returns HTTP 200 with a normal-looking
prose answer, so a pipeline using it would appear to work while never enforcing a schema.

**Decision: canonical memory state is only ever populated through
`response_format: {type: "json_schema", strict: true}`,** which satisfies the brief's requirement
that naked prose never enter canonical state.

## 7. Embeddings

**VERIFIED.** `Qwen/Qwen3-Embedding-8B` returns 4096-dimensional vectors. This is still the only
model in the catalog typed `embedding`, so the no-fallback exposure stands: if it is withdrawn,
the catalog offers no substitute.

## 8. Spend exposure, resolved

**VERIFIED from the billing console.** Token Factory is **prepaid**: "Your API usage is charged to
your balance", top up is a manual button, and no automatic top up is offered. The balance is money
already paid in, and it is the only pool a run can draw on.

Consequence: **Token Factory spend cannot exceed the balance.** The $1,709 figure carried in the
project's earlier cost analysis was never a Token Factory risk; it was an idle GPU virtual machine on
Nebius AI Cloud billed per hour. That is a different product and it is not provisioned.

Measured against the balance: the entire photo library costs under a dollar to ingest, and a
Companion turn at 15K context costs roughly $0.001 on Lightning. Both sit far below the prepaid
balance held for this work, and a runaway loop exhausts that balance rather than producing an
unbounded bill.

## 9. Tavily verified, and the past-to-present boundary holds

**VERIFIED by execution on 2026-08-27.** `POST https://api.tavily.com/search` returned HTTP 200 in
2.26 s with three sourced results and a synthesised answer. Archived at
`.exulanica/experiments/web-lookup/tavily_runtime_call.json`, request payload included.

Account state: **pay as you go is Disabled, and the credential draws on a fixed monthly credit
allowance.** There is no uncapped spend path on this credential: when the allowance is spent, calls
fail rather than billing on.

The archived request is retained deliberately. It is the evidence that the payload carried public
entity text only, with no private media, no person, no private location, and no transcript. The
brief requires proving minimisation rather than asserting it, and the stored request is that proof.

### The demonstration beat this unlocks

The test query concerned a public landmark. The live answer included a current visitor cost and a
seasonal caveat on access, which is exactly the shape of answer the Then and Now beat needs.

The corpus contains a photograph taken at a public landmark, so the same call can be made for an
entity the corpus actually holds. That yields a genuine Then and Now pair drawn from real evidence
on both sides:

- **Then, from memory:** the original photograph, with its own evidence citation.
- **Now, from the live web:** current access and cost, with publisher URLs and a retrieval date.

This satisfies the brief's rule that Tavily results may never rewrite what happened in a memory. The
two panels make separate claims from separate sources, and neither is permitted to overwrite the
other.

**ASSUMPTION to validate later:** that the same quality of current-state answer is available for the
other public entities in the corpus, including a business name legible on signage in a photograph
rather than a landmark named in its own right. Settled by running the same script against those
entities once the corpus is on disk.

## 10. Frontier local readiness, 2026-09-08

No authorized personal photo directory or production signing key was supplied for this work.
The personal-corpus milestone remains unexecuted. These results concern generated fixtures and
read-only inspection of the retained reference, not real vision, COLMAP or CUDA training.

The standalone `exulanica-frontier preflight` was executed on this checkout with the rehearsal's
strict manifest and generated photo directory, the permitted local database's `public` schema,
a fresh output path, and a throwaway Ed25519 key. All local checks passed without creating the
proposed output. The signing procedure in `frontier-demonstration.md` was executed separately:
owner-only key creation, loading through the package implementation and sign/verify all passed.

`exulanica-frontier dry-run` executed the ordinary ten-gate lifecycle with generated photographs.
All three packages passed independent process verification. Model calls were zero, repeat stages
run were empty, and the deletion demonstration left one live region while preserving source files.
The rehearsal created and removed only its own database schema. This is an executable rehearsal,
not a claim that the missing personal run has occurred.

Inspection found and fixed a real authorization error: the ordinary demonstration previously
created synthetic authorization and exemption receipts for any supplied photograph. It now reads
existing screening authority before configured models or lifecycle writes. Only the internal
rehearsal generator can create its synthetic receipts. Observation-only permission is accepted for
vision alone; depth requires geometry permission. The CLI separately requires per-run hosted-model
authorization and refuses to apply pending migrations.

Read-only observation measurements reproduce 97,633,587 canonical bytes for the bowl's 15,005
points and 71,214 observations. A 500-point page is 4,973,392 bytes and 3,649 observations, with
cursor 543. This bounds the answer, not server work. The browser keeps its single complete request
because the current inspector has no partial state and paging has no snapshot identity. It now
rejects pages, wrong scenes, duplicate IDs and inconsistent counts rather than silently dropping
evidence. The remaining browser memory cost is explicit.

Three negative controls were executed in isolated source copies: allowing terminal writes into
existing outputs, bypassing pre-run screening admission, and removing observation completeness
validation. Each unmodified baseline passed; each mutation caused its named test to fail; restored
baselines passed. No failure was counted merely from a nonzero process exit.

Reproduce the digest-bound readiness measurement with:

```sh
uv run python -m exulanica.orchestration.record_readiness \
  --date YYYY-MM-DD --label frontier-readiness \
  --predecessor docs/evaluation/2026-09-08-place-read-paths.json
```

The command creates a new dated record, refuses overwrites, executes a fresh synthetic rehearsal
and local pre-flight, and measures the retained bowl through read-only application-role queries.
The record binds its predecessor, implementation files and pipeline digest. It preserves the
separation between demonstrated local readiness and the still-missing personal run.

The fresh worktree's plain `uv sync` omitted optional numerical dependencies required by existing
pose/training tests. Verification installed the already-locked extras with
`uv sync --extra pose --extra reconstruction --locked`; no dependency declaration or lockfile was
changed. Installing these libraries does not download a model checkpoint or run inference.

# Provider runtime findings

This archive records what calling Nebius Token Factory established about the hosted models
Exulanica uses: measured behaviour of specific model revisions on 2026-08-27 and 2026-08-28, from
`scripts/verify_platform.py` and readings of the provider's machine-readable catalog. A finding
applies to its recorded requests and revisions; it does not establish behaviour for another
execution. [Model and service selection](model-and-service-selection.md) owns the implemented
stack. The [model manifest](../exulanica/models/models.manifest.json), `exulanica/models/preflight.py`
and `exulanica/models/client.py` enforce the operating rules these findings produced.

The raw responses carry account-identifying headers and are not in the repository; every field
that carries a finding is quoted below. A discrepancy with another document is settled by comparing
revisions, inputs and execution evidence, not by preferring this file.

## 1. The NVIDIA claim is evidenced

**VERIFIED.** A call to `nvidia/Nemotron-3_5-Lightning` returned HTTP 200 in 0.52 s, and the
response body echoes `"model": "nvidia/Nemotron-3_5-Lightning"`. The statement that Exulanica runs
NVIDIA Nemotron on Nebius Token Factory rests on that call, not on configuration: no model's use is
claimed until its real identifier and a runtime call are verified.

The harness's seven checks (catalog preflight, that NVIDIA call, strict structured output, vision
at two image sizes, image token cost and embeddings) all passed on 2026-08-27.

## 2. Catalog preflight passes

**VERIFIED.** Every identifier the manifest held resolved against the live catalog of 30
identifiers; no role pointed at a removed model.

Callable identifiers differ from display names, and their casing is inconsistent. Read from the
catalog, `flavors[].model_id` against `name`:

| Callable `flavors[].model_id` | Catalog `name` |
| --- | --- |
| `nvidia/Nemotron-3_5-Lightning` | `Nemotron-3.5-Lightning` |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `Nemotron-3-Nano-30B-A3B` |
| `nvidia/nemotron-3-super-120b-a12b` | `Nemotron-3-Super-120b-a12b` |
| `MiniMaxAI/MiniMax-M3` | `MiniMax-M3` |
| `openbmb/MiniCPM-V-4_5` | `openbmb/MiniCPM-V-4_5` |

The identifier uses an underscore where the name uses a dot (`3_5` against `3.5`), one NVIDIA
identifier doubles the vendor prefix, one is entirely lowercase while its siblings are title-cased,
and `name` sometimes keeps the vendor prefix and sometimes drops it. An identifier typed from a
display name fails as a 404-class error.

**Operating rule.** Every hosted identifier lives in the model manifest; code reads
`flavors[].model_id` and never `name`; and `uv run exulanica-preflight` fails when a manifest
identifier is absent from the live catalog (`exulanica/models/preflight.py`).

## 3. MiniMax-M3 accepts images. The catalog `type` field is wrong.

**VERIFIED.** `MiniMaxAI/MiniMax-M3` is typed `text2text` in the catalog and labelled
"Text-to-text" in the Token Factory console, yet it accepts an `image_url` content part and
describes the image correctly. The test image was a generated PNG with a red vertical block and a
horizontal black bar; the model returned "Red rectangle ... solid, bright red colour" and "Black
rectangle ... long, horizontal". It sees the image; it does not merely accept the request.

The catalog's coarse `type` and its `use_cases` array disagree for other models too:

| Model | `type` | `use_cases` includes |
| --- | --- | --- |
| `MiniMaxAI/MiniMax-M3` | `text2text` | `image`, `video` |
| `nvidia/Nemotron-3-Nano-Omni` | `text2text` | `image` |
| `google/gemma-3-27b-it` | `text2text` | `image` |
| `moonshotai/Kimi-K2.7-Code` | `text2text` | `image` |

`nvidia/Nemotron-3-Nano-Omni` describes itself as an omni-modal reasoning model and is still typed
`text2text`. Filtering the catalog by `type` for a vision model misses all four, and the chat
schema accepts an `image_url` part for every model, so a request validates whether or not the
model can see.

**Operating rule: `use_cases` is authoritative, `type` is not.** The preflight asserts each role's
use cases on `use_cases` (`exulanica/models/preflight.py`), and the manifest records both fields
for every hosted model (`catalog_type`, `catalog_use_cases`). A model evaluation tests a capability
rather than trusting `type`.

## 4. Image token cost, measured

**VERIFIED.**

| Image size | `prompt_tokens` |
| --- | --- |
| 256 x 256 | 277 |
| 768 x 768 | 772 |

Token count is strongly sub-linear in pixel area: nine times the area cost 2.8 times the tokens.
A higher resolution therefore costs far less than a per-pixel estimate suggests, and aggressive
downscaling saves little.

## 5. Nemotron emits reasoning tokens on every call, and they cannot be switched off

**VERIFIED.** `nvidia/Nemotron-3_5-Lightning` is a reasoning model. It spent roughly 150 to 215
reasoning tokens before any answer on every observed call, including a one-line question with a
one-word answer; the structured-output call that asked for the colours of the French flag spent
214. Setting `chat_template_kwargs: {"thinking": false}` did not disable it: 202 reasoning tokens
were still spent.

**A low `max_tokens` looks like model failure.** When the budget is spent before the answer
begins, the endpoint returns HTTP 200 with `finish_reason: "length"` and no answer, which a caller
cannot tell apart from a model that cannot do the task. A harness run with `max_tokens: 200`
recorded a false negative on structured output for exactly this reason. The manifest gives every
reasoning model a `min_max_tokens` of 640, a figure arrived at by measurement, and latency budgets
assume the same floor.

**Where the thinking text goes is OPEN.** Two shapes are on record. The archived responses of
2026-08-27 carry a clean answer in `message.content` and the same thinking text, duplicated
verbatim, in both `message.reasoning` and `message.reasoning_content`. The runtime notes behind this
section record the other shape: the thinking inline in `message.content`, with or without a tag,
and `reasoning_content` null, so anything parsing `content` naively parses the model's scratch
work. The client depends on neither: `exulanica/models/reasoning.py` handles both shapes, and
`exulanica/models/schema.py` reads the answer object out of untagged prose. A documented statement
of which field is canonical, and whether placement varies by model or request, would settle it.

## 6. Structured output works, but only by one mechanism

**VERIFIED.** Measured with `max_tokens: 2000`, so section 5 does not explain these results:

| Mechanism | Result |
| --- | --- |
| `response_format: {type: json_schema, strict: true}` | **Valid, schema-conforming JSON.** Use this. |
| `response_format: {type: json_object}` | Valid JSON |
| Top-level `guided_json` parameter | **Silently ignored**: HTTP 200 with a prose answer |
| No `response_format` | Prose, as expected |

The silent failure of `guided_json` is the dangerous one: a pipeline built on it returns normal
looking answers while nothing enforces a schema, and no test of status codes catches it.

**DECISION: canonical state is only ever populated through
`response_format: {type: "json_schema", strict: true}`,** so that naked prose never enters it. The
client (`exulanica/models/client.py`) refuses a payload naming `guided_json` or its `guided_*`
siblings, refuses any `response_format` other than `json_schema` with `strict: true`, and validates
every structured reply locally against the exact schema it sent.

## 7. Embeddings

**VERIFIED.** `Qwen/Qwen3-Embedding-8B` returns 4096-dimensional vectors. It was the only model in
the catalog typed `embedding`, so the embedding role has no in-catalog fallback: the manifest's
`embedding` role names none, and a withdrawal would need a build-time change and a full
re-embedding. The nearest alternative, `nvidia/Nemotron-3-Embed-1B-BF16`, is a self-hosted
deployment with a different vector width, not a runtime failover.

## 8. Hosted spend is bounded by a prepaid balance

**VERIFIED from the billing console.** Token Factory charges usage to a prepaid balance, top-up is
a manual action and no automatic top-up is offered, so hosted spend cannot exceed the balance. The
budget guard (`exulanica/models/budget.py`) therefore guards against a runaway loop inside that
balance rather than against an unbounded bill.

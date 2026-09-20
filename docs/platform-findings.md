# Platform findings: Nebius Token Factory, Nebius AI Cloud, NVIDIA models and Tavily

Status: mixed, labelled per finding. Runtime observations come from `scripts/verify_platform.py`.
Catalog and documentation observations cite a primary URL and a retrieval date on the finding.

Every finding below is reproducible. Where a claim rests on a response the platform actually
returned, the response is archived and the specific fields that carry the finding are quoted here.
Where a claim rests on published documentation, the primary URL is given. Where something remains
unresolved, it is marked OPEN rather than rounded off in either direction.

---

## 1. Method

Nothing here comes from reading a documentation page and believing it. The project ran a
verification pass against the live platform, archived the raw responses with their headers, and
wrote the findings against those bodies. The pass is `scripts/verify_platform.py`, it makes seven
checks, and all seven passed on 2026-08-27:

| Check | Result |
| --- | --- |
| Catalog preflight | 30 live identifiers, none of the project's five missing |
| NVIDIA runtime call | HTTP 200 in 0.93 s, echoed `"model": "nvidia/Nemotron-3_5-Lightning"` |
| Structured output through `json_schema` strict | HTTP 200, parsed `{"colours": ["blue", "white", "red"]}`, 214 reasoning tokens |
| Vision over a 256 px image | HTTP 200, `prompt_tokens` 277, correct description |
| Vision over a 768 px image | HTTP 200, `prompt_tokens` 772, correct description |
| Cost model | About $0.83 per 1000 photographs at 768 px |
| Embeddings | HTTP 200, 4096 dimensions |

A separate script, `scripts/verify_web_lookup.py`, made one real Tavily search and kept the request
payload.

What this document does **not** cover: Nebius AI Cloud has not been provisioned. Section 4 is
documentation-verified only, and it says so at the top.

---

## 2. What worked well

Stated first, and not as a courtesy. Each of these saved real time.

**The OpenAI-compatible surface made integration nearly free.** A single global base URL,
`https://api.tokenfactory.nebius.com/v1`, bearer auth from an environment variable, and the standard
chat completions shape. The project chose a plain HTTP client over the vendor SDK and still had a
working call on the first attempt. Nothing about the transport needed to be learned.

**`response_format: {type: "json_schema", strict: true}` works correctly.** Once `max_tokens`
cleared the reasoning floor described in finding F1, it returned valid, schema-conforming JSON every
time. This is the mechanism the whole project depends on, because its rule is that model prose can
never enter canonical state, and the platform honours it.

**Prepaid billing means runaway spend is not possible.** The billing console states plainly that API
usage is charged to the balance, top-up is a manual button, and no automatic top-up is offered.
For a small prepaid balance that is the right default, and it removed an entire category of worry.
Every other platform surface the project touched needed a spend guard designed around it. This one
did not.

**Pricing was accurate.** The per-model `input`/`output` figures in the machine-readable catalog
matched the published pricing, and `usage` on every response carries `prompt_tokens`,
`completion_tokens` and `completion_tokens_details.reasoning_tokens`. That was enough to compute
cost per call locally with no separate metering API, which is how the $0.83 per 1000 photographs
figure was measured rather than estimated.

**Response headers are unusually good for debugging.** A single archived response carries
`x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-limit-tokens`,
`x-ratelimit-remaining-tokens`, reset intervals, `x-request-id` and `x-inference-id`. Backoff logic
and support correlation both come free from that.

**The machine-readable catalog exists and is honest about being authoritative.**
`https://tokenfactory.nebius.com/api/public/models_info` is the reason this project could build a
preflight check that fails a build when a model identifier disappears. Several findings below are
about the contents of that catalog, and none of them would have been findable without it.

---

## 3. Nebius Token Factory

### F1. Reasoning tokens are unavoidable, and under a low `max_tokens` they look exactly like model failure

**Severity: high. This is the single most useful thing to document, and it cost the most debugging
time.**

**Observed.** `nvidia/Nemotron-3_5-Lightning` spends roughly 150 to 215 reasoning tokens before
producing any answer, on every call, including a one-line question with a one-word answer. The
archived provenance call asked the model to reply with a single word and
`usage.completion_tokens_details.reasoning_tokens` was non-zero; the archived structured-output call
asked for the colours of the French flag and spent **214 reasoning tokens** to answer with
`{"colours": ["blue", "white", "red"]}`.

**It cannot be switched off.** Sending `chat_template_kwargs: {"thinking": false}` did not disable
it. 202 reasoning tokens were still spent.

**The failure this produces.** With a small `max_tokens`, the endpoint returns **HTTP 200** with
`finish_reason: "length"` and no answer, because the budget was consumed before the answer began. To
a caller, that is indistinguishable from a model that cannot do the task. This project's own
verification harness set `max_tokens: 200`, recorded a false negative on structured output, and
concluded that structured output did not work on this platform. It does. The parameter was wrong.

**Impact.** A developer benchmarking models with a conservative token budget will silently rank
reasoning models as incapable. This is a bad first experience with an otherwise good model, and the
cause is invisible from the response.

**Suggested fix.** Three things, in order of value:

1. Publish a per-model minimum `max_tokens` in the catalog, or at minimum state the reasoning floor
   on the model card. This project hard-codes 640 for every reasoning model in its manifest and
   arrived at that number by measurement.
2. When `finish_reason` is `length` and no answer content was produced, say so distinctly. A
   response that spent its entire budget on reasoning is a different event from a truncated answer,
   and the caller cannot tell them apart.
3. If a thinking-off mode is intended to exist, document which parameter controls it, and return an
   error for a parameter that does not.

**A related discrepancy, OPEN.** Where the thinking text is placed is not documented and this
project has records of two different shapes. The archived responses from 2026-08-27 show
`message.content` holding a clean answer while both `message.reasoning` and
`message.reasoning_content` hold the same thinking text, duplicated verbatim in two fields. The
project's own runtime notes record the opposite shape, thinking inlined in `message.content` with
`reasoning_content` null. The client therefore refuses to depend on either and handles both, because
being wrong in either direction means a model's scratch work is parsed as a fact. **What would
help:** a documented statement of which field is canonical, whether `reasoning` and
`reasoning_content` are both guaranteed, and whether the placement can vary by model or by request.

### F2. A top-level `guided_json` parameter is accepted and silently ignored

**Severity: high. Silent no-ops are the worst possible failure mode for a structured-output feature.**

**Observed.** Passing `guided_json` at the top level of a chat completions request returns **HTTP
200 with a prose body**. No error, no warning, no schema enforcement. Measured with `max_tokens:
2000`, so this is not finding F1 in disguise.

For contrast, in the same measurement pass:

| Mechanism | Result |
| --- | --- |
| `response_format: {type: "json_schema", strict: true}` | Valid, schema-conforming JSON |
| `response_format: {type: "json_object"}` | Valid JSON |
| Top-level `guided_json` | Silently ignored, prose, HTTP 200 |
| No `response_format` | Prose, as expected |

**Impact.** A pipeline built on `guided_json` appears to work. It returns 200s, the bodies look
plausible, and nothing enforces a schema. In a system whose core rule is that unstructured model
output must never enter canonical state, that is a correctness hole that no test written against
status codes would catch.

**Suggested fix.** Reject unknown top-level parameters with a 400, or accept `guided_json` and
honour it. Either is fine. Accepting it and doing nothing is not. If a strict rejection would break
existing callers, a warning field in the response body would still be a large improvement over
silence.

**What this project did as a result.** The client refuses to send `guided_json` at all, refuses any
`response_format` it did not construct itself, and validates every structured reply locally against
the exact schema it sent. That last step exists specifically because `guided_json` proved on this
platform that a constraint parameter can be accepted, ignored, and answered with a response that
looks fine.

### F3. The catalog `type` field is not a capability statement, and it will send a developer to the wrong model

**Severity: high for anyone selecting a vision model.**

**Observed.** The catalog carries both a coarse `type` field and a `use_cases` array, and they
disagree. Read directly from `models_info`:

| Model | `type` | `use_cases` includes |
| --- | --- | --- |
| `MiniMaxAI/MiniMax-M3` | `text2text` | `image`, `video` |
| `nvidia/Nemotron-3-Nano-Omni` | `text2text` | `image` |
| `google/gemma-3-27b-it` | `text2text` | `image` |
| `moonshotai/Kimi-K2.7-Code` | `text2text` | `image` |

The web console agrees with the wrong field: `MiniMaxAI/MiniMax-M3` is labelled **Text-to-text**
there.

**And the `use_cases` reading is the correct one, by execution.** A single `image_url` content part
was sent to `MiniMaxAI/MiniMax-M3`. It returned HTTP 200 and described the test image accurately:
"Red rectangle" for a tall vertical red block and "Black rectangle" for a long horizontal bar. It is
genuinely seeing the image, not merely accepting the request without error. That model is this
project's vision sensor.

The `nvidia/Nemotron-3-Nano-Omni` case is the sharpest illustration. Its own catalog `description`
calls it an "omni-modal reasoning model", its `huggingface_url` points at a card documenting video,
audio, image and text input, and it is typed `text2text` anyway.

**Impact.** A developer filtering the catalog by `type` to find a vision model finds three
(`image2text`) and misses the one with the largest context window and the lowest price. The API
schema does not help either, because `ChatCompletionMessage.content` is a discriminated union of
`text`, `image_url` and `video_url` for every model, so the request validates regardless of whether
the model can see.

**Suggested fix.** Document the relationship between `type` and `use_cases`, and state which one is
a capability contract. Ideally make `type` derived from `use_cases` so the two cannot disagree, and
have the console render `use_cases` rather than `type` on the model card. Failing that, one sentence
in the API reference saying "filter on `use_cases`, not `type`" would be enough.

**Operating rule this project adopted:** `use_cases` is authoritative, `type` is not, and the
build-time preflight asserts on `use_cases`.

### F4. Callable identifiers do not match display names, and their casing is inconsistent

**Severity: medium. It is an afternoon, not a design flaw, but it is an avoidable afternoon.**

**Observed**, read directly from the catalog:

| Callable `flavors[].model_id` | Catalog `name` |
| --- | --- |
| `nvidia/Nemotron-3_5-Lightning` | `Nemotron-3.5-Lightning` |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `Nemotron-3-Nano-30B-A3B` |
| `nvidia/nemotron-3-super-120b-a12b` | `Nemotron-3-Super-120b-a12b` |
| `MiniMaxAI/MiniMax-M3` | `MiniMax-M3` |
| `openbmb/MiniCPM-V-4_5` | `openbmb/MiniCPM-V-4_5` |

Three separate inconsistencies are visible in that table. The identifier uses an underscore where
the display name uses a dot (`3_5` versus `3.5`). One NVIDIA identifier doubles the vendor prefix
(`nvidia/NVIDIA-Nemotron-...`) while its siblings do not. One NVIDIA identifier is entirely
lowercase (`nvidia/nemotron-3-super-120b-a12b`) while every other NVIDIA identifier is title-cased.
And the `name` field usually strips the vendor prefix but sometimes keeps it.

**Impact.** A model identifier typed from a display name, a console screenshot, or a conference
slide fails as a 404-class error at the moment a user is watching. Because the identifiers look
almost right, the mistake survives code review.

**Suggested fix.** Normalise identifier casing across a model family, and show the exact callable
identifier with a copy button wherever a model is named in the console and the documentation. The
`name` field should either always include the vendor prefix or never.

**What this project did:** every identifier lives in one manifest file, the code reads
`flavors[].model_id` and never `name`, and a preflight fails the build if any manifest identifier is
absent from the live catalog.

### F5. Two deprecation rounds in ten weeks, and after 2026-08-31 no NVIDIA multimodal model remains on serverless

**Severity: medium, and this is offered as a heads-up rather than a defect report.**

**Observed.** Nebius removed 11 models from Token Factory Serverless on 2026-06-22 and removes 10
more on 2026-08-31. Both rounds were published ahead of the removal date, which is better practice
than most providers manage. The June list is 7 `-fast` identifiers plus 4 others,
`deepseek-ai/DeepSeek-V3.2`, `moonshotai/Kimi-K2.5`, `PrimeIntellect/INTELLECT-3` and
`zai-org/GLM-5`. The two notices differ in one respect that matters to a caller: the August notice
carries a recommended replacement for every model it removes, and the June notice carries no
replacement column at all, directing readers to Dedicated Endpoints for production workloads
instead. Sources: https://docs.tokenfactory.nebius.com/june-2026-deprecation-notice ,
https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice (both retrieved 2026-08-28)

The sharp edge is in the detail. The two NVIDIA models removed on 2026-08-31,
`nvidia/Nemotron-3-Nano-Omni` and `nvidia/Cosmos3-Super-Reasoner`, are the only two NVIDIA models in
the catalog declaring an `image` use case. **After 2026-08-31 there is no NVIDIA vision or
multimodal model on Token Factory Serverless.** The recommended replacements printed in the notice
carry that consequence without stating it: the omni-modal `Nemotron-3-Nano-Omni` is replaced by
`nvidia/Nemotron-3_5-Lightning`, which declares no `image` use case, and `Cosmos3-Super-Reasoner` is
replaced by the non-NVIDIA `MiniMaxAI/MiniMax-M3`. Neither replacement preserves both the vendor and
the modality, and the notice does not say so.
Source: https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice (retrieved 2026-08-28)

**Impact.** Anyone who needs an NVIDIA model and an image path in the same call has no serverless
option here after 2026-08-31. Someone building anything image-shaped from the catalog would
naturally reach for `Nemotron-3-Nano-Omni`, and the per-model replacement moves them off the vendor
or off the modality silently, because a replacement mapping is read as an equivalence. Routing
reasoning to a text Nemotron and vision to a non-NVIDIA model is a workable answer, and it is what
this project does, but it is a constraint worth learning when the model is chosen rather than when
it is removed.

**Suggested fix.** Two things, both cheap:

1. State the modality consequence in the deprecation notice itself, alongside the per-model
   replacement: after this round the NVIDIA models on serverless are text-only. A replacement table
   that crosses a vendor boundary or a modality boundary should say which boundary it crossed.
2. Publish the deprecation calendar far enough ahead that a short project can plan around it. Two
   rounds in ten weeks is a lot of change to absorb, and a removal landing mid-project is a real
   risk for any caller pinned to a serverless identifier.

**What this project did:** every role has a declared fallback identifier in the same manifest, the
client selects it on a 404-class error only, the fallback path is exercised in CI, and a weekly
check diffs the live catalog. Nothing in the plan depends on a removed model, and that was a
constraint applied before the model matrix was written rather than a lucky outcome.

### F6. Token Factory has no audio capability of any kind

**Severity: low as a defect, high as a documentation gap.**

**Observed.** There is no audio endpoint, no audio content part, and no audio model. The published
OpenAPI document lists 38 paths, covering completions, chat completions, embeddings, rerank,
responses, models, files, image generations, fine-tuning, dedicated endpoints, datasets and
operations. The strings `audio`, `speech`, `transcription` and `tts` appear **zero** times in the
entire document. No catalog entry is typed for audio.

**Impact.** This is not a criticism of the platform's scope. It is a planning fact that is
only discoverable by exhaustive search. This project scoped a set of features around recurring
voices and conversations before establishing that the platform has no path for them, and deferred
that entire pillar with a stated reason as a result. A team that discovers this later
loses more.

**Suggested fix.** One line in the platform overview stating which modalities are supported and
which are not. "Text, image and video input; text, embedding and image output; no audio" would have
saved this project a day.

**Worth noting for completeness.** Chat responses return a `message.audio` field (null), among other
fields such as `token_ids` and `stop_reason` that do not appear in the published OpenAPI document.
The response shape is a superset of the published schema. Harmless, but it means the schema cannot
be used to generate an exhaustive response type.

### F7. Exactly one embedding model, so the embedding role has no in-catalog fallback

**Severity: medium, and it is an availability observation rather than a defect.**

**Observed.** Across all 30 catalog entries there is exactly one model of type `embedding`:
`Qwen/Qwen3-Embedding-8B`. It works correctly and returns 4096-dimensional vectors, verified by
execution.

**Impact.** Every other role in this project's model matrix has a declared fallback that is another
Token Factory identifier and can be swapped at runtime. The embedding role does not. Given the
observed deprecation cadence in finding F5, a single-model role is the one place where a removal
would be unrecoverable without a build-time change and a full re-embedding of the corpus. The
nearest alternative, `nvidia/Nemotron-3-Embed-1B-BF16`, is a self-hosted deployment with a different
vector width, so it is not a runtime failover.

**Suggested fix.** A second serverless embedding model, at any price point, would remove this. If
that second model is absent from the platform roadmap, saying so is still useful, because it tells a developer to precompute and
freeze embeddings rather than depending on the endpoint at request time.

### F8. Documentation is stale in places that produce copy-paste failures

**Severity: medium, because the failures are silent to a reader.**

**Observed.** Both documentation pages and the catalog were re-read on 2026-08-28, and both
discrepancies were still present:

- The inference overview page still documents the `-fast` flavor as a live feature: "To use the Fast
  flavor, append `-fast` to the model name". Every `-fast` identifier was deleted on 2026-06-22 and
  zero remain in the live catalog.
  Sources: https://docs.tokenfactory.nebius.com/ai-models-inference/overview ,
  https://tokenfactory.nebius.com/api/public/models_info (both retrieved 2026-08-28)
- The vision-capabilities examples page cites `Qwen/Qwen2-VL-72B-Instruct` and
  `meta-llama/Meta-Llama-3.1-70B-Instruct` in its code samples. Neither resolves in the catalog,
  which carries `Qwen/Qwen2.5-VL-72B-Instruct` and `meta-llama/Llama-3.3-70B-Instruct` instead. Both
  stale identifiers are near-misses for a live one, which is the worst case for a reader skimming.
  Sources: https://docs.tokenfactory.nebius.com/api-reference/examples/vision-capabilities ,
  https://tokenfactory.nebius.com/api/public/models_info (both retrieved 2026-08-28)

**Impact.** A developer copying a model identifier out of a documentation example gets a 404-class
error, and the natural first conclusion is that their credentials or base URL are wrong, not that
the documentation is describing a removed feature.

**Suggested fix.** Validate documentation examples against `models_info` in CI and fail the docs
build on an identifier that no longer resolves. The catalog already exists and is already
authoritative, so the check is small.

**What this project did:** treat only `models_info` and `openapi.json` as authoritative, and never
copy a model identifier out of a documentation example.

---

## 4. Nebius AI Cloud

**Scope note, stated plainly: AI Cloud has not been provisioned.** No VM, no job, no bucket. Nothing
in this section is execution-verified, and none of it should be read at the same strength as
sections 2, 3 and 5, which rest on responses the platform actually returned. Every claim below rests
on a published Nebius documentation page, cited with its URL and the date it was retrieved. Where
the documentation does not settle a question, the claim is marked OPEN rather than rounded off in
either direction. This is the experience of planning against the documentation, not of running on
the platform.

**Object storage does not support Object Lock, Legal Hold, or WORM.** The S3 compatibility page
states it verbatim: "Write-once-read-many (WORM) retention policies are not supported." This is
documented clearly and was easy to find, which is exactly right, and it directly shaped what this
product is allowed to claim. A memory system's most attractive marketing word is "immutable", and
the honest version available on this storage is bucket versioning plus content-addressed keys plus a
bucket policy denying delete to the runtime service account. This project therefore says
**"append-only by policy"** everywhere, and the words immutable, WORM and tamper-proof do not appear
in its product copy. Worth stating positively: the clarity of that page is what made the honest
claim possible, because an ambiguous page would have left room to overclaim. If Object Lock arrives
later, it would be worth announcing loudly, because retention guarantees are a product feature and
not only an infrastructure one.
Source: https://docs.nebius.com/object-storage/interfaces/s3-api-compatibility (retrieved 2026-08-28)

**GPU quotas count stopped instances.** The quotas page states it directly: "A VM and its resources
count towards the quotas throughout the VM's lifecycle, from its creation to deletion, regardless of
whether it is running or stopped." So a stopped VM still blocks the next job from starting. This is
the kind of thing that is much better to read in the quotas page than to discover while debugging a
job that will not schedule. It is worth surfacing in the compute quickstart too, because that is
where a new user meets the concept.
Source: https://docs.nebius.com/compute/resources/quotas-limits (retrieved 2026-08-28)

**Default GPU quotas are regionally uneven in a way that decides architecture.** Across the eight
regions listed, eu-north1 is the only one with a non-zero default L40S quota, at 2. us-central1 has
no GPU type with a non-zero default at all, and the custom-image quota is 0 in every region
("Number of images: 0"). That last one is the consequential constraint: it means a pipeline ships
as containers and never as a baked image, which is a reasonable design but is a decision made for
the user by a quota default rather than by an architectural recommendation. A short note in the docs
saying "default to containers, request custom-image quota if you need it" would frame it as guidance
rather than as an obstacle discovered late.
Source: https://docs.nebius.com/compute/resources/quotas-limits (retrieved 2026-08-28)

**Serverless AI is Preview-grade, and the terms say so honestly.** The specific terms state "The
Service is in Preview stage", "There is no Service Level provided for the Service" and "The Service
does not provide automatic retry, recovery, or redundancy mechanisms", and the serverless overview
gives an endpoint's "Typical lifetime: Hours to days". This project needs a deployment that survives
unattended for about 46 days, so it puts the API process and database on a plain Compute VM with a
restart policy instead. Serverless usage "is billed under Compute VM pricing", so the cost is
identical either way and only the reliability differs. The honesty of those terms is appreciated and
rare. The gap is one of placement rather than of candour: the product overview encourages Serverless
Endpoints for deployment, the Preview limitations live in a separate legal specific-terms document,
and a developer reading the first will not find the second. Linking the terms from the overview
would close it.
Sources: https://docs.nebius.com/legal/specific-terms/serverless-ai ,
https://docs.nebius.com/serverless/overview , https://docs.nebius.com/serverless/pricing-quotas
(all retrieved 2026-08-28)

**Managed PostgreSQL is priced for a different workload.** The documented worked example is a
`4vcpu-16gb` cluster at 4 x $0.034 + 16 x $0.009 = $0.28 per hour, roughly $204 per month. This
project's database will not reach 1 GB, so the managed option would cost more over the project
period than the entire expected inference spend, and the database therefore runs in a container on
the same Compute VM as the API. That is a correct price for a production database and the wrong
shape for a database that fits in a laptop's page cache.
Source: https://docs.nebius.com/postgresql/resources/pricing (retrieved 2026-08-28)

**OPEN: whether a smaller managed PostgreSQL configuration can be ordered.** The claim that no
smaller tier exists is not supported by the documentation and is not made here. The pricing page
prices any cluster by a per-vCPU and per-GB formula and uses `4vcpu-16gb` only as a worked example,
not as a floor, and the CLI reference for cluster creation requires a resource preset without
enumerating the permitted values, so the smallest orderable configuration is documented nowhere this
project could find. **What would settle it:** a published list of supported PostgreSQL resource
presets, or a single create call accepted or rejected for a preset below `4vcpu-16gb`. The cost
figure above is unaffected either way, because it is the documented example rather than a claimed
minimum. The documentation gap is itself the finding: the only sizing signal a reader gets is an
example shaped like production.
Sources: https://docs.nebius.com/postgresql/resources/pricing ,
https://docs.nebius.com/cli/reference/msp/postgresql/v1alpha1/cluster/create (both retrieved
2026-08-28)

---

## 5. Tavily

Short, because there is little to report, which is the point.

**It worked on the first attempt.** `POST https://api.tavily.com/search` returned HTTP 200 in 2.26 s
with three sourced results and a synthesised answer, on the first request ever made against the
credential. No SDK, no setup beyond a key.

**Pay-as-you-go is disabled by default.** A key cannot spend past its included allowance until
someone deliberately turns overage on. For a project that uses public lookup as a narrow opt-in
layer rather than as a search engine, that means there is no uncapped spend path on the credential
at all, and no spend guard had to be designed around it. That default is the right one and other
APIs should copy it.

**The privacy documentation is specific enough to design against.** Tavily states that it may use
portions of query data to improve future responses and shares query data with third-party index
providers where its own index cannot retrieve content, and advises against personal information in
queries. That specificity is what let this project write a hard rule: queries are constructed
server-side, are opt-in, and carry public entity text only. The archived request payload is kept
deliberately as the evidence that the rule held, and the reason it can be kept as evidence is that
the API surface is small enough to reason about.

**One request, and it is a small one.** The `answer` field is a synthesis over the results, and it
is not obvious from the response whether every sentence in it is supported by the returned `results`
or whether it may draw on content that was retrieved but not returned. For a product whose entire
thesis is that a claim resolves to its source, that distinction decides whether the synthesised
answer can be displayed at all. Documenting it would be genuinely useful.

---

## 6. Prioritised list

What would most improve the developer experience, in the order this project would rank it.

1. **Document the reasoning-token floor, per model, in the catalog.** It is one number, it is
   already knowable to the platform, and not knowing it produces a false negative that looks like a
   bad model rather than a bad parameter. Highest value item on this list by a wide margin (F1).
2. **Stop accepting parameters silently.** Reject unknown top-level parameters with a 400, starting
   with `guided_json`. A silently ignored constraint is worse than an unsupported one, because it
   ships (F2).
3. **Make `type` and `use_cases` agree, and render the capability field in the console.** A vision
   model labelled Text-to-text in the console is a wrong answer to the most common catalog question
   there is (F3).
4. **State which field carries a reasoning model's thinking text, and guarantee it.** Two fields
   carry it verbatim in the responses this project archived, and this project's own notes
   record a third arrangement. Every caller has to write defensive parsing for something the
   platform knows the answer to (F1, OPEN).
5. **Normalise model identifier casing and show the exact callable string everywhere a model is
   named.** Doubled vendor prefixes and a single lowercase entry in an otherwise title-cased family
   cost time that produces nothing (F4).
6. **Publish a modality matrix.** One table of what the platform accepts and returns, including the
   absence of audio. It prevents a whole feature from being scoped against a capability that does
   not exist (F6).
7. **Validate documentation examples against the live catalog in CI.** The authoritative source
   already exists; the documentation should be tested against it (F8).
8. **Add a second serverless embedding model.** One model in a role means one deprecation from an
   unrecoverable position, and embeddings are the least swappable thing in any retrieval system
   (F7).
9. **Publish the deprecation calendar far enough ahead to plan around, and state the modality
   consequence in the notice.** Two rounds in ten weeks is a lot of change to absorb inside a short
   project, and the August round removes the last NVIDIA image path from serverless without saying
   so anywhere in the notice (F5).
10. **Document the smallest orderable managed PostgreSQL configuration.** The only sizing signal on
    the pricing page is a production-shaped worked example, and whether anything smaller can be
    ordered is OPEN (section 4).

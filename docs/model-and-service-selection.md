# Model and service selection

Status: current implementation reviewed 2026-09-12; model upgrades require task-specific evidence.

## 0. Current stack and selection decision

This section supersedes the routing and deployment descriptions in sections 1–8 below. Those
sections retain the August research, its prices and rejected alternatives; they are historical
rationale, not a current runtime inventory. Inspect actual call sites as well as the manifest:
its `structured_extraction` rationale still says reserved although product code uses that role.
The [product roadmap](product-direction.md#model-selection-and-compute-priorities) records the
ordered work and adoption gates. No model configuration changes are made by this review.

### Implemented roles

Reviewed against main `e84663086fc4900eeca5082f0aca5595096ac130`. Implemented means there is a
production call path; it does not mean every configured model is running or has passed a quality
comparison. Provider availability and prices must be checked again before an execution campaign.

| Role | Current implementation | Evidence and boundary |
| --- | --- | --- |
| Cited Companion answers | Nebius Token Factory: Nemotron 3 Nano 30B-A3B; Lightning fallback | `exulanica/selection/question.py::compose_answer` uses `REASONING_CHEAP`. The September 9 comparison supports latency and validator conformance on four questions, not general answer quality. |
| Request classification, search planning and appearance drafts | Nebius Token Factory: Qwen3-235B-A22B-Instruct-2507; DeepSeek-V4-Flash-0731 fallback | `propose_plan`, `classify_request` and `draft_appearance` call `STRUCTURED_EXTRACTION`; this is an implemented role, despite the stale reserved-role rationale in the manifest. |
| Photograph observations | Nebius Token Factory: MiniMax M3; MiniCPM-V-4_5 fallback | `exulanica/ingest/vision.py`; observation and evidence validation remain separate. No broad comparison establishes M3 as the most accurate option for our photographs. |
| Caption/text semantic retrieval | Nebius Token Factory: Qwen3-Embedding-8B, 4096 dimensions | `exulanica/epistemics/caption_embeddings.py` and `exulanica/selection/embeddings.py`; lexical and cosine retrieval, not direct image embeddings. No model fallback is configured for embeddings. |
| Object boxes | Grounding DINO Tiny; OWLv2 Base Patch16 Ensemble fallback | `exulanica/ingest/stages/segmentation.py`; local inference when hosted observations lack suitable boxes. |
| Object masks | SAM 2.1 Hiera Tiny | Same segmentation module; masks are distinct from human identity confirmation, source rights and placement into recovered shared coordinates. |
| Single-image geometry | MoGe-2 ViT-L | `exulanica/reconstruction/moge.py` loads the v2 implementation and a pinned checkpoint. MoGe-3 is not an implemented automatic fallback. |
| Multi-view camera recovery | pycolmap 4.2.0 / COLMAP, SIFT and exhaustive matching | `exulanica/reconstruction/pycolmap_executor.py`; registration must be measured before training. MapAnything is not an implemented rescue path. |
| Scene training and compression | gsplat / PyTorch CUDA; PlayCanvas splat-transform | Production trainer and publication boundaries exist. The September 12 generated L40S check validates packaging and forward/backward execution, not personal-place quality. |
| Browser | TypeScript, Vite, DOM UI, PlayCanvas 2.21.4 | The app imports the PlayCanvas binding. Three.js/Spark is retained as a separate implementation; the `atlas-react` package name does not establish a React application. |
| API, durable state and jobs | Python 3.11, FastAPI, Pydantic, PostgreSQL, pgvector, PostgreSQL-backed job leases/retries | Existing replaceable model/stage interfaces and enforced module boundaries are the extension points. No new orchestration framework is selected. |
| Original bytes and compute | Local content-addressed file store; local API/workers and Docker GPU execution; hosted model calls on Nebius | `exulanica/api/services.py` constructs `LocalContentAddressedStore`. Brev/MassedCompute L40S execution is measured; Nebius GPU hosting and an S3 store implementation are not established by that run. |

Nemotron Super and Ultra are configured roles but have no production caller in the reviewed
Python code. Fallback in the hosted client is provider-error handling, not a quality escalation
policy. DINOv2 appearance embeddings, YuNet/SFace biometric recognition, speech models, a learned
reranker and MapAnything appear in earlier plans or candidate discussions, not in implemented
model paths found by this review. Do not count them as delivered capabilities.

### Decision and evidence

**DECISION:** retain the implemented stack as the comparison baseline. Add the evaluations in the
roadmap, then promote the model or stage that improves the declared user task within measured
runtime limits. No model family, parameter count, vendor benchmark or successful import establishes
an absolute best stack. A candidate that materially improves the task is worth additional compute
when it fits the demonstrated hardware and interaction budget; cheapest is not the selection rule.

The [September 9 comparison](evaluation/2026-09-09-companion-memory.json) recorded median Nano
latency 3627 ms versus Lightning 18617 ms at the selected ceiling, with zero Nano validator
rejections in 24 calls. Its answer-quality measurement is explicitly null. The
[September 12 Companion record](evaluation/2026-09-12-companion-quality.json) prepares retrieval
checks and an evaluation corpus; live answers and human quality judgments remain pending. The
[segmentation record](evaluation/2026-09-11-scene-segments-production.json) records masks but no
positive first-place person lift because pose was absent. The
[GPU record](evaluation/2026-09-12-place-compute-readiness.json) establishes generated CUDA
execution and cleanup at a displayed provider charge of $0.23. None proves an optimal model set.

### Candidate capabilities checked against primary sources

Retrieved 2026-09-12. These sources establish what can be evaluated, not a measured benefit in
Exulanica. Pin exact checkpoint revisions and verify runtime compatibility before comparison.

| Candidate | Reason to evaluate | What is not established |
| --- | --- | --- |
| [SAM 2.1 Base+ or Large](https://github.com/facebookresearch/sam2) | Larger variants of the current segmentation family exist, allowing a comparison with Tiny on the same prompts and masks | Improved boundary quality or acceptable memory/latency on our photographs |
| [SigLIP 2 Base Patch16 224](https://huggingface.co/google/siglip2-base-patch16-224) | Image/text representations could retrieve visual details omitted by captions | Better retrieval on our queries, or identity matching across photographs |
| [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | A separate query/document reranker could improve ordering when relevant evidence is already retrieved | Token Factory availability, deployment cost, or a cure for missing candidate evidence |
| [MapAnything Apache variant](https://github.com/facebookresearch/map-anything) | Feed-forward multi-view reconstruction is a candidate when otherwise suitable captures fail the current pose pipeline | Reliable recovered geometry on our scenes; learned predictions still require independent validation |
| [MoGe-3](https://github.com/microsoft/MoGe) | A finer single-image geometry candidate for the Linux GPU path | A macOS replacement or a fix for absent multi-view coverage; upstream reports no macOS support |
| [SAM 3](https://github.com/facebookresearch/sam3) | Text/concept-driven detection and segmentation may address a failure that larger SAM 2 masks cannot | A compatible replacement under our deployment and license constraints; it uses the SAM License and a different integration |

**Scale boundary:** the current exact search uses `halfvec(4096)`. Standard pgvector HNSW/IVFFlat
half-vector indexes support at most 4000 dimensions. Before claiming large-library scalability,
compare indexed reduced-dimension/subvector or quantized recall with exact full-vector reranking
and permission filtering; changing a model or vector space needs versioned re-embedding, not
mixing old and new vectors. [Primary limit](https://github.com/pgvector/pgvector#hnsw).
The current file store and worker topology also need shared-storage and concurrency evidence
before a multi-host claim. Reuse their interfaces; do not introduce infrastructure on speculation.

The [hackathon criteria](https://nebiusglobalaihackathon.devpost.com/) require Nebius execution and
an NVIDIA open model, and assess implementation, coherent design, impact and originality. They
do not require every role to use NVIDIA or reward parameter count. Keep functional Nemotron use
in the demonstrated experience and identify the actual executed model/provider.

---

## Historical research context

Historical status: mixed. Every claim below carries exactly one label. Retrieval date for all VERIFIED claims is
**2026-08-27**, except the two deprecation notices cited in section 3, which were re-read on
**2026-08-28** and carry that date inline.

Label key, matching `docs/README.md`:
**VERIFIED** (primary source URL plus retrieval date) / **DECISION** (records the rejected
alternative) / **ASSUMPTION** (names the experiment that settles it) / **OPEN** (unresolved).

Scope note, because it changes what appears here. The corpus is a personal **photograph** library.
There is no video and no audio. Nebius Token Factory has zero audio capability, so the "recurring
voices" and "conversations" pillars have neither a platform path nor source material and are deferred
with an honest explanation rather than claimed. See section 8.

One thing to hold onto while reading section 2: **"verified" means the exact identifier string was
read from a primary source on 2026-08-27. It does not by itself mean the model has been invoked.**
One identifier, `nvidia/Nemotron-3_5-Lightning`, has been called for real and its response archived;
the rest are catalog-verified only. Catalog presence is not runtime behaviour. Where a claim rests on
execution, [runtime-verification.md](runtime-verification.md) is the source and it overrides this
document on conflict. Section 7 sets out what may and may not be said as a result.

---

## 1. The platform split

Three execution surfaces. Each boundary is placed by a property the other two surfaces do not have,
not by convenience.

| Surface | Billing | What runs there |
| --- | --- | --- |
| **Nebius Token Factory** | per token, serverless | Reasoning core (text Nemotron), vision sensor over photographs, text embeddings, optional rerank |
| **Nebius AI Cloud** | per GPU hour and per vCPU/GiB hour | Camera pose and splat training jobs, API process, PostgreSQL, object storage, local-class perception models that need a GPU |
| **Browser** | free | Splat and 2.5D rendering, camera, DOM overlay UI and the accessibility surface, evidence playback |

### 1.1 Why inference sits on Token Factory

**VERIFIED.** Token Factory is a single global OpenAI-compatible endpoint at
`https://api.tokenfactory.nebius.com/v1/`, Bearer auth, usable through the stock `openai` SDK with
`base_url` overridden. Source: https://docs.tokenfactory.nebius.com/api-reference/introduction

**DECISION.** All LLM and VLM inference goes to Token Factory serverless, never to a self-hosted
model server. Rejected alternative: self-host the vision and reasoning models on Nebius AI Cloud.
Rejected on arithmetic, not preference. A full inference pass over the corpus costs roughly **$0.41**
(section 5.3). One `gpu-l40s-a` `1gpu-8vcpu-32gb` instance in eu-north1 costs
`1.35 + (8 x 0.012) + (32 x 0.0032) = $1.548/hr` on demand, so a single idle GPU exceeds the entire
projected inference bill of the project in under twenty minutes.
Source: https://docs.nebius.com/compute/resources/pricing

**DECISION.** Use only the global base URL. Never hardcode a regional Token Factory host.
**VERIFIED** rationale: Token Factory public endpoints report Region "Global", Nebius warns the
processing location "can change at any time, without notice", and that a regional base URL "can stop
working if the endpoint's processing region changes".
Source: https://docs.tokenfactory.nebius.com/ai-models-inference/overview
Consequence: the per-model `regions` strings in section 2 are informational for latency reasoning.
They are not addressable and nothing in the code may branch on them.

### 1.2 Why reconstruction, the database and the API sit on AI Cloud

**VERIFIED.** Token Factory has no raw GPU VM and no arbitrary container. Its only custom-weights
path is Dedicated Endpoints, "currently in beta and available on request", covering supported LLM
architectures. Source: Token Factory docs, dedicated-endpoints/custom-weights

COLMAP and gsplat are neither an LLM nor an API-shaped workload, so they cannot run on Token Factory
at all. They run as Nebius Serverless AI Jobs, which take the same `--platform` and `--preset` values
as Compute VMs including `--preemptible`, are billed per second, and self-terminate.
**VERIFIED**, source: https://docs.nebius.com/serverless/jobs/manage

**DECISION.** Pin every GPU workload to **eu-north1**. **VERIFIED** reason: eu-north1 is the only
region with a non-zero default L40S quota (L40S = 2, H100 = 32, H200 = 32). us-central1 has no GPU
type with a non-zero default at all, and the custom-image quota is 0 in every region, so the pipeline
ships as containers and never as a baked image.
Source: https://docs.nebius.com/compute/resources/quotas-limits

**DECISION.** The API process and PostgreSQL run on a plain `cpu-d3` Compute VM with a restart policy
and a Network SSD volume. Rejected alternative: put both on Nebius Serverless AI endpoints, which
follows the platform's own Serverless Endpoints guidance more closely. Rejected because Serverless
AI is **VERIFIED** as Preview with "no Service Level provided for the Service" and "does not provide
automatic retry, recovery, or redundancy mechanisms", endpoint lifetime is documented as "hours to
days", and the demo must survive unattended for roughly 46 days.
Serverless AI applies Compute pricing, so the cost is identical either way and the reliability is not.
Sources: https://docs.nebius.com/legal/specific-terms/serverless-ai ,
https://docs.nebius.com/serverless/overview , https://docs.nebius.com/serverless/pricing-quotas
Jobs are retained precisely because a failed job is retryable and a failed database is not.

**DECISION.** Not Nebius Managed PostgreSQL. **VERIFIED** cost: the documented `4vcpu-16gb` example
is $0.28/hr, about $204/month, for a database that will not reach 1 GB.
Source: https://docs.nebius.com/postgresql/resources/pricing

### 1.3 Why the browser gets rendering and nothing else

**DECISION.** The browser renders and navigates. It holds no credential, calls no model provider, and
constructs no external query. Every live-web lookup is server-constructed and opt-in. Two reasons,
one performance and one security:

- Rendering is a per-frame budget. A splat scene at 60 fps cannot round-trip anything to a server, so
  the frame loop must be entirely local. The scene budget is capped by **measured frame time**, never
  by device sniffing, so no guessed hardware number is ever load-bearing.
- The browser is the untrusted surface. Query construction is exactly where an injected instruction
  would try to act, so it stays server side.

**DECISION.** No model inference runs in the browser. There is no browser-side model in the plan and
none is needed: every inference in this system is either a Token Factory call or an offline job.

**VERIFIED.** Canvas content is invisible to screen readers, so the DOM overlay is the accessibility
surface and must carry real focusable labelled elements for every entity, evidence item and source
moment.

**RESOLVED, PlayCanvas Engine 2.21.4.** The research recorded this as genuinely unresolved:
`browser-rendering` recommended PlayCanvas, `interaction-architecture` designed the Companion,
Atlas and overlay system against three.js / react-three-fiber, and neither picked a winner on
evidence. A matched-resolution bake-off settled it on 2026-08-28, and the reasoning and the
numbers are in [adr/0003-renderer-selection.md](adr/0003-renderer-selection.md). Not a model
selection question, recorded here only because it sits on this boundary.

---

## 2. Model and service matrix

**Verified column semantics.** "Catalog" means the exact identifier string was read from
`https://tokenfactory.nebius.com/api/public/models_info` on 2026-08-27, which Nebius states verbatim
is "the authoritative machine-readable source". "Card" means the model card was read at its primary
URL. **Neither means the model has been invoked.** Region is informational only (section 1.1).

### 2.1 Nebius Token Factory, per token

| Role | Model, exact identifier | Price in / out per M tokens | Context | Region | License (catalog) | Verified | Declared fallback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Reasoning core, Companion dialogue, cross-scene continuity, NVIDIA compliance | `nvidia/Nemotron-3_5-Lightning` | $0.06 / $0.24 | 1024K | eu-north1 | OpenMDW v1.1 | catalog | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Escalation tier, only on measured Lightning failure | `nvidia/nemotron-3-super-120b-a12b` | $0.30 / $0.90 | 256K | us-central1 | nvidia-open-model-license | catalog | `nvidia/Nemotron-3_5-Lightning` (degrade, do not fail) |
| Reasoning fallback, identical price and role | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | $0.06 / $0.24 | 262K | eu-north1 | nvidia-open-model-license | catalog | `nvidia/Nemotron-3_5-Lightning` |
| Manual escalation ceiling, not routed to by default | `nvidia/Nemotron-3-Ultra-550b-a55b` | $1.00 / $3.00 | 1024K | us-central1 | openmdw-1.1 | catalog | n/a, not in the default route |
| Vision sensor over photographs | `openbmb/MiniCPM-V-4_5` | $0.658 / $1.11 | **32K** | eu-north1 | Apache 2.0 | catalog | `MiniMaxAI/MiniMax-M3` |
| Vision sensor fallback, and Nebius' own recommended replacement for the removed `nvidia/Cosmos3-Super-Reasoner` | `MiniMaxAI/MiniMax-M3` | $0.30 / $1.20 | 1049K | us-central1 | "MiniMax-M3", **unverified** | catalog | `openbmb/MiniCPM-V-4_5` |
| Structured extraction, only if Nemotron schema conformance fails | `Qwen/Qwen3-235B-A22B-Instruct-2507` | $0.20 / $0.60 | 262K | eu-north1 | Apache 2.0 | catalog | `deepseek-ai/DeepSeek-V4-Flash-0731` |
| Text embeddings | `Qwen/Qwen3-Embedding-8B` | $0.01 / $0.00 | 41K | eu-north1 | Apache 2.0 | catalog | **none on Token Factory, see 2.4** |
| Reranking | `Qwen/Qwen3-Embedding-8B` on `POST /v1/rerank` | $0.01 / $0.00 | 41K | eu-north1 | Apache 2.0 | **no**, endpoint verified, model compatibility unverified | RRF over a tsvector arm and a vector arm computed in SQL |

**VERIFIED, and this is the trap that costs an afternoon.** The catalog's human-readable `name` field
differs from the callable `model_id`. Casing and separators are inconsistent across the Nemotron
line: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` doubles the vendor prefix,
`nvidia/nemotron-3-super-120b-a12b` is entirely lowercase, `nvidia/Nemotron-3_5-Lightning` uses an
underscore where the display name uses a dot. **Code reads `flavors[].model_id`, never `name`.** A
typo is a silent 404-class failure. Source: https://tokenfactory.nebius.com/api/public/models_info

**VERIFIED.** Catalog license strings disagree with HuggingFace card frontmatter, consistently in the
stricter direction: the catalog labels `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and
`nvidia/nemotron-3-super-120b-a12b` as `nvidia-open-model-license` (revocable, guardrail-conditioned,
unilaterally amendable) where the HuggingFace frontmatter reads `nvidia-nemotron-open-model-license`
(irrevocable, no guardrail clause, no unilateral amendment). These are genuinely different documents.
**DECISION.** `THIRD_PARTY_LICENSES.md` records the license read from raw HuggingFace YAML
frontmatter at a pinned revision SHA, never the Nebius catalog string and never the family name.
Sources: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/ ,
https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license

### 2.2 Nebius AI Cloud, per GPU hour

| Role | Component | Shape and price | Region | Verified | Fallback |
| --- | --- | --- | --- | --- | --- |
| Camera poses | COLMAP 4.x sparse pipeline, CPU-only path | Serverless Job, or local | eu-north1 | card, CPU path confirmed | `facebook/map-anything-apache` as automatic rescue |
| Splat training | `nerfstudio-project/gsplat`, MCMC, 1M cap | `gpu-l40s-a` `1gpu-8vcpu-32gb`, $1.548/hr on demand, $0.749/hr preemptible, `--preemptible` | eu-north1 | card | Brush on Metal locally (Apache-2.0) |
| Monocular metric depth, the 2.5D rung | `Ruicheng/moge-2-vitl` | local M3 Pro, MIT | n/a | card, MIT confirmed | `Ruicheng/moge-3-vitl` on the Nebius Linux GPU (MoGe-3 has no macOS path) |
| Segmentation for people-masking before reconstruction | `facebook/sam2.1-hiera-tiny` | AI Cloud GPU | eu-north1 | card, Apache-2.0 confirmed | none. **Never SAM 3** |
| Open-vocabulary detection | `IDEA-Research/grounding-dino-tiny` via transformers | AI Cloud GPU, MPS locally | eu-north1 | card | `google/owlv2-base-patch16-ensemble` |
| Appearance vector | `facebook/dinov2-base` | GPU or MPS | eu-north1 | card | CLIP (MIT) |
| API and PostgreSQL | PostgreSQL 18.6 + pgvector >= 0.8.6, `halfvec(4096)`, exact search (CORRECTED, see runtime-verification.md section 7) | `cpu-d3 2vcpu-8gb` Compute VM, Network SSD | eu-north1 | versions | none. Do **not** use Managed PostgreSQL |
| Object storage | Nebius Object Storage, `https://storage.eu-north1.nebius.cloud` | Intelligent class, versioned at bucket creation | eu-north1 | docs | none |

**VERIFIED.** Nebius Object Storage does not support Object Lock or Legal Hold: "Write-once-read-many
(WORM) retention policies are not supported." **DECISION.** Say "append-only by policy" in product
copy, never "immutable", "WORM" or "tamper-proof".
Source: https://docs.nebius.com/object-storage/interfaces/s3-api-compatibility

### 2.3 Local CPU, no hosting cost

| Role | Model | License status | Verified | Fallback |
| --- | --- | --- | --- | --- |
| Face detection | `opencv_zoo/models/face_detection_yunet` (`2026may` ONNX) | LICENSE read | yes | none needed |
| Face alignment | `shape_predictor_5_face_landmarks.dat` | permissive | yes | none. **Never the 68-point model** |
| Face embeddings | `opencv_zoo/models/face_recognition_sface` ONNX | LICENSE read | yes | `dlib_face_recognition_resnet_model_v1` |
| Splat compression | `@playcanvas/splat-transform` v3.3.3 | MIT | yes | none |

**DECISION.** Never vendor weights. One `models.manifest.json` carries repo id plus revision SHA plus
the license read from raw HuggingFace frontmatter, and CI re-fetches each pinned revision's license
and fails on drift. The repository is Apache-2.0 and the five most likely accidental violations are
all silent transitive ones: `pip install insightface` pulling buffalo_l, linking the INRIA
`diff-gaussian-rasterization` kernel, the 68-point dlib predictor, Ultralytics arriving through a
tracking library, and an unpinned NVIDIA tag where v1 is CC-BY-NC and v2.1 is not.

### 2.4 The embedding role has no same-tier fallback

**VERIFIED.** The Token Factory catalog contains exactly one model of type `embedding`:
`Qwen/Qwen3-Embedding-8B`. Counted across all 30 entries in
`https://tokenfactory.nebius.com/api/public/models_info`, retrieved 2026-08-27.

**Consequence, stated plainly because it is a hole in the mitigation in section 6.** Every other role
has a declared fallback that is another Token Factory identifier and can therefore be swapped at
runtime. The embedding role does not. Its declared fallback, `nvidia/Nemotron-3-Embed-1B-BF16`
(OpenMDW-1.1, 2048-dim), is a self-hosted deployment, which is a build-time change and not a runtime
failover.

**OPEN.** Whether to pre-build the self-hosted embedding path as a warm standby, accept a
single-point dependency for the unattended deployment window, or precompute and freeze all embeddings
before deployment so the demo never calls the embedding endpoint at all. The third option is the
cheapest and probably correct, but it has not been designed and it interacts with whether new
captures can be ingested once the deployment is running.

### 2.5 Non-model services

| Role | Service | Terms | Verified | Fallback |
| --- | --- | --- | --- | --- |
| Public-entity lookup | Tavily Search API | free tier 1,000 credits/month, resets on the 1st, pay-as-you-go $0.008/credit | https://www.tavily.com/pricing | **cut the feature.** A leaky gate is worse than no feature |
| SPA hosting | Vercel Hobby, static | $0 | yes | Cloudflare Workers Static Assets |
| Edge cache, optional | Cloudflare proxy in front of the Nebius origin | n/a | yes | none, the Nebius origin serves directly |

**DECISION.** The asset origin stays on Nebius Object Storage. Rejected alternative: Cloudflare R2,
whose free egress would save roughly $2 to $10 across the project. Rejected because keeping the origin
on Nebius keeps the platform constraint in section 7 literally true, which is worth more than $10. A
Cloudflare cache in front of the Nebius origin is fine and is recommended for users outside Europe.

**VERIFIED.** Tavily "may use portions of query data to improve future responses" and shares query
data with third-party search index providers where its own index cannot retrieve content, advising
users to avoid personal information in queries. Source: https://www.tavily.com/privacy
**DECISION.** Tavily queries are server-constructed, opt-in, and never carry personal content from
the corpus.

---

## 3. The 2026-08-31 deprecation

**VERIFIED.** On 2026-08-31, from Token Factory **Serverless only** (Dedicated Endpoints unaffected),
Nebius removes ten models. Verbatim from the notice, with Nebius' own recommended replacement:

| Removed 2026-08-31 | Nebius' recommended replacement |
| --- | --- |
| `nvidia/Nemotron-3-Nano-Omni` | `nvidia/Nemotron-3_5-Lightning` |
| `nvidia/Cosmos3-Super-Reasoner` | `MiniMaxAI/MiniMax-M3` |
| `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` | `nvidia/nemotron-3-super-120b-a12b` |
| `Qwen/Qwen2.5-VL-72B-Instruct` | `MiniMaxAI/MiniMax-M3` |
| `meta-llama/Llama-3.3-70B-Instruct` | `nvidia/Nemotron-3_5-Lightning` |
| `MiniMaxAI/MiniMax-M2.5` | `MiniMaxAI/MiniMax-M3` |
| `NousResearch/Hermes-4-70B` | `nvidia/Nemotron-3_5-Lightning` |
| `Qwen/Qwen3-32B` | `nvidia/Nemotron-3_5-Lightning` |
| `Qwen/Qwen3-Next-80B-A3B-Thinking` | `Qwen/Qwen3.5-397B-A17B` |
| `deepseek-ai/DeepSeek-V4-Flash` | `deepseek-ai/DeepSeek-V4-Flash-0731` |

Source: https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice (retrieved 2026-08-27,
re-verified against the notice 2026-08-28: the same ten models, the same replacement column, and the
notice states the change affects Serverless only and leaves Dedicated Endpoints unaffected)

**VERIFIED.** The two NVIDIA models removed, `nvidia/Nemotron-3-Nano-Omni` and
`nvidia/Cosmos3-Super-Reasoner`, are the only two NVIDIA models in the catalog that declare an
`image` use case. **After 2026-08-31 there is no NVIDIA vision or multimodal model on Token Factory
Serverless.**

**CORRECTED 2026-08-28.** An earlier draft of this section said Nebius recommends
`MiniMaxAI/MiniMax-M3` as the replacement for both removed NVIDIA vision models. It does not, and the
notice is sharper than that. `nvidia/Cosmos3-Super-Reasoner` is mapped to the non-NVIDIA
`MiniMaxAI/MiniMax-M3`, while `nvidia/Nemotron-3-Nano-Omni` is mapped to
`nvidia/Nemotron-3_5-Lightning`, which is NVIDIA but declares no `image` use case (section 4).
**Neither recommended replacement keeps both the vendor and the modality**, which is the conclusion
above stated inside Nebius' own mapping.
Source: https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice (retrieved 2026-08-28)

**Nothing in section 2 depends on a removed model.** Every Token Factory identifier in the matrix,
primary and fallback alike, survives 2026-08-31. This is a design constraint that was applied before
the matrix was written, not a coincidence, and it is why the reasoning core is a text Nemotron and
the vision sensor is not NVIDIA. The rejected alternatives are recorded in `adr/0002-model-routing.md`.

**VERIFIED, second round, for cadence. CORRECTED 2026-08-28.** Nebius removed 11 models on
2026-06-22: seven `-fast` identifiers (`deepseek-ai/DeepSeek-V3.2-fast`,
`MiniMaxAI/MiniMax-M2.5-fast`, `moonshotai/Kimi-K2.5-fast`, `openai/gpt-oss-120b-fast`,
`Qwen/Qwen3-235B-A22B-Thinking-2507-fast`, `Qwen/Qwen3-Next-80B-A3B-Thinking-fast`,
`Qwen/Qwen3.5-397B-A17B-fast`) plus four base identifiers (`deepseek-ai/DeepSeek-V3.2`,
`moonshotai/Kimi-K2.5`, `PrimeIntellect/INTELLECT-3`, `zai-org/GLM-5`). An earlier draft listed six
`-fast` flavors and two base models, which is eight, not 11. Unlike the August notice, the June
notice carries **no per-model recommended-replacement column**: it points readers at Dedicated
Endpoints and states that Token Factory does not automatically reroute requests from a deprecated
model.
Source: https://docs.tokenfactory.nebius.com/june-2026-deprecation-notice (retrieved 2026-08-28)

**VERIFIED.** All seven `-fast` identifiers were removed in June and zero `-fast` identifiers remain
in the live catalog, yet the inference overview page still documents the flavor as a live feature
("To use the Fast flavor, append `-fast` to the model name"). Related staleness: the
vision-capabilities examples page still shows `Qwen/Qwen2-VL-72B-Instruct` and
`meta-llama/Meta-Llama-3.1-70B-Instruct`, neither of which exists in the catalog.
**DECISION.** Treat only `models_info` and `openapi.json` as authoritative. Never copy a model
identifier out of a documentation example.

---

## 4. The catalog `type` field is unreliable. OPEN.

**VERIFIED, from the primary catalog JSON.** The catalog carries both a coarse `type` field and a
`use_cases` array, and they disagree. Four models typed `text2text` declare `image` in `use_cases`,
and one of those also declares `video`:

| Model | `type` | `use_cases` includes | Survives 2026-08-31 |
| --- | --- | --- | --- |
| `nvidia/Nemotron-3-Nano-Omni` | `text2text` | `image` | no |
| `MiniMaxAI/MiniMax-M3` | `text2text` | `image`, `video` | yes |
| `google/gemma-3-27b-it` | `text2text` | `image` | yes |
| `moonshotai/Kimi-K2.7-Code` | `text2text` | `image` | yes |

Source: https://tokenfactory.nebius.com/api/public/models_info (retrieved 2026-08-27)

The Nano Omni case is the clearest evidence that `type` is a coarse label rather than a capability
statement. Its own catalog `description` reads "The most open, efficient, and accurate omni-modal
reasoning model for agentic AI" and its `huggingface_url` points at
`nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8`, whose card documents video, audio, image and
text input. It is typed `text2text` anyway.

**VERIFIED.** The API schema is model-agnostic. `ChatCompletionMessage.content` is a discriminated
union of exactly three part types (`text`, `image_url`, `video_url`), so the request will validate
against any model. Capability is a per-model property, and `use_cases` is the only per-model
capability signal the catalog publishes. Source: https://api.tokenfactory.nebius.com/openapi.json

**VERIFIED.** `MiniMaxAI/MiniMax-M3` is the only model in the entire catalog declaring the `video`
use case.

**OPEN.** `use_cases` **appears** to be authoritative and `type` **appears** to be a coarse
categorisation, but this is inference from a field-level disagreement, not a documented contract.
Nebius does not document the relationship between the two fields. Two streams reading the same JSON
and reaching the same conclusion is agreement, not evidence.

**The experiment that settles it, and it is one call.** Send a single `image_url` content part to
`MiniMaxAI/MiniMax-M3` (typed `text2text`, declares `image`) and record the response. A 200 with a
coherent description of the image settles it in favour of `use_cases`. A 4xx rejecting the content
part settles it in favour of `type`, and invalidates the vision-sensor fallback in section 2.1.
Repeat once against `openbmb/MiniCPM-V-4_5` (typed `image2text`) as the control. Fifteen minutes,
blocked only on credentials.

**DECISION, pending that call.** Code selects models by reading `use_cases`, and the build-time
preflight (section 6) asserts on `use_cases` rather than on `type`. The primary vision sensor
`openbmb/MiniCPM-V-4_5` is typed `image2text` **and** declares `image`, so both readings agree on it
and the primary path does not depend on resolving this. Only the declared fallback does.

---

## 5. Routing and cost discipline

### 5.1 The routing table

| Traffic | Model | Why this tier |
| --- | --- | --- |
| Every Companion dialogue turn | `nvidia/Nemotron-3_5-Lightning` | 3B active parameters, validated to 1M context, card describes it as built for "long-running autonomous agents, sub-agent workhorse deployments". Cheapest tier in the NVIDIA line and the largest context in it |
| Every cross-scene continuity decision over an evidence packet | `nvidia/Nemotron-3_5-Lightning` | Context length, not parameter count, is the binding constraint. The packet is many scenes, many entity records, many evidence spans. 1024K context at $0.06/M input is the correct shape for a long, shallow reasoning task |
| One structured-extraction pass per photograph, at ingest only | `openbmb/MiniCPM-V-4_5` | Runs once per photograph, never per dialogue turn. Carries the catalog's "JSON mode" tag, which no surviving text Nemotron does (section 5.4) |
| Continuity decisions **only** where Lightning is measured to fail | `nvidia/nemotron-3-super-120b-a12b` | 12B active against 3B, bought only where wrong answers are most expensive, and only after a measurement says Lightning is the reason |
| Nothing, by default | `nvidia/Nemotron-3-Ultra-550b-a55b` | See 5.2 |

**DECISION.** One model serves both dialogue and continuity reasoning. Rejected alternative: a
separate heavier model for continuity, which is what the raw research recommended before the
Lightning context window was weighed against it. Collapsing both onto Lightning removes an entire
model from the routing surface, and the escalation path to Super remains available the moment a
measurement justifies it.

**ASSUMPTION.** That Lightning is sufficient for cross-scene continuity resolution. Nobody measured
it. Validation: run the continuity task on Lightning and on Super over the same evidence packets and
compare against user-confirmed ground truth. If Lightning holds, the system stays at one text model.

### 5.2 Why the default route is not Ultra, with the arithmetic

Guidance published for the Nemotron line says "Reach for Nemotron 3 Ultra when you need serious
reasoning, and let Nano or Super handle the fast, everyday calls". This section is the honest answer
to why the routing table does not do that.

**ASSUMPTION**, and every number below inherits it: a representative turn is **8,000 input tokens and
800 output tokens**. The input is long because each turn carries an evidence packet plus prior entity
state. Validation: read `usage.prompt_tokens` and `usage.completion_tokens` from twenty real turns
and replace the assumption with a measured distribution. Fifteen minutes once credentials exist.

Prices are **VERIFIED** per million tokens from the catalog JSON, retrieved 2026-08-27.

| Model | in / out per M | 8,000 input | 800 output | **Per turn** | 300 turns | Relative to Lightning |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `nvidia/Nemotron-3_5-Lightning` | $0.06 / $0.24 | $0.000480 | $0.000192 | **$0.000672** | $0.2016 | 1.00x |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | $0.06 / $0.24 | $0.000480 | $0.000192 | **$0.000672** | $0.2016 | 1.00x |
| `nvidia/nemotron-3-super-120b-a12b` | $0.30 / $0.90 | $0.002400 | $0.000720 | **$0.003120** | $0.9360 | 4.64x |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | $1.00 / $3.00 | $0.008000 | $0.002400 | **$0.010400** | $3.1200 | **15.48x** |

Routing an identical turn to Ultra instead of Lightning costs **15.48 times as much**. Against the
roughly $50 of Token Factory budget the project expects, that is about **74,400 Lightning turns
versus about 4,800 Ultra turns**. The absolute amounts are small either way, which is exactly why the
discipline has to be an argument rather than a budget: nothing stops the project routing to Ultra
except the absence of a reason.

**DECISION.** Ultra stays in the manifest as an available escalation and is not in any default route.
It is used only when a measurement shows Lightning and Super both failing a specific task, and the
measurement is recorded next to the routing change. Rejected alternative: default to Ultra for
"serious reasoning" as that guidance suggests. Rejected because Ultra's advantage over Lightning
on this project's tasks has never been measured, and paying 15.48x for an unmeasured advantage is the
kind of claim the project has committed not to make. Note that the routing table also gives Ultra
nothing it is uniquely good at: Lightning already carries the same 1024K context.

### 5.3 Full-corpus pass cost

**ASSUMPTION.** 150 photographs, roughly 1,500 input tokens and 300 output tokens per image, plus 300
text reasoning calls at the 8,000 / 800 shape, plus roughly 1M tokens embedded. The per-image token
figure is the single number the entire vision cost model rests on and it has never been measured.
Validation: one real call, read `usage.prompt_tokens`, then repeat at 2, 4 and 8 images to separate
the per-image slope from the fixed overhead.

| Stage | Model | Arithmetic | Cost |
| --- | --- | --- | ---: |
| Vision, 225,000 in / 45,000 out | `openbmb/MiniCPM-V-4_5` | 0.225 x $0.658 + 0.045 x $1.11 | $0.198 |
| Vision alternative | `MiniMaxAI/MiniMax-M3` | 0.225 x $0.30 + 0.045 x $1.20 | $0.122 |
| Text reasoning, 2.4M in / 0.24M out | `nvidia/Nemotron-3_5-Lightning` | 2.4 x $0.06 + 0.24 x $0.24 | $0.202 |
| Embeddings, 1M tokens | `Qwen/Qwen3-Embedding-8B` | 1.0 x $0.01 | $0.010 |
| **Complete pass** | | | **$0.41** |

At twenty times that for development iteration, retries and prompt tuning, total Token Factory spend
across the project is roughly **$10 to $25**. Inference is not where this project's money goes. GPU
time for reconstruction and continuous hosting are, and the single largest cost risk is a forgotten
GPU VM at $1.548/hr, because quotas count stopped VMs and volumes bill whether attached or not.

### 5.4 Structured output is the routing risk, not cost

**VERIFIED.** Only `deepseek-ai/DeepSeek-V4-Flash`, `deepseek-ai/DeepSeek-V4-Flash-0731`,
`nvidia/Cosmos3-Super-Reasoner` and `openbmb/MiniCPM-V-4_5` carry the catalog's "JSON mode" tag.
**No surviving text Nemotron carries it.** Separately, the live OpenAPI spec's own `response_format`
description states "Only {'type': 'json_object'} or {'type': 'text' } is supported", which
contradicts the documentation page describing `json_schema` support.
Sources: https://tokenfactory.nebius.com/api/public/models_info ,
https://api.tokenfactory.nebius.com/openapi.json , https://docs.tokenfactory.nebius.com/ai-models-inference/json

**ASSUMPTION.** That `nvidia/Nemotron-3_5-Lightning` honours `response_format: json_schema` reliably
enough to emit schema-valid structured answers. Validation: 20 identical nested-schema requests with
`strict: true`, then the same 20 through `extra_body.guided_json`, measuring conformance rate. Two
hours. If it fails, the declared fallback for structured extraction is
`Qwen/Qwen3-235B-A22B-Instruct-2507`, which is Apache-2.0 and carries the JSON mode tag, and the
reasoning core keeps the NVIDIA compliance role while giving up the extraction role.

Noting the shape of that failure honestly: it would not break NVIDIA compliance, but it would mean
the NVIDIA model produces prose that a second model structures, which is a weaker story than the one
in section 7.

---

## 6. Deprecation during an unattended deployment

**VERIFIED.** Two deprecation rounds in roughly ten weeks: 11 models removed 2026-06-22, 10 more
2026-08-31. **DECISION.** The hosted demo must run unattended for about 46 days after feature freeze,
with nobody watching it and no opportunity to ship a fix.

**ASSUMPTION**, high plausibility, and the one assumption here that cannot be validated in advance:
at that cadence there is a material chance of another deprecation round landing between feature
freeze and the end of the unattended window. A user opening the demo six weeks after freeze could hit
a hard 404-class failure on a removed model identifier with nobody watching. This risk was not
visible in any single research stream. It falls out of putting the deprecation cadence next to the
deployment calendar.

**DECISION.** Four mitigations, all structural, because the risk cannot be prevented.

1. **One model manifest.** Every model identifier lives in a single `models.manifest.json`, never
   inlined at a call site. Each entry carries the role, the primary identifier, the declared fallback
   identifier, the region string, and the licence read from raw HuggingFace frontmatter at a pinned
   revision SHA.
2. **Build-time preflight.** The build fetches
   `https://tokenfactory.nebius.com/api/public/models_info` and fails if any referenced identifier is
   absent from `flavors[].model_id`, or if a referenced model no longer declares the `use_cases`
   entry the role needs. This also catches documentation staleness (section 3) and identifier typos
   (section 2.1) at build time instead of at demo time.
3. **Runtime fallback, exercised in CI.** Every Token Factory role has a declared fallback identifier
   in the manifest, selected automatically on a 404-class error. CI runs the fallback path on every
   build by forcing the primary identifier to fail, so the fallback is known-good rather than
   theoretical. A fallback that has never executed is not a mitigation.
4. **Catalog diff in the weekly check.** The weekly uptime check, which runs for the whole
   unattended window, diffs the live catalog against the manifest and alerts on any referenced
   identifier disappearing, rather than only pinging `/healthz`. A `/healthz` that returns 200 while
   the reasoning model has been removed is exactly the failure this is for.

**Degradation, not death.** With the fallbacks in place a deprecation mid-window degrades answer
quality silently instead of killing the demo. That is the honest description of the outcome and the
one to use in the README and the documentation.

**Known gap.** The embedding role has no same-tier fallback (section 2.4), so mitigations 1, 2 and 4
apply to it but mitigation 3 does not. This is unresolved and it is the weakest point in the plan.

**A second, smaller gap.** All four mitigations sit on Token Factory. The NVIDIA licence documents
governing the model weights are separately amendable: the NVIDIA Open Model License states NVIDIA
"may update this Agreement to comply with legal and regulatory requirements at any time", where the
Nemotron Open Model License and OpenMDW-1.1 do not carry that clause. This is one more reason the
reasoning core is on the OpenMDW-1.1 model rather than on one of the models the catalog labels
`nvidia-open-model-license`.

---

## 7. What may and may not be claimed about NVIDIA model use

**VERIFIED, platform constraint, verbatim.** The architecture was built around a stated constraint
on where the project runs and what it must use: "All submissions must run on either Nebius Token
Factory or Nebius AI Cloud and use at least one NVIDIA open source model. Everything else is up to
you." Source: https://nebiusglobalaihackathon.devpost.com/
This is the constraint that puts inference on Nebius and an NVIDIA open model in the reasoning role,
and the alternatives weighed against it are recorded in `adr/0002-model-routing.md`.

**SATISFIED by execution on 2026-08-27.** A real chat completion against
`nvidia/Nemotron-3_5-Lightning` returned HTTP 200 with the model identifier echoed in the response
body, and the full body and response headers are archived. The platform requirement is met by
execution rather than by design. See [runtime-verification.md](runtime-verification.md) section 1,
which overrides this document on conflict.

### 7.1 What the project may say today

- That Exulanica runs `nvidia/Nemotron-3_5-Lightning` on Nebius Token Factory, in the present tense,
  on the evidence of the archived response body and its echoed `model` field.
- That `nvidia/Nemotron-3_5-Lightning` is listed in the Nebius Token Factory catalog at the stated
  price, context window and licence, citing the catalog endpoint and the retrieval date.
- That the architecture routes its reasoning to that model.
- That no model in the plan is scheduled for removal on 2026-08-31.
- The figures actually measured in [runtime-verification.md](runtime-verification.md): image token
  counts at two resolutions, the per-call reasoning-token floor, which structured-output mechanism
  the endpoint honours, the embedding width, and the measured ingestion cost.

### 7.2 What the project still may not say

- Any latency, throughput, quality or accuracy figure that has not been measured. A number is
  claimable only where this project holds the measurement that produced it.
- Anything in the present tense about an identifier that has not itself been called. Section 2 lists
  more identifiers than have been exercised, and catalog presence is not runtime behaviour.
- Any recall or precision figure for cross-capture identity, which is unmeasured and is named as
  unmeasured in [product-specification.md](product-specification.md) section 9.

### 7.3 What closed it

One successful chat completion against `nvidia/Nemotron-3_5-Lightning`, with the **full response body
archived**, including the echoed `model` field (which proves which model actually served the request,
rather than which was requested) and the `x-ratelimit-*` response headers.

**DECISION.** The archived response is a stored artifact, not a screenshot and not a claim in prose,
so the model identifier can be checked against what the platform actually returned. The archive holds
personal and account-identifying response headers, so it lives in the gitignored internal workspace
rather than in the public tree, and [runtime-verification.md](runtime-verification.md) quotes the
fields that matter.

---

## 8. Deferred, with the reason

**DECISION.** The following are out of the plan. They are deferred with a stated reason, not quietly
dropped, and nothing in the README, the documentation or any marketing surface will imply they exist.

| Deferred | Reason |
| --- | --- |
| ASR and word-level timestamps (`nvidia/parakeet-tdt-0.6b-v3` and alternatives) | The corpus is photographs. There is no audio to transcribe, and Token Factory has zero audio capability regardless |
| Diarization (`nvidia/diar_streaming_sortformer_4spk-v2.1`) and speaker embeddings (`nvidia/speakerverification_en_titanet_large`) | Same. Also the reason the "recurring voices" pillar is not claimed |
| Native `video_url` input via `MiniMaxAI/MiniMax-M3` | No video in the corpus. The content part exists in the OpenAPI spec, no documentation page describes it, and no duration, FPS or token limits are published |
| Within-clip tracking (ByteTrack) and SAM 2.1 video mask propagation | Both are video-sequence operations. SAM 2.1 is retained for per-image segmentation before reconstruction |
| `nvidia/Nemotron-3-Nano-Omni` in every form | Removed from Serverless 2026-08-31, and its distinguishing capability (joint video plus audio with word-level timestamps) has no source material here. See `adr/0002-model-routing.md` |

**Cost of the audio deferral, stated because it is real.** The research had identified self-hosted
NVIDIA ASR on Nebius AI Cloud as a second, independent NVIDIA-compliance asset that would also have
demonstrated AI Cloud model usage directly. That asset is gone with the audio pillar. The NVIDIA
compliance story now rests entirely on the text Nemotron path on Token Factory.

**OPEN.** Whether to recover a second NVIDIA asset and an AI Cloud model-usage story by self-hosting
`nvidia/Nemotron-3-Embed-1B-BF16` (OpenMDW-1.1, 2048-dim, 32,768 max sequence) as the text embedder
in place of `Qwen/Qwen3-Embedding-8B`. This would also close the fallback gap in section 2.4. It has
not been costed, it adds a deployment to the critical path, and it must not be adopted for compliance
theatre if the Qwen embedder is measurably better for retrieval. Undecided.

---

## 9. Open items from this document, in one place

| # | Open item | What settles it |
| --- | --- | --- |
| 1 | No model identifier has been invoked. Section 7 | One archived chat completion against `nvidia/Nemotron-3_5-Lightning`, blocked on credentials (Q1) |
| 2 | Whether `use_cases` or `type` is authoritative in the catalog. Section 4 | One `image_url` call to `MiniMaxAI/MiniMax-M3`, with `openbmb/MiniCPM-V-4_5` as the control |
| 3 | The embedding role has no same-tier runtime fallback. Sections 2.4 and 6 | A decision between a warm self-hosted standby, an accepted single point of failure, or freezing all embeddings before deployment |
| 4 | Whether to self-host `nvidia/Nemotron-3-Embed-1B-BF16` as a second NVIDIA asset. Section 8 | A retrieval-quality comparison against `Qwen/Qwen3-Embedding-8B`, plus a deployment cost estimate |
| 5 | Whether `/v1/rerank` accepts `Qwen/Qwen3-Embedding-8B`. Section 2.1 | One call. The endpoint is verified to exist, the model pairing is not |
| 6 | Renderer choice, PlayCanvas versus three.js. Section 1.3 | Bake-off X-R1 by end of week 3. Recorded here only because it sits on the browser boundary |

---

## Related documents

- Section 7 of this document for the verbatim platform constraint and for what may and may not be
  claimed about NVIDIA model use.
- `docs/adr/0002-model-routing.md` for the decision to use an NVIDIA text reasoning core with a
  non-NVIDIA vision sensor, and the alternatives rejected.
- `docs/runtime-verification.md` for what the platform actually does when called, which overrides
  this document on conflict.

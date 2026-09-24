# Model and service selection

Status: implemented stack; model upgrades require task-specific evidence.

## 0. Implemented stack and selection decision

This section supersedes the routing and deployment descriptions in sections 1-8 below, and
it is the living correction of [ADR-0002](adr/0002-model-routing.md). ADR-0002 remains the
accepted original decision (Nemotron Lightning as the reasoning core). The Companion caller
is Nemotron 3 Nano 30B-A3B with Lightning as fallback. The ADR number is
not reused. Sections 1-8 retain the research, its prices and rejected alternatives;
they are historical rationale, not a runtime inventory. The manifest describes the implemented structured-extraction callers and distinguishes
configured reasoning candidates from actual production routes.
The [product roadmap](product-direction.md#model-selection-and-compute-priorities) records the
ordered work and adoption gates. This section does not change model configuration.

### Implemented roles

Reviewed against the integration tree. Implemented means there is a production call path;
it does not mean every configured model is running, deployed or has passed a quality comparison.
Provider availability and prices must be checked again before an execution campaign.

| Role | Current implementation | Evidence and boundary |
| --- | --- | --- |
| Cited Companion answers | Nebius Token Factory: Nemotron 3 Nano 30B-A3B; Lightning fallback | `exulanica/selection/question.py::compose_answer` uses `REASONING_CHEAP`. The September 9 comparison supports latency and validator conformance on four questions, not general answer quality. A pre-registered held-out comparison kept Nano against Super and Ultra: neither cleared the margin on hard grounded questions ([outcome](evaluation/2026-09-22-model-selection-outcome.json)). |
| Request classification, search planning and appearance drafts | Nebius Token Factory: Qwen3-235B-A22B-Instruct-2507; DeepSeek-V4-Flash-0731 fallback | `propose_plan`, `classify_request` and `draft_appearance` call `STRUCTURED_EXTRACTION`; this is an implemented role with feature-level validation of proposals. |
| Photograph observations | Nebius Token Factory: MiniMax M3; MiniCPM-V-4_5 fallback | `exulanica/ingest/vision.py`; observation and evidence validation remain separate. On synthetic held-out photographs M3 omitted and misplaced fewer objects than MiniCPM, which also reported people who were not there ([outcome](evaluation/2026-09-22-model-selection-outcome.json)). Synthetic drawings do not establish accuracy on real photographs. |
| Caption/text semantic retrieval | Nebius Token Factory: Qwen3-Embedding-8B, 4096 dimensions | `exulanica/epistemics/caption_embeddings.py` and `exulanica/selection/embeddings.py`; lexical and cosine retrieval, not direct image embeddings. No model fallback is configured for embeddings. |
| Object boxes | Grounding DINO Tiny; OWLv2 Base Patch16 Ensemble fallback | `exulanica/ingest/stages/segmentation.py`; local inference when hosted observations lack suitable boxes. |
| Object masks | SAM 2.1 Hiera Tiny | Same segmentation module; masks are distinct from human identity confirmation, source rights and placement into recovered shared coordinates. |
| Single-image geometry | MoGe-2 ViT-L | `exulanica/reconstruction/moge.py` loads the v2 implementation and a pinned checkpoint. MoGe-3 is not an implemented automatic fallback. |
| Multi-view camera recovery | pycolmap 4.2.0 / COLMAP, SIFT and exhaustive matching | `exulanica/reconstruction/pycolmap_executor.py`; registration must be measured before training. MapAnything is not an implemented rescue path. |
| Scene training and compression | gsplat / PyTorch CUDA; PlayCanvas splat-transform | Production trainer and publication boundaries exist. The September 12 generated L40S check validates packaging and forward/backward execution, not personal-place quality. |
| Browser | TypeScript, Vite, DOM UI, PlayCanvas 2.21.4 | The app imports the PlayCanvas binding. Three.js/Spark is retained as a separate implementation; the `atlas-react` package name does not establish a React application. |
| API, durable state and jobs | Python 3.11, FastAPI, Pydantic, PostgreSQL, pgvector, PostgreSQL-backed job leases/retries | Existing replaceable model/stage interfaces and enforced module boundaries are the extension points. No new orchestration framework is selected. |
| Original bytes and compute | Local content-addressed file store; local API/workers and Docker GPU execution; hosted model calls on Nebius | `exulanica/api/services.py` constructs `LocalContentAddressedStore`. Brev/MassedCompute L40S execution is measured; Nebius GPU hosting and an S3 store implementation are not established by that run. |

Google OIDC account resolution, deterministic society stepping and playback, typed user-directed
society actions, reviewed-asset admission, scene-surface candidate extraction, scene-run preflight,
character appearance history, native character playback and the representation inspector are
deterministic application/runtime paths. They do not invoke a model merely because a model client is
configured. Optional v3 society decisions remain the only model proposal path in that foundation,
and they are explicitly requested, schema-validated and replayed from stored receipts rather than
recalled during stepping.

Nemotron Super and Ultra are configured roles but have no production caller in the reviewed
Python code. Fallback in the hosted client is provider-error handling, not a quality escalation
policy. DINOv2 appearance embeddings, YuNet/SFace biometric recognition, speech models, a learned
reranker and MapAnything appear in earlier plans or candidate discussions, not in implemented
model paths found by this review. Do not count them as delivered capabilities.

### Hosted call bounds and cost

Each hosted role waits for its own timeout, stated once in the
[model manifest](../exulanica/models/models.manifest.json) beside its measured basis. The manifest's
`timeout_rule` derives a timeout from the longest latency recorded for the role's primary: twice
that latency, rounded up to a multiple of 5 seconds. The manifest parser refuses a timeout the
rule does not produce, and refuses a basis measured on a model other than the primary. The basis
is read from the retained evaluation records by
[`scripts/survey_hosted_call_latency.py`](../scripts/survey_hosted_call_latency.py) and recorded in
[the latency record](evaluation/2026-09-24-hosted-call-latency.json).

| Role | Primary's longest measured call | Timeout |
| --- | --- | --- |
| `reasoning_cheap` (Companion answers) | 28,031 ms of 217 calls | 60 s |
| `structured_extraction` (classification, planning, drafts) | 12,326 ms of 217 calls | 25 s |
| `embedding` (query and caption vectors) | 16,676 ms of 19 calls | 35 s |
| `vision` (photograph observations) | 11,001 ms of 137 rows, each an upper bound | 25 s |
| `reasoning_mid` | 7,528 ms of 8 answers | 20 s |
| `reasoning_hard` | 7,437 ms of 8 answers | 15 s |

The timeout is a deadline on the whole request. The transport abandons a request when it passes,
however the response stalls: name resolution, connection, or a body that arrives slowly
([transport](../exulanica/models/transport.py)). A request cut off this way reports that it timed
out. A fallback serves under its role's timeout, and no retained record measures a fallback's
latency. The vision rows are synthetic drawings, and none of the records measures latency under
concurrent load.

The API client makes one attempt per call, so a question to `/selection/ask` waits on its model
calls for at most the sum of their timeouts. A planner call and its repair
([planner](../exulanica/selection/planner.py)), the query vector, and a composer call and its
repair ([question](../exulanica/selection/question.py)) come to 205 seconds. A withdrawn primary
adds the time its refusal took before the fallback is asked.

Every attempt enters the process's cost ledger, failed ones included
([usage](../exulanica/models/usage.py)). A completed call is priced from the provider's usage
report. An attempt whose connection was never made costs a known zero. A timeout, an error status,
a dropped connection, or a reply without a usage report is recorded with its cost unknown and
charged the attempt's reservation, the most it can have cost, because the provider may bill work
whose result never arrived. The budget guard spends from the same ledger, so an unknown cost
counts against the ceiling at that bound and a failed attempt counts toward the call limit. The
error that reaches the caller states the cost the same way. What the provider actually bills for
an abandoned request is not observable from this side.

### Decision and evidence

**DECISION:** retain the implemented stack as the comparison baseline. Add the evaluations in the
roadmap, then promote the model or stage that improves the declared user task within measured
runtime limits. No model family, parameter count, vendor benchmark or successful import establishes
an absolute best stack. A candidate that materially improves the task is worth additional compute
when it fits the demonstrated hardware and interaction budget; cheapest is not the selection rule.

The September 9 comparison recorded median Nano latency 3627 ms versus Lightning 18617 ms at the
selected ceiling, with zero Nano validator rejections in 24 calls. Its answer-quality measurement is
explicitly null. The September 12 Companion record prepares retrieval checks and an evaluation
corpus; live answers and human quality judgments remain pending. The segmentation record records
masks but no positive first-place person lift because pose was absent. The GPU record establishes
generated CUDA execution and cleanup. None proves an optimal model set. These four are local-only
evaluation records a clone does not contain: `2026-09-09-companion-memory`,
`2026-09-12-companion-quality`, `2026-09-11-scene-segments-production` and
`2026-09-12-place-compute-readiness`.

The [September 22 outcome](evaluation/2026-09-22-model-selection-outcome.json) answers the
criteria [pre-registered](evaluation/2026-09-22-model-selection-preregistration.json) before any
candidate output was read. For cited answers, Super was fully correct on one more hard held-out
question than Nano and Ultra on none; the frozen margin was two, so Nano stays. Both candidates
answered an empty evidence packet by stating that the library held no photographs, which was
false, and Super exposed an internal packet field name in answer text. They were faster than
Nano and cost more. The rubric was applied by an automated reviewer rather than the blinded human
review the roadmap requires, so the answer-quality half of this comparison is still owed. For
observations, MiniCPM had a higher combined rate of omitted and unsupported objects than M3 and
reported a person on two photographs with nobody in them, so M3 stays. On unsigned photographs
MiniCPM, the fallback, returned generic scene labels such as "outdoor urban area" as places; the
place proposal policy below refuses all three it returned, because no sign in those frames reads
any of their words.

A place proposal is the only producer of a place-class memory entity, so what it lets through is
what a person is later asked to confirm. The vision role proposes; a versioned policy in code,
[`exulanica/ingest/place_proposal.py`](../exulanica/ingest/place_proposal.py), decides whether the
proposal is written and under which label:

| Check | What it keeps or refuses |
| --- | --- |
| Label rule | The label keeps only words the observation transcribed from text it marked as signage, compared case-folded and spelled as the transcription spells them. A label left with no word refuses the proposal. |
| Sign question | Asked in a separate call only when a word survives: the probe's question, word for word, about the most prominent sign. A sign judged partly hidden or absent refuses the proposal, and so does an answer from a model the policy has not admitted, such as the fallback. |
| Pairing | Every word the label keeps must be among the words the sign question read, so the sign judged is the one carrying the name. |

A sign question that fails withholds the proposal and keeps the rest of the observation. The
stored observation keeps the model's reply verbatim, with the decision, its named outcome and the
policy's digest beside it, and the digest is part of the vision stage's reprocessing key.

Each check answers a measured failure. The production instruction, phrased as an exception inside
a prohibition, proposed no place from any of 8 legible place names while transcribing every one.
A rewrite that asks for the proposal directly proposed all 8, and also the visible word of a
partly covered board at medium confidence on 2 of 3 such boards, which its
[pre-registered gate](evaluation/2026-09-22-vision-place-proposal-preregistration.json) does not
allow ([outcome](evaluation/2026-09-22-vision-place-proposal-outcome.json)). Asked inside the
observation, as an instruction or as a schema field answered before the label, the model judged
boards with a tree in front of them whole
([second experiment](evaluation/2026-09-22-vision-place-proposal-b-outcome.json)); asked alone, it
judged all 24 boards of a [probe](evaluation/2026-09-22-sign-completeness-probe-outcome.json)
correctly. Asked alone as a second call, it caught every partly hidden board of a held-out split,
but the observation had already written "Ashcombe (partial)" as a label, a word no sign in the
frame carries ([third experiment](evaluation/2026-09-22-vision-place-proposal-c-outcome.json)).
That record also counts one whole street sign, Chestnut Road, as judged partly hidden in error.
The sign is not whole: `scripts/make_place_signage_photographs.py` draws a street blade from
`x - 190` and places that scene's post at `x = 189`, so the blade's left edge lies one pixel
outside the frame, and the judgement matched the picture.

The policy passed every gate [pre-registered](evaluation/2026-09-23-vision-place-proposal-d-preregistration.json)
for it, on a held-out split of 44 synthetic photographs scored once
([outcome](evaluation/2026-09-23-vision-place-proposal-d-outcome.json)). No photograph received a
proposal it should not have: none of 26 with a covered, cut, hidden or absent place name, or with
a product, slogan or personal name, and no wrong name on any of 18 whole place names. It wrote 14
of those 18 exactly, the registered minimum; the production instruction wrote none. Applied to the
same recorded replies without re-running any model, the observation's own proposals would have
put a place on 13 photographs that should have none or named one wrongly, the label rule alone on
12, and every check but pairing on 1: a nameplate the observation misread as "FENWAY CHAMBERS"
where the sign question read "FENWY CHAMBERS". The sign question costs about 820 input tokens a
proposing photograph; the design cost 1.28 times the production instruction on that split.

What the policy does not do. It refuses a place name whenever another sign in the frame is more
prominent: all 3 held-out scenes with a slogan banner behind a street sign lost their name. It
proposes nothing from a landmark with no
legible name, and it cannot tell a place name from other text on a sign: a product or slogan on a
board passes every check if the observation proposes it, and the observation proposed nothing on
all 6 such photographs of the experiment. The measurements are synthetic drawings of one style,
with the fallback disabled; the fallback's sign judgement is refused by name, never measured.

### Quality and runtime requirements, updated 2026-09-13

The living-world preview uses source-footprint building meshes and catalog-backed rigged characters,
with an abstract procedural fallback. Its appearance is not evidence of frontier scene-generation
or character-generation quality. The live society uses the deterministic v2 visit/rest policy.
The opt-in v3 backend adds local simulated observations, communicated beliefs and a bounded decision
adapter through the existing ModelClient. No model role is enabled for that adapter by default.
Its authenticated persistence and provider path are tested with scripted responses; live-model
quality, dialogue and memory reflection remain separate evaluation work. A configured model role,
an expensive GPU or a working API response does not establish these capabilities.

The quality target is the strongest demonstrated result for each user task. Compare stronger
reasoning models for grounded Companion answers and the small-cast social scenario; compare
perception/geometry candidates against actual source failures; evaluate reusable rigged assets,
materials and animation for character quality. Rendering and collision retain their existing local
runtime. Save expensive outputs and reuse them. Track model/provider/checkpoint, quality judgments,
latency, memory and cost for each comparison. Promote quality improvements within an explicit
interactive or offline execution budget; do not select solely by model size or price.

### Stronger candidates to compare, checked 2026-09-13

These are challengers for targeted comparisons, not established winners or enabled runtime roles.
Comparative inference results are pending; the implemented baseline remains unchanged.

For customizable people, first compare established parametric/rigged asset pipelines rather
than training a model solely to obtain body and wardrobe variation. [MPFB](https://static.makehumancommunity.org/mpfb/docs.html)
provides character, asset, rigging and export workflows; its [core assets](https://static.makehumancommunity.org/about/license.html)
are CC0 while the authoring code uses a separate license. [MHR](https://github.com/facebookresearch/MHR)
provides a parametric body, skinned mesh, detail levels and corrective shapes. MPFB now powers the
local editable-human preview with fitted rigs and clothing; MHR remains a candidate. Version-scoped
appearance storage now has an authenticated backend with revision history. The development editor
uses a loopback-only MPFB preparation adapter and applies its result to session presentation.
Connecting that editor to authenticated history, configuring production families and authenticated
production generation remain work. Garment fit, contact, stylization and browser performance still
require visual acceptance; a functioning editor is not a measured visual-quality selection.

Pretrained inference, per-source body fitting, and model training have different inputs and
costs. Evaluate inference first where an existing model addresses a real gap. TRELLIS.2 provides
textured asset generation and training code, but its image-to-GLB output alone does not establish
an animation-ready human. Fine-tuning requires a defined target failure and dataset; budget
inference hardware separately from training hardware. Retain generator versions, inputs,
seeds, material/rig dependencies and outputs for reuse and reproducibility.

| Task | First comparison | Remaining condition |
| --- | --- | --- |
| Grounded answers and bounded social decisions | Current Nano versus Nemotron Super; include [Nemotron 3 Ultra](https://research.nvidia.com/labs/nemotron/Nemotron-3-Ultra/) when healthy | The [Nebius public catalog](https://tokenfactory.nebius.com/api/public/models_info) reported Super active and Ultra error during this check. Recheck before execution; listing alone does not establish inference health. |
| Photograph understanding | Current M3 versus [Kimi-K3](https://huggingface.co/moonshotai/Kimi-K3), listed active and image-capable | Compare supported observations and omissions on the same authorized images; do not inherit vendor rankings. |
| Mask quality | [SAM 2.1 Large](https://github.com/facebookresearch/sam2) versus current Tiny with the same boxes | Test SAM 3 separately for concept/detection failures. SAM 3.1 video tracking improvements alone do not justify changing the still-image pipeline. |
| Scene geometry | [MoGe-3](https://github.com/microsoft/MoGe) versus MoGe-2; [MapAnything Apache](https://github.com/facebookresearch/map-anything) for adequate multi-view captures that fail registration | Separate single-image shape from multi-view pose; verify scale, held-out views, memory and Linux GPU compatibility. |
| Authored textured 3D assets | [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) for generated PBR assets; [SAM 3D Objects](https://github.com/facebookresearch/sam-3d-objects) for masked objects | Generated completion is not observed geometry. The TRELLIS.2 reference runtime needs Linux and at least 24 GB NVIDIA memory; rigging and in-app visual acceptance remain separate work. |
| Scene-derived character bodies | [SAM 3D Body](https://github.com/facebookresearch/sam-3d-body) as a source-to-body fitting candidate | A fitted body is not established identity, a complete texture or a finished animation pipeline. Preserve uncertainty, source lineage and existing person-link authority. |
| Retrieval | [Qwen3-Reranker-8B](https://huggingface.co/Qwen/Qwen3-Reranker-8B) for misranking; [SigLIP 2 SO400M](https://huggingface.co/google/siglip2-so400m-patch14-384) for visual details omitted by captions | Use only after diagnosing the retrieval failure; version a changed vector space and retain permission filtering. |

Begin with a small fixed set of representative failures, ordinary tasks and cases that should
abstain. Score factual support, task success, visual/mask/geometry quality and human preference
separately from latency and cost. Include source withdrawal and branch isolation cases. The first
screening narrows candidates; it cannot prove a universal best model or establish human behavior
prediction from a fluent answer. For model-driven society decisions, persist the accepted proposal
and its inputs/model identity so replay consumes recorded decisions instead of repeating inference.

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

## Historical selection rationale

The earlier platform comparison, provider observations, pricing and unattended-demo assumptions
remain in the [fixed research revision](https://github.com/twinkling-reality/exulanica/blob/857cffe730dad97f9edb34535c773115277e2769/docs/model-and-service-selection.md#historical-research-context).
They are not a second routing table. The implemented stack and scoped comparisons above own model
selection; the manifest and actual callers determine which configured role executes.

[Deployment](deployment.md) owns service configuration, [security](security-floor.md) owns outbound
access and permissions, and the [license matrix](license-matrix.md) owns artifact license decisions.
A historical catalog listing is not proof of availability or permission for another execution.

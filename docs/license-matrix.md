# License matrix

Every dependency, model weight and hosted model the project's technology research encountered, with a ship or
do-not-ship verdict for an Apache-2.0 repository.

Status: **VERIFIED** where a primary source was read on **2026-08-27**, with the exceptions marked
inline as DECISION, ASSUMPTION, DISPUTED, UNVERIFIED or OPEN. This document promotes Part E of the
reconciled research plus the NVIDIA model and perception streams. It records no claim that was not
already in the research.

This is the highest legal-risk document in the repository. Two of its findings (the NVIDIA license
distinction in section 2, and the trap list in section 4) are the difference between a valid
Apache-2.0 release and an invalid one.

---

## 1. How to read this

### Verdict vocabulary

| Verdict | Meaning |
| --- | --- |
| **SHIP** | Safe in an Apache-2.0 repository |
| **SHIP-ATTRIB** | Safe with a live attribution obligation. Do not vendor. Must appear in the credits surface, not only in a file |
| **USE-ONLY** | May be run but never redistributed, and the use-time terms bind the operator |
| **SEGREGATE** | Usable only as a clearly separated, separately noticed artifact, disclosed in the README and the accompanying notices |
| **BLOCKED** | Do not touch |
| **DISPUTED** | Primary sources contradict each other. Resolve before use |
| **UNVERIFIED** | Nobody in the research corpus read the license. Not a verdict, an admission |

### Standing rules

- **DECISION: never vendor model weights into the repository.** Download at build or run time, pin an
  exact repo id **and revision SHA**, and record the license read from the raw HuggingFace YAML
  frontmatter. Rejected alternative: vendoring weights for reproducibility, which converts every
  weights license from a use question into a redistribution question and would relicense the repo.
- **DECISION: record the license from the raw HuggingFace frontmatter at a pinned revision SHA,
  never the Nebius catalog string and never the model family name.** See section 5. Rejected
  alternative: trusting the Nebius catalog `license` field, which is a derived label.
- **Family names carry no license information.** Within a single NVIDIA family the license changes
  between revisions: `diar_sortformer_4spk-v1` is CC-BY-NC-4.0, `-v2` is disputed, `-v2.1` is the
  restrictive NVIDIA Open Model License. VERIFIED for v2.1, F49/F50, HF card frontmatter.

### Source URL convention

Where a row's source is given as a HuggingFace card, the retrieval URL was
`https://huggingface.co/<id>/raw/main/README.md` or `https://huggingface.co/api/models/<id>`, read
2026-08-27. Full URLs are given where the research recorded one.

### Note on the audio rows

The corpus is photographs and there is no audio (see `product-specification.md` section 2), and Nebius Token
Factory has zero audio capability. The ASR, diarization and speaker-embedding rows below therefore
describe a **deferred** capability, not the current critical path. They are retained because the
analysis is already done, because the deferral could be revisited, and because two of the sharpest
traps in the whole matrix live there.

---

## 2. The NVIDIA license distinction

**This is the single most valuable distinction in the corpus and the easiest to get wrong.** Three
NVIDIA instruments have confusingly similar names. Two are permissive and Apache-2.0 compatible. One
is neither, and is not open source in any meaningful sense.

VERIFIED, F36 and F37, each license page fetched and grepped 2026-08-27.

| Instrument | Version read | Grant | Guardrail clause | Unilateral amendment | Apache-2.0 compatible |
| --- | --- | --- | --- | --- | --- |
| **NVIDIA Open Model License** | Last Modified 2025-10-24 | **revocable**, "explicitly conditioned on Your full compliance" | **Yes**, 4 occurrences of "Guardrail" | **Yes** | **No** |
| **NVIDIA Open Model Agreement** | 2026-03-09 (see footnote) | **irrevocable** | **No**, 0 occurrences | No | **Yes** |
| **NVIDIA Nemotron Open Model License** | Last Modified 2025-12-15 | **irrevocable** | **No**, 0 occurrences | No | **Yes** |
| **OpenMDW-1.1** (not an NVIDIA instrument, used by NVIDIA) | last updated 2026-05-27 | deal in the materials "without restriction" | No | No | **Yes** |
| **NVIDIA Community Model License** | Effective 2025-01-30 | production use gated behind an NVIDIA AI Enterprise / NIM subscription | n/a | n/a | **No** |
| **"NVIDIA License", per repo** | per model | "academic and non-profit research purposes only" | n/a | n/a | **No** |

Footnote on the version string: the `nvidia-models` stream recorded the Open Model Agreement page as
"Effective: April 2, 2026" while the reconciliation recorded "version 2026-03-09". The operative
terms are identical in both readings. **OPEN, cosmetic:** record whichever string the page shows at
retrieval time in `THIRD_PARTY_NOTICES.md`.

### The operative difference, quoted

**NVIDIA Open Model License** (restrictive),
<https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/>:

> "The rights granted herein are explicitly conditioned on Your full compliance with the terms of
> this Agreement. Subject to the terms and conditions of this Agreement, NVIDIA hereby grants to You
> a perpetual, worldwide, non-exclusive, no-charge, royalty-free, revocable (as stated in Section
> 2.1) license ..."

> "If You bypass, disable, reduce the efficacy of, or circumvent any technical limitation, safety
> guardrail or associated safety guardrail hyperparameter, encryption, security, digital rights
> management, or authentication mechanism (collectively 'Guardrail') contained in the Model without a
> substantially similar Guardrail appropriate for your use case, your rights under this Agreement
> will automatically terminate."

> "NVIDIA may update this Agreement to comply with legal and regulatory requirements at any time and
> You agree to either comply with any updated license or cease Your copying, use, and distribution of
> the Model and any Derivative Model."

It further incorporates by reference an externally mutable policy: "Use of the Models under the
Agreement must be consistent with NVIDIA's Trustworthy AI terms found at
<https://www.nvidia.com/en-us/agreements/trustworthy-ai/terms/>".

**NVIDIA Nemotron Open Model License** and **NVIDIA Open Model Agreement** (permissive),
<https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license> and
<https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/>:

> "2. Grant of License. Subject to the terms and conditions of this License, NVIDIA hereby grants to
> You a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable license to
> reproduce, prepare Derivative Works of, publicly display, publicly perform, sublicense, and
> distribute the Work and such Derivative Works in source or object form."

Sole termination trigger, in both:

> "If You institute patent or copyright litigation against any entity ... alleging that the Work or an
> output from the Work constitutes direct or contributory patent or copyright infringement, then any
> licenses granted to You under this License for that Work shall terminate as of the date such
> litigation is filed."

Both documents were grepped for `guardrail|circumvent|revocab` and returned **zero hits**. Neither has
a unilateral-amendment clause and neither incorporates an external AI-ethics policy by reference.

**Why this matters in one sentence:** a revocable, unilaterally amendable grant with a
field-of-use-shaped termination condition cannot be sublicensed under Apache-2.0, so weights under
the NVIDIA Open Model License must not be vendored, and per section 6 must not be self-hosted either.

### Which models fall under which

| Instrument | Models |
| --- | --- |
| **OpenMDW-1.1** (permissive) | `nvidia/Nemotron-3_5-Lightning` / `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-*`, `nvidia/nemotron-3.5-asr-streaming-0.6b`, `nvidia/Nemotron-3-Embed-1B-BF16`, `nvidia/Nemotron-3-Embed-8B-BF16`. All four VERIFIED in raw HF frontmatter (F39). `nvidia/Nemotron-3-Ultra-550b-a55b` is **catalog-only**, see section 5 |
| **NVIDIA Nemotron Open Model License** (permissive) | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-*`, `nvidia/nemotron-3-super-120b-a12b`. Both per HF card; the Nebius catalog disagrees, see section 5 |
| **NVIDIA Open Model Agreement** (permissive) | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-*`. Per HF card; the Nebius catalog disagrees. Removed from Token Factory Serverless 2026-08-31 (F4), so it has no role in the plan |
| **NVIDIA Open Model License** (restrictive) | Cosmos family (`Cosmos3-Super-Reasoner`, `Cosmos-Reason1-7B`, `Cosmos-Reason2-*`, `Cosmos-Embed1-*`, `C-RADIOv4-H`), `nvidia/parakeet-unified-en-0.6b`, `nvidia/multitalker-parakeet-streaming-0.6b-v1`, `nvidia/diar_streaming_sortformer_4spk-v2.1`, `nvidia/NVIDIA-Nemotron-Parse-v1.2`, `nvidia/NV-DINOv2`, `nvidia/nv-grounding-dino`, `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` |
| **NVIDIA Community Model License** (unusable) | No model Exulanica needs is only available here |
| **"NVIDIA License", per repo, non-commercial** | `nvidia/LocateAnything-3B` |

**Consequence for the model plan.** All four surviving text Nemotrons in the reasoning plan
(`Nemotron-3_5-Lightning`, `nemotron-3-super-120b-a12b`, `Nemotron-3-Ultra-550b-a55b`,
`NVIDIA-Nemotron-3-Nano-30B-A3B`) sit under permissive instruments, not the restrictive one. The
NVIDIA-compliance requirement and the Apache-2.0 requirement do not conflict.

**RISK, recorded as a standing constraint (R-29).** This analysis holds because Exulanica calls hosted
weights and publishes no derived checkpoint. If the project ever fine-tunes and publishes a
checkpoint, the analysis flips: derive only from OpenMDW-1.1 or NVIDIA Nemotron Open Model License
bases.

---

## 3. The matrices

### 3.1 NVIDIA models

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| `nvidia/Nemotron-3_5-Lightning` (Token Factory) / `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-*` | NeMo / Nemotron Apache-2.0 | OpenMDW-1.1 | **Yes** | <https://openmdw.ai/license/1-1/> | **SHIP.** Primary NVIDIA compliance vehicle |
| `nvidia/nemotron-3-super-120b-a12b` (Token Factory) | Apache-2.0 | nvidia-nemotron-open-model-license per HF; nvidia-open-model-license per Nebius catalog | Yes per HF | <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license> | **SHIP**, trust HF (section 5) |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-*` | Apache-2.0 | nvidia-nemotron-open-model-license per HF; nvidia-open-model-license per Nebius catalog | Yes per HF | <https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B> | **SHIP**, trust HF (section 5) |
| `nvidia/Nemotron-3-Ultra-550b-a55b` (Token Factory) | Apache-2.0 | `openmdw-1.1` **per Nebius catalog only** | Yes if catalog is right | <https://tokenfactory.nebius.com/api/public/models_info> | **UNVERIFIED direction of error.** No role in Exulanica. See section 5 |
| `nvidia/Nemotron-3-Embed-1B-BF16` / `-8B-BF16` | Apache-2.0 | OpenMDW-1.1 (base Ministral is Apache-2.0, so nothing restrictive flows through) | **Yes** | <https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16> | **SHIP** |
| `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-*` | Apache-2.0 | NVIDIA Open Model Agreement | **Yes** | <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/> | SHIP by license, but **removed from Token Factory Serverless 2026-08-31** (F4). Not in the plan |
| `nvidia/omnivinci` | n/a | apache-2.0 | **Yes** | <https://huggingface.co/nvidia/omnivinci> | **SHIP.** Joint video-plus-audio, self-hosted only. No current role given the photo corpus |
| `nvidia/nemotron-3.5-asr-streaming-0.6b` | Apache-2.0 | OpenMDW-1.1 | **Yes** | <https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b> | **SHIP.** Deferred capability |
| `nvidia/parakeet-tdt-0.6b-v3` (25 languages) | NeMo Apache-2.0 | cc-by-4.0 | Conditional: attribution | <https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3> | **SHIP-ATTRIB.** Deferred capability |
| `nvidia/parakeet-tdt-0.6b-v2` (English) | NeMo Apache-2.0 | cc-by-4.0 | Conditional: attribution | <https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2> | **SHIP-ATTRIB.** Deferred capability |
| `nvidia/canary-1b-v2` / `-flash` / `canary-qwen-2.5b` | Apache-2.0 | cc-by-4.0 | Conditional: attribution | <https://huggingface.co/nvidia/canary-1b-v2> | SHIP-ATTRIB |
| `nvidia/canary-1b` (original) | Apache-2.0 | **cc-by-nc-4.0** | **No** | <https://huggingface.co/nvidia/canary-1b> | **BLOCKED.** Note the name collision with `canary-1b-v2` |
| `nvidia/speakerverification_en_titanet_large` | Apache-2.0 | cc-by-4.0 | Conditional: attribution | <https://huggingface.co/api/models/nvidia/speakerverification_en_titanet_large> | SHIP-ATTRIB |
| `nvidia/diar_streaming_sortformer_4spk-v2` | Apache-2.0 | **DISPUTED**: cc-by-4.0 vs nvidia-open-model-license | **Unknown** | <https://huggingface.co/api/models/nvidia/diar_streaming_sortformer_4spk-v2> | **DISPUTED.** See section 4a |
| `nvidia/diar_streaming_sortformer_4spk-v2.1` | Apache-2.0 | nvidia-open-model-license | **No** | <https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1> | **USE-ONLY at best; excluded** per section 6 |
| `nvidia/diar_sortformer_4spk-v1` | Apache-2.0 | **cc-by-nc-4.0** | **No** | <https://huggingface.co/nvidia/diar_sortformer_4spk-v1> | **BLOCKED** |
| `nvidia/parakeet-unified-en-0.6b` | Apache-2.0 | nvidia-open-model-license | **No** | <https://huggingface.co/nvidia/parakeet-unified-en-0.6b> | **Excluded** per section 6. Also does not claim timestamp support |
| `nvidia/multitalker-parakeet-streaming-0.6b-v1` | Apache-2.0 | nvidia-open-model-license | **No** | <https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1> | **SEGREGATE.** Architecturally attractive, excluded per section 6 |
| Cosmos family: `Cosmos3-Super-Reasoner`, `Cosmos-Reason1-7B`, `Cosmos-Reason2-*`, `Cosmos-Embed1-*`, `C-RADIOv4-H` | `nvidia-cosmos/cosmos-reason1` Apache-2.0; `NVIDIA/Cosmos` NOASSERTION | nvidia-open-model-license; Reason2 additionally **gated** | **No** | <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/> | **BLOCKED.** Tuned for physical AI, gated, restrictive, and removed from Token Factory Serverless 2026-08-31 |
| `nvidia/NVIDIA-Nemotron-Parse-v1.2` | Apache-2.0 | nvidia-open-model-license | **No** | <https://huggingface.co/nvidia/NVIDIA-Nemotron-Parse-v1.2> | SEGREGATE. No role in Exulanica |
| `nvidia/LocateAnything-3B` | per repo | **NVIDIA License**, "academic and non-profit research purposes only", plus a stacked Qwen Research License | **No** | <https://huggingface.co/nvidia/LocateAnything-3B/raw/main/README.md> | **BLOCKED.** A use-time block, not only a shipping block: a publicly released project of this kind is arguably not academic non-profit research |
| `nvidia/NV-DINOv2`, `nvidia/nv-grounding-dino` | n/a | gated / nvidia-open-model-license | **No** | NGC / HF | **BLOCKED** |
| `nvidia/difix`, `nvidia/difix_ref` (Difix3D+) | nv-tlabs repo | "NVIDIA License", terms stated as aligned to sd-turbo | **Unverified** | <https://github.com/nv-tlabs/Difix3D> | **UNVERIFIED.** Read in full before any use |
| Anything under the **NVIDIA Community Model License** | n/a | subscription-gated production use; forbids improving other AI models; forbids OSS licensing | **No** | <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-community-models-license/> | **BLOCKED** |

**CODE versus WEIGHTS, VERIFIED via the GitHub API 2026-08-27 (F42).** `NVIDIA-NeMo/NeMo` and
`NVIDIA-NeMo/Nemotron` ship unmodified Apache-2.0 LICENSE files, 200 and 202 lines, with no NVIDIA
addenda. `nvidia-cosmos/cosmos-reason1` is Apache-2.0. `NVIDIA/Cosmos` reports **NOASSERTION**, which
is mixed, so do not assume. Inference, tokenizer and preprocessing **code** can be depended on
freely; the **weights** carry a separate per-model agreement. Treating a repository's SPDX chip as
covering its checkpoints is a category error and is the origin of most of the confusion in this area.

### 3.2 Non-NVIDIA models on Nebius Token Factory

All rows are API-hosted. Licenses here are from the Nebius catalog `models_info` endpoint unless
noted, which per section 5 is a derived label and not authoritative.

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| `openbmb/MiniCPM-V-4_5` | n/a, API | "Apache 2.0 License" per catalog, URL points at the **code** repo LICENSE | **Yes per catalog** | <https://github.com/OpenBMB/MiniCPM-V/blob/main/LICENSE> | **SHIP.** Primary vision sensor. **OPEN:** under the standing rule the HF card frontmatter has not been read; confirm it |
| `MiniMaxAI/MiniMax-M3` | n/a, API | custom, named only "MiniMax-M3" | **UNVERIFIED** | <https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/main/LICENSE> | **UNVERIFIED.** Nebius' own recommended replacement for the removed NVIDIA vision models, and the only catalog model declaring the `video` use case. **Read this license before depending on it.** See section 8 |
| `Qwen/Qwen3-Embedding-8B` | n/a | Apache 2.0 | **Yes** | catalog | **SHIP.** The only embedding model on Token Factory |
| `Qwen/Qwen3-235B-A22B-Instruct-2507`, `Qwen3-30B-A3B-Instruct-2507`, `Qwen3.5-397B-A17B` | n/a | Apache 2.0 | **Yes** | catalog | **SHIP.** Extraction fallback if Nemotron structured output fails |
| `openai/gpt-oss-120b` | n/a | Apache 2.0 | **Yes** | catalog | SHIP |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | n/a | MIT | **Yes** | <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/LICENSE> | SHIP. Carries the catalog "JSON mode" tag |
| `moonshotai/Kimi-K2.6` / `Kimi-K2.7-Code` | n/a | `mit` per catalog | Yes | catalog | SHIP if needed |
| `zai-org/GLM-5.1` / `GLM-5.2` | n/a | MIT | Yes | catalog | SHIP if needed |
| `google/gemma-3-27b-it` | n/a | **Gemma License**, imposes use restrictions Apache-2.0 does not | **Conditional, likely No** | <https://ai.google.dev/gemma/terms> | **UNVERIFIED, avoid.** Declares image use, but nobody read the terms |
| `moonshotai/Kimi-K3` | n/a | custom "Kimi K3 License" | **UNVERIFIED** | <https://huggingface.co/moonshotai/Kimi-K3/blob/main/LICENSE> | **AVOID.** Also $3/$15 per M tokens and hosted in eu-west2, a private region |
| `Qwen/Qwen2.5-VL-72B-Instruct` | n/a | "Qwen License" | **UNVERIFIED** | <https://huggingface.co/Qwen/Qwen2.5-VL-72B-Instruct/blob/main/LICENSE> | Moot: removed from Serverless 2026-08-31 |

### 3.3 Reconstruction and 3D

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| `nerfstudio-project/gsplat` | **Apache-2.0**, verbatim | n/a | **Yes** | <https://github.com/nerfstudio-project/gsplat> | **SHIP. The mandatory rasterizer** |
| COLMAP | New BSD | n/a | Yes | <https://colmap.github.io/license.html> | **SHIP** |
| nerfstudio | Apache-2.0 | n/a | Yes | <https://github.com/nerfstudio-project/nerfstudio> | SHIP |
| `nv-tlabs/3dgrut` (3DGUT / 3DGRT) | Apache-2.0 | n/a | Yes | <https://github.com/nv-tlabs/3dgrut> | **SHIP.** Rolling-shutter aware, and an Apache-2.0 NVIDIA open-source component |
| `ArthurBrussee/brush` | Apache-2.0 | n/a | Yes | <https://github.com/ArthurBrussee/brush> | **SHIP.** Local Metal training insurance path |
| **MoGe 1 / 2 / 3** | **MIT**, except vendored DINOv2 which is Apache-2.0 | **MIT**, all checkpoints | **Yes** | <https://github.com/microsoft/MoGe> | **SHIP.** Use MoGe-2 locally; MoGe-3 has no macOS path |
| FlexGEMM (MoGe-3 dependency) | MIT | n/a | Yes | <https://github.com/microsoft/FlexGEMM> | SHIP, Linux only |
| `facebook/map-anything` (code) | Apache-2.0 | n/a | Yes | <https://github.com/facebookresearch/map-anything> | SHIP |
| `facebook/map-anything-apache` (weights) | Apache-2.0 | **apache-2.0** | **Yes** | <https://huggingface.co/facebook/map-anything-apache> | **SHIP.** Safest feed-forward pose rescue. Note: safest, **not** the only clean option |
| `facebook/map-anything` (weights) | Apache-2.0 | **cc-by-nc-4.0** | **No** | <https://huggingface.co/facebook/map-anything> | **BLOCKED.** Identical API to the apache variant, so this is an easy accidental swap |
| GLOMAP | BSD-3-Clause, **archived and deprecated** | n/a | Yes | <https://github.com/colmap/glomap> | Use COLMAP's global mapper instead |
| **INRIA `gaussian-splatting` + `diff-gaussian-rasterization`** | **non-commercial research only, viral to derivatives** | n/a | **No** | <https://raw.githubusercontent.com/graphdeco-inria/gaussian-splatting/main/LICENSE.md> | **BLOCKED.** Highest-probability accidental violation in the 3D stack |
| `facebook/VGGT-1B` | VGGT License v1 | **cc-by-nc-4.0** | **No** | <https://huggingface.co/facebook/VGGT-1B> | **BLOCKED** |
| `facebook/VGGT-1B-Commercial` | VGGT License v1 | custom `vggt-aup-license`, **gated** | Not OSI | <https://huggingface.co/facebook/VGGT-1B-Commercial> | SEGREGATE plus NOTICE disclosure if ever used |
| `facebook/VGGT-Omega` | FAIR NC Research v1 | fair-noncommercial-research-license, gated | **No** | <https://raw.githubusercontent.com/facebookresearch/vggt-omega/main/LICENSE> | **BLOCKED** |
| **Pi3** (`yyfz/Pi3`, `yyfz233/Pi3`) | BSD-3-Clause per GitHub | **DISPUTED**: HF frontmatter says `bsd-2-clause`, the GitHub README says weights are non-commercial research and education only | **Unknown** | <https://huggingface.co/yyfz/Pi3> and <https://github.com/yyfz/Pi3> | **DISPUTED. Do not use** |
| DUSt3R, MASt3R | CC BY-NC-SA 4.0 | CC BY-NC-SA 4.0 plus dataset terms, mapfree noted as "very restrictive" | **No** | <https://github.com/naver/dust3r> | **BLOCKED** |
| CUT3R | CC BY-NC-SA 4.0 | CC BY-NC-SA 4.0 | **No** | <https://github.com/CUT3R/CUT3R> | **BLOCKED** |
| Fast3R | FAIR NC Research | FAIR NC Research | **No** | <https://github.com/facebookresearch/fast3r> | **BLOCKED** |
| Spann3r | Unverified, DUSt3R-derived | Unverified | Unknown | n/a | **BLOCKED until verified** |
| `facebookresearch/egocentric_splats` | **Creative Commons**, and requires Project Aria MPS data | n/a | **No** | <https://github.com/facebookresearch/egocentric_splats> | **BLOCKED.** Do not plan rolling-shutter handling around it; use 3DGUT |

### 3.4 Perception

Rows marked *(deferred)* belong to the audio capability that has no source material in the current
corpus.

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| **SAM 2 / SAM 2.1** | **Apache-2.0** | **Apache-2.0**, checkpoints, demo code and training code | **Yes** | <https://raw.githubusercontent.com/facebookresearch/sam2/main/README.md> | **SHIP** |
| **SAM 3 / SAM 3.1** | **SAM License**, derivatives must be redistributed under the same agreement | SAM License, **gated with manual review**, CUDA >= 12.6 | **No** | <https://raw.githubusercontent.com/facebookresearch/sam3/main/LICENSE> | **BLOCKED** for in-repo use. If used at all: segregate, ship the license verbatim, disclose, and file the access request early |
| Grounding DINO (open, 2023) plus `grounding-dino-tiny` / `-base` | **Apache-2.0** | **apache-2.0**, ungated | **Yes**, with a residual dataset-provenance caveat | <https://raw.githubusercontent.com/IDEA-Research/GroundingDINO/main/LICENSE> | **SHIP**, and disclose the Cap4M caveat honestly (see section 9) |
| OWLv2 (`google/owlv2-*`) | Apache-2.0 | apache-2.0 | **Yes** | <https://huggingface.co/google/owlv2-base-patch16-ensemble> | SHIP. The card's "research output" framing is a norm, not a license term |
| MM-Grounding-DINO (mmdetection) | Apache-2.0 | Apache-2.0 | Yes | <https://github.com/open-mmlab/mmdetection> | SHIP |
| Grounding DINO 1.5 / 1.6, DINO-X | closed API products | n/a | n/a | IDEA-Research | Do not cite their benchmark numbers while shipping the open model |
| **YOLO-World** | **GPL-3.0** | n/a | **No** | <https://raw.githubusercontent.com/AILab-CVC/YOLO-World/master/LICENSE> | **BLOCKED** |
| **YOLOE, Ultralytics** | **AGPL-3.0** | n/a | **No** | <https://raw.githubusercontent.com/THU-MIG/yoloe/main/LICENSE> | **BLOCKED.** AGPL is worse than GPL here: network use of a hosted product triggers source disclosure |
| **BoxMOT** | **AGPL-3.0** | n/a | **No** | <https://raw.githubusercontent.com/mikel-brostrom/boxmot/master/LICENSE> | **BLOCKED** |
| ByteTrack | MIT | n/a, no appearance model | **Yes** | <https://github.com/FoundationVision/ByteTrack> | **SHIP.** Zero weights-license exposure by design |
| BoT-SORT | MIT | n/a with the ReID branch disabled | Yes | <https://github.com/NirAharon/BoT-SORT> | SHIP with ReID disabled |
| **OpenCV Zoo YuNet** (face detection) | MIT | **MIT**, LICENSE file in the model directory | **Yes** | <https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet> | **SHIP** |
| **OpenCV Zoo SFace** (face embedding) | Apache-2.0 | **Apache-2.0**, LICENSE file in the same directory as the ONNX | **Yes** | <https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface> | **SHIP.** Best clean face embedding |
| **dlib `dlib_face_recognition_resnet_model_v1`** | Boost 1.0, library | **public domain**, author's explicit release | **Yes** | <https://raw.githubusercontent.com/davisking/dlib-models/master/README.md> | **SHIP** |
| dlib `shape_predictor_5_face_landmarks.dat` | Boost 1.0 | public domain, author's own dataset | **Yes** | same | **SHIP** |
| **dlib `shape_predictor_68_face_landmarks(.dat / _GTX)`** | Boost 1.0 | **explicit no-commercial-product carve-out**, ibug 300-W | **No** | same | **BLOCKED. Both 68-point variants** |
| **InsightFace** (`buffalo_*`, `antelopev2`, ArcFace zoo) | MIT for code only; the repo has **no LICENSE file** and GitHub detects none | **"non-commercial research purposes only"**, covering the auto-downloaded weights | **No** | <https://raw.githubusercontent.com/deepinsight/insightface/master/README.md> | **BLOCKED. Ban the package and grep the built image** |
| AdaFace | MIT | **no license attached at all**, bare Google Drive links | **No** | <https://raw.githubusercontent.com/mk-minchul/AdaFace/master/README.md> | **BLOCKED.** Unlicensed is all-rights-reserved, not permissive |
| EdgeFace (`Idiap/EdgeFace-*`) | n/a | **cc-by-nc-sa-4.0** | **No** | <https://huggingface.co/idiap/EdgeFace-XXS> | **BLOCKED** |
| facenet-pytorch | MIT | VGGFace2 / CASIA-WebFace research-terms checkpoints | **No** | <https://github.com/timesler/facenet-pytorch> | **BLOCKED** |
| torchreid / deep-person-reid | **MIT** | OSNet weights have **no license attached**; trained on Market-1501, DukeMTMC (retracted) and MSMT17 | Code Yes, weights **No** | <https://github.com/KaiyangZhou/deep-person-reid> | Code SHIP, **weights BLOCKED** |
| DINOv2 | Apache-2.0 | Apache-2.0 | **Yes** | <https://github.com/facebookresearch/dinov2> | **SHIP.** Appearance vector |
| DINOv3 | GitHub reports NOASSERTION, custom license | custom | **Unknown** | <https://github.com/facebookresearch/dinov3> | SEGREGATE or avoid |
| OpenAI CLIP | MIT | MIT | Yes | <https://github.com/openai/CLIP> | SHIP |
| `pyannote/pyannote-audio` *(deferred)* | MIT | n/a | Yes | <https://github.com/pyannote/pyannote-audio> | SHIP |
| `pyannote/speaker-diarization-3.1` *(deferred)* | MIT | `mit`, HF-gated behind a marketing contact form, not a commercial gate | Yes | <https://raw.githubusercontent.com/pyannote/hf-speaker-diarization-3.1/main/README.md> | **SHIP with a gating caveat**: a fresh clone needs a token |
| `pyannote/speaker-diarization-community-1` *(deferred)* | MIT | cc-by-4.0, HF-gated | Conditional: attribution | <https://huggingface.co/pyannote/speaker-diarization-community-1> | SHIP-ATTRIB with a gating caveat. Diarization fallback |
| `speechbrain/spkrec-ecapa-voxceleb` *(deferred)* | Apache-2.0 | apache-2.0 | **Yes** | <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb> | **SHIP.** Cleanest single speaker-embedding artifact |
| `Wespeaker/wespeaker-voxceleb-resnet34-LM` *(deferred)* | Apache-2.0 | cc-by-4.0 | Conditional: attribution | <https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM> | SHIP-ATTRIB |
| `openai/whisper` code *(deferred)* | MIT | n/a | Yes | <https://github.com/openai/whisper> | SHIP |
| `openai/whisper-large-v3` *(deferred)* | MIT | card declares **apache-2.0** | Yes | <https://huggingface.co/openai/whisper-large-v3> | SHIP |
| `openai/whisper-large-v3-turbo` *(deferred)* | MIT | card declares **mit** | Yes | <https://huggingface.co/openai/whisper-large-v3-turbo> | SHIP. The two cards are inconsistent with each other; cite each as it stands |
| WhisperX *(deferred)* | BSD-2-Clause | n/a | Yes | <https://github.com/m-bain/whisperX> | SHIP, but its diarization path pulls gated pyannote, so a fresh `pip install` returns 401 |
| faster-whisper / CTranslate2 *(deferred)* | MIT | n/a | Yes | <https://github.com/SYSTRAN/faster-whisper> | SHIP. No Metal backend, CPU-only on Apple Silicon |
| `mlx-whisper` *(deferred)* | MIT | n/a | Yes | <https://github.com/ml-explore/mlx-examples> | SHIP |
| `whisper.cpp` *(deferred)* | MIT | n/a | Yes | <https://github.com/ggml-org/whisper.cpp> | SHIP |
| `senstella/parakeet-mlx` *(deferred)* | Apache-2.0 | n/a | Yes | <https://github.com/senstella/parakeet-mlx> | **SHIP.** Runs Parakeet on Apple Silicon |
| `FluidInference/FluidAudio` *(deferred)* | Apache-2.0 | CoreML conversions of Sortformer, inheriting Sortformer's terms | Code Yes; weights inherit | <https://github.com/FluidInference/FluidAudio> | SHIP the code; the weights follow the section 4a resolution |
| CrisperWhisper v1 *(deferred)* | n/a | **cc-by-nc-4.0** | **No** | <https://huggingface.co/nyrahealth/CrisperWhisper> | **BLOCKED** despite being timestamp state of the art |
| CrisperWhisper 2.0 *(deferred)* | n/a | **nyra-health-non-commercial-research** | **No** | HF card | **BLOCKED** |

### 3.5 Browser rendering and frontend

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| three.js | **MIT** | n/a | Yes | <https://github.com/mrdoob/three.js/blob/dev/LICENSE> | **SHIP** |
| `@sparkjsdev/spark` 2.1.0 | **MIT** | n/a | Yes | <https://github.com/sparkjsdev/spark> | **SHIP.** Recommended splat renderer for the three.js path |
| react-three-fiber | MIT | n/a | Yes | <https://github.com/pmndrs/react-three-fiber/blob/master/LICENSE> | SHIP |
| drei | MIT | n/a | Yes | <https://github.com/pmndrs/drei/blob/master/LICENSE> | SHIP, but use `<Html>` sparingly for performance reasons, not license reasons |
| PlayCanvas engine 2.21.4 | **MIT** | n/a | Yes | <https://github.com/playcanvas/engine> | SHIP. Alternative engine, still under bake-off |
| `@playcanvas/splat-transform` v3.3.3 | **MIT** | n/a | Yes | <https://github.com/playcanvas/splat-transform> | **SHIP.** Needed for SOG regardless of which engine wins |
| playcanvas/supersplat | MIT | n/a | Yes | <https://github.com/playcanvas/supersplat> | SHIP |
| playcanvas/sogs (python) | Apache-2.0, **archived 2025-09-10** | n/a | Yes | <https://github.com/playcanvas/sogs> | Superseded by splat-transform |
| Babylon.js | Apache-2.0 | n/a | Yes | <https://github.com/BabylonJS/Babylon.js> | Rejected on Gaussian-splat LOD absence, **not** on license |
| `nianticlabs/spz` | MIT | n/a | Yes | <https://github.com/nianticlabs/spz> | SHIP, interchange format |
| d3-force | **ISC** | n/a | Yes | <https://github.com/d3/d3-force/blob/main/LICENSE> | **SHIP.** Deterministic layout |
| `mkkellogg/GaussianSplats3D` | MIT | n/a | Yes | <https://github.com/mkkellogg/GaussianSplats3D> | Avoid: dormant, zero commits in 90 days. Not a license issue |
| `@lumaai/luma-web` | MIT | n/a | Yes | npm | Avoid: npm-deprecated since 2024. Not a license issue |
| `KHR_gaussian_splatting` spec text | **CC-BY-4.0** | n/a | Spec text, not code | Khronos | Adopt only after ratification |
| Yarn Spinner, ink | MIT | n/a | Yes | GitHub | **Architecture reference only.** Both are C# and neither is vendored |

### 3.6 Data, storage and tooling

| Component | Code license | Weights license | Apache-2.0 compatible | Source URL | Verdict |
| --- | --- | --- | --- | --- | --- |
| Label Studio | **Apache-2.0** | n/a | Yes | <https://github.com/HumanSignal/label-studio/blob/develop/LICENSE> | **SHIP.** Chosen annotator |
| CVAT | MIT | n/a | Yes | <https://github.com/cvat-ai/cvat/blob/develop/LICENSE> | SHIP. Dropped by design, not by license |
| FiftyOne | Apache-2.0 | n/a | Yes | <https://github.com/voxel51/fiftyone/blob/develop/LICENSE> | SHIP. Note it pulls MongoDB |
| PostgreSQL 18 | PostgreSQL License | n/a | **UNVERIFIED in this corpus** | <https://www.postgresql.org/support/versioning/> | **UNVERIFIED.** Nobody read the license text. Widely understood to be permissive. One `curl` settles it (X-0g) |
| pgvector 0.8.6 | PostgreSQL License | n/a | **UNVERIFIED in this corpus** | <https://github.com/pgvector/pgvector> | **UNVERIFIED.** Same. Covered by X-0g |
| ffmpeg 8.1.1 | LGPL or GPL depending on build configuration | n/a | **UNVERIFIED** | n/a | **UNVERIFIED.** We invoke it as a subprocess and neither link nor redistribute it, which is the standard mitigation. **Confirm the build configuration of the binary used in the container** |
| RO-Crate 1.2 spec | open standard | n/a | Yes for the spec | <https://www.researchobject.org/ro-crate/> | SHIP the spec. **Tooling libraries UNVERIFIED** |
| Croissant 1.0 plus RAI spec | open standard, MLCommons | n/a | Yes for the spec | <https://docs.mlcommons.org/croissant/> | SHIP the spec. **Tooling libraries UNVERIFIED** |
| ETH3D high-resolution multi-view benchmark, `pipes` training scene | Data: CC-BY-NC-SA-4.0 | n/a | No, separately licensed evaluation input | <https://www.eth3d.net/> | **USE-ONLY, VERIFIED 2026-09-04.** Official data page states CC BY-NC-SA 4.0. Fixed archive and license-document digests are in `exulanica/evaluation/benchmarks/eth3d-pipes-v1.json`. Never vendor the source images into the Apache-2.0 tree |

---

## 4. The license traps most likely to be hit by accident

Ranked by probability of accidental violation, based on how commonly each appears in tutorials and
default code paths. Every one of these has a clean alternative that already exists.

| # | Trap | What goes wrong | Clean alternative |
| --- | --- | --- | --- |
| 1 | `pip install insightface` then `FaceAnalysis(name="buffalo_l")` | Silently auto-downloads **non-commercial-research-only** weights. The repo has no LICENSE file and GitHub detects none. This is the most common license violation in hobbyist face-recognition projects | **YuNet (MIT) for detection, dlib 5-point landmarks (public domain) for alignment, SFace (Apache-2.0) or dlib ResNet (public domain) for embeddings.** No gated downloads, no HF token, runs on CPU |
| 2 | Linking the INRIA `diff-gaussian-rasterization` CUDA kernel | Most 3DGS tutorials and forks import it by default. Its license is non-commercial research only **and viral to derivatives** | **`nerfstudio-project/gsplat`, Apache-2.0.** Enforce it as the only rasterizer |
| 3 | `dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")` | The first line of nearly every dlib face tutorial. The ibug 300-W dataset license excludes commercial use and the model author states explicitly that the trained model "can't be used in a commercial product" | **`shape_predictor_5_face_landmarks.dat`**, trained on the author's own dataset and covered by his blanket public-domain release |
| 4 | Ultralytics, YOLO-World or BoxMOT arriving transitively as "just give me detection and tracking" | GPL-3.0 (YOLO-World) and AGPL-3.0 (YOLOE, Ultralytics, BoxMOT). AGPL in a hosted product triggers the network source-disclosure obligation, which would relicense the project | **Grounding DINO via `transformers` (Apache-2.0)** for detection, **ByteTrack or BoT-SORT with ReID disabled (both MIT)** for tracking |
| 5 | An unpinned NVIDIA tag | `diar_sortformer_4spk-v1` is CC-BY-NC-4.0, `-v2` is disputed, `-v2.1` is the NVIDIA Open Model License. `canary-1b` is CC-BY-NC-4.0 while `canary-1b-v2` is CC-BY-4.0. A floating tag can change the project's license posture with no visible signal | **Pin repo id plus revision SHA in `models.manifest.json`**, and fail CI on `cardData.license` drift |
| 6 | `facebook/map-anything` instead of `facebook/map-anything-apache` | Identical API, but the plain variant's weights are CC-BY-NC-4.0 | **`facebook/map-anything-apache`**, whose weights are apache-2.0. It is the safest feed-forward option, not the only one |
| 7 | `pip install crisperwhisper` for verbatim timestamps *(deferred capability)* | v1 is CC-BY-NC-4.0 and 2.0 is a non-commercial research license, despite being timestamp state of the art | **`nvidia/parakeet-tdt-0.6b-v3` (CC-BY-4.0)** or **`nvidia/nemotron-3.5-asr-streaming-0.6b` (OpenMDW-1.1)** |
| 8 | Reaching for torchreid's pretrained OSNet weights for body re-identification | The code is MIT but the weights carry **no license** and were trained on Market-1501, MSMT17 and the retracted DukeMTMC | **DINOv2 (Apache-2.0)** as a same-day appearance vector, with the accuracy limits stated honestly |

### 4a. UNRESOLVED: the Sortformer v2 license contradiction

Two research streams read the same model and recorded different licenses. **This is preserved as
unresolved. Neither reading is confirmed.**

| Stream | Reading | Supporting detail |
| --- | --- | --- |
| `perception` | `nvidia/diar_streaming_sortformer_4spk-v2` is **cc-by-4.0**, not gated, last modified 2026-08-12 | Read the card's own frontmatter, reports the gated flag and a last-modified date, and reproduces v2's own DER table (CALLHOME 2spk 6.57%, 3spk 10.05%, DIHARD III full 18.91%) |
| `nvidia-models` | The same model is **nvidia-open-model-license** | Reports DER numbers (CALLHOME 2spk 6.65, DIHARD III full 20.21) that in fact belong to **v2.1**, which suggests the two revisions were conflated |

The adversarial verifier checked **only v2.1** and confirmed it as `nvidia-open-model-license` with
DIHARD III (5 to 9 speakers) DER 41.42. It never checked v2.

**Status: ASSUMPTION, leaning to `perception`.** `perception` is better sourced, but "better sourced"
is not "verified", and the agreement or disagreement of streams is not evidence either way.

**Why it matters.** The two revisions differ on whether the weights are commercially clean. Picking
the wrong one silently changes the project's license posture, and under section 6 a
`nvidia-open-model-license` weight may not enter the self-hosted pipeline at all.

**The experiment that settles it, five minutes (X-0e):**

```
curl -s https://huggingface.co/api/models/nvidia/diar_streaming_sortformer_4spk-v2 \
  | jq '.cardData.license, .cardData.license_name, .gated, .sha'
```

Pin the returned SHA. Do this before any diarization code is written. If it returns
`nvidia-open-model-license`, fall back to `pyannote/speaker-diarization-community-1` (CC-BY-4.0,
HF-gated).

---

## 5. Nebius catalog strings versus HuggingFace model cards

**VERIFIED, three of three checked, 2026-08-27.** Nebius' own model catalog disagrees with the
HuggingFace model cards, and it disagrees in a **consistent direction**: the catalog collapses three
differently named NVIDIA licenses into the single restrictive string `nvidia-open-model-license`.

| Model | Nebius catalog `license.name` | HF card | Direction of the error |
| --- | --- | --- | --- |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `nvidia-open-model-license` (restrictive) | `nvidia-nemotron-open-model-license` (permissive) | Nebius stricter |
| `nvidia/Nemotron-3-Nano-Omni` | `nvidia-open-model-license` (restrictive) | `nvidia-open-model-agreement` (permissive) | Nebius stricter |
| `nvidia/nemotron-3-super-120b-a12b` | `nvidia-open-model-license` (restrictive) | `nvidia-nemotron-open-model-license` (permissive) | Nebius stricter |

Source for the catalog column: <https://tokenfactory.nebius.com/api/public/models_info>, retrieved
2026-08-27. The catalog's `license.url` for all three points at the restrictive Open Model License
page, confirming it is one derived label rather than three readings.

**Which source to trust: the HuggingFace card frontmatter.** The Nebius catalog `license` field is a
derived label. The adversarial verifier independently confirmed that the three named documents are
genuinely different instruments with materially different terms (section 2).

**DECISION.** `THIRD_PARTY_NOTICES.md` records the license read from the **raw HuggingFace YAML
frontmatter at a pinned revision SHA**, never the Nebius catalog string and never the family name.
Rejected alternative: using the catalog field, which is one API call away and machine-readable, but
is wrong in three of three checked cases.

**The dangerous direction, and where it lands. OPEN.** All three verified mismatches are Nebius
being *stricter* than reality, which costs rights but is safe. The case that ends a project is the
opposite: the catalog being more permissive than the card. Exactly one row in this matrix has that
shape. `nvidia/Nemotron-3-Ultra-550b-a55b` is recorded as `openmdw-1.1` **from the catalog only**; it
does not appear in the four models whose OpenMDW-1.1 attribution was verified in raw HF frontmatter
(F39). The exposure is currently zero because Ultra has no role in Exulanica. **If that changes, run
the same `curl` used in section 4a against the Ultra card first.**

---

## 6. API-only use: what it does and does not cover

The convenient claim is: "we only call an API, so weights licenses do not bind us." **That is
partially true, and the research located exactly where the gap lands.**

**Where the claim holds.** Exulanica calls hosted weights over an inference API and vendors zero
weights into the repository. Model weights accessed over an API are not a derivative work of
Exulanica's source and are not redistributed by Exulanica. Redistribution clauses therefore do not bite.
Under this architecture even the restrictive NVIDIA Open Model License is satisfied by use, because
its problem clauses concern redistribution, revocation and derivative distribution. That converts a
licensing blocker into a licensing footnote for the Token Factory calls.

**Two corrections that narrow it.**

1. **An API-only consumer is instead bound by the hosted endpoint's terms of service, which nobody in
   the research corpus read. OPEN.** The Nebius Token Factory terms of service and acceptable use
   policy have not been retrieved. Read them before deployment.
2. **The perception pipeline is not API-only.** The plan self-hosts detection, segmentation, face
   embedding and (if ever revived) ASR and diarization in containers on Nebius AI Cloud. **That is
   downloading and running weights.** The API-only escape hatch covers the Token Factory calls and
   does not cover the self-hosted stack.

**Working the self-hosted case through precisely:**

- **Redistribution clauses still do not bite.** Running weights in your own container is use, not
  distribution, and nothing is vendored into the repository.
- **Use-time clauses do bite.** The NVIDIA Open Model License's grant is revocable, explicitly
  conditioned on full compliance, subject to unilateral amendment, and terminates automatically on
  guardrail circumvention. Self-hosting a weight under that license means operating under those
  terms, not shipping around them.
- **Non-commercial weights bite hardest.** CC-BY-NC-4.0, "non-commercial research purposes only" and
  unlicensed weights are blocked at use time, not only at distribution time. `nvidia/LocateAnything-3B`
  is the sharpest case: a publicly released project of this kind is arguably not "academic and
  non-profit research".
- **CC-BY-4.0 weights are clean for this purpose**, with an attribution obligation that is cheap to
  honour.
- **OpenMDW-1.1 weights are cleanest**, and require retaining the agreement plus origin notices on
  any distribution.

**DECISION.** The self-hosted stack uses only **CC-BY-4.0, OpenMDW-1.1, Apache-2.0, MIT or
public-domain weights**. Nothing under the NVIDIA Open Model License enters the pipeline, not even
for self-hosted use, because the revocability and unilateral-amendment clauses are not worth the
capability delta over the clean alternatives. Rejected alternative: allowing NVIDIA Open Model
License weights in containers on the reasoning that "use is not distribution", which is true of the
redistribution clauses and false of the guardrail, revocation and amendment clauses.

The current self-hosted stack satisfies this by construction: YuNet (MIT), dlib 5-point (public
domain), SFace (Apache-2.0), SAM 2.1 (Apache-2.0), Grounding DINO (Apache-2.0), DINOv2 (Apache-2.0),
gsplat (Apache-2.0), MoGe-2 (MIT).

---

## 7. THIRD_PARTY_NOTICES and the NOTICE-file obligations

Naming note: the research drafts call this file `THIRD_PARTY_LICENSES.md`. This document uses
`THIRD_PARTY_NOTICES.md`. It is one file under either name; pick one and use it consistently in the
repository root.

### 7.1 What `THIRD_PARTY_NOTICES.md` must contain

1. **Every model**, with its exact HuggingFace repo id, its **pinned revision SHA**, the license read
   from the raw frontmatter at that SHA, and the source URL. Not the family name, not the Nebius
   catalog string.
2. **Every third-party code dependency** with a license that is not Apache-2.0, with its license
   identifier and URL. That is at minimum: three.js, Spark, react-three-fiber, drei, PlayCanvas,
   splat-transform, spz, ByteTrack, BoT-SORT (MIT); d3-force (ISC); COLMAP (New BSD); WhisperX
   (BSD-2-Clause); dlib (Boost 1.0); MoGe (MIT); the dlib 5-point and face-recognition models (public
   domain).
3. **The CC-BY-4.0 attributions**, which are a live obligation rather than a formality: NVIDIA for
   any Parakeet, Canary v2, TitaNet or (pending section 4a) Sortformer v2 weights, and WeSpeaker for
   its weights.
4. **The OpenMDW-1.1 condition**: on redistribution, retain a copy of the agreement and all notices
   of origin. Applies to Nemotron-3.5-Lightning, `nemotron-3.5-asr-streaming-0.6b` and the
   Nemotron-3-Embed models.
5. **The NVIDIA attribution strings**, which are conditional on a NOTICE file being present in the
   distribution: "Licensed by NVIDIA Corporation under the NVIDIA Nemotron Model License." for
   Nemotron Open Model License models, and "Licensed by NVIDIA Corporation under the NVIDIA Open
   Model Agreement." for Open Model Agreement models.
6. **Honest disclosure of the residual dataset-provenance caveat**, rather than a claim that the
   weights are fully clean. The defensible line, stated in the research: these artifacts carry
   **explicit permissive grants from their copyright holders**, unlike InsightFace, EdgeFace and
   AdaFace, which carry either an explicit non-commercial restriction or no grant at all. Grounding
   DINO's Cap4M training set is undisclosed web-crawled data whose terms IDEA-Research has never
   published; the same residual attaches to SFace and to the dlib model. An Apache-2.0 grant covers
   the grantor's own rights and cannot cure third-party rights in scraped data.
7. **The UNVERIFIED list from this document, reproduced verbatim**, so a reader can see what was not
   checked rather than inferring that silence means clean.

### 7.2 CC-BY attribution needs a UI surface, not only a file

**DECISION.** CC-BY-4.0 attribution is a real obligation and a file alone is a weak discharge of it.
Attributions appear in the application's credits or about surface as well as in
`THIRD_PARTY_NOTICES.md`. Rejected alternative: a file only, which is what most projects do and which
leaves the obligation arguably unmet for a user-facing product.

### 7.3 Apache-2.0 NOTICE-file mechanics. OPEN.

Two obligations are in play and **the research corpus never quoted the Apache-2.0 text itself**, so
the mechanics below are recorded as the operating rule and are **not** VERIFIED here:

- **Inbound.** Where an Apache-2.0 dependency ships its own NOTICE file, its attribution notices
  propagate into ours. Nobody has enumerated which of the Apache-2.0 dependencies above ship a NOTICE
  file.
- **Outbound.** Exulanica's own top-level `LICENSE` must remain the **unmodified** Apache-2.0 text.
  This is not merely hygiene: GitHub only detects the license and renders the Apache-2.0 chip in the
  repository About section from a recognized filename with unmodified text, and that chip is how most
  readers and automated scanners determine the project's licence. Do not append project-specific terms to
  `LICENSE`; put them in `NOTICE` or `THIRD_PARTY_NOTICES.md`.

**Experiment that settles both, 15 minutes (X-0g):** read the Apache-2.0 text we ship, enumerate
NOTICE files across the Apache-2.0 dependency set, and confirm GitHub renders the Apache-2.0 chip on
the repository page.

---

## 8. Consolidated OPEN and UNVERIFIED items

Nothing in this list is a verdict. Each is an admission that a license was not read, with the check
that closes it.

| # | Item | Why it matters | Check |
| --- | --- | --- | --- |
| L-1 | `nvidia/diar_streaming_sortformer_4spk-v2` license, **DISPUTED** | Determines whether diarization is commercially clean | X-0e, section 4a. 5 min |
| L-2 | `MiniMaxAI/MiniMax-M3` license text never read | It is Nebius' recommended replacement for the removed NVIDIA vision models and the only catalog model declaring the `video` use case | Read <https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/main/LICENSE>. 10 min |
| L-3 | `openbmb/MiniCPM-V-4_5` license is recorded from the Nebius catalog, whose URL points at the **code** repo | It is the primary vision sensor. Under the section 5 rule, a catalog reading is not authoritative | `curl` the HF card frontmatter for the pinned SHA. 5 min |
| L-4 | `nvidia/Nemotron-3-Ultra-550b-a55b` OpenMDW-1.1 attribution is catalog-only, and is the one row where the catalog is **more** permissive than any verified reading | The error direction that ends a project. Exposure is currently zero because Ultra has no role | `curl` the HF card before any use. 5 min |
| L-5 | PostgreSQL 18 and pgvector 0.8.6 license text never read | Two core dependencies | X-0g. 15 min, with the GitHub chip check |
| L-6 | ffmpeg build configuration in the container: LGPL or GPL | Matters only if the binary is redistributed. We invoke it as a subprocess and do not link it | Inspect the container's ffmpeg build flags |
| L-7 | RO-Crate and Croissant **tooling library** licenses | The specs are open standards; the libraries were never checked | Read each library's LICENSE before adoption. Fallback: write the RO-Crate JSON-LD by hand |
| L-8 | Nebius Token Factory terms of service and acceptable use policy never read | This is the instrument that actually binds API-only use (section 6) | Retrieve and read both. 30 min |
| L-9 | `nvidia/difix`, `nvidia/difix_ref` "NVIDIA License" never read in full | Difix3D+ is an optional quality step | Read the in-repo license before use |
| L-10 | Pi3 weights, **DISPUTED** between HF frontmatter (`bsd-2-clause`) and the GitHub README (non-commercial research and education only) | Blocked in the interim, so no exposure | Not scheduled. The model is not needed |
| L-11 | Apache-2.0 NOTICE mechanics, inbound and outbound (section 7.3) | Determines what `NOTICE` must contain | X-0g |
| L-12 | `google/gemma-3-27b-it` Gemma License use restrictions never read | Avoided, so no exposure | Not scheduled |

---

## 9. Mechanical enforcement

All cheap, and all of it should exist before the perception pipeline is written.

- One `models.manifest.json` holding, for every model: repo id, **revision SHA**, and the license read
  from the raw HuggingFace frontmatter at that SHA.
- CI job that re-fetches each pinned revision's `cardData.license` and **fails on drift**.
- CI job that scans the full transitive dependency tree for **GPL and AGPL**.
- CI job that greps the built image for: `insightface`, `shape_predictor_68`,
  `diff_gaussian_rasterization`, `ultralytics`, `boxmot`, `crisperwhisper`, `canary-1b` (exact match,
  not `canary-1b-v2`), `sortformer_4spk-v1`, `map-anything` without the `-apache` suffix.
- `THIRD_PARTY_NOTICES.md` plus a CC-BY attribution surface in the application's credits UI.
- Verify GitHub renders the **Apache-2.0 chip** at the top of the repository page.

---

## 10. Provenance

Promoted from `.exulanica/research/00-RECONCILED-REPORT.md` Part E, sections B4, B5, C-D1, C-D4, C-D9
and C-D13; `.exulanica/research/nvidia-models.md` sections 1.1 and 1.2; `.exulanica/research/perception.md`
sections 0, 1.2, 6.1, 6.1.1 and 9; `.exulanica/research/00-RISK-REGISTER.md` entries R-07, R-29, R-30,
R-35, R-39 and R-67; and the primary catalog data in `.exulanica/research/nebius-raw-catalog.md` and
`nebius-raw-models_info.json`.

All primary sources retrieved **2026-08-27**. No claim in this document has been re-verified since.
**No model identifier in this corpus has ever been invoked**, so every hosted-model row describes a
catalog entry, not an observed response.


## 11. HEIC decoder candidate review, 2026-09-11

**Candidate only, not installed or added to the lock.** `pi-heif==1.4.0` provides a decode-only
alternative to Pillow-Heif. The inspected Python 3.11 macOS arm64 wheel contains BSD-3-Clause
wrapper code and declares LGPLv3 for bundled libheif and libde265. Its bundled notice lists no
x265 encoder. The Python wrapper's BSD metadata alone would therefore be an incomplete license
claim. [Package and wheel inventory](https://pypi.org/project/pi-heif/1.4.0/).

Inspected wheel: `pi_heif-1.4.0-cp311-cp311-macosx_11_0_arm64.whl`, SHA-256
`dafa2ea7e7ff594f64fa60e0cd25b3dea9d200277d7aed9fb2b73835fa41fb6d`.
The wheel's `LICENSE.txt` digest is
`9e2635f155b00af5a46cb2f2c9b052072ec546d59837ee74efc9cba2cbb83f3d`; its
`LICENSES_bundled.txt` digest is
`8155948291bc988b17fa600308e359be32111c1a22aef1dab7b330f17b8106d3`.

The bundled notice points to [libheif v1.18.1 COPYING](https://github.com/strukturag/libheif/blob/v1.18.1/COPYING)
and [libde265 v1.0.15 COPYING](https://github.com/strukturag/libde265/blob/v1.0.15/COPYING).
Those primary texts were read, including LGPLv3's additional permissions and its incorporated GPLv3
terms. LGPLv3 permits application use under separate terms, subject to its conditions. Distribution
requires the applicable notices and license texts, plus a suitable replaceable shared-library
mechanism or corresponding source and relinking material. Runtime use is not a finding that
binary redistribution obligations have been fulfilled. These notices name source versions; the
actual compiled library versions and Linux wheel contents remain unverified.

This is evidence for a viable LGPL decoder candidate, not evidence that no license-clean decoder
exists. No decoder has been approved for redistribution. The current implementation blocker is
separate: the writable set excludes dependency pins and ingest stage wiring, and migration 0040
requires any non-null geometry `read_source_sha256` to resolve to a current masked-source artifact.
A distinct format conversion must not bypass that guard or masquerade as a privacy mask.

# Third party notices

Exulanica is distributed under the Apache License, Version 2.0. The unmodified license text is in
[LICENSE](LICENSE) at the repository root.

This file records the third party work Exulanica depends on, together with the attribution each
license requires. It is built from three sources: the dependency manifests in this repository
(`pyproject.toml`, `uv.lock`, `web/package.json` and the `web/packages/*/package.json` files), the
model manifest at `exulanica/models/models.manifest.json`, and the component analysis in
[docs/license-matrix.md](docs/license-matrix.md).

Dependency license identifiers and copyright lines below were read on **2026-08-28** from the
license files and package metadata shipped inside the resolved packages themselves, in the local
virtual environment and in `web/node_modules`, not from a summary or an index. Where that was not
possible, the row says so.

---

## 1. How to read this file

### Status vocabulary

The same vocabulary the rest of the documentation set uses, applied to license claims.

| Status | Meaning here |
| --- | --- |
| **VERIFIED** | The license text or the license metadata shipped with the artifact was read, on the date given |
| **UNVERIFIED** | Nobody has read the license for this entry. It appears here so that the gap is visible rather than silent |
| **DISPUTED** | Two primary sources give different answers and neither has been settled |
| **OPEN** | A question that has to be answered before submission, with the check that answers it |

**An entry with no status marker in section 9 is one whose license nobody has read.** Silence in
this file never means clean. Section 9 lists every gap known at the time of writing.

### What this file does and does not assert

- It asserts what the license identifier was at the moment it was read, at the version pinned in the
  lock files.
- It does not assert that any dependency's own upstream training data or vendored subcomponents are
  free of third party rights. Section 8 states that limit explicitly.
- It does not assert that the transitive dependency tree has been fully enumerated. Section 4.3 and
  section 5.3 record how far the enumeration actually goes.

### Scope: nothing is vendored

**DECISION, carried from [docs/license-matrix.md](docs/license-matrix.md) section 1.** No model
weights are vendored into this repository, and no third party source is copied into it. Every
dependency is resolved at build time from its own registry, and every model is called over a network
API or, where a model is self-hosted, downloaded at deployment time. Redistribution clauses therefore
do not attach to this repository's contents. Use-time clauses still bind the operator, which is why
section 3 and section 7 exist.

---

## 2. Exulanica's own license

| Item | Value |
| --- | --- |
| License | Apache License, Version 2.0 |
| File | `LICENSE`, 201 lines, unmodified upstream text, appendix template unfilled |
| Status | **VERIFIED** 2026-08-28 by reading the file |

Project specific terms are never appended to `LICENSE`. They belong here or in a `NOTICE` file.

---

## 3. Hosted models called over an API

These are the models Exulanica calls on Nebius Token Factory. Every identifier below comes from
`exulanica/models/models.manifest.json`, which is the only place in the codebase where a model
identifier is allowed to exist.

**No weights are downloaded, stored or redistributed by Exulanica for any row in this section.** The
call is an HTTPS request to `https://api.tokenfactory.nebius.com/v1`.

### 3.1 The reading problem, stated before the table

[docs/license-matrix.md](docs/license-matrix.md) section 5 records a **VERIFIED** finding that
matters for every row here: the Nebius Token Factory catalog and the HuggingFace model card
frontmatter disagree about NVIDIA model licenses, in three of three cases checked, and the catalog
collapses three differently named NVIDIA instruments into the single restrictive string
`nvidia-open-model-license`. The catalog `license` field is a derived label, and the standing
decision is to record the license read from the raw HuggingFace frontmatter at a pinned revision
SHA instead.

**OPEN, and it is the largest gap in this file.** That decision has not been carried out. The
`catalog_license` values in `exulanica/models/models.manifest.json` are Nebius catalog strings, and
no model in this project has a pinned HuggingFace revision SHA. The "License recorded here" column
below therefore states what was actually read, and by whom, rather than presenting a catalog string
as a verified license. Closing this is item **T-1** in section 9.

### 3.2 NVIDIA reasoning models

| Model identifier | Role | License recorded here | Source of that reading | Status |
| --- | --- | --- | --- | --- |
| `nvidia/Nemotron-3_5-Lightning` | reasoning, cheap tier, primary | **OpenMDW-1.1** | Raw HuggingFace card frontmatter, read 2026-08-27. The Nebius catalog agrees (`OpenMDW v1.1`) | **VERIFIED** |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | reasoning, cheap tier, fallback | **NVIDIA Nemotron Open Model License** | HuggingFace card. The Nebius catalog says `nvidia-open-model-license`, which is the stricter of the two and is a derived label | **DISPUTED between sources, resolved in favour of the card** per license-matrix section 5 |
| `nvidia/nemotron-3-super-120b-a12b` | reasoning, mid tier, primary | **NVIDIA Nemotron Open Model License** | HuggingFace card. Nebius catalog again says `nvidia-open-model-license` | **DISPUTED between sources, resolved in favour of the card** |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | reasoning, hard tier, primary | `openmdw-1.1` **per the Nebius catalog only** | Nebius catalog. No HuggingFace card reading exists for this model | **UNVERIFIED. See the warning below** |

**Warning, and it is a change from what license-matrix section 5 records.** The matrix states that
`nvidia/Nemotron-3-Ultra-550b-a55b` is the one row where the catalog is *more permissive* than any
verified reading, and that "the exposure is currently zero because Ultra has no role in Exulanica".
**That is no longer true.** The model manifest names it as the primary for the `reasoning_hard`
role. Nothing routes to it by default and it is reachable only by asking for the hard role
explicitly, so the exposure is small, but it is not zero. The HuggingFace card must be read before
that role is used. Item **T-2** in section 9.

**Attribution strings required by the NVIDIA instruments**, conditional on a notices file being
present in the distribution, which this file is:

> Licensed by NVIDIA Corporation under the NVIDIA Nemotron Open Model License.

applies to `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and `nvidia/nemotron-3-super-120b-a12b`.

**OpenMDW-1.1 condition.** On redistribution of the materials, retain a copy of the agreement and
all notices of origin. Exulanica redistributes no weights, so the condition is recorded rather than
triggered. It applies to `nvidia/Nemotron-3_5-Lightning`, and to
`nvidia/Nemotron-3-Ultra-550b-a55b` if its catalog reading is confirmed.

License instrument texts:

- OpenMDW-1.1: <https://openmdw.ai/license/1-1/>
- NVIDIA Nemotron Open Model License:
  <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license>
- NVIDIA Open Model Agreement:
  <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/>
- NVIDIA Open Model License (the restrictive instrument, listed for contrast; no model Exulanica calls
  is recorded under it by its own model card):
  <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/>

**Version strings of the NVIDIA instruments, recorded as retrieved 2026-08-27.** The NVIDIA Open
Model Agreement page carried two different version strings across two readings ("Effective: April 2,
2026" and "version 2026-03-09") with identical operative terms. The Nemotron Open Model License page
read "Last Modified 2025-12-15". Re-read and record whichever string the page shows at submission
time.

### 3.3 Vision, extraction and embedding models

| Model identifier | Role | License recorded here | Source of that reading | Status |
| --- | --- | --- | --- | --- |
| `MiniMaxAI/MiniMax-M3` | vision sensor, primary | Custom license named only "MiniMax-M3" | Nebius catalog string. **The license text has never been read** | **UNVERIFIED. Highest priority gap in this section** |
| `openbmb/MiniCPM-V-4_5` | vision sensor, fallback | "Apache 2.0 License" per the Nebius catalog, whose `license.url` points at the **code** repository LICENSE rather than at the weights card | Nebius catalog | **UNVERIFIED as a weights license** |
| `Qwen/Qwen3-Embedding-8B` | embedding, primary, no fallback exists | Apache-2.0 | Nebius catalog | **UNVERIFIED against the card frontmatter** |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | structured extraction, primary, not in any default route | Apache-2.0 | Nebius catalog | **UNVERIFIED against the card frontmatter** |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | structured extraction, fallback, not in any default route | MIT | Nebius catalog, corroborated by the repository LICENSE at <https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/main/LICENSE> | **UNVERIFIED against the card frontmatter** |

`MiniMaxAI/MiniMax-M3` is the sharpest entry in this file. It is the **primary** vision sensor, every
photograph in the corpus passes through it, and nobody has read its license. Item **T-3** in
section 9.

### 3.4 The instrument that actually binds API-only use

**OPEN.** Calling hosted weights over an API is use, not redistribution, so the weights licenses
above bite far less than they would if anything were vendored. The instrument that does bind an
API-only consumer is the hosted endpoint's own terms of service and acceptable use policy. The
Nebius Token Factory terms of service and acceptable use policy have not been retrieved or read.
Item **T-4** in section 9.

The same applies to the Tavily Search API, used for the optional public-entity lookup. Tavily's
privacy page was read on 2026-08-27 and is quoted in
[docs/model-and-service-selection.md](docs/model-and-service-selection.md) section 2.5. Its terms of
service were not.

---

## 4. Python dependencies

Read on **2026-08-28** from the installed distribution metadata and the license files shipped inside
each wheel, at the versions pinned in `uv.lock`.

### 4.1 Runtime dependencies

These four are declared in `pyproject.toml` under `[project].dependencies` and are required to run
the application.

| Package | Version | License | Required attribution |
| --- | --- | --- | --- |
| `httpx` | 0.28.1 | BSD-3-Clause | Copyright © 2019, Encode OSS Ltd. <https://www.encode.io/> |
| `jsonschema` | 4.26.0 | MIT | Copyright (c) 2013 Julian Berman |
| `pillow` | 12.3.0 | MIT-CMU (the historical PIL permission notice) | Copyright © 1997-2011 by Secret Labs AB. Copyright © 1995-2011 by Fredrik Lundh and contributors. Copyright © 2010 by Jeffrey A. Clark and contributors |
| `pydantic` | 2.13.4 | MIT | Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors |

**Note on Pillow.** The binary wheels bundle native imaging libraries that carry their own licenses.
The shipped license file includes at least one such notice, "Copyright (c) 2016, Alliance for Open
Media. All rights reserved." The full set of bundled native library licenses has not been
enumerated. Item **T-5** in section 9.

### 4.2 Transitive runtime dependencies

Resolved by `uv.lock` and installed alongside the four above.

| Package | Version | License | Required attribution |
| --- | --- | --- | --- |
| `annotated-types` | 0.8.0 | MIT | Copyright (c) 2022 the contributors |
| `anyio` | 4.14.2 | MIT | Copyright (c) 2018 Alex Grönholm |
| `attrs` | 26.1.0 | MIT | Copyright (c) 2015 Hynek Schlawack and the attrs contributors |
| `certifi` | 2026.7.22 | MPL-2.0 | Mozilla Public License 2.0. The package contains a modified version of `ca-bundle.crt`, a bundle of X.509 root certificates extracted from Mozilla's root certificate store |
| `h11` | 0.16.0 | MIT | Copyright (c) 2016 Nathaniel J. Smith and other contributors |
| `httpcore` | 1.0.9 | BSD-3-Clause | Copyright © 2020, Encode OSS Ltd. <https://www.encode.io/> |
| `idna` | 3.19 | BSD-3-Clause | Copyright (c) 2013-2026, Kim Davies and contributors |
| `jsonschema-specifications` | 2025.9.1 | MIT | Copyright (c) 2022 Julian Berman |
| `pydantic-core` | 2.46.4 | MIT | Copyright (c) 2022 Samuel Colvin |
| `referencing` | 0.37.0 | MIT | Copyright (c) 2022 Julian Berman |
| `rpds-py` | 2026.6.3 | MIT | Copyright (c) 2023 Julian Berman |
| `typing-extensions` | 4.16.0 | PSF-2.0 (Python Software Foundation License 2.0) | Copyright (c) 2001 to present, Python Software Foundation. All rights reserved |
| `typing-inspection` | 0.4.4 | MIT | Copyright (c) Pydantic Services Inc. 2025 to present |

**Note on certifi.** MPL-2.0 is a file-level copyleft and is compatible with distribution alongside
Apache-2.0 work, but it is not MIT or BSD and it carries a source availability obligation for the
covered files if they are distributed in modified form. Exulanica does not modify or redistribute
certifi. The row is called out here because MPL-2.0 is the only copyleft license in the runtime
dependency set.

### 4.3 Optional and development dependencies

Not required to run the application. `psycopg` is installed only via the `postgres` extra, which is
needed to run the migration against a live PostgreSQL server.

| Package | Version | License | Required attribution | Group |
| --- | --- | --- | --- | --- |
| `psycopg` | 3.3.4 | **LGPL-3.0-only** | GNU Lesser General Public License v3.0. Copyright notices in the shipped `COPYING.LESSER` reference the Free Software Foundation text | `postgres` extra |
| `psycopg-binary` | 3.3.4 | **LGPL-3.0-only** | As above | `postgres` extra |
| `pytest` | 9.1.1 | MIT | Copyright (c) 2004 Holger Krekel and others | dev |
| `ruff` | 0.16.5 | MIT | Copyright (c) 2022 Charles Marsh | dev |
| `iniconfig` | 2.3.0 | MIT | Copyright (c) 2010-2023 Holger Krekel and others | dev, transitive |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | Copyright (c) Donald Stufft and individual contributors | dev, transitive |
| `pluggy` | 1.6.0 | MIT | Copyright (c) 2015 Holger Krekel | dev, transitive |
| `pygments` | 2.21.0 | BSD-2-Clause | Copyright (c) 2006-2022 by the respective authors (see the package AUTHORS file) | dev, transitive |
| `colorama` | 0.4.6 | Not read | Resolved by `uv.lock` under a `sys_platform == 'win32'` marker, so it is not installed on the development or deployment platform and its license file was not available locally | dev, transitive, Windows only |
| `tzdata` | 2026.3 | Not read | As above, `sys_platform == 'win32'` marker | dev, transitive, Windows only |

**The psycopg rows need a decision, and they are not covered by the existing analysis.**
[docs/license-matrix.md](docs/license-matrix.md) does not mention psycopg at all, and its mechanical
enforcement plan (section 9 of that document) scans only for GPL and AGPL. LGPL-3.0 is neither, and
it is the standard license for PostgreSQL drivers in Python, but "standard" is not "analysed". The
relevant questions are whether the deployed container redistributes the library and whether the
LGPL's relinking obligation is discharged by the fact that Python imports it dynamically at run
time. Neither has been answered here. Item **T-6** in section 9.

**Enumeration limit.** The rows above are the complete contents of `uv.lock`, which resolves 27
packages plus the `orimera` project itself. The Python dependency tree is small enough to enumerate
by hand and it has been enumerated in full.

---

## 5. Browser and frontend dependencies

Read on **2026-08-28** from `web/package.json`, the `web/packages/*/package.json` files,
`web/pnpm-lock.yaml`, and the license files inside the resolved packages in `web/node_modules`.

### 5.1 Shipped in the browser bundle

| Package | Version | License | Required attribution | Where |
| --- | --- | --- | --- | --- |
| `playcanvas` | 2.21.4 | MIT | Copyright (c) 2011-2026 PlayCanvas Ltd. | `@exulanica/atlas-react`, the selected renderer per [docs/adr/0003-renderer-selection.md](docs/adr/0003-renderer-selection.md) |
| `three` | 0.185.1 | MIT | Copyright © 2010-2026 three.js authors | `@exulanica/atlas-three` and `@exulanica/bakeoff` |
| `@sparkjsdev/spark` | 2.1.0 | MIT | Copyright © 2025 World Labs Technologies, Inc. | `@exulanica/atlas-three` |

**Honest note on the three.js rows.** The renderer decision is PlayCanvas. The three.js plus Spark
binding is **retained in the repository as the measured alternative and as insurance, and is not
built or shipped** (ADR-0003, Consequences). It is listed here because it is a declared dependency
of a package in this repository and a reader auditing the manifests will find it, not because it
reaches a browser today.

### 5.2 Build and development tooling

Not shipped to the browser. Listed because they are declared in the workspace manifests and because
an Apache-2.0 entry (`typescript`) carries its own attribution requirement.

| Package | Version | License | Required attribution |
| --- | --- | --- | --- |
| `typescript` | 5.9.3 | Apache-2.0 | Copyright (c) Microsoft Corporation. The package ships its own `ThirdPartyNoticeText.txt`, whose contents are not reproduced here |
| `vite` | 6.4.3 and 8.2.2 (two majors resolved across the workspace) | MIT | Copyright (c) 2019 to present, VoidZero Inc. and Vite contributors |
| `vitest` | 2.1.9 | MIT | Copyright (c) 2021 to present Vitest Team. Copyright (c) 2021 Anthony Fu |
| `tsx` | 4.23.12 | MIT | Copyright (c) Hiroki Osame |
| `dependency-cruiser` | 16.10.4 | MIT | Copyright (c) 2016-2025 Sander Verweij |
| `@types/node` | 22.20.1 | MIT | Copyright (c) Microsoft Corporation, DefinitelyTyped contributors |
| `@types/three` | 0.185.4 | MIT | Copyright (c) Microsoft Corporation, DefinitelyTyped contributors |

### 5.3 Enumeration limit, stated plainly

`web/pnpm-lock.yaml` resolves **246** package versions. The tables above cover the **direct**
dependencies declared in the workspace manifests. The remaining entries are the transitive build
toolchain (bundler internals, compiler plugins, test runner internals and their platform specific
binaries) and have **not** been enumerated or license checked one by one.

That is a real gap, and it is smaller than it looks for one reason: none of the unenumerated packages
is shipped to the browser. The browser bundle is produced from the three packages in section 5.1 plus
this repository's own TypeScript. It is still a gap, and closing it is a scripted pass rather than a
judgement call. Item **T-7** in section 9.

### 5.4 Workspace packages

`@exulanica/atlas-core`, `@exulanica/atlas-react`, `@exulanica/atlas-three`, `@exulanica/bakeoff`,
`@exulanica/companion-runtime`, `@exulanica/graph-client`, `@exulanica/landing`, `@exulanica/scene-synth`
and `@exulanica/world-index` are private packages in this repository. They are covered by Exulanica's
own Apache-2.0 license and require no separate notice.

---

## 6. Components selected but not yet present in a manifest

[docs/license-matrix.md](docs/license-matrix.md) records ship or do-not-ship verdicts for a much
larger set of components than this repository currently depends on, because the reconstruction and
perception pipelines are designed and not yet built. The components below carry a **SHIP** verdict
and are expected to enter the build. They are listed here so that the notices file is ahead of the
code rather than behind it.

**None of these appears in `pyproject.toml`, `uv.lock` or any `package.json` today.** Nothing in this
section is currently distributed, executed or downloaded by this repository.

| Component | Expected role | License per the matrix | Attribution note |
| --- | --- | --- | --- |
| `nerfstudio-project/gsplat` | The mandatory Gaussian splat rasterizer | Apache-2.0 | Notice required when adopted |
| COLMAP | Structure from motion | New BSD | Copyright notice required when adopted |
| MoGe (Microsoft) | Monocular point maps, the primary reconstruction rung for a photograph corpus | MIT, except a vendored DINOv2 which is Apache-2.0 | Both notices required when adopted |
| `nv-tlabs/3dgrut` | Rolling shutter aware 3DGUT / 3DGRT | Apache-2.0 | Notice required when adopted |
| `facebook/map-anything-apache` (weights) | Feed forward pose rescue | Apache-2.0 | Must not be confused with `facebook/map-anything`, whose weights are CC-BY-NC-4.0 and are blocked |
| SAM 2.1 | Segmentation | Apache-2.0, code and checkpoints | Notice required when adopted |
| Grounding DINO (open, 2023) | Detection | Apache-2.0, code and weights | See the dataset provenance disclosure in section 8 |
| DINOv2 | Appearance vectors | Apache-2.0, code and weights | Notice required when adopted |
| OpenCV Zoo YuNet | Face detection | MIT | Notice required when adopted |
| OpenCV Zoo SFace | Face embedding | Apache-2.0 | See section 8 |
| dlib and `dlib_face_recognition_resnet_model_v1` | Face alignment and embedding | Boost Software License 1.0 (library); the model weights and the 5 point landmark predictor are released into the public domain by their author | Only the **5 point** landmark predictor. Both 68 point variants are blocked, see below |
| ByteTrack | Tracking | MIT | Zero weights exposure by design |
| `@playcanvas/splat-transform` | SOG asset production | MIT | Notice required when adopted |
| `nianticlabs/spz` | Splat interchange format | MIT | Notice required when adopted |
| d3-force | Deterministic index layout | ISC | Notice required when adopted |
| Label Studio | Annotation | Apache-2.0 | Tooling, not shipped |

**Components deliberately excluded, recorded here because their absence is itself a compliance
claim.** The matrix blocks, among others, the INRIA `gaussian-splatting` rasterizer and
`diff-gaussian-rasterization` (non-commercial, viral to derivatives), InsightFace (weights are
non-commercial research only and the repository has no license file), Ultralytics, YOLOE, YOLO-World
and BoxMOT (GPL-3.0 and AGPL-3.0), the dlib 68 point landmark predictors (explicit no commercial
product carve out), `facebook/map-anything` non-Apache weights, VGGT, DUSt3R, MASt3R, CUT3R, Fast3R,
EdgeFace and AdaFace. If any of these appears in a future dependency tree or built image, it is a
defect, not a choice. [docs/license-matrix.md](docs/license-matrix.md) section 9 specifies the
mechanical checks that enforce this; those checks are not yet implemented.

---

## 7. Attribution obligations that this file alone does not discharge

### 7.1 CC-BY-4.0 attribution needs a visible surface

**DECISION**, carried from license-matrix section 7.2. Creative Commons Attribution 4.0 is a live
obligation for a user-facing product, and a file in a repository is a weak discharge of it.
Attributions for any CC-BY-4.0 licensed artifact must appear in the application's credits or about
surface as well as here.

**No CC-BY-4.0 artifact is currently in use.** The CC-BY-4.0 entries in the license matrix are all
NVIDIA speech models (Parakeet, Canary v2, TitaNet) and speaker embedding models, which belong to the
audio capability. The corpus is photographs and carries no audio, so that capability is deferred and
those artifacts are not called, downloaded or shipped. If the audio capability is ever revived, the
credits surface obligation activates with it.

### 7.2 Apache-2.0 NOTICE mechanics

**OPEN.** Two obligations are in play and neither has been fully worked through:

- **Inbound.** Where an Apache-2.0 dependency ships its own `NOTICE` file, its attribution notices
  propagate into ours. A partial scan on 2026-08-28 found that `typescript` ships a
  `ThirdPartyNoticeText.txt`, and that `three` and `playcanvas` (both MIT) ship none. No Python
  package in `uv.lock` was found to ship a `NOTICE` file. The scan was partial and covered direct
  dependencies only.
- **Outbound.** Exulanica's top-level `LICENSE` must remain the unmodified Apache-2.0 text so that the
  repository host detects the license and renders the license indicator on the repository page. That
  file was confirmed unmodified on 2026-08-28.

Item **T-8** in section 9.

---

## 8. Dataset provenance: the residual that permissive licenses cannot cure

Stated here deliberately rather than omitted, because omitting it would leave a reader to infer a
guarantee that does not exist.

Several components in section 6 carry explicit permissive grants from their copyright holders and
were nonetheless trained on datasets whose own terms are undisclosed or unpublished. Grounding DINO's
Cap4M training set is undisclosed web crawled data whose terms IDEA-Research has never published. The
same residual attaches to the OpenCV Zoo SFace model and to the dlib face recognition model.

**An Apache-2.0 or MIT grant covers the grantor's own rights and cannot cure third party rights in
scraped data.** That is a general limit of permissive licensing on trained artifacts, not a defect
specific to these projects.

The defensible line, and the one this project takes: these artifacts carry **explicit permissive
grants from their copyright holders**, which is a materially different position from InsightFace,
EdgeFace and AdaFace, which carry either an explicit non-commercial restriction or no grant at all.
That is a difference in kind, not a difference in confidence.

---

## 9. What still needs verification before submission

Every item is a gap, not a verdict. Each names the check that closes it. Items T-1 through T-4 are
the ones that would matter to a reviewer.

| # | Item | Why it matters | Check | Effort |
| --- | --- | --- | --- | --- |
| **T-1** | No model in `models.manifest.json` has a pinned HuggingFace revision SHA, and the recorded `catalog_license` values are Nebius catalog strings, which are derived labels known to be wrong in three of three checked cases | The standing decision (license-matrix section 5) is to record the license from raw card frontmatter at a pinned SHA. It has not been carried out for any model | For each identifier, `curl https://huggingface.co/api/models/<id>` and record `cardData.license`, `gated` and `sha`. Add the SHA and the frontmatter license to the manifest | 30 min |
| **T-2** | `nvidia/Nemotron-3-Ultra-550b-a55b` carries a catalog-only `openmdw-1.1` reading, which is the one known case where the catalog is more permissive than any verified reading, **and it is now the declared primary for the `reasoning_hard` role** | This is the error direction that invalidates a compliance claim. license-matrix section 5 records the exposure as zero, which is out of date | Read the HuggingFace card before the hard role is used, and correct license-matrix section 5 either way | 5 min |
| **T-3** | `MiniMaxAI/MiniMax-M3` custom license text has never been read | It is the **primary** vision sensor. Every photograph passes through it | Read <https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/main/LICENSE> | 10 min |
| **T-4** | Nebius Token Factory terms of service and acceptable use policy never retrieved | This is the instrument that actually binds API-only use, which is most of what Exulanica does | Retrieve and read both. Do the same for Tavily's terms of service | 30 min |
| **T-5** | Pillow's bundled native imaging library licenses not enumerated | The wheels bundle native libraries with their own notices, at least one of which (Alliance for Open Media) appears in the shipped license file | Read the complete license file shipped in the wheel and reproduce the bundled notices here | 15 min |
| **T-6** | `psycopg` and `psycopg-binary` are **LGPL-3.0-only** and are not analysed anywhere in the documentation set | The existing enforcement plan scans for GPL and AGPL only. LGPL is neither, and the relinking obligation has not been assessed against a deployed container | Decide whether the deployed image redistributes the library, and record the conclusion. Add LGPL to the dependency scan | 30 min |
| **T-7** | 246 resolved npm package versions, of which only the direct dependencies are license checked | None is shipped to the browser, which bounds the exposure but does not close it | Run a license enumeration over `pnpm-lock.yaml` and append or attach the result | 30 min |
| **T-8** | Apache-2.0 NOTICE mechanics, inbound and outbound (section 7.2) | Determines whether a separate `NOTICE` file is required and what it must contain | Enumerate `NOTICE` files across the full Apache-2.0 dependency set, then decide | 15 min |
| **T-9** | `openbmb/MiniCPM-V-4_5` license recorded from a catalog entry whose URL points at the **code** repository rather than the weights card | It is the vision fallback, so it is on a live failover path | `curl` the card frontmatter at a pinned SHA | 5 min |
| **T-10** | `colorama` and `tzdata` licenses not read | Both resolve only under a Windows platform marker and are not installed on the development or deployment platform | Read from the published package metadata if either platform ever becomes relevant | 5 min |
| **T-11** | The mechanical enforcement described in license-matrix section 9 (manifest SHA pinning, catalog drift CI job, GPL and AGPL dependency scan, built-image grep for the named blocked packages) is specified and **not implemented** | These checks are what keep this file true after it is written | Implement before the perception pipeline is written | Not yet scheduled |
| **T-12** | `nvidia/diar_streaming_sortformer_4spk-v2` license is **DISPUTED** between two readings (CC-BY-4.0 versus NVIDIA Open Model License) | Determines whether diarization is commercially clean. No exposure today: the corpus has no audio and the capability is deferred | Recorded in license-matrix section 4a with the `curl` that settles it | 5 min if revived |

---

## 10. Corrections to the license matrix that this file records

Building this file from the manifests rather than from the analysis surfaced two places where
[docs/license-matrix.md](docs/license-matrix.md) is now out of date. They are recorded here rather
than silently reconciled.

1. **License matrix section 3.1 and section 5 state that `nvidia/Nemotron-3-Ultra-550b-a55b` has
   "no role in Exulanica" and that its exposure is "currently zero".** The model manifest declares it
   as the `reasoning_hard` primary. Nothing routes there by default, so the exposure is small, but it
   is not zero. See item T-2.
2. **The license matrix does not cover `psycopg`**, an LGPL-3.0-only dependency reachable through the
   `postgres` optional extra and required to run the database migration. See item T-6.

---

Last built: **2026-08-28**. Rebuild this file whenever a dependency manifest or the model manifest
changes, and re-check section 9 before submission.

## Scene Gaussian training and compression (2026-09-05)

The optional `deploy/gsplat` runtime uses `nerfstudio-project/gsplat` v1.5.3 at commit
`937e29912570c372bed6747a5c9bf85fed877bae` under Apache-2.0. The image retains the upstream checkout,
including its LICENSE and third-party notices, at `/opt/gsplat`. Exulanica's independent training
loop uses the public rasterization, MCMC strategy, and PLY export APIs. It does not include or use
the restricted INRIA `gaussian-splatting` / `diff-gaussian-rasterization` implementation.
Source: <https://github.com/nerfstudio-project/gsplat/tree/937e29912570c372bed6747a5c9bf85fed877bae>.

The separate pinned CPU delivery converter is `@playcanvas/splat-transform` 3.3.3 (MIT), installed
through `deploy/gsplat/compressor/package-lock.json`; npm preserves the package's license files.
Source: <https://github.com/playcanvas/splat-transform/tree/d092ae94e6e1d5161990ce5ca960f659ea9faf5f>.
Its generated SOG container records the converter version. Other runtime dependencies retain their
respective distributions and licenses in the image; the runtime receipt records their versions.

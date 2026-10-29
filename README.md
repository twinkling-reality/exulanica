<p align="center">
  <img src="assets/brand/exulanica/exulanica-symbol.svg" width="88" alt="Exulanica">
</p>

<h1 align="center">Exulanica</h1>

<p align="center"><strong>Worlds for AI Agents. The open world engine for AI.</strong></p>

<p align="center">
  <a href="https://exulanica.com">Live World Runtime</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="docs/product-direction.md">Product Direction</a> ·
  <a href="docs/architecture-overview.md">Architecture</a> ·
  <a href="#getting-started">Getting Started</a>
</p>

<p align="center">
  <a href="https://github.com/twinkling-reality/exulanica/actions/workflows/check.yml"><img src="https://github.com/twinkling-reality/exulanica/actions/workflows/check.yml/badge.svg?branch=main" alt="Checks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-4c715d" alt="License: Apache 2.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11-3776ab" alt="Python 3.11"></a>
  <a href="web/package.json"><img src="https://img.shields.io/badge/Node.js-22%2B-5f7846" alt="Node.js 22 or newer"></a>
</p>

Exulanica is the **open world engine for AI**: a causal 3D world runtime where open models,
external agents, and humans co-habit the same persistent, verifiable reality.

Exulanica provides the authoritative spatial and semantic state (`World <-> Data`) beneath a 3D
world while heterogeneous AI minds, including frontier open models (`Nemotron`, `Qwen`,
`DeepSeek`), local on-device models, and external Python/MCP agents, live alongside human
inhabitants under shared rules, cross between worlds with cryptographic translation manifests,
and generate engine-verified trajectories for model distillation.

<p align="center">
  <img src="assets/brand/exulanica/readme-worlds-for-ai-agents.svg" width="100%" alt="Exulanica runtime architecture: co-habiting open models, local models, external agents, and human inhabitants interacting through a five-stage deterministic causal boundary over authoritative symbolic and spatial world state.">
</p>

## Why Exulanica exists: four structural fault lines

Generative world models, 3D spatial engines, and open language models sit in disconnected silos,
leaving four structural gaps across AI research and deployment:

| Fault line | What the research and market show | Why existing systems fail |
| --- | --- | --- |
| **1. Pixel world models vs. persistent reality** | Generative world platforms ([Google DeepMind Genie 3](https://deepmind.google/discover/blog/genie-3-a-new-frontier-for-world-models/), [NVIDIA Cosmos](https://www.nvidia.com/en-us/ai/cosmos/), and [World Labs, acquired by AMD for $8.2B in Sept 2026](https://techcrunch.com/2026/09/28/amd-will-acquire-fei-fei-lis-world-labs-for-8-2-billion/)) demonstrate strong demand for AI-generated worlds. | Video world models predict next-frame RGB pixels from controller inputs. They have **zero symbolic state, zero persistent object identity, zero multi-agent causality, and zero inspectability**, collapsing over long horizons or when multiple agents interact. Conversely, traditional 3D engines synchronize physics for human players but have **zero native AI cognition, zero causal provenance, and no cross-world entity translation**. |
| **2. The open-model discovery bottleneck** | Hugging Face hosts **2.96 million** public model repositories, yet **85.6% have fewer than 200 lifetime downloads**, and **1.5%** of repositories account for **99.2%** of all downloads ([Hugging Face, *State of Open Models: Summer 2026*](https://huggingface.co/blog/state-of-open-models-summer-2026)). | Static leaderboards and single-turn chat boxes cannot show how open models (`Nemotron`, `Qwen`, `DeepSeek`, `Llama`) behave over time, navigate spatial and social constraints, interact with other models, or trade off latency and cost inside living environments. |
| **3. The AI opacity, trust, and literacy gap** | **50% of U.S. adults** are more concerned than excited about AI in daily life (up from 37% in 2021), **~60%** want more control over how AI acts, and **53%** cannot reliably distinguish AI behavior from human behavior ([Pew Research Center, 2025](https://www.pewresearch.org/science/2025/09/17/how-americans-view-ai-and-its-impact-on-people-and-society/)). Meanwhile, **over 80% of U.S. students** and **88% to 96% of European teens** use AI tools while only **6% of teachers** report clear school policies ([Stanford HAI *2026 AI Index*](https://hai.stanford.edu/ai-index/2026-ai-index-report)). | As the [OECD and European Commission (*AI Literacy Framework*, 2026)](https://doi.org/10.1787/65cd27d4-en) and [PISA 2029](https://www.oecd.org/en/about/projects/pisa-2029-media-and-artificial-intelligence-literacy.html) state: *"AI literacy is different from AI tool use."* People and engineers cannot build intuition or trust when model decisions happen inside an uninspectable black box. |
| **4. Ungrounded synthetic training data** | Post-training and distillation increasingly depend on synthetic agent trajectories, yet text-to-text synthetic loops degrade without an authoritative environment verifier. | Single-agent DOM or terminal benchmarks lack persistent multi-agent worlds, spatial grounding, and deterministic refusal signals that turn model proposals into verified supervised and preference-learning datasets. |

## Core primitives of the Exulanica runtime

Exulanica bridges these silos through six architectural primitives defined in the repository's
[living contracts](docs/README.md):

### 1. Verifiable spatial and semantic reality (`World <-> Data`)

A world in Exulanica is content-addressed semantic state (`state_sha256`) with integer millimetre
coordinates (`x_mm`, `y_mm`, `z_mm`), typed catalog records (`exulanica.world-kind/v2`,
`exulanica.thing-kind/v1`), and explicit provenance ([world state architecture](docs/world-memory-model.md)).
- **Live semantic inspection:** Toggling the `World <-> Data` view in the workspace dissolves the
  60fps PlayCanvas 3D scene into semantic point clouds, bounding volumes, and live per-being model
  telemetry (active model, latency in `ms`, disposition `Applied` / `Not Applied · Stale` /
  `Routine Fallback`, and spend).
- **Structure-locked neural appearance:** Rather than using video world models as hallucinating
  state stores, Exulanica uses open image and video models on Nebius AI Cloud GPUs strictly as
  neural appearance passes conditioned on exact `depth`, `normal`, `identity`, and `edges` buffers
  ([generated appearance](docs/generated-appearance.md)).

### 2. Multi-model and human-AI co-habitation

Heterogeneous minds inhabit the same persistent world simultaneously:
- **Hosted frontier open models:** Assign `Nemotron 3 Super 120B`, `Nemotron 3 Ultra 550B`,
  `Nemotron 3 Nano 30B`, `Qwen3 235B Instruct`, or `DeepSeek V4 Flash` via Nebius Token Factory
  ([model manifest](exulanica/models/models.manifest.json)), with worst-case cost ceilings enforced
  before any call runs ([where models run and who pays](docs/product-direction.md#where-models-run-and-who-pays)).
- **Local models on user hardware:** Run local models on the owner's machine for free with zero
  external network egress.
- **Outside agents:** Connect custom Python or MCP agents (such as agents built with NVIDIA NeMo
  Agent Toolkit via `bridges/agents`) to inhabit and decide for townspeople
  ([outside agents](docs/capabilities/outside-agents.md)).
- **Direct human co-habitation:** Step directly into any inhabitant to walk, converse, place
  objects, and interact alongside AI-driven inhabitants under the same world rules and receipt
  schema (`exulanica/world/society_play.py`).

### 3. Five-stage deterministic causal boundary

Models never mutate world state directly. A model is a proposer; the world engine is the authority
([decision roles contract](docs/decision-roles-contract.md)). Every turn crosses a verifiable
five-stage execution pipeline inspectable in the live **`Decision`** view:

```text
1. World Snapshot -> 2. Context -> 3. Model Inference -> 4. Engine Check -> 5. Outcome
```

1. **World Snapshot:** Pins the canonical `state_sha256`, world clock, and 8-metre spatial hearing
   and reachability graph.
2. **Context:** Assembles bounded, privacy-screened observations (`Personality`, `Location & Time`,
   `Status`, `Nearby`, `Heard`, `Remembers`) and seed-shuffled legal affordances.
3. **Model Inference:** Dispatches via forced tool call or strict JSON schema within a pre-reserved
   spending envelope (`exulanica/models/client.py`).
4. **Engine Check:** Validates enum membership, speech rules, saved-name scrubbing, and spatial
   availability at commit time.
5. **Outcome:** Commits the state transition and seals an immutable `exulanica.society-decision/v2`
   receipt so runs replay deterministically without re-calling the model.

### 4. Cross-world interoperability (`The Door`)

[The Door contract](docs/door-contract.md) (`exulanica/door/`) is an open protocol for moving
agents, characters, and inventories across independent worlds and external games without hardcoded
monolithic binaries:
- **Scoped capability grants:** Time-bounded, revocable admission specifying visitor limits, speech
  rights, item carry permissions, and mind authority.
- **Cryptographic Translation Manifest (`exulanica.translation-manifest/v2`):** Every attribute and
  carried item of a crossing entity is deterministically accounted for as `exact` (carried unchanged),
  `approximated` (adapted to the host world's catalog with an explicit reason), `dropped` (refused by
  host world physics/rules), or `opaque` (preserved for return departure).

### 5. Grounded trajectories, counterfactuals, and local model distillation

Because every action is validated by the world engine, every world run produces grounded
post-training data (`exulanica/world/trajectories.py`, [world memory package](docs/world-memory-package.md)):
- **Counterfactual branching (`Compared with <Model>`):** Fork any moment in History or run paired
  multi-seed comparisons ([society experiments](docs/society-experiments.md)) to measure how two
  models act from the exact same starting state, without ranking models on a static leaderboard.
- **Trajectory export and GitHub sync:** Exports privacy-screened `exulanica.world-trajectory/v1`
  archives containing supervised tool-calling traces (`sft.jsonl`) and natural preference pairs
  (`dpo.jsonl`) from engine refusals and counterfactual branches, formatted for NVIDIA NeMo Gym,
  OpenEnv, and TRL to distill `120B-550B` frontier teachers into fast `1B-8B` local student minds.

### 6. Real-time 20 Hz multi-agent scale

Alongside the inspectable 1-minute society loop, `exulanica/world/realtime_runtime.py` implements an
authoritative **20 Hz (`50 ms`) Spatial Room & 3-Tier Hierarchical Mind Runtime**:
- **Tier 0 (`20 Hz`):** Swept collision avoidance, spatial-hash AOI filtering, and path following.
- **Tier 1 (`Instant`):** Sub-millisecond reactive local policy continuation.
- **Tier 2 (`Async`):** Non-blocking open-model deliberation with `ContinuationValidator` commit
  checks, benchmarked at **`0.225 ms/tick` median across 256 concurrent beings** over FastAPI
  WebSockets and 60fps PlayCanvas interpolation.

## The world experience

The workspace connects six capabilities; [product direction](docs/product-direction.md) sets their
delivery order and acceptance gates:

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Models run your world</h3>
      Open models decide what the people in your world do: where to go, whether to wait, stand a while, or stop to talk. The engine validates every decision and stores it, so a run replays exactly. The world's owner chooses the model for each person or group of people; with no choice, their routine decides.
      <p><a href="docs/capabilities/simulation.md">People and models</a> · <a href="docs/decision-roles-contract.md">Decision roles</a> · <a href="docs/model-and-service-selection.md">Model selection</a></p>
    </td>
    <td width="50%" valign="top">
      <h3>Swap a model, see the difference</h3>
      Run the same saved world's hour under two models and compare what happened. A comparison scores how the people fared against a control run and shows both runs side by side in the application, where the world's owner starts it within a spending bound they state and watches its runs finish.
      <p><a href="docs/society-experiments.md">Controlled comparisons</a> · <a href="docs/product-direction.md#first-milestone">First milestone</a></p>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Build your world</h3>
      Generate a town from a sentence with web references, place pieces from the catalogs, make a world from photographs, or import content with its origin labelled. Edits persist as versions. A starter and a world made from photographs each start with eight people. A generated town's people come from its homes.
      <p><a href="docs/capabilities/world-creation.md">World creation</a> · <a href="docs/capabilities/scene-reconstruction.md">Reconstruction</a></p>
    </td>
    <td valign="top">
      <h3>Give the world life</h3>
      The people in your world follow routines, walk to the places they use, and respond to what you change. Small birds fly and perch on the trees that host them, on a clock everyone watching shares. Pause and playback speed are clock controls. The <a href="docs/world-clock-contract.md">world clock contract</a> owns the rest of the clock.
      <p><a href="docs/synthetic-society-contract.md">Society contract</a> · <a href="docs/movement-modules-contract.md">Movement modules</a> · <a href="docs/product-direction.md#configurable-world-rules">World rules</a></p>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Inspect the data</h3>
      Inspect a subject's geometry, properties, relationships, and origin, and examine the five-stage causal execution pipeline behind any decision. Query, edit, and extract supported world content as reusable data while keeping its identity across views.
      <p><a href="docs/atlas-reconstruction-inspection.md">Representation and inspection</a> · <a href="docs/capabilities/world-api.md">World API</a></p>
    </td>
    <td valign="top">
      <h3>The Companion and your photographs</h3>
      The Companion is an AI partner that helps you explore, create, and understand what happens, and your own photographs can become places and references in a world, under your rights and consent.
      <p><a href="docs/capabilities/companion.md">Companion</a> · <a href="docs/saved-world-entry.md#reference-photographs">Reference photographs</a></p>
    </td>
  </tr>
</table>

## Capability boundaries

The repository supplies working components for this experience. Their contracts define the
supported operations; the full product direction is broader than those components.

| Area | Implemented foundation | Delivery target |
| --- | --- | --- |
| Models in the world | Open models in hosted roles through one policy boundary; a model chosen for a person or a group, or for a generated town's junction signal, validated, stored, and replayed; outside Python/MCP agents via The Door; comparisons of models started from the application within a stated bound, scored against a control and shown side by side | Roles beyond a person and a junction signal, and automated in-app LoRA distillation jobs |
| Persistent worlds | Generated towns and creatures from words with Tavily web references, authored starter worlds, worlds made from reviewed photographs, saved versions, object edits and undo, appearance state, reference photographs | A complete personal-media-to-editable-world journey and richer procedural interiors |
| Inspectable data | Live `World <-> Data` point-cloud and bounding-box inspection, five-stage decision pipeline receipts, structured records, and source references | Complete reusable object extraction and consistent semantic coverage across sources |
| Companion | Grounded answers, including about a world's simulated people; conversation memory kept across reloads; reviewed appearance proposals | Shared activity, durable personal continuity, and broader creation tools |
| Life and experiments | A starter or photograph world begins with eight people. A generated town's people come from its homes and are admitted by minute cost; real-time 20 Hz spatial runtime supports up to 256 concurrent beings. Small birds and a generated town's vehicles share a clock. Paired experiments record specific interventions | Richer social behavior, configurable calendar and physics, and validated model-driven scenarios |
| Developer access | Authenticated world APIs, an independent Python client, Door bridges (`exulanica.translation-manifest/v2`), `exulanica.world-trajectory/v1` SFT/DPO exports, and signed world packages synced to GitHub | General model adapters and runnable cross-application interchange |

The [experiment contract](docs/society-experiments.md) specifies paired society runs with supported
interventions. Synthetic outcomes do not establish predictions about real people or real-world
systems.

## Architecture

A persistent world connects identity, spatial state, time, edits, and recorded events. The browser,
Companion, model adapters, and external clients work through declared interfaces. Observations,
authored content, and simulation results retain distinct origins and meanings.

| Module | Responsibility | Reference |
| --- | --- | --- |
| World state | Identity, epistemic planes, and representations; versions and edit history | [World state architecture](docs/world-memory-model.md) · [World objects](docs/world-objects-contract.md) |
| Creation and representation | World and creature generation, reconstruction, authored objects, appearance, and browser rendering | [World composition](docs/world-composition-contract.md) · [Generated appearance](docs/generated-appearance.md) |
| Simulation | Societies, the engines and routines that run them, 20 Hz real-time spatial rooms, movement modules, and replayable outcomes | [Society contract](docs/synthetic-society-contract.md) · [Movement modules](docs/movement-modules-contract.md) |
| Models deciding | Decision roles as data, one validated decision path, outside agents via The Door, and comparisons of models | [Decision roles](docs/decision-roles-contract.md) · [The Door](docs/door-contract.md) · [Comparisons](docs/society-experiments.md#comparisons-of-models) |
| Model integration | Replaceable reconstruction, generation, and decision providers behind one policy boundary, with validated outputs | [Model selection](docs/model-and-service-selection.md) · [Model manifest](exulanica/models/models.manifest.json) |
| API, trajectories, and portability | Authorized reads and edits; `exulanica.world-trajectory/v1` SFT/DPO exports; signed, capability-declared snapshots (`World Memory Package`) | [Developer client](docs/capabilities/developer-client.md) · [World package](docs/world-memory-package.md) |

Python and PostgreSQL carry the backend; TypeScript and PlayCanvas carry the browser experience.
The configured Companion answer path uses **NVIDIA Nemotron through Nebius Token Factory** to
compose answers from validated evidence. The open models a world's owner can choose for a person
are those the manifest records as verified to answer a choice. The
[model and service selection](docs/model-and-service-selection.md) describes the implemented
callers, evaluation evidence, and hosting boundaries.

## Getting started

### Browser preview

Requires Git, Node.js 22 or newer, and pnpm 10.7.1.

```bash
git clone https://github.com/twinkling-reality/exulanica.git
cd exulanica/web
pnpm install --frozen-lockfile
pnpm app
```

Open [http://localhost:5173/?preview=1](http://localhost:5173/?preview=1), or the address Vite
prints if that port is occupied, with `?preview=1` appended. This development preview uses fixture
data. It does not create an authenticated saved world or demonstrate media reconstruction, and
choosing or comparing the models that decide for a world's people needs the persistent application.

### Persistent application

The authenticated application uses a separate API, PostgreSQL, local asset storage, and configured
accounts. Backend development requires Python 3.11 and [uv](https://docs.astral.sh/uv/);
reconstruction and processing use additional dependencies and workers.

Follow [development setup](docs/development-setup.md) for installation and services, and its
[people and models section](docs/development-setup.md#seeing-people-and-models-locally) to see
models decide in a local world; [account configuration](docs/deployment.md) for deployment
requirements; and [the Python client guide](docs/capabilities/developer-client.md) to build against
a configured API.

## Documentation

| Start here | Go deeper |
| --- | --- |
| [Product direction and delivery gates](docs/product-direction.md) | [Architecture overview](docs/architecture-overview.md) |
| [People and models in a world](docs/capabilities/simulation.md) | [Society contract](docs/synthetic-society-contract.md) · [Decision roles](docs/decision-roles-contract.md) |
| [Outside agents and The Door](docs/capabilities/outside-agents.md) | [The Door contract](docs/door-contract.md) · [Things contract](docs/things-contract.md) |
| [Society experiments and comparisons](docs/society-experiments.md) | [Movement modules](docs/movement-modules-contract.md) |
| [Saved worlds](docs/saved-world-entry.md) | [Authored objects and behaviors](docs/world-objects-contract.md) · [World composition](docs/world-composition-contract.md) |
| [World API](docs/capabilities/world-api.md) | [Independent Python client](docs/capabilities/developer-client.md) · [World Memory Package](docs/world-memory-package.md) |
| [Documentation hub](docs/README.md) | [Complete document catalog](docs/all-documents.md) |

For bugs and focused proposals, [open an issue](https://github.com/twinkling-reality/exulanica/issues)
with the relevant world operation, expected result, and reproduction steps. Use the capability
contracts and [development guide](docs/development-setup.md) when contributing a change.

## License

[Apache-2.0](LICENSE). Model weights, datasets, and third-party assets have their own terms;
see [third-party notices](THIRD_PARTY_NOTICES.md).

KayKit Adventurers 2.0 and KayKit Character Animations 1.1 by Kay Lousberg are used under CC0
([asset credits](assets/things/kaykit-adventurers-2)). A Luanti player's look is built at deployment
from the operator's copy of Minetest Game's default player picture (character.png by Jordach,
CC BY-SA 3.0); that picture is not committed.

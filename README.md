<p align="center">
  <img src="assets/brand/exulanica/exulanica-symbol.svg" width="88" alt="Exulanica">
</p>

<h1 align="center">Exulanica</h1>

<p align="center"><strong>A persistent, programmable personal world.</strong><br>Create a world. Shape how it works. Build something with it.</p>

<p align="center">
  <a href="https://exulanica.com">Website</a> ·
  <a href="docs/README.md">Documentation</a> ·
  <a href="docs/product-direction.md">Roadmap</a> ·
  <a href="#getting-started">Getting started</a>
</p>

<p align="center">
  <a href="https://github.com/twinkling-reality/exulanica/actions/workflows/check.yml"><img src="https://github.com/twinkling-reality/exulanica/actions/workflows/check.yml/badge.svg?branch=main" alt="Checks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-4c715d" alt="License: Apache 2.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11-3776ab" alt="Python 3.11"></a>
  <a href="web/package.json"><img src="https://img.shields.io/badge/Node.js-22%2B-5f7846" alt="Node.js 22 or newer"></a>
</p>

Exulanica is an open-source platform for persistent, customizable digital worlds. Its goal is a world
you can create from imagination, your own media or permitted imports, then inhabit and reshape. Design a dream
landscape, a familiar place or a fantasy city with your own aesthetic, rules and sense of time.
Populate it with a synthetic society whose activities and interactions become part of its history.

Underneath the experience is structured world data: identifiable places, objects and inhabitants,
their geometry, properties, relationships and recorded changes. The aim is to make that world
inspectable, queryable, editable and reusable, and to let open or custom models perform tasks
within it. The same foundation supports personal creation, applications, simulations and experiments.

<p align="center">
  <img src="assets/brand/exulanica/readme-world-model.svg" width="100%" alt="Product direction: personal media, imagination and permitted imports feed a persistent, customizable world with identity, space, time, rules and history. Explore and build, inspect and edit, simulate inhabitants, and apply models inside the world.">
  <br><sub>Product direction. The capability boundaries below distinguish implemented foundations from delivery targets.</sub>
</p>

## The world

The [product roadmap](docs/product-direction.md) defines six connected parts of the experience:

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Create and explore</h3>
      Build from imagination, personal media or permitted imports. Design your own architecture, landscape and aesthetic, then keep your edits and return to the same world.
      <p><a href="docs/capabilities/world-creation.md">World creation</a> · <a href="docs/capabilities/scene-reconstruction.md">Reconstruction</a></p>
    </td>
    <td width="50%" valign="top">
      <h3>Inspect the data</h3>
      Inspect a subject's geometry, properties, relationships and origin. Query, edit and extract supported world content as reusable data while keeping its identity across views.
      <p><a href="docs/atlas-reconstruction-inspection.md">Representation and inspection</a></p>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Create with your Companion</h3>
      Describe what you want to find or change. The Companion is your AI partner within the world, helping you explore, create and understand what happens. Its tools prepare supported changes for review alongside direct editing controls.
      <p><a href="docs/capabilities/companion.md">Companion</a></p>
    </td>
    <td valign="top">
      <h3>Give the world life</h3>
      Populate your world with synthetic inhabitants, routines and interactions. Your designs can change their opportunities and activities; physical or fictional rules define how the world and its time behave.
      <p><a href="docs/capabilities/simulation.md">Simulation</a> · <a href="docs/product-direction.md#configurable-world-rules">World rules</a></p>
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Shape behavior and scenarios</h3>
      Configure supported rules and interactions, connect decision models and explore what happens. A controlled comparison is one way to study a world alongside open-ended creation and simulation.
      <p><a href="docs/product-direction.md#worlds-as-project-foundations">Projects and scenarios</a> · <a href="docs/society-experiments.md">Controlled experiments</a></p>
    </td>
    <td valign="top">
      <h3>Put models to work inside the world</h3>
      Apply open models or your own models to particular world tasks: interpret scene observations, propose inhabitants' actions or evaluate a control policy. Build applications that use the resulting state and events.
      <p><a href="docs/capabilities/world-api.md">World API</a> · <a href="docs/product-direction.md#worlds-as-project-foundations">Project foundations</a></p>
    </td>
  </tr>
</table>

## Models inside the world

The model-integration goal is to give models defined jobs within a world. For example, a perception
model could interpret a scene's camera observations, a behavior model could propose an inhabitant's
actions, and a control model could operate a simulated vehicle in an environment with the required
physics and sensors. Multiple models can serve different roles in the same project.

These examples describe integration targets. Each adapter must declare its observations, permitted
actions, timing and resource limits. Its outputs pass the world's validation rules, and accepted
changes retain their identity and history. A model's availability alone does not supply a compatible
simulator, usable training data or a validated prediction.

## The world as data

The architectural goal is **structured, addressable world state**: meaningful subjects and changes
have identities, properties, relationships, spatial context and history that people and programs
can inspect and act on. Supported geometry and records can be selected, queried and reused through
declared interfaces, with their origin and permissions preserved.

Meshes, tessellated surfaces, point clouds and Gaussian splats are representations of that state.
They do not by themselves provide semantic labels, complete object extraction or physical behavior.
A render vertex need not be a permanent database entity; a selectable object or consequential
change needs a stable record. This foundation lets different renderers, models and applications
work with the same world. See the [world model architecture](docs/world-memory-model.md).

## Capability boundaries

The repository supplies working components for this experience. Their contracts define the
supported operations; the full product direction is broader than those components.

| Area | Implemented foundation | Delivery target |
| --- | --- | --- |
| Persistent worlds | Authored starter worlds, saved versions, object edits and undo, appearance state, reference photographs | A complete personal-media-to-editable-world journey |
| Inspectable data | Supported point and surface representations, subject selection, structured records and source references | Complete reusable object extraction and consistent semantic coverage across sources |
| Companion | Conversation, selection context and reviewed appearance proposals | Shared activity, durable personal continuity and broader creation tools |
| Life and experiments | Deterministic societies, bounded motion, recorded paired comparisons with specific interventions | Richer social behavior, customizable world rules and validated model-driven scenarios |
| Developer access | Authenticated world APIs, an independent Python client and signed partial world packages | General model adapters, dataset workflows and runnable interchange |

General model adapters, user-defined world rules and dataset generation are delivery targets.
The [experiment contract](docs/society-experiments.md) specifies one bounded application of the world:
paired society runs with supported interventions.
Synthetic outcomes do not establish predictions about real people or real-world systems.

## Architecture

A persistent world connects identity, spatial state, time, edits and recorded events. The browser,
Companion, model adapters and external clients work through declared interfaces. Observations,
authored content and simulation results retain distinct origins and meanings.

| Module | Responsibility | Reference |
| --- | --- | --- |
| World state | Versions, sources, identities and edit history | [World model architecture](docs/world-memory-model.md) |
| Creation and representation | Reconstruction, authored objects, appearance and browser rendering | [World composition](docs/world-composition-contract.md) |
| Simulation | Supported behaviors, inhabitants and replayable outcomes | [Society contract](docs/synthetic-society-contract.md) |
| Model integration | Replaceable reconstruction, generation and decision providers, with validated outputs | [Model selection](docs/product-direction.md#model-selection-and-compute-priorities) |
| API and portability | Authorized reads and edits; signed, capability-declared snapshots | [Developer client](docs/capabilities/developer-client.md) · [World package](docs/world-memory-package.md) |

Python and PostgreSQL carry the backend; TypeScript and PlayCanvas carry the browser experience.
The configured Companion answer path uses **NVIDIA Nemotron through Nebius Token Factory** to
compose answers from validated evidence. Other model roles support perception, retrieval and
reviewed proposals. The [model and service selection](docs/model-and-service-selection.md) describes
the implemented callers, evaluation evidence and hosting boundaries. This does not imply that the
whole application or its background workers are deployed on Nebius Serverless.

The world model is structured, versioned state with model integrations, not a single trained
general-purpose predictor. The portable format is named **World Memory Package** in its technical
contract; verifying a package does not by itself load a runnable world in another application.

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
data. It does not create an authenticated personal world or demonstrate media reconstruction.

### Persistent application

The authenticated application uses a separate API, PostgreSQL, local asset storage and configured
accounts. Backend development requires Python 3.11 and [uv](https://docs.astral.sh/uv/);
reconstruction and processing use additional dependencies and workers.

Follow [development setup](docs/development-setup.md) for installation and services,
[account configuration](docs/deployment.md) for deployment requirements, and
[the Python client guide](docs/capabilities/developer-client.md) to build against a configured API.

## Documentation

| Start here | Go deeper |
| --- | --- |
| [Product direction and delivery gates](docs/product-direction.md) | [World composition](docs/world-composition-contract.md) |
| [Saved worlds](docs/saved-world-entry.md) | [Authored objects and behaviors](docs/world-objects-contract.md) |
| [World API](docs/capabilities/world-api.md) | [Independent Python client](docs/capabilities/developer-client.md) |
| [Society experiments](docs/society-experiments.md) | [Simulation tooling and adoption gates](docs/product-direction.md#modular-simulation-and-scientific-tooling) |
| [Documentation hub](docs/README.md) | [Complete document catalog](docs/all-documents.md) |

For bugs and focused proposals, [open an issue](https://github.com/twinkling-reality/exulanica/issues)
with the relevant world operation, expected result and reproduction steps. Use the capability
contracts and [development guide](docs/development-setup.md) when contributing a change.

## License

[Apache-2.0](LICENSE). Model weights, datasets and third-party assets have their own terms;
see [third-party notices](THIRD_PARTY_NOTICES.md).

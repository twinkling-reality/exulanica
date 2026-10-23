# Exulanica documentation

Exulanica: Worlds for AI Agents. This hub routes a task to the document that owns it.
[Product direction](product-direction.md) owns the public name, scope and delivery order.
Exulanica does not generate a world's appearance with a learned model. Comparing models on one
saved world is one capability. The
[people and models guide](capabilities/simulation.md) explains it. The
[root README](../README.md) introduces the product.

## Start here

| I want to… | Read |
| --- | --- |
| Understand the goal and delivery order | [Product direction](product-direction.md) |
| See how people and models run a world, and how two models are compared | [People and models in a world](capabilities/simulation.md) |
| Understand how the system fits together | [Architecture overview](architecture-overview.md) |
| Run Exulanica on my own computer, with open models deciding | [Running your own install](development-setup.md#running-your-own-install) |
| Run or change the application | [Development setup](development-setup.md), then the contract for the affected behavior |
| Keep a world's database on my own computer | [Local database](local-database.md) |
| Build something using a world | [World API](capabilities/world-api.md) and [Python client](capabilities/developer-client.md) |
| Bring my own AI agent to live in a world | [Outside AI agents](capabilities/outside-agents.md) |
| Write, update or consolidate documentation | [Documentation standard](documentation-standard.md) |

## Capability guides

[People and models](capabilities/simulation.md) ·
[World creation](capabilities/world-creation.md) ·
[Scene reconstruction](capabilities/scene-reconstruction.md) ·
[Companion](capabilities/companion.md) ·
[World API](capabilities/world-api.md) ·
[Developer client](capabilities/developer-client.md) ·
[Outside AI agents](capabilities/outside-agents.md)

[People and models](capabilities/simulation.md) explains how a world's people live, how its
owner hands supported roles to open models, and how two models are compared. The
[decision roles contract](decision-roles-contract.md) and the
[society contract](synthetic-society-contract.md) own validation, storage, and replay. The
Companion, photographs, and reconstruction are other ways to build and use a world. Their guides
separate supported behavior from later requirements.

## Contracts

Find the owner by subject in the [catalog](all-documents.md). Each document has one home and states
what it owns. Read the relevant owner rather than loading every document as context.

| Subject | Questions it answers |
| --- | --- |
| [Product and architecture](all-documents.md#orientation) | What is the product, how is it built, and how do contributors work? |
| [Capability guides](all-documents.md#capabilities) | What can a person or another program do with a world, and where does each feature stop? |
| [Agents and simulation](all-documents.md#simulation) | How do a world's people live, how do models decide for them, how are runs replayed and compared, and how do movement and traffic work? |
| [World state and creation](all-documents.md#world-state) | What persists, how do edits work, and what can a package carry? |
| [Generated and admitted environments](all-documents.md#environments) | How are environments generated or admitted from outside sources, and how are their streets, tiles, textures and lettering made? |
| [Interaction and Companion](all-documents.md#interaction) | How do controls, proposals, selection and representations behave? |
| [Photographs, reconstruction and evidence](all-documents.md#perception) | What may be processed, reconstructed, cited and served? |
| [Runtime, security and model selection](all-documents.md#operations) | How are services configured, protected and connected to models? |
| [Verification and evidence](all-documents.md#verification) | What constitutes a valid measurement or acceptance result? |
| [Historical context](all-documents.md#history) | Which earlier plans and recorded findings exist, and which living documents succeeded them? |

The [decision catalog](all-documents.md#decisions) lists the decision records.

## Capability boundaries

Product direction defines requirements. Living contracts define supported behavior and material
limits. Code and scoped execution evidence establish implementation facts. A fixture or local test
does not prove deployment, visual quality or a complete user journey. A signed package does not
prove another application can execute every behavior.

Historical findings apply to their recorded inputs, versions and conditions. They do not override
an unrelated contract or a later measurement. Investigate discrepancies against source rather than
choosing whichever document sounds most confident.

## Decision records

The [decision catalog](all-documents.md#decisions) preserves choices, alternatives and rationale.
[Historical context](all-documents.md#history) points to research and earlier plans. Neither is a
second product specification. Immutable execution records and their bound artifacts remain under
`docs/evaluation/`; publish a campaign only when it belongs in the public evidence set.

## Document filing

The [documentation standard](documentation-standard.md) owns the quality rubric, contribution
workflow and file lifecycle. [navigation.json](navigation.json) owns the public subject map, and
[scripts/generate_docs_index.py](../scripts/generate_docs_index.py) generates the catalog.

Update an existing owner before adding a document. Working notes and handoffs belong in ignored
`.exulanica/briefs/`, never in public contracts. Retain paths named by immutable records and leave
bound artifacts unchanged. The structure checks and [link checks](../tests/test_documentation_links.py)
enforce mechanical properties; factual accuracy still requires review of the affected source.

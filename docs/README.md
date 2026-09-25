# Exulanica documentation

Exulanica: Worlds for AI Agents. A person builds a world, and open models run what happens inside
it, each doing what it is good at; the person can swap one model for another and see the
difference. World models generate how a world looks; Exulanica is the world AI models live in. The
[root README](../README.md) introduces the product.

## Start here

| I want to… | Read |
| --- | --- |
| Understand the goal and delivery order | [Product direction](product-direction.md) |
| Understand how the system fits together | [Architecture overview](architecture-overview.md) |
| Run or change the application | [Development setup](development-setup.md), then the contract for the affected behavior |
| Build something using a world | [World API](capabilities/world-api.md) and [Python client](capabilities/developer-client.md) |
| Write, update or consolidate documentation | [Documentation standard](documentation-standard.md) |

## Capability guides

[World creation](capabilities/world-creation.md) ·
[Scene reconstruction](capabilities/scene-reconstruction.md) ·
[Companion](capabilities/companion.md) ·
[Simulation](capabilities/simulation.md) ·
[World API](capabilities/world-api.md) ·
[Developer client](capabilities/developer-client.md)

**Models inside the world** are the product's core: the [simulation guide](capabilities/simulation.md)
and the [society contract](synthetic-society-contract.md) describe how the people in a world decide
and how model decisions are validated, stored and replayed. The **Companion**, personal photographs
and reconstruction from photographs are features and ways to build a world; the Companion's guide
separates its role from the implemented tools.

## Contracts

Find the owner by subject in the [catalog](all-documents.md). Each document has one home and states
what it owns. Read the relevant owner rather than loading every document as context.

| Subject | Questions it answers |
| --- | --- |
| [Product and architecture](all-documents.md#orientation) | What is the product, how is it built, and how do contributors work? |
| [World state and creation](all-documents.md#world-state) | What persists, how do edits work, and what can a package carry? |
| [Sources, perception and evidence](all-documents.md#perception) | What may be processed, reconstructed, cited and served? |
| [Interaction and Companion](all-documents.md#interaction) | How do controls, proposals, selection and representations behave? |
| [Simulation and generated environments](all-documents.md#simulation) | How are environments generated and inhabitants, traffic and appearance represented? |
| [Runtime, security and model selection](all-documents.md#operations) | How are services configured, protected and connected to models? |
| [Verification and evidence](all-documents.md#verification) | What constitutes a valid measurement or acceptance result? |

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

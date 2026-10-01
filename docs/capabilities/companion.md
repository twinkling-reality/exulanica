# Companion

The Companion is an AI partner inside a world. It answers questions about the world from cited
sources, drafts changes the person reviews, and helps a person explore and create. It is one
feature of a world; the product is a world that open models run
([product direction](../product-direction.md)). Direct controls reach the same supported
operations, so using a world never requires a conversation. This guide separates what the
Companion does from the experience it is meant to become.

## What it does

| Tool | What the person gets |
| --- | --- |
| Grounded answers | An answer composed from the evidence the person's rights allow, with its sources cited. A question it cannot answer from evidence gets an abstention, not a guess. |
| Answers about a world's people | Who somebody is, what they are doing, why they are there or what has happened among them, read from the society's state and recorded events, cited and marked as simulation, never as memory. |
| Appearance proposals | A reviewed change to the world's appearance, shown as a preview in Customize for the person to apply or discard. The Companion speaks about a proposal only once that preview has been shown or refused. A proposal is drawn from the world's evidence, or, when the caller asks for it, is a design choice that cites none. |
| World actions | A plan of the exact requests that place, move or remove an object, take back an edit, set out an arrangement, play or pause the world's time or change its speed, move it on up to ten simulated minutes, or bring people into a world with none, each with the authority's own preview where it has one. The person confirms each step, or once for a chain of minutes, and the client sends it to the same route a direct control uses; the Companion reports the receipts the authorities recorded, never an effect no record shows. |
| Conversation memory | What was asked, what was answered and what the person corrected, kept across reloads. The person can read it back, correct it and delete it. |
| Project context | What a person keeps about their work in a world: goals, preferences, open questions, tasks, decisions naming accepted edits and simulated events they want to return to. Any client can read, correct, share and delete it without a model, and the Companion can be given a bounded context assembled from it. A suggestion the Companion draws is kept only once the person accepts it. |

The rules for each are in [Companion questions, memory and proposals](../companion-question.md),
and the appearance authority a proposal is applied through is in
[world version authorities](../world-version-authorities.md).

An NVIDIA Nemotron model on Nebius Token Factory composes its answers, through the one hosted policy
boundary that applies the egress allowlist, the budget and the person's rights. A model's output is
an answer or a proposal, never a direct write to the world, an identity or a permission.

## What it is meant to become

A recognizable personality, awareness of what the person is doing, shared history and taking part
in the world's activities are design requirements, not implemented capabilities. Appearance,
initiative and the limits of what it retains need concrete interaction design. Familiarity never
authorizes an edit or an identity decision, and creation help uses supported, reviewable editing
operations only.

See [interaction design](../interaction-model.md#4-the-companion) for the Companion's encounter in the
world, and the [frontend integration boundary](../atlas-world-customization-contract.md#7-frontend-integration-boundary)
for how the browser reviews what it proposes.

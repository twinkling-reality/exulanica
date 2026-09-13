# Simulation runtime

Give created objects movement, interactions, and rules for responding to the world.

## Scope

The initial runtime milestone is one supported behavior with trigger, stop, and reset controls.
Later milestones address physics, collisions, dynamic objects, and more complex behavior.
Bounded object motion and a deterministic synthetic society exist; the renderer and generation
receipts do not implement a general simulation system.

Behavior definitions belong to reviewed runtime capabilities. Saved world state references those
capabilities and their parameters. The API changes supported state; the runtime executes it.
A package signature does not prove that a runtime supports a behavior.

Simulation state is a separate epistemic plane from memory evidence. Synthetic identities, goals,
actions and outcomes may share places and objects with a memory without becoming claims about what
happened there. Rendering may interpolate snapshots but may not invent canonical actions or
positions.

The current deterministic society and bounded object motion do not establish a learned predictive
world model. That claim requires action-conditioned prediction evaluated against held-out future
observations, calibrated uncertainty, increasing-horizon error measurements and improvement over
deterministic and no-memory baselines. See
[the world-memory research program](../world-memory-model.md#7-dynamics-and-the-claim-to-prediction).
The implemented population's exact state, event, selection, rendering, training and package
boundaries are in the [synthetic society contract](../synthetic-society-contract.md).

See [delivery milestones](../product-direction.md#subsequent-milestones) and
[package compatibility](../product-direction.md#package-and-api-boundaries).

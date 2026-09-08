# Simulation runtime

Give created objects movement, interactions, and rules for responding to the world.

## Scope

The initial runtime milestone is one supported behavior with trigger, stop, and reset controls.
Later milestones address physics, collisions, dynamic objects, and more complex behavior.
Simulation is planned; the existing renderer and generation receipts do not implement a general
simulation system.

Behavior definitions belong to reviewed runtime capabilities. Saved world state references those
capabilities and their parameters. The API changes supported state; the runtime executes it.
A package signature does not prove that a runtime supports a behavior.

See [delivery milestones](../product-direction.md#subsequent-milestones) and
[package compatibility](../product-direction.md#package-and-api-boundaries).

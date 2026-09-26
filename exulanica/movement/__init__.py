"""Movement modules: one engine module per kind of movement, chosen by data.

``movement-modules.v1.json`` states each module: the space it moves in, the catalog its agents
come from, its clock, its bounded parameters with reasons, the output it hands a renderer, and
whether it is built (:mod:`exulanica.movement.registry`). :mod:`exulanica.movement.steps` holds
each built module's step. Walking (:mod:`exulanica.movement.walking`) moves a society's people over
a route graph; flight (:mod:`exulanica.movement.flight`) moves flying kinds through a world's air
volume. Roads are stated and not connected.

Pure: nothing here opens a database or a store, or imports the world, traffic or a model. The
world composes each module's input and passes it down (docs/movement-modules-contract.md).
"""

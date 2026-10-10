"""Movement modules: one engine module per kind of movement, chosen by data.

``movement-modules.v1.json`` states each module: the space it moves in, the catalog its agents
come from, its clock, its bounded parameters with reasons, the output it hands a renderer, and
whether it is built (:mod:`exulanica.movement.registry`). :mod:`exulanica.movement.steps` holds
each built module's step. Walking (:mod:`exulanica.movement.walking`) moves a society's people over
a route graph, and its second version (:mod:`exulanica.movement.walking_v2`) moves each at its
own body's pace; flight (:mod:`exulanica.movement.flight`) moves flying kinds through a world's air
volume; flight for beings (:mod:`exulanica.movement.flight_v2`) flies a world's flying things one
society minute at a time through its air columns. Roads run in a host above this package.

Pure: nothing here opens a database or a store, or imports the world, traffic or a model. The
world composes each module's input and passes it down (docs/movement-modules-contract.md).
"""

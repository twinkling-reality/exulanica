"""Traffic: cars, vans, buses and bicycles on generated streets, as a deterministic simulation.

A vehicle follows lanes and lane connectors, stops at stop lines, gives way by the junction's
rule, keeps out of crossings pedestrians are on, and parks. Every second is one pure step over
integers and recorded inputs, so a replay of the same inputs is byte-identical.

**What a run reads.** Road records (lanes, connectors, junctions and their approaches, signal
controllers and groups, crossings, parking spaces), the three traffic catalogs under
``assets/catalogs/traffic`` (vehicle classes, right-of-way policies, signal plans), a seed, a
fleet, and two ordered inputs: trip requests and the pedestrian crossing feed.

**What it writes.** A state document per second, events with uuid5 identities, and a transition
receipt binding the previous and next state digests, the inputs consumed and the events.

**The modules.**

``catalogs``
    The cited, licensed vehicle, policy and signal catalogs and their digest.
``provisional_records``
    The approved road record shapes, until the city vocabulary lane lands them in the grammar.
``geometry``, ``kinematics``, ``signals``, ``routing``
    Integer geometry, the braking-envelope safety rule, signal indications as a pure function of
    the second, and deterministic routing.
``network``
    The compiler: records and catalogs in, a checked network with conflict zones out, or a
    refusal that says why.
``inputs``, ``simulation``
    The input contracts and the step.
``checks``
    Mechanical checks of every transition, written apart from the step.
``metrics``, ``presentation``
    Throughput, delay and parking occupancy; the per-vehicle record the tessellator draws.

**The layer.** This package sits below the database, the store and the model client, and a
forbidden contract keeps it from the evidence spine, the pipeline, reconstruction, the capture
verdict and the society engine. See ``docs/traffic-contract.md``.
"""

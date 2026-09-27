# ADR-0006: Desktop/laptop viewport boundary

- Status: Accepted
- Date: 2026-08-29
- Supersedes the mobile-delivery portions of ADR-0003 and ADR-0005.
- Affects: [interaction model](../interaction-model.md)

## Context

The Atlas interaction depends on pointer lock, a fixed-centre reticle and a wide continuous world.
Earlier documents proposed a separate mobile World Index mode because dominant mobile browsers do
not support pointer lock. That proposal expanded the current prototype into a second navigation and
layout system. The active product scope is desktop and laptop only.

The app already had a `60rem` responsive breakpoint. Keeping that implementation boundary is more
honest than using device sniffing or presenting an unvalidated mobile mode as equivalent.

## Decision

The current Atlas supports viewports wider than `60rem`. At or below that boundary it displays one
plain notice that the prototype requires a wider laptop or desktop window.

There is no mobile command vocabulary, mobile Index entry mode, touch traversal, virtual joystick,
gyro mode or mobile Companion arrangement in this prototype. The World Index remains a desktop
overlay and keyboard/accessibility route.

## Consequences

- The shell always begins in the live desktop Atlas.
- `I`, `M`, `O` and `?` have one meaning across the supported viewport.
- Narrow layouts do not silently expose inactive or differently behaving controls.
- A future mobile product requires a new decision, implementation and validation pass.

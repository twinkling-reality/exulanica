# Generated-world representation decisions

This reference owns how a generated world is represented: the tile container the tessellator in
`web/packages/loom-tess` bakes from a grammar package, what that representation lets a reader name,
select, vary and compare, each decision it rests on, and the condition that would force the decision
to change. A decision is listed whether or not it is settled, and an unsettled one says so. A
representation decision that lives only in the code is indistinguishable from an accident: a reader
cannot tell a value that was chosen from a value that was never questioned.

## Contents

- [A world built from records](#a-world-built-from-records)
- [What the representation supports](#what-the-representation-supports)
- [What it does not support](#what-it-does-not-support)
- [Settled](#settled)
- [Settled, and only partly built](#settled-and-only-partly-built)
- [Unsettled, and named so nobody assumes otherwise](#unsettled-and-named-so-nobody-assumes-otherwise)

## A world built from records

A generated world is built from records rather than modelled as a surface, so any part of it can be
named, selected, varied or held fixed. A controlled comparison of two worlds needs them identical
except in one respect, and three properties together make that demonstrable:

| Property | Mechanism |
| --- | --- |
| Every drawn thing has an identity | `render_batch` preserves the record and stated identity of every triangle, as a contract term |
| Every world has a name that depends on its inputs | Content addressing: the container digest, `tile_inputs_digest`, per-projection triangle digests, the catalog digest, the tessellator version and the grammar version pins |
| Generation reads nothing but its declared inputs | A source scan over the tessellator's core |

The third does the most work. Without it two worlds could differ in ways no digest records.
`web/packages/loom-tess/test/vocabulary-emptiness.test.ts` scans every file in the tessellator's core
and refuses, among other things:

| Refused | What it would otherwise admit |
| --- | --- |
| Domain vocabulary in source | A word the grammar should state, fixed in code where no document can vary it |
| Bare numeric literals | A dimension nobody declared |
| `??`, `\|\|`, default parameters, a `switch` default | A fallback that silently supplies a value the inputs did not |
| `Math.random` | Variation no digest can reproduce |
| `Date.now` | A result that depends on when it ran |
| `localeCompare`, unsorted `Object.keys`, `for...in` | An order that depends on the host |
| Filesystem and dynamic imports | An input arriving from outside the declared ones |

The scan carries its own positive control: planted violations must be found first, so a scan that
stopped working would fail rather than pass. These rules are why two containers with the same inputs
are byte-identical, and therefore why a difference between two worlds can be attributed to what was
changed.

## What the representation supports

**Selection and counting by identity.** Each drawn entry names its record and its triangle range, and
each surface within it names its role, orientation and material record, or states that none exists.
No role is inferred from geometry, so how many square metres a role covers, or every triangle of one
record, is answered from the container without rendering anything.

**Attributing a change to its cause.** Digests move independently. A catalog change moves the
container digest and not the triangle digests, so provenance changes and geometry changes are told
apart without inspecting either. The corridor street's
[six bakes](generated-corridor-street.md#9-the-bakes-of-one-street) show
this, including a bake where nothing drawn or walked changed and only the container digest moved.

**Stating what is absent.** A container entry carries `unavailable` with the needs that would satisfy
it, or `not_admitted`, `not_in_projection` or `halo`, so a comparison distinguishes a thing that is
missing from a thing that was never admitted.

**Predicting before measuring.** The visual gate commits its predictions to the repository before a
run and keeps the wrong ones ([visual gate targets](visual-gate-targets.md)).

## What it does not support

**Naming a record from a pixel.** Identity reaches the triangle, not the frame. Going from a rendered
pixel through the depth buffer to the triangle and its record is not built, so a container can be
queried by identity but a picture cannot be captioned by one, and a claim about what a frame shows
rests on a person looking at it.

**A world variant as a first-class object.** Nothing in the tile schema says that two tiles are the A
and the B of one comparison, which input distinguishes them, or what question they were built to
answer; that relationship lives in prose beside them, and a comparison whose design is prose can
drift from what was run. Comparisons of models are different: a comparison runs the same hour of one
saved world once per model and is stored and replayed as a declared object
([society experiments](society-experiments.md#comparisons-of-models)).

**Occupancy and picking.** `collision_proxy` and `pick_geometry` are named by the grammar and have no
contract (below). A consumer needing solid occupancy has no projection that offers it, and
`nav_envelope` must not be substituted: its contract is support and clearance, not solidity.

## Settled

### Coordinates are exact integers

Recorded in [ADR-0024](adr/0024-declared-coordinate-quantum.md).

The quantum is one millimetre, declared in the container header and refused on mismatch by
`checkHeader`, and stated by a tile document in its tile record, closed to that one value by the
grammar. A document written before the field existed is read at millimetres because the version it
pins fixes the unit, never because a reader supplied one; a version no table states is refused.

**Forcing condition:** a generated dimension whose millimetre rounding changes what a reader sees or
measures. The lettering rule measures rounding as safe above about 100 mm. The first candidate below
that line is the segmental arch's chord bisection in facade layout.

### Floating point is presentation, never source

The container carries integer `position_mm` and a float32 `position` section derived from it, in
metres from `origin_mm`. Nothing derives integers from floats.

**Forcing condition:** none identified. The one defect traced to floating point in this pipeline is
`navEnvelopeSupport` refusing a point exactly on a shared triangle edge, where a barycentric weight
evaluates to -5.551e-17.

### Unavailability is stated, not omitted

A container entry carries its state: `drawn`, `unavailable` with the needs that would satisfy it,
`not_admitted`, `not_in_projection`, or `halo`. A record the tessellator cannot draw produces a
statement about why, not a gap. Most generated worlds represent absence as nothing, which makes
absence indistinguishable from an oversight.

**Forcing condition:** none. This one is a floor, not a compromise.

### Record identity reaches the triangle

`render_batch` preserves "the record and stated identity of every triangle" as a contract term, not
as an implementation detail. This is what makes the world queryable rather than merely renderable.

**Forcing condition:** none.

## Settled, and only partly built

### Five projections are named, two are materialised

The grammar names `render_batch`, `collision_proxy`, `nav_envelope`, `pick_geometry` and
`export_gltf`. `PROJECTION_DEFINITIONS` in `web/packages/loom-tess/src/core/expand.ts` materialises
two: `render_batch` and `nav_envelope`.

The three that are not materialised have no contract, which is why they are absent rather than
approximated. A consumer needing occupancy or picking either does without or improvises one from a
projection whose contract forbids that use: `render_batch` names `support height`, `collision` and
`measurement` as inadmissible uses.

**Forcing condition:** a consumer that needs one. Design the contract before the geometry, as the two
materialised projections were.

### One level of detail

`MATERIALISED_LOD` is 0. A tile at any other level is refused rather than drawn at this one and
labelled as the other. Drawing one level and calling it another is how a world starts lying about
its own fidelity.

**Forcing condition:** a scene too large to draw at one level. No such scene exists in the
repository.

## Unsettled, and named so nobody assumes otherwise

### The step rule is absolute, not a gradient

The walking rule compares a height difference against a fixed step: the walker climbs a step of
180 mm ([visual gate targets](visual-gate-targets.md)), and a surface that rises more is refused.

**The defect this hides:** a real ramp rises continuously and would be refused, correctly by the
letter of the rule and wrongly by its intent. Nothing on the corridor is a ramp, so the defect has
never fired.

**The revision, already named:** separate a step from a gradient, so a rise over a distance is a
different question from a rise at a point.

**Forcing condition:** the first producer that publishes a ramp. Accessibility work would produce one
immediately.

### A catalog entry's register is a prefix on a sentence

A catalog entry states its provenance as English prose, and the gate matches on the first words of
that sentence. Matching on the opening of a sentence is a parser over English, and English is not a
schema.

**The revision, decided in principle and not scheduled:** a declared field from a closed set the
schema names, so the loader refuses an unknown value and the field enters the digest like every other
schema field.

**Two hazards recorded with it.** The proposed third value, `depicts`, is a weak name and was left
unchosen rather than picked quietly. And the obvious field name is taken: `origin_kind` is already a
column on world objects in `exulanica/world/object_repository.py`, describing a different axis. A
catalog field of the same name would collide in every reader that handles both.

**Separable and cheaper, needing no digest move:** the licence contradiction test alone. Measured on
2026-09-18 at 782ab758 across 133 city entries: 98 authored with an original licence, which the gate
asserts; 19 derived with a derived licence, which nothing asserts; 16 carrying the material sentence
with an original licence, whose origin nothing ties to its register. The hole was 35 entries wide.

**Forcing condition:** the next catalog change that already moves the digest, so the world rebakes
once for two reasons rather than twice for one each.

### A surface knows its look and not its physics

A surface carries a role, an orientation and a material record. It does not carry density, albedo,
thermal mass, acoustic absorption, permeability or hardness. The world can be drawn and walked. It
cannot be asked how hot the street gets, how loud the corner is, or where the rain goes.

**The shape of the addition:** a table of physical parameters per material class, and a projection
that reads them. It is a table plus a contract, not a rewrite, because the geometry and the material
classes already exist.

**Forcing condition:** a question about the world that is not about looking at it. Do not build it
before that question is real, and do not build it before `collision_proxy` and `pick_geometry`, which
are named, needed and missing. A design that grows a sixth projection while three of five are
unbuilt is getting wide instead of deep.

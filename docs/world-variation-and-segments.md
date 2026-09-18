# World variation and segments

What it means that a world is built from records rather than modelled as a surface: any part of it
can be named, selected, varied or held fixed, and two worlds can be compared with a proof that they
differ in one respect only.

This document states what the tree supports, and what it does not. The gap between the two is the
interesting half.

## The property

A controlled comparison needs two worlds identical except in one respect. That is easy to claim and
hard to demonstrate, and unseen confounding is why simulation results are hard to trust.

Three things together make it demonstrable here.

| Property | Mechanism |
| --- | --- |
| Every drawn thing has an identity | `render_batch` preserves the record and stated identity of every triangle, as a contract term |
| Every world has a name that depends on its inputs | Content addressing: the container digest, `tile_inputs_digest`, per-projection triangle digests, the catalog digest, the tessellator version and the grammar version pins |
| Generation reads nothing but its declared inputs | A source scan over the tessellator's core, described below |

The third is the one that is easy to miss and does the most work. Without it two worlds can differ in
ways no digest records, and the comparison is worthless however good the identities are.

## Why the core source rules exist

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

The scan carries its own positive control: a test plants one of each violation and asserts the scan
finds it, so the scan cannot pass by having stopped working.

These rules read as pedantry when writing a single rule. They are the reason two containers with the
same inputs are byte-identical, and therefore the reason a difference between two worlds can be
attributed to the thing that was changed.

## What the tree supports

**Selection and counting by identity.** Each drawn entry names its record and its triangle range, and
each surface within it names its role, orientation and material record, or states that none exists.
No role is inferred from geometry. So a question like how many square metres of a given role, or
every triangle belonging to one record, is answered from the container without rendering anything.

**Attributing a change to its cause.** Digests move independently. A catalog change moves the
container digest and not the triangle digests, so provenance changes and geometry changes are
distinguishable without inspecting either. The corridor's bake table demonstrates this across six
tessellator versions, including one where nothing drawn and nothing walked changed and only the
container digest moved.

**Stating what is absent.** A container entry carries `unavailable` with the needs that would satisfy
it, or `not_admitted`, `not_in_projection`, or `halo`. A comparison between two worlds can therefore
distinguish a thing that is missing from a thing that was never admitted.

**Predicting before measuring.** The visual gate commits its predictions to the repository before a
run, and keeps the wrong ones. `docs/visual-gate-targets.md` carries four predictions from one run of
which two were wrong, with the reasoning that failed.

## What the tree does not support

**Naming a record from a pixel.** Identity reaches the triangle, not the frame. Going from a rendered
pixel back through the depth buffer to the triangle to the record is scoped and not built. Until it
exists, a container can be queried by identity but a picture cannot be captioned by one, and a claim
about what a frame shows rests on a person looking at it.

**A segment or variant as a first-class object.** Nothing in the schema says that two tiles are the A
and the B of one comparison, which input distinguishes them, or what question they were built to
answer. Today that relationship lives in whatever document a person writes beside them. A comparison
whose design is prose is a comparison whose design can drift from what was run.

**Occupancy and picking.** `collision_proxy` and `pick_geometry` are named by the grammar and have no
contract. A consumer needing solid occupancy has no projection that offers it, and `nav_envelope`
must not be substituted: its contract is support and clearance, not solidity. See
`docs/representation-decisions.md`.

**A population that responds differently to different worlds.** This is the one that would make a
comparison return nothing for a reason unrelated to the intervention. The district society was
measured converging on a single node, with four destinations for 128 people, a rest threshold that
never fires, and coincident collapse drawing one person. If both worlds collapse to the same node,
the comparison reports no difference whatever was changed.

That measurement predates the merge of the fourth society version. Re-measure it before building any
comparison on top of it, and state the measurement rather than the expectation.

## The order this suggests

Each step below makes the next one meaningful, and none of them is a rewrite.

1. Re-measure whether the society still converges. A comparison over a population that collapses
   answers nothing, and this is a measurement, not a build.
2. Give `collision_proxy` and `pick_geometry` their contracts, so a population can interact with a
   world rather than walk across it.
3. Make a comparison a declared object: the two worlds, the one input that differs, the question, and
   the prediction, committed before the run in the form the visual gate already uses.
4. Build the pixel-to-record tool, so a frame can be captioned by identity and a difference can be
   shown rather than described.

Physical surface parameters, which would let the world answer questions about heat, sound and water,
belong after those. The reasoning is in `docs/representation-decisions.md`: three of five named
projections are unbuilt, and a design that adds a sixth before finishing those is getting wide
instead of deep.

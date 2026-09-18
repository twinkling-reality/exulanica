# ADR-0024: Integer coordinates at a declared quantum

- Status: Accepted
- Date: 2026-09-18
- Deciders: Exulanica build
- Supersedes: nothing
- Related: `docs/representation-decisions.md`, `web/packages/loom-tess/README.md`

## Context

World geometry is exact integers. That choice is load-bearing in three places, and none of them
survives a move to floating point.

| What integers buy | Why floating point loses it |
| --- | --- |
| Content-addressed bakes | Identical inputs must give bit-identical output. Float results vary with compiler, architecture and optimisation level |
| Refusals that fire | A refusal such as two heights over one plan point needs exact equality |
| Cross-architecture agreement | Determinism is checked on arm64 and x86_64 under Rosetta. Float geometry kernels disagree at the last bit |

The project has one measured instance of the cost. `navEnvelopeSupport` refuses a point sitting
exactly on a shared envelope triangle edge, because a barycentric weight evaluates to -5.551e-17 and
both triangles reject it. That defect exists in the one place the pipeline uses floating point.

The quantum is one millimetre, and that value was inherited rather than chosen. Records come from
building surveys and city data, a domain that works in millimetres. Storing a surveyed curb height of
95 mm as 95,000 micrometres would state four digits of precision nobody measured, which is the
failure this project's evidence rules exist to prevent.

Generated detail changes that reasoning. A tessellator that writes lettering relief, mouldings,
reveals and a segmental arch produces dimensions bounded by no survey. The lettering rule already
measures millimetre rounding as safe only above about 100 mm, with an edge cap of radius over 100.

### What the tree states, and what it does not

| Artefact | Declares the unit | Refuses a mismatch |
| --- | --- | --- |
| Container header `coordinates.unit` | Yes, from `COORDINATE_UNIT` in `web/packages/loom-tess/src/core/owd.ts` | Yes. `checkHeader` refuses a container whose `coordinates` block differs from the block this build writes |
| Bake record `coordinate_unit` | Yes, in `web/packages/loom-tess/src/core/bake.ts` | Records what a bake used |
| Tile document | **No** | **No** |

The container asserts its records are in millimetres. The records do not say so. A producer writing a
tile document in another unit is refused by nothing, and a reader cannot tell the difference between
a document that means millimetres and one that does not.

## Decision

1. **Integer arithmetic stays, and this ADR does not reopen it.** Coordinates are exact integers in
   the document, in the container, and in every rule between them. Floating point belongs to
   presentation: the container's `position` section carries float32 metres for the renderer, derived
   from the integer `position_mm` section, never the reverse.

2. **A tile document states its coordinate unit.** The unit becomes a field a producer writes, and
   the tessellator refuses a document that omits it or states a unit the running version does not
   write. The container's claim about its records then rests on something the records stated.

3. **The quantum is one millimetre, and one millimetre is a constant of the tessellator version, not
   a per-document variable.** Two quanta coexisting in one world is a class of defect nobody wants:
   a rule that reads two documents would have to scale between them, and every scaling is a place a
   value can be wrong by a factor of a thousand while looking plausible.

4. **Changing the quantum is a tessellator version bump and a full rebake.** The existing machinery
   already carries that: a version mismatch is refused by `decodeOwd`, the digests move, and the
   evaluation records that bind old digests stay correct because they describe a past bake.

5. **A finer quantum is a measurement's decision, not a preference.** The condition that moves it is
   a generated dimension whose millimetre rounding changes what a reader sees or measures. Whoever
   proposes the move states the dimension, the rounding error and the effect.

### The best figure available, and what it is not

Read from the grammar's inputs across the corridor city: segmental arch rises run 5 mm to 772 mm over
widths of 613 mm to 2,083 mm. The shallowest is a rise of 5 mm over a width of 758 mm, in tile (2,0)'s
halo; the shallowest in owned geometry is a rise of 8 mm over a width of 1,258 mm. An arc with a 5 mm
sagitta has at most five distinct integer heights along its whole span, so at a one millimetre quantum
that arch is the difference between a curve and a staircase.

**This is a property of the records the first sub-100 mm work will read. It is not a measurement of a
rule's output, because no such rule exists.** The number that decides the quantum is the measured
chord and point spacing of the arch rule once it is written, and it is not in this document. The
figure above says the forcing condition is reachable, not that it has been reached.

## What a producer must write

This is the obligation that changes for anyone writing a tile document. Stated plainly because the
next piece of generation work has to obey it:

- A tile document carries its coordinate unit in the tile record, beside the grammar version pins it
  already carries.
- A document that omits the unit is refused, not defaulted. A default is how an assumption survives
  a rule written to remove it.
- The value is `millimetre` until an ADR supersedes this one.

### An artefact written before the field exists

Containers need nothing. Every container already carries `coordinates.unit`, and `checkHeader`
already refuses one whose block differs from the block its reader writes.

Tile documents need a rule, because none of them carries the field today and a refusal on absence
would refuse every document that exists.

**The unit is a property of the schema version, and the schema version is already pinned.** The field
enters at a named grammar version. A document pinned to an earlier version has no field and is read
as millimetres, not because a reader defaulted, but because that version fixes the unit. A document
pinned at or after that version without the field is refused.

The distinction matters and it is the reason this is not "assume 1 mm when absent". A reader never
supplies a unit the artefact did not fix. It reads the field, or it reads the version that fixes the
field's absence. What a reader must not do is meet an unrecognised version and carry on in
millimetres, which is the assumption this ADR exists to remove.

Migration cost is therefore one schema version and no rebake of anything already written.

## What this ADR does not do

It changes no code. The document field, its refusal and its tests are a schema change to be made on
its own, in the same commit as the tests that prove a document without the field is refused and a
document with a different unit is refused. Until that lands, the input side is as described above and
nothing refuses an undeclared unit.

It also does not change the quantum. Millimetres remain, and the first candidate for trouble is
measured rather than predicted.

## Consequences

**A stale reader refuses instead of misreading.** This is the whole point. The failure being
prevented is a reader that assumes millimetres, receives something finer, reports success and is
wrong by three orders of magnitude in a value that still looks like a plausible building.

**Migration is bounded.** Evaluation records under `docs/evaluation/` need no change. A record
describes a bake that happened, in the units of that bake, and rewriting one would break the
provenance chain the records exist to carry.

**The cost of the move is known in advance.** A quantum change is a version bump, a rebake of every
tile, and new digests. It is not a rewrite of the arithmetic, because the arithmetic is already
integer.

**Range is not the constraint.** A 128 m tile in micrometres is 1.28e8, inside int32. A 100 km extent
in micrometres is 1e11, inside both a Postgres bigint and the exact integer range of a JavaScript
number, which is 9.0e15.

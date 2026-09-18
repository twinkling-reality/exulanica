# Representation decisions

Every choice about how the world is represented, what each one assumes, and the condition that would
force it to change. A decision is listed here whether or not it is settled. An unsettled one says so.

The reason this document exists: a representation decision that lives only in the code is
indistinguishable from an accident. A reader cannot tell a value that was chosen from a value that
was never questioned, and neither can a rule.

## Settled

### Coordinates are exact integers

Recorded in `docs/adr/0024-declared-coordinate-quantum.md`.

The quantum is one millimetre, declared in the container header and refused on mismatch by
`checkHeader`. A tile document does not yet declare its unit, which ADR-0024 decides it must.

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
statement about why, not a gap.

This is unusual and it is deliberate. Most generated worlds represent absence as nothing, which makes
absence indistinguishable from an oversight.

**Forcing condition:** none. This one is a floor, not a compromise.

### Record identity reaches the triangle

`render_batch` preserves "the record and stated identity of every triangle" as a contract term, not
as an implementation detail. Each drawn entry names its record and its triangle range, and each
surface within it names its role, orientation and material record, or states that none exists. No
role is inferred from geometry.

**Forcing condition:** none. This is what makes the world queryable rather than merely renderable.
See `docs/world-variation-and-segments.md`.

## Settled, and only partly built

### Five projections are named, two are materialised

The grammar names `render_batch`, `collision_proxy`, `nav_envelope`, `pick_geometry` and
`export_gltf`. `PROJECTION_DEFINITIONS` in `web/packages/loom-tess/src/core/expand.ts` materialises
two: `render_batch` and `nav_envelope`.

The three that are not materialised have no contract, which is why they are absent rather than
approximated. A reader wanting solid occupancy wants `collision_proxy` and must not substitute
`nav_envelope`, whose contract is support and clearance, not solidity.

**Consequence today:** a consumer needing occupancy or picking either does without or improvises one
from a projection whose contract forbids that use. `render_batch` names `support height`, `collision`
and `measurement` as inadmissible uses.

**Forcing condition:** a consumer that needs one. Design the contract before the geometry, as the two
materialised projections were.

### One level of detail

`MATERIALISED_LOD` is 0. A tile at any other level is refused rather than drawn at this one and
labelled as the other.

The refusal is the decision. Drawing one level and calling it another is how a world starts lying
about its own fidelity.

**Forcing condition:** a scene too large to draw at one level. Nothing in the tree is yet.

## Unsettled, and named so nobody assumes otherwise

### The step rule is absolute, not a gradient

The walking rule compares a height difference against a fixed step. The world states a step it will
climb, measured at 0.18 m in the gate's run record in `docs/visual-gate-targets.md`. A surface that
rises more is refused.

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

**The revision, decided in principle and deliberately unscheduled:** a declared field from a closed
set the schema names, so the loader refuses an unknown value and the field enters the digest like
every other schema field.

**Two hazards recorded with it.** The proposed third value, `depicts`, is a weak name and was left
unchosen rather than picked quietly. And the obvious field name is taken: `origin_kind` is already a
column on world objects in `exulanica/world/object_repository.py`, describing a different axis. A
catalog field of the same name would collide in every reader that handles both.

**Separable and cheaper, needing no digest move:** the licence contradiction test alone. Measured
across 133 city entries: 98 authored with an original licence, which the gate asserts; 19 derived
with a derived licence, which nothing asserts; 16 carrying the material sentence with an original
licence, whose origin nothing ties to its register. The hole is 35 entries wide.

**Forcing condition:** the next catalog change that is already moving the digest, so the world rebakes
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
are named, needed and still missing. A design that grows a sixth projection while three of five are
unbuilt is getting wide instead of deep.

# Owned district and source admission

Status: **OWNED DISTRICT DATA PATH AND RENDERER**. Complete-district validation is not established.

The bounded Flatiron district is Exulanica's first owned geographic environment. “Owned” means the
runtime possesses a local, versioned artifact admitted for the declared operations. It does not
mean Exulanica owns New York geography, that the artifact is photorealistic, or that every visible
detail came from the provider.

Implementation:

- compiler: `exulanica/environment/owned_district.py`;
- preparation command: `scripts/prepare_owned_district.py`;
- asset: `assets/owned-world/flatiron/flatiron-owned-district.json`;
- parser/navigation: `web/packages/atlas-core/src/owned-district.ts`;
- optional interpretation: `exulanica/environment/district_interpretation.py` and
  `web/packages/atlas-core/src/district-interpretation.ts`;
- shared clearance predicates: `exulanica/environment/district_geometry.py` and
  `web/packages/atlas-core/src/district-geometry.ts`;
- rendering: `web/packages/atlas-react/src/playcanvas/owned-district-runtime.ts`;
- application loading: `web/packages/app/src/config.ts`; and
- decision evidence: `docs/evaluation/2026-09-13-owned-world-source-decision.json`.

## Source and admission

The compiler accepts two bounded NYC Open Data GeoJSON datasets:

| Content | Dataset | Retained source semantics |
| --- | --- | --- |
| Building footprints and available attributes | `5zhs-2jue` | DOITT identity, geometry, name/BIN/year where present, roof-height-derived mass |
| Sidewalk polygons and available attributes | `52n9-sdep` | source identity, geometry, status/code where retained |

The source query is bounded around Flatiron and capped at 1,000 features per layer. The compiler
records each dataset identity, provider revision, source digest, attribution, source URL and the
operations reviewed for this artifact. Coordinates are transformed into a local centimetre frame
around the declared geographic origin. The transform does not change source identity.

`parseOwnedDistrict` fails closed unless every source record explicitly permits display,
persistence and modification. The backend admission plan carries the broader operation matrix.
Those booleans are a reviewed source decision for this exact use, not a general statement that all
NYC or third-party map data may be extracted, trained on, or redistributed.

The web client carries no third-party photorealistic tiles. A provider feed licensed for viewing
only cannot become ground a person edits, saves or builds on (the source evaluation in
[the world composition contract](world-composition-contract.md#data-source-fitness-and-visual-quality)),
so collision, semantic identity, persistence and export come only from admitted sources such as
the owned district described here.

## The admission chain, and the place an admitted source belongs to

An admitted source is always admitted **to a place**. The place is what a memory, a question and
an authored placement all address, and without one an admission is bytes with a licence and no
subject. Because an external source has no reconstruction behind it, its place cannot be anchored
by a scene; it declares its frame instead. `place-identity.md` owns that decision, including the
honesty column that keeps a declared frame from being read as a measured one, and the two
alternatives it rejects.

The chain, in the order the routes take it:

| Step | Route | What it establishes |
| --- | --- | --- |
| Create the place | `POST /environment-resources/places` | A canonical place whose frame is a provider's declaration, with `frame_authority`, the declared frame and bounds, and a digest-bound receipt |
| Read it back | `GET /environment-resources/places/{place_id}` | The same declaration, for any later reader holding only the identifier |
| Admit the source | `POST /environment-resources/sources` | Exact local bytes, verified against the declared digest and size, with provenance, attribution and the operation matrix |
| Register derived bytes | `POST /environment-resources/assets` | A render or extraction output bound to that admission's source digest and lineage |
| Publish a catalog | `POST /environment-resources/sources/{admission_id}/feature-indexes` | The bounded feature index and its relational projection, pinned to exact source and render digests |
| Read features | `GET /environment-resources/sources/{admission_id}/features` | The current publication, filtered, with fail-closed rights and digest binding |

Each step resolves rights for itself. Creating a place grants nothing: a place carries no
operation rights, and a source is admitted, derived from, indexed and composed only while
`environment_resource_allows` says so for that exact operation at that exact moment. An
admission whose rights review has not concluded is not admissible, and the preparer for NYC
Building Footprints writes a plan that says so rather than a row: it marks place identity as
integration input and the operation rights as requiring legal review, and leaves publication
blocked. Nothing in the chain above overrides that.

### What an admission into a declared place must agree with

The admitted source must carry the frame its place declared and its bounds must lie inside the
declared box, checked in integers over bounds of kind `bbox` or `polygon`. Bounds naming a
provider feature identifier are refused, because a feature id is not geometry and nothing could
establish that it lies inside a box.

A derived asset is **not** held to the place's frame. A derivation may legitimately reproject
into a local frame, which is what the Flatiron compiler does when it transforms source
coordinates into a local centimetre frame, and a constraint there would forbid the ordinary case
in order to restate a fact about the source.

### A refused admission stores nothing

Admission verifies the local bytes against the declared digest and size, writes the row, and only
then puts the bytes in the content-addressed store. Every refusal therefore happens before
anything is stored, including refusals the database raises inside the write, so a rejected
request leaves no row and no blob under a digest nothing references. The ordering is what makes
that true of refusals added later, rather than of a list of checks somebody remembered to put
first.

### What is not reachable from the interface

No browser flow admits a place or a source. The routes above are exercised end to end against
PostgreSQL and a real content-addressed store, including composition into an authored version and
a cross-content Selection over the resulting place, and no shipped screen calls them. Admitting a
real provider dataset is a separate decision about that provider's terms and has not been made.

## What the artifact authoritatively contains

The `exulanica.owned-district/v1` browser contract contains:

- district identity, name, seed and local bounds;
- source records and operation rights;
- building source identity, optional attributes, local polygons, height, material class and render
  batch identifier;
- sidewalk source identity, optional status, local polygons and bounds; and
- a bounded material catalog.

The same building polygons drive mass extrusion, semantic building picking and polygon collision.
The same district bounds drive visible support and navigation recovery. This shared input is a
contract invariant: selection and collision do not infer identity from PlayCanvas entity names.

## What it does not authoritatively contain

Version 1 contains no explicit:

- road centerlines, lanes, crossings, curb graph, traffic state or road classification;
- facade openings, storefronts, doors, cornices, signs or facade materials;
- roof structures or mechanical equipment;
- individual trees, planting, lamps, benches or street furniture;
- interiors;
- pedestrian paths, destinations or affordance graph; or
- photogrammetric appearance.

The browser does not complete any of those. It draws each building as its recorded footprint and
roof height, and each sidewalk as its recorded footprint, outlined and hatched with no surface
material, the sidewalks lighter so they read as ground. It draws the ground as a grid marking the
authored flat walking datum. That drawing represents the recorded footprints and heights; it is not
new data. No facade, roof, tree, lamp or street-furniture geometry is generated, the material class
and material catalog above are not drawn, and the interpretation's facade grids and parapets are
not drawn either. Two tints are declared and name recorded facts rather than materials: an
authored instance, drawn with the same outline and hatching, takes one tint per recorded role, and
the interpretation's generated entrance and rest markers take one tint that marks them as
generated.

## Interpretation boundary

The optional district extension uses a versioned, engine-neutral interpretation compiler. Each
consequential result records:

- stable subject or parametric-pattern identity;
- source feature dependencies;
- `source`, `inference`, `authored`, or `generated` origin on the applicable axis;
- compiler/model version, parameters, deterministic seed where applicable, and output digest;
- coordinate frame and temporal/source revision scope;
- uncertainty and alternatives;
- permitted uses such as render, select, collide, navigate, simulate, modify, train, or export; and
- withdrawal and supersession behavior.

Not every window vertex needs a durable entity. A facade grammar can be a compact authoritative
interpretation until an individual window becomes selectable, editable, simulated, persistent, or
queryable. Trees, doors, lamps and inhabitants cross that threshold earlier because users and
simulations naturally treat them as objects.

The renderer compiles interpretation records into batches. Renderer batching, tessellation, LOD,
shadows and tone mapping remain disposable representation detail.

## Optional interpretation v1

`exulanica.district-interpretation/v1` is a separate artifact; the retained district v1 bytes,
manifest, admission plan and bound evaluation artifacts remain unchanged. Compile from retained
bytes without fetching another source:

```sh
uv run python scripts/prepare_owned_district.py assets/owned-world/flatiron-interpretation-v1 \
  --interpretation-from assets/owned-world/flatiron/flatiron-owned-district.json
```

`assets/owned-world/flatiron-interpretation-v1/district-interpretation.json` is the retained
producer output for the connected demonstration. This is a district mechanics fixture, not
personal-source acceptance. The PlayCanvas consumer and authenticated society-district read are
implemented; that connection does not establish street-level visual quality or a production
personal-world registration.

The document binds `base_artifact_sha256` to the exact original bytes, including whitespace.
`document_sha256` hashes canonical, integer-only UTF-8 JSON excluding only its own field.
`producer` is `flatiron-interpretation/1`; `seed` retains the base seed. Arrays with semantic
identities are sorted and unique. The compiler has no clock, network, model call or database write.
Changing the seed changes the generated recipe digest without changing source identities.

All extension positions are integer `[x,z]` millimetres, east/south, in `flatiron-local-mm`.
`origin_crs84_e7` is copied from the base. Base centimetres multiply by ten exactly; runtime metres
divide millimetres by 1,000. Height is above `authored-flat-ground`, not surveyed elevation. No
personal-region registration is inferred from this origin. Bounds are `[west,north,east,south]`.

Each subject carries `subject_id`, `kind`, `epistemic_status`, exact feature/dataset/digest
`source_refs`, a plain uncertainty statement, `permitted_uses` and a tagged `recipe`. Source
subjects retain their existing feature IDs; generated identities depend on source subjects or
fixed grid coordinates, never render batch order. Producer, frame, seed, source revision scope and
digest are inherited from the enclosing document. The interpretation itself has no authored branch;
its placement in a branch is a separate input. No windows receive separate object identities.

| Recipe | Authority and bounded meaning |
| --- | --- |
| `source-footprint` | Observed source footprint reference, preserving every polygon and ring in the bound base. Building subjects support exterior collision; sidewalks alone do not assert accessibility. |
| `facade-grid` | Generated mass height, bay/floor spacing, window dimensions, recess and material index. Base height can be source-derived, clamped or fallback; v1 cannot distinguish these cases. No observed windows or material claim. |
| `roof-parapet` | Generated flat roof at the declared mass height and parapet height. Holes must remain holes. No surveyed roof equipment or roof access. |
| `flat-ground` | Authored zero-height datum for visible ground and existing collision support. |
| `residual-ground` | Generated visible ground minus all retained building and sidewalk subjects. Not observed roads, lanes, crossings or route support. |
| `walk-envelope` | Interpretation defining bounded graph coverage and grid spacing. Does not turn omitted areas into free space. |
| `entrance-marker` | Generated exterior arrival marker at a route node near a named building facade edge. Position is outside the footprint, not an actual door location; no entering or indoor connection. |
| `rest-pad` | Generated flush civic rest marker with radius and zero height. Rest means a timed pause, not seated activity or observed street furniture. |

The bounded graph samples a four-metre grid within local x = -60 to 110 metres and z = 30 to
200 metres, clipped to the district. It retains the largest connected component, with a stable
lexicographic tie break. The retained result has 93 nodes, 151 undirected edges and four
destinations: a generated exterior visit marker near the Flatiron Building and three rest pads.
Other components, park interiors, road crossings and unsupported space have no edges.

Every node and entire straight edge must fit inside one source sidewalk polygon with strictly
more than 450 mm clearance from all its rings, all building exterior rings and district bounds.
Exact integer predicates reject crossings and tangencies, including narrow obstructions between
valid endpoints. Building courtyard holes remain conservatively blocked to match the v1
navigation policy; sidewalk holes remain unsupported. Renderers retain holes regardless of this
navigation restriction. The graph establishes simulated clearance in retained geometry, not
current real-world pedestrian access, ADA accessibility or legal entry.

Nodes carry shared subjects and positions; edges carry shared subjects, endpoint node IDs and
ceil-Euclidean `length_mm`. Destinations carry shared subjects, access node IDs and only `visit`
(one subsequent simulation tick) or `rest` (three subsequent ticks). Routing is deterministic
shortest distance with lexicographic path ties. No snapping or teleporting is permitted. Existing
first-person v1 navigation remains available independently of this narrower society envelope.

Strict validation rejects bad profiles, extra fields, digest drift, malformed rings, mismatched
feature/dataset bindings, false observation labels, unsupported recipe uses, unresolved references,
coordinate disagreement and unsafe edges. TypeScript injects a host SHA-256 function because the
core does not import DOM or Node. The host must hash exact base bytes; a reserialized object digest
is not equivalent. Parsed interpretation state is copied before asynchronous hashing and frozen.
Input without an interpretation still parses; consumers report `interpretation-unavailable`
instead of inventing routes. An empty graph reports `no-supported-connected-sidewalk`.

### Current availability and authored composition

Source dependencies bind dataset identity, revision, content digest, attribution, source URL and
the retained operation matrix. Every subject inherits the full document dependency closure,
including buildings that constrain negative space. Missing, unavailable, withdrawn or drifted
current dependencies withhold routes and interpretation materialization. An artifact's stored
rights never grant current authorization. The host rechecks authorized current availability by
exact source digest before each materialization and invalidates every dependent recipe/route after
withdrawal. A later source revision is a new input, not a silent substitution. Training and WMP
export are unsupported by this extension even when a source operation matrix is broader.

The authored adapter composes a new spatial/society input around this immutable document. It binds
the world/version, accepted edit sequence and authored state digest, immutable object identity and
origin, an explicitly registered region-to-district transform, asset/rights dependencies, reviewed
affordance assignment, enabled state and clearance geometry. A moved object changes placement and
the composed input digest, never its geographic source origin or the base district digest.

Only accepted edits can add/move/disable targets. Validate the transformed object and its access
connector against this envelope, all source obstacles and accepted authored obstacles. The shared
`districtSegmentSupported` predicate checks source clearance; the adapter must additionally check
authored geometry. Unregistered transforms, unavailable dependencies, positions off the envelope
and blocked connectors produce unavailable targets, never nearest-node snapping. Accepted edits
must remain ordered even between ticks. Restoring an earlier authored state still checks current
rights and does not undo simulation history. Persistence, adapter wiring, current-rights resolution,
Selection/Companion and shared export barrels belong to integration, not this producer. The
integration supplies PostgreSQL composition, current-rights resolution, the authenticated exact-byte
district view and a browser adapter for the registered translation-only frame. Selection,
Companion grounding and package export remain incomplete.

The same authorized input exposes canonical `visit` and `rest` targets to the society runtime.
Typed `go_to` and `perform` requests can name those target IDs through the society action API; the
server freezes the current target and the next deterministic transition records whether the request
applied. This adds no road crossing, browser-space destination, teleport or new affordance. The
browser destination list has a control that issues one typed `perform` against a selected
synthetic inhabitant and shows the returned record or an explicit unavailable or refused state;
living (v4) societies refuse it. The control is implemented and unit-tested, and no shipped
configuration reaches it: saved worlds open without this district, and the development preview
omits the control. The prerequisites are listed in
[synthetic-society-contract.md](synthetic-society-contract.md#typed-user-directed-actions).
Simulated action records are not personal evidence.

## Relationship to authored worlds

`world_alternate_environment_instance` can pin an admitted environment asset or exact indexed
feature into an alternate version with a region-local transform, source binding and availability
state. Placement changes where an admitted asset appears in an authored world; it does not rewrite
its source location.

The authored-world 1.0 package extension does not export these environment instances. The
environment-instances 1.0 extension does, without granting source-use rights or embedding
source bytes. Selection across imported geography, personal memory and authored versions
remains partial.

## Validation

Complete-district validation requires:

1. source and derived features inspectable through the world-memory contract;
2. roads, ground, facades, roofs and civic objects represented at their honest authority;
3. semantic selection, collision and navigation agreeing on shared subjects;
4. save/reload/undo and withdrawal behavior for authored placements;
5. measured street-level visual quality from live captures;
6. bounded CPU, GPU, memory, draw-call and resident-byte measurements; and
7. no use of reference-only data outside its admitted operations.

The evaluation record covers only part of this matrix and therefore does not establish
complete-district validation.


Producer verification is in `tests/test_district_interpretation.py`; the independent TypeScript
reader, shared-coordinate and clearance tests are in
`web/packages/atlas-core/test/district-interpretation.test.ts`. These verify retained-source
recompilation, prior-artifact compatibility, deterministic output, malformed and cross-bound references,
withdrawn/unresolved dependencies, supported destinations, polygon holes and whole-edge collisions.
Compiler fixtures do not establish street-level visual quality, authenticated persistence,
authored-object adapter correctness, Companion grounding or end-to-end acceptance.

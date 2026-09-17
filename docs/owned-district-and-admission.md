# Owned district and source admission

Status: **IMPLEMENTED DATA PATH; VISUAL AND WORLD-MEMORY VALIDATION IN PROGRESS**.

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

Google photorealistic tiles remain a reference-only optional visualization under the separate
provider policy. They do not supply owned-district collision, semantic identity, persistence,
extraction, model inputs, or export.

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
| `facade-grid` | Generated mass height, bay/floor spacing, window dimensions, recess and material index. Base height can be source-derived, clamped or fallback; legacy v1 cannot distinguish these cases. No observed windows or material claim. |
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
valid endpoints. Building courtyard holes remain conservatively blocked to match the old
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
Old input without an interpretation still parses; consumers report `interpretation-unavailable`
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
Selection/Companion and shared export barrels belong to integration, not this producer. The current
integration supplies PostgreSQL composition, current-rights resolution, the authenticated exact-byte
district view and a browser adapter for the registered translation-only frame. Selection,
Companion grounding and package export remain incomplete.

The same authorized input exposes canonical `visit` and `rest` targets to the society runtime.
Typed `go_to` and `perform` requests can name those target IDs through the society action API; the
server freezes the current target and the next deterministic transition records whether the request
applied. This adds no road crossing, browser-space destination, teleport or new affordance. The
current browser can inspect district destinations but does not issue directed-action requests.

## Relationship to authored worlds

`world_alternate_environment_instance` can pin an admitted environment asset or exact indexed
feature into an alternate version with a region-local transform, source binding and availability
state. Placement changes where an admitted asset appears in an authored world; it does not rewrite
its source location.

The current authored-world package extension does not export these environment instances.
Selection across imported geography, personal memory and authored versions remains partial.

## Validation

Complete-district validation requires:

1. source and derived features inspectable through the world-memory contract;
2. roads, ground, facades, roofs and civic objects represented at their honest authority;
3. semantic selection, collision and navigation agreeing on shared subjects;
4. save/reload/undo and withdrawal behavior for authored placements;
5. measured street-level visual quality from live captures;
6. bounded CPU, GPU, memory, draw-call and resident-byte measurements; and
7. no use of reference-only data outside its admitted operations.

The current evaluation record covers only part of this matrix and therefore does not establish
complete-district validation.


Producer verification is in `tests/test_district_interpretation.py`; the independent TypeScript
reader, shared-coordinate and clearance tests are in
`web/packages/atlas-core/test/district-interpretation.test.ts`. These verify retained-source
recompilation, old artifact compatibility, deterministic output, malformed and cross-bound references,
withdrawn/unresolved dependencies, supported destinations, polygon holes and whole-edge collisions.
Compiler fixtures do not establish street-level visual quality, authenticated persistence,
authored-object adapter correctness, Companion grounding or end-to-end acceptance.

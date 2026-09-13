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

The browser currently completes several of those visually with deterministic mesh-generation
rules. Those meshes are a provisional representation, not source records or validated world-memory
interpretations. In particular, the full-bounds asphalt plane is visible ground beneath other
geometry; it is not road data.

## Interpretation boundary

Future district completion uses a versioned, engine-neutral interpretation compiler. Each
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

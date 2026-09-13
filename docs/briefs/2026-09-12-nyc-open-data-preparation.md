# NYC Open Data preparation

Status: **ISSUED**
Base: `8fdd996d03ea0930d4b97b7c8cde46571e4def89`
Branch: `codex/nyc-open-data-preparation`

## Outcome

Add a pure, deterministic downloader and preprocessor for the official NYC
Building Footprints dataset over one fixed East Village and Lower East Side
hero corridor. Produce canonical, digest-addressed source shards, feature-index
inputs, checksummed manifests, and a machine-readable plan for the existing
environment admission and feature-index contracts. Commit only a small official
response fixture and records about the bounded live fetch, never the complete
city dataset.

The lane prepares semantic building identity and footprint geometry. It does not
admit bytes, publish an index, create a render asset, place a world object, or
claim a visually complete environment.

## Writable files

- `docs/briefs/2026-09-12-nyc-open-data-preparation.md`
- `docs/evaluation/2026-09-12-nyc-open-data-preparation.json`
- `docs/evaluation/artifacts/2026-09-12-nyc-open-data-preparation/**`
- `exulanica/environment/nyc_open_data.py`
- `scripts/prepare_nyc_open_data.py`
- `tests/fixtures/nyc-open-data-building-footprints.geojson`
- `tests/test_nyc_open_data.py`

No other file is writable for this task.

## Official source and fixed request

- Provider: NYC Open Data, with the Office of Technology and Innovation as the
  attributed agency.
- Dataset: `BUILDING`, dataset identifier `5zhs-2jue`.
- Dataset metadata:
  `https://data.cityofnewyork.us/api/views/5zhs-2jue`.
- GeoJSON endpoint:
  `https://data.cityofnewyork.us/resource/5zhs-2jue.geojson`.
- Primary field and quality documentation:
  `https://github.com/CityOfNewYork/nyc-geo-metadata/blob/master/Metadata/Metadata_BuildingFootprints.md`.
- Primary terms:
  `https://opendata.cityofnewyork.us/overview/#termsofuse`.
- Fixed inclusive processing bounds in longitude and latitude:
  west `-73.9930000`, south `40.7200000`, east `-73.9840000`, north
  `40.7240000`.
- Pinned candidate query: select only `the_geom`, `name`, `bin`, `doitt_id`,
  `base_bbl`, `construction_year`, `feature_code`, `geom_source`,
  `ground_elevation`, `height_roof`, `last_edited_date`, and
  `last_status_type`; filter with
  `within_box(the_geom,40.724,-73.993,40.720,-73.984)`; order by
  `doitt_id`; limit `1000`.

Metadata fetched at `2026-09-13T01:15:20Z` reported dataset row revision
`2026-09-07T15:51:52Z`. The bounded count response fetched at
`2026-09-13T01:15:21Z` reported truth last modified
`2026-09-07T15:51:51Z` and 445 rows. The pipeline must record fresh response
timestamps, revision headers, byte counts, and SHA-256 digests on every live
fetch. A changed revision or row count is visible manifest drift, not silently
the same source.

No road or named-place dataset is included. Building Footprints already supplies
the identity and geometry needed by this lane; an additional source would add a
second revision and rights surface without materially improving building
selection or the existing place binding.

## Source semantics and caveats

- GeoJSON coordinates are published as EPSG:4326. GeoJSON serialization is
  interpreted in RFC 7946 longitude, latitude order and represented to the
  environment contract as `OGC:CRS84`, axes `longitude`, `latitude`, decimal
  degrees, with integer `coordinate_scale=10000000`.
- `DOITT_ID` is the consistent OTI identifier and is the only admitted feature
  identity. Canonical `provider_feature_id` is `doitt_id:<base-10 integer>`.
- `BIN` may be duplicated and borough-million values such as `1000000` are
  explicitly unknown. It is retained as nullable source metadata and never used
  as an identity fallback.
- Missing, non-integral, non-positive, or duplicate `DOITT_ID` values are
  rejected. Records do not fall back to BIN, OBJECTID, array position, geometry
  digest, or guessed spatial matching. A duplicate `DOITT_ID` makes the entire
  input ambiguous and fails preprocessing.
- A valid non-dummy BIN is retained as `bin:<seven digits>`. Missing, malformed,
  or borough-million BIN values become null metadata. BIN collisions do not
  merge footprints.
- Footprints are top-down perimeters, not observed facades or complete objects.
  Placeholder triangles, manual geometry, estimated accuracy, duplicated BINs,
  source imagery noted by the agency, stale building names, and update-time
  changes remain explicit caveats.
- `HEIGHT_ROOF` is roof height above ground, and zero or null means unavailable.
  The primary attribute table does not state a safe output unit. Preserve the
  source decimal text as optional semantic metadata; do not extrude, convert, or
  treat it as altitude.
- Do not use `SHAPE_AREA` or `SHAPE_LENGTH`; official documentation says those
  Web Mercator-generated values are unsuitable.
- NYC Open Data disclaims completeness, accuracy, and fitness and may update or
  correct data at any time. Preserve City and OTI attribution, source links,
  retrieval time, and modification notice in every manifest.

## Required behavior

- Use standard-library HTTPS only, with no token, credential, payment, retry
  ambiguity, or unbounded request. Enforce the exact host, dataset id, selected
  fields, predicate, order, and limit above.
- Accept downloaded GeoJSON only when it is a FeatureCollection with Polygon or
  MultiPolygon features. Reject null, empty, non-finite, out-of-range,
  wrong-dimensional, unclosed, undersized, or otherwise malformed rings.
- Canonicalize Polygon and MultiPolygon geometry without repairing or guessing:
  quantize decimal longitude and latitude directly to integers at scale
  10,000,000 using decimal round-half-even; remove only consecutive duplicate
  points; require explicit ring closure; rotate each closed ring to its
  lexicographically smallest start while preserving source winding; sort
  interior rings and polygons lexicographically.
- Include a feature when its validated geometry bbox intersects the fixed
  corridor bbox inclusively. A footprint touching the boundary is included.
  Do not clip or simplify source geometry.
- Preserve source decimal fields as canonical strings where retained. Normalize
  absent values to null, reject unsupported property types, and sort features by
  `provider_feature_id`.
- Shard in sorted feature order. Start a new shard before either 512 features or
  64 MiB canonical payload bytes would be exceeded. Reject a single feature
  whose canonical payload cannot fit. Name shards by zero-based fixed-width
  ordinal and content SHA-256, so identical input creates byte-identical output
  and manifests.
- Build one source admission and at most one feature-index publication plan per
  shard. Each shard receives a distinct deterministic admission id derived from
  the provider revision, query identity, shard ordinal, and source digest. Never
  plan several current publications for one admission.
- Emit index features with official provider identity, two-dimensional integer
  bboxes, kind `building`, optional official name labels, and no invented
  `render_batch_id`. Record that publication remains gated on a separately
  admitted exact render asset.
- Verify every source, canonical shard, index input, and manifest digest and byte
  count before reporting success. Canonical JSON is UTF-8, sorted and compact,
  with one trailing newline.

## Tests and evidence

Focused pure tests cover canonical bytes, stable and rejected identities,
decimal-to-integer conversion, inclusive boundaries, malformed geometry and
properties, deterministic ordering and sharding, 512-feature and 64 MiB limits,
separate admission plans, and reproducible manifests.

Retain exact commands, test counts, formatting and import results, response
headers selected for provenance, source metadata digests, bounded response
digests, and all unexecuted gates. The committed fixture must be a small subset
of the official bounded response with its own checksum and retrieval record.

## Explicit non-scope

- No migration, repository, route, database, retained state, or API changes.
- No database writes or live admission/index publication.
- No render asset, renderer integration, `AtlasBinding`, PlayCanvas, world
  placement, Selection, Companion/NLP, WMP, or package changes.
- No commercial visual source, imagery, tile, trace, screenshot, coordinates,
  height, machine interpretation, or derivative in preprocessing.
- No Google, Apple, Cesium, Aerometrex, Hexagon, Overture, or street-view input.
- No photorealistic facade, street completeness, source-to-visual alignment,
  provider tile selection, or complete-object claim.
- No full-city download, large committed generated blob, provider write, paid
  request, vendor contact, GPU run, deployment, or public release.

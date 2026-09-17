# The generator system: `exulanica.grammar`

Status: **CITY VOCABULARY VERSION 2 BUILT; NO STAGE GENERATES ANYTHING YET**. Phase 1 of the target
architecture. Updated 2026-09-17.

`exulanica.grammar` is a generator system, not a city generator. It holds a generic contract
(grammar id and version, a closed parameter schema, a parameter cascade, a seed, an output digest
and declared semantics) and the grammars that implement it. The city is the first and largest
grammar. A second grammar, `box`, ships beside it to prove that the contract carries something
that is not architecture with no change to the contract.

This phase is structural. The package produces **no mesh and no vertices**; the only generated
values are the box grammar's three integer extents. City version 2 declares the whole vocabulary a
generator will write: 27 record kinds with integer geometry, 69 declared parameters, four
projection contracts, 18 licensed catalogs, one identity rule and a hand-written fixture tile that
exercises all of it. No city stage has a generator: a city generated today is a receipt and eleven
emissions that each say `not_implemented` and why.

## 1. Where it sits, and why below `evidence`

The exhaustive import-linter layer list in `pyproject.toml` now reads, from `reconstruction`
down:

```text
reconstruction | capture
evidence | migrations
grammar
canonical
corpus | errors
env
```

A layers contract permits imports downward only, so `exulanica.grammar` may import
`exulanica.canonical`, `exulanica.errors` and `exulanica.env` and nothing else in this
repository. That is the arrangement `exulanica.reconstruction` already has, one notch stricter:
reconstruction sits above `evidence` and is kept away from it by a forbidden contract alone, while
the generator system sits below it and could not import it even without one.

No existing package moved. `capture` is a new sibling of `reconstruction`, placed at the request
of the lane that owns it; siblings may not import each other.

## 2. What the contracts prevent

Two forbidden contracts name `exulanica.grammar`.

**Generated content cannot name a citation, because it cannot name one.** The forbidden modules
are `exulanica.evidence`, `exulanica.store`, `exulanica.db`, `exulanica.ingest`,
`exulanica.identity` and `exulanica.selection`. A generator that does not import the module that
defines an evidence address cannot construct one, cannot register a blob a span could point at,
cannot open the database, cannot reach the pipeline that admits a photograph, cannot name a
person, and cannot reach the selector that binds cited content for a model. This is the strongest
available form of [ADR-0008](adr/0008-generated-geometry.md) compliance: a synthetic city
structurally cannot pass for evidence.

What it deliberately does not claim: every module it names already sits above `grammar`, so the
layers contract alone refuses those imports today, and this contract is the one that survives a
future move of the layer. It says nothing about how generated content is labelled once something
above composes it with recorded content; that is the `invented` plane's job (section 9).

**The pure core does not know a database exists.** `exulanica.grammar` is now listed there too,
so a direct `psycopg` import fails as well. A generated world is recomputable on a machine that
has never seen a database.

`tests/test_grammar_layering.py` makes both contracts fail on purpose. For each forbidden name it
writes a module `exulanica/grammar/_negative_control_<name>.py` containing one import, runs
`lint-imports --no-cache`, asserts a non-zero exit and asserts the contract is reported
`BROKEN`, then deletes the module. A companion test fails if any file with that prefix exists,
tracked or not. An AST test fails if any module names `EvidenceAddress`, `BlobId`,
`span_digest`, `evidence_span` or `TimeInterval`, even in a string.

## 3. The generic contract, and adding a grammar

| Module | What it holds |
| --- | --- |
| `seed.py` | The seed validator |
| `draw.py` | `_number`, bounded draws, `DomainCursor` |
| `records.py` | The canonical form of a record, and field checks |
| `parameters.py` | The closed parameter schema, declared parameters, the cascade and `require_parameter_bindings` |
| `contract.py` | `Grammar`, stages, `StageEmission`, `GrammarReceipt`, `generate`, descriptor schema 2 (frame, stage declarations, projection contracts) and `ParameterSurface` |
| `shapes.py` | `RecordShape` and `FieldShape`: every field of a record kind declared once, as data; `validate_record`, `read_record`, `describe_shapes`, and the reference, identity and vocabulary checks across a set of records |
| `geometry.py` | Exact integer rings, extents, point and ring relations, `integer_sqrt` and the floored centroid |
| `subjects.py` | The one subject identity rule |
| `migration.py` | `ParameterMigration` between two versions of a grammar, and `migrate_chain` |
| `registry.py` | `GrammarRegistry`, empty by default |
| `catalogs.py` | The versioned, licensed catalog loader and `catalog_digest` |
| `textures.py` | The reader for the texture lane's manifest, and the pin a texture set carries |
| `documents.py` | Strict JSON reading for every data file |
| `grammars/` | The grammars, and `builtin_registry()`, the one place that names them |

Nothing outside `grammars/` imports anything inside it, and no city word (street, parcel,
facade, kerb, building, storey, roof and the rest) appears in the code of the generic modules.
Both are tested.

A grammar is a descriptor file named `<grammar_id>.v<version>.json` and a tuple of stages written
in code. Adding one is a new module under `grammars/` and one `register` line in
`builtin_registry()`. A test builds a tree grammar from scratch, registers it, and runs it, with
nothing else changed.

**Descriptor schema 1** states identity, subject kind, admissible uses, cascade levels and
parameters; the box uses it. **Schema 2** adds what the code is then held to:

- `frame`: the coordinate frame and its metric class. A grammar on the `invented` plane may not
  claim `metric_measured`.
- `stages`: every stage id and version in order, and the record kinds and versions each stage's
  validators take. A mismatch with the code is refused.
- declared `parameters`: each with its unit, cascade level, the one stage that reads it, the
  vocabulary a choice's options come from, and the basis of its range. An unset parameter is
  `draw`, `required` or `derive`; there is no default value. A binding may set a parameter at its
  own level or a coarser one, never finer.
- `projections`: one representation contract per admitted projection, with what it preserves and
  what it does not as separate rows, and one verdict for each use. A preserved property a
  consumer builds to by number (`PROPERTY_MEASURES`) states its integer measures as data, and no
  other row states any. A projection admits its own use. **No contract may admit `personal_world` or `citation`**; lifting either is a code change
  in `contract.py`, not a descriptor edit.

`generate(grammar, seed=..., subject_identity=..., bindings=...)` runs the stages in order,
validates every record with its stage's validator, refuses any float through canonical JSON, and
returns a `GrammarReceipt` beside the emissions. The receipt carries the six facts
[world-memory-model.md](world-memory-model.md) section 5.1 requires of a durable procedural
record: the admitted subject identity, the grammar id and version, the resolved parameters with
where each came from, the seed, the output digest, and the declared semantics. The declared plane
is always `invented`, and it is a field of every receipt.

**A stage with no implementation emits nothing and says so.** `UnimplementedStage` returns a
`not_implemented` emission with a reason and no records. `StageEmission` refuses records on a
`not_implemented` emission and refuses one with no reason.

**Subject identity** is one rule for every generated subject a person can point at:

```text
identity = uuid5(SUBJECT_NAMESPACE, canonical_json([
    "exulanica.grammar.subject/v1", grammar_id, root_identity,
    subject_kind, owner_identity, ordinal,
]))
```

`SUBJECT_NAMESPACE` is `uuid5(NAMESPACE_URL, "https://exulanica.invalid/grammar/subject")`.
`root_identity` is the admitted identity of the subject the generation is for, which reaches every
stage as `StageContext.subject_identity`; a stage derives with `context.identity(kind, owner,
ordinal)`. **Neither the seed nor the grammar version is in the tuple**, so an identity survives a
reseed and a version bump. A version that assigns `(kind, owner, ordinal)` to other subjects than
its predecessor did must say so in its migration's identity policy (`preserved`, `rekeyed` or
`introduced`). What a pinned subject keeps across a reseed belongs to the edit log, not here.

**Parameter migrations.** A grammar version after the first ships
`<grammar_id>-migration.v<target>.json`. `ParameterMigration` holds it to both parameter surfaces:
every source parameter is carried, mapped or removed exactly once and every target parameter
carried, mapped or introduced exactly once; a carried integer is `value * multiply + add` with
`multiply >= 1` and its whole source range landing in the target range; a mapped choice maps every
option; the level map keeps order and never merges levels; a binding that sets a removed
parameter comes back in `dropped` with the removal's reason. A retired version keeps its
descriptor as the migration's source surface, read without stage code by `ParameterSurface`.

## 4. The draw

```text
_number(seed, domain, ordinal)
    = int.from_bytes(sha256(f"{seed}:{domain}:{ordinal}".encode()).digest()[:8], "big")
```

**Domain namespacing is the rule.** A draw depends on its seed, its domain and its ordinal and on
nothing else. There is no shared stream, so adding a stage, or new draws under a new domain,
never moves a value an earlier stage produced. Inside a grammar a stage draws through
`context.cursor(name)`, whose domain is `<grammar_id>.<stage_id>.<name>`, so two stages and two
grammars never share a namespace. An unset parameter is drawn in
`<grammar_id>.parameters.<name>` at ordinal 0.

A domain is lowercase ASCII words joined by dots, with no colon, so the preimage splits one way.
An ordinal is a non-negative `int` and exactly an `int`; `True` is refused because it formats as
`True`.

A bounded draw is `minimum + (n * span >> 64)`, exact integer arithmetic, with spans capped at
`2**32` so the largest relative bias stays below one part in four billion. A raw 64-bit draw is
larger than a JavaScript number holds exactly, so it is never written into a record; bound it
first.

Tested: a pinned known answer, the formula re-derived, a domain's sequence unchanged with
another domain interleaved, an earlier stage's emission byte-identical when stages are added
before and after it, and the whole emitted set digested identically by two interpreter processes
with different `PYTHONHASHSEED` values.

## 5. The seed

Exactly 64 lowercase hexadecimal characters, as a `str`. Uppercase is refused rather than folded,
an `int` is refused rather than formatted, and non-ASCII digits are refused. `generate` has no
default seed, and the package has no clock, no `random` and no `secrets`, so it cannot make one
up. An AST scan over the whole package enforces that, together with no float literal, no `float`
name, no true division, no power operator, no `hash()` or `id()`, no environment read, and no
JSON parse that does not refuse floats. The scan's own detector is tested against planted
violations.

## 6. Records

A record is a frozen dataclass of `int`, `str`, tuples and nested records, with a declared kind
and version. `bool`, `None`, lists and mappings are refused. A float is passed to
`exulanica.canonical.canonical_json` untouched so that its refusal, `CanonicalisationError`, is
the one that fires. Integers are bounded to what a double holds exactly, because the TypeScript
tessellator will read the same records. Quantise first: millimetres, microradians, millionths.

A grammar with many record kinds declares each one as a `RecordShape`, data rather than code:
every field in dataclass order with its kind, integer bounds, closed values, counts, the record
kinds an identity field may refer to and the catalog a key resolves in, plus named rules across
fields, the identity rule and the extent field. One validator reads the shape, one reader turns a
payload back into a record and refuses a missing or unknown field at any depth, and
`describe_shapes` writes the table as plain JSON so a reader in another language compares itself
with the shapes rather than with a transcription.

Tested: canonical JSON accepts the whole emitted set, and a float placed at every position of it,
or added to every container in it, raises `CanonicalisationError`, for six different floats
including `nan` and `-0.0`. Every record validator raises `CanonicalisationError` for a float in
any field. For every city record kind and every nested shape, generated from the shapes and
applied to fixture records: a missing and an extra field, a float, `bool`, `None` and a list in
every field, a string for an integer and an integer for a string, one past every declared bound
and count, and a case for each of the 36 named rules in which that rule, and no field check or
other rule, refuses (`tests/test_grammar_city_records.py`).

## 7. The city stages

City version 2 is registered; version 1 is retired, and its descriptor stays beside the new one as
the source of the version 1 to 2 migration.

| Stage | Version | Record kinds | Parameters | Generator |
| --- | --- | --- | --- | --- |
| `terrain` | 2 | `city.terrain` | 2 | none |
| `districts` | 1 | `city.district` | 1 | none |
| `streets` | 2 | `city.street_node`, `city.street`, `city.street_segment`, `city.block`, `city.curb_edge`, `city.crossing`, `city.lane`, `city.junction`, `city.junction_approach`, `city.lane_connection`, `city.signal`, `city.parking_space`, `city.road_marking` | 11 | none |
| `parcels` | 2 | `city.parcel` | 4 | none |
| `massing` | 2 | `city.massing`, `city.rooftop_object` | 13 | none |
| `facade` | 2 | `city.facade`, `city.ground_bay`, `city.entrance` | 22 | none |
| `material` | 2 | `city.surface_material` | 5 | none |
| `streetlife` | 2 | `city.street_furniture`, `city.street_tree` | 5 | none |
| `vitrine` | 2 | `city.vitrine` | 3 | none |
| `premises` | 2 | `city.premises` | 3 | none |
| `tile` | 2 | `city.tile` | 0 | none |

The record shapes are in `exulanica/grammar/grammars/city/` (`common.py` holds what every record
shares), and `tests/fixtures/city-v2/record-shapes.json` is the whole table as data.

**Records carry integer geometry sufficient for a deterministic tessellation.** Everything a
tessellator would otherwise guess is a field: rings, centrelines and kerb lines with elevations,
extents, carriageway and footway widths, camber and crossfall, corner radii, crossing bands, lane
centrelines with stop lines and connections, parcel frontages, building tiers with their rings,
light wells, parapets and ridge, facade bay layouts, opening grids, mouldings, ground panels,
awnings and entrances, object parts for furniture, trees, rooftop plant and vitrine fitouts, and
texture coordinates. The frame is `city_local`: x east, y north, z up, integer millimetres,
`metric_authored`. A direction is an integer vector, never an angle. The rules for surface frames,
stop lines, frontage lines, the camber profile and texture coordinates are written in the module
docstrings and are the contract the tessellator reads.

**Catalog keys are labels.** No reader draws a shape from a key: a furniture class's parts, a roof
family's form and a material's texture set are resolved into the record that uses them.

**The target architecture's bounds** are checked on every record and pinned by number in tests:
kerb height 100 to 180 mm, vitrine depth 600 to 1500 mm, ground band 4000 to 6000 mm, reveal 120 to
250 mm, string course 60 to 200 mm, cornice 400 to 900 mm, and bay pitch 2400 to 3500 mm as a
declared face parameter. `city.facade` carries the six section 5.1 fields first, by name, and states
every parameter the facade stage reads with its value and source.

**Parameters.** 69 are declared, at the cascade levels city (2), district (7), block (13), lot (1),
building (20) and face (26). All but one are `derive`: the reading stage derives a value per
subject and the record states it. `driving_side` is `required`, because the side of the road is a
convention a world states and nothing chooses silently. Every choice with a vocabulary offers
exactly that catalog's keys (`wall_material` offers exactly the materials that dress a wall), and
a test holds them equal.

**Projections.** The descriptor admits `render_batch`, `collision_proxy`, `nav_envelope` and
`pick_geometry`. Each contract admits its own use and `evaluation` and refuses every other use,
including `personal_world` and `citation`; each preserves `subject_identity`. The nav envelope's
`capsule_clearance` row carries its capsule as numbers, `radius_mm` 340, `height_mm` 1900 and
`eye_height_mm` 1620, so the tessellator carves for the numbers rather than for a sentence; a
test holds them equal to the visual gate's thresholds.

**Identity.** Every subject record's identity follows section 3's rule over the owner and ordinal
its shape declares, with append-only codes where an ordinal stands for a side or a surface role.
The identity policy of the version 1 to 2 migration is `introduced`: version 1 derived none.

**The version 1 to 2 migration is vacuous, and says so.** Version 1 declared no parameters, so
every version 2 parameter is `introduced`. It is tested: total over both surfaces, empty bindings
at every level carry across, and a version 1 binding that names any parameter is refused. The
machinery itself is tested on probe grammars (carried, mapped, removed, introduced, a chain from
version 1 to 3, and every refusal).

**The tile document** (`exulanica.tile-document/v2`, `document.py`) is one tile's records as a bake
reads them: canonical JSON of the tile record, and per grammar its descriptor digest, declared
semantics, the admitted city identity, and the owned and halo records, each list sorted. A tile
pins each grammar by the SHA-256 of its descriptor file, and a test pins every shipped
descriptor's digest per version. `validate_city_document` runs every record's own validator and
the envelope checks, then everything that spans records: references resolve to admitted kinds,
identities are their rule's derivation, catalog keys resolve and mean what the record says,
geometry agrees across records (frontage lines, camber, stop lines, connections, parking, parcels
in blocks, footprints in parcels, facade runs, bays, entrances, vitrines behind glazing), membership
matches the tile's rules, and the pins match what was loaded. Each refusal names its check in
brackets.

**Membership.** A tile owns a subject whose anchor (a parcel's centroid, a node's point, a
segment's node midpoint, shared down to everything the subject owns) lies in its 128 m square. A
subject it does not own is in its halo when the subject's extent meets the square grown by 64 m on
every side (`extent_meets_grown_square`), so a long segment or a large parcel anchored far away
that still crosses the tile is carried. A record with no extent (a surface material, a junction
approach, a signal) goes with the record it relates to. Owned and halo never overlap.

**The fixture**, `tests/fixtures/city-v2/tile-document.json`, is written by hand in
`build_fixture.py`: one signalised T-junction, a memory precinct lot and a four-storey shophouse
with a chamfered corner, a set-back top storey, a light well, a bakery, a bookshop and flats, lanes,
parking, cycle stands, paint, a lamp, a bench, signal poles and a London plane. Every record kind
is present with real catalog keys, and it validates completely: 1 building with every facade, 4 of
4 bayed frontage faces in the 2.4 to 3.5 m band, kerb 150 mm, no object inside a footprint, and 81
surface materials, each with a texture set. Glazing, doors, road markings and the tree have no
published texture set and are reported as unavailable surfaces. Its bytes are pinned by SHA-256,
and 21 mutations are each refused by the check they name.

## 8. Catalogs

Versioned JSON files under `assets/catalogs`, one per catalog, named
`<catalog_id>.v<version>.json`, with the envelope `schema_version`, `catalog_id`,
`catalog_version`, `entries`, following `exulanica/world/style-registry.v1.json`. The loader
refuses a name that disagrees with the contents, an unknown or missing key at any level, a
repeated key inside one JSON object, a repeated entry key, any float, `NaN` and `Infinity`.
`catalog_digest` is SHA-256 over the canonical JSON of every catalog, ordered by id.

**Every entry carries a licence**, stated the way [license-matrix.md](license-matrix.md) states
one: `spdx`, `verdict`, `origin`, `licence_source` and `content_source`. Only `SHIP` and
`SHIP-ATTRIB` are accepted. An `original` entry is authored in this repository, is `Apache-2.0`,
and names `LICENSE` as the licence it was read from. A `derived` entry names its real source's
licence and may not cite `LICENSE`.

**A material entry must name a published texture set.** The texture set id contract was fixed
with the orchestrator on 2026-09-16, before the texture lane started:

- An id matches `^[a-z][a-z0-9.-]*$`, the rule an authored-world asset key already follows, by
  convention `<licence>.<name>`. It is a stable name and never contains a version or a digest.
  Both the material catalog and `SurfaceMaterialRecord` check it.
- The texture lane publishes `assets/textures/manifest.json` as
  `{"profile": "exulanica.texture-manifest/v1", "sets": [...]}`, with `sets` sorted by `set_id`,
  each id once, and each entry carrying exactly `set_id`, `version`, `content_sha256`,
  `byte_size`, `resolution`, `channels`, `extent_mm`, `licence_id` and `licence_sha256`.
  `read_texture_manifest` refuses anything else, and refuses a missing file rather than reading
  it as empty. It reads through `exulanica.materials.manifest`, the one rule every reader of the
  manifest shares, so the file must also be canonical JSON and each field must have the form
  `docs/texture-package.md` section 8 gives.
- **A resolved reference carries a pin into the digest.** A catalog file and a material record
  hold the id alone. When the loader resolves an id, it records the set's `set_id`, `version`
  and `content_sha256` beside the entry, and `catalog_digest` covers them. A rebaked set moves
  the catalog digest, and so every tile digest built on it, with the catalog file byte-identical;
  a set no entry uses moves nothing. Both are tested with fixture manifests.

`load_city_catalogs` reads the published manifest by default, strictly: a missing or malformed
manifest is refused, never read as empty.

**Every entry states why it exists.** Authored vocabulary (every catalog below except material,
tree species, and `band` and `action-vocabulary`, whose version 1 schemas predate the field) says
it is authored and why. A material names the texture set it depicts and reads
its course and mortar modules from that set's recipe object, which its `content_source` names. A
derived entry names the retained source it was derived from and the rule. Where an authored street
dimension cites a well-known guide, the guide is named by title and edition and marked as not
re-read; the value is this grammar's own.

**Across catalogs**, `check_city_catalogs` refuses an era wall material that dresses no wall, a
typology use, era or roof family, a fitout use class or a street-name hierarchy that does not
exist, a sign for a use class that takes none, and a signed use class with no sign.

| File | Entries | What it holds |
| --- | --- | --- |
| `action-vocabulary.v1.json` | 0 | The architecture names a closed action vocabulary for lenses and does not enumerate it. |
| `band.v1.json` | 1 | The ground band, from the target below. |
| `crossing-type.v1.json` | 3 | Raised table, signalised and zebra: kerb treatment, marking, signal and width range. |
| `era.v1.json` | 4 | Prewar masonry, interwar, postwar and contemporary: wall materials, roof families, storey heights and cornice. |
| `fitout.v1.json` | 7 | Vitrine fitout units as explicit parts, with the use classes each dresses. |
| `junction-control.v1.json` | 4 | Right-of-way classes; the keys equal the traffic lane's right-of-way policy keys. |
| `lane-use.v1.json` | 5 | General, bus, cycle, parking and buffer, with width ranges; traffic maps them to vehicle classes. |
| `material.v2.json` | 8 | One material per pinned texture set, with the surface roles it dresses and its baked modules. |
| `parking-kind.v1.json` | 5 | General, loading, accessible, bus layover and cycle stand, with placement and size. |
| `roof-family.v2.json` | 3 | Flat with parapet, flat with eaves, and gable: form, rise, parapet and rooftop objects. |
| `rooftop-object.v1.json` | 4 | HVAC unit, water tank, lift overrun and stair bulkhead as explicit parts. |
| `signage-lexicon.v2.json` | 18 | Generic descriptors ("Bakery", "Books") for the signed use classes; never a brand or business name. |
| `street-furniture.v1.json` | 9 | Lamps, benches, bins, bollards, hydrants, cycle stands, signal poles and sign posts as explicit parts, with exclusion radius and kerb offsets. |
| `street-hierarchy.v2.json` | 4 | Avenue, high street, local street and narrow street, with lane, width, speed and kerb ranges. |
| `street-name.v1.json` | 12 | Generic street names and the hierarchies each suits. Presentation, never identity. |
| `tree-species.v2.json` | 19 | Derived from the 2015 NYC Street Tree Census: each named species of at least one percent of the named trees. |
| `typology.v2.json` | 7 | Building types: storeys, frontage, attachment, ground and upper floor uses, eras and roof families. |
| `use-class.v1.json` | 11 | Exactly the living society lane's use-class keys; it maps them to roles through its own catalog. |

**The tree census source** is retained unchanged at
`assets/catalogs/sources/nyc-2015-street-tree-census-species.json`, SHA-256
`68865bbbfdbcff42ce2492eadb218313e20c5f54845e7a4cac93885873b3ae15`, with a provenance file beside
it. It came from one approved GET on 2026-09-17. A test re-derives every tree species entry from
those bytes, and the source is listed with its attribution, terms and modifications in the shipped
data section of `THIRD_PARTY_NOTICES.md`.

**The ground band entry** is transcribed from the target stated in the dated 2026-09-15
target-architecture brief, which the operator authored: a ground band from grade to a top edge
between 4.0 and 6.0 m, carrying a stall riser, glazing, a transom, a recessed entrance, a
threshold, a fascia, an awning, and a lit vitrine behind the glass. It is recorded as
`top_minimum_mm` 4000, `top_maximum_mm` 6000, and those eight elements. The same brief also names
string courses of 60 to 200 mm and cornices of 400 to 900 mm. Version 2 reads those as the height
of one string course and the total height of a cornice's stack of mouldings, declares them as face
parameters and checks them on every facade record (section 7), rather than in this catalog. The
reading of "band" as a horizontal facade band is this document's interpretation of the brief's
vocabulary list.

## 9. The `invented` truth class

`exulanica.selection.packet.build_content_packet` now maps `origin_kind` `invented` to the truth
class `invented_world`, so generated content never reaches a model as `other`, and `other` still
means an origin the map does not know. `tests/test_selection_packet_invented.py` pins both.

## 10. Open gaps

Each of these is known and deliberately not done here.

- **No stage has a generator.** The corridor lane writes them against these record shapes,
  parameters and catalogs.
- **The city v1 consumers have not been ported.** The tessellator's bake stage and its fixture,
  the living society's city place adapter and the traffic lane's provisional records read city v1
  record classes. The tessellator lane ports on a branch stacked on this one and both merge
  together; the society and traffic lanes port before they merge.
- **Texture gaps.** No published texture set is glazing, a door, road paint, terrain, a tree pit,
  foliage, bark, timber, fabric or a sign panel, so those surfaces have no material record and
  draw as unavailable. They are queued with the texture lane.
- **`READ_ONLY_TABLES` registration.** Catalogs are meant to be registered in
  `exulanica/db/roles.py` so a runtime process may propose a registered value and never register
  one. They ship as data files and are not in any table.
- **The catalog table migration.** Migration number `0064` stays reserved and is not written.
- **Catalogs are not in the wheel.** The directory is found relative to the source file, which
  works in a checkout. Tiles are baked offline from a checkout; an installed service would need
  the files packaged.
- **The edit subsequence digest.** `city.tile` carries `edit_delta_digest` and the empty
  subsequence has its one encoding, but how a non-empty subsequence is digested belongs to the
  edit log, which does not exist yet. What a pinned subject keeps across a reseed is the edit
  log's decision too.
- **Root identity minting.** Every generated identity derives from the admitted city identity.
  Nothing here mints that root.
- **Signal durations.** A signal record carries the traffic lane's plan key and the SHA-256 of
  the plan catalog it was generated against, never a duration. The plan catalog is the traffic
  lane's and is re-checked when that lane merges.
- **Street dimensions** are authored values citing well-known guides that were not re-read in
  this build.
- **`objects_inside_footprints`** in the document report is 0 whenever a report exists: an object
  inside a footprint is refused by `[footprint_intersection]` rather than counted.
- **Content answers.** `render_content_answer` in `exulanica/selection/question.py` has no clause
  for invented content and would describe it as authorized related content. That file is outside
  this lane.
- **The truth-class table in [world-memory-model.md](world-memory-model.md) section 3.1** lists
  four current values and does not yet list `invented_world`. That document is outside this lane.
- **Reachability.** Nothing here makes a generated world reachable from any person's atlas. The
  superseding ADR comes first.

# The generator system: `exulanica.grammar`

Status: **STRUCTURE BUILT; NO STAGE GENERATES ANYTHING YET**. Phase 1 of the target architecture.
Updated 2026-09-16.

`exulanica.grammar` is a generator system, not a city generator. It holds a generic contract
(grammar id and version, a closed parameter schema, a parameter cascade, a seed, an output digest
and declared semantics) and the grammars that implement it. The city is the first and largest
grammar. A second grammar, `box`, ships beside it to prove that the contract carries something
that is not architecture with no change to the contract.

This phase is structural. The package produces **no mesh and no vertices**; the only generated
values are the box grammar's three integer extents. Every city stage has a versioned record shape
and a validator, and none has a generator: a city generated today is a receipt and ten emissions
that each say `not_implemented` and why.

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
above composes it with recorded content; that is the `invented` plane's job (section 8).

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
| `parameters.py` | The closed parameter schema and the cascade |
| `contract.py` | `Grammar`, stages, `StageEmission`, `GrammarReceipt`, `generate` |
| `registry.py` | `GrammarRegistry`, empty by default |
| `catalogs.py` | The versioned, licensed catalog loader and `catalog_digest` |
| `textures.py` | The reader for the texture lane's manifest, and the pin a texture set carries |
| `documents.py` | Strict JSON reading for every data file |
| `grammars/` | The grammars, and `builtin_registry()`, the one place that names them |

Nothing outside `grammars/` imports anything inside it, and no city word (street, parcel,
facade, kerb, building, storey, roof and the rest) appears in the code of the generic modules.
Both are tested.

A grammar is a descriptor file named `<grammar_id>.v<version>.json` (identity, subject kind,
admissible uses, cascade levels, parameters) and a tuple of stages written in code. Adding one is
a new module under `grammars/` and one `register` line in `builtin_registry()`. A test builds a
tree grammar from scratch, registers it, and runs it, with nothing else changed.

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

Tested: canonical JSON accepts the whole emitted set, and a float placed at every position of it,
or added to every container in it, raises `CanonicalisationError`, for six different floats
including `nan` and `-0.0`. Every record validator raises `CanonicalisationError` for a float in
any field.

## 7. The city stages

| Stage | Version | Record shapes | Generator |
| --- | --- | --- | --- |
| `terrain` | 1 | `TerrainRecord` | none |
| `streets` | 1 | `StreetNodeRecord`, `StreetSegmentRecord`, `CurbEdgeRecord` | none |
| `parcels` | 1 | `ParcelRecord` | none |
| `massing` | 1 | `MassingRecord` | none |
| `facade` | 1 | `FacadeRecord` | none |
| `material` | 1 | `SurfaceMaterialRecord` | none |
| `streetlife` | 1 | `StreetFurnitureRecord` | none |
| `vitrine` | 1 | `VitrineRecord` | none |
| `premises` | 1 | `PremisesRecord` | none |
| `tile` | 1 | `TileRecord` | none |

Validators check the bounds the target architecture states: kerb height 100 to 180 mm on every
street segment, vitrine depth 600 to 1500 mm, a tile of 128 m with a 64 m halo, a texture set
on every surface material. `FacadeRecord` carries the six section 5.1 fields by name:
`building_identity`, `grammar_version`, `parameters`, `seed`, `output_digest`,
`declared_semantics`, plus the edge it faces.

The city's cascade is city, district, block, lot, building, face. Its parameter schema is empty,
because no implemented stage reads a parameter. Its declared semantics admit it to no projection.

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

The caller passes the published sets and there is no default. No manifest exists yet, so the
only honest argument today is an empty mapping, and any material entry is refused. That is the
intended behaviour.

| File | Entries | Why |
| --- | --- | --- |
| `action-vocabulary.v1.json` | 0 | The architecture names a closed action vocabulary for lenses and does not enumerate it. |
| `band.v1.json` | 1 | The ground band, from the target below. |
| `material.v1.json` | 0 | No texture set is published, and a material without one is a schema error. |
| `roof-family.v1.json` | 0 | The architecture names roof families and enumerates none. |
| `signage-lexicon.v1.json` | 0 | The architecture names a seeded lexicon and gives no strings. |
| `street-hierarchy.v1.json` | 0 | The architecture names a hierarchy and gives no classes. |
| `tree-species.v1.json` | 0 | A species list is a fact about the world that needs a read source, and none was read. |
| `typology.v1.json` | 0 | The architecture names typologies and enumerates none. |

An empty catalog is deliberate. Entries are art direction for the operator, not a gap to be
filled by whoever builds the loader, and six plausible names would be exactly the invented
vocabulary this build exists to remove.

**The ground band entry** is transcribed from the target stated in the dated 2026-09-15
target-architecture brief, which the operator authored: a ground band from grade to a top edge
between 4.0 and 6.0 m, carrying a stall riser, glazing, a transom, a recessed entrance, a
threshold, a fascia, an awning, and a lit vitrine behind the glass. It is recorded as
`top_minimum_mm` 4000, `top_maximum_mm` 6000, and those eight elements. The same brief also names
string courses of 60 to 200 mm and cornices of 400 to 900 mm, but does not say which dimension
those figures measure, so they were not recorded. The reading of "band" as a horizontal facade
band is this document's interpretation of the brief's vocabulary list.

## 9. The `invented` truth class

`exulanica.selection.packet.build_content_packet` now maps `origin_kind` `invented` to the truth
class `invented_world`, so generated content never reaches a model as `other`, and `other` still
means an origin the map does not know. `tests/test_selection_packet_invented.py` pins both.

## 10. Open gaps

Each of these is known and deliberately not done here.

- **`READ_ONLY_TABLES` registration.** Catalogs are meant to be registered in
  `exulanica/db/roles.py` so a runtime process may propose a registered value and never register
  one. That file is outside this lane and is being changed elsewhere, so catalogs ship as data
  files first and are not in any table.
- **The catalog table migration.** Migration number `0064` is reserved for it and is not written.
- **Texture sets.** The id rule and manifest shape are agreed (section 8) and the reader exists,
  but no manifest has been published, so nothing reads one by default and the material catalog
  is empty. When the texture lane's manifest lands, the city catalog loader should read it
  instead of taking the sets from its caller.
- **Seven empty catalogs** (section 8), waiting on art direction.
- **No stage has a generator.** Phase 2 builds six of them for one corridor.
- **No deterministic `StageSpec` is registered.** That registration belongs in
  `exulanica/ingest/stages/`, reserved for the tessellator lane in phase 2.
- **Catalogs are not in the wheel.** The directory is found relative to the source file, which
  works in a checkout. Tiles are baked offline from a checkout in phase 2; an installed service
  would need the files packaged.
- **The edit subsequence digest.** `TileRecord` carries `edit_delta_digest` and
  `tile_inputs_digest` covers it, but how it is computed belongs to the edit log, which does not
  exist yet.
- **Parameter migrations.** No grammar has a version 2, so no vN to vN+1 migration exists.
- **Subject identity minting.** A receipt requires a canonical UUID supplied by whoever admitted
  the subject. Nothing here mints one.
- **Content answers.** `render_content_answer` in `exulanica/selection/question.py` has no clause
  for invented content and would describe it as authorized related content. That file is outside
  this lane.
- **The truth-class table in [world-memory-model.md](world-memory-model.md) section 3.1** lists
  four current values and does not yet list `invented_world`. That document is outside this lane.
- **Reachability.** Nothing here makes a generated world reachable from any person's atlas. The
  superseding ADR comes first.

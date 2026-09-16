# Texture package

Status: IMPLEMENTED for eight baked texture sets, their container, the manifest, migration 0065, the
backend resolver, and the recipes, makers and object store the sets are baked from. The appearance of these sets in the rendered product is UNVERIFIED: no
renderer draws them yet, and that check belongs to the corridor lane, against the gate lane's
Flatiron baseline.

The plan names what shipped and what this package replaces, and both sentences are quoted
verbatim:

> "Seven flat hex fills by `doitt_id % 7`; zero texture, no UV channel, no texture field in the schema"

> "A real texture package, six to ten seeded tiling channel-packed sets, baked offline,
> content-addressed, digest-pinned by a migration exactly as `assets.py` pins GLB bytes, and baked
> in milestone 1."

The implementation is `web/packages/loom-texture` (the makers and the offline bake), its `library/`
(one recipe file per published set), `assets/textures/` (the published sets, objects and indexes),
`exulanica/materials/` (the backend's checks on recipes, manifests and the catalog),
`exulanica/world/texture_assets.py` (the backend reader and resolver) and
`exulanica/migrations/0065_texture_set_digests.sql` (the pins).

## 1. The sets

Eight sets, named by the surface a street draws. Deciding which building gets which surface is the
grammar's material stage, so no set is named after an era, a typology or a height class.

| Set | Version | Surface | Texels | Extent (mm) | Height range (mm) | Seed | content_sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cc0.brick-running-bond` | 1 | vertical | 1024 x 1024 | 1800 x 1800 | 12 | 2026091601 | `91791b17a705e45919e38aa42f2dacba961f01c51675efa443bf4a1934650499` |
| `cc0.carriageway-asphalt` | 1 | horizontal | 1024 x 1024 | 2000 x 2000 | 6 | 2026091606 | `3ed5d23aa14dac2f373cc834c6e98dacf6abcc9b2a484580db6e169b1e280a78` |
| `cc0.cast-concrete` | 1 | vertical | 1024 x 1024 | 2400 x 2400 | 12 | 2026091604 | `e2903a77e5841cd5b97d788fb503e8d2faf3fdd09b5eb62ab062e1ded6223c43` |
| `cc0.footway-paving` | 1 | horizontal | 1024 x 1024 | 1800 x 1800 | 8 | 2026091607 | `3c0df2400f0eae3e7a7f6440217762f8eb51e7e7f2c4f8e4f2ebe2919e0707ef` |
| `cc0.kerb-stone` | 1 | horizontal | 1024 x 256 | 1800 x 450 | 6 | 2026091608 | `495906d226fb50f827afa0f9b55e386be65adb53e4c2e1fac8a92188f9355bb3` |
| `cc0.limestone-ashlar` | 1 | vertical | 1024 x 1024 | 2400 x 2400 | 8 | 2026091602 | `4d7b009dcf2280b1ecff7febc97da6ee584211983d85e5399fe7dfb78d73b60b` |
| `cc0.painted-render` | 1 | vertical | 1024 x 1024 | 2000 x 2000 | 4 | 2026091603 | `986e2119f33818d7cacf368a7a70fa22766bc9a1922eea35a46c3590ef43ac6d` |
| `cc0.storefront-metal` | 1 | vertical | 1024 x 1024 | 1000 x 1000 | 1 | 2026091605 | `7178431b117baaef8b2b6de2416631539237bda296a00bb3305071397fb9b41a` |

Every set is CC0-1.0. The dedication is its own blob, referenced by digest
`d51d213f1f5d94acb27403d616b29007802618979c106b075fdbd399fa86310f`, the way
`exulanica/world/assets.py` references the dedication for its meshes. The sets are generated from
hashed integers by source in this repository, with no photograph, scan, sample library or model
output anywhere near the bake, which is what makes CC0 a claim this project can make.

Each set's full recipe is `web/packages/loom-texture/library/<set_id>.json` (section 2). The module
each set is built on is also stated in its header under `parameters`, in whole millimetres (or 1/1024
mm where a half-module offset is not a whole millimetre):

- **Brick, running bond.** 215 x 65 mm faces with 10 mm head and bed joints make a 225 x 75 mm
  module. Alternate courses are offset by half a module (112.5 mm). The 1800 mm tile holds exactly
  8 units per course and 24 courses. Joints are recessed 5 mm behind the face.
- **Limestone ashlar.** 600 x 300 mm module, 5 mm lime joints, half bond, 4 blocks and 8 courses to
  a 2400 mm tile, joints recessed 3 mm, fine horizontal tooling and bedding along the course.
- **Painted render.** A dashed finish on a 6.7 mm cell over a 50 mm trowel relief, paint flaking on
  a few raised dashes. No module, so the extent states the size of the finish's features.
- **Cast concrete.** Plywood form panels on a 1200 x 600 mm module, 2 panels and 4 courses to a
  2400 mm tile, a 2 mm seam fin, four 28 mm form-tie holes per panel on a 600 x 300 mm grid with a
  run-off stain below each, and scattered bug holes.
- **Storefront metal.** Brushed, clear-anodised aluminium, brushing along u, full metalness except
  under faint handling marks.
- **Carriageway asphalt.** Coarse aggregate on an 11 mm cell and fine aggregate on a 3.8 mm cell in
  a dark binder, light wear, small oil stains and sparse cracking on a warped 333 mm network. No
  markings, wheel tracks or ironwork: those are geometry or decals, and a tiling texture that
  carried them would repeat them.
- **Footway paving.** Precast concrete flags on a 600 x 600 mm module, stack bond, 6 mm grit
  joints, 3 x 3 flags to an 1800 mm tile, per-flag lippage, a 3 mm chamfer, exposed fine aggregate
  and sparse trodden-in gum.
- **Kerb stone.** Flame-textured grey granite units 900 mm long with 6 mm head joints and no bed
  joint. 1024 x 256 texels over 1800 x 450 mm keeps texels square at 1.76 mm.

The corridor needs six. Which six is the grammar's decision, so everything below that depends on
the choice charges the six most expensive sets, which bounds any six the grammar picks.

## 2. Recipes, makers and the object store

A set is a MAKER applied to a RECIPE, and everything but the maker's code is a data object.

- **A maker** is versioned code in `web/packages/loom-texture/src/makers/` (`loom.brick`,
  `loom.ashlar`, `loom.render`, `loom.concrete`, `loom.metal`, `loom.asphalt`, `loom.paving`,
  `loom.kerb`, all version 1) with a **manifest** (`exulanica.texture-maker/v1`): every control's
  key, kind (`integer`, `integer_list`, `choice`, `srgb`, `srgb_list`), unit, range, group, label and
  explanation, and the rules across controls a recipe must satisfy (`equal`, `less`,
  `less_or_equal`, `even`, each optionally applying only when a choice has a given value, over sums
  and products of controls, extents and constants). Every manifest declares the four controls the
  bake reads itself: `height_range_mm` and the three occlusion controls. What a maker leaves fixed
  (its noise scales and thresholds) is fixed by its version; what a person would name (a module, a
  joint, a colour, how much wear) is a control.
- **A recipe** (`exulanica.texture-recipe/v1`) names a maker and version and states every control,
  the seed, the resolution (a power of two from 16 to 1024 on each axis) and the extent. Nothing is
  left to a default, so a recipe means the same thing even if a maker's default changes. A recipe
  is refused if a control is missing, undeclared, of the wrong kind or out of range, if a rule
  fails, if a rule's arithmetic leaves the range doubles hold exactly, or if its height range times
  its texels on an axis exceeds 32 times that axis in millimetres, past which the normal derivation
  would stop being exact.
- **A library entry** (`exulanica.texture-library-entry/v1`) publishes a recipe as a named,
  versioned set with a title, a summary and a licence. The source of each is one file in
  `web/packages/loom-texture/library/`, the recipe written out in full and kept in one layout that
  `test/published.test.ts` enforces.
- **A bake receipt** (`exulanica.texture-bake-receipt/v1`) records one bake: the maker manifest,
  entry, recipe and licence digests that went in, the bake pipeline (`exulanica.texture-bake/v1`),
  and the container digest and length that came out.

Every one of these is canonical JSON under `assets/textures/objects/<sha256>.json`, named by the
digest of its bytes, and they refer to each other only by digest, so any of them can be copied into
another content-addressed store and still resolve. `assets/textures/catalog.json`
(`exulanica.texture-catalog/v1`) indexes them: the digest of the manifest it accounts for, every
maker, and one row per set naming its receipt. `manifest.json` is unchanged, byte for byte, and
still the contract with the grammar lane (section 8).

The eight published recipes are each maker's defaults on the frame the set was first baked on, and
rebaking them reproduced every one of the eleven files published before recipes existed, byte for
byte: no set's version changed.

**Two languages, one check.** `web/packages/loom-texture/src/recipe.ts` and
`exulanica/materials/recipes.py` both run every case in
`web/packages/loom-texture/test/recipe-cases.json` (50 recipe cases and 39 manifest cases, each
starting from a published object and listing the exact problems expected, in order), so the baker
and the backend refuse the same objects with the same explanation. A person's variant, a recipe the
Companion proposes, and a recipe a model fits later are all this kind of object, and all of them
pass this check before anything stores or bakes them. `MaterialCatalog.recipe_problems` in
`exulanica/materials/catalog.py` is that check against whichever published maker a recipe names.

**Whatever a maker accepts, it can bake.** `test/makers.test.ts` pushes every control of every
maker to each end of its range, and every choice to each option, one at a time on a small frame,
repairing an extent a module rule pins. Every variant the check accepts must bake without
throwing, encode a canonical header and tile exactly. When this was written that was 507 of the 543
variants tried; each of the other 36 is refused by a rule, and the test lists them when it fails.

**What `exulanica.materials` may not do.** It sits below the evidence spine in the layers contract,
and a forbidden contract in `pyproject.toml` keeps it from importing the evidence address, the
store, the database, the ingest pipeline, identity, selection, reconstruction, psycopg, torch,
numpy, cv2 or pycolmap. A recipe is invented even when it is fitted to a photograph, and a module
that cannot name an evidence address cannot make one pass for an observation.

**What comes next, not built here.** Workspace-scoped recipes and bakes (a person's variants) get
their own migration with forced row-level security and tombstone invalidation. A recipe derived
from a photograph is an inert object that records the consent it depends on and is invalidated
when its source is tombstoned; no model infers a recipe from a personal photograph. Any learned
model that proposes recipes runs behind a process boundary, as the reconstruction container does,
and every proposal passes the check above.

## 3. The container, and why PNG is not digested

`.ltex` is the shape `web/packages/scene-synth/src/format/opm.ts` proved out: four magic bytes
(`LTX1`), a little-endian uint32 header length, the header as canonical JSON, space padding to a
16-byte boundary, then the four maps packed one after another with no gap. Only the first map is
aligned, which is ADR-0010's correction to OPM carried over; every texel is one byte wide, so
nothing after it needs alignment. The header states every offset and length anyway, and both
readers (`decodeContainer` in `web/packages/loom-texture/src/container.ts` and
`decode_texture_set` in `exulanica/world/texture_assets.py`) refuse a file whose maps are not
exactly contiguous, whose padding is not spaces, or whose header is not its own canonical form.

The packing is stated in the header, map by map, and nothing is implied by convention:

| Map | Channels, in stored order | sRGB | Decoding |
| --- | --- | --- | --- |
| `base_color` | red, green, blue | true | the sRGB transfer function to linear reflectance |
| `normal` | normal_x, normal_y, normal_z | false | `n = 2 * b / 255 - 1`, then normalise. Tangent space, glTF convention: +X toward increasing u, +Y toward row 0, +Z out of the surface |
| `orm` | occlusion, roughness, metalness | false | `b / 255`, linear. Occlusion 255 is unoccluded, and roughness is perceptual, as glTF's `occlusionTexture` and `metallicRoughnessTexture` read them |
| `height` | height | false | `mm = b * height_range_mm / 255` |

Texels are interleaved within a map, rows top to bottom, and row 0, column 0 is the texel at glTF
uv (0, 0). Every row is 3072 or 1024 bytes, both multiples of 4, so a map is a `subarray` a
renderer can hand to `texImage2D` under the default unpack alignment. The header also carries the
set id, version, seed, title, summary, the licence id and digest, the resolution, the extent, the
placement (section 6), the height range, the cavity-occlusion parameters, the recipe's stated
module, and `"truth": "invented"`. Every number in it is an integer.

**Why PNG is not digested.** A PNG's bytes are whatever its deflate implementation emitted, so a
pinned PNG digest would make Node's bundled zlib a digest input: the same pixels baked with a
different zlib build would hash differently, and the migration naming those bytes would quietly
stop being reproducible from source. The container stores texels raw, so its bytes are a function
of the texels and the header alone. PNG is still written, by `loom-texture/src/inspect/`, as a
picture for people; the CLI refuses to write it inside the output directory, and nothing pins or
digests it. Transport compression (section 7) is the server's business and does not touch a
digest.

## 4. Determinism

Every file the bake writes is a function of the library files and the source: each set's recipe,
id and version, and the makers' code.

- **Hashes, not a stateful generator.** Every stochastic decision is a hash of integer lattice
  coordinates and a seed, for the reason `scene-synth/src/rng.ts` gives: output is identical across
  machines, Node versions and thread counts, and a different resolution samples the same surface.
- **Integers throughout.** Positions, weights, heights and colours are integers in stated units.
  IEEE-754 addition, subtraction, multiplication and division are correctly rounded wherever V8
  runs, but `Math.pow`, `Math.exp`, `Math.sin` and the rest are only "implementation-approximated"
  by the language and V8 has changed their results between releases. None of them appears in
  `src/`, and neither does `**`. The sRGB curve is a literal table computed once at 60 significant
  digits (no entry lies within 0.0016 of a rounding tie). The one square root is `isqrt`, which
  uses `Math.sqrt` only as a first guess and corrects it to the exact floor.
- **No ambient input.** `test/source-hygiene.test.ts` reads every file under
  `web/packages/loom-texture/src` and fails on `Math.random`, `Date`, `hrtime`, `process.env`,
  `randomUUID`, `getRandomValues`, `randomBytes`, `randomInt`, `performance.now` or `node:os`, and
  on the approximated arithmetic above; it asserts that its walk reaches the nested modules and
  that a planted violation of each kind is caught. `test/determinism.test.ts` also stubs the clocks
  and `Math.random` to throw during a bake.
- **Canonical JSON in both languages.** The TypeScript writer accepts only safe integers and
  printable ASCII, and `test/container.test.ts` compares its output with a string that
  `exulanica.canonical.canonical_json` produced from the same value.

**Evidence.** `web/packages/loom-texture/evidence/2026-09-16-determinism.log.txt` is the output of
the script printed at its top. It baked the catalog five times: twice on Node 24.15.0 (arm64), once
on Node 26.7.0 (arm64), once on Node 20.10.0 (arm64) and once on Node 20.10.0 running as x86_64
under Rosetta 2. Every one of the 11 files in every run was compared with `cmp` against the first
run and against the committed `assets/textures/`: 0 differ.

`web/packages/loom-texture/evidence/2026-09-16-determinism-objects.log.txt` is the same script run
again once the sets were baked from recipes, at the commit it names and with no uncommitted change
under `src/`, on the same five runtimes. Every one of the 44 files it wrote (the 8 sets, the
dedication, the 32 objects, the manifest, the catalog and `.gitattributes`) was compared the same
way: 0 differ, the manifest and every set are the same bytes as in the first record, and the x86_64
run, which executes the compiled output, found the library through the package root. The package's
`test/published.test.ts` rebakes the whole library on every test run and compares each committed
file byte for byte, and `tests/test_texture_sets.py` holds both records to the committed files.

## 5. Tiling

**By construction.** A recipe receives the unwrapped position of each texel, in micro-units where
one tile is 2^20 along each axis. Every lattice is reduced modulo an integer number of cells per
tile before it is hashed, every octave doubles its period exactly, and every bonded pattern checks
that the tile holds a whole number of modules each way, and an even number of courses when
alternate courses are offset (`checkBond` in `src/bond.ts`). The derived maps (normals and cavity
occlusion) wrap every neighbour index. `test/tiling.test.ts` bakes each set with its sampling
window shifted by (37, 23) texels and by (-389, 267), several tiles away and below zero, and
requires every field and every map to equal the unshifted bake rolled by the same amount, exactly.
A recipe whose period does not divide the tile fails the same check, which the file also asserts.

**Numerically, on the pinned bytes.** For every channel of every map, along both axes, the summed
absolute difference across the wrap edge is compared in integer units with the same sum for every
interior neighbour pair. The criterion is that the edge is at most twice the mean interior pair. A
visible seam is one that stands out from a texture's own neighbour-to-neighbour variation; a torus
sampled field sits near 1, and the worst measured across the published sets is about 1.5, where the
texel grid beats against a fine lattice (the metal's brushing along v and the kerb's crystals along
v). The check runs in both suites, `test/tiling.test.ts` and `tests/test_texture_sets.py`, and both
show it failing on a plane stretched so its wrap edge joins texels half a tile apart. It is a
statistical check by nature, because any finite array is a sample of its own periodic extension;
the exact guarantee is the construction test above.

**By eye.** The contact sheet and the per-set previews (`pnpm texture --out DIR --inspect DIR`)
show every set as a 2 x 2 tiling and at full scale around the corner where four tiles meet. They
were inspected during the bake. They are inspection pictures lit by a fixed light, not the product.

## 6. Physical extent and UV scale

`extent_mm` is the physical size one tile covers, and it is the direct answer to "no UV channel, no
texture field in the schema": a surface can carry a UV scale derived from a real dimension instead
of a number somebody picked. A wall `w` mm wide and `h` mm tall repeats a vertical set
`w / extent_u` times across and `h / extent_v` times down, and one texel covers
`extent_u / width` mm, which is 1.76 mm for brick, paving and kerb.

`placement` in the header states how a tile lies:

- `vertical`: u runs horizontally along the wall and v runs downward, so world up is toward row 0.
  This is also the direction the brick and ashlar courses and the concrete tie stains assume.
- `horizontal`: u runs along the carriageway, footway or kerb, and v across it.

## 7. Budgets

**Decoded texture, the envelope this package must fit.** Melbourne was rejected on looks while
passing every mechanical budget, with 168 MB of decoded texture for 127 m of one street. Read as
168,000,000 bytes, the smaller reading, and charged conservatively as if every map were uploaded as
RGBA8, four bytes a texel, whatever its channel count:

| | Bytes |
| --- | --- |
| One 1024 x 1024 map, RGBA8 | 4,194,304 (4 MiB) |
| One set, four maps | 16,777,216 (16 MiB) |
| The corridor's six, no mips | 100,663,296 (96 MiB) |
| The corridor's six, full mip chains (1,398,101 texels a map) | 134,217,696 (128 MiB) |
| The accepted envelope | 168,000,000 |
| The corridor's six at 2048 x 2048, no mips | 402,653,184 |
| All eight sets, full mip chains | 162,179,744 |

1024 is the largest power of two that fits: six sets with mips leave 33,782,304 bytes of the
envelope for everything else, and 2048 does not fit even before mips. All eight at once would also
fit, but with almost no room left, so a renderer should load the sets a view draws rather than the
catalog. `web/packages/loom-texture/test/maps.test.ts` and `tests/test_texture_sets.py` both assert
these numbers.

**Transfer, measured and not a ceiling this package was given.** The containers are raw. The six
most expensive are 62,927,728 bytes; compressed with gzip at level 6, the usual HTTP setting, they
are 24,357,693 bytes. Melbourne transferred 28,247,006 bytes for the whole street, geometry
included, so the corridor lane should expect the texture sets alone to take most of a transfer
budget of that size. GPU-compressed delivery (KTX2 and Basis) would cut both numbers but brings an
encoder whose version becomes a digest input, the same problem as zlib, and is not done here.

**Repository weight.** The published directory is 76,045,080 bytes raw and 30,512,540 bytes in git's
compressed object store, against a pack of about 89 MiB before this package. Every rebake of a set
adds its bytes to history for good.

## 8. The manifest, the contract with the grammar lane

`assets/textures/manifest.json` is the single index both `exulanica/world/texture_assets.py` and
the grammar's catalog loader read. It is canonical JSON with no trailing newline, an object
`{"profile": "exulanica.texture-manifest/v1", "sets": [...]}`, with `sets` sorted by `set_id` and
each id once. Each entry holds exactly `set_id`, `version`, `content_sha256`, `byte_size`,
`resolution`, `channels`, `extent_mm`, `licence_id` and `licence_sha256`. The shapes this package
defines for the open fields:

- `resolution`: `{"height": H, "width": W}` in texels.
- `channels`: one object per map, in stored order, `{"components": N, "holds": [...], "map": NAME,
  "srgb": BOOL}`, exactly the header's packing less the offsets.
- `extent_mm`: `{"u": U, "v": V}` in whole millimetres.

Each set is `blobs/<content_sha256>.ltex` beside the manifest, and the dedication is
`blobs/<licence_sha256>.txt`. `assets/textures/.gitattributes` stops any checkout converting line
endings, expanding keywords or running filters over the pinned files, and keeps the blobs out of
textual diffs and merges.

**`version` and `content_sha256` are replay inputs.** The grammar records the pin
`{set_id, version, content_sha256}` when it resolves an id, and its catalog digest covers those
pins. A set id is a stable name and never carries a version or a digest; a rebake that changes a
set's bytes must bump its version, and the pins in migration 0065 are what catch one that does not.
The grammar lane's reader, `exulanica.grammar.textures.read_texture_manifest`, was run from its
worktree against this manifest and accepted all eight sets.

## 9. The backend reader and resolver

`exulanica/world/texture_assets.py` sits in the `world` layer and imports only
`exulanica.canonical`, `exulanica.errors`, `exulanica.materials` and `exulanica.store`, which the
layers contract permits.

- `load_texture_catalog(directory=TEXTURE_DIRECTORY) -> TextureCatalog` reads the manifest, refuses
  it unless it is canonical, integer-only, sorted and in the agreed shape, recomputes every blob's
  sha256 and length from disk, decodes every header and refuses one that disagrees with its entry,
  and verifies the dedication. A directory that is not what it says fails here, before any set is
  handed out.
- `resolve_texture_set(material: object, catalog: TextureCatalog) -> PinnedTextureSet` takes a
  material record carrying `texture_set_id` as a mapping key or an attribute, and has exactly two
  failure modes: `MissingTextureSet` when the record has no id (absent, `None` or empty), and
  `UnpinnedTextureSet` when the id is anything but exactly a pinned id. Both are
  `TextureSetUnresolved`. The catalog is a required argument, so resolution never loads one and
  never has a third way to fail, and its one `return` is the catalog's own entry for that id.
  `tests/test_texture_sets.py` checks all of this, including by reading the function's syntax tree.
- A set id is a string matching `^[a-z][a-z0-9.-]*$`, exactly `asset_key` in migration 0042, by
  convention `<licence>.<surface>`, for example `cc0.brick-running-bond`.
- `load_texture_catalog` also requires `catalog.json` and verifies it through
  `exulanica.materials`: every object hashes to its name and is canonical; the catalog describes
  exactly this manifest; every maker manifest is well formed and every recipe valid for its maker;
  every receipt agrees with the manifest about the bytes and the licence and with its entry about
  the recipe. Each container header must then agree with its recipe and maker: title, summary,
  seed, resolution, extent, family, surface, height range and occlusion. What the backend cannot
  check is that the maker, run on the recipe, produces these bytes, because the maker is
  TypeScript; `test/published.test.ts` rebakes every set and compares byte for byte, which is what
  catches a recipe edited in a way no header shows, such as a colour.
- `PinnedTextureSet` carries the manifest fields, `extent_u_mm` and `extent_v_mm`, the header's
  title, summary, seed and height range, the maker id and version, the recipe and receipt digests,
  and `pin()`, which returns the three replay fields. `read_bytes()` re-verifies the digest on every
  read. `TextureCatalog.materials` is the verified material catalog.
- `seed_texture_sets(store, catalog=None)` writes every pinned set and the dedication into the
  content-addressed store and checks the store's digest against each pin. It is idempotent.

There is no default and no fallback. A surface whose material does not resolve is an unavailable
surface, and whatever draws it must say so rather than paint a flat colour that reads as
architecture.

The grammar lane's layering puts `exulanica.grammar` below `world`, so its material stage cannot
import this module; it reads the same manifest through its own reader and refuses an unpublished id
with its own schema error. This resolver is for the layers above `world`.

## 10. Migration 0065

`0065_texture_set_digests.sql` creates `world_texture_set`, keyed by `(set_id, version)`, with
`content_sha256` unique, the check constraints 0042 uses (the id pattern, 64 lowercase hex
characters, a positive byte size, `licence_id = 'CC0-1.0'`), the resolution and extent as positive
integers, the packing as a JSON array, the title and summary from each header, the media type, and
`truth = 'invented'`. It inserts the eight pins above as literals and makes the table read-only
for `exulanica_app` and `exulanica_ro`, the two runtime roles `exulanica/db/roles.py`
provisions, with the same inline block 0042 uses, skipping a role the cluster does not have.
Unlike 0042 it names no role from before the ADR-0011 rename. A trigger refuses every UPDATE and DELETE, even by the owner, and every INSERT by a role that
is not a member of the owner, so a pinned version never names other bytes and a new version
arrives only in a new migration.

The catalog has no `workspace_id`, no `ws_isolation` policy and no forced row-level security,
because, like `world_reviewed_asset`, it is a global reviewed registry every workspace reads
identically and no workspace may own, hide or alter. It therefore does not change the count of
workspace-keyed forced tables that `tests/test_migration.py` measures.

The registry row is the reviewed decision; the bytes live in the content-addressed store. A read
reports a texture unavailable when the row is here and the bytes are not, and never substitutes a
default map or a flat colour.

## 11. Rebaking a set

1. Change the set's recipe in `web/packages/loom-texture/library/<set_id>.json` and bump its
   `version` in the same file. A change to a maker's code that alters any texel for an existing
   recipe is a new maker version, and a new version of every set that uses it.
2. From `web/`, run `pnpm texture --out ../assets/textures` (or
   `npx tsx packages/loom-texture/src/cli.ts --out ../assets/textures` until the script is
   registered). The directory is rewritten and superseded blobs are removed; they stay in history.
3. Write a new migration that inserts the new `(set_id, version)` row. Never edit 0065: its checksum
   is verified at boot, and an edited migration is a silent schema fork.
4. Update the table in section 1, run both suites, and bake twice into scratch directories and
   compare them with `cmp` before trusting the digest.

`web/packages/loom-texture/test/published.test.ts` fails if the committed files, objects and indexes
included, are not what the source bakes, and `tests/test_texture_set_migration.py` fails if the
manifest and the pinned rows disagree.

## 12. Follow-ups

- **`world_texture_set` in `READ_ONLY_TABLES` (deferred, blocked on `exulanica/db/roles.py`).**
  That file was closed to every lane when 0065 was written. `provision_runtime_role` grants insert
  and update on every table and revokes them only from the tables `READ_ONLY_TABLES` names, so
  until `world_texture_set` is added there, a provisioning run after 0065 grants the runtime role
  INSERT and UPDATE on the catalog. The migration's trigger refuses both in the meantime, and
  `tests/test_texture_set_migration.py` measures the grant and the refusal and asserts the table is
  still absent from the list, so that test fails, and should be updated, on the day it is added.
- **Done in this lane:** `world_texture_set` is classified in `GLOBAL_TABLES` in
  `exulanica/orchestration/judge_seed.py` as migration-provided reviewed texture set pins, so a
  judge-seed export no longer refuses a schema with 0065; it is in `_PRESERVED_TABLES` in
  `tests/conftest.py`, so the per-test truncation leaves the catalog alone; and
  `docs/all-documents.md` is regenerated with this document.
- **Registration in `web/`.** The `web/tsconfig.json` reference and the `web/pnpm-lock.yaml`
  importer for this package are on the fabrication-delete lane's branch; the `texture` script in
  `web/package.json` and the two dependency-cruiser rules (nothing that ships to a browser imports
  loom-texture; loom-texture reaches no workspace package but `atlas-core`) are requested from it.

## 13. What is not verified

- **The appearance of these sets in the rendered product: UNVERIFIED.** No renderer draws a set yet.
  The contact sheet was inspected, and it shows the stored maps under a fixed light, which is
  evidence about the bytes and not about the product. The corridor lane verifies appearance against
  the gate lane's Flatiron baseline.
- The transfer figure in section 7 is gzip over the files, not a measured browser load.
- That a recipe, run through its maker, produces a set's bytes is checked by the package's suite,
  which runs the TypeScript maker. The backend verifies every binding it can see without the maker,
  and no more.
- The UV derivation in section 6 is arithmetic on stated extents; no surface consumes it yet.

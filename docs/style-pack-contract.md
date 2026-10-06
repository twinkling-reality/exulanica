# Style pack contract

This contract owns the style pack: the data object that decides how a world looks. It owns the
manifest, the look roles a pack dresses and how each is resolved and fitted to a slot, the palette and
its colour encoding, the light presets, the budgets a piece is held to, and the readers that check a
manifest. Which values of a world are protected, and how an appearance is proposed, previewed,
applied and rolled back, is the [customization contract](atlas-world-customization-contract.md);
the light and finish a preset becomes is the [render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses).

Status: the manifest, both readers, the resolver, the fit rules, the piece budgets, the browser's
reading of a palette piece and drawing a generated town in a pack (section 7) are built. The packs
themselves, choosing a pack per world, storing, listing, uploading and downloading packs, binding a
pack to a world's style version and drafting a pack with a model are planned and not built.

## 1. In plain words

A style pack makes a world look a certain way: toon, cozy and faceted, or finished and realistic.
It says what light the world stands in, what colours and materials its walls, roads and ground are,
and which small 3D pieces dress its windows, doors, benches, trees and cars. It never says where
anything is: a pack cannot move a wall, a road or a door, so changing a world's pack changes how the
world looks and nothing about what it is.

## 2. The manifest

A pack is a manifest, profile `exulanica.style-pack/v1`, and the files it lists. Every number in a
manifest is a whole number in a stated unit (per mille, millimetres, millidegrees, millionths), and
the manifest's identity is the SHA-256 of its canonical bytes: keys sorted, no whitespace, ASCII with
lowercase `\u` escapes. Both readers write the same bytes.

| Field | What it holds |
| --- | --- |
| `pack_id`, `version` | A namespaced id (`exulanica.cozy-town`) and a whole-number version |
| `title`, `description`, `tags` | What a person reads in a library; tags are lowercase words |
| `origin`, `provenance` | `authored`, `uploaded`, `drafted`, `generated` or `imported`, and what each requires: a drafted pack names the model, prompt version, execution and the digest of the words; a generated one names its generation receipts |
| `licence`, `authors` | `CC0-1.0`, or `CC-BY-4.0` with its attribution; who made it |
| `base` | The pack this one is drawn on, by id, version and manifest digest, or none |
| `light` | Named presets (at most six) and the default one; each preset is a sky, a fog, a sun with a one-tap, three-tap or five-tap shadow filter, image light, contact shadowing and a finish, in whole-number units. A pack may not choose soft (PCSS) shadows: they alone cost more than a frame ([render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses)) |
| `shading` | `pbr`, `toon` with its bands, or `flat`, and an ink colour or none |
| `edge` | The ground beyond the world: a colour, how far below the tiles it lies, how far it reaches |
| `palette` | At most 64 swatches, each a distinct sRGB colour with roughness, metalness and emission |
| `surfaces` | A look role of a surface family to a swatch or a texture set, with an optional swatch for upward faces |
| `modules` | A look role of a module family to one to eight variants, each a piece file, an optional second level of detail, the piece's own size and, for a fill family, where it stretches |
| `files` | Every file the pack carries, in path order: path, SHA-256, size and media type (`model/gltf-binary`) |

A pack with no base states its light and shading. A pack drawn on a base states only what it changes:
its swatches, surfaces, modules, presets, shading and edge replace the base's, and anything it leaves
out is the base's. A chain holds at most four manifests.

## 3. Look roles

A look role is `family.leaf`. The families, how each is fitted and how a pack dresses it are the
world kinds' look-family catalog, which both readers are given rather than copying; leaves are open. A pack
dresses look roles only, never a slot, an engine role or a position.

| Dressing | Families | What the pack supplies |
| --- | --- | --- |
| Surface | ground, path, road, water, wall | A swatch or a texture set |
| Both | roof | A surface, and optionally pieces |
| Module | door, window, fixture, prop, plant, boundary, vehicle, structure | Pieces |
| Catalog | character | Nothing: characters are the published character catalogs' |
| Primitive | animal | Nothing yet: the engine's primitive |

A slot is resolved by its leaf, then by the family's `default` leaf in the pack (its base chain
already applied); when neither is dressed the caller draws the engine's primitive. The caller states
what a slot can take: a surface a tile already drew takes only a swatch or texture set, a hole a tile
left takes only a piece, and a primitive takes either, a surface before a piece at each leaf. When a
family has several variants, the part's identity picks one: FNV-1a over `identity|leaf` in UTF-8,
modulo the count, so every runtime picks the same piece for the same part; a variant that does not
fit the slot passes to the next.

A piece meets its slot by its family's fit. Pieces are authored at real size in metres, +Y up, +Z
toward the front, pivot at the base centre; a slot is millimetres, front +y, up +z, and a piece is
placed by the rotation that takes +Z to the slot's front (never a reflection, so lettering never
mirrors).

| Fit | Rule |
| --- | --- |
| Contain | One uniform scale, the tightest axis's, so the piece lies inside the box |
| Fill | Each axis meets the box: by its stretch zone where the variant states one, else scaled within the family's bounds (800 to 1250 per mille for doors and windows); a box that leaves a zone no length, or a scale outside the bounds, passes to the next variant, then none |
| Tile | Copies along the width, as many as the width holds rounded, each scaled to share it exactly |
| Surface | A material, never a piece |

A fill variant may state a stretch zone per axis (`stretch_mm`, in the order of `size_mm`: width,
depth, height), as a low and a high in millimetres from the piece's low face on that axis. What lies
below the low and above the high keeps its size, and the zone takes up the difference, so one
window's frame keeps its bars in any hole at least as large as the bars; the city grammar's openings
run from 300 to 4000 mm wide, 500 to 5000 mm tall and 120 to 250 mm deep, more than one scaled
piece could meet within the bounds. A zone lies within the piece with its low below its high, and
only a fill family's piece states one. A normal in a zone turns by the inverse of the zone's
draw-out, so a slanted face stays lit as its shape says.

## 4. Palette and colour

Stylised pieces carry no texture: their `COLOR_0` is `VEC4` unsigned-short normalized, alpha always
65535, and each RGB triple is exactly one swatch of the pack's palette in the encoding
`exulanica.srgb8-linear16/v1` (`assets/colour/srgb8-linear16.v1.json`: every sRGB byte's linear value
times 65535, rounded half to even). The table is one file both the piece generator and the page read.
Because every colour is exactly a swatch, a pack drawn on another can recolour every piece by
changing its swatches.

The page reads a palette piece with `readStylePiece` (`web/packages/atlas-core/src/style-piece.ts`):
one triangle primitive with float `POSITION` and `NORMAL`, `COLOR_0` as above and 16-bit or 32-bit
indices, each triangle coloured by one swatch. It groups the triangles by swatch, so each swatch
draws as one material, and names the swatch by its key in the palette of the manifest that stated the
piece's module (`swatchKeyOf`), so a base pack's piece takes the colours a pack drawn on it restates.
A piece that is anything else is refused by name: another container, more than one primitive, lines,
a missing or differently laid out attribute, an alpha other than 65535, a colour that is no byte of
the table, a triangle of two swatches, an index or accessor past its data.

## 5. Budgets

A piece is an `exulanica.static-glb/v1` container first
([workspace asset admission](workspace-asset-admission.md)), and its family's budget sits on top of
that profile's limits: `assets/style-packs/piece-budgets.v1.json` states, per family, the triangles
at the first level of detail (per metre of the piece's own width for a tiled family), materials, the
largest texture side and the file's size, and a second level of detail holds at most a quarter of
the first's triangles. A pack's files total at most 64 MiB.

## 6. Readers

`exulanica/world/style_packs.py` is the authoritative reader; `web/packages/atlas-core/src/style-pack.ts`
is the browser's, written from the same rules. Each checks every field in the order the schema lists
it, then the rules across sections, and refuses with the first fault by reason and path:

| Reason | What it refuses |
| --- | --- |
| `shape` | An unknown or missing key, a value of the wrong kind, a fraction, a malformed id, role, path or text |
| `range` | A whole number outside its bounds, a value not in its list, fog or toon bands out of order, a soft (PCSS) shadow filter, a stretch zone outside its piece or of no length |
| `reference` | A role of an unknown family or of a family not dressed that way, a swatch, texture set, preset or file that is not there, a listed file no variant uses, provenance that is not the origin, a pack with no base and no light or shading, a stretch on a piece of a family that is not fill |
| `duplicate` | Two swatches of one key or one colour, two files of one path |
| `licence` | CC-BY-4.0 without attribution, attribution on CC0-1.0 |

`assets/style-packs/manifest-cases.v1.json` holds both readers to the same verdict on every case: the
same refusal by reason and path, or the same digest; `tests/test_style_packs.py` and
`web/packages/atlas-core/test/style-pack.test.ts` run it, and the latter also holds the resolver,
the variant choice and the fit rules, stretching included.
`web/packages/atlas-core/test/style-piece.test.ts` holds the piece reader to a piece it writes
itself, apart from the pieces' writer.

## 7. Drawing a town in a pack

`web/packages/atlas-react/src/playcanvas/style-pack/` draws a generated town in a resolved pack.
Nothing it does changes a tile, a record, what anyone can walk on or what collides; taking the tiles
down puts every material back and removes every piece.

| Part | What it does |
| --- | --- |
| Light | The pack's default preset, in its whole-number units, becomes the tiles' render look (`renderLookOfPreset`); what a pack does not choose, such as shadow map sizes, is the engine's |
| Surfaces | Each texture set a town is drawn with takes the look role `assets/style-packs/town-look-roles.v1.json` names: the family of the first grammar surface role the material catalog lists for the set's material, then the material's key. The pack resolves it as a surface only; a swatch replaces the set's material, a texture set keeps the set's own, and either may colour the set's upward faces with an up swatch (`dressTownSurfaces`) |
| Windows | One slot per opening a facade the tile owns cuts, read with the tessellator's own rules (`openingSlots`): the hole's width and reveal, its height to the head or to an arched head's springing line, its base centre set in half the reveal, its front the face's outward side; its look role `window.<head treatment>` |
| Pieces | A pack's pieces are fetched, held to the size and digest their manifest states, read as palette pieces and uploaded once (`fetchPackPieces`, `uploadPackPieces`); every slot's piece is placed by its fit and baked with the others into one mesh per swatch (`dressSlots`) |
| Vehicles | A traffic vehicle's body is the pack's piece for `vehicle.<body family>`, chosen by the vehicle's id, contained in the record's own size; its `vehicle_body` swatch takes the vehicle's colour as the pack states it (`vehicle_red`); a body family the pack does not dress keeps the traffic's boxes (`packVehicleBodies`) |
| Ink | A shading that draws ink outlines the tiles' opaque surfaces and the pack's baked pieces (`attachTileInk`) |

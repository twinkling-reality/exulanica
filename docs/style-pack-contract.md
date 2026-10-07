# Style pack contract

This contract owns the style pack: the data object that decides how a world looks. It owns the
manifest, the look roles a pack dresses and how each is resolved and fitted to a slot, the palette and
its colour encoding, the light presets, the budgets a piece is held to, and the readers that check a
manifest. Which values of a world are protected, and how an appearance is proposed, previewed,
applied and rolled back, is the [customization contract](atlas-world-customization-contract.md);
the light and finish a preset becomes is the [render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses).

Status: the manifest, both readers, the resolver, the fit rules, the piece budgets, the browser's
reading of a palette piece, drawing a generated town in a pack (section 7), three authored packs
(section 8), the committed library the host serves (section 9) and a world's appearance naming its
pack (section 10) are built. A control for choosing a pack, a person's own packs (storing,
uploading and downloading them) and drafting a pack with a model are planned and not built.

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
| `preview` | A listed picture (`.jpg`, `.png` or `.webp`, at most 512 KiB) that shows what the pack looks like, for a person choosing one, or none; absent, none |
| `base` | The pack this one is drawn on, by id, version and manifest digest, or none |
| `light` | Named presets (at most six) and the default one; each preset is a sky, a fog, a sun with a one-tap, three-tap or five-tap shadow filter, image light, contact shadowing and a finish, in whole-number units. A pack may not choose soft (PCSS) shadows: they alone cost more than a frame ([render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses)) |
| `shading` | `pbr`, `toon` with its bands, or `flat`, and an ink colour or none |
| `edge` | The ground beyond the world: a colour, how far below the tiles it lies, how far it reaches |
| `palette` | At most 64 swatches, each a distinct sRGB colour with roughness, metalness and emission |
| `surfaces` | A look role of a surface family to a swatch or a texture set, with an optional swatch for upward faces |
| `modules` | A look role of a module family to one to eight variants, each a piece file, an optional second level of detail, the piece's own size and, for a fill family, where it stretches |
| `files` | Every file the pack carries, in path order: path, SHA-256, size and the media type its extension states (`model/gltf-binary` for `.glb`, `image/jpeg`, `image/png` or `image/webp` for a picture); every file is a variant's piece or the preview |

A pack with no base states its light and shading. A pack drawn on a base states only what it changes:
its swatches, surfaces, modules, presets, shading and edge replace the base's, and anything it leaves
out is the base's. A chain holds at most four manifests.

A profile changes without breaking a manifest written under it. A field added within a profile is
optional, and its absence keeps the meaning a manifest had before the field existed: `preview` came
after the first packs were published, and a manifest without it names no picture. A change that a
manifest written earlier could not meet needs a new profile, which readers read beside the old one,
so every published version stays readable.

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
the first's triangles. A pack's files total at most 64 MiB. One reader reads that file,
`exulanica_pieces/budgets.py`, for the pack reader and the generated pieces alike, so a generated
piece is made against the numbers a pack's piece is held to.

## 6. Readers

`exulanica/world/style_packs.py` is the authoritative reader; `web/packages/atlas-core/src/style-pack.ts`
is the browser's, written from the same rules. Each checks every field in the order the schema lists
it, then the rules across sections, and refuses with the first fault by reason and path:

| Reason | What it refuses |
| --- | --- |
| `shape` | An unknown key or a missing one the profile requires, a value of the wrong kind, a fraction, a malformed id, role, path or text, a file whose media type is not its extension's |
| `range` | A whole number outside its bounds, a value not in its list, fog or toon bands out of order, a soft (PCSS) shadow filter, a stretch zone outside its piece or of no length, a picture over 512 KiB |
| `reference` | A role of an unknown family or of a family not dressed that way, a swatch, texture set, preset or file that is not there, a preview naming no listed file, a listed file nothing uses, provenance that is not the origin, a pack with no base and no light or shading, a stretch on a piece of a family that is not fill |
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

The app draws a saved generated world in the pack its address names (`?look=toon`, `cozy`,
`finished`, or `today` for the tile look), else the pack its appearance names (section 10), else
`DEFAULT_WORLD_LOOK` (`web/packages/app/src/world-look.ts`), the cozy town, reading the pack from the
host (section 9). A pack the page cannot read is not stood in for: the world opens in the tile look,
and the shell's `data-world-look` attribute states the pack asked for, what chose it (`address`,
`world` or `default`) and why it was not drawn.

`redrawWorldLook(pack)` (`web/packages/app/src/composition/world-look-redraw.ts`) draws the open
world in another pack, named exactly (null: the default), without opening the world again: the
person stays where they stand, and its people and traffic go on. The pack is read and its pieces
fetched first, and a pack the page cannot read leaves the world as it was and says why. The tiles,
as the page loaded them, are then attached again in the new pack's light (`inLook`, in
[the runtime](generated-tile-runtime.md#4-loading-a-tile)), so nothing is fetched, verified or
decoded a second time, and swapped on the same host: the old look is taken down before the new one
goes up, and the traffic draws its vehicles in the new pack's bodies. Redraws run one after another in the order asked. Any part of the page may
ask by dispatching `exulanica:world-look-redraw` on the shell with the pack as the event's detail;
`data-world-look` then states the look drawn (source `redraw`) and `data-world-look-redraw` the
redraw's own result with its time. A redraw changes nothing the world's appearance names: that is
the appearance's own Apply (section 10).

## 8. The authored packs

Three packs are committed under `assets/style-packs/packs/`, each CC0-1.0 and authored by Exulanica:
`exulanica.toon-town` (flat colour in two light bands with ink), `exulanica.cozy-town` (faceted,
warm light, some windows lit) and `exulanica.finished-town` (the town's own texture sets for every
wall, road, path and ground material, physically lit, slate roofs). Each states a day and an evening
preset, a preview picture, surfaces for the town's materials and for every surface family's default,
window and door frames that stretch, a hatchback, a sedan, one van for minivans and panel vans and a
bus for the traffic (bicycles keep the traffic's boxes), a tree and a fence. Each preset's sky
lights a surface in shade with at most twice as much blue as red, so a shaded street reads grey
rather than navy. Every preview is the pack drawn by the product on one generated market town at
its arrival camera, the same town and camera for all three, 1600 by 1000 pixels with the interface
hidden.
`scripts/style_packs/authored_packs.py` writes every byte of the pieces and manifests from boxes,
prisms, cones and faceted spheres through the shared piece writer, lists each committed preview,
and refuses a frame whose fixed parts would not fit the smallest opening the city grammar cuts or
the smallest door a site cuts, each read from the grammars. `tests/test_authored_style_packs.py`
holds the committed files to the script, the product's reader, the piece budgets, those openings
and the previews' format and size; `web/packages/atlas-react/test/style-pack-authored.test.ts`
reads them as the page does and holds each preset's shade light to that bound.

Every version a pack has published stays servable, so a world keeps the look it was given. Writing a
new version first retires the committed one: the script copies its folder whole to
`assets/style-packs/published/<pack id>/<version>/` and appends the version to the ledger
`assets/style-packs/published.v1.json`, so keeping an earlier version is part of bumping one.
`--check` refuses a published folder that no longer holds the bytes its ledger entry and manifest
state, and a version below the current one that the ledger does not list.

## 9. The library the host serves

The host serves its committed library, and nothing of a pack is bundled with the page, as no 3D
content is. When the host starts it reads `assets/style-packs/packs/` once
(`exulanica/world/style_pack_library.py`) and does not start if a pack breaks a rule, naming the
pack and the rule: a manifest not written as its canonical JSON and one newline, a manifest the
authoritative reader refuses, a folder not named by its pack id, a listed file that is absent, a
symbolic link or other bytes than its manifest states, a file its manifest does not list, or a base
that is not another pack of the library at the version and digest it names. A name starting with a
dot is passed over; no pack id or listed path can start with one. `assets/style-packs/library.v1.json`
(`exulanica.style-pack-library/v1`) names the library's default pack, the look a world is made in
when the person making it names none; a default that is not a pack of the library, or a file stating
anything else, refuses the library the same way.

A pack's earlier versions stay served. Each is read from its folder under
`assets/style-packs/published/` by the same rules as a pack folder and held to its entry in
`published.v1.json` (`exulanica.style-pack-published/v1`); a published folder whose manifest is not
the one its entry records, an entry with no folder, a folder with no entry, and a version that is
not below its pack's current one each refuse the library. `changes.v1.json`
(`exulanica.style-pack-changes/v1`) holds the host's own note on what a version changed, one plain
sentence of at most 200 characters, for a version the library holds. The notes live beside the
packs rather than in their manifests, so writing a note never moves a digest.

| Route | Answer |
| --- | --- |
| `GET /world/style-packs` | `exulanica.style-pack-list/v1`, each pack at its current version: its id, version and manifest digest, title, description and tags, origin, licence with the attribution it requires, authors, file count and bytes, its preview picture's digest and media type (`preview_sha256`, `preview_media_type`, or null), whether it is the default (`default`), the note on what this version changed (`changes`, or null), and its earlier versions the host still serves (`earlier_versions`, oldest first, each its `version`, `manifest_sha256`, `preview_sha256` and `preview_media_type`) |
| `GET /world/style-packs/{content_sha256}` | A manifest of any version the library holds, as its canonical bytes (`application/json`), or a file a manifest lists (its stated media type), named by the SHA-256 of exactly those bytes and cached as immutable; any other digest is 404 `unknown_reference` |

Both need a session holding `world.read`. A request names a digest and nothing else, so no request
reaches a path. The page reads the list, fetches a pack's manifest by the digest the list names and
each piece by the digest its manifest states, and holds every answer to its digest before reading
it (`web/packages/app/src/world-look.ts`). A world naming no pack is drawn in the pack the list
marks default (`listedDefault`); the page's own `DEFAULT_WORLD_LOOK` is read only from a host that
marks none. The bytes are held by
`exulanica/world/committed_content.py`, an index of committed content by digest that any later
library of committed looks can share. `tests/test_style_pack_library.py` and
`tests/test_style_pack_routes.py` hold the host's half, and `web/packages/app/test/world-look.test.ts`
the page's.

## 10. A world's pack

A world's appearance names the pack it is drawn in. Its style version holds the pack's id, version
and manifest digest, or none; naming one is an ordinary appearance change, previewed, applied and
rolled back with the rest of the appearance and kept in its history
([appearance authority](world-version-authorities.md#appearance-authority)). A pack the host's
library does not hold at exactly that version and digest is refused when it is named, applied or
rolled back to, so a world is never stored naming a pack its host cannot serve; a world read from
history whose pack the host no longer holds says so in the version's warnings. The library holds
every version it has published (section 9), so a world given an earlier version keeps it: the page
fetches a world's pack by the manifest digest its appearance names, so it draws exactly the bytes the
world was given, and moving to the current version is a choice of its own through the same preview
and Apply. `listedVersion` (`web/packages/app/src/world-look.ts`) places a digest as a listed pack's
current version or an earlier one. A pack states no structure, so naming one never moves the world's topology. A world
package exported from a world does not yet carry the pack its appearance names.

A world made by `POST /worlds/generated` is made wearing a look: the pack its `style_pack` names
(`{pack_id, version, manifest_sha256}`, a version the library holds at exactly that digest, else
422 `invalid_style_data` and nothing made), or the library's default when it names none
(`exulanica/world/creation_look.py`). The world is made first, its first appearance naming no pack;
the pack is then named by the appearance's next version through the same preview and Apply a
person's change takes, its provenance `user` with the reference `world-creation`, and the saved
entry's resume pointer moves with it in that write. A write to a world's look is its own
transaction, so it follows the making's: when it is refused as busy, the world stays as made, naming
no pack, and is drawn in the default. Binding the default at creation means a later change of the
library's default never restyles a world already made; a rollback to the first version returns a
world to naming no pack.

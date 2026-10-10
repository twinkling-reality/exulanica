# Style pack contract

This contract owns the style pack: the data object that decides how a world looks. It owns the
manifest, the look roles a pack dresses and how each is resolved and fitted to a slot, the palette and
its colour encoding, the light presets, the budgets a piece is held to, and the readers that check a
manifest, and a world's own setting drawn over its pack (section 12). Which values of a world are
protected, and how an appearance is proposed, previewed,
applied and rolled back, is the [customization contract](atlas-world-customization-contract.md);
the light and finish a preset becomes is the [render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses).

Status: the manifest, both readers, the resolver, the fit rules, the piece budgets, the browser's
reading of a palette piece, drawing a generated town in a pack (section 7), three authored packs
(section 8), the committed library the host serves (section 9) and a world's appearance naming its
pack (section 10) are built, as are a creator's own packs in their workspace: kept, uploaded,
checked, served, downloaded as an archive, offered for publication and withdrawn (section 11), and
looks made of generated pieces, recorded, checked, served and worn by the world they were made for
(sections 10 and 11.2), and a world's own setting, chosen from named parts, checked, stored and
drawn (section 12) and offered from a description (section 12.1). A person choosing their own workspace pack for a world, publishing one to
the library, the page's upload control, and drafting a pack with a model are planned and not built.

## 1. In plain words

A style pack makes a world look a certain way: toon, cozy and faceted, or finished and realistic.
It says what light the world stands in, what colours and materials its walls, roads and ground are,
and which small 3D pieces dress its windows, doors, benches, trees and cars. It never says where
anything is: a pack cannot move a wall, a road or a door, so changing a world's pack changes how the
world looks and nothing about what it is.

## 2. The manifest

A pack is a manifest, profile `exulanica.style-pack/v1`, and the files it lists. Every number in a
manifest is a whole number in a stated unit (per mille, millimetres, millidegrees, millionths) that
both readers hold exactly (at most 2^53 - 1 in size), and the manifest's identity is the SHA-256 of
its canonical bytes: keys sorted, no whitespace, ASCII with lowercase `\u` escapes. Both readers
write the same bytes. Text is trimmed and holds no lone surrogate, no control character (C0, DEL or
C1) and no bidirectional control character (the Unicode `Bidi_Control` set), so what a person reads
is the text as stored, in the order it is stored.

| Field | What it holds |
| --- | --- |
| `pack_id`, `version` | A namespaced id (`exulanica.cozy-town`) and a whole-number version |
| `title`, `description`, `tags` | What a person reads in a library; tags are lowercase words |
| `origin`, `provenance` | `authored`, `uploaded`, `drafted`, `generated` or `imported`, and what each requires: a drafted pack names the model, prompt version, execution and the digest of the words; a generated one names its generation receipts |
| `licence`, `authors` | `CC0-1.0`, or `CC-BY-4.0` with its attribution, or for an uploaded pack only `LicenseRef-Exulanica-Own-Work` with none (a person's own work, used in their own workspace and never public); who made it |
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
already applied); when neither is dressed the caller draws the engine's primitive. The server asks
the same of a role before any slot's fit (`exulanica.world.style_packs.role_offer`: its leaf, its
family's default, or nothing), to find the kinds a look dresses only with a default or the
primitive. The caller states
what a slot can take: a surface a tile already drew takes only a swatch or texture set, a hole a tile
left takes only a piece, and a primitive takes either, a surface before a piece at each leaf. When a
family has several variants, the part's identity picks one: FNV-1a over `identity|leaf` in UTF-8,
modulo the count, so every runtime picks the same piece for the same part; a variant that does not
fit the slot passes to the next.

A world made from a kind adds one step between the leaf and the family's default, for the families
that take a surface. Its parts name their surfaces in a kind's own words (`ground.sand`,
`wall.adobe`, `roof.thatched`, `path.desert_track`), and a pack states few of them, so the plain rule
would draw every ground as the pack's one ground. The surface material catalog
([`surface-material.v1.json`](../assets/catalogs/world-kinds/surface-material.v1.json)) states
each material a surface may be drawn in: the words that name it, the families that may wear it,
what it is in plain words, and the colour it is drawn in. A leaf is read by its words, whole and
then one by one in the order written, among the materials its family may wear
(`materialOfLeaf`, in
[`surface-material.ts`](../web/packages/atlas-core/src/surface-material.ts)), so `forest_floor` is
the forest's floor, a `lake_shore` named for ground is sand and not water, and `tile` is a floor's
tile underfoot and a clay tile on a roof. The order is then (`resolveSurfaceLookRole`):

1. the pack's own dressing for the leaf, a surface or a piece, exactly as the plain rule gives it;
2. for a leaf that names a material: the pack's own surface under `family.material` (a pack that
   wants its own sand states `ground.sand`); or the pack's family default where the catalog says
   that default is this material already (every pack's ground default is a lawn, so grass is the
   pack's own); or the catalog's colour, which the dresser draws as a swatch in the pack's shading;
3. the family's default, as before.

A leaf whose words name no material takes the default and is counted, never refused: the canvas
states how many slots wear a catalog material and which look roles named none
(`data-site-materials`, `data-site-unknown-looks`), so the next version of the catalog is written
from the words that were written. A town does not come through this step: its tiles name only
leaves its packs state, and the code that dresses a town calls the plain rule.

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
| `shape` | An unknown key or a missing one the profile requires, a value of the wrong kind, a fraction, a malformed id, role, path or text, text holding a lone surrogate, a control character or a bidirectional control character, a file whose media type is not its extension's |
| `range` | A whole number outside its bounds (one too long for a double included), a value not in its list, fog or toon bands out of order, a soft (PCSS) shadow filter, a stretch zone outside its piece or of no length, a picture over 512 KiB |
| `reference` | A role of an unknown family or of a family not dressed that way, a swatch, texture set, preset or file that is not there, a preview naming no listed file, a listed file nothing uses, provenance that is not the origin, a pack with no base and no light or shading, a stretch on a piece of a family that is not fill |
| `duplicate` | Two swatches of one key or one colour, two files of one path |
| `licence` | CC-BY-4.0 without attribution, attribution on CC0-1.0, the own-work id on a pack that is not uploaded or with an attribution |

`assets/style-packs/manifest-cases.v1.json` holds both readers to the same verdict on every case: the
same refusal by reason and path, or the same digest; `tests/test_style_packs.py` and
`web/packages/atlas-core/test/style-pack.test.ts` run it, and the latter also holds the resolver,
the variant choice and the fit rules, stretching included.

A reader never refuses a manifest it once accepted, since a world drawn in that manifest names it by
digest and no digest can be repaired. Every published version is read through both readers
(`tests/test_style_pack_library.py` and `web/packages/atlas-react/test/style-pack-authored.test.ts`).
A rule that would refuse a manifest already stored applies at admission only, never in the readers
that draw a world.
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

### 7.1 Drawing a site in a pack

A world made from a world kind (its site, [world kinds](world-kinds-contract.md#the-drawing)) is
drawn in a pack too, chosen the same way as a town's: the address's, else the pack its appearance
names, else the host's default. `packSiteDresser`
(`web/packages/atlas-react/src/playcanvas/style-pack/site-dresser.ts`) dresses the site's drawn
slots; nothing it does changes a slot, the walk or the seats, and taking the site down puts every
material back and shows every primitive again.

| Part | What it does |
| --- | --- |
| Light | The pack's default preset is the site's render look, as it is a town's |
| Resolving | Each slot by its look role (section 3): a slot the engine draws as a primitive takes either a surface or a piece, a surface before a piece at each leaf; a `none` slot, a hole only a pack fills, takes a piece alone |
| Surfaces | A swatch, with its up swatch, becomes the material of the slot's primitive, in the pack's shading. A site holds no texture set's images, so a leaf the pack dresses with a texture set is resolved as if the pack left it out, and takes its material where its words name one and otherwise its family's `default` |
| Materials | A leaf the pack does not state is drawn in the material its words name (section 3): the pack's own surface for that material, or the surface material catalog's colour in the pack's shading. A leaf that names none takes its family's `default` and is counted on the canvas |
| Pieces | Placed by the family's fit and baked one mesh per swatch, as a town's are (`dressSlots`); the slot's primitive is hidden while its piece stands |
| The rest | A slot the pack does not dress keeps the engine's primitive in its fallback colour, drawn in the pack's shading; when the shading draws ink, everything the site draws is outlined |

The app (`web/packages/app/src/composition/site-world.ts`) reads the pack and fetches its pieces
before it mounts the site. A pack it cannot read is not stood in for: the site opens in the tile
look in the engine's colours, and `data-world-look` states the pack asked for, what chose it and why
it was not drawn. The Look sheet is offered on a site as on a town, and `redrawWorldLook` mounts the
site's drawing, already read and checked, again in the new pack's light and dressing on the same
host.

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
| `GET /world/style-packs` | `exulanica.style-pack-list/v1`, with the named parts a world's setting is chosen from (`settings`, section 12), and each pack at its current version: its id, version and manifest digest, title, description and tags, origin, licence with the attribution it requires, authors, file count and bytes, its preview picture's digest and media type (`preview_sha256`, `preview_media_type`, or null), whether it is the default (`default`), the note on what this version changed (`changes`, or null), and its earlier versions the host still serves (`earlier_versions`, oldest first, each its `version`, `manifest_sha256`, `preview_sha256` and `preview_media_type`) |
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

A world may also wear a version of its workspace's own pack (section 11): its style version then
states `style_pack_source` `workspace` beside the id, version and digest (one migration,
`a_world_wears_its_own_look_of_generated_pieces`; every version written before it, and every one
naming a library pack, states `library`, and reads exactly as it did). Such a version is named only
while `workspace_style_pack_wearable` says it may be worn, asked under the asset read lock as the
last question of the write, and the schema holds the same at insert, so a rollback to a version
naming one that was since withdrawn is refused. The appearance routes name library packs only; the
generation worker names a look made of a world's generated pieces
([generated pieces](generated-pieces-contract.md#54-a-worlds-look-taking-its-pieces-in-and-back)).
A version naming the workspace's own pack is answered with `source` `workspace`, the library version
it is drawn on (`base`) and whether it may still be worn (`wearable`); a library pack's answer states
none of the three. The page fetches such a pack's manifest from `GET /workspace-style-packs/{sha256}`
and its own pieces from that version's file route, held to their digests, and its base from the
library, and resolves the two as one chain. A world whose own look was withdrawn after it was named
still opens: its version keeps naming it, its read carries a warning, and the page draws it in that
base.

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

### 10.1 A look offered from a description

A person who describes a world in words (`POST /worlds/specification/drafts`) is offered the look
the words ask for, if any. After a draft that is not refused, the route makes one short call of its
own (`exulanica/selection/look_choosing.py`, the manifest role `look_chooser`), shown only the
description as it was sent to the drafter, every saved name replaced, and each library pack's id,
title and description. The answer is one listed pack id or none, with up to three phrases copied
from the description that chose it. Code decides what is kept: a pack the library does not list, a
phrase not found word for word in the description, a look with no words or words with no look is
refused, told why once, and on a second refusal the step answers none. The answer is the draft
response's optional `look_offer`:

| `state` | Meaning |
| --- | --- |
| `offered` | `pack_id`, `version` and `manifest_sha256` name the library's current version of the pack, so the page binds exactly what was offered; `look_words` are the person's own words that chose it, as typed, a saved name written back and never sent |
| `none` | The words ask for no listed look, or the answer was refused twice (`reason` `answer_refused`) |
| `unavailable` | The step did not answer: `reason` `timed_out`, `failed`, `request_refused` (the workspace's rules refused the request) or `no_allowance` (the draft's allowance is spent) |

`look_offer` is absent for a refused draft and while the library holds no pack. Whatever it says, the
person picks the look, and a world made naming none is made in the library's default (section 10).
The step never changes the draft: the drafter's request is the same, byte for byte, with the step
and without it, and the draft's `execution` lists only the drafter's calls; the step's own calls are
in `look_offer.execution`. It spends the same allowance as the draft, through the same client.

The step runs after the draft in the same request, so the answer comes that much later: a median
of about 1 s in its measurement, and never more than the role's timeout, one deadline over the call
and its repair together. A repair is asked only while some of it is left; a call the deadline ends
is `unavailable` with `timed_out`. The role's timeout,
10 s, follows the manifest's timeout rule (the primary's longest measured call times two, rounded up
to 5 s) from its pre-registered measurement, whose record holds the primary's own calls
([record](evaluation/2026-10-07-look-chooser-timings.json)): 59 calls, longest 4,830 ms. The
measurement's own pre-registered rule, the longest call rounded up to the next 5 s, gives 5 s; the
manifest's rule governs every role. The three longest calls were all one description. A call past
the timeout leaves the library default with no error. The fallback serves under the same timeout
when the primary is withdrawn; its slowest calls in the measurement were longer than the primary's
and are cut by it. Twenty descriptions over three packs do not establish how well the step reads
other words or a larger library.

The page shows the offer and takes it with the draft. It reads `look_offer` leniently
(`web/packages/app/src/world-draft-api.ts`): an absent or null offer, a state it does not know, or
an `offered` look missing its pack, version, digest or words is no offer, a field it does not know
is passed over, and none of these refuses the draft. Under Describe it, a draft that can be used
says an `offered` look in one line right under the person's words
(`web/packages/app/src/ui/world-description.ts`): the look by the title the host's list gives its
pack, the name of the model whose call answered (the last completed call in
`look_offer.execution`), and `look_words` as typed. `unavailable` is one line saying that no look
was chosen this time and the town is drawn in the look shown; `none` and no offer are no line.
The draft's line of what is not in the town yet comes right after it and leaves out every phrase
the shown look was chosen from (a left-out phrase that lies within one of `look_words` or holds
one, without regard to case), so the page never says of the same words both that they chose the
look and that they are not in the town.

"Use these values" takes the offered look with the values
(`web/packages/app/src/composition/town-look.ts`): the Look row above Create this town shows it,
says it came from the person's words and keeps Change look, and Create this town sends exactly the
offered `pack_id`, `version` and `manifest_sha256` as its `style_pack` (section 10). Nothing is
made or saved before that. A look the person chose themselves in the Look sheet is never replaced
by an offer: it stays, the line says so, and one press on the line takes the offered look instead.
A look the person chooses after taking an offer is the one the town is made in.

The look follows the draft that is taken, unless the person chose the look themselves. Taking a
later draft whose offer is `none` returns a look that came with an earlier draft to the host's
default: the Look row says what it says for that look and quotes none of the earlier words, and
Create this town names no pack. A look the person chose in the Look sheet, or took by the one
press on the line, stays. Taking a draft whose offer is `unavailable`, or whose answer carries no
offer, changes nothing: the look shown stays the one the town is made in.

An offered pack the host's list does not hold has no title to say, so the page neither shows nor
takes it. A version the host no longer holds when the town is made is refused as section 10
states, in the words Create a world says any refused making in, and the draft, its values and the
look stay on the page. `web/packages/app/test/world-description.test.ts` holds the reader and the
line to this section's table, and `web/packages/app/test/town-look.test.ts` holds the taking, the
look following the draft, and the request.

## 11. A workspace's own packs

A creator's own pack is kept in their workspace and never becomes a library pack. One migration
(`a_workspace_keeps_its_own_style_packs`) holds it; `exulanica/world/workspace_style_packs.py`
records and reads it; section 11.1 is how one arrives and is served. A world wears one through its
appearance (section 10), which the appearance routes do not yet offer a person; the command that
publishes one is planned and not built.

| Part | What it holds |
| --- | --- |
| A version | Its canonical manifest and the creator's declaration, each with its digest; its pack id (never in the project's `exulanica.` namespace) and version; the declared rights (own work, under `LicenseRef-Exulanica-Own-Work`; or licensed work under `CC0-1.0`, or `CC-BY-4.0` with the attribution it came under); the base it is drawn on, a library version or one of the workspace's own; its files' count and bytes; its preview's digest; and the admission's receipt. Unique by manifest digest, and among live versions by pack id and version (`workspace_style_pack_version_identity`, a partial unique index over versions not erased). An erased version's pack id is derived from its digest under the reserved prefix `erased.`, which no live version's pack id or base, library or workspace, may take |
| Its files | Every file the manifest lists, by path, digest, size and media type, in its order. The bytes live in the workspace's own `workspace-style-packs` namespace |
| Its check | One per version: requested, running under a lease, then ready, failed or cancelled. A failure is `interrupted` (its time bound or its worker stopped it, and it may be asked again), `refused` (its pieces broke a rule, which the same bytes always will) or `base_unavailable`; cancelled is `withdrawn` or `deleted` |
| Its withdrawal | The creator ending the version, once and for good |
| A publish request | The creator asking for a ready version to join the shared library, with the licence they grant the project (`CC0-1.0`, or `CC-BY-4.0` with its attribution) and their statement. Only the version's creator may ask, only while it may be worn, and a licensed version passes on only the licence and attribution it came under. Only a host command publishes, and only on such a request |

A world may wear a version, and its files may be served, only while `workspace_style_pack_wearable`
says so: the version is the asking workspace's, its check is ready, neither it nor any of the
workspace's versions in its base chain (at most eight deep: no version is drawn on a chain already
that deep) is withdrawn, the workspace is not
erased, and every file is still held. A version is recorded drawn only on a workspace base that may
be worn then, and becomes ready only if its base chain may still be worn, so a base withdrawn while
the check ran leaves the version failed as `base_unavailable` rather than serving the withdrawn
base's files. A version another live version of the workspace is drawn on is not withdrawn: the
refusal (`style_pack_is_a_base`) names the versions drawn on it.

Bounds, each enforced by the schema or by the repository under the workspace's lifecycle lock:

| Bound | Value |
| --- | --- |
| Live versions in a workspace (not withdrawn, not finally failed) | 16 |
| Their bytes: files, and each version's manifest, declaration and receipt | 256 MiB |
| A declaration, a receipt, a check's report | 64 KiB each |
| Checks waiting or running in a workspace, a check asked again included | 4 |
| A workspace's own content: assets, style pack files and every unerased version's documents together | `EXULANICA_WORKSPACE_ASSET_RETAINED_BYTES` ([workspace assets](workspace-asset-admission.md)), each namespace's bytes counted, withdrawn ones included until the workspace is erased; an asset's admission and preparation count the style pack documents as a style pack's recording counts the assets |
| Upload attempts a UTC day | 32 a workspace and 512 the installation, counted by `style_pack_attempt`; an attempt the installation refuses still counts for its workspace, and a limit below one admits no attempt and counts none |
| Every workspace's retained style pack bytes, files and documents | the installation's ceiling, checked by `style_pack_installation_bytes_admit` against a total the inventory's and the versions' trigger keeps and a workspace tombstone's trigger lowers by the documents it erases, under that total's row lock, so two uploads cannot both take the last room |

The counters and the total are written only by those security-definer functions, the inventory's and
the versions' trigger and a workspace tombstone's trigger, each run as `exulanica_definer`; the
runtime role may read them and write none of them. A workspace's versions, files,
withdrawals and inventory are insert-only for the runtime role, and each table is under row-level
security by workspace.

Withdrawal hides and does not erase: a withdrawn version stops being worn or served and its pending
check is cancelled, and its bytes stay until the workspace is erased. A workspace tombstone cancels
every check still to finish; clears everything the creator chose or wrote (both documents, the
attribution, every file path, every check's message and report, every publish request's
attribution and statement), replaces each pack id with one derived from its version's digest and the
receipt with a fixed marker, keeping digests and sizes; and queues every file in the namespace for
the purge (kind `workspace_style_pack`, authorized by `workspace_style_pack_purge_is_authorized`).
The tombstone is complete only once each is destroyed. A restore writes a withdrawal again from its
checkpoint, as every withdrawal in `exulanica/deletion/withdrawals.v2.json`, in the order the
withdrawals were made, and first cancels as `base_unavailable` each unfinished version the restored
database holds that is drawn on the one withdrawn, as its check would have ended. A judge seed
refuses a workspace holding any style pack version, files or none, since they never leave it.

### 11.1 Uploading, checking and serving

`POST /workspace-style-packs` is one `multipart/form-data` body: a `declaration` field
(`exulanica.workspace-style-pack-admission/v1`: the manifest's digest and size, the rights, own work
or licensed under `CC0-1.0` or `CC-BY-4.0` with its attribution, the source the creator names and
the statement they affirm), a `manifest` field holding the manifest's canonical bytes, and one file
part per path the manifest lists, named by that path. It needs `admission.write`, and a browser
session needs its account's creator grant as well, which the operator gives with
`exulanica-creator-grant` ([deployment 5.1.4](deployment.md#514-browser-accounts)); without it the
answer is 403 `creator_grant_required`, before the body is read. A bearer token's `admission.write`
is enough. Past those, it is off unless the installation sets
`EXULANICA_WORKSPACE_STYLE_PACK_UPLOADS` to `on`, answering 503 `style_pack_uploads_off`
otherwise.
It joins the uploads admission class, and its body is bounded at 68,485,120 bytes. The route declares no form parameter,
so the caller is authenticated, holds the permission and their workspace's upload share, and has
the attempt counted before a byte of the body is read; and it holds no database connection while
the body arrives. Anything but `multipart/form-data` is 415; a body the multipart parser refuses (a
part over 256 KiB that is not a file, more than 512 files or more than two fields, a part with
more than 8 headers or a header line over 4,224 bytes) is 422 `invalid_style_pack_body`, as is a
manifest sent as a file or a part named twice.

`exulanica/world/style_pack_admission.py` then decides, in order, with nothing written before the
first refusal:

| Step | Refused as |
| --- | --- |
| The declaration | 422 `invalid_declaration`, `licence_not_admitted` or `attribution_required` |
| The manifest's bytes: at most 256 KiB, the declared digest and size, UTF-8 JSON with no duplicate key, no `NaN` or `Infinity`, at most 32 deep, and exactly its canonical bytes | 422 `content_digest_mismatch` or `invalid_style_data` |
| The manifest, through the reader (section 6), then origin `uploaded`, an id outside `exulanica.` and not beginning `erased.` (the ids an erasure gives), the declaration's licence and attribution, and a base that is a library version or one of the workspace's own versions that may be worn | 422 `invalid_style_data` with its `path`, `licence_mismatch`, or `style_pack_base_unavailable` |
| The parts: exactly the manifest's files, each at its listed size and digest, a piece within its family's file size before it is opened | 422 `invalid_style_pack_body`, `content_digest_mismatch` or `over_budget` |
| Each piece's profile (`exulanica/world/style_pack_pieces.py`): an `exulanica.static-glb/v1` container with one buffer, the binary chunk that buffer and at most three zero bytes, every buffer view packed tightly, used and read byte for byte by its accessors, no `extras`, no images, textures or samplers, names and `asset.generator` at most 64 plain characters, `asset` holding nothing else; and its family's triangles (a second level of detail a quarter of the first's) and materials, from accessor counts | 422 `style_pack_piece_refused` or `over_budget`, with the piece's `path` |
| The preview, walked to its end without decoding (`exulanica/world/style_pack_preview.py`) | 422 `style_pack_preview_refused` |

The preview walk allows only what a plain still picture needs. A JPEG is SOI, one JFIF APP0 of 16
bytes (no thumbnail), DQT, DHT, DRI, one SOF0, SOF1 or SOF2, its scans, and EOI with nothing after
it: no Exif, XMP, ICC profile or comment. A PNG is IHDR, then only PLTE, tRNS, gAMA, cHRM, sRGB and
IDAT, then IEND with nothing after it. A WebP is one `VP8 ` or `VP8L` image, or `VP8X` with only the
alpha flag and its `ALPH` and `VP8 `. One frame, 1 to 2,048 pixels a side. The committed library's
previews carry an ICC profile, so a library pack is not accepted back as an upload until its preview
is re-encoded.

An admitted version answers 201 (200 when the same declaration over the same manifest already made
it), 409 `style_pack_exists` for another declaration over the same manifest, 409
`style_pack_version_exists` (naming the `held` digest) for another manifest at a held pack id and
version, 410 for a withdrawn one, and 429 `style_pack_quota_exceeded` at a bound (`bound` names
`workspace` or `installation` for the attempts). Its check then runs off-request, in the asset
preparation process after each of its passes (`exulanica/world/style_pack_checks.py`): every
triangle of every piece read for its colour, as the browser reads a piece, and held to the pack's
palette or a palette in its base chain; at most 120 s a version, past which it is `interrupted`, and
three attempts, after which it is `interrupted` too. A version that passes is ready.

| Route | Answer |
| --- | --- |
| `GET /workspace-style-packs` | `exulanica.workspace-style-pack-list/v1`: every version, with its state and its check's failure |
| `GET /workspace-style-packs/{manifest_sha256}` | `exulanica.workspace-style-pack/v1`: one version, and its manifest once ready |
| `GET /workspace-style-packs/{manifest_sha256}/files/{content_sha256}` | A file of a ready version or of a workspace version in its base chain: copied and verified into a file of the request's own, then the final read check asks `workspace_style_pack_wearable`, then the bytes are sent with no connection held; 409 `style_pack_not_ready` before the check passes, 410 once withdrawn |
| `GET /workspace-style-packs/{manifest_sha256}/archive` | A ready version as one uncompressed POSIX tar archive (`application/x-tar`): `manifest.json` (the canonical manifest and one newline) and every file at its manifest path, each copied and verified, then the final read check, then sent; every header field but the name and size fixed, a path past 100 bytes in a pax header. At most 2 archives a process and 1 a workspace at a time (503 `capacity_exhausted` or 429 `workspace_capacity_exhausted`, `capacity` `archives`) |
| `POST /workspace-style-packs/{manifest_sha256}/withdraw` | The version, and `withdrew`; 409 `style_pack_is_a_base` while a live version is drawn on it |
| `POST /workspace-style-packs/{manifest_sha256}/publish-request` | `{licence_id, attribution, statement}`: 201 with the request; 403 `style_pack_not_creator`, 409 `style_pack_not_ready`, 422 `publish_licence_not_held` |
| `GET /world/style-packs` | The library's packs, each with `source` `library`, and `workspace_packs`: this workspace's ready versions, each with `source` `workspace` |

Writes need `admission.write` and reads `world.read`. Another workspace's version or file answers
exactly as an invented digest does (404 `unknown_reference`). Every answer of these routes, refusals
included, carries `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none';
sandbox`, `Content-Disposition: attachment`, `Cache-Control: private, no-store` and
`Cross-Origin-Resource-Policy: same-origin`, so a creator's bytes are never sniffed, framed, cached
or read by another origin.

No hosted model request carries a workspace pack's text or picture: its pack id, title,
description, tags, authors, attribution, source reference, statement, swatch, preset and role keys,
file paths and preview are a creator's words and choices. An import contract in `pyproject.toml`
holds every module with a registered hosted call site away from the modules that keep, admit, check
or serve a workspace's packs, indirect imports counted, and `tests/test_hosted_boundary.py` runs
every registered call path over a workspace holding a ready pack with a sentinel in each of those
strings and in its preview, and finds none in any request.

### 11.2 Looks made of generated pieces

A world's own look made of [generated pieces](generated-pieces-contract.md) is a version of a
workspace's own pack of origin `generated`: drawn on a library pack, with pieces the generation
worker made at a person's request in place of some of its own (`exulanica/generation/looks.py`
builds its manifest). One migration (`a_workspace_look_wears_generated_pieces`) adds it to section
11's tables, a second (`a_held_piece_is_found_by_an_index`) indexes the held clause, keeps a generated
version's base a library one and closes publication to it, and
`WorkspaceStylePackRepository.record_generated` records one; no route uploads one.

| Part | What it holds |
| --- | --- |
| The version | Origin `generated`; a pack id in `generated.`, which the schema keeps for these versions and the upload admission refuses; licensed `CC0-1.0` with no attribution; drawn on a version the library holds, which the schema requires of every generated version. Its declaration is the worker's (`exulanica.workspace-style-pack-generated-declaration/v1`): whose request it was and the licence, and no words of anybody's. Its receipt names what it is made of (its base chain and pieces, by which a world applying the same pieces again wears it rather than another) and the pieces' receipts |
| Its files | Each a generated piece by digest, with source `generated_piece`: the bytes live in the one shared `generated-pieces` store, not in the workspace's namespace, and no inventory record names them |

- **Held.** A generated piece is held while a passed output of the workspace (`piece_output`,
  `within`) names its digest. A version is recorded only once every piece is held, becomes ready
  only while each still is, and `workspace_style_pack_wearable` asks the same before it is worn or
  served. An output of another workspace never holds a piece here. The record's content digest is
  64 lower case hexadecimal digits, or it is refused (`content_digest_unreadable`).
- **Checked.** The machine that made a piece judged it, and this server judges it again. The check
  reads each piece from the shared store and holds it, before the palette, to the pack-piece profile
  and its family's budget (file size, triangles by the variant's width, materials), as the upload's
  admission holds an upload's pieces with the same helper (`hold_pieces`); a piece outside them ends
  the check `refused`, naming the piece and the code (`style_pack_piece_refused` or
  `over_budget`). Then it holds every piece to the base's palette, as an upload's are.
- **Never published.** A generated look is not offered to the shared library: its pieces are the
  generation worker's, made at a person's request, not a creator's own work. A publish request for
  one is refused 422 `publish_generated_look`.
- **Bounds.** A person's bounds (16 live versions, 256 MiB) count their uploads only. A workspace
  holds at most 64 live generated versions (`workspace_style_pack_generated_limit`): every distinct
  set of pieces a world wears is one, and applying a set again reuses its version. Generated pieces
  count toward no byte total; each version's documents count as every version's do. A generated
  version's check takes one of the four places the workspace's checks share.
- **Erasure.** A workspace tombstone erases a generated version as it erases every version (its
  documents, pack id, file paths and receipt), and the piece batch migration's trigger deletes the
  workspace's outputs, so the version is never worn or served again. Nothing is queued for its
  pieces and the tombstone's completion never waits on them: the shared bytes stay, holding nothing
  of the person, as [generated pieces](generated-pieces-contract.md#53-the-shared-store-of-generated-pieces)
  says. An erased version's file rows keep each piece's digest and source, as every erased
  version's rows keep digests and sizes; they name nothing of anybody, so a sweep of the shared store
  that keeps a piece while a row names it does not count them.

## 12. A world's setting

A pack is shared and says how a world is drawn. A **setting** is one world's own, drawn over the
pack it wears: the hour and sky, the colours it restates, what lies on its roofs and ground, and the
ground beyond it. Like a pack it never says where anything is, so stating one moves nothing a
person walks on and nothing traffic drives. A world that states none is drawn as its pack states,
as every world was before settings.

A setting is a document, profile `exulanica.world-setting/v1`, of whole numbers and identifiers, and
its identity is the SHA-256 of its canonical bytes, written as a manifest's are.

| Field | What it holds |
| --- | --- |
| `origin`, `provenance` | `authored`, or `drafted` with the model id, prompt version and execution id of the call that drafted it |
| `parts` | The named parts it was composed from, one an axis, in the axes' order; none for a setting stated outright |
| `light` | Changes to one of the pack's own presets (`from`), each a dotted path of a preset replaced whole, such as `sun.elevation_mdeg` or `fog`; or none |
| `surfaces` | The colour a look role's surfaces are drawn in, with an emission, whatever the pack dresses the role with |
| `up` | The colour a look role's upward faces take, or null for none |
| `swatches` | Swatches of the pack restated: a colour, an emission, or both |
| `edge` | The colour of the ground beyond the world; or none |

**Nothing of a person.** A world's appearance versions are history no erasure rewrites, and a
setting is stored on one. So a setting holds no words and no digest of words: every value is a
whole number, a colour, a look role, a key or an identifier of a shape that holds no sentence, and
both readers refuse any other key. The shapes are held, not only the keys: a drafted setting's
execution id is a UUID, none of its three identifiers may be 64 hexadecimal characters (the shape
of a digest), and `parts` names only axes and parts the rules file lists, so a part's name is
never a caller's own word. A request states only an authored setting: a drafted one says which
call drafted it, which only the host's own drafting step can say, so one a caller states is
refused (`invalid_style_data`, `reference` at `origin`). The words a person typed stay with the
draft that read them.

**Checked against the pack it is drawn over.** `exulanica/world/world_settings.py` is the
authoritative reader and `web/packages/atlas-core/src/world-setting.ts` the browser's. Each reads a
setting's shape, then applies it to the pack with its base chain resolved, and applying it is the
check:

| Rule | Refused as |
| --- | --- |
| The preset a setting changes is read again by the pack reader's own rule for a preset, so a setting states no light a pack could not | the reader's own reason, `shape` or `range`, at `light.changes.<path>` |
| A path a setting may not change: the tone mapping, the sun's shadow filter, contact shadowing, the sky's face size and temporal anti-aliasing are a look's finish and its measured frame cost | `reference` |
| A preset, a swatch or the ground beyond that the pack does not state; a role of a family no surface dresses; an upward face of a role nothing dresses | `reference` |
| A person standing in the open is lit enough to be seen: the sun on level ground plus the sky's image light, through the exposure, at least the rules' floor | `legibility` at `light` |
| A footway, and a crossing's paint, stay lighter or darker than the carriageway beside them by at least a quarter, where the setting changed either colour and both are drawn as colours | `legibility` at `surfaces` |

What a setting may change, both floors with the pictures and figures they were judged from, the
names a setting's `parts` may state, and the bounds (64 roles, 64 upward faces, 64 swatches, 8
parts: a safety bound of storage, since a setting is stored with each appearance version) are
data, `assets/style-packs/settings/setting-rules.v1.json`, which both readers read. A stored
setting is checked against these rules again whenever its world's appearance is written, and the
page draws by the rules it was built with. So under this rules profile a floor is only ever
lowered, a bound only ever raised and a name only ever added: a setting that was accepted is
never refused or left undrawn by a later edit of the file. A tighter figure is a new rules
profile, which new settings state and old ones do not. `setting-cases.v1.json` beside it holds
both readers to the same verdict on
every case: the same refusal by reason and path, or the same digest of the setting and of the pack
as drawn (`tests/test_world_settings.py`, `web/packages/atlas-core/test/world-setting.test.ts`).
Every look the library holds stands in light its own setting rule accepts, in every version it
still serves.

**Named parts.** `setting-parts.v1.json` lists parts a person or a model chooses by name, one an
axis, each stated for any pack:

| Axis | Parts |
| --- | --- |
| Hour and sky | Dawn mist, clear noon, dusk, overcast, thick fog, night |
| Ground and beyond | By the sea, desert sand, snowfields, wheat fields |
| Cover | Snow |

The host composes the chosen parts into the exact setting for one pack (`compose_setting`), in the
axes' order, a later part's colour for a role replacing an earlier one's: a part's swatch the pack
does not state is left out, its colour for a family's upward faces becomes one entry for each
surface of that family the pack dresses, and its light is the first of its alternatives whose
preset the pack states, so dusk is a pack's own evening preset where it has one. The setting stores
the figures and the parts' keys, so a later version of the parts file never changes a world. Each
part, composed for every look of the library, is drawn by the browser's reader and held to the bound
every look's own light is held to, a surface in shade lit at most twice as blue as red
(`web/packages/atlas-react/test/world-setting-parts.test.ts`, over
`setting-composed.v1.json`, which `scripts/style_packs/composed_settings.py` writes).

**Stored and asked for.** A world's style version states its setting beside its pack: one nullable
column (migration `a_world_states_its_own_setting`), a document only while the version names a
pack. A request names it with the pack: `style_pack.setting`, the document outright, or
`style_pack.setting_parts`, a part for an axis, which the host composes; both together are refused.
It is checked against the manifests of exactly the pack version the request names, when it is
previewed and again when it is applied or rolled back to, and one the pack cannot be drawn in is
`invalid_style_data` with the reader's reason and path. A preview that names no pack keeps its base
version's pack and the setting drawn over it; a pack named with no setting is drawn as it states.
`POST /worlds/generated` takes the same `style_pack`, so a town is made already in its setting, and
a setting that is refused makes no town. A version's answer states `setting` and `setting_sha256`
inside `style_pack` only for a world that has one. When a world's look takes generated pieces in or
gives them back (section 11.2), the world's setting stays with it. `GET /world/style-packs` lists
the parts (`settings`: the axes in order and each part's title and description, never its figures).

**Drawn.** The page applies the setting to the resolved pack before anything is drawn
(`prepareWorldLook` in `web/packages/app/src/world-look.ts`), and the result is a resolved pack, so
the light, the surfaces, the pieces' swatches and the ground beyond are drawn by the code that draws
any pack. A setting the pack cannot be drawn in is never stood in for: the world is drawn as its
pack states, and the shell's `data-world-look` says the setting was not drawn and why. The Look
sheet shows one choice an axis under a look's words, "As the look has it" or a named part, and
saves a changed setting over the look the world wears or with another look.

**Limits.** A person chooses among the named parts; nothing drafts a setting from a description
yet, and no route previews a setting on the open world before it is saved. The sea is the flat
ground beyond the world in a sea's colour, with no shore. The ground beyond is drawn in its own
colour whatever the light, so at night it reads lighter than the town. Lit windows are a look's
own pieces: night raises their glow where a look has them, and a look with none shows dark
windows. A look draws a tree's leaves from its own texture, which a setting cannot colour, so no
part turns leaves. Two legibility floors were judged from pictures of generated towns and the
shipped looks, not measured with people.

### 12.1 A setting offered from a description

A person who describes a world in words (`POST /worlds/specification/drafts`) is offered the
setting the words ask for, if any. After a draft that is not refused, and after the look offer
(section 10.1), the route makes one more short call of its own
(`exulanica/selection/setting_choosing.py`, the manifest role `setting_chooser`), shown only the
description as it was sent to the drafter, every saved name replaced, and each named part's axis,
key, title and description. The answer is one listed part or none for each axis, with up to four
phrases copied from the description that chose them. Code decides what is kept: a part the list
does not hold is outside the answer's form, and a phrase not found word for word in the
description, parts with no words or words with no part is refused, told why once, and on a second
refusal the step answers none. The answer is the draft response's optional `setting_offer`:

| `state` | Meaning |
| --- | --- |
| `offered` | `parts` names a part for each axis the words speak of, an axis's key to a part's key, both of the host's list at `parts_version`; `setting_words` are the person's own words that chose them, as typed, a saved name written back and never sent |
| `none` | The words ask for no listed part, or the answer was refused twice (`reason` `answer_refused`) |
| `unavailable` | The step did not answer: `reason` `timed_out`, `failed`, `request_refused` or `no_allowance`, as for a look |

`setting_offer` is absent for a refused draft and while the host lists no part. The offer is keys
and the person's words, never a setting: nothing is composed, checked or stored until a world is
made naming the parts (`style_pack.setting_parts`, section 12), and the stored setting holds the
parts' keys and figures and none of the words. The step never changes the draft or the look offer:
it sees neither and neither sees it, the drafter's and the look chooser's requests are the same,
byte for byte, with the step and without it, and its own calls are in `setting_offer.execution`. It
spends the same allowance as the draft, through the same client.

The step runs after the look step in the same request, so the answer comes that much later: a
median of about 2.8 s in its measurement, and never more than the role's timeout, one deadline over
the call and its repair together. The role's timeout, 15 s, follows the manifest's timeout rule
(the primary's longest measured call times two, rounded up to 5 s) from its pre-registered
measurement, whose record holds the primary's own calls
([record](evaluation/2026-10-10-setting-chooser-timings.json)): 36 calls, longest 5,761 ms. A call
past the timeout leaves the town drawn as its look states, with no error. Thirty descriptions by
one author over eleven parts do not establish how well the step reads other words. The parts name
no rain, no falling snow and no season, so words that ask for those are answered with the nearest
listed part or none. The answer states one list of copied words for all its parts, so code holds
that the words are the person's and that some stand behind some part, not that each part has
words of its own: an offer may carry a part no word asked for, which is why the page shows an
offer and never takes it for the person.

The page shows the offer; the person takes it or leaves it. It reads `setting_offer` leniently
(`web/packages/app/src/world-draft-api.ts`): an absent or null offer, a state it does not know, or
an `offered` setting with no part or no words is no offer, a field it does not know is passed
over, and none of these refuses the draft. Under Describe it, a draft that can be used says an
`offered` setting in one line under the look's line
(`web/packages/app/src/ui/world-description.ts`): the parts by the titles the host's list gives
them, the name of the model whose call answered, and `setting_words` as typed, as a suggestion
with one press beside it, "Use this setting". `unavailable` is one line saying that no setting was
chosen this time and the town is drawn as its look has it; `none` and no offer are no line. The
draft's lines of what the words did not reach (section 10.1) treat a shown setting as they treat a
shown look: its words are not listed as not in the town yet, and the town is not said to be its
recipe's usual one.

An offered setting is the town's only by that press
(`web/packages/app/src/composition/town-setting.ts`); "Use these values" takes the values and the
look and never the setting. Once pressed, the Setting row under the Look row shows the parts and
the words they came from, with one press to draw the town as its look has it instead, and Create
this town sends the parts as `style_pack.setting_parts` with the look the town is made in, the
host's default named exactly where the person chose none. The host composes the parts for that
look and holds the result to the setting's rules, and a setting the look cannot be drawn in makes
no town and is said in the words any refused making is. A setting the person took is theirs: it
stays through later drafts until they press back to the look's own or take another. Parts the
host's list does not hold have no title to say, so the page neither shows nor takes them. Once
the town is made, its setting is changed in the Look sheet like any world's.
`web/packages/app/test/town-setting.test.ts` holds the reader and the line to this section's
table, the press, the left-out lines beside a shown setting, and the request.

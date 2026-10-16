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
drawn (section 12) and offered from a description (section 12.1). The appearance preview/apply API
accepts ready packs from the world's workspace. The page's workspace-pack choice and upload controls,
publishing a pack to the library, and drafting a pack with a model are planned and not built.

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
| `light` | Named presets (at most six) and the default one; each preset is a sky (its gradient colours, or optionally an analytic daylight sky computed from the preset's sun: `sky.model` with turbidity, Rayleigh and Mie scattering and Mie direction, the gradient's ground still drawn below the horizon), a fog, a sun with a one-tap, three-tap or five-tap shadow filter, image light, contact shadowing and a finish, in whole-number units, and optionally a haze that thins with height (`haze`: density and falloff per million metres, base height, a cap on its depth, and a colour or the sky's horizon), drawn in place of the fog. A preset written before haze existed states none and draws its fog. Optionally, the wind its plants sway in (`wind`: where it blows to in millidegrees from east toward south, how far a swaying piece's top moves along it, its pace, the size of its gusts and the share of the sway that comes and goes with them, a leaf's flutter across it, and the one to eight look families whose pieces sway); absent, nothing sways. Optionally, how much its frame is sharpened after it is drawn (`post.sharpness_permille`, 0 to 1,000), which keeps a frame drawn with temporal anti-aliasing as fine as one drawn without; absent, it is not sharpened. Optionally, the share of a facade's windows lit under the light whatever its sun (`lit_windows_permille`, 0 to 1,000), as a moonlit night needs; absent, each facade lights its windows by its sun (section 7.1). A pack may not choose soft (PCSS) shadows: they alone cost more than a frame ([render look](generated-tile-runtime.md#61-the-render-look-a-style-chooses)) |
| `shading` | `pbr`, `toon` with its bands, or `flat`, and an ink colour or none |
| `edge` | The ground beyond the world: a colour, how far below the tiles it lies, how far it reaches |
| `water` | Optional: how the pack finishes water under physically based shading: a shallow and a deep colour, absorption per kilometre for each colour channel, the depth over which the colour turns from shallow to deep, the width of the foam where water meets what stands in it, and the strength of its reflection. Optionally, its ripple (`ripples`: one to four octaves of drifting noise, each an angle, a cell, a tilt and a drift along its own axes, and the cells a pixel over which each fades; absent, the ripple every water carries today) its caustics (`caustics`: the light the waves gather on what lies under shallow water, its strength, cell, pace and the depth it fades over; absent, none) and how it meets what stands in it and lies under it (`contact`: the share of light a surface under the water keeps, how far light travels down to it per metre of depth, how much the shallow colour needs a surface turned up to the sky, and how far foam reaches across the surface from a solid that meets it, by the water's look role, at most 16 roles, each a `water` role; absent, water meets solids as it always has). Absent, as in every pack written before it, water is drawn as its surface states; nearer packs of a chain replace a base's finish whole |
| `falling_water` | Optional: how the pack finishes a sheet of falling water (a cascade's fall on a site on land), in any shading model: how fast its streaks move down it (`streak_speed_mm_per_s`), how wide and how long a streak is (`streak_width_mm`, `streak_length_mm`), how far a streak lightens or darkens the water's colour (`streak_contrast_permille`), how white the sheet is with the air in it (`aeration_permille`), and how high the foam stands where it lands and its colour (`foam_height_mm`, `foam`). Absent, as in every pack written before it, the page's defaults finish it (`FALLING_WATER_DEFAULTS` in `generated-tile/look.ts`); nearer packs of a chain replace a base's whole |
| `palette` | At most 64 swatches, each a distinct sRGB colour with roughness, metalness and emission |
| `look_family_catalog` | Optional retained appearance catalog pin, `{version, sha256}`; the digest names the exact catalog file bytes. Absence retains version 1 and adds nothing to the manifest's canonical bytes |
| `surfaces` | A look role of a surface family to a swatch, a texture set or one of the pack's own textures, with an optional swatch for upward faces |
| `textures` | Optional: the pack's own textures, by key, at most 32. Each names a listed colour picture and, optionally, a normal and a roughness picture, all JPEG or PNG and of one size, and the width and height in millimetres one repeat covers (100 to 50,000). Absent, the pack carries none |
| `modules` | A look role of a module family to one to eight variants, each a piece file (a palette piece or a textured piece, section 4), an optional second level of detail, the piece's own size, for a fill family where it stretches, and optionally the share of a wind's sway its pieces take (`sway_permille`, 0 to 4,000; absent, the whole of it): a stiff tree takes less than a tuft of grass |
| `cover` | Optional: what grows on a surface look role (at most 64), as the dresser draws it (section 7.1): one to eight `plant` module roles (one named more than once grows more often), how many pieces grow on a hundred square metres (1 to 4,000), the least and most scale in thousandths (100 to 3,000) and a seed. A pack with no base names its own modules. A chain's rules are by look role, the nearest pack's replacing a base's. Absent, nothing grows |
| `facade` | Optional: the windows the building walls of a `wall` look role are drawn with (at most 64 roles), as the dresser draws them (section 7.1): the storey height its rows of windows aim for (2,000 to 12,000 mm), the least bay (600 to 20,000 mm), one window's width and height (300 to 19,000 and 300 to 10,000 mm, its width below the least bay), its sill over its storey's floor and the least wall over it (0 to 3,000 mm each), the storeys from the ground kept clear (0 to 20), the bays a room lights together (1 to 8), the reveal's depth (0 to 600 mm) and shade, the sill ledge's height (0 to 300 mm) and light, the glass's darkening and gloss, the share of windows lit with the sun high and with it low and those two sun elevations (5,000 to 85,000 millidegrees, the day's above the dusk's), the warm, cool and unlit lamp colours, the warm share, the lamps' spread and strength (at most 20,000), a room's depth (500 to 30,000 mm), and the bays a pixel, in thousandths, where the grid starts and ends fading to its average (10 to 4,000 and 20 to 8,000, the end above the start). Shares are per mille. A chain's rules are by look role, the nearest pack's replacing a base's. Absent, no wall has windows |
| `climb` | Optional: what climbs a structure look role's walls (at most 64), as the dresser draws it (section 7.1): one to eight `plant` module roles (one named more than once grows more often), the faces of the building's box it grows on (`front`, `back`, `left`, `right`, the right as a viewer facing the front sees it), optionally only the faces within an angle of the direction toward the sun (`sun_within_mdeg`, 0 to 180,000), the share of a face's length covered (1 to 1,000 per mille), the least and most share of the building's height a plant reaches (1 to 1,000 per mille) and a seed. A pack with no base names its own modules. A chain's rules are by look role, the nearest pack's replacing a base's. Absent, nothing climbs |
| `trail` | Optional: what hangs over the edges of a ground look role where its land falls away (at most 64, each a `ground` role), as the dresser draws it (section 7.1): one to eight `plant` module roles (textured; one named more than once grows more often), the share of an overhanging run of the edge covered (1 to 1,000 per mille), the least and most share of the face below the edge a plant hangs down (`hang_permille`, 1 to 1,000 per mille, the least not above the most) and a seed, and optionally only the edges facing within an angle of the direction toward the sun (`sun_within_mdeg`, 0 to 180,000), the least drop below the edge (`drop_mm`, 200 to 20,000) and the least slope of the face below it (`slope_permille`, 300 to 20,000); a figure the rule leaves out is the page's and is not written into the manifest. A pack with no base names its own modules. A chain's rules are by look role, the nearest pack's replacing a base's. Absent, nothing hangs over an edge |
| `land_cover` | Optional: what grows on the near land a site stands on, as rules by key (at most 16), as the dresser draws it (section 7.1). Each names the surface role the land is drawn in where it grows (`role`: `land`, the ground it is drawn in where no band wins, or a band key of the land's surface catalog such as `sand`, `planted` or `rock`; a role no band names grows nowhere), so one role may grow several rules, each at its own density; one to eight `plant` or `prop` module roles (textured; one named more than once grows more often), how many pieces grow on a hectare (1 to 400,000), the least and most scale in thousandths (100 to 3,000), a seed, and optionally a slope window in thousandths (0 to 20,000), a height window in millimetres above the sea, a reach in millimetres from the place's own rectangle, and groves (`clump`: a grove's least and most radius in millimetres, 1,000 to 200,000; about the share of the land the groves cover in thousandths, 1 to 999; and the share of the rule's pieces that grow in them in thousandths, 0 to 1,000, the rest growing between; absent, the pieces lie evenly). A pack with no base names its own modules. A chain's rules are by key, the nearest pack's replacing a base's. Absent, nothing grows on the land |
| `files` | Every file the pack carries, in path order: path, SHA-256, size and the media type its extension states (`model/gltf-binary` for `.glb`, `image/jpeg`, `image/png` or `image/webp` for a picture); every file is a variant's piece, a texture's picture or the preview |

A pack with no base states its light and shading. A pack drawn on a base states only what it changes:
its swatches, surfaces, modules, presets, shading and edge replace the base's, and anything it leaves
out is the base's. A chain holds at most four manifests.

Catalog selection is explicit rather than inherited: every manifest in a base chain either omits
`look_family_catalog` or states the same version and digest. A mixed chain is refused after base
identity checks, before resolving its appearance. A generated derived look preserves its base's
explicit pin. Readers accept only retained catalog versions with matching file digests, never a
manifest-supplied path, URL or latest-version lookup.

A profile changes without breaking a manifest written under it. A field added within a profile is
optional, and its absence keeps the meaning a manifest had before the field existed: `preview` came
after the first packs were published, and a manifest without it names no picture. A change that a
manifest written earlier could not meet needs a new profile, which readers read beside the old one,
so every published version stays readable.

## 3. Look roles

A look role is `family.leaf`. The families, how each is fitted and how a pack dresses it are the
world kinds' look-family catalog, which both readers are given rather than copying; leaves are open. A pack
dresses look roles only, never a slot, an engine role or a position.

Appearance catalog version 2 retains the version 1 families and changes the optional roof module's
fit from `surface` to uniform `contain` within the served roof slot. A pack opts into it through
`look_family_catalog`; a pack without that field keeps version 1. This selection does not change
the kind catalog, a saved canonical drawing, support or navigation. A roof module still needs to
respect the roof envelope and usable openings; selecting a catalog is not a clearance proof.

Appearance catalog version 3 retains version 2 and changes the structure family's fit from uniform
`contain` to `fill`, from 800 to 1,250 per mille: a building's piece meets the box the world made on
each axis, by repeating the bays or storeys its variant states, by stretching a plain run it states,
or scaled within those bounds, so a dressed building stands as large as the building people walk
round. A slot no variant meets keeps the engine's own building. A pack opts in through the same pin;
a pack pinned to version 1 or 2 reads as it was made.

| Dressing | Families | What the pack supplies |
| --- | --- | --- |
| Surface | ground, path, road, water, wall | A swatch, a texture set or the pack's own texture |
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
([`surface-material.v2.json`](../assets/catalogs/world-kinds/surface-material.v2.json); version 1 is kept
beside it, and version 2 moved six of its colours and nothing a leaf is read by) states
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
| Fill | Each axis meets the box: by its repeat zone where the variant states one, by its stretch zone where it states one, else scaled within the family's bounds (800 to 1250 per mille for doors, windows and, in catalog version 3, structures); a box that leaves a zone no length, a repeat whose copies fall outside the bounds, or a scale outside them, passes to the next variant, then none |
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

A fill variant may instead state a repeat zone per axis (`repeat_mm`, optional, in the same order
and units; an axis stretches or repeats, not both). The zone's content is drawn a whole number of
times, every copy scaled alike so the piece meets the box exactly: the count is the one whose copy
scale is nearest 1 by ratio (the fewer copies on a tie), at most 64 an axis, and every copy lies
within the family's bounds, else the variant does not fit. What lies below the zone keeps its place
and what lies above it follows the last copy, so a building keeps its end walls, ground storey and
cornice and repeats its bays across and its storeys up: a front of 600 mm ends about a 3.8 m bay
meets a 20 m box with five bays at 989 per mille. Up a building whose drawing states its storey
height, the count is instead the one whose copy is nearest that storey by ratio: each copy is
exactly a storey tall where what lies below and above the zone is a whole number of storeys (a zone
spanning the piece's height draws one copy for each of the building's storeys), and otherwise as
near it as a whole number of copies allows. Across a building whose drawing states its arcade's
bays, the count is those bays: the arcade spans the front between its 200 mm end walls in equal
bays, so each copy is exactly one of them where what lies before and after the zone is 200 mm each,
and otherwise there are as many copies as bays. Where those copies fall outside the family's bounds,
and along an axis the drawing gives no count for, the count is the one above. A variant with no
`repeat_mm` repeats nothing, and its manifest keeps its bytes. Every triangle of a repeating piece
lies wholly below, inside or above each zone on its axis (the check holds this, section 11), so the
page assigns each triangle by its centroid and the copies join without a crack; a triangle of two
zones is drawn once for every pair of copies. A normal in a copy turns by the inverse of the
copy's scale.

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

### 4.1 Textured pieces

A piece whose container holds images is a textured piece: it is drawn in its own pictures, cut out
where its colour's alpha falls under its material's cutoff, and a pack's swatches never recolour it.
It is how a look carries what flat colour cannot: cut-out leaves on a tree, bark, scanned rock. Both
readers hold it to the same rules and refuse the rest by name (`readTexturedPiece` in
`web/packages/atlas-core/src/textured-piece.ts`; `check_piece_profile` and `read_textured_piece` in
`exulanica/world/style_pack_pieces.py`):

- one mesh, drawn by the scene's one node with no transform of its own;
- each primitive triangles, with float `POSITION` and `NORMAL`, float `TEXCOORD_0` and nothing
  else, unsigned short or int indices in whole triangles, and a material;
- each material a base colour texture on the first texture coordinates, optionally a normal
  texture, factors for base colour, metalness and roughness, alpha opaque or cut out by a cutoff
  (never blended), and whether both sides are drawn; nothing else;
- each image a JPEG or PNG embedded in the binary chunk, walked to its last byte by the pack's
  picture probe (`style_packs.probe_pack_image`, the walk section 11.1 describes), every buffer view
  read whole by an image or byte for byte by an accessor.

A textured piece states no stretch or repeat zone: it is drawn whole (section 7). A textured first level's
second level is textured too. The page reads `isTexturedPiece` (the container holds images) to
choose the reader; a piece is one or the other, never both.

## 5. Budgets

A piece is an `exulanica.static-glb/v1` container first
([workspace asset admission](workspace-asset-admission.md)), and its family's budget sits on top of
that profile's limits: `assets/style-packs/piece-budgets.v1.json` states, per family, the triangles
at the first level of detail (per metre of the piece's own width for a tiled family), materials, the
largest texture side and the file's size, and a second level of detail holds at most a quarter of
the first's triangles. A pack's files total at most 64 MiB. One reader reads that file,
`exulanica_pieces/budgets.py`, for the pack reader and the generated pieces alike, so a generated
piece is made against the numbers a pack's piece is held to.

A textured piece is held to the same file size, triangles and materials, and each of its images to
its family's largest texture side (a plant's 512 pixels, a structure's 1,024). Its pictures count
toward the pack's one bound of 64 pictures, beside its textures' (section 2), at admission and in
the check of a look made of generated pieces (`hold_pieces`, given the textures' pictures by
`style_packs.texture_pictures`). A picture counts once by its SHA-256, however many files or maps
carry it (the page decodes a piece's picture once by its digest), so variants that share a picture
spend one place.

## 6. Readers

`exulanica/world/style_packs.py` is the authoritative reader; `web/packages/atlas-core/src/style-pack.ts`
is the browser's, written from the same rules. Each checks every field in the order the schema lists
it, then the rules across sections, and refuses with the first fault by reason and path:

| Reason | What it refuses |
| --- | --- |
| `shape` | An unknown key or a missing one the profile requires, a value of the wrong kind, a fraction, a malformed id, role, path or text, text holding a lone surrogate, a control character or a bidirectional control character, a file whose media type is not its extension's, a texture's picture that is not a JPEG or a PNG |
| `range` | A whole number outside its bounds (one too long for a double included), a value not in its list, fog or toon bands out of order, a soft (PCSS) shadow filter, a stretch or repeat zone outside its piece or of no length, a preview over 512 KiB, a texture's picture over 4 MiB, a texture repeating over less than 100 mm, a pack drawing with more than 64 pictures (its textures' and its pieces' together, each once by its digest), a cover's least scale above its most, a climb's least height above its most or a wall it does not know, a trail's least hang above its most, a wind swaying no family, a facade's window as wide as its bay or wider, a facade's day sun not above its dusk sun, a facade's fade ending where it starts, a land cover window with its least above its most |
| `reference` | A role of an unknown family or of a family not dressed that way, a swatch, texture set, texture, preset or file that is not there, a preview naming no listed file, a listed file nothing uses, provenance that is not the origin, a pack with no base and no light or shading, a stretch or a repeat on a piece of a family that is not fill, cover on a role that is not a surface, a cover piece that is not a plant or (with no base) not one of the pack's modules, a climb on a role that is not a structure, a climbing piece that is not a plant or (with no base) not one of the pack's modules, a trail on a role that is not a ground, a trailing piece that is not a plant or (with no base) not one of the pack's modules, a wind swaying a family the context does not know, a facade on a role that is not a wall's, a land cover piece that is not a plant or a prop |
| `duplicate` | Two swatches of one key or one colour, two files of one path, a wall a climb rule names twice |
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
| Pieces | A pack's pieces are fetched, held to the size and digest their manifest states, read as palette pieces and uploaded once (`fetchPackPieces`, `uploadPackPieces`); every slot's piece is placed by its fit and baked with the others into one mesh per swatch (`dressSlots`). A repeat zone is baked copy by copy; a slot whose copies would bake more triangles than the drawing's `repeatedTrianglesMost` (`atlas-core/src/piece-drawing.ts`, by default 80,000, four structure pieces at their family's budget) keeps its primitive |
| Textured pieces | A textured piece (section 4.1) is fetched with its variant's second level, held to its manifest the same way; each picture is decoded once by its digest, and the upload makes one texture per picture and use (colour in sRGB, a normal map linear) and one material per material of each level, in the pack's shading, all destroyed with the drawing. It is not baked: `placementMatrix` gives the transform the bake applies to a corner, and the pieces of one file are drawn instanced in square cells of the ground (`drawInstancedPieces`), one draw per cell, level and material, culled by the cell's own bounds in the camera and in every shadow cascade. A cell draws the second level beyond a distance proportional to its tallest piece and returns to the first only a share nearer (hysteresis); only the first level casts shadows, and only within a reach. Those four figures (distance per metre of height, hysteresis, shadow reach, cell size), and the shadow reach of climbing and trailing plants (section 7.1), are `atlas-core/src/piece-drawing.ts`'s, defaults with their reasons, beside the render budget. A textured piece stands whole on its base: on a draped slot it is not bent to the land under each of its points, and a slot asking it to stretch or repeat keeps its primitive. A seat's contact copy is its placed triangles either way |
| Vehicles | A traffic vehicle's body is the pack's piece for `vehicle.<body family>`, chosen by the vehicle's id, contained in the record's own size; its `vehicle_body` swatch takes the vehicle's colour as the pack states it (`vehicle_red`); a body family the pack does not dress keeps the traffic's boxes (`packVehicleBodies`) |
| Ink | A shading that draws ink outlines the tiles' opaque surfaces and the pack's baked pieces (`attachTileInk`) |

The app draws a saved generated world in the pack its address names (`?look=toon`, `cozy`,
`finished`, `kits`, or `today` for the tile look: one word for each pack of the library), else the
pack its appearance names (section 10), else
`DEFAULT_WORLD_LOOK` (`web/packages/app/src/world-look.ts`), the cozy town, reading the pack from the
host (section 9). A library pack drawn on another names that base by its manifest's digest, which
the host serves like any version it holds; the page reads the chain down to the pack that names no
base, at most four manifests, and holds each to the id and version the pack above it names
(`prepareWorldLook`). A pack the page cannot read is not stood in for: the world opens in the tile look,
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
slots; nothing it does changes a slot, the walk or the society's seat places, and taking the site down puts every
material back and shows every primitive again.

A person resting at a declared site fixture faces its served front and keeps their recorded
plan position. The renderer finds contact on that fixture's actual transformed triangles,
captured when it mounts or changes appearance, with at most 100,000 module vertices retained
across the site; a seat exceeding that budget has unavailable contact. It tests the upper visible intersection before
accepting a nearly horizontal upward face between the source's height hint and the supported
human-seat ceiling of 460 mm above the slot base. A missing corner, occluding slope, tall face
or absent geometry reports `fixture-seat-contact-unavailable`; it does not use a hidden seat
below it or another object nearby. Contact belongs to the attached saved entry and version,
and is withdrawn with the appearance. Authored catalog seats and town furniture keep their
existing paths. This presentation rule grants no walking support and does not establish full
seated-body clearance or arbitrary seat heights.

| Part | What it does |
| --- | --- |
| Light | The pack's default preset is the site's render look, as it is a town's |
| Resolving | Each slot by its look role (section 3): a slot the engine draws as a primitive takes either a surface or a piece, a surface before a piece at each leaf; a `none` slot, a hole only a pack fills, takes a piece alone |
| Surfaces | A swatch, with its up swatch, becomes the material of the slot's primitive, in the pack's shading. A texture surface uses the same digest-verified texture library and material classes as a town. Copies of primitive meshes carry UVs in physical millimetres along the slot's served frame, including separate strips around openings; their positions, bounds and canonical walk are unchanged. An unavailable or refused texture draws the unavailable pattern. Glazing requests a scene-colour copy and keeps its transparent draw ordering and shadow rules |
| Materials | A leaf the pack does not state is drawn in the material its words name (section 3): the pack's own surface for that material, or the surface material catalog's colour in the pack's shading. A leaf that names none takes its family's `default` and is counted on the canvas |
| Ground beyond | A pack's ground beyond the world is its own colour for a town. Beyond a site that is open to the sky, the pack's plane is drawn in whatever the site's base ground is drawn in (the one ground its drawing lays over its whole extent, once dressed) and lies just under it, so a desert's sand runs to the pack's reach. It reads the base ground only, never a zone or an area at the site's edge; an indoor site keeps the pack's own. The canvas states the base ground's look role (`data-site-ground-beyond`) |
| Scenery beyond | On the ground beyond a site stands what the site scenery catalog states for the material of the site's base ground ([`site-scenery.v1.json`](../assets/catalogs/world-kinds/site-scenery.v1.json), read by [`site-scenery.ts`](../web/packages/atlas-core/src/site-scenery.ts)): trees beyond a forest's floor, a low stone here and there beyond sand, a tree here and there beyond grass, and nothing beyond any other ground. **It is scenery, like the horizon: not a part of the world, not listed, not walked, not picked, and it hides nobody; a creator's world document states none of it.** The page makes it from the base ground's material and the world's own identity, in whole millimetres, so one world has the same trees every time and on every machine; it is never a slot of the site's drawing, so the walk, a click, what hides a being and everything else that reads the drawing are the same with it as without. It stands only beyond the site's rectangle, from the catalog's margin out to its reach, thinning toward the site where the entry says so, so a wood meets a clearing raggedly and not as a row of trunks. A tree is the pack's own tree piece (its `plant` module) scaled to each tree, baked into the pack's meshes beside the site's and not outlined, or drawn instanced where the piece is textured; where a pack has no plant, a plain trunk and crown in the pack's shading. A stone is a plain low shape in every pack, since no pack holds one. Each entry's count is a rendering budget stated with its reason and no fact of any world: where the ground holds more, the nearest to the site are kept (a wood of 1,200 trees is 216,000 triangles). Limits: a look that draws no ground beyond a site (the tile look) draws no scenery; an indoor site has none; the site's own grounds are still rectangles, their edges broken as Borders below says, so from above a clearing is square; no water is drawn beyond any site, an island's included; and a town has none of this, having no site rectangle |
| Inside | A site whose extent is indoors is drawn as a room, by the site interior catalog ([`site-interior.v1.json`](../assets/catalogs/world-kinds/site-interior.v1.json), read by [`site-interior.ts`](../web/packages/atlas-core/src/site-interior.ts)): a ceiling, a slab of the stated thickness over the whole extent lying on the top of the tallest box the site draws (in practice its walls) and drawn in what that box is drawn in once the site is dressed; and the pack's one sun turned into the light under it, shining from the stated tilt off straight down, at the stated share of the sun's own strength and in the stated colour. The ceiling casts no shadow, since the light is under it; walls and fixtures still do. The ceiling is drawn beside the site's slots and is none of them: it is not listed, not walked and not picked, and the walk, a click and what hides a being read the drawing as before. An open site has neither. Limits: there is one light, not a lamp in each room, so a room is lit evenly and a corridor as a hall is; a doorway in the outer wall shows the pack's sky beyond it; a building inside an open site is not an indoor extent and has no ceiling of this kind (its roof is its own slot) |
| Roofs | The drawing serves a roof as a slab or as one prism. Where the roof's leaf names a material the roof form catalog shapes ([`roof-form.v1.json`](../assets/catalogs/world-kinds/roof-form.v1.json), read by [`roof-form.ts`](../web/packages/atlas-core/src/roof-form.ts)), the page draws it in that form instead, in the same material: a ridge at the material's pitch, as thick and overhanging as far as stated, its ridge along the footprint's longer side, the way the door faces, or as served; a tent, whose two sides run from the ridge to the ground and whose ends are canvas with the doorway left open; a slab with a parapet round it. The drawing's flat or pitched still decides which of the two a roof is. The wall pieces inside a tent's footprint are not drawn and stay in the walk. A roof is drawn only: no form reaches the walk, a door or a seat |
| Patterns | A surface whose leaf names a material is not one flat colour. The surface pattern catalog ([`surface-pattern.v1.json`](../assets/catalogs/world-kinds/surface-pattern.v1.json), read by [`surface-pattern.ts`](../web/packages/atlas-core/src/surface-pattern.ts)) states a pattern for each material at physical scale: courses of blocks with broken joints, boards, the strokes of thatch, seams, ripples or a soft grain, with its periods in millimetres and its strength. The dresser draws it in the surface's colour chunk from each point's place in the world ([`pattern-material.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/pattern-material.ts)), so it needs no texture image: across the ground on a face that points up, along and up a wall on any other, a pattern of lines darkening toward the pack's ink where it draws ink, a mottle or a ripple (and every pattern where the pack draws none) toward the colour's own shade, and fading where it would be finer than the picture. It is drawn on the catalog's colour and on the pack's own surface for the material alike, except a surface that colours its upward faces apart. Colour only: nothing is raised. The canvas states how many slots are patterned (`data-site-patterned`) |
| Borders | Where two grounds of a site meet, the line between them is broken. The ground border catalog ([`ground-border.v1.json`](../assets/catalogs/world-kinds/ground-border.v1.json), read by [`ground-border.ts`](../web/packages/atlas-core/src/ground-border.ts)) states, by surface material, a small ragged break at the edge itself (`edge_mm`) over a gentler wander of the line (`wander_mm`, over `wander_period_mm`), small against a path's width so a path keeps its width and its direction. One rule, with no table of pairs: **the upper ground breaks over the lower by its own edge, and the lower is drawn on under it**, so a break shows the neighbour and never a third ground. Which is upper is the drawing's own layering (the higher, and of two at one height the later), with one exception each entry states: water lies under whatever ground it meets (`lies`). At a shore the land breaks over the water in tongues, by the land's own edge, and the water is never drawn past its own ruled line. The ground a site lays over its whole extent breaks over the ground beyond, out of doors and where a look draws one; both wear one material today, so that edge shows nothing until they differ. A material with no entry (a floor, a deck, a carpet, concrete) and a leaf that names no material keep a ruled edge, and a ruled ground drawn higher simply covers what is under it. **Colour only: the walk, every box, what hides a being and a click read the drawing's rectangles as before, so within a border the picture and the walk may disagree.** Nowhere by more than the catalog's greatest reach (a wander and half a break; 460 mm in version 1), which no entry may put past the least `shore_reach_most_mm` a water states (600 mm): the reader refuses a catalog that does. At a shore the picture may show land where the walk says water, up to that reach, and never water where a person walks. A being in a border is drawn where it stands; a border hides nobody. The dresser works it in the ground's colour chunk from each point's place in the world ([`border-material.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/border-material.ts)), beside its pattern and on the pack's own surface alike, the same in every pack: each ground states its own rectangle and those of at most four neighbours (the most overlapping are kept and the rest counted), and is drawn larger than its rectangle by the greatest reach. The working is off unless a ground states values, so a ground never given them is drawn whole. The canvas states how many grounds are worked (`data-site-borders`). Limits: a rectangle stays a rectangle with a rough edge, so a lake is a rectangle with a rough bank, no path bends, and a clearing is still square from above; it is flat, with no bank, kerb or step; where a pack draws ink, a ground with a broken edge is not outlined, since its mesh's edge is not the edge drawn, and a ruled ground keeps its line; the working is GLSL for the WebGL2 device the page asks for, and on a WebGPU device no ground is worked and each keeps its ruled rectangle; a site drawn with no pack (the tile look) keeps every ruled edge; and a town has none of this |
| Pieces | Placed by the family's fit and baked one mesh per swatch, as a town's are (`dressSlots`), or drawn instanced where the piece is textured, its level chosen by where the person looks from; the slot's primitive is hidden while its piece stands. The canvas states how many textured pieces stand instanced and in how many cells (`data-site-piece-instances`), and the site's texture bytes count their pictures |
| Cover | Where the pack states `cover` for a slot's look role, or else for the role its surface is drawn in (section 3: the pack's surface its leaf's material names or its family's `default`, or the catalog material's role; a leaf whose own surface the pack states takes its own rule alone), its plant pieces grow on the slot ([`ground-cover.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/ground-cover.ts)): as many as the rule's density gives the slot's area, each at a point inside the slot's rectangle, one of its pieces and variants, a turn about up and a scale between its least and most, drawn from the rule's seed and the slot's identity, so a world grows the same cover every time and on every machine. A piece grows only on a slot the site draws as a plane or a box (on a box, on its top), never where another slot stands on it (anything that is not a plane) or another plane's surface lies above its own at the piece's point, and on land never where a body of the land's water stands above the ground there; heights are compared at each point, so a lawn rising out of a pond's basin grows to the water's edge, and a draped ground's pieces each stand on the land under them. Pieces are drawn instanced in cells as textured pieces are, at their first level within reach of the camera and their second beyond; a cover piece must be a textured piece: admission refuses an upload that names a palette piece as cover, and one a pack drawn on as a base holds grows nowhere. **Cover is presentation, like the scenery beyond: not a part of the world, not listed, not walked, not picked, and it hides nobody.** A site grows at most 40,000 pieces (`COVER_PLACEMENTS_MAX`), a guard on the page's work that counts only pieces that grow, never a point refused under a path, a building or water: past it the pieces met first keep their places and the rest are counted as left out. Finding where pieces grow tries at most 160,000 points in all, grown or not (`COVER_TRIES_MAX`), and the points never tried are counted. The canvas states what grew (`data-site-cover`: pieces, slots growing any, pieces left out, points untried), and `data-site-piece-instances` counts them with the rest. Limits: a slot is a rectangle, so cover runs to its ruled edge, under a broken border's tongues; cover is not thinned toward a path or a wall |
| Climb | Where the pack states `climb` for a building's look role, or else for `structure.default`, its plant pieces climb the building's walls ([`climbers.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/climbers.ts)): on each face of the building's box the rule lists, and where it states `sun_within_mdeg` only on a face whose outward direction lies within that angle of the direction toward the sun the look is drawn with (a look drawn with no sun grows on every face listed), plants are chosen in turn from the rule's seed and the building's identity, each one of its pieces and variants reaching a height drawn between the rule's least and most share of the box's height, until their widths cover the rule's share of the face; they stand evenly spaced along it, rooted at the building's base, each scaled whole to its height (the plant family's contained fit) and turned to face out, its back 30 mm in front of the face. A climbing piece is authored against a wall in the plane z = 0 behind it, its leaves toward +Z, and must be a textured piece: admission refuses an upload that names a palette piece, and one a pack drawn on as a base holds climbs nowhere. Climbing plants are drawn instanced in cells as cover is and sway with the look's wind by their variant's `sway_permille`; they cast a shadow from their first level only within the drawing's `climbShadowReachM` of the camera, by default nowhere, since a plant lying on its wall shadows only the wall a few centimetres behind it (on Wall city, 282 plants casting within the trees' 80 m reach took 0.65 million triangles and 24 draws of the quay view, and left out its GPU frame fell from 6.05 to 5.37 ms). **Like cover, they are presentation: not a part of the world, not listed, not walked, not picked, and they hide nobody.** A site grows at most 4,000 (`CLIMB_PLACEMENTS_MAX`), counting only plants that grow: past it the plants met first keep their places and the rest are counted as left out; a face takes at most 64. The canvas states what climbed (`data-site-climb`: plants, buildings growing any, plants left out), and `data-site-piece-instances` counts them with the rest. Limits: a face is the box's face, so a plant on a front would stand before its door (a rule names its walls), a building drawn smaller than its box (a contained piece of catalog version 1 or 2) leaves its plants in front of air, and a face another building touches still grows them; what hangs over a terrace's edge is the trail's (the Trail row) |
| Trail | Where the pack states `trail` for a ground's look role, or else for the role its surface is drawn in (as cover's), and the site stands on land, its plant pieces hang over the edges of the ground's plane where the land falls away past them ([`trailers.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/trailers.ts)). The drawing states no terrace and no edge: a zone is a level pad in the graded land, so each edge is read from the land. Along each side of the ground's rectangle, at a station every 500 mm (`TRAIL_STATION_MM`), the level is the land one cell inside the side; the lip is the last point out from it still within 10 mm of the level (`TRAIL_LEVEL_WITHIN_MM`), within two cells of the side, and the land must lie below the level one cell past the lip. The face runs down from the lip while each 250 mm step out (`TRAIL_STEP_MM`) falls faster than the rule's least slope, by default 400 per mille (`TRAIL_SLOPE_LEAST_PERMILLE`, steeper than the 250 a person walks), and stays within 50 mm of the straight line from the lip (`TRAIL_STRAIGHT_WITHIN_MM`), since a plant is rigid, for at most 16 m across the plan. The drop, the level less the land at the face's foot, must reach the rule's `drop_mm`, by default 600 (`TRAIL_DROP_LEAST_MM`, more than three 180 mm kerb steps, so a step or a kerb never trails). Over a parapet (a wall or boundary box that is no building's) whose outer face lies within 50 mm of the side and whose top stands above the land there, a plant hangs from the parapet's top straight down its outer face to the land at its foot, never out over the land face below, so a plant over a bank lies against the wall and not in the air before it: hung along the straight line from a parapet's top to the land face's foot instead, creepers hanging 40 to 80 percent of the face over Terraces on the bay's parapets stood a median 259 mm and at most 1,529 mm off the wall and its bank. The drop is still the land's, and the parapet's own height does not count toward it. A station grows nothing where its side faces farther from the direction toward the sun than the rule's `sun_within_mdeg` (a look drawn with no sun, or a rule stating none, grows on every side), where another slot covers the level (cover's own test), where the land is wet at the level or at the foot, or where water, a path or road, or anything but a plane other than the parapet lies across the strip from the level to a walker's reach (340 mm) past the foot. Neighbouring kept stations are one run while their lips agree within 50 mm, they hang from the same parapet or none, and their faces turn by at most 10 degrees (`TRAIL_RUN_TURN_MDEG`). Along each run plants are chosen in turn from the rule's seed and the slot's identity, each one of its pieces and variants hanging a share of the run's shortest face drawn between the rule's least and most `hang_permille`, until their widths cover the rule's share of the run; they hang evenly spaced along it, each scaled whole to its hang, so none reaches past a foot. A trailing piece is authored with its foot at y = 0, its stems toward +Y and its leaves toward +Z; the page lays +Y down the face and +Z out from it, turned and never mirrored, its back 30 mm in front of the face at its top. It must be a textured piece: admission refuses an upload that names a palette piece, and one a pack drawn on as a base holds hangs nowhere. Only a ground the site draws as a plane hangs any, and never the base ground, which is the land itself. Trailing plants are drawn instanced in cells as climbing plants are, sway with the look's wind by their variant's `sway_permille`, and cast a shadow only within the climbing plants' `climbShadowReachM`, by default nowhere. **Like climbing plants, they are presentation: not a part of the world, not listed, not walked, not picked, and they hide nobody.** A site grows at most 2,000 (`TRAIL_PLACEMENTS_MAX`), counting only plants that grow: past it the plants met first keep their places and the rest are counted as left out; a run takes at most 64 (`TRAIL_PER_RUN_MAX`), and a site reads at most 16,000 stations (`TRAIL_STATIONS_MAX`): a slot whose stations would pass it is not read, and its stations are counted as untried. The canvas states what hung (`data-site-trail`: plants, grounds growing any, plants hung over a parapet, plants left out, stations untried), and `data-site-piece-instances` counts them with the rest. Limits: an edge is the side of the ground's rectangle, so a zone with a broken border hangs along its ruled line; a ground drawn as a box hangs nothing; a plant hangs the run's shortest face wherever along the run it stands; a site on level ground has no land to read and hangs nothing |
| Land cover | Where the pack states `land_cover`, its pieces grow on the near land a site on land stands on ([`land-cover.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/land-cover.ts)), never on the backdrop: on each near chunk, nearest the place first, as many as each rule's density gives the chunk's area, rules in their keys' order, each at a point drawn from the rule's seed, its key and its chunk, so the land grows the same every time and on every machine. A piece grows only where the land is drawn in its rule's `role` at that point, by the same rule the land's shader follows (`landBandAt` in the landform module: the land's slope over one cell each way, its height above the sea and the surfaces' noise), within its rule's slope and height windows and its reach of the place, and, where the rule states groves, kept or not by whether it falls in one: the groves stand one to a cell of a lattice laid over the whole land, each at a point and of a radius drawn from the rule's seed for that cell, the cell's side making them cover about the stated share (overlaps counted as for groves placed at random); the scatter measures the groves' cover over the near land and draws more points, keeping each so the stated share of the rule's pieces grows in groves and its density over the land holds; never inside a slot of the place's own (the place's grounds grow their own cover; the land under the place, its base ground, does grow), never where the land is wet (the sea's edge, a lake, a pond or a cascade's pool) and never within 1,000 mm of a fall (`FALL_CLEAR_MM`). Each stands on the land under it, turned about up and scaled between its least and most, drawn instanced in cells as cover is and swaying in the look's wind by its variant's share. A land cover piece must be a textured piece: admission refuses an upload that names a palette piece. Without the land's surface catalog, every point is drawn in `land`. **Land cover is presentation, as cover is: not a part of the world, not listed, not walked, not picked, and it hides nobody.** A site grows at most 60,000 land cover pieces (`LAND_COVER_PLACEMENTS_MAX`), counting only pieces that grow, the nearest chunks' first, from at most 240,000 points tried (`LAND_COVER_TRIES_MAX`). The canvas states what grew (`data-site-land-cover`: pieces, pieces by role, pieces left out, points untried). Limits: the role at a point is read where the scatter samples it, so a piece may stand just inside a band's ramp where the drawn colour is already the next; nothing grows under a town's tiles once towns stand on land, since a tile draws its own ground |
| Wind | Where the look states a `wind`, every textured piece of the families it names sways, the cover's and the slots' alike ([`wind.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/wind.ts)). A piece bends from its foot: a vertex moves by the square of its height over the piece's own height, so the foot stays put and the top moves farthest. The top leans along the wind by up to the stated sway, scaled by its variant's `sway_permille`, and back at the stated pace, each piece at its own phase from where it stands. A cut-out material (leaves, blades, petals) also flutters across the wind by the stated flutter at four times that pace; an opaque one (a trunk, a stem) bends whole and does not. Gusts are a smooth field, one gust size across, carried downwind one gust size for each sway; where no gust is, a piece sways by one less the gust share of its sway. The sway is in the piece's own vertex positions (the engine's transform chunk), so its shadow sways with it; nothing moves a slot, a bound or the walk. Palette pieces, baked into one mesh per swatch, do not sway. The canvas states how many materials sway (`data-site-wind`). The working is GLSL for the WebGL2 device the page asks for; on a WebGPU device nothing sways |
| Facades | Where the pack states a `facade` for a building wall's look role, or else for the role its surface is drawn in (as cover's), the wall's faces that look out of its building are drawn with windows ([`facade-finish.ts`](../web/packages/atlas-react/src/playcanvas/style-pack/facade-finish.ts)): rows from the building's own base, each storey the drawing states (`storeyHeightMm`, else the building's whole height) holding the whole number of rows nearest the rule's storey height, at least one, so the rows meet the building's storeys and its top; on each face, as many of the rule's least bays as the face's length holds, stretched to fill it from the building's corner; and in each bay of each storey but those kept clear from the ground, one window of the rule's one size, centred, its foot at the sill and never into the least wall under the next floor, so no window is larger than its bay. Around it, its reveal: the jamb and the head (or the sill's top) the eye sees into as it moves, by the reveal's depth, in the reveal's shade; under it, a ledge as tall as stated and that much wider each side, lighter by its light; inside, glass darker than the wall by its darkening and glossy by its gloss, so it shows the sky, and a room behind it, the rule's depth deep, whose back, sides, floor and ceiling shift as the eye moves. Rooms of the rule's bays are lit together: the light's own share where its preset states `lit_windows_permille`, else the rule's dusk share with the sun at or below its dusk elevation, its day share at or above its day elevation and smoothly between; a lit room in warm light by the warm share or else cool, its brightness spread by the spread, an unlit one dim in the unlit colour. Where a bay is smaller than a pixel by the rule's fade, the grid fades to its average colour and light, so a far wall does not shimmer. A facade is a wall the building owns (a slot the drawing gives a `structure`) on the edge of the building's own slot, within its own thickness, facing open ground: never a wall between its rooms, a wall against another building, the inside of any wall, or a wall's end except where it lies in the building's outer face (there it draws as the face it lies in), so no window is seen from inside a building; a piece over an opening (a lintel) is one, and draws a storey's window only where it stands over all of it. Each facade wall's own mesh instance states its building and its rule, so walls keep sharing their materials and a wall that states none, a boundary wall among them, draws its plain colour; the finish is set after the material's own colour, emission and gloss, so a pattern, a texture and a pack's emission keep working beneath it. Glazing (a blended material) and a wall whose texture could not be read have none. **Presentation only: a painted window is not an opening, and no slot, wall, door, walk, contact or pick changes; nothing more is drawn.** The canvas states how many building walls show windows and in how many materials (`data-site-facade`). Limits: the grid does not read the drawing's own openings, so where a look keeps no storey clear a painted window may meet a door; a building a pack dresses with one piece shows that piece's own windows; a site drawn with no pack has none; and the working is GLSL for the WebGL2 device the page asks for, so on a WebGPU device every wall keeps its plain colour |
| The rest | A slot the pack does not dress keeps the engine's primitive in its fallback colour, drawn in the pack's shading; when the shading draws ink, everything the site draws is outlined |

The app (`web/packages/app/src/composition/site-world.ts`) reads the pack and fetches its pieces
before it mounts the site. A pack it cannot read is not stood in for: the site opens in the tile
look in the engine's colours, and `data-world-look` states the pack asked for, what chose it and why
it was not drawn. The Look sheet is offered on a site as on a town, and `redrawWorldLook` mounts the
site's drawing, already read and checked, again in the new pack's light and dressing on the same
host.

Texture surfaces retain their served rectangle rather than expanding for a cosmetic broken border.
The ground beyond uses the base ground's physical texture scale. Water swatches in PBR shading
carry animated normal ripples, the slope of drifting noise in two octaves, each fading where it would
be finer than the picture; the land's sea and lakes carry none, so far water is a soft glow and never
a grid of glints. These are cosmetic, with no change to basin geometry, keep-outs,
movement or simulation. Toon water keeps its static pattern. Glazing samples the drawn scene;
water reflects the environment, without a separate planar reflection pass. A pack that states a
`water` finish has its PBR water coloured by its own depth: the scene's depth behind the surface
gives the water's thickness, what lies under shallow water shows through, deep water takes the deep
colour, and thin water foams against what stands in it. It is blended over the drawn scene with
one transmittance (the mean of the three channels' absorption), so it needs no copy of the scene's
colour; the per-channel tint of the seabed is approximated by that mean. A finish that states
`contact` also darkens what lies under the water by the look's share (it is wet) and by the light's
way down to it, light lost and not replaced by the water's colour; gives the shallow colour to a
surface under the water by how far it turns up to the sky, so a stack's or a wall's side under the
water takes the deep colour; and foams across the surface from a solid that meets it within the reach
the look states for that water's look role (a land water asks for `water.` and its kind, a slot water
for its slot's role; a role named nowhere gets no ring). The solid is found among 16 points of the
camera frame's depth map round each pixel, each placed in the world from the camera's inverse
view-projection, and counts where it stands no lower than the foam width under the surface. Slot
waters asking for different roles keep a material each under such a finish. It is GLSL only: on a
WebGPU device the finish is not applied and the water keeps its ripples.

A cascade on a site on land states level pools and the upright falls between them. A pool wears the
pack's `water.pool` where it states one, else its lake's water (`water.lake`, then `water.default`),
and is finished as a lake is (the `water` finish by its own depth, else the surface finish's sea), with
the ripples of a pond: it lies within the site, near. A fall wears `water.fall`, else the lake's water,
and is finished in its colour as a sheet: streaks drawn down it at the look's pace and foam where it
lands, from `falling_water` or the page's defaults, with no depth and no ripple normals. Colour only,
in every shading model, and cosmetic like the ripples: the water does not move and the walk is the
land's. The fall finish is GLSL only: on a WebGPU device a fall keeps its pack's flat colour.

The optional `?measure=1` review mode records a bounded frame-interval sample, draw calls, canvas
resolution, graphics backend, camera position and facing, and accounted texture bytes on the canvas. Frame intervals are not
GPU execution times. Accounted bytes cover uploaded surface textures and the environment maps,
not total graphics-device or process memory.

The existing Look sheet lists the committed library and the current workspace's admitted, wearable
looks. Choices retain source, version and manifest digest separately from their displayed names,
so the same pack id in both namespaces stays unambiguous. An older bound version stays selected
until a person chooses another. Unready, withdrawn or unreadable workspace versions are not
offered, and Apply rechecks availability. The browser supports standalone workspace packs and
workspace packs based on a library pack; workspace-on-workspace base chains are not offered by
this browser loader.

## 8. The authored packs

Three packs authored by Exulanica are committed under `assets/style-packs/packs/`, each CC0-1.0:
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

A fourth pack, `exulanica.kit-places`, is drawn on the cozy town and adds a ready-made piece from an
open kit where a place made from a world kind has a thing of its own: a rowing boat for
`vehicle.fishing_boat`, from Kenney's Pirate Kit, dedicated to the public domain (CC0 1.0). Its
manifest states only what it adds: its base (the cozy town, by version and digest), swatches of
its own and one module a look role; its light, ground, surfaces and the town's pieces are its
base's. Its origin is `imported`, its authors are Exulanica and the kit's maker, and it states no
family default: a slot whose leaf it does not name keeps what the cozy town draws there.
`assets/style-packs/kits/kit-places.v1.json` states what it is made from (each kit's archive as it
was fetched, with its size, SHA-256 and the licence file read inside it, and each piece's model,
what is left out of it and why, how it stands and how long its longest side is), and what it
leaves out and why; `kit-places.built.v1.json` beside it records each conversion: the model's and
its pictures' digests, the size given, the swatches and the piece's digest. A kit's archive is not
in this repository. `scripts/style_packs/kit_pack.py --convert` reads the unpacked kits
(`scripts/style_packs/kit_models.py`: a model is parsed, never run, and a file it names outside
its own folder is refused) and writes the pieces and that record; with no flag it writes the
manifest from the catalog, the record and the committed pieces, which is run again when the cozy
town moves. A piece keeps its kit's colours: every triangle of a kit model has one colour, and
the pieces' colours become the pack's swatches, heaviest first by the area they cover, a colour
joining a swatch already made when it is within the catalog's distance of it in OKLab. A kit piece
is scaled whole into its slot like any contained piece, so it is as large as the slot's box lets
its own proportions be; a piece whose proportions are far from the box a kind gives its leaf
would stand as a miniature, and is left out of the pack for that (a roofed well, for a well's low
box). `tests/test_kit_style_pack.py` holds the committed pack to the script, the library, its own
swatches, its family budgets and its records, and `tests/test_kit_models.py` holds the reader.

A kit document may also name trees (`scripts/style_packs/garden_kit.py`, a `tree` row: a species,
a height, an optional width and a seed). The tree maker (`scripts/style_packs/tree_maker.py`)
grows each as a textured piece (section 4.1) with its second level: the species is data, every
figure held to its range when the catalog is read (`assets/style-packs/makers/tree-species.v1.json`,
profile `exulanica.tree-species/v1`: how the trunk and branches grow, the leaf card it carries, its
bark, how its second level thins it, the sides of its pictures, and the share of a look's wind it
takes, `sway_permille`, which each of its tree variants carries: a stiff cypress less, a palm
more). Given a width, the crown is
grown to the box's proportions, never stretched to them; a crown that cannot be narrower than its
cards is made at its narrowest and its receipt says how wide. Leaf cards are composed from scanned
single leaves (`leaf_cards.py`) and the bark is a scanned bark; the scans are not in this repository,
and the maker reads them from the folder `--sources` names, each held to the digest the catalog
states, so a catalog, its scans and a row make the same bytes. Rows of one role become that role's
variants, at most eight; what made each tree is written beside the packs (`<pack id>.trees.json`).
`tests/test_tree_maker.py` makes trees from synthetic scans and holds them to the plant budget,
both readers' rules and their boxes.

A kit pinned to appearance catalog version 3 makes its arcade blocks, towers and halls as modules
that repeat to meet a building's box (`scripts/style_packs/assembled_architecture.py`): an arcade
block is its end walls about one bay of an arch on piers before the loggia, with an arched window
over it on one upper storey, its ground storey and cornice below and its eaves and balustrade
above; a tower is one stage under its belfry and roof; a hall is its gable ends about one bay of an
aisle arch and a clerestory window. The bay repeats across and the storey or stage up
(`repeat_mm`), an arcade block's plain body between its back wall and its loggia stretches in depth
(`stretch_mm`), and an axis with neither is scaled within the family's bounds, so a tower's roof and
a hall's section keep their shape. The row's fields are the same as for a whole piece, and its
size, bays and storeys give the bay width and storey height the module is drawn at; every face is
cut at the zone edges, so the check passes it. A row whose bay would be under 2,000 mm or whose
upper storey under 2,500 mm is refused before anything is made. A kit pinned to version 1 or 2 makes
the same rows whole at their size, byte for byte as before. `tests/test_assembled_architecture.py`
holds each module to its size, its zones, the structure budget and its row's size when drawn with
the row's bays and storeys.

A kit document may also name climbing plants (a `creeper` row: a species, a width, a height and a
seed). The creeper maker (`scripts/style_packs/creeper_maker.py`) grows each over a wall patch of that
size as a textured piece with its second level: stems rise from roots spaced along the patch's foot,
wander and branch as they climb and stay inside the patch, and leaf cards (`leaf_cards.py`, from the
scans the tree species catalog names) hug the wall along them, leaning a little out of it, fewer
toward a stem's growing end. The patch's wall is the plane z = 0 behind it and its leaves face +Z,
as section 7.1's climbing plants are set against a face. The species is data
(`assets/style-packs/makers/creeper-species.v1.json`, profile `exulanica.creeper-species/v1`: how
the stems grow, the card and how densely and how far out it stands, the stem's bark, how the second
level thins it, and the share of a look's wind the plant takes), every figure held to its range when
the catalog is read; it names the tree species catalog version whose scans it reads, so no digest is
stated twice. A patch is held to the plant budget: past it every other card is dropped and the rest
grown larger to cover the same wall, and its receipt says how many were kept; its second level keeps
a share of the cards on stems of fewer points, within the share of the first level's triangles a
second level may hold. A patch's pictures are its species' alone (the leaf sheet drawn from the
species' card recipe, the stem from its bark), so every variant of one species carries the same
pictures and a pack counts them once (section 5), while its stems and cards follow its seed. Rows of
one role become its variants, each with its species' `sway_permille`,
and what made each is written beside the packs (`<pack id>.creepers.json`). A kit variant may state
`climb`, copied to its manifest. `tests/test_creeper_maker.py` makes patches from synthetic scans and
holds them to the plant budget, the product's readers, their patch and the catalog's ranges.

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
when the person making it names none, and may list the looks offered to the look chooser
(`offered_to_the_look_chooser`, section 10.1; a file that lists none offers every pack); a default
or an offered look that is not a pack of the library, or a file stating anything else, refuses the
library the same way.

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
package exported from a world does not carry the pack its appearance names.

A world may also wear a version of its workspace's own pack (section 11): its style version then
states `style_pack_source` `workspace` beside the id, version and digest (one migration,
`a_world_wears_its_own_look_of_generated_pieces`; every version written before it, and every one
naming a library pack, states `library`, and reads exactly as it did). Such a version is named only
while `workspace_style_pack_wearable` says it may be worn, asked under the asset read lock as the
last question of the write, and the schema holds the same at insert, so a rollback to a version
naming one that was since withdrawn is refused. An appearance preview resolves the exact id,
version and manifest digest against the host's library first, then the current workspace's wearable
packs. It accepts a standalone workspace pack or an admitted base chain, and checks any requested
setting against that chain. Unknown, unready, withdrawn and other-workspace identities are refused;
the request cannot choose another workspace. Apply rechecks availability under the write lock.
The generation worker also names a look made of a world's generated pieces
([generated pieces](generated-pieces-contract.md#54-a-worlds-look-taking-its-pieces-in-and-back)).
Migration `a_world_wears_an_admitted_workspace_pack` extends the original generated-only gate to
admitted uploads without rewriting existing appearance rows. A pack withdrawal revokes use and
keeps history; workspace erasure deletes every world's appearance history as well as scrubbing the
pack's private identifiers and documents and purging its files. Restore carries withdrawals and
workspace tombstones so an earlier backup cannot restore their use or erased world history.
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
description as it was sent to the drafter, every saved name replaced, and the id, title and
description of each look the library offers the step: the ones
`assets/style-packs/library.v1.json` lists as `offered_to_the_look_chooser`, which are the looks
the step's recorded runs were measured with (the three authored towns). A pack added to the
library since is a look a person chooses, in the Look sheet or by the page's address, and the
step is not shown it until it is measured with it. The answer is one listed pack id or none, with up to three phrases copied
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
| Each piece's profile (`exulanica/world/style_pack_pieces.py`): an `exulanica.static-glb/v1` container with one buffer, the binary chunk that buffer and at most three zero bytes, every buffer view packed tightly, used and read byte for byte by its accessors, no `extras`, no images, textures or samplers in a palette piece, a textured piece as section 4.1 states with each picture walked to its end, names and `asset.generator` at most 64 plain characters, `asset` holding nothing else; and its family's triangles (a second level of detail a quarter of the first's), materials and, for a textured piece, texture side, no stretch or repeat zone and a textured second level, from accessor counts; the pictures of every piece and texture at most 64 together, each once by its digest; every piece a cover, climb, trail or land cover rule names textured | 422 `style_pack_piece_refused` or `over_budget`, with the piece's `path` |
| The preview, walked to its end without decoding (`exulanica/world/style_pack_preview.py`) | 422 `style_pack_preview_refused` |
| Each texture's pictures, walked the same way (`style_packs.probe_pack_image`, JPEG and PNG only, at most 2,048 pixels a side), its maps one size | 422 `style_pack_texture_refused` |

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
palette or a palette in its base chain, and a palette piece whose variant repeats a zone held to
that zone: a triangle that crosses one of its edges by more than half a millimetre refuses the
version (`crosses_repeat_zone`, naming the triangle and the edge); at most 120 s a version, past which it is `interrupted`, and
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

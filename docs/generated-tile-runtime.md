# Generated tile runtime

Status: IMPLEMENTED as a development evaluation only: the browser reads baked texture sets and
baked `.owd` tiles, draws a tile's `render_batch` with physically based materials under one
versioned look, and stands the player on its `nav_envelope`. No generated tile appears in any
person's world, and none may until a superseding governance ADR is accepted in writing. A baked
corridor street now exists in the tile store and has been loaded through the product route and
walked on the development page (2026-09-17): 4 of its 854 records drew, and 851 named a tessellator
expander that does not exist yet, so what a walker saw was the stated unavailable hatch rather than a
street. Textured tile geometry has still been seen only on a test-only bench.

The code is `web/packages/atlas-core/src/texture-set.ts` (the texture set reader),
`web/packages/atlas-react/src/playcanvas/generated-tile/` (materials, look, environment, tile
loading, navigation and the binding contract, exported as `@exulanica/atlas-react/generated-tile`),
the `generatedTile` option of `web/packages/atlas-react/src/playcanvas/atlas-binding.ts`, and the
development entry in `web/packages/app/src/composition/generated-tile.ts` and
`web/packages/app/src/dev/`. The container is tess's, documented in `web/packages/loom-tess/README.md`;
the sets are the texture lane's, documented in [texture-package.md](texture-package.md).

## 1. What a person sees

On the app's development server, `/?preview=1&tile=tile-conformance` opens the normal shell with
the Companion and the reticle, but the owned district is replaced by the named tile. Today that
tile is tess's city version 2 conformance fixture: a 128 m terrain patch, drawn whole (512
triangles, one `terrain` surface) in the stated unavailable pattern (a magenta hatch carrying the
word UNAVAILABLE, unlit), because no material record dresses terrain and the tile says so. The player stands on the tile's
`nav_envelope`, eye 1.62 m above it, at the middle of its southern edge, and walking follows it; the
envelope leaves out the ground around the tile's other records, so the middle of the patch is drawn
but cannot be stood on. A panel at the bottom left says what this is ("Development evaluation of
generated tile tile-conformance. Not part of any world."), what the player stands on, what is
missing (no `collision_proxy`, so nothing blocks the capsule), how many of the records render_batch
lists are drawn and how many surfaces are drawn as unavailable, and lists each such surface (record,
role and orientation, with its reason) and every record not drawn yet, with the geometry it waits on.

The eight texture sets are seen on real surfaces only on the test-only bench,
`web/packages/atlas-react/test/generated-tile-bench/`: a few metres of hand-built street
(carriageway, 150 mm kerb, footway, a wall with a stone plinth, a recessed metal door and a
projecting cornice), lit by the same look. The bench is never shipped and is not a placeholder
for a tile.

With no tile requested, the app is unchanged: a GPU readback of the default view at three poses
is byte-identical to main (section 8).

## 2. The texture set reader

`decodeTextureSet(bytes, entry, digest)` parses one `LTX1` container and holds it to its manifest
entry; `parseTextureSetManifest` reads `assets/textures/manifest.json` exactly as committed. The
reader is pure (no DOM, no Node, no renderer) and returns views over the caller's bytes. It is the
browser runtime's own reader, written from the container's stated layout; it does not import or
copy `loom-texture`, which is fenced as offline only.

It reads both profiles of each document. `exulanica.texture-manifest/v1` lists
`exulanica.texture-set/v1` containers only, every one the four-map `opaque` layout.
`exulanica.texture-manifest/v2` adds each entry's `container_profile` and `material_class`, and its
`channels` must be one of the layouts that pair allows: the procedural layout, or a model-made one
(the entry does not name its maker). A v2 container states its `material_class` (`opaque`,
`cutout`, `decal` or `glazing`), its `maker_kind` (`procedural` or `model`), a `class` object, and
exactly that class's and maker's layout:

| Class | Procedural maps | Model-made maps | `class` |
| --- | --- | --- | --- |
| `opaque` | `base_color`, `normal` (x, y), `orm` | `base_color`, `normal` (x, y, z) if produced, `orm`, `height` if produced | `{}` |
| `cutout` | `base_color_coverage`, `normal` (x, y), `orm` | the same pattern with `base_color_coverage` | `alpha_cutoff` 128, `coverage_permille`, `double_sided` true |
| `decal` | `base_color_coverage`, `normal` (x, y), `orm` | as cutout | `coverage_permille` |
| `glazing` | `base_color`, `transmission_roughness` | `base_color`, `normal` (x, y, z) if produced, `transmission_roughness`, `height` if produced | `double_sided` false, `ior_millionths` 1500000, `film_srgb`, `film_roughness_permille` |

A procedural set whose class bakes relief states `height_range_mm` and `cavity`; procedural glazing
states neither; a model-made set states `height_range_mm` only when it ships a height map. Every
map's description (name, components, what it holds, sRGB or linear, its decode words, and for a
normal its space and convention) must be exactly the layout's, and `coverage_permille` must equal
what the reader measures from the coverage channel (texels at or above the cutoff, in thousandths,
floored). A glazing set's film is declared by its recipe, not measured: `film_srgb` must be three
integers from 0 to 255 and `film_roughness_permille` an integer from 0 to 1000, and the reader checks
their shape and range and never recomputes them; any other class that states a film is refused. `DecodedTextureSet` carries the profile, class, maker kind, typed class parameters, the
channels in stored order and the maps present.

It refuses, with a `TextureSetRefusal` and one of the shared reasons, and never degrades:

- `digest-unavailable`: every set, before reading a byte, when the page has no `crypto.subtle`, the
  same posture as the app's geometry reader;
- `manifest`: a manifest that is not canonical JSON, names a profile, container profile or class no
  reader was written for, lists an entry with a missing or extra key, a v1 container of a class
  other than `opaque`, channels that are no layout of the entry's pair, another licence, or sets out
  of `set_id` order or twice;
- `byte-size` and `digest`: bytes that are not the pinned count or do not hash to the pin;
- `container`: a wrong magic, a header or map running past the end, padding that is not spaces, or
  bytes after the last map;
- `header`: a header that is not canonical, names a profile, class or maker kind no reader was
  written for, has a key its class and maker do not have, describes a map other than the layout does,
  states a `class` its class and texels do not give, or disagrees with its manifest entry (set id,
  version, resolution, extent, licence, media type, profile, class or channels).

Conformance, two ways. `web/packages/atlas-core/test/texture-set.test.ts` decodes all eight
published v1 containers and requires, per map, the byte offset, length, SHA-256 and first and last
bytes the Python reader (`exulanica/world/texture_assets.py`) produced, from a fixture beside the test
written by `texture-set-python-decode.py.txt`. `web/packages/atlas-core/test/texture-set-cases.test.ts`
runs the texture lane's shared case file, `web/packages/loom-texture/test/texture-set-cases.json`, the
one the baker and the backend run too: every manifest case and every container case, over one v2
fixture per class plus a v1 and a model-made one, each accepted or refused for the same reason every
reader gives. The file and its fixtures are read by path, which is not an import, so nothing that ships
depends on the offline package.

## 3. Materials and the UV rule

A set is drawn by its material class and by nothing else, never by its id or title. This runtime
draws all four classes, `opaque`, `cutout`, `decal` and `glazing`, of either container profile and
either maker. A class this runtime has not been taught draws the stated unavailable surface with the
reason "material class X is not drawn by this runtime" (`undrawnClassReason`), and nothing of it is
uploaded.

A `cutout` set is glTF's `alphaMode: MASK` with `doubleSided: true`. Its `base_color_coverage` map is
uploaded as sRGB colour with linear coverage, and every mip level is built by
`coveragePreservingMips` (`cutout-coverage.ts`): each level is averaged from the one above, colour in
linear light weighted by coverage, and its coverage is then scaled by the one factor that keeps the
share of texels at or above the cutoff equal to the set's `coverage_permille` (texels tied with the
last one wanted are covered together). Each sample is tested against `alpha_cutoff / 255` and nothing
is blended; depth is written; the shadow pass applies the same test; both faces are drawn and lit, a
back face with its normal reversed; a set is still one draw. Measured on the bench on the published
`cc0.broadleaf-foliage` (`evidence/cutout-acceptance.log.txt`): silhouette coverage at 30 m is within
2.2 per cent of 5 m, where plain averaged levels drift by 12.1 per cent (this set thickens on plain
levels, because averaging pulls the many part-covered texels at leaf edges over the cutoff; the
test-only field thinned instead, by 4.2 per cent kept against 10.1 plain). Its shadow is dappled
(21.1 per cent of the ground under it shadowed, against 100 per cent for the same square drawn
opaque), and its back face is lit (92.6 against 36.7 without two-sided lighting, where the front face
in shade reads 36.6).

A `decal` set is glTF's `alphaMode: BLEND` over the surface it lies on: road paint, a stain, a patch
of grime, geometry that is part of the surface under it rather than a thing of its own. Its
`base_color_coverage` map is uploaded as sRGB colour with linear coverage, level 0 only, so the device
builds the chain by averaging: a decal is blended by its coverage rather than tested against a cutoff,
so an average is exactly what a partly covered texel means, and the coverage-preserving chain a cutout
needs would be wrong here. Each sample is source over the surface by its coverage; depth
is tested and not written, so decals never hide one another by depth; the surface is lit by its own
normal, roughness and metalness maps and receives shadows; it casts none (`castsShadow`), since a
film of paint lying on a road shadows nothing.

Two things the class needs that opaque and cutout do not. A decal is coplanar with the surface it
dresses, so the depth buffer cannot separate them and the surface shows through in bands that crawl
as the camera moves; the material is pulled toward the camera by a constant bias and one that grows
with the surface's slope to the view (`DECAL_DEPTH_BIAS` -1, `DECAL_SLOPE_DEPTH_BIAS` -2), the slope
term being what a road needs at eye level, where the ground runs away almost edge on. And a blended
surface is drawn in the engine's back-to-front pass, which sorts by draw bucket before distance:
decal takes bucket 160 and glazing 96, above and below the default 127, so every decal is drawn after
the opaque and cutout scene and before any glass, and a lane line behind a shop window is drawn
before the window.

Measured on the bench with a test-only worn lane line lying on published asphalt in the same plane,
walked 30 m at eye level beside it (`evidence/decal-acceptance.log.txt`): at each of 32 poses the line
is compared against a reference drawn with no depth test, pixel by pixel. As bound it matches the
reference at every pose (minimum, mean and maximum share 1.000, no pose below 0.99); with both biases
set to 0 it matches 0.611 of the line's pixels on average, and 19 of the 32 poses fall below 0.99,
between 0.011 and 1.000. So the bias is not a refinement: without it the road wins a third of the
line's pixels, and which pixels it wins changes pose by pose, which is the crawling a walker sees.

A `glazing` set is glTF metallic-roughness with metalness 0 plus `KHR_materials_transmission` and
`KHR_materials_ior`. Its `transmission_roughness` map is uploaded with transmission in red and
roughness in green. It reflects the environment probe and the sun with reflectance
`((n - 1) / (n + 1))^2` face on, from `ior_millionths`, rising with angle by Schlick's approximation
with its value at grazing incidence the surface's gloss (`glazing-fresnel.ts`): the glazing material
replaces the engine's Schlick term, whose value at grazing incidence stays at 0.04 for glass. It
transmits what the scene drew before it, from a copy of the scene colour the environment keeps once
glazing is drawn (`requestSceneColor`), tinted by the base colour, times the transmission map, times
(1 - Fresnel), blurred by roughness; where transmission is below full, the rest is the film the base
colour and roughness maps carry, lit like an opaque surface. It is drawn after the opaque scene,
depth tested, writes no depth, casts no shadow (`castsShadow`) and is one sided. What lies behind the
pane is geometry the grammar states; the runtime never draws the far side of a building through
glass, because the scene copy holds only what was drawn in front of it. The film the class object
declares is for laying more film by position, which waits for its inputs.

Measured on the bench on the published `cc0.float-glazing`, against a test-only checker backing 0.6 m
behind the pane, since no interior stands behind glass yet
(`evidence/glazing-acceptance.log.txt`): the backing reads through at 2, 4 and 6 m (luminance
correlation 0.89 to 0.90, 0.89 to 1.00 of its contrast kept); with the backing at about a shop
interior's brightness the sky's reflection is 38 per cent of the pane's light face on, passes half
between 50 and 70 degrees, and reaches 73 per cent at 70 degrees and 91 at 80, while what is behind
the glass fades with it (correlation 0.89 face on, 0.25 at 80); and a pane darkens the ground under it
by nothing. Stated
limits: the probe is the look's sky gradient, so glass reflects sky, not the street; one set is one
draw, so its panes are not sorted against one another.

One `pc.StandardMaterial` per opaque set, shared by every surface that names it
(`texture-materials.ts`): `base_color` uploaded as sRGB, `normal` as linear bytes, and `orm` driving
occlusion (red), roughness (green, inverted into gloss) and metalness (blue). A two-component normal
(a procedural v2 set) gets its z rebuilt where it is uploaded, `z = sqrt(max(0, 1 - x^2 - y^2))`, in
arithmetic that enters no digest (`normalTexels`); a model-made set that produced no normal draws
without one. Three RGBA maps with full mip chains, 16,777,212 bytes for a 1024 by 1024 set. A set
whose manifest entry is missing or whose bytes are refused draws the stated unavailable surface, with
the refusal kept as the reason. There is no default set and no flat colour.

The texture's placement is interpreted in exactly one function, `surfaceUv`, and it is the city
vocabulary's final formula for `surface_material` version 2. With `s`, `t` the surface coordinates
in millimetres, theta the record's `uv_rotation_urad`, and
`repeat = extent_mm * repeat_size_millionths / 10^6` per axis:

```text
u = (cos(theta) * s - sin(theta) * t + uv_offset_u_mm) / repeat_u
v = (sin(theta) * s + cos(theta) * t + uv_offset_v_mm) / repeat_v
```

So the size factor is a repeat length (2,000,000 draws the set twice as large), a positive theta
turns +s toward +t, offsets apply after rotation, and a wall `w` mm wide at size 1,000,000 repeats
the set `w / extent_u_mm` times. There is no other scale anywhere. A surface whose material is
`none-exists` (exact geometry no material record dresses) is drawn as the unavailable surface with
that reason, never withheld. A `surface_material` version 1 states no placement, so a surface citing
one is drawn as unavailable ("version 1 does not state how its texture is placed").

The surface coordinates are tess's, in the frames the city vocabulary fixed: on horizontal faces
`t` is to the left of `s`, and terrain, lot and roof use the plan (`s = x`, `t = y`); on vertical
faces `s` runs along the run from its start and `t = base - z` points down.

Normal map sign: PlayCanvas derives its bitangent toward increasing v and the sets put +Y toward row
0, so `setTangents` flips the handedness once. The bench proves the sign from pixels (section 6).

## 4. Loading a tile

`loadGeneratedTile(sources)` (`tile-runtime.ts`) consumes tess's pure core,
`@exulanica/loom-tess/core`, the only tess entry shipping code may import (tess's rule in
`web/.dependency-cruiser.cjs`). It calls `verifyOwd`, which decodes the container and bakes the
header's records again, requiring every byte to match; there is no second reader and nothing is
repaired. The container is tess's `owd/3`. It refuses a page with no `crypto.subtle`, a tile that
fails verification, a grammar frame other than `city_local` (section 5 has the capsule it also
reads), and a tile with no `render_batch`, no surface coordinates or no drawn range.

Only `render_batch` is drawn, and only its drawn entries, exactly as stored. A drawn entry is a list
of surfaces: contiguous runs of its triangles that share no vertex, each with one grammar role, one
material and one orientation, so a kerb's vertical face and its horizontal top, or a facade's ten
roles, are separate surfaces of one record. A surface is textured when its material is a version 2
`surface_material` record whose set is pinned and verifies; a surface whose material is
`none-exists`, or whose material does not resolve, is the unavailable surface with its reason. An
`unavailable` entry is geometry tess has not produced yet: it has no
triangles and is listed with the needs tess stated ("Not drawn yet: its geometry waits on
massing_faces."). A `not_admitted` entry is listed too. A `halo` entry is a neighbouring record
carried as context and is neither drawn nor listed, and neither is `not_in_projection`. Every set a
tile cites, and only those, is fetched and verified before the renderer exists, so an attached tile
is complete on its first frame. `batchTileSurfaces` batches surfaces by what they are drawn with,
across records: one draw per set and one for all unavailable surfaces. Each surface's UVs follow its
own material and orientation, its normals are computed over its own triangles, and a surface
triangle that reaches outside its surface's vertices is refused.

Frames: records are `city_local`, integer millimetres, x east, y north, z up. The renderer draws a
tile point (x, y, z) at (x, z, -y) / 1000 metres, a proper rotation, so winding is kept and north is
the camera's yaw 0.

Identity for picking: `rangeAtTriangle(triangle)` returns the record a `render_batch` triangle
belongs to, and `pick(origin, direction)` returns the nearest drawn triangle along a ray with its
record; both stay per entry, whatever surfaces it has. Version 2 records state their identity (the conformance terrain is
`2f14328d-39f8-5bee-a06a-f963b701ccf3`), and every range carries it. Data view selection through
`registerRepresentationSubjects` is not wired yet; it waits for the data view lane to merge.

## 5. Standing and walking

The binding (`atlas-binding.ts`, `generatedTile` option) takes a `GeneratedTileMount`
(`binding-contract.ts`): a navigation world, an opening stance and `attach`. A tile replaces the
owned district; passing both is refused. The binding never reads the tile's geometry and never
falls back to the district's ground.

Support comes only from `nav_envelope` (`tile-navigation.ts`): the height of the highest envelope
triangle over a plan point, exact on its plane, with its normal; walls and downward faces support
nothing. Navigation is never derived from the render mesh; Melbourne failed capsule clearance there.
The player is the capsule the tile's grammar states for the envelope's `capsule_clearance`, because
that is the capsule the envelope was carved for: `tileCapsule` reads the radius, height and eye
height from tess's grammar table (city version 2: 340 mm, 1900 mm and 1620 mm, which is also the gate
harness's capsule) and builds the navigation world to them. A tile whose grammars state no capsule,
or two different ones, is refused. Support is resampled every 0.05 m along a move. The step and
slope limits the controller applies (0.18 m and 12 degrees) are
the Atlas controller's comfort contract, not a statement about the tile. A tile without a
`nav_envelope` opens at a stated viewpoint south of it and every move gets the app's "no walkable
surface" notice.

Not yet: no tile carries `collision_proxy`, so the capsule's 1.9 m height has no overhead clearance
check and nothing blocks it; the panel says so. The tile route is first person only, because the
third person camera and avatar stay tied to the owned district until the characters lane's player
renderable arrives.

## 6. The look, measured

Every look parameter lives in one descriptor, `TILE_LOOK_V1` in `look.ts` (id
`exulanica.generated-tile-look`, version 1), and `validateTileLook` refuses an unknown or missing
key, a wrong kind or an out-of-range value. Three ranges are the architecture's look targets and are
enforced there: fog onset 40 to 60 m, an environment probe with no off switch, and contact
shadowing with no off switch whose radius must reach a 100 mm kerb without spanning a storey. The
corridor lane changes the look by editing this descriptor and bumping its version; geometry, UV
scale and texture choice are world data and are not in it.

`environment.ts` applies the look. Its camera frame (tone mapping and the occlusion pass) builds
render targets at the canvas's size when it is created, so it is created only once the graphics
device has a size, at once or on the device's first resize. A page that mounts a tile while its
canvas is 0 by 0 then logs no incomplete framebuffer for the frame's own targets
(`evidence/camera-frame-zero-size.log.txt`).

Measured on the bench (Chromium, WebGL2, Apple M3 Pro, 1440 by 900; values from
`web/packages/atlas-react/test/generated-tile-bench/evidence/bench-measurements.log.txt`):

| Target | Measurement | Result |
| --- | --- | --- |
| Fog onset 40 to 60 m | Unlit target ahead, fog on minus off, mean luminance: 0 at every step from 30 to 50 m, 5.07 at 52 m, 21.79 at 60 m | Onset between 50 and 52 m (`fog.startM` 50) |
| Environment probe | Door pose, mean luminance with and without: metal door 142.89 and 0.30; brick wall 150.32 and 139.70 | Probe lights metal that would otherwise be black |
| Contact shadow at kerb, doorway, cornice | Luminance ratio with occlusion over without, same pixels, `combine` mode: kerb 0.705, door at reveal 0.560, threshold 0.820, cornice 0.653; controls 1.5 to 2.5 m from any junction 1.000 | Darkens the three junctions only. `lighting` mode left the sunlit kerb foot at 0.927 and was rejected |
| Normal map sign | Correlation of shading difference with the height map's slope, sun swung above and below: 0.906 to 0.998 for seven sets; storefront metal 0.12 (1 mm relief, metallic) | With the handedness flip removed, brick falls to -0.957 and paving to -0.982 |
| Clipping | Luminance histogram at wall, footway, street and kerb poses | 0 pixels at 250 or above, 0 at 5 or below |

Cast shadows: at the cornice pose, the wall 0.25 m under the soffit reads 32 with shadows and 133
without.

**The height map is unused.** Parallax at the physical factor (12 mm relief over an 1800 mm repeat)
changed mean luminance by 0.12, 0.16 and 0.11 at the wall, footway and door poses, with no pixel
changing by 8 or more, and would add 8,738,133 bytes of decoded texture for the bench street's
seven sets. At
four times the physical factor it changed at most 0.79 per cent of pixels by 8 or more. It does not
help at eye level, so look version 1 sets `surface.parallax` false and the map is never uploaded.

## 7. The evaluation entry

A tile can be named only on the synthetic development preview route:

- `generatedTileEvaluationName(search, preview)` in `web/packages/app/src/config.ts` returns a name
  only when `preview` is true, which `isAtlasPreview` makes false in every production build, and a
  preview session carries no workspace credential. The name must be lowercase words joined by single
  hyphens, 64 characters at most, so it can never be a path or a URL.
- `composition/renderer.ts` loads the tile only inside `import.meta.env.DEV`, so a production build
  drops the branch and the modules it imports; `composition/generated-tile.ts` refuses to run
  outside development preview as a second guard.
- `dev/generated-tile-sources.ts` resolves a name only among `dev/tiles/*.owd`, pinned development
  goldens described in that folder's README, and texture sets only among the committed blobs. It
  imports the blobs' URLs eagerly: they sit outside the app's workspace, and Vite's development
  server resolves a `?url` import of such a file only when a module imports it statically (a lazy
  import is answered with the raw bytes, so no cited set could load).
  `web/packages/app/test/generated-tile-sources.test.ts` starts a development server from the app's
  configuration and resolves every pinned set to its URL and its pinned bytes.
  Baked corridor streets are not repository files; they go to the baked tile store and a permission
  gated route, and nothing here reaches them.
- The preview title is left alone: the visual gate harness holds the shell to its title, and
  choosing a harness target for tiles belongs to the corridor lane.
- `environment-selection.ts` treats a mounted tile like the owned district and chooses the neutral
  overlay, so no NYC footprint lines are drawn over it.

Proof: `web/packages/app/test/generated-tile-evaluation.test.ts` builds the app with Vite in its own
process. The production build contains none of the evaluation path's markers (its attribute and
wording, the runtime's refusal text and sky name, tess's triangle digest domain), no `.owd` or
`.ltex` file, no file named for the tile runtime, and no copy of the tile's bytes inlined or not.
The control builds in development mode and finds all of them, so the test can fail. The same file
checks that a workspace query (`?tile=` without `preview=1`) and every path-like name get no tile.
`web/packages/app/test/generated-tile-golden.test.ts` rebakes `tile-conformance.owd` through tess's
own bake command and requires identical bytes.

### 7.1 The second entry: a tile fetched from the product route

A baked corridor street is never a file in this repository, so the preview route's goldens cannot
reach one. The second entry loads a tile from the product route instead, on the same development
page, and the difference between the two is where the container comes from:

- `bakedTileRequest(search, preview)` in `config.ts` reads `?preview=1&city=<64 hex>&tile_x=&tile_y=`
  with `lod` defaulting to 0, and `&baked_tile=<uuid>` as a shortcut that wins when both are given.
  A seed must be a 64 hex digest, a key a UUID and the coordinates bounded whole numbers, so no
  reading of that query can become a path. The coordinate is the public door because a key is uuid5
  over the stage version and inputs digest and so moves with every bake, while the coordinate a walk
  wants does not.
- `tile-route.ts` lists the city (metadata, no tile quota), picks the tile with `tileAt`, and fetches
  the container. It hashes what arrived and refuses anything whose digest is not the one the row
  records, naming both digests; refuses a container that carries no digest to check it against; and
  refuses from the list, with no request at all, a tile whose state is not `baked`.
- A reload asks for nothing. The list names each tile's `container_sha256`, so a container already
  held is used without a request, which is cheaper than a revalidation per tile. The request carries
  `If-None-Match` as well, so a 304 costs nothing where the route answers one.
- Refusals carry the route's own code and status and never a guess at the cause. An unknown key and a
  credential without `tiles.materialise` are both 404 `unknown_reference`: MEASURED against the
  running route, they share the status and the code and differ in detail and headers, because the
  permission floor refuses an id-addressed route before the route's own function runs. The pair this
  runtime relies on is the status and the code, and nothing here turns either answer into a claim
  about which one it was.
- With no development token the page refuses in plain words rather than asking anonymously, because
  an anonymous ask is answered exactly as an unknown tile is and a walker would be told the wrong
  thing.

**The split, which is a decision and not an accident.** The CONTAINER comes from the route with a
credential, because a generated tile must never be committed. The TEXTURE SETS come from the
committed library through the development page (`committedTextureLibrary()`), because they are
committed and no route serves the published texture library yet. A published-texture route is a real
gap and a future lane's work. The statement panel says both, with the container's digest and whether
the bytes were fetched, held or not modified, so no picture of a walk can imply a product path that
does not exist; the golden path prints its own line, so the two can never be mistaken for each other.

Proof: `atlas-react/test/generated-tile-route.test.ts` drives every status, header and problem body
the route really gives; `app/test/generated-tile-walk.test.ts` runs the whole page path with the
committed golden's bytes served as if fetched, and asserts the statement names the route and the
digest; `atlas-react/test/generated-tile-route-live.test.ts` runs against a RUNNING route and skips
itself unless one is named in the environment, so no credential can ever reach a suite. The live
proof is retained in `evidence/tile-route-loader.log.txt`.

## 8. Budget

Measured against the accepted Melbourne envelope per corridor: about 227,000 faces, 28 MB
transferred, 168 MB decoded texture, 87 draw calls, 16.7 ms p95 at 1440 by 900. The runs are in
`web/packages/atlas-react/test/generated-tile-bench/evidence/tile-route-budget.log.txt`, taken with
headless Chrome through `.exulanica/bin/quiet-slot`, with the load average before and after.

| Envelope | Measured | Within |
| --- | --- | --- |
| Frame p95 16.7 ms | Bench street, 7 sets, full look, 20 s walk at eye level: p50 16.7, p95 16.7, p99 16.8, max 16.8 ms on the app validation recorder's clock (two runs); script work 1.5 ms at p95 | Yes |
| 87 draw calls | 55, shadow cascades, occlusion and compose passes included | Yes |
| 168 MB decoded texture | 104,857,596 bytes for the 7 cited sets, plus a 1,671,168 byte probe; all 8 sets would be 121,634,808 | Yes |
| 28 MB transferred | The 7 cited sets: 65,551,200 bytes raw, 21,292,652 gzip, 17,955,391 brotli | Only from a compressing host |
| About 227,000 faces | 40 on the bench street; 512 on the conformance tile | Not measured at corridor scale |

Only the sets a tile cites are fetched. A GPU compressed transfer container is a texture lane
follow-up. The frame figures are the look's per-pixel cost at full screen; what 227,000 faces in a
handful of texture batches cost is unverified until the corridor lane bakes a street.

Default view unchanged: `evidence/default-view-comparison.log.txt` records a GPU readback (SHA-256 of
the whole backbuffer) at three poses on `?preview=1` with no tile, byte-identical between this
runtime's branch and main, first on 2026-09-16 and again after the rebase onto main 36e6d2dd.

## 8.1 The paired walk, stated before it is taken

Written before the tessellator 14 bake exists, so the numbers reported afterwards have something to be
checked against rather than something to be chosen to fit. The corridor lane pre-registered the same
walk from its side (its street document, commit 15d1352a); these are the parameters this lane will
match, so the two runs are one experiment from two directions rather than two similar ones.

| | |
| --- | --- |
| path | east along the footway centre line, y `70300`, from x `262000` toward x `378000` |
| pose | stated, `pose_x_mm=262000&pose_y_mm=70300&facing_dx=1&facing_dy=0`, never a default |
| movement | the product's own walking, a held W key through its movement and support resolution |
| stepping | `beginTileCapture().advance(dt)`, dt exactly 1/30 s, no clock consulted |
| never | no camera override and no writing of a position: a walk that teleports proves nothing about support |
| viewport | 1080 square, which is above the 960 px the app requires before it serves its boundary page |
| recorded | the camera's position every step, plus frames at the start, at x `320000` and at the end |
| compared against | the same capture on the tessellator 13 bake, where the walk advanced almost not at all |

**The question, and why one run could not answer it.** On tessellator 13 the walk barely advanced. Two
things could have caused that and the run cannot separate them: the seven tree-canopy holes, which
left 53 m of the 116 m unsupported, or the movement rule that returns a walker to safety each frame
instead of sliding along what it cannot enter. Tessellator 14's carve leaves the walked line
supported while `render_batch` is unchanged, so the picture is held constant and the only thing that
moves is the support. If the walk advances, the holes were the limit. If it does not, this is a
measurement of the recovery behaviour alone, which is worth more than the first run was.

**Neither half decides it alone, which is why both are stated here.** This lane's trace says where the
walker WENT. The corridor lane samples its own container every 100 mm along the same line and says
where the bake states a walker COULD have stood. Laid against each other at an x the container calls
unsupported, the trace either stops, drops 170 mm to the terrain, or passes over, and which of the
three it is cannot be read off a film. A trace without the container's support is a behaviour with no
ground truth; the sampling without a trace is ground truth with nothing walking on it. Both halves key
on the CONTAINER DIGEST rather than on a file name, so they can be lined up without either lane
trusting the other's label.

**What is not predicted.** What a walker does when they meet a metre of unsupported footway is the
corridor lane's open question and it is open here too: stopping, dropping to the terrain 170 mm below,
and stepping over are all honest answers. Recording the question in advance is what stops whichever
happens from being described afterwards as the expected behaviour.

**What the eye height is, read rather than remembered, and what it makes decidable.** The capsule comes
from the tile's own grammar table: city version 2 states `eye_height_mm` 1620 (`loom-tess/src/core/
city-v2.ts`), `tileCapsule` reads it and refuses a tile whose grammar states none, and the movement
rule puts the eye exactly that above the sampled support (`navigation.ts`: the target is
`sample.height + world.eyeHeight`, and the resolved position is `finalSample.height + world.eyeHeight`).
So a standing eye is support plus 1620 mm and nothing else, which is what lets this lane's trace and the
corridor lane's support heights SUBTRACT. On tessellator 13, whose footway support measures 147 to 170
mm, a standing eye reads 1767 to 1790 mm, and the behaviours separate:

| behaviour | signature in the pair |
| --- | --- |
| stops | x stops advancing, eye height holds near 1790 |
| passes over nothing | x advances across a gap the container calls unsupported while the eye holds near 1790 |
| drops to terrain | eye falls about 170 mm to near 1620 while x advances |

**A fourth signature this lane can predict from its own code**, which neither half would have guessed
from the street: a tile's navigation world states no regions (`tile-navigation.ts` passes an empty
list), so if movement ever recovers with no last safe position to return to, `nearestRegionEntry`
answers the world CENTRE at `world.eyeHeight` above the datum rather than above any support. That
reads as an eye at exactly 1620 mm, not 1767 to 1790, and an x that jumps to the middle of the tile.
If a trace shows that, it is not a walk at all and must not be reported as one.

**Read the pair, never x alone, and this is fixed before the run rather than after the number.** The
corridor lane's pre-registered midpoint capture is x `320000`, and tile (2,0) spans x 256000 to 384000
and y 0 to 128000, so ITS CENTRE IS ALSO x 320000. A trace reading x 320000 is therefore either a
walker who reached the midpoint or the recovery signature above, and x cannot tell them apart. The
disambiguator is y, 6.3 m of it: the walked line is y `70300` and the tile centre is y `64000`, which
is the far side of the carriageway.

| reading | what it is |
| --- | --- |
| x 320000, y 70300 | the walker reached the midpoint |
| x 320000, y 64000 | a recovery to the world centre, which is not a walk |

The eye height stands beside it as the second test: a recovery answers exactly 1620 above the datum,
while a walker standing on the footway answers that bake's support plus 1620.

**The mirror of this lane's eye caveat, from the corridor lane, recorded before the run:** its support
heights are the CONTAINER's, not the runtime's. If the runtime applied a step height, a ground offset,
or held the last known support where it found none, its idea of the floor would differ from the
container's by a constant or by a history, and neither half would see that alone. A clean difference
that is not 1620 is therefore the first thing to suspect, and a fact about the runtime worth having
rather than an error in either measurement.

**The walk, run 2026-09-18, and what the pair found.** On the tessellator 14 container
(`dd0dc7f6`, digest `2adf282b`) the walk ADVANCED: 121,982 mm continuously at 1.62 m/s, 23 to 55 mm a
step at dt 1/30, with the walked line's y constant at `70300` for all 3,000 steps. So this lane's
claim of the night before, that the walk barely advances, was about the tessellator 13 tree-canopy
holes and not about the capture or the movement rule. At x `378334` the eye fell 146 mm and the walker
came to rest at x `383999` for the remaining 779 steps.

That last stretch was first reported here as "the end of the world" and that was wrong. A third lane
read the records along the walked line and found the fall is 34 mm past where the Harbour Way 7 left
kerb ends, with the tile continuing 5.7 m further: it is the end of the PAVEMENT, not of the world,
and the 146 mm is exactly the footway's own height, so the walker stepped off the footway onto terrain
at the datum. Reading the trace for x `383000` to `383999` alone confirms it from this side: 797 steps,
the eye at 1620 for every one of them with no variation, y constant at `70300` throughout. So the
walked line held and the KERB turned away from it, not the other way about.

**Report a walk as segments by surface, not as one distance.** "121,982 mm continuous" is true and
hides that the surface changed 5.7 m before the end. A continuity claim is about the walker and says
nothing about what they were walking on, and neither of this lane's numbers, advance and eye height,
distinguishes a footway from terrain: only the eye height's VALUE does, and only against a support
height measured by somebody else.

Two instrument faults came out of it, and only the pair could have found the second.

*This lane's:* the trace records the CAMERA's world position, and the tile is mounted with its root
64 m away in x and z, so every raw reading was 64 m from the city frame the corridor lane samples in.
Corrected, the stated pose landed 17 mm from where it was stated, one step of walking, and that
agreement is what proves the correction rather than the correction proving itself. A frame mismatch
survives every check that compares a number with itself.

*The corridor lane's, and the reason the experiment was worth running from two directions:* its
sampler read the HIGHEST CORNER of the triangle under a sample point rather than interpolating the
plane at the point, and the footway falls 56 mm across its width to the gutter, so it overstated the
walked line by about 24 mm. Its number said a standing eye would be 1790; this lane measured 1766.
Corrected, support on that line is 146 mm everywhere and 146 + 1620 is exactly 1766. Nothing on
either side could have exposed that alone: the corridor lane's readings were all measured the same
wrong way and were internally consistent, and an eye height of 1766 says nothing without a support
height to subtract from it. `generated-tile-runtime.test.ts` now holds the line they agree on, that a
resolved move puts the eye exactly the stated eye height above the support it sampled.

**One candidate excluded by measurement, 2026-09-18, before either half ran.** The pre-registration
above is left as written; this is what has since been measured against it. The corridor lane sharpened
its sampler after finding that a point supported at 170 mm and a point supported at 0 mm both counted
as "supported", so a walker dropping off the kerb would have read as a continuous walk: the tool meant
to catch that behaviour could not see it. Reporting the support HEIGHT at 100 mm along the walked line
of the tessellator 13 container gives 1,161 samples, every supported one of them footway at 147 to 170
mm, no terrain level anywhere, and seven runs of NO SUPPORT AT ANY HEIGHT totalling 60.7 m of the 116,
which is more than the 53 to 56 m a 500 mm sampling had reported. So on that bake the candidate "drops
170 mm to the terrain" is excluded by the ground truth rather than by argument: where the footway is
carved away the envelope holds no triangle at any height, because the terrain had already yielded to
the footway's own record and the carve removes both. Two candidates remain there, stopping or passing
over nothing, and a trace can tell those apart. Whether the third returns on tessellator 14 is a
question for that container's own sampling, not for this paragraph.

## 9. After this runtime

- The corridor lane bakes the street and iterates on its look, at most three times, by editing
  `look.ts` and these modules.
- Dressed surfaces are drawn by the UV rule above as soon as tess draws a range that cites a
  material record; no tile does yet, so that path is covered by the `surfaceUv` tests only.
- Data view selection through `registerRepresentationSubjects`, after the data view lane merges.
- `collision_proxy` is consumed when tess materialises it.

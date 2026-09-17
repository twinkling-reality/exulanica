# Generated tile runtime

Status: IMPLEMENTED as a development evaluation only: the browser reads baked texture sets and
baked `.owd` tiles, draws a tile's `render_batch` with physically based materials under one
versioned look, and stands the player on its `nav_envelope`. No generated tile appears in any
person's world, and none may until a superseding governance ADR is accepted in writing. No baked
corridor street exists yet, so textured tile geometry has been seen only on a test-only bench.

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
| `glazing` | `base_color`, `transmission_roughness` | `base_color`, `normal` (x, y, z) if produced, `transmission_roughness`, `height` if produced | `double_sided` false, `ior_millionths` 1500000 |

A procedural set whose class bakes relief states `height_range_mm` and `cavity`; procedural glazing
states neither; a model-made set states `height_range_mm` only when it ships a height map. Every
map's description (name, components, what it holds, sRGB or linear, its decode words, and for a
normal its space and convention) must be exactly the layout's, and `coverage_permille` must equal
what the reader measures from the coverage channel (texels at or above the cutoff, in thousandths,
floored). `DecodedTextureSet` carries the profile, class, maker kind, typed class parameters, the
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
draws `opaque` sets, of either container profile and either maker; `cutout`, `decal` and `glazing`
draw the stated unavailable surface with the reason "material class X is not drawn by this runtime"
(`undrawnClassReason`), and nothing of theirs is uploaded, so glazing is never drawn as opaque.
Drawing those three classes follows section 3 of the texture proposal and comes next.

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
  goldens described in that folder's README, and texture sets only among the committed blobs.
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

## 9. After this runtime

- The corridor lane bakes the street and iterates on its look, at most three times, by editing
  `look.ts` and these modules.
- Dressed surfaces are drawn by the UV rule above as soon as tess draws a range that cites a
  material record; no tile does yet, so that path is covered by the `surfaceUv` tests only.
- Data view selection through `registerRepresentationSubjects`, after the data view lane merges.
- `collision_proxy` is consumed when tess materialises it.

# loom-tess fixtures

These files are hand written for tests. No stage emits them, and none may be served.

## `tile-conformance.json`

This is the conformance tile. The golden triangle digest in
`../triangle-digest-conformance.test.ts` is computed over it.

It is written by `build_fixture_document` in `tests/test_bake_determinism.py`, from the grammar's
own record classes. That test fails if the committed bytes drift. To regenerate it:

```bash
uv run python tests/test_bake_determinism.py --write-fixture
```

After regenerating, update the golden literal in the same commit.

The tile contains:

- a terrain grid, which draws;
- a lot whose ring has a chamfered corner edge under 1.2 m;
- a building with four facade records, one of them on that short edge;
- a vitrine behind the frontage glazing;
- one surface material bound to a pinned texture set;
- premises;
- a street with two nodes, a segment and two kerb runs;
- one tree position.

Where each value comes from:

| Value | Source |
| --- | --- |
| Record shapes, bounds and closed values | `exulanica/grammar/grammars/city`, validated by each stage's own validator |
| `texture_set_id` | `assets/textures/manifest.json`, checked with `require_texture_set` |
| `course_module_mm`, `mortar_module_mm` | the brick set's recipe: `unit_height_mm + bed_joint_mm`, and `bed_joint_mm` |
| `catalog_digest` | `catalog_digest(load_city_catalogs(...))` over the real catalogs and manifest |
| `edit_delta_digest` | `edit_delta_digest_of([])`, the empty subsequence |
| `tile_size_mm`, `halo_radius_mm`, `kerb_height_mm`, vitrine `depth_mm` | the grammar's own constants (kerb height is the midpoint of its bound, vitrine depth is its minimum) |
| Facade `grammar_version`, `parameters`, `seed`, `output_digest`, `declared_semantics` | a real `generate()` receipt under the fixture descriptor |
| Every key the empty catalogs cannot source | `unresolved_<field>`, proven to resolve to no catalog entry |
| The seed | SHA-256 of `exulanica loom-tess conformance fixture` |
| The building identity | uuid5 over a fixture URL; the test is the admitting party |
| Coordinates, heights, storey counts and heights, widths, offsets, ordinals | chosen fixture inputs |
| `uv_scale_millionths`, `uv_rotation_urad`, weathering and soiling | the identity transform and zero, not a chosen look |

## `cityrenderfixture.v1.json`

This is a test-only grammar descriptor, used over the real city record classes. It admits
`render_batch`. City version 1 admits no projection, so a city version 1 tile draws nothing.

When the city vocabulary lane ships a descriptor that admits projections:

1. move the fixture onto that descriptor;
2. replace the `unresolved_` keys with real catalog keys;
3. update the golden digest.

Do all three in one commit.

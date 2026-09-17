/**
 * The grammar table core reads is the grammar's own, not a transcription: the generated module
 * equals what the grammar's files state, and `tests/test_bake_determinism.py` holds it to
 * `describe_shapes` itself. Regenerate with `pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts`.
 */
import { describe, expect, it } from 'vitest';
import { CITY_V2 } from '../src/core/city-v2.js';
import { GRAMMAR_TABLES, PLANE, PROJECTIONS, TILE_SHAPE } from '../src/core/record-shapes.js';
import { grammarTableFromSources } from './grammar-table-sources.js';

describe('the grammar table', () => {
  it('is exactly the city grammar version 2 shape table and descriptor frame', () => {
    expect(JSON.parse(JSON.stringify(CITY_V2))).toEqual(grammarTableFromSources());
    expect(GRAMMAR_TABLES).toEqual([CITY_V2]);
  });

  it('gives the projections, the plane and the tile shape from the table itself', () => {
    expect(PROJECTIONS).toEqual(['render_batch', 'collision_proxy', 'nav_envelope', 'pick_geometry', 'export_gltf']);
    expect(PLANE).toBe('invented');
    expect(TILE_SHAPE.kind).toBe('city.tile');
    expect(TILE_SHAPE.version).toBe(2);
  });
});

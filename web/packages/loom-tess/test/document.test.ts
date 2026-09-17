/**
 * The tile document reader refuses rather than defaults: every case below is one broken thing in
 * the conformance fixture, and every one must be refused by name.
 */
import { describe, expect, it } from 'vitest';
import { bakeTile } from '../src/core/bake.js';
import { CanonicalJsonError, readTileDocument, TessellationError, TileDocumentError } from '../src/core/index.js';
import { AsciiError } from '../src/core/ascii.js';
import { OwdError } from '../src/core/owd.js';
import { nodeSha256 } from '../src/node/sha256.js';
import { documentBytes, fixtureBytes, fixtureObject, recordsOf } from './support.js';

const text = (): string => new TextDecoder().decode(fixtureBytes());
const bytesOf = (value: string): Uint8Array => new TextEncoder().encode(value);

/** The fixture, broken by one mutation, as canonical bytes. */
function broken(mutate: (document: any) => void): Uint8Array {
  const document = fixtureObject();
  mutate(document);
  return documentBytes(document);
}

const refuses = (bytes: Uint8Array, pattern: RegExp): void => {
  expect(() => readTileDocument(bytes)).toThrow(pattern);
};

describe('the tile document reader', () => {
  it('reads the conformance fixture', () => {
    const document = readTileDocument(fixtureBytes());
    expect(document.grammars).toHaveLength(1);
    expect(document.grammars[0]!.records).toHaveLength(16);
  });

  describe('refuses bytes that are not canonical JSON', () => {
    it.each([
      ['insignificant whitespace', (t: string) => t.replace('{"grammars":', '{ "grammars":')],
      ['keys out of order', (t: string) => t.replace('{"grammars":[', '{"profile":"x","grammars":[')],
      ['a fraction', (t: string) => t.replace('"lod":0', '"lod":0.0')],
      ['an exponent', (t: string) => t.replace('"tile_x":0', '"tile_x":0e0')],
      ['a repeated key', (t: string) => t.replace('"lod":0', '"lod":0,"lod":0')],
      ['a null', (t: string) => t.replace('"lod":0', '"lod":null')],
      ['a boolean', (t: string) => t.replace('"lod":0', '"lod":false')],
      ['not JSON at all', (t: string) => t.slice(1)],
    ])('%s', (_name, mutate) => {
      expect(() => readTileDocument(bytesOf(mutate(text())))).toThrow(CanonicalJsonError);
    });

    it('a trailing newline, which is not printable ASCII', () => {
      expect(() => readTileDocument(bytesOf(`${text()}\n`))).toThrow(AsciiError);
    });

    it('a byte outside printable ASCII', () => {
      const bytes = fixtureBytes();
      bytes[bytes.indexOf(0x61)] = 0xe9;
      expect(() => readTileDocument(bytes)).toThrow(AsciiError);
    });
  });

  describe('refuses a document that is canonical and wrong', () => {
    it.each([
      ['an unknown top-level key', (d: any) => { d.extra = 1; }, /unknown keys \["extra"\]/],
      ['a missing top-level key', (d: any) => { delete d.profile; }, /missing keys \["profile"\]/],
      ['another profile', (d: any) => { d.profile = 'exulanica.tile-document/v2'; }, /profile/],
      ['an unknown record field', (d: any) => { recordsOf(d, 'city.terrain')[0].fields.colour = 1; }, /unknown keys \["colour"\]/],
      ['a missing record field', (d: any) => { delete recordsOf(d, 'city.terrain')[0].fields.cell_mm; }, /missing keys \["cell_mm"\]/],
      ['a string where an integer goes', (d: any) => { recordsOf(d, 'city.terrain')[0].fields.cell_mm = '4000'; }, /cell_mm: is not an integer/],
      ['a kerb below 100 mm', (d: any) => { recordsOf(d, 'city.street_segment')[0].fields.kerb_height_mm = 99; }, /below its minimum 100/],
      ['a kerb above 180 mm', (d: any) => { recordsOf(d, 'city.street_segment')[0].fields.kerb_height_mm = 181; }, /above its maximum 180/],
      ['a shallow vitrine', (d: any) => { recordsOf(d, 'city.vitrine')[0].fields.depth_mm = 599; }, /below its minimum 600/],
      ['a rotation past one turn', (d: any) => { recordsOf(d, 'city.surface_material')[0].fields.uv_rotation_urad = 6283186; }, /above its maximum/],
      ['an unknown record kind', (d: any) => { recordsOf(d, 'city.parcel')[0].kind = 'city.lawn'; }, /record kind "city.lawn"/],
      ['another record version', (d: any) => { recordsOf(d, 'city.parcel')[0].version = 2; }, /version: is 2, above its maximum 1/],
      ['a repeated record', (d: any) => { d.grammars[0].records.push(recordsOf(d, 'city.parcel')[0]); }, /repeats a record exactly/],
      ['a side that is neither', (d: any) => { recordsOf(d, 'city.curb_edge')[0].fields.side = 'middle'; }, /is not one of/],
      ['a closed ring', (d: any) => { const f = recordsOf(d, 'city.parcel')[0].fields; f.boundary_mm.push(f.boundary_mm[0]); }, /closed by repeating/],
      ['a segment from a node to itself', (d: any) => { recordsOf(d, 'city.street_segment')[0].fields.end_node = 0; }, /joins a node to itself/],
      ['a curb that follows itself', (d: any) => { recordsOf(d, 'city.curb_edge')[0].fields.next_curb_ordinal = 0; }, /follows itself/],
      ['a grid short of samples', (d: any) => { recordsOf(d, 'city.terrain')[0].fields.height_mm.pop(); }, /columns \* rows = 16/],
      ['a setback at the top storey', (d: any) => { recordsOf(d, 'city.massing')[0].fields.setbacks = [[4, 1500]]; }, /above its maximum 3/],
      ['crossings out of order', (d: any) => { recordsOf(d, 'city.street_segment')[0].fields.crossing_offsets_mm = [9000, 2000]; }, /strictly increasing/],
      ['unsorted facade parameters', (d: any) => { recordsOf(d, 'city.facade')[0].fields.parameters = [['b', 1], ['a', 1]]; }, /sorted by name/],
      ['a texture set id that is not one', (d: any) => { recordsOf(d, 'city.surface_material')[0].fields.texture_set_id = 'Brick'; }, /texture set id/],
      ['a material with its texture set stripped', (d: any) => { delete recordsOf(d, 'city.surface_material')[0].fields.texture_set_id; }, /missing keys \["texture_set_id"\]/],
      ['an identity that is not a UUID', (d: any) => { recordsOf(d, 'city.massing')[0].fields.building_identity = 'house-1'; }, /canonical lowercase UUID/],
      ['a seed in capitals', (d: any) => { d.tile.fields.city_seed = d.tile.fields.city_seed.toUpperCase(); }, /seed/],
      ['a tile of another size', (d: any) => { d.tile.fields.tile_size_mm = 64000; }, /below its minimum 128000/],
      ['a grammar the tile does not name', (d: any) => { d.grammars[0].grammar_id = 'city'; }, /grammar_id: is not "cityrenderfixture"/],
      ['a grammar at another version', (d: any) => { d.grammars[0].grammar_version = 2; }, /grammar_version: is not 1/],
      ['a plane that is not invented', (d: any) => { d.grammars[0].declared_semantics.plane = 'recorded'; }, /plane/],
      ['a use that is not a projection', (d: any) => { d.grammars[0].declared_semantics.admissible_uses = ['display']; }, /is not one of/],
      ['a repeated use', (d: any) => { d.grammars[0].declared_semantics.admissible_uses = ['render_batch', 'render_batch']; }, /repeats a use/],
    ] as [string, (d: any) => void, RegExp][])('%s', (_name, mutate, pattern) => {
      refuses(broken(mutate), pattern);
    });

    it('names the refusal type', () => {
      expect(() => readTileDocument(broken((d) => { d.extra = 1; }))).toThrow(TileDocumentError);
    });
  });
});

describe('the bake', () => {
  it('refuses a level of detail it does not draw', async () => {
    await expect(bakeTile(broken((d) => { d.tile.fields.lod = 1; }), nodeSha256)).rejects.toThrow(/level of detail 0 only/);
  });

  it('draws nothing a grammar does not admit, and says so for every record', async () => {
    const bake = await bakeTile(
      broken((d) => { d.grammars[0].declared_semantics.admissible_uses = []; }),
      nodeSha256,
    );
    for (const mesh of bake.tessellation.projections) {
      expect(mesh.vertices).toHaveLength(0);
      expect(new Set(mesh.entries.map((entry) => entry.state))).toEqual(new Set(['not_admitted']));
    }
  });

  it('admits projections one by one', async () => {
    const bake = await bakeTile(
      broken((d) => { d.grammars[0].declared_semantics.admissible_uses = ['nav_envelope']; }),
      nodeSha256,
    );
    const [render, nav] = bake.tessellation.projections;
    expect(render!.vertices).toHaveLength(0);
    expect(nav!.vertices).toHaveLength(48);
  });

  it('states a one-sample-wide grid as unavailable rather than drawing a line', async () => {
    const bake = await bakeTile(
      broken((d) => {
        const fields = recordsOf(d, 'city.terrain')[0].fields;
        fields.columns = 1;
        fields.rows = 16;
      }),
      nodeSha256,
    );
    const terrain = bake.tessellation.records.findIndex((record) => record.payload.kind === 'city.terrain');
    expect(bake.tessellation.projections[0]!.entries[terrain]).toEqual({
      record: terrain,
      state: 'unavailable',
      needs: ['grid_with_area'],
    });
  });

  it('refuses coordinates a double cannot hold exactly', async () => {
    const huge = broken((d) => { recordsOf(d, 'city.terrain')[0].fields.origin_x_mm = Number.MAX_SAFE_INTEGER - 4000; });
    await expect(bakeTile(huge, nodeSha256)).rejects.toBeInstanceOf(TessellationError);
  });

  it('refuses a span the container cannot hold as int32 offsets', async () => {
    const wide = broken((d) => { recordsOf(d, 'city.terrain')[0].fields.cell_mm = 1_000_000_000; });
    await expect(bakeTile(wide, nodeSha256)).rejects.toBeInstanceOf(OwdError);
  });
});

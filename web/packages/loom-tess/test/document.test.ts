/**
 * The tile document reader refuses rather than defaults: every case below is one broken thing in
 * the conformance fixture, and every one must be refused by name.
 */
import { describe, expect, it } from 'vitest';
import { bakeTile } from '../src/core/bake.js';
import { CanonicalJsonError, readTileDocument, TessellationError, TileDocumentError } from '../src/core/index.js';
import { AsciiError } from '../src/core/ascii.js';
import { nodeSha256 } from '../src/node/sha256.js';
import { documentBytes, dressedTerrainObject, fixtureBytes, fixtureObject, recordsOf, sortList } from './support.js';

const text = (): string => new TextDecoder().decode(fixtureBytes());
const bytesOf = (value: string): Uint8Array => new TextEncoder().encode(value);

/** The fixture, broken by one mutation, as canonical bytes. */
function broken(mutate: (document: any) => void, start: () => any = fixtureObject): Uint8Array {
  const document = start();
  mutate(document);
  return documentBytes(document);
}

const refuses = (bytes: Uint8Array, pattern: RegExp): void => {
  expect(() => readTileDocument(bytes)).toThrow(pattern);
};

const owned = (d: any): any[] => d.grammars[0].owned;
const first = (d: any, kind: string): any => recordsOf(d, kind)[0].fields;

describe('the tile document reader', () => {
  it('reads the conformance fixture', () => {
    const document = readTileDocument(fixtureBytes());
    const fixture = fixtureObject();
    expect(document.grammars).toHaveLength(1);
    expect(document.grammars[0]!.owned).toHaveLength(fixture.grammars[0].owned.length);
    expect(document.grammars[0]!.halo).toHaveLength(fixture.grammars[0].halo.length);
    expect(document.grammars[0]!.subject_identity).toBe(fixture.grammars[0].subject_identity);
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
      ['the version 1 profile', (d: any) => { d.profile = 'exulanica.tile-document/v1'; }, /profile/],
      ['an unknown record field', (d: any) => { first(d, 'city.terrain').colour = 1; }, /unknown keys \["colour"\]/],
      ['a missing record field', (d: any) => { delete first(d, 'city.terrain').cell_mm; }, /missing keys \["cell_mm"\]/],
      ['a string where an integer goes', (d: any) => { first(d, 'city.terrain').cell_mm = '8000'; }, /cell_mm: is not an integer/],
      ['a kerb below 100 mm', (d: any) => { first(d, 'city.curb_edge').kerb_height_mm = 99; }, /below its minimum 100/],
      ['a kerb above 180 mm', (d: any) => { first(d, 'city.curb_edge').kerb_height_mm = 181; }, /above its maximum 180/],
      ['a shallow vitrine', (d: any) => { first(d, 'city.vitrine').depth_mm = 599; }, /below its minimum 600/],
      ['a rotation past one turn', (d: any) => { first(d, 'city.surface_material').uv_rotation_urad = 6283186; }, /above its maximum/],
      ['an unknown record kind', (d: any) => { recordsOf(d, 'city.parcel')[0].kind = 'city.lawn'; }, /record kind "city.lawn"/],
      ['another record version', (d: any) => { recordsOf(d, 'city.parcel')[0].version = 3; }, /version: is 3, above its maximum 2/],
      ['a repeated record', (d: any) => { owned(d).push(recordsOf(d, 'city.parcel')[0]); sortList(owned(d)); }, /by kind, version and identity, each once/],
      ['records out of order', (d: any) => { owned(d).reverse(); }, /by kind, version and identity, each once/],
      ['an identity both owned and halo', (d: any) => { owned(d).push(recordsOf(d, 'city.street')[0]); sortList(owned(d)); }, /stated by two records/],
      ['a tile record among the records', (d: any) => { owned(d).push(d.tile); sortList(owned(d)); }, /is a tile record/],
      ['a choice that is not one', (d: any) => { first(d, 'city.curb_edge').side = 'middle'; }, /is not one of/],
      ['a ring of two vertices', (d: any) => { const f = first(d, 'city.parcel'); f.boundary_mm = f.boundary_mm.slice(0, 2); }, /fewer than 3 vertices/],
      ['a plan point with three coordinates', (d: any) => { first(d, 'city.parcel').boundary_mm[0].push(0); }, /does not have 2 coordinates/],
      ['a point with two coordinates where three go', (d: any) => { first(d, 'city.curb_edge').kerb_line_mm[0].pop(); }, /does not have 3 coordinates/],
      ['a point repeated at once', (d: any) => { const line = first(d, 'city.curb_edge').kerb_line_mm; line.splice(1, 0, [...line[0]]); }, /repeats point 0 at 1/],
      ['more points than the field holds', (d: any) => { const line = first(d, 'city.crossing').line_mm; line.push([...line[1]].map((v: number) => v + 1)); }, /holds more than 2/],
      ['two where at most one goes', (d: any) => { const f = first(d, 'city.curb_edge'); f.next_curb_identity = [f.identity, f.segment_identity].sort(); }, /holds more than 1/],
      ['turns out of order', (d: any) => { recordsOf(d, 'city.lane').find((l: any) => l.fields.turns.length === 2).fields.turns.reverse(); }, /in the order/],
      ['a repeated identity in a list', (d: any) => { const f = first(d, 'city.junction'); f.segment_identities.push(f.segment_identities[0]); }, /repeats an item/],
      ['storeys that do not increase', (d: any) => { first(d, 'city.facade').openings[0].storeys = [2, 1]; }, /strictly increasing/],
      ['a nested record with an unknown field', (d: any) => { first(d, 'city.massing').tiers[0].colour = 1; }, /tiers\[0\]: unknown keys \["colour"\]/],
      ['a nested integer that is text', (d: any) => { first(d, 'city.facade').bays.count = '2'; }, /bays.count: is not an integer/],
      ['a light well of two vertices', (d: any) => { const t = first(d, 'city.massing').tiers[1]; t.light_wells_mm[0] = t.light_wells_mm[0].slice(0, 2); }, /fewer than 3 vertices/],
      ['text with surrounding space', (d: any) => { first(d, 'city.street').name_text = ' Mill Lane'; }, /surrounding space/],
      ['a parameter value that is neither an integer nor a key', (d: any) => { first(d, 'city.facade').parameters[0].value = 'Twelve'; }, /is not a key/],
      ['a texture set id that is not one', (d: any) => { first(d, 'city.surface_material').texture_set_id = 'Brick'; }, /texture set id/],
      ['a material with its texture set stripped', (d: any) => { delete first(d, 'city.surface_material').texture_set_id; }, /missing keys \["texture_set_id"\]/],
      ['an identity that is not a UUID', (d: any) => { first(d, 'city.massing').identity = 'house-1'; }, /canonical lowercase UUID/],
      ['a seed in capitals', (d: any) => { d.tile.fields.city_seed = d.tile.fields.city_seed.toUpperCase(); }, /seed/],
      ['a tile of another size', (d: any) => { d.tile.fields.tile_size_mm = 64000; }, /below its minimum 128000/],
      ['a tile with another ownership rule', (d: any) => { d.tile.fields.ownership_rule = 'nearest'; }, /ownership_rule: is not one of/],
      ['a grammar the tile does not pin', (d: any) => { d.grammars[0].grammar_id = 'town'; }, /grammar_id: is not the tile's pin/],
      ['a descriptor the tile does not pin', (d: any) => { d.grammars[0].descriptor_sha256 = '0'.repeat(64); }, /descriptor_sha256: is not the tile's pin/],
      ['a grammar version this tessellator does not read', (d: any) => { d.grammars[0].grammar_version = 1; d.tile.fields.grammar_versions[0].grammar_version = 1; }, /reads \["city 2"\] only/],
      ['a plane that is not invented', (d: any) => { d.grammars[0].declared_semantics.plane = 'recorded'; }, /plane: is not one of/],
      ['a use that is not a projection', (d: any) => { d.grammars[0].declared_semantics.admissible_uses = ['display']; }, /is not one of/],
      ['uses out of order', (d: any) => { d.grammars[0].declared_semantics.admissible_uses = ['nav_envelope', 'render_batch']; }, /in the order/],
      ['a repeated use', (d: any) => { d.grammars[0].declared_semantics.admissible_uses = ['render_batch', 'render_batch']; }, /repeats an item/],
      ['a subject identity that is not a UUID', (d: any) => { d.grammars[0].subject_identity = 'city'; }, /subject_identity: is not a canonical lowercase UUID/],
    ] as [string, (d: any) => void, RegExp][])('%s', (_name, mutate, pattern) => {
      refuses(broken(mutate), pattern);
    });

    it('names the refusal type', () => {
      expect(() => readTileDocument(broken((d) => { d.extra = 1; }))).toThrow(TileDocumentError);
    });
  });
});

describe('the bake', () => {
  const bake = (bytes: Uint8Array) => bakeTile(bytes, nodeSha256);
  const terrainEntry = async (bytes: Uint8Array, projection: number) => {
    const baked = await bake(bytes);
    const index = baked.tessellation.records.findIndex((record) => record.payload.kind === 'city.terrain');
    return baked.tessellation.projections[projection]!.entries[index];
  };

  it('refuses a level of detail it does not draw', async () => {
    await expect(bake(broken((d) => { d.tile.fields.lod = 1; }))).rejects.toThrow(/level of detail 0 only/);
  });

  it('draws nothing a grammar does not admit, and says so for every owned record', async () => {
    const baked = await bake(broken((d) => { d.grammars[0].declared_semantics.admissible_uses = []; }));
    for (const mesh of baked.tessellation.projections) {
      expect(mesh.vertices).toHaveLength(0);
      expect(new Set(mesh.entries.map((entry) => entry.state))).toEqual(new Set(['not_admitted', 'halo']));
    }
  });

  it('admits projections one by one', async () => {
    const baked = await bake(broken((d) => { d.grammars[0].declared_semantics.admissible_uses = ['nav_envelope']; }));
    const [render, nav] = baked.tessellation.projections;
    expect(render!.vertices).toHaveLength(0);
    expect(new Set(render!.entries.map((entry) => entry.state))).toEqual(new Set(['not_admitted', 'halo']));
    expect(nav!.vertices.length).toBeGreaterThan(0);
  });

  it('states terrain that something covers everywhere as unavailable rather than drawing under it', async () => {
    const covered = broken((d) => {
      Object.assign(first(d, 'city.block').extent, { min_x_mm: 0, min_y_mm: 0, max_x_mm: 128000, max_y_mm: 128000 });
    });
    expect(await terrainEntry(covered, 1)).toMatchObject({ state: 'unavailable', needs: ['ground_coverage'] });
  });

  it('keeps support a capsule radius clear of a record that stands just outside a cell', async () => {
    // A lamp's stated extent 200 mm, then 400 mm, east of the tile's south-east cell, which it
    // never meets. Within the 340 mm radius the cell is left out; beyond it the cell is kept.
    const nearEast = (gap: number) => broken((d) => {
      Object.assign(first(d, 'city.street_furniture').extent, {
        min_x_mm: 128000 + gap, max_x_mm: 128000 + gap + 100, min_y_mm: 4000, max_y_mm: 4100,
      });
    });
    const southEastCell = async (bytes: Uint8Array): Promise<boolean> => {
      const baked = await bake(bytes);
      const nav = baked.tessellation.projections[1]!;
      for (let triangle = 0; triangle < nav.indices.length / 3; triangle += 1) {
        const xs = [0, 1, 2].map((corner) => nav.vertices[nav.indices[triangle * 3 + corner]! * 3]!);
        const ys = [0, 1, 2].map((corner) => nav.vertices[nav.indices[triangle * 3 + corner]! * 3 + 1]!);
        if (Math.min(...xs) === 120000 && Math.min(...ys) === 0) return true;
      }
      return false;
    };
    expect(await southEastCell(fixtureBytes())).toBe(true);
    expect(await southEastCell(nearEast(200))).toBe(false);
    expect(await southEastCell(nearEast(400))).toBe(true);
    // Render draws the whole patch either way.
    const render = (await bake(nearEast(200))).tessellation.projections[0]!;
    expect(render.indices.length / 3).toBe(16 * 16 * 2);
  });

  it('refuses a terrain grid that does not span its tile', async () => {
    await expect(bake(broken((d) => { first(d, 'city.terrain').cell_mm = 4000; }))).rejects.toThrow(/do not span its tile/);
  });

  it('refuses a vertex outside the extent its record states', async () => {
    await expect(bake(broken((d) => { first(d, 'city.terrain').height_mm[0] = 10; }))).rejects.toThrow(TessellationError);
    await expect(bake(broken((d) => { first(d, 'city.terrain').height_mm[0] = 10; }))).rejects.toThrow(/outside the extent it states/);
  });

  it('refuses coordinates a double cannot hold exactly', async () => {
    const far = broken((d) => { first(d, 'city.terrain').tile_x = Number.MAX_SAFE_INTEGER; });
    await expect(bake(far)).rejects.toBeInstanceOf(TessellationError);
  });

  it('draws a dressed surface and refuses a dressing that does not fit it', async () => {
    expect(await terrainEntry(documentBytes(dressedTerrainObject()), 0)).toMatchObject({ state: 'drawn' });
    const otherKind = broken((d) => { recordsOf(d, 'city.surface_material').find((m: any) => m.fields.role === 'terrain').fields.surface_kind = 'city.block'; }, dressedTerrainObject);
    await expect(bake(otherKind)).rejects.toThrow(/names another kind of surface/);
    const twice = broken((d) => {
      const dressing = recordsOf(d, 'city.surface_material').find((m: any) => m.fields.role === 'terrain');
      const copy = JSON.parse(JSON.stringify(dressing));
      copy.fields.identity = '00000000-0000-5000-8000-000000000000';
      owned(d).push(copy);
      sortList(owned(d));
    }, dressedTerrainObject);
    await expect(bake(twice)).rejects.toThrow(/two material records dress/);
  });
});

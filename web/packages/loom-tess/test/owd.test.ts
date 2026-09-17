/**
 * The pure decoder refuses anything the writer would not have produced, and `verifyOwd` refuses
 * anything its own records do not bake to. Each case breaks one thing in the baked fixture.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import { bakeTile, verifyOwd } from '../src/core/bake.js';
import { absoluteVertices, decodeOwd, OwdError } from '../src/core/owd.js';
import { nodeSha256 } from '../src/node/sha256.js';
import { fixtureBytes } from './support.js';

let baked: Uint8Array;

beforeAll(async () => {
  baked = (await bakeTile(fixtureBytes(), nodeSha256)).container;
});

const copy = (): Uint8Array => new Uint8Array(baked);
const headerLength = (bytes: Uint8Array): number => new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, true);
const headerText = (bytes: Uint8Array): string =>
  new TextDecoder().decode(bytes.subarray(8, 8 + headerLength(bytes)));

/** Replace text in the header without changing its length, so the layout stays where it was. */
function sameLength(from: string, to: string): Uint8Array {
  expect(to).toHaveLength(from.length);
  const bytes = copy();
  const text = headerText(bytes);
  const at = text.indexOf(from);
  expect(at, `${from} is in the header`).toBeGreaterThanOrEqual(0);
  bytes.set(new TextEncoder().encode(to), 8 + at);
  return bytes;
}

const refused = (bytes: Uint8Array, pattern: RegExp): void => {
  expect(() => decodeOwd(bytes)).toThrow(OwdError);
  expect(() => decodeOwd(bytes)).toThrow(pattern);
};

function sectionOffset(bytes: Uint8Array, projection: string, name: string): number {
  const header = JSON.parse(headerText(bytes)) as {
    sections: { projection: string; name: string; byte_offset: number }[];
  };
  return header.sections.find((section) => section.projection === projection && section.name === name)!.byte_offset;
}

describe('decodeOwd', () => {
  it('decodes the fixture into views over its own bytes', () => {
    const decoded = decodeOwd(baked);
    expect(decoded.projections.map((projection) => projection.header.name)).toEqual(['render_batch', 'nav_envelope']);
    const render = decoded.projections[0]!;
    expect(render.positionMm.buffer).toBe(baked.buffer);
    expect(render.position).toHaveLength(48);
    expect(render.index).toHaveLength(54);
    const vertices = absoluteVertices(render);
    // The float payload is the integers in metres from the origin, and nothing else.
    render.position.forEach((value, index) => {
      const origin = render.header.origin_mm[index % 3] as number;
      expect(value).toBe(Math.fround((vertices[index]! - origin) / 1000));
    });
  });

  it('copies once when the bytes do not start on a four-byte boundary', () => {
    const shifted = new Uint8Array(baked.length + 1);
    shifted.set(baked, 1);
    const decoded = decodeOwd(shifted.subarray(1));
    expect(Array.from(decoded.projections[0]!.positionMm)).toEqual(Array.from(decodeOwd(baked).projections[0]!.positionMm));
  });

  it.each([
    ['another magic', () => { const b = copy(); b[0] = 0x58; return b; }, /magic/],
    ['a truncated preamble', () => baked.slice(0, 6), /shorter than its preamble/],
    ['a header running past the end', () => { const b = copy(); new DataView(b.buffer).setUint32(4, b.length, true); return b; }, /runs past the end/],
    ['a header that is not canonical', () => sameLength('"tile_x":0,"tile_y":0', '"tile_y":0,"tile_x":0'), /not canonical JSON/],
    ['a padding byte that is not a space', () => { const b = copy(); b[8 + headerLength(b)] = 0x2e; return b; }, /padding byte/],
    ['a trailing byte', () => { const b = new Uint8Array(baked.length + 4); b.set(baked); return b; }, /sections end at/],
    ['a missing byte', () => baked.slice(0, baked.length - 4), /sections end at/],
    ['another tessellator version', () => sameLength('"tessellator_version":1', '"tessellator_version":2'), /no upgrade on read/],
    ['another profile', () => sameLength('exulanica.owd/v1', 'exulanica.owd/v2'), /profile/],
    ['a truth that is not invented', () => sameLength('"truth":"invented"', '"truth":"recorded"'), /truth/],
    ['a need nobody states', () => sameLength('"crossing_width"', '"crossing_depth"'), /unknown need/],
    ['an entry out of record order', () => sameLength('"needs":["base_elevation"],"record":0', '"needs":["base_elevation"],"record":1'), /record is not 0/],
    ['an identity the record does not state', () => sameLength('"identity":"not-stated"', '"identity":"not-stat3d"'), /identity is not not-stated/],
    ['a section somewhere else', () => { const b = copy(); const text = headerText(b); const offset = sectionOffset(b, 'render_batch', 'position'); const at = text.indexOf(`"byte_offset":${offset}`); b[8 + at + 14] = b[8 + at + 14] === 0x31 ? 0x32 : 0x31; return b; }, /contiguous layout/],
    ['a contract this version does not write', () => sameLength('"sampling support height"', '"sampling support heighT"'), /contract/],
  ] as [string, () => Uint8Array, RegExp][])('refuses %s', (_name, make, pattern) => {
    refused(make(), pattern);
  });

  it('refuses an index outside its range', () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'render_batch', 'index');
    new DataView(bytes.buffer).setUint32(at, 99, true);
    refused(bytes, /indexes outside its range/);
  });

  it('refuses an extent its vertices do not have', () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'nav_envelope', 'position_mm');
    const view = new DataView(bytes.buffer);
    view.setInt32(at, view.getInt32(at, true) - 1, true);
    refused(bytes, /extent its vertices do not have/);
  });
});

describe('verifyOwd', () => {
  it('accepts the fixture', async () => {
    await expect(verifyOwd(baked, nodeSha256)).resolves.toBeDefined();
  });

  it('refuses a float payload the integers do not give', async () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'render_batch', 'position');
    bytes[at + 1] = bytes[at + 1]! ^ 0x01;
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses surface coordinates the records do not give', async () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'render_batch', 'surface_mm');
    bytes[at + 4] = bytes[at + 4]! ^ 0x01;
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses a record whose fields no longer match its digest', async () => {
    const bytes = sameLength('"address_number":1', '"address_number":2');
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses a triangle digest the triangles do not give', async () => {
    const header = headerText(baked);
    const digest = /"name":"nav_envelope","origin_mm":\[[^\]]*\],"triangle_count":18,"triangle_digest":"([0-9a-f]{64})"/.exec(header)![1]!;
    const bytes = sameLength(digest, digest.replace(/^./, digest[0] === '0' ? '1' : '0'));
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });
});

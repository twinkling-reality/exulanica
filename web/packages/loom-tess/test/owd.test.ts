/**
 * The pure decoder refuses anything the writer would not have produced, and `verifyOwd` refuses
 * anything its own records do not bake to. Each case breaks one thing in the baked fixture, or in
 * the test-only variant whose terrain is dressed, where a render range is needed to break.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import { bakeTile, verifyOwd } from '../src/core/bake.js';
import { absoluteVertices, decodeOwd, encodeOwd, OwdError } from '../src/core/owd.js';
import type { Bake } from '../src/core/bake.js';
import { nodeSha256 } from '../src/node/sha256.js';
import { documentBytes, dressedTerrainObject, fixtureBytes } from './support.js';

let baked: Bake;
let dressed: Uint8Array;

beforeAll(async () => {
  baked = await bakeTile(fixtureBytes(), nodeSha256);
  dressed = (await bakeTile(documentBytes(dressedTerrainObject()), nodeSha256)).container;
});

const copy = (bytes: Uint8Array = baked.container): Uint8Array => new Uint8Array(bytes);
const headerLength = (bytes: Uint8Array): number => new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, true);
const headerText = (bytes: Uint8Array): string =>
  new TextDecoder().decode(bytes.subarray(8, 8 + headerLength(bytes)));

/** Replace text in the header without changing its length, so the layout stays where it was. */
function sameLength(from: string, to: string, source: Uint8Array = baked.container): Uint8Array {
  expect(to).toHaveLength(from.length);
  const bytes = copy(source);
  const text = headerText(bytes);
  const at = text.indexOf(from);
  expect(at, `${from} is in the header`).toBeGreaterThanOrEqual(0);
  bytes.set(new TextEncoder().encode(to), 8 + at);
  return bytes;
}

/** The first match of `pattern` in the header, with its first capture changed in one character. */
function oneCharacter(pattern: RegExp, source: Uint8Array = baked.container): Uint8Array {
  const match = pattern.exec(headerText(source))!;
  const value = match[1]!;
  const changed = value.replace(/^./, value[0] === '0' ? '1' : '0');
  return sameLength(match[0], match[0].replace(value, changed), source);
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
    const decoded = decodeOwd(baked.container);
    expect(decoded.projections.map((projection) => projection.header.name)).toEqual(['render_batch', 'nav_envelope']);
    const nav = decoded.projections[1]!;
    expect(nav.positionMm.buffer).toBe(baked.container.buffer);
    expect(nav.position).toHaveLength(nav.header.vertex_count * 3);
    expect(nav.index).toHaveLength(nav.header.triangle_count * 3);
    const vertices = absoluteVertices(nav);
    // The float payload is the integers in metres from the origin, and nothing else.
    nav.position.forEach((value, index) => {
      const origin = nav.header.origin_mm[index % 3] as number;
      expect(value).toBe(Math.fround((vertices[index]! - origin) / 1000));
    });
    expect(decoded.header.grammars[0]!.frame.name).toBe('city_local');
  });

  it('copies once when the bytes do not start on a four-byte boundary', () => {
    const shifted = new Uint8Array(baked.container.length + 1);
    shifted.set(baked.container, 1);
    const decoded = decodeOwd(shifted.subarray(1));
    expect(Array.from(decoded.projections[1]!.positionMm)).toEqual(Array.from(decodeOwd(baked.container).projections[1]!.positionMm));
  });

  it.each([
    ['another magic', () => { const b = copy(); b[3] = 0x31; return b; }, /magic/],
    ['a truncated preamble', () => baked.container.slice(0, 6), /shorter than its preamble/],
    ['a header running past the end', () => { const b = copy(); new DataView(b.buffer).setUint32(4, b.length, true); return b; }, /runs past the end/],
    ['a header that is not canonical', () => sameLength('"tile_x":0,"tile_y":0', '"tile_y":0,"tile_x":0'), /not canonical JSON/],
    ['a padding byte that is not a space', () => { const b = copy(); b[8 + headerLength(b)] = 0x2e; return b; }, /padding byte/],
    ['a trailing byte', () => { const b = new Uint8Array(baked.container.length + 4); b.set(baked.container); return b; }, /sections end at/],
    ['a missing byte', () => baked.container.slice(0, baked.container.length - 4), /sections end at/],
    ['another tessellator version', () => sameLength('"tessellator_version":2', '"tessellator_version":3'), /no upgrade on read/],
    ['another profile', () => sameLength('exulanica.owd/v2', 'exulanica.owd/v3'), /profile/],
    ['a truth that is not invented', () => sameLength('"truth":"invented"', '"truth":"recorded"'), /truth/],
    ['a frame its grammar does not state', () => sameLength('"name":"city_local"', '"name":"city_locum"'), /frame is not the frame/],
    ['a subject identity that is not a UUID', () => { const at = /"subject_identity":"[0-9a-f]/.exec(headerText(baked.container))![0]; return sameLength(at, `${at.slice(0, -1)}X`); }, /subject_identity is not a UUID/],
    ['a membership that is neither', () => sameLength('"membership":"owned"', '"membership":"ownex"'), /membership is not one of/],
    ['a need nobody states', () => sameLength('"crossing_band"', '"crossing_bond"'), /unknown need/],
    ['an entry out of record order', () => sameLength('"needs":["ring_triangulation"],"record":0', '"needs":["ring_triangulation"],"record":1'), /record is not 0/],
    ['an identity the record does not state', () => oneCharacter(/"grammar":0,"identity":"([0-9a-f-]{36})"/), /identity is not the identity the record states/],
    ['a section somewhere else', () => { const b = copy(); const text = headerText(b); const offset = sectionOffset(b, 'nav_envelope', 'position'); const at = text.indexOf(`"byte_offset":${offset}`); b[8 + at + 14] = b[8 + at + 14] === 0x31 ? 0x32 : 0x31; return b; }, /contiguous layout/],
    ['a contract this version does not write', () => sameLength('"sampling support height"', '"sampling support heighT"'), /contract/],
    ['a material statement that is neither a record nor none', () => sameLength('"material":{"state":"none-exists"}', '"material":{"state":"none-exiSts"}'), /neither record nor none-exists/],
  ] as [string, () => Uint8Array, RegExp][])('refuses %s', (_name, make, pattern) => {
    refused(make(), pattern);
  });

  it('refuses an index outside its range', () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'nav_envelope', 'index');
    new DataView(bytes.buffer).setUint32(at, 99_999, true);
    refused(bytes, /indexes outside its range/);
  });

  it('refuses an extent its vertices do not have', () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'nav_envelope', 'position_mm');
    const view = new DataView(bytes.buffer);
    view.setInt32(at, view.getInt32(at, true) - 1, true);
    refused(bytes, /extent its vertices do not have/);
  });

  it('refuses a material citation to a record that is not a material', () => {
    const header = headerText(dressed);
    const records = (JSON.parse(header) as { records: { kind: string }[] }).records;
    const match = /"material":\{"record":(\d+),"state":"record"\}/.exec(header)!;
    const cited = match[1]!;
    // Another record whose index has as many digits, so the header keeps its length.
    const other = records.findIndex((record, index) => String(index).length === cited.length && record.kind !== 'city.surface_material');
    expect(other).toBeGreaterThanOrEqual(0);
    refused(sameLength(match[0], match[0].replace(cited, String(other)), dressed), /cites a record that is not a material/);
  });

  it('refuses a span the container cannot hold as int32 offsets', () => {
    const tessellation = baked.tessellation;
    const [render, nav] = tessellation.projections;
    const far = { ...nav!, vertices: [...nav!.vertices, 3_000_000_000, 0, 0] };
    expect(() => encodeOwd({ ...tessellation, projections: [render!, far] }, {
      tileInputs: baked.tileInputsDigest,
      triangles: baked.triangleDigests,
    })).toThrow(/int32/);
  });
});

describe('verifyOwd', () => {
  it('accepts the fixture and the dressed variant', async () => {
    await expect(verifyOwd(baked.container, nodeSha256)).resolves.toBeDefined();
    await expect(verifyOwd(dressed, nodeSha256)).resolves.toBeDefined();
  });

  it('refuses a float payload the integers do not give', async () => {
    const bytes = copy();
    const at = sectionOffset(bytes, 'nav_envelope', 'position');
    bytes[at + 1] = bytes[at + 1]! ^ 0x01;
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses surface coordinates the records do not give', async () => {
    const bytes = copy(dressed);
    const at = sectionOffset(bytes, 'render_batch', 'surface_mm');
    bytes[at + 4] = bytes[at + 4]! ^ 0x01;
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses a record whose fields no longer match its digest', async () => {
    const bytes = sameLength('"address_number":10', '"address_number":11');
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });

  it('refuses a triangle digest the triangles do not give', async () => {
    const bytes = oneCharacter(/"name":"nav_envelope","origin_mm":\[[^\]]*\],"triangle_count":\d+,"triangle_digest":"([0-9a-f]{64})"/);
    expect(() => decodeOwd(bytes)).not.toThrow();
    await expect(verifyOwd(bytes, nodeSha256)).rejects.toThrow(/not what its own records bake to/);
  });
});

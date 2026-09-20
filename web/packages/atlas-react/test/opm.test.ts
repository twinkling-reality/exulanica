import { describe, expect, it } from 'vitest';
import {
  PACKED_STRIDE_BYTES,
  decodeOpm,
  footprintRadiusOf,
  packedVertexBytes,
  sourcePanelEnvelopeOf,
} from '../src/playcanvas/opm.js';
import type { OpmHeader } from '../src/playcanvas/opm.js';

/**
 * These tests cover the loader only. They deliberately import nothing from `playcanvas`, because
 * the engine touches browser globals at module scope and these run under vitest's node
 * environment; the binding itself is covered by the bake-off page, which is the only place a GPU
 * exists.
 *
 * What is worth asserting here is the CONTIGUITY CONTRACT. PlayCanvas holds one VertexBuffer per
 * Mesh and computes its own tightly packed planar offsets, so the loader can only avoid a
 * per-point CPU pass when the file's sections sit back to back. That is a property of the
 * container, it holds for every count on the bake-off ladder, and a change to `scene-synth` could
 * silently break it into a copy nobody notices.
 *
 * Everything below writes OPM/2. The container's version, the `tags` section, `modelImage` and
 * the `colorAlpha` enum are ADR-0010, and the tests that reach a refusal build a file no
 * conforming writer emits, which is the only way to reach one.
 */

const align = (n: number): number => Math.ceil(n / 16) * 16;

interface BuildOptions {
  readonly count: number;
  /** Extra bytes of padding inserted before every section after the first. */
  readonly gap?: number;
  /** Header fields to override, for the files a writer would never produce. */
  readonly header?: Partial<Record<string, unknown>>;
  /** Extra sections to declare after the registered ones, with their byte lengths. */
  readonly extra?: readonly { readonly name: string; readonly byteLength: number }[];
  /**
   * Declared shape overrides for a registered section, leaving the layout alone.
   *
   * A test that wants a section to MIS-declare itself has to keep the offsets the file actually
   * has, or the range check fires first and the test passes for the wrong reason.
   */
  readonly shapes?: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
}

function buildOpm(
  { count, gap = 0, header: overrides = {}, extra = [], shapes = {} }: BuildOptions,
): ArrayBuffer {
  const sizes = { position: count * 12, color: count * 4, tags: count * 4 };

  const header = (offsets: readonly number[]): OpmHeader =>
    ({
      format: 'exulanica-point-map',
      version: 2,
      pointCount: count,
      rung: 3,
      frame: 'local',
      up: '+Y',
      forward: '-Z',
      units: 'metres',
      metric: true,
      viewpoint: {
        position: [0, 1.55, 0],
        forward: [0, 0, -1],
        up: [0, 1, 0],
        fovYDeg: 55,
        aspect: 4 / 3,
      },
      sourceImage: { width: 400, height: 300 },
      modelImage: { width: 400, height: 300 },
      bounds: { min: [-3, 0, -8], max: [4, 2, -1] },
      colorAlpha: 'confidence',
      segments: [
        { id: 0, name: 'quay', cls: 'ground' },
        { id: 1, name: 'water', cls: 'water' },
      ],
      sections: [
        {
          name: 'position',
          type: 'float32',
          components: 3,
          normalized: false,
          byteOffset: offsets[0]!,
          byteLength: sizes.position,
          ...shapes['position'],
        },
        {
          name: 'color',
          type: 'uint8',
          components: 4,
          normalized: true,
          byteOffset: offsets[1]!,
          byteLength: sizes.color,
          ...shapes['color'],
        },
        {
          name: 'tags',
          type: 'uint16',
          components: 2,
          normalized: false,
          byteOffset: offsets[2]!,
          byteLength: sizes.tags,
          ...shapes['tags'],
        },
        ...extra.map((section, index) => ({
          name: section.name,
          type: 'uint8' as const,
          components: 1,
          normalized: false,
          byteOffset: offsets[3 + index]!,
          byteLength: section.byteLength,
        })),
      ],
      ...overrides,
    }) as unknown as OpmHeader;

  const lengths = [sizes.position, sizes.color, sizes.tags, ...extra.map((s) => s.byteLength)];
  const probe = new TextEncoder().encode(JSON.stringify(header(lengths.map(() => 0))));
  const capacity = align(probe.length + 96);
  const dataStart = 8 + capacity;

  const offsets: number[] = [];
  let cursor = align(dataStart);
  for (const [index, length] of lengths.entries()) {
    cursor += index === 0 ? 0 : gap;
    offsets.push(cursor);
    cursor += length;
  }
  const total = cursor;

  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  const headerBytes = new TextEncoder().encode(JSON.stringify(header(offsets)));
  bytes.set(new TextEncoder().encode('OPM1'), 0);
  view.setUint32(4, headerBytes.length, true);
  bytes.set(headerBytes, 8);
  bytes.fill(0x20, 8 + headerBytes.length, offsets[0]!);

  const [positionAt, colorAt, tagsAt] = offsets as [number, number, number];
  for (let i = 0; i < count; i += 1) {
    view.setFloat32(positionAt + i * 12, i, true);
    view.setFloat32(positionAt + i * 12 + 4, i + 0.5, true);
    view.setFloat32(positionAt + i * 12 + 8, -i, true);
    bytes[colorAt + i * 4] = i & 0xff;
    bytes[colorAt + i * 4 + 3] = 200;
    view.setUint16(tagsAt + i * 4, i % 2, true);
    view.setUint16(tagsAt + i * 4 + 2, i % 2, true);
  }
  return bytes.buffer;
}

describe('the .opm loader', () => {
  it('reads the header and exposes zero-copy views over the same buffer', () => {
    const buffer = buildOpm({ count: 8 });
    const map = decodeOpm(buffer);

    expect(map.header.pointCount).toBe(8);
    expect(map.header.rung).toBe(3);
    expect(map.header.version).toBe(2);
    // The alpha channel says which quantity it holds, and the reader no longer infers it from
    // whether a statistics key happens to be present.
    expect(map.header.colorAlpha).toBe('confidence');

    expect(map.position.buffer).toBe(buffer);
    expect(map.color.buffer).toBe(buffer);
    expect(map.tags.buffer).toBe(buffer);

    expect(map.position[3]).toBeCloseTo(1);
    expect(map.color[3]).toBe(200);
    // Two channels per point: the segment id, then the flags word.
    expect(map.tags[2]).toBe(1);
    expect(map.tags[3]).toBe(1);
    expect(map.tags).toHaveLength(16);
  });

  it('rejects a file that is not an .opm', () => {
    const notOpm = new Uint8Array(64);
    notOpm.set(new TextEncoder().encode('GLTF'), 0);
    expect(() => decodeOpm(notOpm.buffer)).toThrow(/not an \.opm/);
  });

  it('refuses an OPM/1 container by name and says what produces the version it reads', () => {
    // ADR-0010 D9 is refuse and regenerate. There is no converter to name: the container version
    // rides in the depth stage's params, so it is inside the idempotency key, and re-running
    // ingest writes a new artifact rather than rewriting this one. A message that said only
    // "unsupported version" would send a reader looking for a tool that does not exist.
    const one = buildOpm({ count: 4, header: { version: 1 } });
    expect(() => decodeOpm(one)).toThrow(/OPM\/1/);
    expect(() => decodeOpm(one)).toThrow(/depth stage/);
  });

  it('skips a section this client has never heard of rather than refusing the file', () => {
    // The whole of ADR-0010 D2: "a registered optional section is not a version bump" is only
    // true if an older reader keeps reading the sections it knows when a newer writer adds one.
    const map = decodeOpm(buildOpm({ count: 8, extra: [{ name: 'curvature', byteLength: 8 }] }));
    expect(map.header.pointCount).toBe(8);
    expect(map.position[3]).toBeCloseTo(1);
    // The newcomer sits after the registered three, so the fast path is untouched.
    expect(map.planarContiguous).toBe(true);
  });

  it('refuses a section it does know whose shape it does not', () => {
    // The other half of D2. An unknown name is a later writer's section; a known name with a
    // different type is a file that means something else by a word this reader is about to build
    // a typed-array view from.
    // The offsets stay the file's real ones. Only the declared shape is wrong, which is the
    // case a range check would otherwise catch first and for the wrong reason.
    const wrong = buildOpm({ count: 8, shapes: { tags: { components: 1, byteLength: 16 } } });
    expect(() => decodeOpm(wrong)).toThrow(/tags section layout/);
    // The same for a type: a uint16 channel read as uint8 halves every offset past it.
    const retyped = buildOpm({ count: 8, shapes: { tags: { type: 'uint8', byteLength: 32 } } });
    expect(() => decodeOpm(retyped)).toThrow(/tags section layout/);
  });

  it('takes the zero-copy path when the sections are contiguous', () => {
    const map = decodeOpm(buildOpm({ count: 64 }));
    expect(map.planarContiguous).toBe(true);

    const packed = packedVertexBytes(map);
    expect(packed.copied).toBe(false);
    expect(packed.bytes.byteLength).toBe(PACKED_STRIDE_BYTES * 64);
    expect(packed.bytes.buffer).toBe(map.buffer);
  });

  it('packs twenty bytes a point, which is what the engine has to be given', () => {
    // ADR-0010 D3. Eighteen under OPM/1, and the binding was widening the two-byte segment
    // channel to four with a per-point CPU pass because WebGPU rejects an arrayStride of 2.
    expect(PACKED_STRIDE_BYTES).toBe(20);
  });

  it('repacks, and says so, when the sections are not contiguous', () => {
    const map = decodeOpm(buildOpm({ count: 64, gap: 16 }));
    expect(map.planarContiguous).toBe(false);

    const packed = packedVertexBytes(map);
    expect(packed.copied).toBe(true);
    expect(packed.bytes.byteLength).toBe(PACKED_STRIDE_BYTES * 64);
    expect(packed.bytes.buffer).not.toBe(map.buffer);

    // The repack must preserve the planar order the engine expects: position, colour, tags.
    const positions = new Float32Array(packed.bytes.buffer, 0, 64 * 3);
    expect(positions[3]).toBeCloseTo(1);
    expect(packed.bytes[12 * 64 + 3]).toBe(200);
    const tags = new Uint16Array(packed.bytes.buffer, 16 * 64, 64 * 2);
    expect(tags[2]).toBe(1);
    expect(tags[3]).toBe(1);
  });

  it('derives a footprint radius that encloses every corner of the bounds', () => {
    const map = decodeOpm(buildOpm({ count: 4 }));
    // bounds are x -3..4 and z -8..-1, so the furthest ground-plane corner is (4, -8).
    expect(footprintRadiusOf(map.header)).toBeCloseTo(Math.hypot(4, 8));
  });

  it('derives an observed panel envelope from source camera facts, not Atlas placement', () => {
    const envelope = sourcePanelEnvelopeOf(decodeOpm(buildOpm({ count: 4 })).header);
    expect(envelope.nearDepth).toBeCloseTo(1);
    expect(envelope.farDepth).toBeCloseTo(8);
    expect(envelope.farHalfWidth).toBeCloseTo(
      8 * Math.tan((55 * Math.PI) / 360) * (4 / 3),
    );
  });

  it('refuses a structurally valid header whose source aspect contradicts the camera', () => {
    expect(() => decodeOpm(buildOpm({
      count: 4,
      header: { viewpoint: { position: [0, 1.55, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 55, aspect: 2 } },
    }))).toThrow(/aspect/);
  });

  it('refuses a file that does not say what its alpha channel holds', () => {
    expect(() => decodeOpm(buildOpm({ count: 4, header: { colorAlpha: 'alpha' } })))
      .toThrow(/colorAlpha/);
  });

  describe('the model grid against the photograph', () => {
    /**
     * ADR-0010 D6 asks for consistency rather than equality, with a tolerance derived from the
     * model's own rounding rather than assumed. The derivation is an overlap of two rounding
     * windows, and the values below are the same ones `tests/test_reconstruction.py` uses, so the
     * two languages are pinned to the same boundary from either side.
     */
    it.each([
      [400, 300, 400, 300],
      [1500, 1000, 512, 341],
      [1500, 1000, 512, 342],
      [1000, 1000, 400, 400],
      [3000, 2, 512, 1],
    ])('accepts %ix%i unprojected from a %ix%i grid', (sw, sh, mw, mh) => {
      const map = decodeOpm(buildOpm({
        count: 4,
        header: {
          sourceImage: { width: sw, height: sh },
          modelImage: { width: mw, height: mh },
          viewpoint: { position: [0, 1.55, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 55, aspect: sw / sh },
        },
      }));
      expect(map.header.modelImage).toEqual({ width: mw, height: mh });
    });

    it.each([[512, 343], [512, 512], [513, 341]])(
      'refuses a %ix%i grid, whose two dimensions imply different scales',
      (mw, mh) => {
        expect(() => decodeOpm(buildOpm({
          count: 4,
          header: {
            sourceImage: { width: 1500, height: 1000 },
            modelImage: { width: mw, height: mh },
            viewpoint: { position: [0, 1.55, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 55, aspect: 1.5 },
          },
        }))).toThrow(/modelImage/);
      },
    );
  });
});

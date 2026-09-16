import type { PointMap } from '../pointmap.js';
import type { Segment } from '../primitives.js';

export { TAG_ONE_SIDED } from '../pointmap.js';

/**
 * THE INTERCHANGE FORMAT, AND WHY IT IS THIS ONE.
 *
 * `.opm` (Exulanica Point Map): a binary container holding a JSON header followed by planar
 * typed-array sections, the first of them 16-byte aligned. One file, one fetch, zero parsing.
 *
 * The requirement is narrow and it is not "a good point cloud format". It is: BOTH RENDERER
 * BINDINGS IN ADR-0003 MUST LOAD THE SAME BYTES AT THE SAME COST. The bake-off measures render
 * performance. Any format whose decode cost differs between three.js and PlayCanvas puts loader
 * engineering into a number that is supposed to be about rendering, and the ADR would then be
 * decided partly by whose parser is better, which is not the question.
 *
 * What that buys, concretely: `fetch` -> `arrayBuffer()` -> three `subarray` views ->
 * `new THREE.BufferAttribute(view, n)` or `new pc.VertexBuffer(device, format, count, {data:
 * view})`. Neither engine touches a point individually on the CPU.
 *
 * ONLY THE FIRST SECTION IS ALIGNED, AND THAT IS A CORRECTION. This writer used to align every
 * section to 16 bytes, which ADR-0010 supersedes by name: PlayCanvas computes its own tightly
 * packed planar offsets, so a gap anywhere costs a per-point CPU repack, and the gap appeared for
 * every point count that was not a multiple of four. The production validator refused these files
 * outright. Aligning the start and packing the rest behind it keeps every typed-array view legal,
 * because the strides that follow are all multiples of the element sizes behind them.
 *
 * REJECTED, with reasons:
 *
 *   PLY (binary or ASCII). The obvious choice and the wrong one here. Both engines can read it,
 *   but through different loaders with different per-point JavaScript parses, and custom
 *   properties (segment id, confidence) are exactly where those loaders diverge most. It is kept
 *   as an OPTIONAL SIDE OUTPUT for eyeballing in MeshLab or SuperSplat, because being able to
 *   look at the fixture matters and PLY is what the tools read.
 *
 *   SOG (meta.json plus lossless WebP). ADR-0003 fixes SOG as the delivery format and it is the
 *   right choice THERE, but SOG describes GAUSSIAN SPLATS: position, scale, rotation, opacity,
 *   spherical harmonics. This generator produces a POINT MAP, which is rung 3 on the
 *   reconstruction ladder and explicitly not splats (product-specification.md section 5).
 *   Encoding points as degenerate splats would misrepresent the rung and would tilt the bake-off
 *   toward whichever engine has the better splat path, when the point of measuring rung 3 is
 *   that it is the guaranteed floor with no gate that can fail. When experiment X-1 produces a
 *   real splat, the bake-off should load real SOG alongside this.
 *
 *   glTF / GLB with a POINTS primitive. Standard, and genuinely viable. Rejected because the
 *   segment id and confidence become non-standard `_SEGMENT` / `_CONFIDENCE` attributes that
 *   both loaders need custom plumbing for, and because PlayCanvas's glTF loader constructs a
 *   full entity and mesh graph on the way in. More moving parts inside the measurement, no gain.
 *   `.opm` is deliberately GLB-shaped (magic, length-prefixed JSON header, aligned binary
 *   sections) so moving to glTF later is a re-wrapping rather than a rewrite.
 *
 *   A separate `meta.json` sidecar. Rejected for the primary file: a second HTTP request adds
 *   variable latency to load timings. The header IS written out separately as `<name>.meta.json`
 *   for tooling and for humans, but the `.opm` is self-contained and the sidecar is never needed
 *   to read it.
 *
 * COST: 20 bytes per point. 5.0 MB at 250k, 80 MB at 4M. Eighteen under OPM/1, and the two extra
 * bytes are the tags section's second channel: the engine was already padding the old two-byte
 * segment attribute to four on WebGPU, per point, on the CPU. Positions are float32 rather than
 * quantised because a quantisation grid would flatten exactly the depth noise the fixture exists
 * to reproduce. If upload bandwidth ever needs to be measured separately, add a quantised
 * variant as a second section type rather than changing this one.
 */

export const OPM_MAGIC = 'OPM1';
export const OPM_VERSION = 2;
/** The version this one replaces. Refused by name on read; ADR-0010 D9. */
export const SUPERSEDED_OPM_VERSION = 1;
const ALIGNMENT = 16;

export type SectionType = 'float32' | 'uint8' | 'uint16';

const ELEMENT_BYTES: Readonly<Record<SectionType, number>> = Object.freeze({
  float32: 4,
  uint8: 1,
  uint16: 2,
});

export interface OpmSection {
  readonly name: string;
  readonly type: SectionType;
  readonly components: number;
  readonly normalized: boolean;
  readonly byteOffset: number;
  readonly byteLength: number;
}

/**
 * THE CONTAINER, in declaration order, which is also the order the bytes are packed in.
 *
 * ADR-0010 D2 makes the header's section list authoritative: every offset and stride below is
 * computed from this table rather than written out, so adding a section is a change to one place.
 * `tags` is OPM/2's replacement for `segment` and is the only structural change of the version.
 */
const REGISTRY = [
  { name: 'position', type: 'float32', components: 3, normalized: false },
  { name: 'color', type: 'uint8', components: 4, normalized: true },
  { name: 'tags', type: 'uint16', components: 2, normalized: false },
] as const satisfies readonly Omit<OpmSection, 'byteOffset' | 'byteLength'>[];

const strideOf = (section: { type: SectionType; components: number }): number =>
  ELEMENT_BYTES[section.type] * section.components;

/** Bytes per point across the packed sections. */
export const PACKED_STRIDE_BYTES = REGISTRY.reduce((total, s) => total + strideOf(s), 0);

/** What the colour buffer's alpha channel holds, declared rather than inferred. ADR-0010 D5. */
export type OpmColorAlpha = 'support' | 'confidence';

export interface OpmViewpoint {
  readonly position: readonly [number, number, number];
  readonly forward: readonly [number, number, number];
  readonly up: readonly [number, number, number];
  readonly fovYDeg: number;
  readonly aspect: number;
}

export interface OpmHeader {
  readonly format: 'exulanica-point-map';
  readonly version: number;
  readonly generator: string;
  readonly seed: number;
  readonly sceneName: string;
  readonly pointCount: number;
  /** The reconstruction rung this fixture stands in for. A single photo earns rung 3. */
  readonly rung: 3;
  readonly frame: 'local';
  readonly up: '+Y';
  readonly forward: '-Z';
  readonly units: 'metres';
  readonly metric: boolean;
  /** Where the camera stood. Everything not visible from here is honestly absent. */
  readonly viewpoint: OpmViewpoint;
  readonly sourceImage: { readonly width: number; readonly height: number };
  /**
   * The grid the points were unprojected from. Equal to `sourceImage` for this generator, which
   * rasterises at the resolution it reports and downscales nothing; it is stated anyway because
   * ADR-0010 D6 makes it a declared fact rather than one a reader infers from a point count.
   */
  readonly modelImage: { readonly width: number; readonly height: number };
  readonly bounds: {
    readonly min: readonly [number, number, number];
    readonly max: readonly [number, number, number];
  };
  /**
   * Which quantity the colour buffer's alpha channel carries, and never opacity. This generator
   * writes `confidence`, a belief its own honesty model produces; the reconstruction path writes
   * `support`, which is counted coverage. An enum since OPM/2 (ADR-0010 D5), because both used to
   * say `confidence` and the renderer told them apart by whether a statistics key was present.
   */
  readonly colorAlpha: OpmColorAlpha;
  readonly segments: readonly {
    readonly id: number;
    readonly name: string;
    readonly cls: string;
  }[];
  readonly sections: readonly OpmSection[];
  readonly statistics: Readonly<Record<string, number>>;
}

export interface OpmMetadata {
  readonly generator: string;
  readonly seed: number;
  readonly sceneName: string;
  readonly viewpoint: OpmViewpoint;
  readonly sourceImage: { readonly width: number; readonly height: number };
  readonly modelImage: { readonly width: number; readonly height: number };
  readonly colorAlpha: OpmColorAlpha;
  readonly metric: boolean;
  readonly segments: readonly Segment[];
  readonly statistics: Readonly<Record<string, number>>;
}

const align = (n: number): number => Math.ceil(n / ALIGNMENT) * ALIGNMENT;

export function encodeOpm(points: PointMap, meta: OpmMetadata): Uint8Array {
  const lengths = REGISTRY.map((section) => points.count * strideOf(section));

  // Two passes: lay out the sections against a placeholder header, then rewrite the header with
  // the real offsets. The header is padded to a fixed length so the second pass cannot move it.
  const buildHeader = (offsets: readonly number[]): OpmHeader => ({
    format: 'exulanica-point-map',
    version: OPM_VERSION,
    generator: meta.generator,
    seed: meta.seed,
    sceneName: meta.sceneName,
    pointCount: points.count,
    rung: 3,
    frame: 'local',
    up: '+Y',
    forward: '-Z',
    units: 'metres',
    metric: meta.metric,
    viewpoint: meta.viewpoint,
    sourceImage: meta.sourceImage,
    modelImage: meta.modelImage,
    bounds: { min: points.min, max: points.max },
    colorAlpha: meta.colorAlpha,
    segments: meta.segments.map((s) => ({ id: s.id, name: s.name, cls: s.cls })),
    sections: REGISTRY.map((section, index) => ({
      ...section,
      byteOffset: offsets[index]!,
      byteLength: lengths[index]!,
    })),
    statistics: meta.statistics,
  });

  const probe = new TextEncoder().encode(JSON.stringify(buildHeader(lengths.map(() => 0))));
  // Reserve room for the offsets, which are the only thing that grows on the second pass.
  const headerCapacity = align(probe.length + 96);
  const dataStart = align(8 + headerCapacity);

  // The START of the first section is aligned and the rest pack behind it. See the module
  // comment: a per-section alignment is what took this writer off the renderer's zero-copy path
  // for every count that was not a multiple of four.
  const offsets: number[] = [];
  let cursor = dataStart;
  for (const length of lengths) {
    offsets.push(cursor);
    cursor += length;
  }
  for (const [index, section] of REGISTRY.entries()) {
    if (offsets[index]! % ELEMENT_BYTES[section.type] !== 0) {
      throw new Error(
        `the ${section.name} section lands at byte ${offsets[index]!}, which no `
          + `${section.type} view may start at; the section order or a stride is wrong`,
      );
    }
  }

  const headerBytes = new TextEncoder().encode(JSON.stringify(buildHeader(offsets)));
  if (headerBytes.length > headerCapacity) {
    throw new Error('opm header exceeded its reserved capacity');
  }

  const out = new Uint8Array(cursor);
  const view = new DataView(out.buffer);

  out.set(new TextEncoder().encode(OPM_MAGIC), 0);
  view.setUint32(4, headerBytes.length, true);
  out.set(headerBytes, 8);
  // Pad the header region with spaces so the JSON stays readable in a hex dump.
  out.fill(0x20, 8 + headerBytes.length, dataStart);

  for (const [index, channel] of [points.position, points.color, points.tags].entries()) {
    out.set(
      new Uint8Array(channel.buffer, channel.byteOffset, channel.byteLength),
      offsets[index]!,
    );
  }

  return out;
}

export interface DecodedOpm {
  readonly header: OpmHeader;
  readonly position: Float32Array;
  readonly color: Uint8Array;
  readonly tags: Uint16Array;
}

/**
 * Reference decoder. Both renderer bindings should read the file this way: one subarray view per
 * section over one ArrayBuffer, with the offsets and strides taken from the header.
 *
 * Every view below is built from the section list rather than from a constant, which is ADR-0010
 * D2. It refuses OPM/1 by name, per D9: there is no upgrade on read and no converter, because the
 * container version rides in the depth stage's params and re-running ingest is what produces the
 * new one. For this generator's own fixtures the equivalent is `pnpm synth`.
 */
export function decodeOpm(buffer: ArrayBuffer): DecodedOpm {
  const bytes = new Uint8Array(buffer);
  const magic = new TextDecoder().decode(bytes.subarray(0, 4));
  if (magic !== OPM_MAGIC) throw new Error(`not an .opm file: magic was ${JSON.stringify(magic)}`);

  const headerLength = new DataView(buffer).getUint32(4, true);
  const header = JSON.parse(
    new TextDecoder().decode(bytes.subarray(8, 8 + headerLength)),
  ) as OpmHeader;
  if (header.version === SUPERSEDED_OPM_VERSION) {
    throw new Error(
      `this is an OPM/${SUPERSEDED_OPM_VERSION} container and this build reads `
        + `OPM/${OPM_VERSION}. There is no upgrade on read: regenerate the fixture with `
        + '`pnpm synth`, or re-run the depth stage for a reconstruction',
    );
  }
  if (header.version !== OPM_VERSION) {
    throw new Error(`unsupported .opm version ${header.version}`);
  }

  const find = (name: string): OpmSection => {
    const s = header.sections.find((x) => x.name === name);
    if (s === undefined) throw new Error(`.opm is missing the ${name} section`);
    return s;
  };

  const pos = find('position');
  const col = find('color');
  const tags = find('tags');

  return {
    header,
    position: new Float32Array(buffer, pos.byteOffset, pos.byteLength / ELEMENT_BYTES.float32),
    color: new Uint8Array(buffer, col.byteOffset, col.byteLength),
    tags: new Uint16Array(buffer, tags.byteOffset, tags.byteLength / ELEMENT_BYTES.uint16),
  };
}

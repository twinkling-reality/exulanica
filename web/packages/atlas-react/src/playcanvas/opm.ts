/**
 * Reading the `.opm` container that `@exulanica/scene-synth` and `exulanica.reconstruction` write.
 *
 * The boundary contract forbids this package from importing scene-synth, so the container is
 * re-described here from its documented layout rather than shared as a type. That duplication is
 * deliberate and it is the point: the bake-off has to prove that a renderer binding can load the
 * bytes with no build-time coupling to the tool that produced them.
 *
 * THE ONE REQUIREMENT: no per-point JavaScript. Parsing cost must not land inside a number that
 * is supposed to be about rendering. Everything below is a header parse plus one typed-array
 * view per section over the same ArrayBuffer.
 *
 * **This reads OPM/2 and refuses OPM/1 by name.** ADR-0010 D9 is refuse and regenerate: there is
 * no upgrade on read, and this reader is the one the app's loader hands bytes to, so the message
 * has to say what produces OPM/2 rather than only that OPM/1 is unsupported.
 *
 * **The section list is authoritative, and that is the whole of ADR-0010 D2.** Every offset and
 * every stride below comes from the header. Under OPM/1 three sections were hardcoded here and
 * the packed stride was the literal 18 in the binding, so the header's own generic section list
 * was a fiction; the registry is what makes "a registered optional section is not a version
 * bump" true, because a reader that has never heard of a section still reads the ones it knows.
 */

/** Every section type the container defines, and the bytes one element of each takes. */
const ELEMENT_BYTES = { float32: 4, uint8: 1, uint16: 2 } as const;

export type OpmSectionType = keyof typeof ELEMENT_BYTES;

export interface OpmSection {
  readonly name: string;
  readonly type: OpmSectionType;
  readonly components: number;
  readonly normalized: boolean;
  readonly byteOffset: number;
  readonly byteLength: number;
}

/**
 * THE SECTIONS THIS BUILD KNOWS, in the order their bytes appear.
 *
 * `tags` is OPM/2's replacement for OPM/1's `segment` and is the container's only structural
 * change. Two uint16 channels: channel 0 is the segment id, unchanged in meaning, and channel 1
 * is a flags word. Four bytes rather than two because WebGPU rejects a vertex stream whose
 * `arrayStride` is not a multiple of 4, outright and silently in a release engine build, so the
 * binding was widening the channel with a per-point CPU pass over every point in the corpus.
 */
const REGISTRY = [
  { name: 'position', type: 'float32', components: 3, normalized: false },
  { name: 'color', type: 'uint8', components: 4, normalized: true },
  { name: 'tags', type: 'uint16', components: 2, normalized: false },
] as const satisfies readonly {
  readonly name: string;
  readonly type: OpmSectionType;
  readonly components: number;
  readonly normalized: boolean;
}[];

const strideOf = (section: { type: OpmSectionType; components: number }): number =>
  ELEMENT_BYTES[section.type] * section.components;

/** Bytes per point across the sections the engine uploads. 20 under OPM/2, 18 under OPM/1. */
export const PACKED_STRIDE_BYTES = REGISTRY.reduce((total, s) => total + strideOf(s), 0);

/**
 * THE LARGEST SEGMENT ID A FILE MAY DECLARE IS NOT CHECKED HERE, AND IS NOT A HEADER FIELD.
 *
 * ADR-0010 D3 bounds it by "what the renderer can actually draw, not the width of the field":
 * `semantics.ts` owns `MAX_SEGMENTS`, the binding raises for a larger id and the shaders index a
 * fixed array. This module is not where that is enforced, for the same reason it never checked
 * segment ids against the declared list: both are per-point questions and the one requirement of
 * this decoder is no per-point JavaScript. The production validator in
 * `exulanica/reconstruction/validation.py` walks every point already and enforces both, and
 * `tests/test_reconstruction.py` reads `MAX_SEGMENTS` out of this package's own source to pin the
 * two languages to one number. A re-export of it from here would also make this module depend on
 * `semantics.ts`, which imports this one.
 */

/** Bit 0 of a point's flags channel: a neighbour of this point went to the silhouette drop. */
export const TAG_ONE_SIDED = 0x0001;

export interface OpmSegment {
  readonly id: number;
  readonly name: string;
  /** ground / water / structure / object / person / vegetation. Drives semantic appearance. */
  readonly cls: string;
}

/**
 * What the colour buffer's alpha channel holds, declared rather than inferred (ADR-0010 D5).
 *
 * `support` is coverage: how much surface one sample was asked to stand for, counted. It is what
 * `exulanica.reconstruction` writes. `confidence` is belief, and it is what `scene-synth` writes.
 * Under OPM/1 both said `confidence` and one of them had stopped meaning it, and this reader
 * told them apart by whether a statistics key was present, which is a format flag nobody
 * declared as one.
 */
export type OpmColorAlpha = 'support' | 'confidence';

export interface OpmHeader {
  readonly format: 'exulanica-point-map';
  readonly version: number;
  readonly pointCount: number;
  readonly rung: 3;
  readonly frame: 'local';
  readonly up: '+Y';
  readonly forward: '-Z';
  readonly units: 'metres';
  readonly metric: boolean;
  readonly viewpoint: {
    readonly position: readonly [number, number, number];
    readonly forward: readonly [number, number, number];
    readonly up: readonly [number, number, number];
    readonly fovYDeg: number;
    readonly aspect: number;
  };
  /** The photograph. `viewpoint.aspect` describes this camera and nothing else. */
  readonly sourceImage: { readonly width: number; readonly height: number };
  /**
   * The grid the points were unprojected from, which is NOT the photograph (ADR-0010 D6).
   *
   * A depth model works at a bounded resolution and rounds each dimension independently, so a
   * 1500x1000 photograph arrives as 512x341 and the two aspects differ in the third decimal.
   * This is the lattice a load-time tangent frame is estimated on, and under OPM/1 it had to be
   * guessed at from a point count.
   */
  readonly modelImage: { readonly width: number; readonly height: number };
  readonly bounds: {
    readonly min: readonly [number, number, number];
    readonly max: readonly [number, number, number];
  };
  readonly colorAlpha: OpmColorAlpha;
  readonly segments: readonly OpmSegment[];
  readonly sections: readonly OpmSection[];
  /**
   * What the producer measured about the map, keyed by name. Optional, because the format has
   * always allowed a producer to report nothing, and a reader must not require a number that a
   * writer never claimed to have measured.
   *
   * **No longer a format flag.** `medianSampleSpacingM` is the denominator a support ratio was
   * formed against and is worth reading back; what it is not any more is how the binding decides
   * what the alpha channel means. `colorAlpha` says that, which is ADR-0010 D5.
   */
  readonly statistics?: Readonly<Record<string, number>>;
}

export interface PointMap {
  readonly header: OpmHeader;
  /** The whole file. Kept so a VertexBuffer can be built over it without copying. */
  readonly buffer: ArrayBuffer;
  readonly position: Float32Array;
  readonly color: Uint8Array;
  /** Two uint16 per point: segment id then flags. See `REGISTRY` and `TAG_ONE_SIDED`. */
  readonly tags: Uint16Array;

  /**
   * True when the registered sections sit back to back with no inter-section padding, in the
   * order the registry declares.
   *
   * This matters because PlayCanvas holds exactly ONE VertexBuffer per Mesh and computes its own
   * offsets for a non-interleaved format (tightly packed, in declaration order). It cannot be
   * told to read three attributes from three unrelated offsets. When this is true the binding can
   * hand the engine a zero-copy view of the file; when it is false it must repack, which is a
   * per-point CPU pass and is reported rather than hidden.
   */
  readonly planarContiguous: boolean;
  /** Byte offset of the first section, which is the start of the packed region when contiguous. */
  readonly packedByteOffset: number;
  readonly packedByteLength: number;
}

const MAGIC = 'OPM1';

/** The version this reader speaks, and the one it refuses by name. */
const VERSION = 2;
const SUPERSEDED_VERSION = 1;

function finiteVector(value: unknown, name: string): asserts value is readonly [number, number, number] {
  if (!Array.isArray(value) || value.length !== 3 || value.some((x) => typeof x !== 'number' || !Number.isFinite(x))) {
    throw new Error(`.opm ${name} must be three finite numbers`);
  }
}

function positiveInteger(value: unknown, name: string): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    throw new Error(`.opm ${name} must be a positive integer`);
  }
}

/**
 * Could this model grid have come from this photograph by one uniform resize?
 *
 * ADR-0010 D6 requires the two to be checked "for consistency rather than for equality", with a
 * tolerance "derived from how the model rounds both dimensions independently rather than assumed
 * to be one row". This is that derivation and it carries no tolerance constant: a model scales by
 * one factor and rounds each dimension on its own, so a declared grid is reachable exactly when
 * some real scale could have produced both numbers, which is whether two closed intervals
 * overlap. The scale itself is not in the file, which is why a rule phrased as "within one row of
 * the scaled value" could not be evaluated at all.
 *
 * The same arithmetic, in the same order, as `_model_grid_is_reachable` in
 * `exulanica/reconstruction/validation.py`. Neither language can import the other and both must
 * agree on the boundary, so the operations are written to match rather than to read well.
 */
function modelGridIsReachable(
  source: { readonly width: number; readonly height: number },
  model: { readonly width: number; readonly height: number },
): boolean {
  // A dimension of 1 is the resize helper's clamp rather than a rounding, so its lower bound
  // opens: a photograph two pixels tall is thin, not malformed.
  const window = (declared: number, original: number): readonly [number, number] =>
    declared <= 1 ? [0, (declared + 0.5) / original] : [(declared - 0.5) / original, (declared + 0.5) / original];
  const [lowW, highW] = window(model.width, source.width);
  const [lowH, highH] = window(model.height, source.height);
  return Math.max(lowW, lowH) <= Math.min(highW, highH);
}

function validateHeader(header: OpmHeader): void {
  if (header.version === SUPERSEDED_VERSION) {
    // By name, and naming the path rather than the problem. There is no converter to point at:
    // the container version rides in the depth stage's params, so it is inside the idempotency
    // key, so re-running ingest writes a new artifact rather than rewriting this one.
    throw new Error(
      `this is an OPM/${SUPERSEDED_VERSION} container and this client reads OPM/${VERSION}. `
        + 'There is no upgrade on read: re-run the depth stage over the source photograph, which '
        + 'regenerates the point map under a new idempotency key',
    );
  }
  if (header.version !== VERSION) throw new Error(`unsupported .opm version: ${String(header.version)}`);
  if (header.rung !== 3) throw new Error('.opm point maps must declare rung 3');
  if (header.frame !== 'local' || header.up !== '+Y' || header.forward !== '-Z' || header.units !== 'metres') {
    throw new Error('.opm has an unsupported local-frame convention');
  }
  if (typeof header.metric !== 'boolean') throw new Error('.opm metric must be an explicit boolean');
  if (!Number.isSafeInteger(header.pointCount) || header.pointCount < 0) {
    throw new Error('.opm pointCount must be a non-negative integer');
  }
  if (header.colorAlpha !== 'support' && header.colorAlpha !== 'confidence') {
    throw new Error(
      `.opm colorAlpha must say what the alpha channel holds, support or confidence, and it said `
        + `${JSON.stringify(header.colorAlpha)}`,
    );
  }
  finiteVector(header.viewpoint?.position, 'viewpoint.position');
  finiteVector(header.viewpoint?.forward, 'viewpoint.forward');
  finiteVector(header.viewpoint?.up, 'viewpoint.up');
  if (header.viewpoint.forward.some((x, i) => x !== [0, 0, -1][i]) ||
      header.viewpoint.up.some((x, i) => x !== [0, 1, 0][i])) {
    throw new Error('.opm source-camera axes do not match the renderer frame');
  }
  if (!Number.isFinite(header.viewpoint.fovYDeg) || header.viewpoint.fovYDeg < 1 || header.viewpoint.fovYDeg >= 179) {
    throw new Error('.opm viewpoint field of view is outside the camera range');
  }
  positiveInteger(header.sourceImage?.width, 'sourceImage.width');
  positiveInteger(header.sourceImage?.height, 'sourceImage.height');
  positiveInteger(header.modelImage?.width, 'modelImage.width');
  positiveInteger(header.modelImage?.height, 'modelImage.height');
  if (!modelGridIsReachable(header.sourceImage, header.modelImage)) {
    throw new Error(
      `.opm modelImage ${header.modelImage.width}x${header.modelImage.height} cannot be a `
        + `uniform resize of sourceImage ${header.sourceImage.width}x${header.sourceImage.height}`,
    );
  }
  const expectedAspect = header.sourceImage.width / header.sourceImage.height;
  if (!Number.isFinite(header.viewpoint.aspect) || Math.abs(header.viewpoint.aspect - expectedAspect) > expectedAspect * 1e-6) {
    throw new Error('.opm viewpoint aspect does not match its source image');
  }
  finiteVector(header.bounds?.min, 'bounds.min');
  finiteVector(header.bounds?.max, 'bounds.max');
  if (header.bounds.min.some((x, i) => x > header.bounds.max[i]!)) {
    throw new Error('.opm bounds are inverted');
  }
}

/**
 * Every registered section's declared range, checked against the registry and not against a copy.
 *
 * **A section this client has never heard of is skipped rather than refused**, which is what makes
 * "a registered optional section is not a version bump" true: an older build has to keep reading
 * the sections it knows when a newer writer adds one. A known name with an unknown shape is a
 * different thing entirely, because a typed-array view is about to be built from it, and that is
 * refused.
 */
function registered(header: OpmHeader, headerLength: number, byteLength: number): OpmSection[] {
  if (!Array.isArray(header.sections)) throw new Error('.opm sections must be an array');
  const found = new Map<string, OpmSection>();
  for (const section of header.sections) {
    const name = section?.name;
    if (typeof name !== 'string' || name.length === 0) throw new Error('.opm sections must be named');
    if (found.has(name)) throw new Error(`.opm declares the ${name} section twice`);
    if (!Number.isSafeInteger(section.byteOffset) || !Number.isSafeInteger(section.byteLength) ||
        section.byteOffset < 8 + headerLength || section.byteLength < 0 ||
        section.byteOffset + section.byteLength > byteLength) {
      throw new Error(`.opm ${name} section range is invalid`);
    }
    found.set(name, section);
  }
  return REGISTRY.map((expected) => {
    const section = found.get(expected.name);
    if (section === undefined) throw new Error(`.opm is missing its "${expected.name}" section`);
    if (section.type !== expected.type || section.components !== expected.components ||
        section.normalized !== expected.normalized ||
        section.byteLength !== header.pointCount * strideOf(expected)) {
      throw new Error(`.opm ${expected.name} section layout or range is invalid`);
    }
    if (section.byteOffset % ELEMENT_BYTES[expected.type] !== 0) {
      throw new Error(`.opm ${expected.name} section is not ${expected.type} aligned`);
    }
    return section;
  });
}

export function decodeOpm(buffer: ArrayBuffer): PointMap {
  if (buffer.byteLength < 8) throw new Error('not an .opm file: container is shorter than its prefix');
  const magic = new TextDecoder().decode(new Uint8Array(buffer, 0, 4));
  if (magic !== MAGIC) throw new Error(`not an .opm file: magic was "${magic}"`);

  const headerLength = new DataView(buffer).getUint32(4, true);
  if (headerLength === 0 || headerLength > 1_048_576 || 8 + headerLength > buffer.byteLength) {
    throw new Error('.opm header length is outside the container');
  }
  const header = JSON.parse(
    new TextDecoder().decode(new Uint8Array(buffer, 8, headerLength)),
  ) as OpmHeader;

  if (header.format !== 'exulanica-point-map') {
    throw new Error(`unexpected .opm format field: ${String(header.format)}`);
  }
  validateHeader(header);

  const sections = registered(header, headerLength, buffer.byteLength);
  const [pos, col, tags] = sections as [OpmSection, OpmSection, OpmSection];
  const n = header.pointCount;

  // The engine's packed planar layout, for comparison against the file's actual offsets. Both
  // sides of the comparison come from the registry, so a section added to it moves the fast path
  // rather than silently falling off it.
  let packed = pos.byteOffset;
  const planarContiguous = sections.every((section) => {
    const contiguous = section.byteOffset === packed;
    packed += section.byteLength;
    return contiguous;
  });

  return {
    header,
    buffer,
    position: new Float32Array(buffer, pos.byteOffset, n * 3),
    color: new Uint8Array(buffer, col.byteOffset, n * 4),
    tags: new Uint16Array(buffer, tags.byteOffset, n * 2),
    planarContiguous,
    packedByteOffset: pos.byteOffset,
    packedByteLength: PACKED_STRIDE_BYTES * n,
  };
}

export interface SourcePanelEnvelope {
  readonly nearDepth: number;
  readonly farDepth: number;
  readonly nearHalfWidth: number;
  readonly nearHalfHeight: number;
  readonly farHalfWidth: number;
  readonly farHalfHeight: number;
}

/**
 * The exact source-camera frustum occupied by an OPM's declared depth range.
 *
 * This is an observed source-panel envelope, not a navigation envelope and not Atlas placement.
 * A renderer may use it to size the panel and initial view; it may not infer traversable space.
 */
export function sourcePanelEnvelopeOf(header: OpmHeader): SourcePanelEnvelope {
  const cameraZ = header.viewpoint.position[2];
  const nearDepth = Math.max(0, cameraZ - header.bounds.max[2]);
  const farDepth = Math.max(nearDepth, cameraZ - header.bounds.min[2]);
  const tangent = Math.tan((header.viewpoint.fovYDeg * Math.PI) / 360);
  return Object.freeze({
    nearDepth,
    farDepth,
    nearHalfWidth: nearDepth * tangent * header.viewpoint.aspect,
    nearHalfHeight: nearDepth * tangent,
    farHalfWidth: farDepth * tangent * header.viewpoint.aspect,
    farHalfHeight: farDepth * tangent,
  });
}

/**
 * A zero-copy byte view of the packed planar region, or a repacked copy when the file's sections
 * are not contiguous.
 *
 * Returns the view and whether a copy happened, because "did the loader touch every point" is a
 * fact the bake-off has to report rather than assume. **The repack is a section-at-a-time `set`
 * driven by the registry**, so it stays free of per-point JavaScript and gains a section without
 * gaining a loop: OPM/1's version wrote three offsets out by hand as multiples of the point
 * count, which is the same literal stride the container has now made a header field.
 */
export function packedVertexBytes(map: PointMap): { bytes: Uint8Array; copied: boolean } {
  if (map.planarContiguous) {
    return {
      bytes: new Uint8Array(map.buffer, map.packedByteOffset, map.packedByteLength),
      copied: false,
    };
  }
  const out = new Uint8Array(map.packedByteLength);
  let cursor = 0;
  for (const channel of [map.position, map.color, map.tags]) {
    const bytes = new Uint8Array(channel.buffer, channel.byteOffset, channel.byteLength);
    out.set(bytes, cursor);
    cursor += bytes.byteLength;
  }
  return { bytes: out, copied: true };
}

/** Radial extent of the point map about its local origin, on the ground plane. */
export function footprintRadiusOf(header: OpmHeader): number {
  const { min, max } = header.bounds;
  return Math.max(
    Math.hypot(min[0], min[2]),
    Math.hypot(max[0], max[2]),
    Math.hypot(min[0], max[2]),
    Math.hypot(max[0], min[2]),
  );
}

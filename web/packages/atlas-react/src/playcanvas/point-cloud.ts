import * as pc from 'playcanvas';
import { DISSOLVE_BAND_FRACTION } from '@exulanica/atlas-core';
import {
  BLUE_HOUR_THEME,
  pointProvenancePalette,
  unitRgb,
  type PresentationTheme,
} from '@exulanica/presentation';
import { depthSurfaceIndices } from './depth-surface.js';
import type { PointMap } from './opm.js';
import { footprintRadiusOf, packedVertexBytes } from './opm.js';
import type { SegmentSemantics } from './semantics.js';
import { MAX_SEGMENTS, packSemantics } from './semantics.js';
import {
  POINT_FRAGMENT_GLSL,
  POINT_FRAGMENT_WGSL,
  POINT_VERTEX_GLSL,
  POINT_VERTEX_WGSL,
} from './point-shader.js';

/**
 * One island's 2.5D shell as a PlayCanvas mesh.
 *
 * ENGINE CONSTRAINT WORTH RECORDING. A PlayCanvas `Mesh` owns exactly one `VertexBuffer`. There is
 * no equivalent of three.js's independent `BufferAttribute` per channel, and the only second
 * stream a mesh can carry is the hardware-instancing one. So a planar (structure-of-arrays) point
 * map has to arrive as a single contiguous run of position, then colour, then segment, in that
 * order and with no padding between them, or it has to be repacked on the CPU.
 *
 * `.opm` happens to satisfy that for every count in the bake-off ladder, so the fast path is a
 * zero-copy `Uint8Array` view of the fetched file. `packedVertexBytes` reports when it is not
 * satisfied and a copy was made, because a per-point CPU pass inside a render benchmark is
 * exactly the kind of thing that should never be silent.
 *
 * **THE WEBGPU REPACK IS GONE, AND THE CONTAINER IS WHY.** This binding used to widen the
 * segment channel from one uint16 to two on the CPU, for every point of every cloud, on WebGPU
 * only: a planar uint16 channel is a vertex stream with `arrayStride` 2, WebGL2 accepts it,
 * PlayCanvas's debug build only warns, and WebGPU rejects the pipeline outright and silently in
 * a release build. The note left here said "the right long-term fix is for the container to
 * store `segment` as 4 bytes". ADR-0010 D3 did that. Both graphics paths now upload the same
 * zero-copy view of the file, and the two shader sources read the same two channels.
 */

export interface PointCloudOptions {
  readonly device: pc.GraphicsDevice;
  readonly map: PointMap;
  readonly semantics: readonly SegmentSemantics[];
  /** Screen-space size gain. Multiplied by the projection scale and divided by view distance. */
  readonly sizeGain?: number;
  readonly maxSizePx?: number;
  /** Alpha blending instead of the alpha-tested opaque path. Order-dependent; off by default. */
  readonly blend?: boolean;
  readonly theme?: PresentationTheme;
  /**
   * Draw a single photograph's map as a surface between neighbouring grid samples rather than as
   * points (see `depth-surface.ts`). Honoured on WebGL2 for a map that is a grid; anything else
   * keeps drawing points, and `surface` on the result says which happened.
   */
  readonly surface?: boolean;
}

export interface PointCloud {
  readonly mesh: pc.Mesh;
  readonly material: pc.ShaderMaterial;
  readonly vertexBuffer: pc.VertexBuffer;
  readonly pointCount: number;
  readonly footprintRadiusLocal: number;
  /** True when the loader had to repack the file. Reported, never hidden. */
  readonly repacked: boolean;
  readonly vertexBytes: number;
  readonly defaultSizeGain: number;
  readonly defaultMaxSizePx: number;
  /** True when this map is drawn as a surface, false when as points. Reported, never assumed. */
  readonly surface: boolean;
  /** The seam triangles of a surface, drawn with the same material; null for points. */
  readonly seamMesh: pc.Mesh | null;
  setTheme(theme: PresentationTheme): void;
  /** Compare evidence without the authored fog or display gain masking reconstruction defects. */
  setInspection(active: boolean): void;
  /**
   * Draw this map as one photograph's own view: it thins towards the edges of the photograph's
   * frame and as the visitor's line of sight departs from the camera's. For maps in an unmeasured
   * arrangement only; see the uniform contract in `point-shader.ts`. Returns the camera's local
   * position, which `setCaptureWorld` must then be given in world space every frame.
   */
  enableSingleView(): readonly [number, number, number];
  /** The photograph's camera in world space. Ignored until `enableSingleView` has run. */
  setCaptureWorld(x: number, y: number, z: number): void;
  destroy(): void;
}

/**
 * How a single photograph's view dissolves. The margin is the fraction of the frame, measured in
 * from its edge, over which points thin out; the angles are between the camera's line of sight to
 * a point and the visitor's, where thinning starts and where nothing is left. A visitor standing
 * where the photograph was taken sees all of it; one who steps a metre or two aside sees the
 * people in front begin to dissolve before the distant ridge does, because the angle to a near
 * point grows faster; one who walks round behind sees nothing, which is what was photographed.
 */
export const SINGLE_VIEW_EDGE_MARGIN = 0.15;
export const SINGLE_VIEW_FADE_START_DEG = 18;
export const SINGLE_VIEW_FADE_END_DEG = 42;
/** World distance from the photograph's camera over which the whole photograph thins out. */
export const SINGLE_VIEW_STANDPOINT_START = 3;
export const SINGLE_VIEW_STANDPOINT_END = 9;
/** Angles over which a seam of a surface dissolves; see depth-surface.ts. Far tighter than a surface. */
export const SEAM_FADE_START_DEG = 3;
export const SEAM_FADE_END_DEG = 9;
/** The tags flag bit that marks a copied seam vertex. Bit 0 is the file's own one-sided flag. */
const SEAM_FLAG = 2;

/**
 * Default sprite sizing.
 *
 * `sizeGain` is a world-space length: the shader turns it into pixels with the projection scale
 * and the view distance, so a point keeps a constant world footprint rather than a constant screen
 * one. 0.05 m is roughly the sample spacing of the 1M fixture at mid depth, which is the value
 * that makes the shell read as a surface instead of as noise without inventing coverage the
 * capture never had.
 */
const DEFAULT_SIZE_GAIN = 0.05;
const DEFAULT_MAX_SIZE_PX = 10;

/**
 * How far a thinly sampled sprite may be widened, as the smallest support it is divided by.
 *
 * 0.12 caps the growth at a little over eight times. There has to be a cap: support approaches
 * zero for a sample standing alone, and an uncapped divisor turns one point at the edge of the
 * sky into a sprite that fills the screen. Eight is measured rather than picked, on the courtyard
 * at 512 px, it is the ratio between the median sample spacing and the coarsest sampling that
 * still belongs to a readable surface rather than to the far haze.
 */
const SUPPORT_FLOOR = 0.12;

const ATTRIBUTES = {
  aPosition: pc.SEMANTIC_POSITION,
  aColor: pc.SEMANTIC_COLOR,
  aTags: pc.SEMANTIC_ATTR8,
} as const;

/** `ShaderDesc` is documented but not exported from the engine's type surface, so it is restated. */
interface ShaderDesc {
  uniqueName: string;
  attributes?: Record<string, string>;
  vertexGLSL?: string;
  fragmentGLSL?: string;
  vertexWGSL?: string;
  fragmentWGSL?: string;
}

function buildShaderDesc(blend: boolean, surface = false): ShaderDesc {
  const defines = `${blend ? '#define POINT_BLEND\n' : ''}${surface ? '#define SURFACE\n' : ''}`;
  return {
    uniqueName: `exulanica-point-map${blend ? '-blend' : ''}${surface ? '-surface' : ''}`,
    attributes: { ...ATTRIBUTES },
    vertexGLSL: `${defines}${POINT_VERTEX_GLSL}`,
    fragmentGLSL: `${defines}${POINT_FRAGMENT_GLSL}`,
    // A surface is only ever built on WebGL2 (see `createPointCloud`), so the WGSL twins stay the
    // point shader: there is no WGSL surface to keep in step, and none that could ship untested.
    vertexWGSL: POINT_VERTEX_WGSL,
    fragmentWGSL: POINT_FRAGMENT_WGSL,
  };
}

export function createPointCloud(options: PointCloudOptions): PointCloud {
  const { device, map, semantics } = options;
  const n = map.header.pointCount;

  // Non-interleaved (planar) format. The third argument is what selects it, and it makes the
  // element offsets a function of the vertex count, which is why the format is built per cloud.
  //
  // The tags stream is two uint16 channels on BOTH graphics paths, which is what the container
  // now stores. `arrayStride` is therefore 4 and WebGPU accepts the pipeline; see the module
  // comment for what this cost before ADR-0010 D3. The engine's own debug assertion about a
  // non-interleaved element size that is not a multiple of four also stops firing, which is the
  // warning that named this defect in the first place.
  const format = new pc.VertexFormat(
    device,
    [
      { semantic: pc.SEMANTIC_POSITION, components: 3, type: pc.TYPE_FLOAT32 },
      { semantic: pc.SEMANTIC_COLOR, components: 4, type: pc.TYPE_UINT8, normalize: true },
      { semantic: pc.SEMANTIC_ATTR8, components: 2, type: pc.TYPE_UINT16, normalize: false },
    ],
    n,
  );

  // THE ENGINE'S LAYOUT AND THE FILE'S HAVE TO BE THE SAME BYTES, and neither is written here.
  //
  // A non-interleaved format makes the element offsets a function of the vertex count: the engine
  // places channel k at the sum of the element sizes before it, times the count, and reports the
  // total as `verticesByteSize`. The file's packed region is the same expression over the .opm
  // section registry. If a section is ever added to one and not the other, every channel after it
  // is read from the wrong place, the cloud renders as noise and nothing reports a fault. ADR-0010
  // D2 made the section list authoritative, so that is now a live possibility rather than a
  // hypothetical, and the two totals are compared once per cloud.
  //
  // `verticesByteSize` and NOT `format.size`. The latter rounds every element up to four bytes,
  // so it was already 20 when the container packed 18: it would have accepted the old layout and
  // is not the quantity that has to agree.
  if (format.verticesByteSize !== map.packedByteLength) {
    throw new RangeError(
      `the vertex format reads ${format.verticesByteSize} bytes and the container packs `
        + `${map.packedByteLength} for ${n} points; a section is in one and not the other`,
    );
  }

  const packed = packedVertexBytes(map);
  const vertexBuffer = new pc.VertexBuffer(device, format, n, {
    usage: pc.BUFFER_STATIC,
    data: packed.bytes as unknown as ArrayBuffer,
  });

  const mesh = new pc.Mesh(device);
  mesh.vertexBuffer = vertexBuffer;
  const triangles = options.surface === true && device.isWebGL2 ? depthSurfaceIndices(map) : null;
  let seamMesh: pc.Mesh | null = null;
  if (triangles === null || triangles.surface.length === 0) {
    mesh.primitive[0] = { type: pc.PRIMITIVE_POINTS, base: 0, count: n, indexed: false, baseVertex: 0 };
  } else {
    mesh.indexBuffer[0] = new pc.IndexBuffer(device, pc.INDEXFORMAT_UINT32, triangles.surface.length,
      pc.BUFFER_STATIC, triangles.surface.buffer as ArrayBuffer);
    mesh.primitive[0] = { type: pc.PRIMITIVE_TRIANGLES, base: 0, count: triangles.surface.length, indexed: true,
      baseVertex: 0 };
    if (triangles.seams.length > 0) seamMesh = buildSeamMesh(device, map, triangles.seams);
  }
  const surface = triangles !== null && triangles.surface.length > 0;

  const { min, max } = map.header.bounds;
  mesh.aabb = new pc.BoundingBox();
  mesh.aabb.setMinMax(new pc.Vec3(min[0], min[1], min[2]), new pc.Vec3(max[0], max[1], max[2]));
  // The seams are copies of samples inside the same bounds. Without a box of its own the engine
  // treats a mesh built from a raw vertex buffer as empty and culls it, which is exactly how the
  // first version of this drew no seams at all.
  if (seamMesh !== null) {
    seamMesh.aabb = new pc.BoundingBox();
    seamMesh.aabb.setMinMax(new pc.Vec3(min[0], min[1], min[2]), new pc.Vec3(max[0], max[1], max[2]));
  }

  const blend = options.blend ?? false;
  const material = new pc.ShaderMaterial(buildShaderDesc(blend, surface) as ConstructorParameters<typeof pc.ShaderMaterial>[0]);
  material.cull = pc.CULLFACE_NONE;
  if (blend) {
    material.blendType = pc.BLEND_NORMAL;
    material.depthWrite = false;
  } else {
    material.blendType = pc.BLEND_NONE;
    material.depthWrite = true;
  }
  material.depthTest = true;

  const footprint = footprintRadiusOf(map.header);

  // ARRAY UNIFORMS TAKE A "[0]" SUFFIX, AND GETTING IT WRONG IS SILENT.
  //
  // PlayCanvas registers an array uniform in the device scope under `name[0]`, matching the name
  // WebGL reflection reports (`UniformFormat` does `this.name = count ? name + '[0]' : name`, and
  // the engine's own forward renderer resolves `pcssDiskSamples[0]`). `setParameter('uSegState',
  // ...)` therefore binds nothing at all, no warning is produced, and the shader reads a table of
  // zeros: every segment comes back unconfirmed=0, presenceOnly=0, confidence floor 0.
  //
  // The visible symptom is the one that matters most in this product. presenceOnly 0 means the
  // person points are NOT discarded, so people get baked into the geometry as reconstructions
  // instead of rendering as time-anchored presence markers. The scene looks fine. It is lying.
  material.setParameter('uSegState[0]', packSemantics(semantics));
  const setTheme = (theme: PresentationTheme): void => {
    material.setParameter('uPalette[0]', pointProvenancePalette(theme));
    material.setParameter('uFogColor', [...unitRgb(theme.ground)]);
    material.update();
  };
  setTheme(options.theme ?? BLUE_HOUR_THEME);
  // Fog starts at the footprint boundary rather than inside it, so the island's own body is not
  // washed out and the ramp lands where the dissolve band already is.
  material.setParameter('uFog', [footprint * 0.9, footprint * 3.2, 1.2, 1]);
  material.setParameter('uExposure', 1.25);
  material.setParameter('uPoint', [options.sizeGain ?? DEFAULT_SIZE_GAIN, options.maxSizePx ?? DEFAULT_MAX_SIZE_PX, 900, 0]);
  // Spacing-aware sizing, but only for a producer that SAYS its alpha is a spacing ratio. Every
  // other file keeps a floor of 1, which makes the shader's divisor exactly 1 and leaves it
  // rendering as it always did. Reinterpreting another writer's channel on a guess is how one
  // producer's confidence silently becomes another's geometry.
  //
  // The condition used to be the presence of a `medianSampleSpacingM` statistic, which ADR-0010
  // calls out by name: "the renderer tells them apart by the presence of a statistics key, which
  // is a format flag that nobody declared as one". D5 made `colorAlpha` an enum, so the file now
  // says which quantity it holds and this reads the declaration. The statistic is still the
  // denominator the ratio was formed against and is still worth reading back; it is no longer
  // what decides the meaning of a channel.
  material.setParameter(
    'uSupportFloor',
    map.header.colorAlpha === 'support' ? SUPPORT_FLOOR : 1,
  );
  material.setParameter('uIsland', [
    1,
    footprint,
    // The dissolve band start, from atlas-core's constant rather than a number typed here. The
    // band is a product decision; the shader is only allowed to render it.
    footprint * (1 - DISSOLVE_BAND_FRACTION),
    1,
  ]);
  // The proof lens, off. Bound here rather than only when the lens is switched on, because an
  // unbound uniform is read as whatever the device scope last held for that name, which on a
  // second cloud would be the previous cloud's tier. The off state has to be a value.
  material.setParameter('uLens', [0, 0, 0, 0]);
  // Single-view fading, off: a value rather than an absence, for the reason `uLens` gives above.
  const capture = new Float32Array(4);
  material.setParameter('uFrame', [0, 0, 0, 0]);
  material.setParameter('uViewpoint', [0, 0, 0, 0]);
  material.setParameter('uCapture', capture);
  material.setParameter('uSeamFade', [
    Math.cos((SEAM_FADE_START_DEG * Math.PI) / 180),
    Math.cos((SEAM_FADE_END_DEG * Math.PI) / 180),
    0,
    0,
  ]);
  material.setParameter('uViewFade', [
    Math.cos((SINGLE_VIEW_FADE_START_DEG * Math.PI) / 180),
    Math.cos((SINGLE_VIEW_FADE_END_DEG * Math.PI) / 180),
    SINGLE_VIEW_STANDPOINT_START,
    SINGLE_VIEW_STANDPOINT_END,
  ]);
  material.update();

  if (semantics.some((s) => s.id >= MAX_SEGMENTS)) {
    throw new RangeError(`segment id exceeds the ${MAX_SEGMENTS}-entry semantic table`);
  }

  return {
    mesh,
    material,
    vertexBuffer,
    pointCount: n,
    footprintRadiusLocal: footprint,
    repacked: packed.copied,
    vertexBytes: vertexBuffer.numBytes,
    defaultSizeGain: options.sizeGain ?? DEFAULT_SIZE_GAIN,
    defaultMaxSizePx: options.maxSizePx ?? DEFAULT_MAX_SIZE_PX,
    surface,
    seamMesh,
    setTheme,
    setInspection(active) {
      material.setParameter('uFog', [footprint * 0.9, footprint * 3.2, 1.2, active ? 0 : 1]);
      material.setParameter('uExposure', active ? 1 : 1.25);
    },
    enableSingleView() {
      const { position, fovYDeg, aspect } = map.header.viewpoint;
      const tanY = Math.tan((fovYDeg * Math.PI) / 360);
      const framed = Number.isFinite(tanY) && tanY > 0 && Number.isFinite(aspect) && aspect > 0;
      // A frame the header cannot describe keeps its edges rather than guessing at them; the
      // line-of-sight fade needs only the camera position and still applies.
      material.setParameter('uFrame', framed ? [tanY * aspect, tanY, SINGLE_VIEW_EDGE_MARGIN, 1] : [0, 0, 0, 0]);
      material.setParameter('uViewpoint', [position[0], position[1], position[2], 0]);
      capture[3] = 1;
      material.setParameter('uCapture', capture);
      return [position[0], position[1], position[2]];
    },
    setCaptureWorld(x, y, z) {
      if (capture[3] !== 1) return;
      capture[0] = x;
      capture[1] = y;
      capture[2] = z;
      material.setParameter('uCapture', capture);
    },
    destroy(): void {
      mesh.destroy();
      seamMesh?.destroy();
      material.destroy();
    },
  };
}

/**
 * The seam triangles as their own vertices: three copies per triangle of the file's samples, with
 * the seam bit set in each copy's flags. Copies rather than an index list over the file's vertices
 * because the flag is per vertex and a sample on a seam is also a corner of ordinary surface.
 */
function buildSeamMesh(device: pc.GraphicsDevice, map: PointMap, seams: Uint32Array): pc.Mesh {
  const count = seams.length;
  const format = new pc.VertexFormat(
    device,
    [
      { semantic: pc.SEMANTIC_POSITION, components: 3, type: pc.TYPE_FLOAT32 },
      { semantic: pc.SEMANTIC_COLOR, components: 4, type: pc.TYPE_UINT8, normalize: true },
      { semantic: pc.SEMANTIC_ATTR8, components: 2, type: pc.TYPE_UINT16, normalize: false },
    ],
    count,
  );
  const position = new Float32Array(count * 3);
  const color = new Uint8Array(count * 4);
  const tags = new Uint16Array(count * 2);
  for (let k = 0; k < count; k += 1) {
    const i = seams[k]!;
    position.set(map.position.subarray(i * 3, i * 3 + 3), k * 3);
    color.set(map.color.subarray(i * 4, i * 4 + 4), k * 4);
    tags[k * 2] = map.tags[i * 2]!;
    tags[k * 2 + 1] = map.tags[i * 2 + 1]! | SEAM_FLAG;
  }
  const bytes = new Uint8Array(position.byteLength + color.byteLength + tags.byteLength);
  bytes.set(new Uint8Array(position.buffer), 0);
  bytes.set(color, position.byteLength);
  bytes.set(new Uint8Array(tags.buffer), position.byteLength + color.byteLength);
  // The same agreement the file's own buffer is held to above: the engine's planar layout and ours.
  if (format.verticesByteSize !== bytes.byteLength) {
    throw new RangeError(`the seam vertex format reads ${format.verticesByteSize} bytes and ${bytes.byteLength} were packed`);
  }
  const seamMesh = new pc.Mesh(device);
  seamMesh.vertexBuffer = new pc.VertexBuffer(device, format, count, {
    usage: pc.BUFFER_STATIC,
    data: bytes.buffer as ArrayBuffer,
  });
  seamMesh.primitive[0] = { type: pc.PRIMITIVE_TRIANGLES, base: 0, count, indexed: false, baseVertex: 0 };
  return seamMesh;
}

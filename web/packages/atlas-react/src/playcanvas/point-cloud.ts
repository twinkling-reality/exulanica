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
  /** The viewer's image of the photograph, upright, to colour a surface with. Ignored for points. */
  readonly photograph?: ImageBitmap;
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
  /** True when a surface takes its colour from the photograph rather than its own samples. */
  readonly photographed: boolean;
  setTheme(theme: PresentationTheme): void;
  /** Compare evidence without the authored fog or display gain masking reconstruction defects. */
  setInspection(active: boolean): void;
  /**
   * Draw this map as one photograph's own view (see the uniform contract in `point-shader.ts`):
   * soft at its frame's edges, flattened into a print standing `printDepth` in front of its camera
   * as the visitor leaves the camera, and a plain card from behind. For maps in an unmeasured
   * arrangement only. Returns the camera's local position, which the caller turns into
   * `setCaptureWorld` every frame, with `setRelief`.
   */
  enableSingleView(printDepth: number): readonly [number, number, number];
  /** The photograph's camera in world space. Ignored until `enableSingleView` has run. */
  setCaptureWorld(x: number, y: number, z: number): void;
  /** How flat the relief is, 0 to 1, and whether the visitor is behind the print. */
  setRelief(flatten: number, behind: boolean): void;
  destroy(): void;
}

/** The fraction of the frame, measured in from its edge, over which a photograph's points thin out. */
export const SINGLE_VIEW_EDGE_MARGIN = 0.15;
/**
 * The most parallax, in degrees, a photograph's relief may show a visitor. See `reliefFor` in
 * atlas-binding.ts, which flattens the relief just enough to keep within it.
 *
 * Parallax is the whole of what one photograph's depth can get wrong away from its camera: every
 * gap it opens and every edge it stretches is two samples on one camera ray parting by that much.
 * MEASURED 2026-09-11 on the first personal place, as the share of the flat print's own pixels the
 * relief left empty, over three photographs and twelve standpoints each (at the camera, 0.1 to
 * 1 m aside, 2 to 15 m back, halfway in, 30 and 60 degrees round, and behind):
 *
 *   limit   0.5 deg   1 deg   2 deg   4 deg
 *   worst     0.9 %   1.6 %   3.0 %   5.9 %
 *
 * plus 1.1 to 4.3 % at one degree for a visitor who has walked half way in to the print, where the
 * small-angle bound this works in understates the parallax. One degree because the photographs are
 * whole at it and 4 degrees visibly frayed the edges of people's hair; the choice buys depth, and
 * the numbers above are the price in holes.
 */
export const RELIEF_PARALLAX_DEG = 1;

/** A photograph's depths from its own camera, in its local units. */
export interface SingleViewDepths {
  /** Where half the photograph's content is nearer and half further: where its subject stands. */
  readonly median: number;
  readonly nearest: number;
  readonly furthest: number;
}

/**
 * MEASURED 2026-09-11 on the first personal place: medians 5.3, 2.6 and 3.9, nearest 2.4, 2.1 and
 * 2.5, furthest 214, 164 and 201. The median is where the people stand in each photograph.
 */
export function singleViewDepths(map: PointMap): SingleViewDepths {
  const eyeZ = map.header.viewpoint.position[2];
  const depths = new Float32Array(map.header.pointCount);
  for (let i = 0; i < depths.length; i += 1) depths[i] = eyeZ - map.position[i * 3 + 2]!;
  depths.sort();
  const middle = depths.length >> 1;
  const median = depths.length % 2 === 1 ? depths[middle]! : (depths[middle - 1]! + depths[middle]!) / 2;
  if (!(depths.length > 0 && depths[0]! > 0 && median > 0)) return { median: 1, nearest: 1, furthest: 1 };
  return { median, nearest: depths[0]!, furthest: depths[depths.length - 1]! };
}

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

function buildShaderDesc(blend: boolean, surface = false, photographed = false): ShaderDesc {
  const defines = `${blend ? '#define POINT_BLEND\n' : ''}${surface ? '#define SURFACE\n' : ''}`
    + `${photographed ? '#define PHOTOGRAPH\n' : ''}`;
  return {
    uniqueName: `exulanica-point-map${blend ? '-blend' : ''}${surface ? '-surface' : ''}${photographed ? '-photograph' : ''}`,
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
  if (triangles === null || triangles.surface.length === 0) {
    mesh.primitive[0] = { type: pc.PRIMITIVE_POINTS, base: 0, count: n, indexed: false, baseVertex: 0 };
  } else {
    // The seams are drawn with the surface rather than only down the camera's own rays. A seam
    // spans a depth jump, so what it can show wrongly is that jump's parallax, and flattening
    // holds every parallax in this map within `RELIEF_PARALLAX_DEG` from wherever the visitor is.
    const indices = new Uint32Array(triangles.surface.length + triangles.seams.length);
    indices.set(triangles.surface);
    indices.set(triangles.seams, triangles.surface.length);
    mesh.indexBuffer[0] = new pc.IndexBuffer(device, pc.INDEXFORMAT_UINT32, indices.length,
      pc.BUFFER_STATIC, indices.buffer as ArrayBuffer);
    mesh.primitive[0] = { type: pc.PRIMITIVE_TRIANGLES, base: 0, count: indices.length, indexed: true,
      baseVertex: 0 };
  }
  const surface = triangles !== null && triangles.surface.length > 0;

  const { min, max } = map.header.bounds;
  mesh.aabb = new pc.BoundingBox();
  mesh.aabb.setMinMax(new pc.Vec3(min[0], min[1], min[2]), new pc.Vec3(max[0], max[1], max[2]));

  const blend = options.blend ?? false;
  const photographed = surface && options.photograph !== undefined;
  const material = new pc.ShaderMaterial(
    buildShaderDesc(blend, surface, photographed) as ConstructorParameters<typeof pc.ShaderMaterial>[0]);
  let photographTexture: pc.Texture | null = null;
  if (photographed) {
    const image = options.photograph!;
    photographTexture = new pc.Texture(device, {
      name: 'photograph',
      width: image.width,
      height: image.height,
      format: pc.PIXELFORMAT_RGBA8,
      mipmaps: true,
      minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
      magFilter: pc.FILTER_LINEAR,
      addressU: pc.ADDRESS_CLAMP_TO_EDGE,
      addressV: pc.ADDRESS_CLAMP_TO_EDGE,
      flipY: false,
    });
    // The engine uploads an ImageBitmap directly (playcanvas 2.21.4's texture upload tests
    // `instanceof ImageBitmap`); only its declared parameter type omits it.
    photographTexture.setSource(image as unknown as HTMLImageElement);
    material.setParameter('uPhotograph', photographTexture);
  }
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
  const relief = new Float32Array(4);
  material.setParameter('uFrame', [0, 0, 0, 0]);
  material.setParameter('uViewpoint', [0, 0, 0, 0]);
  material.setParameter('uCapture', capture);
  material.setParameter('uRelief', relief);
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
    photographed,
    setTheme,
    setInspection(active) {
      material.setParameter('uFog', [footprint * 0.9, footprint * 3.2, 1.2, active ? 0 : 1]);
      material.setParameter('uExposure', active ? 1 : 1.25);
    },
    enableSingleView(printDepth) {
      const { position, fovYDeg, aspect } = map.header.viewpoint;
      const tanY = Math.tan((fovYDeg * Math.PI) / 360);
      const framed = Number.isFinite(tanY) && tanY > 0 && Number.isFinite(aspect) && aspect > 0;
      // A frame the header cannot describe keeps its edges rather than guessing at them; the
      // flattening needs only the camera position and still applies.
      material.setParameter('uFrame', framed ? [tanY * aspect, tanY, SINGLE_VIEW_EDGE_MARGIN, 1] : [0, 0, 0, 0]);
      material.setParameter('uViewpoint', [position[0], position[1], position[2], 0]);
      capture[3] = 1;
      material.setParameter('uCapture', capture);
      relief[0] = printDepth > 0 ? printDepth : 1;
      material.setParameter('uRelief', relief);
      return [position[0], position[1], position[2]];
    },
    setCaptureWorld(x, y, z) {
      if (capture[3] !== 1) return;
      capture[0] = x;
      capture[1] = y;
      capture[2] = z;
      material.setParameter('uCapture', capture);
    },
    setRelief(flatten, behind) {
      if (capture[3] !== 1) return;
      relief[1] = Math.min(1, Math.max(0, flatten));
      relief[2] = behind ? 1 : 0;
      material.setParameter('uRelief', relief);
    },
    destroy(): void {
      mesh.destroy();
      photographTexture?.destroy();
      material.destroy();
    },
  };
}


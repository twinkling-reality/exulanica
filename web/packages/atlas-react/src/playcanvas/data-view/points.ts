import * as pc from 'playcanvas';
import { dataViewRgb, type DataViewStyle } from '@exulanica/atlas-core';
import {
  POINT_FRAGMENT_GLSL,
  POINT_FRAGMENT_WGSL,
  POINT_VERTEX_GLSL,
  POINT_VERTEX_WGSL,
} from '../point-shader.js';
import type { RepresentationPointAllocation, RepresentationPointLook } from '../representation-runtime.js';

/**
 * The data view's point draw: dense glowing sprites, or short dashes, on the point-map shader.
 *
 * ONE SHADER FAMILY. This is `point-shader.ts` with `POINT_BLEND` and `DATA_VIEW` defined, fed a
 * vertex buffer in the point-map layout (position, colour, the two tag channels), so the data view
 * and a personal point map are the same program with different switches rather than two programs
 * that drift apart. Every per-point semantic term the point-map path branches on is set to its
 * neutral value here: one segment state that is confirmed, present and fully confident, no
 * dissolve band, no photograph frame, no lens. What is left is the palette colour, the depth fade
 * (the point-map fog, fading to black under an additive blend) and the data view's sprite shape.
 *
 * WEBGL2 ONLY FOR THE LOOK. WGSL has no point size (see the header of `point-shader.ts`), so on
 * WebGPU this material draws the same samples as one-pixel points in the same colours and with the
 * same cross-fade weight, and nothing else. Nothing has measured expanded quads yet, and nothing
 * decided against them: the product creates a WebGL2 device in every configuration
 * (`atlas-binding.ts`, `deviceTypes` defaults to `['webgl2']`), and only the bake-off harness asks
 * for WebGPU. A WebGPU sprite look is open work, to be measured before it is chosen.
 *
 * Every value that shapes the look comes from the style descriptor in atlas-core.
 */

const ATTRIBUTES = {
  aPosition: pc.SEMANTIC_POSITION,
  aColor: pc.SEMANTIC_COLOR,
  aTags: pc.SEMANTIC_ATTR8,
} as const;

/** Twenty bytes a point: position, colour and the two tag channels, every stream four-aligned. */
export const DATA_VIEW_VERTEX_BYTES = 20;

/** `ShaderDesc` is documented but not exported from the engine's type surface, so it is restated. */
interface ShaderDesc {
  uniqueName: string;
  attributes?: Record<string, string>;
  vertexGLSL?: string;
  fragmentGLSL?: string;
  vertexWGSL?: string;
  fragmentWGSL?: string;
}

function dataViewShaderDesc(): ShaderDesc {
  const defines = '#define POINT_BLEND\n#define DATA_VIEW\n';
  return {
    uniqueName: 'exulanica-data-view-points',
    attributes: { ...ATTRIBUTES },
    vertexGLSL: `${defines}${POINT_VERTEX_GLSL}`,
    fragmentGLSL: `${defines}${POINT_FRAGMENT_GLSL}`,
    vertexWGSL: `${defines}${POINT_VERTEX_WGSL}`,
    fragmentWGSL: `${defines}${POINT_FRAGMENT_WGSL}`,
  };
}

/** The neutral segment table: slot 0 confirmed, palette slot 0, drawn, confidence floor 1. */
const NEUTRAL_SEGMENTS = (() => {
  const table = new Float32Array(16 * 4);
  for (let i = 0; i < 16; i += 1) table[i * 4 + 3] = 1;
  return table;
})();

/** The time uniform the data view writes once per drawn frame, shared by every data view draw. */
export const DATA_VIEW_TIME_UNIFORM = 'uDataViewTime';
/** The twinkle's clock in seconds, written once per drawn frame by the data view; held at 0 under reduced motion. */
export const DATA_VIEW_CLOCK_UNIFORM = 'uDataViewClock';
/** The share of samples every data view draw keeps, 0 to 1: a host steps it down on a GPU that cannot draw them all. */
export const DATA_VIEW_KEEP_UNIFORM = 'uDataViewKeep';

export interface DataViewPointsOptions {
  readonly device: pc.GraphicsDevice;
  /** The borrowed node whose frame the positions are in; the draw is parented under it. */
  readonly node: pc.GraphNode;
  /** Positions in that node's local frame, three per point. Copied, never retained. */
  readonly positions: Float32Array;
  readonly style: DataViewStyle;
  readonly subjectId: string;
  /** Layers to draw in; the borrowed node's own when it has a render component. */
  readonly layers?: readonly number[];
  /**
   * For samples of a surface sampled for the eye (a style with `points.screen`): each sample's surface normal in
   * the node's frame (three to a point) and the density, in samples to the square metre, at which it is first drawn
   * (one to a point), and the distances from the eye this draw covers, from the first up to the second metres (the
   * second may be Infinity). Without them every sample is drawn as before, thinned by distance alone.
   */
  readonly samples?: {
    readonly normals: Float32Array;
    readonly densities: Float32Array;
    readonly reach: readonly [number, number];
  };
}

/** A sample's first-drawn density, in samples to the square metre, as the shader's log scale reads it. */
export function dataViewDensityCode(density: number): number {
  return Math.min(65535, Math.max(0, Math.round(2048 * Math.log2(density) + 32768)));
}

/**
 * Upload one subject's samples as a data view draw. Returns null for an empty or non-finite
 * buffer rather than drawing part of it.
 */
export function createDataViewPoints(options: DataViewPointsOptions): RepresentationPointAllocation | null {
  const { device, node, positions, style, subjectId } = options;
  const pointCount = positions.length / 3;
  if (!Number.isSafeInteger(pointCount) || pointCount < 1) return null;
  const sampled = options.samples !== undefined && style.points.screen !== undefined ? options.samples : null;
  if (sampled !== null && (sampled.normals.length !== positions.length || sampled.densities.length !== pointCount)) return null;
  const bytes = new ArrayBuffer(pointCount * DATA_VIEW_VERTEX_BYTES);
  const floats = new Float32Array(bytes);
  const view = new Uint8Array(bytes);
  const shorts = new Uint16Array(bytes);
  let minX = Infinity; let minY = Infinity; let minZ = Infinity;
  let maxX = -Infinity; let maxY = -Infinity; let maxZ = -Infinity;
  for (let i = 0; i < pointCount; i += 1) {
    const x = positions[i * 3]!; const y = positions[i * 3 + 1]!; const z = positions[i * 3 + 2]!;
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
    const base = i * DATA_VIEW_VERTEX_BYTES;
    floats[base / 4] = x; floats[base / 4 + 1] = y; floats[base / 4 + 2] = z;
    // White at full support: the palette uniform decides the colour, and the tags stay zero. A sample of a surface
    // sampled for the eye carries its normal in the colour channels and its first-drawn density in the second tag.
    view[base + 12] = 255; view[base + 13] = 255; view[base + 14] = 255; view[base + 15] = 255;
    if (sampled !== null) {
      const nx = sampled.normals[i * 3]!, ny = sampled.normals[i * 3 + 1]!, nz = sampled.normals[i * 3 + 2]!;
      const density = sampled.densities[i]!;
      if (!Number.isFinite(nx) || !Number.isFinite(ny) || !Number.isFinite(nz) || !(density > 0)) return null;
      view[base + 12] = Math.round(Math.min(1, Math.max(-1, nx)) * 127.5 + 127.5);
      view[base + 13] = Math.round(Math.min(1, Math.max(-1, ny)) * 127.5 + 127.5);
      view[base + 14] = Math.round(Math.min(1, Math.max(-1, nz)) * 127.5 + 127.5);
      shorts[base / 2 + 9] = dataViewDensityCode(density);
    }
    if (x < minX) minX = x; if (y < minY) minY = y; if (z < minZ) minZ = z;
    if (x > maxX) maxX = x; if (y > maxY) maxY = y; if (z > maxZ) maxZ = z;
  }
  const format = new pc.VertexFormat(device, [
    { semantic: pc.SEMANTIC_POSITION, components: 3, type: pc.TYPE_FLOAT32 },
    { semantic: pc.SEMANTIC_COLOR, components: 4, type: pc.TYPE_UINT8, normalize: true },
    { semantic: pc.SEMANTIC_ATTR8, components: 2, type: pc.TYPE_UINT16, normalize: false },
  ]);
  const vertexBuffer = new pc.VertexBuffer(device, format, pointCount, { usage: pc.BUFFER_STATIC, data: bytes });
  const mesh = new pc.Mesh(device);
  mesh.vertexBuffer = vertexBuffer;
  mesh.primitive[0] = { type: pc.PRIMITIVE_POINTS, base: 0, count: pointCount, indexed: false, baseVertex: 0 };
  // Bounds from the samples themselves, so the renderer never culls a valid draw off-camera.
  mesh.aabb = new pc.BoundingBox();
  mesh.aabb.setMinMax(new pc.Vec3(minX, minY, minZ), new pc.Vec3(maxX, maxY, maxZ));

  // The band phase is one device-scope value shared by every data view draw (the overlay writes it
  // per drawn frame). A material parameter would shadow it, so only a missing value is filled.
  const time = device.scope.resolve(DATA_VIEW_TIME_UNIFORM);
  if (time.value === null || time.value === undefined) time.setValue(0);
  // The twinkle's clock and the kept share are device-scope values of the same kind: still, and every sample.
  const clock = device.scope.resolve(DATA_VIEW_CLOCK_UNIFORM);
  if (clock.value === null || clock.value === undefined) clock.setValue(0);
  const keep = device.scope.resolve(DATA_VIEW_KEEP_UNIFORM);
  if (keep.value === null || keep.value === undefined) keep.setValue(1);
  const material = new pc.ShaderMaterial(dataViewShaderDesc() as ConstructorParameters<typeof pc.ShaderMaterial>[0]);
  material.blendType = pc.BLEND_ADDITIVEALPHA;
  material.depthWrite = false;
  material.depthTest = true;
  material.cull = pc.CULLFACE_NONE;
  const fade = style.points.depthFade;
  material.setParameter('uSegState[0]', NEUTRAL_SEGMENTS);
  material.setParameter('uIsland', [1, 0, 0, 1]);
  material.setParameter('uPoint', [style.points.sizeMetres, style.points.maxPixels, 900, 0]);
  material.setParameter('uSupportFloor', 1);
  material.setParameter('uFog', [fade.startMetres, fade.endMetres, fade.density, 1]);
  material.setParameter('uFogColor', [0, 0, 0]);
  material.setParameter('uExposure', 1);
  material.setParameter('uLens', [0, 0, 0, 0]);
  material.setParameter('uFrame', [0, 0, 0, 0]);
  material.setParameter('uViewpoint', [0, 0, 0, 0]);
  material.setParameter('uCapture', [0, 0, 0, 0]);
  material.setParameter('uRelief', [1, 0, 0, 0]);
  material.setParameter('uDataViewThin', [style.points.thinning.keepAllWithinMetres, style.points.thinning.maxGain, 0, 0]);
  material.setParameter('uDataViewGlow', [
    style.points.glow.core, style.points.glow.falloff, style.points.glow.halo, style.points.pullMetres,
  ]);
  // A style before version 3 has no twinkle: depth 0 draws every sample at its one brightness.
  material.setParameter('uDataViewLife', [style.points.twinkle?.depth ?? 0, style.points.twinkle?.periodSeconds ?? 1, 0, 0]);
  // Before version 4, or for samples not taken for the eye, all zero: thinned by distance alone.
  const screen = sampled !== null ? style.points.screen! : null;
  material.setParameter('uDataViewScreen', screen === null ? [0, 0, 0, 0]
    : [screen.density, screen.facingFloor, screen.nearestMetres, Math.cos((screen.coneDegrees * Math.PI) / 180)]);
  material.setParameter('uDataViewReach', sampled === null ? [0, 0] : [sampled.reach[0], Math.min(1e9, sampled.reach[1])]);
  const palette = new Float32Array(16);
  const dataView = new Float32Array(4);
  const look = new Float32Array(4);
  material.setParameter('uPalette[0]', palette);
  material.setParameter('uDataView', dataView);
  material.setParameter('uDataViewLook', look);

  const entity = new pc.Entity(`data-view-points:${subjectId}`);
  node.addChild(entity);
  const instance = new pc.MeshInstance(mesh, material, entity);
  instance.pick = false;
  instance.castShadow = false;
  instance.receiveShadow = false;
  const layers = options.layers ?? (node instanceof pc.Entity ? node.render?.layers : undefined);
  entity.addComponent('render', {
    meshInstances: [instance],
    castShadows: false,
    receiveShadows: false,
    ...(layers ? { layers: [...layers] } : {}),
  });

  let destroyed = false;
  let weight = 0;
  let current: RepresentationPointLook = { colour: '#ffffff', treatment: 'points', gain: 1 };
  const apply = (): void => {
    const [r, g, b] = dataViewRgb(current.colour);
    palette[0] = r; palette[1] = g; palette[2] = b; palette[3] = 1;
    const dashed = current.treatment === 'dashes';
    const scale = dashed ? style.dashes.sizeScale : 1;
    dataView[0] = style.points.sizeMetres * scale;
    dataView[1] = style.points.minPixels * scale;
    dataView[2] = style.points.maxPixels * scale;
    dataView[3] = dashed ? style.dashes.halfWidth : 0;
    look[0] = Math.min(1, style.points.intensity * current.gain);
    // The points arrive faster than the surface dissolves, so the midpoint shows both.
    look[1] = Math.min(1, weight * style.points.rise);
    look[2] = dashed ? style.dashes.bandDepth : 0;
    look[3] = dashed ? style.dashes.bandsPerMetre : 0;
    material.setParameter('uPalette[0]', palette);
    material.setParameter('uDataView', dataView);
    material.setParameter('uDataViewLook', look);
    instance.visible = weight > 0;
  };
  apply();
  material.update();
  return {
    pointCount,
    // CPU vertex storage plus the GPU copy of the same bytes; engine and material overhead is
    // bounded separately by the registry size.
    byteLength: bytes.byteLength * 2,
    setWeight(next) {
      if (destroyed || next === weight) return;
      weight = next;
      apply();
    },
    setLook(next) {
      if (destroyed || (next.colour === current.colour && next.treatment === current.treatment
        && next.gain === current.gain)) return;
      current = next;
      apply();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      entity.destroy();
      mesh.destroy();
      material.destroy();
    },
  };
}

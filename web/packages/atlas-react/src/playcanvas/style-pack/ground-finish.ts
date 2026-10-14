import * as pc from 'playcanvas';

/**
 * The finish a site's grounds and water are drawn with, over whatever colour the pack gives them.
 *
 * A pack states a ground's colour and a water's colour; on its own that is one flat tone to the
 * horizon. The finish varies a ground's tone over the ground in the world's metres (a broad wander
 * and a finer one, a little warmer in places and a little cooler in others), darkens it near water
 * as wet ground is, and draws water lighter where it is shallow at its edge and darker towards its
 * middle, with light that drifts over it and a brighter sheen seen at a low angle. Every figure is
 * read from one data file, each with its class and reason
 * (`assets/catalogs/world-kinds/surface-finish.v2.json`; version 1 is still read).
 *
 * THE SEA AND LAKES OF A SITE ON LAND (version 2) are drawn with the same water finish, but their
 * depth is the land's own: the scene depth behind the surface (the depth contact shadowing writes,
 * read as the graphics lane's depth water reads it, with no copy of the scene's colour), so a beach
 * shelves from light to dark and a basin shows its bowl, and the water fades in over its shallowest
 * depth, so the shoreline is soft (`applySeaFinish`).
 *
 * PRESENTATION ONLY. Nothing here changes where anything is, what a ground or water is, where a
 * person may walk or what a pick answers; a material keeps its own colour chunk and the finish works
 * on the colour that chunk makes.
 *
 * THE COLOUR CHUNK IS WRAPPED, NOT REPLACED. The material's colour function (a pattern's, an up
 * swatch's, the engine's own) is renamed and called first; the finish then works on its colour.
 * A ground border (`border-material.ts`) set into the chunk before or after runs as before.
 *
 * GLSL ONLY, as the border is: the finish runs on the WebGL2 device the page asks for
 * (`finishRuns`); on a WebGPU device every ground and water keeps its pack's flat colour.
 */

export const SURFACE_FINISH_PROFILE = 'exulanica.surface-finish/v1';
/** Version 2 adds the depth figures of a site on land's sea and lakes. */
export const SURFACE_FINISH_PROFILE_V2 = 'exulanica.surface-finish/v2';

/** The finish as the drawing reads it: shares from 0 to 1, metres, metres a second, pixels. */
export interface SurfaceFinish {
  readonly groundVariation: number;
  readonly groundBroadM: number;
  readonly groundFineM: number;
  readonly groundWarmth: number;
  readonly wetBandM: number;
  readonly wetDarkening: number;
  readonly waterDeepM: number;
  readonly waterShallowLift: number;
  readonly waterDeepDarkening: number;
  readonly waterRipple: number;
  readonly waterRippleM: number;
  readonly waterRippleSpeed: number;
  readonly waterSheen: number;
  readonly reflectionStrength: number;
  readonly reflectionSizePx: number;
  /** From version 2: how deep a sea or lake on land is where it reads in its deepest colour, metres. */
  readonly waterDepthFullM?: number;
  /** From version 2: how deep a sea or lake on land is where its edge has faded in fully, metres. */
  readonly waterShoreFadeM?: number;
}

interface Row {
  readonly field: keyof SurfaceFinish;
  readonly unit: string;
  readonly from: number;
  readonly to: number;
  readonly whole?: boolean;
}

/** Every entry the finish needs, by its key in the file, with the unit and range it is read in. */
const ROWS: Readonly<Record<string, Row>> = {
  ground_variation_share: { field: 'groundVariation', unit: 'share', from: 0, to: 0.5 },
  ground_broad_m: { field: 'groundBroadM', unit: 'metre', from: 1, to: 200 },
  ground_fine_m: { field: 'groundFineM', unit: 'metre', from: 0.2, to: 50 },
  ground_warmth_share: { field: 'groundWarmth', unit: 'share', from: 0, to: 0.3 },
  wet_band_m: { field: 'wetBandM', unit: 'metre', from: 0, to: 10 },
  wet_darkening_share: { field: 'wetDarkening', unit: 'share', from: 0, to: 0.8 },
  water_deep_m: { field: 'waterDeepM', unit: 'metre', from: 0.1, to: 50 },
  water_shallow_lift_share: { field: 'waterShallowLift', unit: 'share', from: 0, to: 1 },
  water_deep_darkening_share: { field: 'waterDeepDarkening', unit: 'share', from: 0, to: 0.9 },
  water_ripple_share: { field: 'waterRipple', unit: 'share', from: 0, to: 0.5 },
  water_ripple_m: { field: 'waterRippleM', unit: 'metre', from: 0.1, to: 20 },
  water_ripple_speed_m_per_second: { field: 'waterRippleSpeed', unit: 'metre_per_second', from: 0, to: 5 },
  water_sheen_share: { field: 'waterSheen', unit: 'share', from: 0, to: 1 },
  reflection_strength_share: { field: 'reflectionStrength', unit: 'share', from: 0, to: 1 },
  reflection_size_px: { field: 'reflectionSizePx', unit: 'pixel', from: 64, to: 2048, whole: true },
};

/** The entries version 2 adds. */
const ROWS_V2: Readonly<Record<string, Row>> = {
  water_depth_full_m: { field: 'waterDepthFullM', unit: 'metre', from: 0.2, to: 50 },
  water_shore_fade_m: { field: 'waterShoreFadeM', unit: 'metre', from: 0, to: 2 },
};

/** Read the surface finish catalog, or refuse it by what is wrong with it. */
export function readSurfaceFinish(value: unknown): SurfaceFinish {
  const refuse = (what: string): never => {
    throw new Error(`surface finish catalog: ${what}`);
  };
  if (typeof value !== 'object' || value === null || Array.isArray(value)) refuse('is not a document');
  const document = value as { readonly profile?: unknown; readonly entries?: unknown };
  if (document.profile !== SURFACE_FINISH_PROFILE && document.profile !== SURFACE_FINISH_PROFILE_V2) {
    refuse(`is not ${SURFACE_FINISH_PROFILE} or ${SURFACE_FINISH_PROFILE_V2}`);
  }
  if (!Array.isArray(document.entries)) refuse('states no entries');
  const rows: Readonly<Record<string, Row>> = document.profile === SURFACE_FINISH_PROFILE_V2 ? { ...ROWS, ...ROWS_V2 } : ROWS;
  const table: Partial<Record<keyof SurfaceFinish, number>> = {};
  for (const raw of document.entries as readonly unknown[]) {
    const entry = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
    const key = entry['key'];
    const row = typeof key === 'string' && Object.hasOwn(rows, key) ? rows[key]! : refuse(`states an entry this page does not read: ${String(key)}`);
    if (table[row.field] !== undefined) refuse(`states ${String(key)} twice`);
    if (entry['unit'] !== row.unit) refuse(`${String(key)} is not in ${row.unit}`);
    const stated = entry['value'];
    if (typeof stated !== 'number' || !Number.isFinite(stated) || stated < row.from || stated > row.to || (row.whole === true && !Number.isInteger(stated))) {
      refuse(`${String(key)} is not a ${row.whole === true ? 'whole ' : ''}figure from ${row.from} to ${row.to}`);
    }
    if (typeof entry['class'] !== 'string' || typeof entry['reason'] !== 'string' || entry['reason'].length === 0) {
      refuse(`${String(key)} states no class or no reason`);
    }
    table[row.field] = stated as number;
  }
  for (const [key, row] of Object.entries(rows)) if (table[row.field] === undefined) refuse(`states no ${key}`);
  return Object.freeze(table as SurfaceFinish);
}

/** Whether the finish runs on a device: on WebGL2, the one device it is written for, as the border. */
export const finishRuns = (device: pc.GraphicsDevice): boolean => device.isWebGPU !== true;

/**
 * The most waters a finish measures its shore and depth from. A site with more takes its largest
 * this many: a wet band or a shallow edge is a near thing, and the shader's loop needs a bound.
 */
export const FINISH_WATERS_MOST = 8;

/** A water's rectangle in the world's metres: west, north-most z, east, south-most z. */
export type WaterRect = readonly [number, number, number, number];

const waters = (text: (n: number) => string): string => Array.from({ length: FINISH_WATERS_MOST }, (_, n) => text(n)).join('\n');

/** Text both finishes share: the noise and the distance to the waters. Declared once per shader. */
const SHARED = `
uniform float exuFinishWaterCount;
${waters((n) => `uniform vec4 exuFinishWater${n};`)}
float exuFinishHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float exuFinishNoise(vec2 p) {
\tvec2 i = floor(p);
\tvec2 t = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuFinishHash(i), exuFinishHash(i + vec2(1.0, 0.0)), t.x), mix(exuFinishHash(i + vec2(0.0, 1.0)), exuFinishHash(i + vec2(1.0, 1.0)), t.x), t.y);
}
float exuFinishOutside(vec4 r, vec2 p) { return length(max(vec2(r.x - p.x, r.y - p.y), max(vec2(p.x - r.z, p.y - r.w), vec2(0.0)))); }
float exuFinishInside(vec4 r, vec2 p) { return min(min(p.x - r.x, r.z - p.x), min(p.y - r.y, r.w - p.y)); }
float exuFinishShore(vec2 p) {
\tfloat d = 1.0e6;
${waters((n) => `\tif (exuFinishWaterCount > ${n}.5) d = min(d, exuFinishOutside(exuFinishWater${n}, p));`)}
\treturn d;
}
float exuFinishDepth(vec2 p) {
\tfloat d = 0.0;
${waters((n) => `\tif (exuFinishWaterCount > ${n}.5) d = max(d, exuFinishInside(exuFinishWater${n}, p));`)}
\treturn d;
}
`;

const ALBEDO = 'void getAlbedo() {';
const BASE = 'void exuFinishBase() {';

const GROUND = `${SHARED}
uniform vec4 exuFinishGround;
uniform vec2 exuFinishWet;
void getAlbedo() {
\texuFinishBase();
\tvec2 p = vPositionW.xz;
\tfloat n = exuFinishNoise(p / exuFinishGround.y) * 0.7 + exuFinishNoise(p / exuFinishGround.z + vec2(13.1, 7.7)) * 0.3;
\tfloat lean = exuFinishGround.w * (2.0 * exuFinishNoise(p / (exuFinishGround.y * 1.9) + vec2(41.0, 3.0)) - 1.0);
\tdAlbedo *= (1.0 + exuFinishGround.x * (2.0 * n - 1.0)) * vec3(1.0 + lean, 1.0, 1.0 - lean);
\tfloat wet = 1.0 - smoothstep(0.0, max(exuFinishWet.x, 0.0001), exuFinishShore(p));
\tdAlbedo *= 1.0 - exuFinishWet.y * wet * step(0.0001, exuFinishWet.x);
}
`;

const WATER = `${SHARED}
uniform float exuFinishTime;
uniform vec3 exuFinishEye;
uniform vec4 exuFinishWaterTone;
uniform vec4 exuFinishWaterRipple;
void getAlbedo() {
\texuFinishBase();
\tvec2 p = vPositionW.xz;
\tfloat deep = smoothstep(0.0, exuFinishWaterTone.z, exuFinishDepth(p));
\tdAlbedo *= mix(1.0 + exuFinishWaterTone.x, 1.0 - exuFinishWaterTone.y, deep);
\tvec2 drift = vec2(0.8, 0.6) * exuFinishTime * exuFinishWaterRipple.y;
\tfloat r = exuFinishNoise((p + drift) / exuFinishWaterRipple.x) * 0.6 + exuFinishNoise((p - drift.yx) / (exuFinishWaterRipple.x * 0.47) + vec2(5.0, 9.0)) * 0.4;
\tdAlbedo *= 1.0 + exuFinishWaterTone.w * (2.0 * r - 1.0);
\tvec3 toEye = normalize(exuFinishEye - vPositionW);
\tfloat grazing = pow(1.0 - clamp(toEye.y, 0.0, 1.0), 4.0);
\tdAlbedo = mix(dAlbedo, min(dAlbedo * 1.6 + vec3(0.04), vec3(1.0)), exuFinishWaterRipple.z * grazing);
}
`;

/**
 * A sea's or lake's depth, straight down to the land under it, from the scene depth behind the
 * surface. Declared once whichever of the sea's two chunks the shader includes first.
 */
const SEA_DEPTH = `
#ifndef EXU_SEA_DEPTH
#define EXU_SEA_DEPTH
#include "screenDepthPS"
uniform vec4 exuFinishSea;
float exuSeaDepth() {
\tvec2 screen = gl_FragCoord.xy * uScreenSize.zw;
\tfloat thickness = max(getLinearScreenDepth(screen) - 1.0 / gl_FragCoord.w, 0.0);
\tvec3 view = normalize(view_position - vPositionW);
\treturn thickness * max(abs(view.y), 0.08);
}
#endif
`;

/** The water finish of a sea or lake on land: the water's, with the land's own depth. */
const SEA = WATER.replace('\tfloat deep = smoothstep(0.0, exuFinishWaterTone.z, exuFinishDepth(p));', '\tfloat deep = smoothstep(0.0, exuFinishSea.x, exuSeaDepth());')
  .replace('uniform vec4 exuFinishWaterTone;', `${SEA_DEPTH}\nuniform vec4 exuFinishWaterTone;`);

/** A sea's or lake's edge: faded in over the shore depth, so the shoreline is soft. */
const SEA_OPACITY = `${SEA_DEPTH}
void getOpacity() {
\tdAlpha = smoothstep(0.0, max(exuFinishSea.y, 0.0001), exuSeaDepth());
}
`;

/** Marks that say a chunk already carries a finish. */
const GROUND_MARK = 'uniform vec4 exuFinishGround;';
const WATER_MARK = 'uniform vec4 exuFinishWaterTone;';

/**
 * A colour chunk with a finish set after it: its colour function renamed and called first, the
 * finish's own colour function after. A chunk that already carries the finish is returned as it
 * is; one with no colour function this module knows is refused, since a finish set into nothing
 * would silently draw none.
 */
export function withFinish(chunk: string, finish: 'ground' | 'water' | 'sea'): string {
  if (chunk.includes(GROUND_MARK) || chunk.includes(WATER_MARK)) return chunk;
  if (chunk.split(ALBEDO).length !== 2) throw new TypeError('a colour chunk the finish cannot be set into: it has no one colour function');
  return chunk.replace(ALBEDO, BASE) + (finish === 'ground' ? GROUND : finish === 'water' ? WATER : SEA);
}

const OFF = [0, 0, 0, 0];

function wrap(device: pc.GraphicsDevice, material: pc.StandardMaterial, finish: 'ground' | 'water' | 'sea'): void {
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  const held = chunks.get('diffusePS') as string | undefined;
  const plain = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined;
  if (held === undefined && plain === undefined) throw new TypeError('the engine states no colour chunk to set the finish into');
  material.shaderChunksVersion = '2.8';
  chunks.set('diffusePS', withFinish(held ?? plain!, finish));
  material.setParameter('exuFinishWaterCount', 0);
  for (let n = 0; n < FINISH_WATERS_MOST; n += 1) material.setParameter(`exuFinishWater${n}`, OFF);
}

/** Give a ground's material the ground finish. */
export function applyGroundFinish(device: pc.GraphicsDevice, material: pc.StandardMaterial, finish: SurfaceFinish): void {
  wrap(device, material, 'ground');
  material.setParameter('exuFinishGround', [finish.groundVariation, finish.groundBroadM, finish.groundFineM, finish.groundWarmth]);
  material.setParameter('exuFinishWet', [finish.wetBandM, finish.wetDarkening]);
  material.update();
}

/** Give a water's material the water finish; its time and the eye are kept by `WaterRipples`. */
export function applyWaterFinish(device: pc.GraphicsDevice, material: pc.StandardMaterial, finish: SurfaceFinish): void {
  wrap(device, material, 'water');
  material.setParameter('exuFinishTime', 0);
  material.setParameter('exuFinishEye', [0, 1000, 0]);
  material.setParameter('exuFinishWaterTone', [finish.waterShallowLift, finish.waterDeepDarkening, finish.waterDeepM, finish.waterRipple]);
  material.setParameter('exuFinishWaterRipple', [finish.waterRippleM, finish.waterRippleSpeed, finish.waterSheen, 0]);
  material.update();
}

/**
 * Give a site on land's sea or lake the water finish with the land's own depth, faded in at its
 * shore, blended over the scene. Needs version 2's depth figures: false, and nothing set, without
 * them. Its time and the eye are kept by `WaterRipples`.
 */
export function applySeaFinish(device: pc.GraphicsDevice, material: pc.StandardMaterial, finish: SurfaceFinish): boolean {
  if (finish.waterDepthFullM === undefined || finish.waterShoreFadeM === undefined) return false;
  wrap(device, material, 'sea');
  material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('opacityPS', SEA_OPACITY);
  material.blendType = pc.BLEND_NORMAL;
  material.depthWrite = false;
  material.opacity = 1;
  material.setParameter('exuFinishTime', 0);
  material.setParameter('exuFinishEye', [0, 1000, 0]);
  material.setParameter('exuFinishWaterTone', [finish.waterShallowLift, finish.waterDeepDarkening, finish.waterDeepM, finish.waterRipple]);
  material.setParameter('exuFinishWaterRipple', [finish.waterRippleM, finish.waterRippleSpeed, finish.waterSheen, 0]);
  material.setParameter('exuFinishSea', [finish.waterDepthFullM, finish.waterShoreFadeM, 0, 0]);
  material.update();
  return true;
}

/**
 * Tell a finished material where the site's waters are. More than `FINISH_WATERS_MOST` keeps the
 * largest that many.
 */
export function setFinishWaters(material: pc.StandardMaterial, rects: readonly WaterRect[]): void {
  const area = (r: WaterRect) => (r[2] - r[0]) * (r[3] - r[1]);
  const kept = [...rects].sort((a, b) => area(b) - area(a)).slice(0, FINISH_WATERS_MOST);
  material.setParameter('exuFinishWaterCount', kept.length);
  for (let n = 0; n < FINISH_WATERS_MOST; n += 1) material.setParameter(`exuFinishWater${n}`, kept[n] === undefined ? OFF : [...kept[n]!]);
}

/** A water plane's rectangle in the world's metres, from the engine's own bounds of its mesh. */
export function waterRectOf(instance: pc.MeshInstance): WaterRect {
  const box = instance.aabb;
  const c = box.center, h = box.halfExtents;
  return [c.x - h.x, c.z - h.z, c.x + h.x, c.z + h.z];
}

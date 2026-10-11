import * as pc from 'playcanvas';
import { BORDER_NEIGHBOURS_MOST, borderReachMm, type BorderNeighbour, type GroundBorder, type PlaneBorder } from '@exulanica/atlas-core';

/**
 * A ground's broken border, drawn in its colour chunk.
 *
 * `ground-border.ts` in atlas-core states which ground breaks over which and how. Here a ground
 * plane's material is given the working of it: at every point of the plane, in the world's metres,
 *
 *  1. where a neighbour that lies over this plane is drawn at the point, this plane is not: two
 *     grounds never both draw one point, so neither needs lifting over the other and nothing
 *     shimmers far off;
 *  2. within a neighbour's reach of that neighbour's rectangle this plane is drawn whatever its own
 *     edge says: the lower ground runs on under the upper one's break, so what shows in a break is
 *     the neighbour and never a third ground under both;
 *  3. elsewhere it is cut by its own edge: a small ragged break at the ruled line over a gentler
 *     wander of the line. Where land reaches water its edge only ever reaches outward, in tongues;
 *  4. a plane that lies under (water) is drawn inside its own rectangle only, less those tongues:
 *     it is cut back from its ruled line by the edge of the land it meets there, never past it.
 *
 * An edge is worked from the point's place in the world alone, so a neighbour's edge is the same
 * line in this plane's working as in the neighbour's own. The plane is drawn larger than its
 * rectangle by the catalog's greatest reach, which is as far as any of this can put its edge.
 *
 * WHERE THE CUT-OUT DOES NOT RUN, the plain plane is drawn whole. The working is off unless a plane
 * states its own values (`setPlaneBorder`); a material never given the chunk, or a plane never
 * given values, draws its full rectangle as before.
 *
 * GLSL ONLY. The working is written for the WebGL2 device the page asks for and has been seen on
 * it. There is no WGSL text: a caller gives no ground a border on a WebGPU device (`bordersRun`),
 * where every ground keeps its ruled rectangle, so no text that has run nowhere can leave a ground
 * undrawn.
 *
 * The working's text is this module's, set into whatever colour chunk the material already has (a
 * pattern's, an up swatch's) or, where it has none, the engine's own for the device. The only
 * values that reach a shader are a plane's own numbers, as parameters.
 */

/** The marker that says a chunk already carries the border's working. */
const MARK = 'exuBorderCut';

const over = (text: (n: number) => string): string => Array.from({ length: BORDER_NEIGHBOURS_MOST }, (_, n) => text(n)).join('\n');

const GLSL = `
uniform vec4 exuBorder;
uniform vec4 exuBorderShape;
${over((n) => `uniform vec4 exuOver${n};\nuniform vec4 exuOverShape${n};`)}
float exuBorderHash(vec2 p) { return fract(sin(dot(p, vec2(269.5, 183.3))) * 43758.5453); }
float exuBorderNoise(vec2 p) {
\tvec2 i = floor(p);
\tvec2 t = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuBorderHash(i), exuBorderHash(i + vec2(1.0, 0.0)), t.x), mix(exuBorderHash(i + vec2(0.0, 1.0)), exuBorderHash(i + vec2(1.0, 1.0)), t.x), t.y);
}
float exuBorderInside(vec4 r, vec2 p) { return min(min(p.x - r.x, r.z - p.x), min(p.y - r.y, r.w - p.y)); }
float exuBorderEdge(vec4 s, vec2 p) {
\tfloat fine = s.x > 0.0 ? s.x * (exuBorderNoise(p / (s.x * 1.4)) - 0.5) : 0.0;
\tfloat wide = s.y > 0.0 ? s.y * (2.0 * exuBorderNoise(p / s.z + vec2(31.0, 7.0)) - 1.0) : 0.0;
\treturn fine + wide;
}
bool exuBorderKept(vec4 r, vec4 s, vec2 p) { return exuBorderInside(r, p) >= exuBorderEdge(s, p); }
bool exuBorderNear(vec4 r, vec4 s, vec2 p) { return exuBorderInside(r, p) >= -(s.y + 0.5 * s.x); }
void ${MARK}() {
\tfloat mode = exuBorderShape.w;
\tif (mode <= 0.0) return;
\tvec2 p = vPositionW.xz;
\tfloat inside = exuBorderInside(exuBorder, p);
\tif (mode > 1.5) {
\t\tvec4 s = exuBorderShape;
\t\tbool met = false;
${over((n) => `\t\tif (!met && exuOverShape${n}.w > 0.0 && exuBorderNear(exuOver${n}, exuOverShape${n}, p)) { s = exuOverShape${n}; met = true; }`)}
\t\tif (inside < abs(exuBorderEdge(s, p))) discard;
\t\treturn;
\t}
\tbool under = false;
\tbool shore = false;
\tfloat reach = exuBorderShape.y + 0.5 * exuBorderShape.x;
${over((n) => `\tif (exuOverShape${n}.w > 1.5) {\n\t\tshore = shore || exuBorderInside(exuOver${n}, p) >= -reach;\n\t} else if (exuOverShape${n}.w > 0.0) {\n\t\tif (exuBorderKept(exuOver${n}, exuOverShape${n}, p)) discard;\n\t\tunder = under || exuBorderNear(exuOver${n}, exuOverShape${n}, p);\n\t}`)}
\tfloat edge = exuBorderEdge(exuBorderShape, p);
\tif (shore) edge = -abs(edge);
\tif (!under && inside < edge) discard;
}
`;

const ALBEDO = 'void getAlbedo() {';

/**
 * A colour chunk with the border's working set into it: its text before the chunk's own, its call
 * first in the chunk's colour function. A chunk that already carries it is returned as it is; one
 * with no colour function this module knows is refused, since a border set into nothing would
 * silently draw none.
 */
export function withBorder(chunk: string): string {
  if (chunk.includes(`${MARK}();`)) return chunk;
  if (chunk.split(ALBEDO).length !== 2) throw new TypeError('a colour chunk the border cannot be set into: it has no one colour function');
  return chunk.replace(ALBEDO, `${GLSL}${ALBEDO}\n\t${MARK}();`);
}

/** Whether the border's working runs on a device: on WebGL2, the one device it is written for. */
export const bordersRun = (device: pc.GraphicsDevice): boolean => device.isWebGPU !== true;

const OFF = [0, 0, 0, 0];

/**
 * Give a material the border's working in its colour chunk, off until a plane states values.
 * Returns whether the material was changed (false where it already carries it).
 */
export function applyBorder(device: pc.GraphicsDevice, material: pc.StandardMaterial): boolean {
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  const held = chunks.get('diffusePS') as string | undefined;
  if (held?.includes(`${MARK}();`) === true) return false;
  // A material with no colour chunk of its own draws by the engine's: the working goes into that text.
  const plain = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined;
  if (held === undefined && plain === undefined) throw new TypeError('the engine states no colour chunk to set the border into');
  chunks.set('diffusePS', withBorder(held ?? plain!));
  material.setParameter('exuBorder', OFF);
  material.setParameter('exuBorderShape', OFF);
  for (let n = 0; n < BORDER_NEIGHBOURS_MOST; n += 1) {
    material.setParameter(`exuOver${n}`, OFF);
    material.setParameter(`exuOverShape${n}`, OFF);
  }
  material.update();
  return true;
}

/**
 * A site rectangle (millimetres: west, south, east, north) as the shader takes it: world metres, x
 * then z, least then most, from where the site's origin lies in the world.
 */
const worldRect = ([x0, y0, x1, y1]: readonly [number, number, number, number], [x, z]: readonly [number, number]): number[] =>
  [x + x0 / 1000, z - y1 / 1000, x + x1 / 1000, z - y0 / 1000];

/**
 * A border as the shader takes it: edge, wander and period in metres, and how it is read. For a
 * plane's own: 1 a ground that breaks over, 2 one that lies under. For a neighbour: 1 a ground lying
 * over the plane, 2 a water the plane reaches. A ruled edge is no edge and no wander.
 */
const shapeOf = (border: GroundBorder | null, read: 1 | 2): number[] =>
  (border === null ? [0, 0, 1, read] : [border.edgeMm / 1000, border.wanderMm / 1000, border.periodMm / 1000, read]);

/** The names of every value a plane states, for taking them back. */
export const BORDER_PARAMETERS: readonly string[] = Object.freeze([
  'exuBorder', 'exuBorderShape',
  ...Array.from({ length: BORDER_NEIGHBOURS_MOST }, (_, n) => [`exuOver${n}`, `exuOverShape${n}`]).flat(),
]);

/**
 * State one plane's border on its mesh instance: its own rectangle and edge, and the neighbours it
 * is worked against. `originM` is where the site's origin lies in the world, x then z, in metres;
 * the site is laid along the world's axes.
 */
export function setPlaneBorder(
  instance: pc.MeshInstance, rectMm: readonly [number, number, number, number], plan: PlaneBorder, originM: readonly [number, number],
): void {
  instance.setParameter('exuBorder', worldRect(rectMm, originM));
  instance.setParameter('exuBorderShape', shapeOf(plan.own, plan.own?.lies === 'under' ? 2 : 1));
  for (let n = 0; n < BORDER_NEIGHBOURS_MOST; n += 1) {
    const neighbour: BorderNeighbour | undefined = plan.over[n];
    instance.setParameter(`exuOver${n}`, neighbour === undefined ? OFF : worldRect(neighbour.rectMm, originM));
    instance.setParameter(`exuOverShape${n}`, neighbour === undefined ? OFF : shapeOf(neighbour.border, neighbour.as === 'water' ? 2 : 1));
  }
}

/** Take a plane's border back: it draws its full rectangle again. */
export function clearPlaneBorder(instance: pc.MeshInstance): void {
  for (const name of BORDER_PARAMETERS) instance.deleteParameter(name);
}

/** How far a border's edge may lie from its ruled line, metres, for a caller that grows a plane. */
export const borderReachM = (border: GroundBorder): number => borderReachMm(border) / 1000;

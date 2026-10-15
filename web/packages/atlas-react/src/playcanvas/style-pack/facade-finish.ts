import * as pc from 'playcanvas';
import type { StylePackFacade } from '@exulanica/atlas-core';
import { linearRgb } from './preset-look.js';

/**
 * The windows a building's walls are drawn with, over whatever colour the pack gives them, where the
 * pack states a `facade` for the wall's look role.
 *
 * A pack states a wall's colour; on its own a building is then a box of one tone. The finish draws
 * the building's storeys and bays on each face of it that looks out: rows from the building's own
 * base, each storey the drawing states (else the building's whole height) holding the whole number
 * of rows nearest the rule's storey height, so rows meet the building's storeys and its top; bays fitted to each face from the
 * building's corner (as many of the rule's least bay as the face holds, stretched to fill it), and
 * in each bay of each storey one window of the rule's one size, centred, its foot at the sill, never
 * wider than its bay and never into the wall the next floor stands on. The storeys from the ground
 * that the rule keeps clear have none. Around each window, its reveal (the jambs and head seen into
 * as the eye moves, in shade) and its sill ledge; inside, glass darker and glossier than the wall, so
 * it shows the sky, and a room behind it (its ceiling, floor, sides and back, shifting as the eye
 * moves), lit by its lamp or dim. Windows are lit by room: a share of rooms, the light's own where
 * it states one (`litWindows`), else the rule's by the look's sun, none or few by day and more at
 * dusk. Once a bay is smaller than a pixel the grid fades to its average colour and light, so a far
 * wall does not shimmer. Every figure is the rule's (`StylePackFacade`); the shading of a room's
 * surfaces by how the lamp reaches them is the drawing's own model.
 *
 * PRESENTATION ONLY. Nothing here changes where anything is, what a wall is, where a person may walk
 * or what a pick answers. A painted window is not an opening. It is drawn on the faces of a
 * building's walls that lie on its edge and look out of it (`facadeFronts`), so never inside a
 * building, and never on a boundary wall: a wall's own mesh instance states its building and its
 * rule (`setFacadeWall`), and a material worn by any wall that states none draws its plain colour.
 *
 * THE CHUNKS ARE WRAPPED, NOT REPLACED, as the surface finish's are (`ground-finish.ts`): the
 * material's colour, emission and gloss functions are renamed and called first, and the finish works
 * on what they make, so a pattern, a texture, a pack's own emission and the engine's gloss all still
 * count. A chunk that already carries the finish is left as it is; one without exactly one function
 * of the name is refused.
 *
 * GLSL ONLY: on a WebGPU device walls keep their pack's plain colour.
 */

/** Whether the finish runs on a device: on WebGL2, the one device it is written for. */
export const facadeRuns = (device: pc.GraphicsDevice): boolean => device.isWebGPU !== true;

/**
 * The share of a rule's windows lit under a light: `stated`, the light's own share, where it states
 * one; else the rule's dusk share with the sun at or below its dusk elevation, its day share at or
 * above its day elevation, and smoothly between.
 */
export function litShareOf(rule: StylePackFacade, sunElevationDeg: number, stated: number | null = null): number {
  if (stated !== null) return stated;
  const dusk = rule.dusk_sun_mdeg / 1000;
  const day = rule.day_sun_mdeg / 1000;
  const t = Math.min(1, Math.max(0, (sunElevationDeg - dusk) / (day - dusk)));
  const smooth = t * t * (3 - 2 * t);
  return (rule.lit_dusk_permille + (rule.lit_day_permille - rule.lit_dusk_permille) * smooth) / 1000;
}

const DECLARATIONS = `
uniform vec4 exuFacadeFrame;   // xy the middle of the wall's building in the world (x, z); zw its half extents along x and z
uniform vec4 exuFacadeFloor;   // x the building's base height, y its storey height, z its whole storeys (0: none drawn), w the wall's thickness
uniform vec4 exuFacadePiece;   // xy the wall piece's own foot and top heights; z the building's salt; w the bays a room lights together
uniform vec4 exuFacadeWindow;  // x the least bay, y the window's width, z its height, w its sill's height over its floor
uniform vec4 exuFacadeTrim;    // x the least wall over a window, y the storeys kept clear, z the reveal's depth, w its shade
uniform vec4 exuFacadeSurface; // x the ledge's height, y its light, z the glass's darkening, w its gloss
uniform vec4 exuFacadeLight;   // x the share of rooms lit, y the lamps' strength, z the warm share, w a room's depth
uniform vec4 exuFacadeFade;    // xy bays a pixel where the far fade starts and ends; z the lamps' spread
uniform vec3 exuFacadeWarm;
uniform vec3 exuFacadeCool;
uniform vec3 exuFacadeDim;     // the light of a room with no lamp on, seen through its window
float exuFacadeGlassShare;
float exuFacadeShade;
vec3 exuFacadeLit;
uint exuFacadeMix(uint v) { v ^= v >> 16; v *= 0x7feb352du; v ^= v >> 15; v *= 0x846ca68bu; v ^= v >> 16; return v; }
float exuFacadeHash(ivec2 c, uint salt) { return float(exuFacadeMix(uint(c.x) * 73856093u ^ exuFacadeMix(uint(c.y) * 19349663u ^ salt))) * (1.0 / 4294967295.0); }
`;

const FACADE = `
void exuFacade() {
\texuFacadeGlassShare = 0.0;
\texuFacadeShade = 1.0;
\texuFacadeLit = vec3(0.0);
\tvec3 n = normalize(dVertexNormalW);
\tbool facesX = abs(n.x) > abs(n.z);
\t// Along the face from the building's corner and up from its base, metres; its bays fitted to it.
\tfloat lengthM = 2.0 * (facesX ? exuFacadeFrame.w : exuFacadeFrame.z);
\tfloat bays = floor(lengthM / max(exuFacadeWindow.x, 1.0e-3));
\tfloat bayM = lengthM / max(bays, 1.0);
\tfloat storeyM = max(exuFacadeFloor.y, 1.0e-3);
\tvec2 m = vec2((facesX ? vPositionW.z - exuFacadeFrame.y + exuFacadeFrame.w : vPositionW.x - exuFacadeFrame.x + exuFacadeFrame.z), vPositionW.y - exuFacadeFloor.x);
\tvec2 cell = m / vec2(bayM, storeyM);
\t// Derivatives before any branch: a pixel beside one that returned would read none.
\tvec2 fw = fwidth(cell);
\tvec2 fm = max(fwidth(m), vec2(1.0e-4));
\tif (exuFacadeFloor.z <= 0.0 || bays < 1.0 || abs(n.y) > 0.3) return;
\t// Only a face on its building's edge looking out of it: never a wall's inside, nor a door's jamb.
\tvec2 fromMiddle = vPositionW.xz - exuFacadeFrame.xy;
\tfloat reach = (facesX ? exuFacadeFrame.z : exuFacadeFrame.w) - exuFacadeFloor.w;
\tif ((facesX ? sign(n.x) * fromMiddle.x : sign(n.z) * fromMiddle.y) < reach) return;
\tivec2 ci = ivec2(floor(cell));
\tif (float(ci.y) < exuFacadeTrim.y || float(ci.y) >= exuFacadeFloor.z || ci.x < 0 || float(ci.x) >= bays) return;
\t// The window in its bay, metres from the bay's middle across and from the storey's floor up.
\tfloat halfW = 0.5 * exuFacadeWindow.y;
\tfloat sill = exuFacadeWindow.w;
\tfloat top = min(sill + exuFacadeWindow.z, storeyM - exuFacadeTrim.x);
\tfloat floorY = exuFacadeFloor.x + float(ci.y) * storeyM;
\t// A storey's window is drawn only on a piece standing over the whole of it, so none is cut by a lintel's foot.
\tif (top <= sill || floorY + sill - 0.5 * fm.y < exuFacadePiece.x || floorY + top + 0.5 * fm.y > exuFacadePiece.y) return;
\tvec2 p = vec2(m.x - (float(ci.x) + 0.5) * bayM, m.y - float(ci.y) * storeyM);
\tfloat far = smoothstep(exuFacadeFade.x, exuFacadeFade.y, max(fw.x, fw.y));
\tfloat inX = (1.0 - smoothstep(halfW - fm.x, halfW + fm.x, abs(p.x)));
\tfloat inY = smoothstep(sill - fm.y, sill + fm.y, p.y) * (1.0 - smoothstep(top - fm.y, top + fm.y, p.y));
\tfloat window = inX * inY;
\t// The reveal: the jamb and head (or the sill's top) the eye sees into, by how it looks into the wall.
\tvec3 v = normalize(vPositionW - view_position);
\tvec3 r = vec3(facesX ? v.z : v.x, v.y, max(dot(v, -n), 0.05));
\tfloat depth = exuFacadeTrim.z;
\tfloat jamb = min(depth * abs(r.x) / r.z, 2.0 * halfW);
\tfloat head = min(depth * max(r.y, 0.0) / r.z, top - sill);
\tfloat foot = min(depth * max(-r.y, 0.0) / r.z, top - sill);
\tfloat side = r.x > 0.0 ? smoothstep(halfW - jamb - fm.x, halfW - jamb + fm.x, p.x) : 1.0 - smoothstep(-halfW + jamb - fm.x, -halfW + jamb + fm.x, p.x);
\tfloat over = smoothstep(top - head - fm.y, top - head + fm.y, p.y);
\tfloat under = 1.0 - smoothstep(sill + foot - fm.y, sill + foot + fm.y, p.y);
\tfloat reveal = window * max(side, max(over, under));
\tfloat glass = window - reveal;
\t// The ledge under the window: a band as tall as it is, as wide as the window and a ledge each side.
\tfloat ledgeH = exuFacadeSurface.x;
\tfloat ledge = (1.0 - smoothstep(halfW + ledgeH - fm.x, halfW + ledgeH + fm.x, abs(p.x)))
\t\t* smoothstep(sill - ledgeH - fm.y, sill - ledgeH + fm.y, p.y) * (1.0 - smoothstep(sill - fm.y, sill + fm.y, p.y));
\tfloat shade = (1.0 - exuFacadeTrim.w * reveal) * (1.0 + exuFacadeSurface.y * ledge * step(1.0e-4, ledgeH));
\t// Who is home: rooms of the rule's bays on each storey of each face, lit by the share.
\tuint face = uint(facesX ? (n.x > 0.0 ? 1 : 2) : (n.z > 0.0 ? 3 : 4));
\tuint salt = uint(exuFacadePiece.z) * 8u + face;
\tivec2 room = ivec2(int(floor(float(ci.x) / max(exuFacadePiece.w, 1.0))), ci.y);
\tfloat lit = step(exuFacadeHash(room, salt), exuFacadeLight.x);
\tvec3 lamp = (exuFacadeHash(room, salt + 97u) < exuFacadeLight.z ? exuFacadeWarm : exuFacadeCool)
\t\t* (1.0 + exuFacadeFade.z * (2.0 * exuFacadeHash(room, salt + 193u) - 1.0));
\tfloat inside = 1.0;
#ifdef EXU_FACADE_ROOMS
\tif (far < 0.99) {
\t\t// The room behind the glass: where the view ray, entering the window, meets its back wall, a
\t\t// side wall, the floor or the ceiling, each lit by its own share of the room's lamp.
\t\tvec2 size = vec2(bayM, storeyM);
\t\tvec3 o = vec3(p.x + 0.5 * bayM, p.y, 0.0);
\t\tfloat roomDepth = exuFacadeLight.w;
\t\tvec3 t = vec3(r.x > 0.0 ? (size.x - o.x) / r.x : -o.x / min(r.x, -1.0e-4),
\t\t              r.y > 0.0 ? (size.y - o.y) / r.y : -o.y / min(r.y, -1.0e-4),
\t\t              roomDepth / r.z);
\t\tfloat th = min(t.x, min(t.y, t.z));
\t\tvec3 hit = o + r * th;
\t\tfloat back = step(t.z, min(t.x, t.y));
\t\tfloat sideHit = (1.0 - back) * step(t.x, t.y);
\t\tfloat floorHit = (1.0 - back) * (1.0 - sideHit) * step(r.y, 0.0);
\t\tfloat ceilingHit = (1.0 - back) * (1.0 - sideHit) * (1.0 - floorHit);
\t\tfloat deep = clamp(hit.z / roomDepth, 0.0, 1.0);
\t\tfloat surface = back * 0.7 + sideHit * (0.4 - 0.15 * deep) + floorHit * (0.18 + 0.1 * deep) + ceilingHit * (0.9 - 0.3 * deep);
\t\tinside = mix(surface * 1.6, 1.0, far);
\t}
#endif
\t// From afar, the storey's average: its share of glass, lit by the share of rooms.
\tfloat area = (2.0 * halfW * (top - sill)) / (bayM * storeyM);
\tvec3 meanLamp = mix(exuFacadeCool, exuFacadeWarm, exuFacadeLight.z);
\texuFacadeGlassShare = mix(glass, area, far);
\texuFacadeShade = mix(shade, 1.0, far);
\tvec3 near = glass * inside * (lit * lamp * exuFacadeLight.y + (1.0 - lit) * exuFacadeDim);
\tvec3 farAverage = area * (exuFacadeLight.x * meanLamp * exuFacadeLight.y + (1.0 - exuFacadeLight.x) * exuFacadeDim);
\texuFacadeLit = mix(near, farAverage, far);
}
`;

const ALBEDO = 'void getAlbedo() {';
const ALBEDO_BASE = 'void exuFacadeBase() {';
const EMISSION = 'void getEmission() {';
const EMISSION_BASE = 'void exuFacadeEmissionBase() {';
const GLOSS = 'void getGlossiness() {';
const GLOSS_BASE = 'void exuFacadeGlossBase() {';

/** The mark that says a colour chunk already carries the finish. */
const MARK = 'uniform vec4 exuFacadeFrame;';

const once = (chunk: string, name: string, what: string): void => {
  if (chunk.split(name).length !== 2) throw new TypeError(`a ${what} chunk the facade finish cannot be set into: it has no one ${what} function`);
};

/** A colour chunk with the facade set after its colour function, which is renamed and called first. */
export function withFacadeColour(chunk: string): string {
  if (chunk.includes(MARK)) return chunk;
  once(chunk, ALBEDO, 'colour');
  return `${chunk.replace(ALBEDO, ALBEDO_BASE)}${DECLARATIONS}${FACADE}
void getAlbedo() {
\texuFacadeBase();
\texuFacade();
\tdAlbedo *= exuFacadeShade * (1.0 - exuFacadeSurface.z * exuFacadeGlassShare);
}
`;
}

/** An emission chunk with the lit windows added after its own emission. */
export function withFacadeEmission(chunk: string): string {
  if (chunk.includes(EMISSION_BASE)) return chunk;
  once(chunk, EMISSION, 'emission');
  return `${chunk.replace(EMISSION, EMISSION_BASE)}
void getEmission() {
\texuFacadeEmissionBase();
\tdEmission += exuFacadeLit;
}
`;
}

/** A gloss chunk with the glass's gloss set over its own, where there is glass. */
export function withFacadeGloss(chunk: string): string {
  if (chunk.includes(GLOSS_BASE)) return chunk;
  once(chunk, GLOSS, 'gloss');
  return `${chunk.replace(GLOSS, GLOSS_BASE)}
void getGlossiness() {
\texuFacadeGlossBase();
\tdGlossiness = mix(dGlossiness, exuFacadeSurface.w, exuFacadeGlassShare);
}
`;
}

function wrap(device: pc.GraphicsDevice, material: pc.StandardMaterial, name: string, set: (chunk: string) => string): void {
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  const held = chunks.get(name) as string | undefined;
  const plain = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get(name) as string | undefined;
  if (held === undefined && plain === undefined) throw new TypeError(`the engine states no ${name} chunk to set the facade finish into`);
  chunks.set(name, set(held ?? plain!));
}

/** Every uniform a facade wall's instance states, by name, all zero on a material: no wall states a building. */
const UNIFORMS: Readonly<Record<string, number>> = {
  exuFacadeFrame: 4, exuFacadeFloor: 4, exuFacadePiece: 4, exuFacadeWindow: 4, exuFacadeTrim: 4,
  exuFacadeSurface: 4, exuFacadeLight: 4, exuFacadeFade: 4, exuFacadeWarm: 3, exuFacadeCool: 3, exuFacadeDim: 3,
};

/**
 * Set the facade finish into a wall's material, its windows drawn only on the instances that state
 * their building (`setFacadeWall`). `rooms` false leaves out the rooms behind windows (a lower render
 * budget level may), chosen when the material is made, never per frame. Setting it twice changes
 * nothing.
 */
export function applyFacadeFinish(device: pc.GraphicsDevice, material: pc.StandardMaterial, rooms = true): void {
  material.shaderChunksVersion = '2.8';
  wrap(device, material, 'diffusePS', withFacadeColour);
  wrap(device, material, 'emissivePS', withFacadeEmission);
  wrap(device, material, 'glossPS', withFacadeGloss);
  material.setDefine('EXU_FACADE_ROOMS', rooms);
  for (const [name, size] of Object.entries(UNIFORMS)) material.setParameter(name, new Array<number>(size).fill(0));
  material.update();
}

/** Whether a wall's material can wear the facade: an opaque standard material, so glazing never does. */
export function facadeWears(material: pc.Material): material is pc.StandardMaterial {
  return material instanceof pc.StandardMaterial && material.blendType === pc.BLEND_NONE;
}

/** Whether a material carries the facade finish. */
export function facadeApplied(material: pc.Material): boolean {
  return material instanceof pc.StandardMaterial && (material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined)?.includes(MARK) === true;
}

/** A slot as the facade reads it: its family, its building, its box in plan millimetres, and a building's storey height. */
export interface FacadeSlot {
  readonly identity: string;
  readonly family: string;
  readonly structure?: string;
  readonly positionMm: readonly number[];
  readonly boxMm: readonly number[];
  readonly yawQuarterTurns: number;
  readonly storeyHeightMm?: number;
}

/** A rectangle in plan millimetres: its middle (east, north) and its half extents. */
export interface PlanRect {
  readonly x: number;
  readonly y: number;
  readonly hx: number;
  readonly hy: number;
}

/** A building as its walls' windows read it: its rectangle in plan, its base and height, its salt, and its storey height where the drawing states one. */
export interface FacadeBuilding {
  readonly rect: PlanRect;
  readonly baseMm: number;
  readonly heightMm: number;
  readonly salt: number;
  readonly storeyMm?: number;
}

/** One facade wall: the way it faces out of its building in plan (east, north), its building, its own thickness, and its foot and top heights. */
export interface FacadeFront {
  readonly out: readonly [number, number];
  readonly building: FacadeBuilding;
  readonly thicknessMm: number;
  readonly footMm: number;
  readonly topMm: number;
}

/** How far past a wall's outer face another building is looked for: a wall against one is a party wall. */
const NEIGHBOUR_REACH_MM = 100;

/** A slot's rectangle in plan: its middle and its half extents, its box turned by its quarter turns. */
function planRect(slot: FacadeSlot): PlanRect {
  const odd = slot.yawQuarterTurns % 2 !== 0;
  return { x: slot.positionMm[0]!, y: slot.positionMm[1]!, hx: slot.boxMm[odd ? 1 : 0]! / 2, hy: slot.boxMm[odd ? 0 : 1]! / 2 };
}

/** A small whole number from a building's identity, so neighbouring buildings light different rooms. */
function saltOf(identity: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < identity.length; i += 1) h = Math.imul(h ^ identity.charCodeAt(i), 0x01000193) >>> 0;
  return h % 65_536;
}

/**
 * The building walls of a site that are its facades: a wall on its building's edge, within its own
 * thickness of the edge of the building's own slot, facing open ground. A wall between rooms, a wall
 * against another building and a wall whose building has no slot are none, so no lit window is ever
 * seen from inside a building. A piece over an opening (a lintel) is one, and draws a storey's window
 * only where it stands over the whole of it.
 */
export function facadeFronts(slots: readonly FacadeSlot[]): Map<string, FacadeFront> {
  const owners = new Set(slots.flatMap((slot) => (slot.structure === undefined ? [] : [slot.structure])));
  const buildings = new Map(slots.filter((slot) => owners.has(slot.identity)).map((slot): [string, FacadeBuilding] => [slot.identity, {
    rect: planRect(slot),
    baseMm: slot.positionMm[2] ?? 0,
    heightMm: slot.boxMm[2] ?? 0,
    salt: saltOf(slot.identity),
    ...(slot.storeyHeightMm === undefined ? {} : { storeyMm: slot.storeyHeightMm }),
  }]));
  const fronts = new Map<string, FacadeFront>();
  for (const slot of slots) {
    const building = slot.family === 'wall' && slot.structure !== undefined ? buildings.get(slot.structure) : undefined;
    if (building === undefined) continue;
    const wall = planRect(slot);
    const alongEast = wall.hx >= wall.hy;
    const thickness = 2 * Math.min(wall.hx, wall.hy);
    const offset = alongEast ? wall.y - building.rect.y : wall.x - building.rect.x;
    const half = alongEast ? building.rect.hy : building.rect.hx;
    if (offset === 0 || half - Math.abs(offset) > thickness) continue;
    const out: readonly [number, number] = alongEast ? [0, Math.sign(offset)] : [Math.sign(offset), 0];
    const reach = thickness / 2 + NEIGHBOUR_REACH_MM;
    const [px, py] = [wall.x + out[0] * reach, wall.y + out[1] * reach];
    const against = [...buildings].some(([identity, other]) => identity !== slot.structure
      && Math.abs(px - other.rect.x) < other.rect.hx && Math.abs(py - other.rect.y) < other.rect.hy);
    const footMm = slot.positionMm[2] ?? 0;
    if (!against) fronts.set(slot.identity, { out, building, thicknessMm: thickness, footMm, topMm: footMm + (slot.boxMm[2] ?? 0) });
  }
  return fronts;
}

const MIDDLE = new pc.Vec3();
const ALONG_EAST = new pc.Vec3();
const ALONG_NORTH = new pc.Vec3();
const UP = new pc.Vec3();

/**
 * State on a facade wall's own mesh instance its building, in the world under the site's root (plan
 * east is the root's x and plan north its -z), and its rule's figures lit at `litShare`, so walls of
 * every building and rule share their materials. Returns whether it stated any: a building no thicker
 * than its wall, or of no height, has no facade. The edge is tested along the world's x and z,
 * so a site's root turned other than by quarter turns about up would draw it only roughly; nothing
 * turns a site's root.
 */
export function setFacadeWall(instance: pc.MeshInstance, root: pc.GraphNode, front: FacadeFront, rule: StylePackFacade, litShare: number): boolean {
  const toWorld = root.getWorldTransform();
  const { building } = front;
  // Rows as near the rule's storey height as the building allows: each storey the drawing states, or
  // the building's whole height where it states none, holds a whole number of them, at least one.
  const unitMm = building.storeyMm ?? building.heightMm;
  const perUnit = Math.max(1, Math.round(unitMm / rule.storey_mm));
  const storeyMm = unitMm / perUnit;
  const storeys = unitMm > 0 ? Math.floor((building.heightMm * perUnit) / unitMm) : 0;
  toWorld.transformPoint(MIDDLE.set(building.rect.x / 1000, building.baseMm / 1000, -building.rect.y / 1000), MIDDLE);
  toWorld.transformVector(ALONG_EAST.set(building.rect.hx / 1000, 0, 0), ALONG_EAST);
  toWorld.transformVector(ALONG_NORTH.set(0, 0, -building.rect.hy / 1000), ALONG_NORTH);
  toWorld.transformVector(UP.set(0, 1, 0), UP);
  const halfX = Math.abs(ALONG_EAST.x) + Math.abs(ALONG_NORTH.x);
  const halfZ = Math.abs(ALONG_EAST.z) + Math.abs(ALONG_NORTH.z);
  const scale = UP.length();
  const thicknessM = (front.thicknessMm / 1000) * scale;
  if (storeys < 1 || halfX <= thicknessM || halfZ <= thicknessM) return false;
  const m = (mm: number): number => (mm / 1000) * scale;
  const footY = MIDDLE.y + m(front.footMm - building.baseMm);
  const topY = MIDDLE.y + m(front.topMm - building.baseMm);
  const stated: Record<string, readonly number[]> = {
    exuFacadeFrame: [MIDDLE.x, MIDDLE.z, halfX, halfZ],
    exuFacadeFloor: [MIDDLE.y, m(storeyMm), storeys, thicknessM],
    exuFacadePiece: [footY, topY, building.salt, rule.room_bays],
    exuFacadeWindow: [m(rule.bay_mm), m(rule.window_mm[0]), m(rule.window_mm[1]), m(rule.sill_mm)],
    exuFacadeTrim: [m(rule.head_mm), rule.clear_storeys, m(rule.reveal_mm), rule.reveal_shade_permille / 1000],
    exuFacadeSurface: [m(rule.ledge_mm), rule.ledge_light_permille / 1000, rule.glass_darkening_permille / 1000, rule.glass_gloss_permille / 1000],
    exuFacadeLight: [litShare, rule.light_permille / 1000, rule.warm_permille / 1000, m(rule.room_depth_mm)],
    exuFacadeFade: [rule.fade_from_millicells_per_px / 1000, rule.fade_to_millicells_per_px / 1000, rule.lamp_spread_permille / 1000, 0],
    exuFacadeWarm: linearRgb(rule.warm),
    exuFacadeCool: linearRgb(rule.cool),
    exuFacadeDim: linearRgb(rule.unlit),
  };
  for (const [name, data] of Object.entries(stated)) instance.setParameter(name, new Float32Array(data));
  return true;
}

/** Forget a wall's building and rule, as the facade is taken off it. */
export function clearFacadeWall(instance: pc.MeshInstance): void {
  for (const name of Object.keys(UNIFORMS)) instance.deleteParameter(name);
}

// The data view in a made town ([X] Data): one small card with one slider, from the world to its data. As it moves,
// the town's surfaces go dark and glowing points sampled from them take their place, each coloured by the kind of
// record it stands on, over the data view's dark ground; each thing the town's records name gets a thin box and a
// tag in the catalogs' words, and each person drawn here a tag with their name and, under it, the model that decides
// for them where one does. Nothing is kept or picked: closing the card puts every surface back as it was.
// The look is the product's data view style for a town seen from its own street (atlas-core's DATA_VIEW_STYLE_STREET,
// version 4: fine points that twinkle a little and never move, as many to the square pixel on every surface), drawn
// by the product's own parts: the point draw (data-view/points.ts) and the dark ground and the boxes
// (data-view/overlay.ts). Every surface goes to data, the land beyond the town as the land and the sky as the dark
// ground, and the world's fog and haze go into the ground with it. Its samples are taken for the eye
// (data-view-samples.mjs): near, middle and far sets (SETS), each taken again as the eye walks, a moving thing's all
// over it, and a surface the world draws later borrowed as it comes. A GPU that cannot draw every point at the page's
// frame rate draws a stable share of them, stepped by its measured frame time, never fewer than half. What the town's
// things are, their words and where a tag goes are data-view-things.mjs's; whether a wall stands between the eye and a
// tag is scene-sight.ts's.
//
// A town is seen from its own street, so its surfaces go dark rather than dissolve: each keeps standing where it is,
// in the ground's colour, and so hides what is behind it, its own points drawn over it (the style's pull brings each
// point that far toward the eye). Dissolved, as a district seen from above dissolves, every building's points would
// show through every other's.
import {
  DATA_VIEW_STYLE_STREET, REPRESENTATION_POINTS_PER_SUBJECT, dataViewKindColour, dataViewRgb,
  type DataViewHex, type DataViewStyle, type RepresentationSubject,
} from '../../../web/packages/atlas-core/src/index.ts';
import type { AtlasBinding } from '../../../web/packages/atlas-react/src/playcanvas/atlas-binding.ts';
import { DATA_VIEW_KEEP_UNIFORM, createDataViewPoints } from '../../../web/packages/atlas-react/src/playcanvas/data-view/points.ts';
import { createDataViewSkinnedGroup, type DataViewSkinnedGroup, type DataViewSkinnedPoints } from '../../../web/packages/atlas-react/src/playcanvas/data-view/skinned-points.ts';
import { DataViewOverlay } from '../../../web/packages/atlas-react/src/playcanvas/data-view/overlay.ts';
import type { LoadedGeneratedTile } from '../../../web/packages/atlas-react/src/playcanvas/generated-tile/tile-runtime.ts';
import type { staticMeshRepresentation } from '../../../web/packages/atlas-react/src/playcanvas/representation-binding.ts';
import type { RepresentationPointAllocation, RepresentationReport } from '../../../web/packages/atlas-react/src/playcanvas/representation-runtime.ts';
import { SPLIT, surfaceIndex, surfaceSamples, trianglesNear } from './data-view-samples.mjs';
import { bigEnough, keepStep, personLines, placeTags, pointBoxes, pointKinds, streetLine, surfaceOf, tagAnchors, townThings, walkerBoxes } from './data-view-things.mjs';
import { sceneHit, sceneSight } from './scene-sight.ts';
import { DATA_WORDS } from './world-words.mjs';
import './world-data-view.css';

/**
 * The sets a town's surfaces are drawn from, by distance from the eye: each from `from` up to `to` metres, taken
 * again each time the eye has walked `step` metres from where it was taken, for an eye up to `slack` metres nearer
 * still, so a set holds until the next is ready, `slice` triangles a job (the nearer, the more samples a triangle). Sets are the same samples where they meet (data-view-samples.mjs),
 * so one hands over to the next, and a set to the one taken after it, without a seam.
 */
const SETS = Object.freeze([
  Object.freeze({ from: 0, to: 8, step: 0.3, slack: 0.5, slice: 250 }),
  Object.freeze({ from: 8, to: 32, step: 1.3, slack: 2, slice: 1500 }),
  Object.freeze({ from: 32, to: Infinity, step: 6, slack: 8, slice: 5000 }),
]);
/** A moving thing may come anywhere, so it is sampled all over for an eye this many metres away, by its surface. */
const MOVER_NEAREST: Readonly<Record<string, number>> = Object.freeze({ vehicle: 6, person: 12, object: 3 });
/**
 * A walker drawn near is drawn by its bones (skinned-points.ts): its body, outfit, shoes and hair, every PERSON_STRIDE-th
 * vertex a point, a fifth as wide as the town's and never wider than PERSON_MAX_PIXELS.
 */
const PERSON_POINTS = /character:(skin|outfit|shoes|hair)\//u;
const PERSON_STRIDE = 3;
const PERSON_MAX_PIXELS = 2.5;
/** How often the world layer is read again for surfaces drawn since the view opened, ms. */
const LATE_MS = 1000;
/** The most of a frame the sampling takes, ms: the rest waits for the next frame. */
const SAMPLE_MS = 5;
/** How many hidden draws are let go of in a frame. */
const RETIRE_PER_FRAME = 12;
/** The least share of the points a GPU's frame time steps them down to. */
const KEEP_FLOOR = 0.5;
/**
 * From here on the slider the borrowed surfaces cast no shadows: darkened past four fifths, no shadow on them shows,
 * and the shadow passes are most of what the points would otherwise cost a frame. From here on too a walker or a
 * vehicle is its points alone: its darkened surface is drawn no more, so one beside the eye is a figure of points,
 * never a dark shape over the town.
 */
const SHADOWS_UNTIL = 0.8;
/** How bright a walker's points are beside the town's: their vertices crowd at the face and hands. */
const PERSON_GAIN = 0.45;
/**
 * Where on the slider the boxes come in: once the town has mostly gone dark. The overlay draws a box at the style's one
 * opacity, so a box shown near the world end would stand over the town as it still looks.
 */
const BOXES_FROM = 0.35;
/** How long the slider glides between the world and its data when X is pressed, ms (none with reduced motion). */
const GLIDE_MS = 1400;
/** How far a tag is shown, metres from the eye: a thing's middle, a person's head, a street's middle line. */
const REACH = Object.freeze({ thing: 70, person: 45, street: 60 });
/** How often a tag's sight line is asked again, ms, and how many are asked in one frame. */
const SIGHT_MS = 250;
const SIGHTS_PER_FRAME = 12;
/** How far short of its anchor a sight line stops, metres: a face's own wall, a person's own body. */
const OWN = Object.freeze({ face: 0.8, top: 0.6, person: 0.5, line: 0.5 });
/** How often a person's name and model are read again for their tag, ms: a model can change while the view shows. */
const WORDS_MS = 1000;

type Vec = readonly [number, number, number];
/** A drawn mesh instance, as the sampled surface takes it (the engine's own type, named where atlas-react names it). */
type MeshInstance = Parameters<typeof staticMeshRepresentation>[1];
type Thing = { readonly id: string; readonly kind: string; readonly words: string; readonly min: Vec; readonly max: Vec; readonly hang: 'face' | 'top' | 'line' };
type Surface = 'wall' | 'road' | 'path' | 'kerb' | 'plant' | 'furniture' | 'ground' | 'vehicle' | 'backdrop' | 'sky' | 'person' | 'object';
type Material = MeshInstance['material'];
/** A colour as a standard material holds it. */
interface Colour { r: number; g: number; b: number; set(r: number, g: number, b: number): unknown }
/** A standard material, as the darkening reads and writes it. */
interface Darkenable {
  clone(): Darkenable; update(): void; destroy(): void; diffuse: Colour; emissive: Colour; specular?: Colour; specularityFactor?: number;
  reflectivity?: number; useMetalness?: boolean; useMetalnessSpecularColor?: boolean;
}
/** A material's dark copy and the colours, shine and reflection it is darkened from. */
interface Dark {
  readonly copy: Darkenable; readonly diffuse: Vec; readonly emissive: Vec; readonly specular: Vec | null; readonly specularity: number | null;
  readonly reflectivity: number | null; shaped: boolean;
}
/** A standard material's own colour and value fields and its parameters, which easing writes without a new shader. */
interface Uniforms {
  _diffuse: Colour; _emissive: Colour; _specular?: Colour; _specularityFactor?: number; _reflectivity?: number;
  setParameter(name: string, value: number | number[]): void;
}
/** A surface's triangles as read once: local positions and indices, and its node's world matrix then. */
interface Shape { readonly positions: Float32Array; readonly indices: Uint32Array; readonly matrix: Float32Array }
/**
 * A borrowed surface: its dark copy, its triangles and where they are, and its points, one list of draws for each set
 * (SETS). A moving thing (`mover`) has one list, its samples all over it, and no index.
 */
interface Held {
  readonly instance: MeshInstance; original: Material; dark: Dark; readonly surface: Surface;
  readonly key: number; readonly mover: boolean; readonly shape: Shape; readonly index: ReturnType<typeof surfaceIndex> | null;
  readonly drawn: RepresentationPointAllocation[][]; shown: boolean; readonly castShadow: boolean;
}
interface Planned { readonly instance: MeshInstance; readonly surface: Surface; readonly key: number; readonly mover: boolean; readonly away: number; readonly skinned: boolean }
/** A walker's skinned surface: its dark copy, and its points drawn by its bones where it has any. */
interface Walker { readonly instance: MeshInstance; readonly original: Material; readonly dark: Dark; readonly points: DataViewSkinnedPoints | null; shown: boolean; readonly castShadow: boolean }
/** A set on its way: the eye it is taken for, the surfaces it is taken over, and what each has made of it so far. */
interface Taking { readonly at: Vec; readonly members: readonly Held[]; readonly made: Map<Held, RepresentationPointAllocation[]> }

const darkenable = (material: unknown): material is Darkenable => {
  const one = material as Partial<Darkenable> | null;
  return one !== null && typeof one === 'object' && typeof one.clone === 'function' && typeof one.update === 'function'
    && typeof one.diffuse?.set === 'function' && typeof one.emissive?.set === 'function';
};
const rgb = (colour: Colour): Vec => [colour.r, colour.g, colour.b];

/** Who lives here, as the workspace knows them: where each is drawn, and how each is called and who decides for them. */
export interface DataViewPeople {
  /** Everyone drawn now: their society id and the point just over their head, render space; empty where nobody lives. */
  everyone(): readonly { readonly id: string; readonly head: { readonly x: number; readonly y: number; readonly z: number } }[];
  /** How they are called, and the model that decides for them in the look tag's words, or null where none does. */
  words(id: string): { readonly name: string; readonly model: string | null };
}

export interface DataView {
  /** Whether the data view works in this world: a made town's tiles are drawn here. */
  readonly works: boolean;
  /** Whether its card shows. */
  readonly shown: boolean;
  /** Opens the card and glides to the data, or glides back to the world and closes it. */
  toggle(): void;
  /** Closes the card if it shows, gliding back to the world; true when it showed (Esc closes it before anything else). */
  close(): boolean;
  /** Called every frame by the world view. */
  frame(now: number): void;
  dispose(): void;
}

/** The town's tile as the page loaded it, or null in a world drawn another way. */
function townTile(binding: AtlasBinding): LoadedGeneratedTile | null {
  const ground = binding.worldKind?.ground;
  if (ground?.form !== 'generated-tile') return null;
  const tile = ground.tile as Partial<LoadedGeneratedTile>;
  return typeof tile.pick === 'function' && Array.isArray(tile.ranges) && Array.isArray(tile.header?.records) ? tile as LoadedGeneratedTile : null;
}

/**
 * Each tile of the town with its records, and its drawn ranges where the page holds them: the tile's own, and each
 * neighbour a ring of picks around the eye meets (a neighbour's header comes back only with a pick that meets it).
 */
function townTiles(tile: LoadedGeneratedTile, eye: Vec): { records: readonly unknown[]; ranges: readonly unknown[] }[] {
  const tiles = new Map<string, { records: readonly unknown[]; ranges: readonly unknown[] }>([[tile.name, { records: tile.header.records, ranges: tile.ranges }]]);
  for (let pitch = -40; pitch <= 20; pitch += 10) {
    for (let yaw = 0; yaw < 360; yaw += 3) {
      const p = pitch * Math.PI / 180, y = yaw * Math.PI / 180;
      const hit = tile.pick(eye, [Math.cos(p) * Math.sin(y), Math.sin(p), Math.cos(p) * Math.cos(y)]);
      if (hit !== null && !tiles.has(hit.tile)) tiles.set(hit.tile, { records: hit.header.records, ranges: [] });
    }
  }
  return [...tiles.values()];
}

/** A drawn surface only the data view borrows, never a subject of the panel or a pick. */
const surfaceSubject = (name: string): RepresentationSubject => Object.freeze({
  subjectId: `town-surface:${name}`, subjectKind: 'geometry-group', sceneId: null, frameId: 'town', origin: 'generated',
  sourceRefs: Object.freeze([]), availability: 'available', rendered: true, points: 'mesh-vertices', compatibleBlend: true,
  bounds: null, label: null, dataAvailable: false, unavailableReason: null,
});

/** One of the town's things, boxed by the data view's overlay. */
const thingSubject = (thing: Thing): RepresentationSubject => Object.freeze({
  subjectId: thing.id, subjectKind: 'object', sceneId: null, frameId: 'town', origin: 'generated',
  sourceRefs: Object.freeze([]), availability: 'available', rendered: true, points: null, compatibleBlend: false,
  bounds: Object.freeze({ frameId: 'town', units: 'metres', origin: 'generated', basis: 'generated-extent', min: thing.min, max: thing.max }),
  label: thing.words, dataAvailable: true, unavailableReason: null,
});

/** A box's eight corners in the overlay's order: x outermost, then y, then z. */
function corners(min: Vec, max: Vec): readonly (readonly [number, number, number])[] {
  const out: (readonly [number, number, number])[] = [];
  for (const x of [min[0], max[0]]) for (const y of [min[1], max[1]]) for (const z of [min[2], max[2]]) out.push([x, y, z]);
  return out;
}

const smooth = (t: number): number => { const k = Math.min(1, Math.max(0, t)); return k * k * (3 - 2 * k); };

export function mountDataView({ host, binding, people = null, onOpen = () => {}, style = DATA_VIEW_STYLE_STREET }: {
  readonly host: HTMLElement;
  readonly binding: AtlasBinding;
  /** Who lives here, or null where nobody does. */
  readonly people?: DataViewPeople | null;
  /** The card opened: the keys card and any other corner card give way. */
  readonly onOpen?: () => void;
  readonly style?: DataViewStyle;
}): DataView {
  const tile = townTile(binding);
  const colourOf = (kind: string): DataViewHex => dataViewKindColour(style, kind) ?? style.boxes.colour;

  // ---------- The card: X and its word, and the one slider from the world to its data ----------
  const card = document.createElement('div');
  card.className = 'wu-glass-thin wu-data-card';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', DATA_WORDS.title);
  card.hidden = true;
  const head = document.createElement('div');
  head.className = 'wu-data-head';
  const cap = document.createElement('span');
  cap.className = 'wu-key wu-small';
  cap.textContent = 'X';
  cap.setAttribute('aria-hidden', 'true');
  const title = document.createElement('span');
  title.textContent = DATA_WORDS.title;
  head.append(cap, title);
  const range = document.createElement('div');
  range.className = 'wu-data-range';
  const from = document.createElement('span');
  from.textContent = DATA_WORDS.world;
  const slider = document.createElement('input');
  slider.type = 'range'; slider.min = '0'; slider.max = '1000'; slider.step = '1'; slider.value = '0';
  slider.setAttribute('aria-label', DATA_WORDS.range);
  const to = document.createElement('span');
  to.textContent = DATA_WORDS.data;
  range.append(from, slider, to);
  card.append(head, range);
  const tagLayer = document.createElement('div');
  tagLayer.className = 'wu-data-tags';
  tagLayer.setAttribute('aria-hidden', 'true');
  // The tags' colours are the style's own: its text, and its ground at its opacity.
  const [gr, gg, gb] = [1, 3, 5].map((at) => Number.parseInt(style.tags.backgroundColour.slice(at, at + 2), 16));
  tagLayer.style.setProperty('--data-text', style.tags.textColour);
  tagLayer.style.setProperty('--data-ground', `rgba(${gr}, ${gg}, ${gb}, ${style.tags.backgroundOpacity})`);
  host.append(tagLayer, card);

  // ---------- State: where the slider stands, where it is going, what is drawn ----------
  let mix = 0, shownMix = -1, target = 0, glide: { from: number; to: number; start: number } | null = null;
  let held: Held[] = [], walkers: Walker[] = [], allocated = 0;
  // Every walker's points, drawn by one material, and the dark copies walkers and vehicles wear (drawn no more past
  // SHADOWS_UNTIL).
  let walkerPoints: DataViewSkinnedGroup | null = null;
  const figures = new Set<Dark>();
  // Sampling work, one queue for each set, the nearest first: each job one surface's read or one set of its samples.
  let queues: (() => void)[][] = SETS.map(() => []);
  // Draws handed over and hidden, let go of a few a frame.
  let retired: RepresentationPointAllocation[] = [];
  // Where the view opened (its triangles are split for there, once), the eye each set was taken for, each set on its
  // way, every mesh already looked at, and when the world layer was last read again for new ones.
  let opened: Vec | null = null, lateAt = -Infinity;
  let takenAt: (Vec | null)[] = SETS.map(() => null), taking: (Taking | null)[] = SETS.map(() => null);
  const known = new Set<MeshInstance>();
  // Where the town's own land lies, each chunk's (min x, min z, max x, max z, top): the land's backdrop under it is never seen.
  let land: [number, number, number, number, number][] = [];
  // The GPU's share of the points (every data view draw's one keep value) and the frame times it is stepped by.
  let keep = 1, downAt = -Infinity, stepAt = -Infinity, lastFrame: number | null = null;
  let tried: { keep: number; slow: number } | null = null, heldUntil = -Infinity;
  const intervals: number[] = [];
  const setKeep = (share: number): void => { keep = share; binding.device.scope.resolve(DATA_VIEW_KEEP_UNIFORM).setValue(share); };
  let things: readonly Thing[] = [], near: readonly Thing[] = [], thingsAt = -Infinity;
  let kinds: ReturnType<typeof pointKinds> | null = null;
  let overlay: DataViewOverlay | null = null;
  let sight: { face: ReturnType<typeof sceneSight>; top: ReturnType<typeof sceneSight>; person: ReturnType<typeof sceneSight>; line: ReturnType<typeof sceneSight> } | null = null;
  const seen = new Map<string, { seen: boolean; at: number }>();
  const tags = new Map<string, HTMLDivElement>();
  const reduced = (): boolean => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const eye = (): Vec => { const at = binding.camera.getPosition(); return [at.x, at.y, at.z]; };
  const apart = (a: Vec, b: Vec): number => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  /** Each borrowed material's dark copy, one for every surface that wears it. */
  const darks = new Map<Material, Dark>();
  const ground = dataViewRgb(style.ground.colour);
  // The world's haze and its fog, eased into the ground with the slider: what each was, and what each was last given.
  const linear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const groundLinear = ground.map(linear) as unknown as Vec;
  let fogFrom: Vec | null = null, fogSet: Vec | null = null, hazeFrom: number | null = null, hazeSet: number | null = null;

  /** A material's dark copy, made once: the same material, its colours to be eased toward the ground's. */
  function darkOf(material: Material): { dark: Dark; made: boolean } | null {
    const held = darks.get(material);
    if (held !== undefined) return { dark: held, made: false };
    if (!darkenable(material)) return null;
    const copy = material.clone();
    // A surface lit by the metalness workflow keeps a dielectric's own shine whatever its specular colour says; its
    // copy takes that shine as a white specular colour it can ease out (the same look until it is eased).
    const shine = material.useMetalness === true && material.useMetalnessSpecularColor !== true && copy.specular !== undefined;
    if (shine) copy.useMetalnessSpecularColor = true;
    const dark: Dark = {
      copy, diffuse: rgb(material.diffuse), emissive: rgb(material.emissive),
      specular: shine ? [1, 1, 1] : material.specular ? rgb(material.specular) : null,
      specularity: shine ? 1 : typeof material.specularityFactor === 'number' ? material.specularityFactor : null,
      reflectivity: typeof material.reflectivity === 'number' ? material.reflectivity : null, shaped: false,
    };
    darks.set(material, dark);
    return { dark, made: true };
  }

  /**
   * Eases one dark copy toward the ground: its own colour, shine and reflection out by `weight`, the ground's colour
   * in. The engine takes reading a material's colour as a change to its shader, so this is done only as the slider
   * moves, and once for a copy made since.
   */
  function tone(dark: Dark, weight: number): void {
    const keep = 1 - weight;
    const diffuse: Vec = [dark.diffuse[0] * keep, dark.diffuse[1] * keep, dark.diffuse[2] * keep];
    const emissive: Vec = [dark.emissive[0] * keep + ground[0] * weight, dark.emissive[1] * keep + ground[1] * weight, dark.emissive[2] * keep + ground[2] * weight];
    const specular: Vec | null = dark.specular === null ? null : [dark.specular[0] * keep, dark.specular[1] * keep, dark.specular[2] * keep];
    if (!dark.shaped) {
      // The first easing goes through the engine, from a hair past the world end, so the copy's shader is the one every
      // later easing needs (a shine and a reflection that can be eased); the copy is worn only past the world end.
      const shape = Math.max(weight, 0.001), held = 1 - shape;
      dark.copy.diffuse.set(dark.diffuse[0] * held, dark.diffuse[1] * held, dark.diffuse[2] * held);
      dark.copy.emissive.set(emissive[0], emissive[1], emissive[2]);
      if (dark.specular !== null && dark.copy.specular) dark.copy.specular.set(dark.specular[0] * held, dark.specular[1] * held, dark.specular[2] * held);
      if (dark.specularity !== null) dark.copy.specularityFactor = dark.specularity * held;
      if (dark.reflectivity !== null) dark.copy.reflectivity = dark.reflectivity * held;
      dark.copy.update();
      dark.shaped = true;
      if (shape === weight) return;
    }
    // Every later easing goes straight into the copy's own fields and its uniforms (linear, as the engine writes them),
    // so the engine never picks a shader again for the meshes that wear it.
    const own = dark.copy as unknown as Uniforms;
    own._diffuse.set(diffuse[0], diffuse[1], diffuse[2]);
    own._emissive.set(emissive[0], emissive[1], emissive[2]);
    own.setParameter('material_diffuse', diffuse.map(linear));
    own.setParameter('material_emissive', emissive.map(linear));
    if (specular !== null && own._specular) {
      own._specular.set(specular[0], specular[1], specular[2]);
      own.setParameter('material_specular', specular.map(linear));
    }
    if (dark.specularity !== null) { own._specularityFactor = dark.specularity * keep; own.setParameter('material_specularityFactor', dark.specularity * keep); }
    if (dark.reflectivity !== null) { own._reflectivity = dark.reflectivity * keep; own.setParameter('material_reflectivity', dark.reflectivity * keep); }
  }

  /**
   * Eases every dark copy toward the ground by `weight`, and dresses every borrowed surface in its copy, or its own,
   * casting its shadow only short of SHADOWS_UNTIL.
   */
  function darken(weight: number): void {
    for (const dark of darks.values()) tone(dark, weight);
    for (const one of [...held, ...walkers]) {
      one.instance.material = (weight > 0 ? one.dark.copy : one.original) as Material;
      one.instance.castShadow = one.castShadow && weight < SHADOWS_UNTIL;
    }
    for (const dark of figures) vanish(dark, weight >= SHADOWS_UNTIL);
  }

  /** A walker's or a vehicle's dark copy drawn, or drawn no more (neither colour nor depth): its points alone stand for it. */
  function vanish(dark: Dark, gone: boolean): void {
    const copy = dark.copy as Darkenable & { redWrite?: boolean; greenWrite?: boolean; blueWrite?: boolean; alphaWrite?: boolean; depthWrite?: boolean };
    if (copy.redWrite === !gone) return;
    copy.redWrite = copy.greenWrite = copy.blueWrite = copy.alphaWrite = !gone;
    copy.depthWrite = !gone;
    copy.update();
  }

  /** Dresses a surface borrowed since the slider last moved: its copy eased as the others are, if it is new. */
  function dress(instance: MeshInstance, original: Material, dark: Dark, made: boolean, castShadow: boolean): void {
    const weight = shownMix < 0 ? mix : shownMix;
    if (made) tone(dark, weight);
    instance.material = (weight > 0 ? dark.copy : original) as Material;
    instance.castShadow = castShadow && weight < SHADOWS_UNTIL;
  }

  /**
   * Eases the world's air into the ground by `weight`: its fog's colour toward the ground's, and its haze (a town's
   * aerial haze, aerial-haze.ts) thinned to none, each from whatever the world last gave it.
   */
  function air(weight: number): void {
    const colour = binding.app.scene.fog.color;
    const now: Vec = [colour.r, colour.g, colour.b];
    if (fogFrom === null || (fogSet !== null && now.some((value, at) => Math.abs(value - fogSet![at]!) > 1e-6))) fogFrom = now;
    const from = fogFrom;
    fogSet = [0, 1, 2].map((at) => from[at]! * (1 - weight) + groundLinear[at]! * weight) as unknown as Vec;
    colour.set(fogSet[0], fogSet[1], fogSet[2]);
    const haze = binding.device.scope.resolve('exuHaze');
    const value = haze.value as number[] | Float32Array | null | undefined;
    if (value === null || value === undefined || value.length < 4) return;
    if (hazeFrom === null || (hazeSet !== null && Math.abs(value[3]! - hazeSet) > 1e-6)) hazeFrom = value[3]!;
    hazeSet = hazeFrom * (1 - weight);
    haze.setValue([value[0]!, value[1]!, value[2]!, hazeSet]);
  }

  /** Gives the world its fog and haze back as they were. */
  function airBack(): void {
    if (fogFrom !== null) binding.app.scene.fog.color.set(fogFrom[0], fogFrom[1], fogFrom[2]);
    const haze = binding.device.scope.resolve('exuHaze');
    const value = haze.value as number[] | Float32Array | null | undefined;
    if (hazeFrom !== null && value !== null && value !== undefined && value.length >= 4) haze.setValue([value[0]!, value[1]!, value[2]!, hazeFrom]);
    fogFrom = null; fogSet = null; hazeFrom = null; hazeSet = null;
  }

  /** The camera's pixels to a radian on the drawing buffer, as the point shader counts them. */
  const pixels = (): number => 0.5 * binding.device.height * (binding.camera.camera?.projectionMatrix.data[5] ?? 1);

  /** What the world layer draws that the data view has not yet looked at and can borrow, nearest the eye first. */
  function plan(at: Vec): Planned[] {
    const world = binding.app.scene.layers.getLayerByName('World');
    const found: Planned[] = [];
    for (const instance of world?.meshInstances ?? []) {
      // The data view's own draws (its points, a walker's points, its ground) are never borrowed.
      if (known.has(instance) || (instance.node?.name ?? '').startsWith('data-view') || (instance.material?.name ?? '').startsWith('data-view')) continue;
      const surface = surfaceOf(instance.material?.name ?? '', instance.node?.name ?? '') as Surface;
      // A walker drawn from afar is shown and hidden as they come and go; anything else is looked at once it is drawn.
      if (!instance.visible && surface !== 'person') continue;
      known.add(instance);
      if (instance.instancingData || !darkenable(instance.material)) continue;
      const skinned = Boolean(instance.skinInstance);
      const mover = surface === 'vehicle' || surface === 'person' || surface === 'object';
      const c = instance.aabb.center, h = instance.aabb.halfExtents;
      if (surface === 'ground' && (instance.node?.name ?? '').startsWith('site-land:chunk')) land.push([c.x - h.x, c.z - h.z, c.x + h.x, c.z + h.z, c.y + h.y]);
      found.push({ instance, surface, key: known.size, mover, skinned, away: Math.max(0, Math.hypot(c.x - at[0], c.y - at[1], c.z - at[2]) - Math.hypot(h.x, h.y, h.z)) });
    }
    return found.sort((a, b) => a.away - b.away);
  }

  /** Reads one surface and borrows it: its dark copy, its triangles once, and where they are for the sets. */
  function prepare({ instance, surface, key, mover }: Planned): Held | null {
    const original = instance.material;
    const copy = darkOf(original);
    if (copy === null) return null;
    const { dark, made } = copy;
    const positions: number[] = [], indices: number[] = [];
    instance.mesh.getPositions(positions);
    instance.mesh.getIndices(indices);
    const shape: Shape = { positions: new Float32Array(positions), indices: new Uint32Array(indices), matrix: Float32Array.from(instance.node.getWorldTransform().data) };
    const one: Held = {
      instance, original, dark, surface, key, mover, shape, index: mover || surface === 'sky' ? null : surfaceIndex(shape),
      drawn: SETS.map(() => []), shown: true, castShadow: instance.castShadow,
    };
    held.push(one);
    // A walker drawn from afar, or a vehicle: its points alone near full Data.
    const figure = surface === 'person' || surface === 'vehicle';
    if (figure) figures.add(dark);
    dress(instance, original, dark, made, one.castShadow);
    if (figure) vanish(dark, (shownMix < 0 ? mix : shownMix) >= SHADOWS_UNTIL);
    return one;
  }

  /** Borrows a walker's skinned surface: its dark copy, and its body, outfit, shoes and hair as points. */
  function prepareWalker({ instance }: Planned): void {
    const original = instance.material;
    const copy = darkOf(original);
    const layer = binding.app.scene.layers.getLayerByName('World');
    if (copy === null || !layer) return;
    const { dark, made } = copy;
    walkerPoints ??= createDataViewSkinnedGroup({
      app: binding.app, device: binding.device, layer, colour: style.boxes.selectedColour, style, pixels: pixels(),
      stride: PERSON_STRIDE, sizeMetres: style.points.sizeMetres / 5, maxPixels: PERSON_MAX_PIXELS, gain: PERSON_GAIN,
    });
    walkerPoints.setWeight(mix);
    const points: DataViewSkinnedPoints | null = PERSON_POINTS.test(original?.name ?? '') ? walkerPoints.add(instance) : null;
    points?.setShown(instance.visible);
    walkers.push({ instance, original, dark, points, shown: instance.visible, castShadow: instance.castShadow });
    figures.add(dark);
    dress(instance, original, dark, made, instance.castShadow);
    vanish(dark, (shownMix < 0 ? mix : shownMix) >= SHADOWS_UNTIL);
  }

  /** One surface's samples for an eye: a set's (by its index in SETS), or a moving thing's all over it. */
  function samplesOf(one: Held, at: Vec, set: number, triangles: readonly number[] | null): Map<string, { positions: number[]; normals: number[]; densities: number[] }> {
    const screen = style.points.screen;
    if (screen === undefined || kinds === null || one.surface === 'sky') return new Map();
    const shared = { at, pixels: pixels(), density: screen.density, facingFloor: screen.facingFloor, cone: Math.cos((screen.coneDegrees * Math.PI) / 180) };
    const { from, to, slack } = SETS[set]!;
    const look = one.mover ? { ...shared, slack: 0, nearest: MOVER_NEAREST[one.surface] ?? 3, within: Infinity, fixed: true }
      : { ...shared, slack, nearest: Math.max(screen.nearestMetres, from), within: to + slack };
    // A moving thing is read where it stands now.
    const matrix = one.mover ? one.instance.node.getWorldTransform().data : one.shape.matrix;
    const table = kinds, under = land;
    const hidden = one.surface === 'backdrop' && under.length > 0
      ? (x: number, y: number, z: number) => under.some((chunk) => x > chunk[0] && x < chunk[2] && z > chunk[1] && z < chunk[3] && y < chunk[4]) : null;
    return surfaceSamples({ ...one.shape, matrix, key: one.key, hidden, kind: (x: number, y: number, z: number) => table.kindAt(one.surface, x, y, z) ?? 'object' },
      look, { at: opened ?? at, ...SPLIT }, triangles).groups;
  }

  /** One draw for each kind of record a surface's samples stand on, drawn from `reach[0]` up to `reach[1]` metres. */
  function allocate(one: Held, groups: ReturnType<typeof samplesOf>, reach: readonly [number, number], weight: number): RepresentationPointAllocation[] {
    const out: RepresentationPointAllocation[] = [];
    for (const [kind, group] of groups) {
      const allocation = createDataViewPoints({
        device: binding.device, node: one.instance.node, positions: new Float32Array(group.positions), style, subjectId: `town:${kind}`,
        samples: { normals: new Float32Array(group.normals), densities: new Float32Array(group.densities), reach },
      });
      if (allocation === null) continue;
      allocation.setLook?.({ colour: colourOf(kind), treatment: 'points', gain: 1 });
      allocation.setWeight(weight);
      out.push(allocation);
    }
    return out;
  }

  const countOf = (list: readonly RepresentationPointAllocation[]): number => list.reduce((sum, one) => sum + one.pointCount, 0);
  const reachOf = (set: number): readonly [number, number] => [SETS[set]!.from, SETS[set]!.to];

  /**
   * Puts `made` in place of a surface's draws of one set, at the weight it shows at; the draws it replaces are hidden
   * at once and let go of a few a frame after (`retired`), so a set handed over costs no frame its whole teardown.
   */
  function replace(one: Held, set: number, made: RepresentationPointAllocation[]): void {
    allocated += countOf(made) - countOf(one.drawn[set]!);
    for (const allocation of one.drawn[set]!) { allocation.setWeight(0); retired.push(allocation); }
    one.drawn[set] = made;
    for (const allocation of made) allocation.setWeight(one.shown ? mix : 0);
  }

  /**
   * Queues one surface's samples for a set as jobs of the set's slice of triangles each (every triangle when `triangles` is null),
   * and hands them, all taken, to `done`; `live` says whether they are still wanted.
   */
  function sliced(one: Held, at: Vec, set: number, triangles: readonly number[] | null, live: () => boolean, done: (groups: ReturnType<typeof samplesOf>) => void): void {
    const count = triangles?.length ?? Math.floor((one.shape.indices.length > 0 ? one.shape.indices.length : one.shape.positions.length / 3) / 3);
    const groups: ReturnType<typeof samplesOf> = new Map();
    const { slice: size } = SETS[set]!;
    for (let from = 0; from < count; from += size) {
      const last = from + size >= count;
      queues[set]!.push(() => {
        if (!live() || one.instance.mesh === null) return;
        const slice = triangles === null ? Array.from({ length: Math.min(size, count - from) }, (_, at) => from + at) : triangles.slice(from, from + size);
        for (const [kind, group] of samplesOf(one, at, set, slice)) {
          const into = groups.get(kind);
          if (into === undefined) groups.set(kind, group);
          else groups.set(kind, { positions: into.positions.concat(group.positions), normals: into.normals.concat(group.normals), densities: into.densities.concat(group.densities) });
        }
        if (last) done(groups);
      });
    }
  }

  /**
   * A set taken for `at`: each surface it reaches jobs of its queue, drawn by none until all are made, then in place
   * of the set before it at once. A moving thing has no sets; it is sampled once, all over (`sampleMover`).
   */
  function takeSet(set: number, at: Vec): void {
    const { to, slack } = SETS[set]!;
    const members = held.filter((one) => one.index !== null);
    const next: Taking = { at, members, made: new Map() };
    taking[set] = next;
    for (const one of members) {
      const triangles = to === Infinity ? null : trianglesNear(one.index!, at, to + slack);
      if (triangles !== null && triangles.length === 0) continue;
      sliced(one, at, set, triangles, () => taking[set] === next, (groups) => next.made.set(one, allocate(one, groups, reachOf(set), 0)));
    }
    queues[set]!.push(() => {
      if (taking[set] !== next) return;
      for (const one of next.members) {
        if (one.instance.mesh !== null) replace(one, set, next.made.get(one) ?? []);
        else for (const allocation of next.made.get(one) ?? []) allocation.destroy();
      }
      takenAt[set] = at;
      taking[set] = null;
      binding.invalidate();
    });
  }

  /** A moving thing's one set: samples all over it, drawn at every distance. */
  function sampleMover(one: Held): void {
    if (one.instance.mesh === null) return;
    replace(one, 0, allocate(one, samplesOf(one, eye(), 0, null), [0, Infinity], 0));
    binding.invalidate();
  }

  /**
   * Borrows what the world layer draws that the data view has not yet borrowed: at the view's opening every surface,
   * those near the eye first; later each surface drawn since, sampled into the sets already taken.
   */
  function borrowNew(at: Vec, opening: boolean): void {
    for (const one of plan(at)) {
      const near = one.away < SETS[1]!.to + SETS[1]!.slack;
      queues[near ? 0 : SETS.length - 1]!.push(() => {
        if (one.skinned) { prepareWalker(one); return; }
        const made = prepare(one);
        if (made === null || opening) {
          if (made !== null && made.mover) queues[SETS.length - 1]!.push(() => sampleMover(made));
          return;
        }
        if (made.mover) { queues[SETS.length - 1]!.push(() => sampleMover(made)); return; }
        SETS.forEach(({ to, slack }, set) => {
          const from = takenAt[set] ?? null;
          if (from === null || made.index === null) return;
          const triangles = to === Infinity ? null : trianglesNear(made.index, from, to + slack);
          if (triangles !== null && triangles.length === 0) return;
          sliced(made, from, set, triangles, () => made.instance.mesh !== null, (groups) => replace(made, set, allocate(made, groups, reachOf(set), 0)));
        });
      });
    }
  }

  /** Reads the town and lines up its surfaces: those near the eye and the near sets first, then the far set. */
  function begin(): void {
    if (tile === null || overlay !== null) return;
    const at = eye();
    opened = at; lateAt = performance.now(); land = [];
    takenAt = SETS.map(() => null); taking = SETS.map(() => null);
    const tiles = townTiles(tile, at);
    things = townThings(tiles) as readonly Thing[];
    kinds = pointKinds(pointBoxes(tiles));
    // What stands in a tag's way is read before any point is drawn, so the points are never in its way.
    const hit = sceneHit(binding.app);
    sight = { face: sceneSight(hit, OWN.face), top: sceneSight(hit, OWN.top), person: sceneSight(hit, OWN.person), line: sceneSight(hit, OWN.line) };
    borrowNew(at, true);
    // The near sets once the surfaces near the eye are read, the far set once every one is.
    queues[0]!.push(() => { takeSet(0, at); takeSet(1, at); });
    queues[SETS.length - 1]!.push(() => takeSet(SETS.length - 1, at));
    setKeep(1); intervals.length = 0; downAt = -Infinity; stepAt = -Infinity; tried = null; heldUntil = -Infinity;
    overlay = new DataViewOverlay({
      device: binding.device, app: binding.app, camera: binding.camera,
      report: () => report(),
      worldBounds: (subject) => (subject.bounds === null ? null : corners(subject.bounds.min, subject.bounds.max)),
      reducedMotion: reduced,
      invalidate: () => binding.invalidate(),
    }, style);
  }

  /** Does sampling work for at most `ms` of this frame, the nearest set's first. */
  function work(ms: number): void {
    for (const allocation of retired.splice(0, RETIRE_PER_FRAME)) allocation.destroy();
    const until = performance.now() + ms;
    while (performance.now() < until) {
      const job = queues.find((queue) => queue.length > 0)?.shift();
      if (job === undefined) return;
      job();
    }
  }

  /** Puts every surface back as it was and lets go of everything drawn. */
  function end(): void {
    for (const one of held) {
      if (one.instance.material === (one.dark.copy as Material)) one.instance.material = one.original;
      one.instance.castShadow = one.castShadow;
      for (const list of one.drawn) for (const allocation of list) allocation.destroy();
    }
    for (const one of walkers) {
      if (one.instance.material === (one.dark.copy as Material)) one.instance.material = one.original;
      one.instance.castShadow = one.castShadow;
    }
    walkerPoints?.destroy();
    walkerPoints = null;
    for (const one of taking) if (one !== null) for (const made of one.made.values()) for (const allocation of made) allocation.destroy();
    for (const allocation of retired) allocation.destroy();
    retired = [];
    for (const dark of darks.values()) dark.copy.destroy();
    darks.clear();
    figures.clear();
    airBack();
    held = []; walkers = []; queues = SETS.map(() => []); allocated = 0; things = []; near = []; thingsAt = -Infinity; kinds = null; sight = null;
    opened = null; land = []; takenAt = SETS.map(() => null); taking = SETS.map(() => null);
    known.clear();
    setKeep(1); intervals.length = 0;
    overlay?.destroy(); overlay = null;
    seen.clear();
    said.clear();
    for (const tag of tags.values()) tag.remove();
    tags.clear();
    shownMix = -1;
    binding.invalidate();
  }

  /** What the overlay draws from: the town's surfaces' points, and a box for each thing near enough. */
  function report(): RepresentationReport {
    const town = surfaceSubject('town');
    const entries = [{
      subject: town,
      resolved: { subjectId: town.subjectId, renderedWeight: 1 - mix, pointWeight: mix, pointLabel: null, blend: 'crossfade' as const, boxes: false, labels: false, ids: false, data: true, binary: false, colourKey: 'geometry-group', geometryVisible: true, reasons: [] },
      allocatedPoints: allocated, plannedPoints: allocated,
    }, ...near.map((thing) => {
      const subject = thingSubject(thing);
      return {
        subject,
        resolved: { subjectId: subject.subjectId, renderedWeight: 1 - mix, pointWeight: 0, pointLabel: null, blend: 'none' as const, boxes: mix >= BOXES_FROM, labels: false, ids: false, data: true, binary: false, colourKey: thing.kind, geometryVisible: true, reasons: [] },
        allocatedPoints: 0, plannedPoints: 0,
      };
    })];
    return {
      intent: { pointMix: mix, boxes: true, labels: false, ids: false, data: true, binary: 'off', colour: 'kind' },
      subjects: entries, allocatedPoints: allocated, allocatedBytes: 0, pointBudget: allocated,
      perSubjectLimit: REPRESENTATION_POINTS_PER_SUBJECT, pendingSubjects: queues.reduce((sum, queue) => sum + queue.length, 0), selection: null,
      style: { id: style.id, version: style.version },
    };
  }

  /** Whether nothing stands between the eye and a tag's anchor, asked again every SIGHT_MS, a few in a frame. */
  function inSight(key: string, kind: keyof typeof OWN, at: Vec, from: Vec, now: number, asked: { count: number }): boolean {
    const held = seen.get(key);
    if (held !== undefined && (now - held.at < SIGHT_MS || asked.count >= SIGHTS_PER_FRAME)) return held.seen;
    if (sight === null) return false;
    asked.count += 1;
    const answer = sight[kind]({ x: from[0], y: from[1], z: from[2] }, { x: at[0], y: at[1], z: at[2] });
    seen.set(key, { seen: answer, at: now });
    return answer;
  }

  /** How a person is called and who decides for them, read again at most every WORDS_MS. */
  const said = new Map<string, { words: { readonly name: string; readonly model: string | null }; at: number }>();
  function wordsOf(id: string, now: number): { readonly name: string; readonly model: string | null } {
    const held = said.get(id);
    if (held !== undefined && now - held.at < WORDS_MS) return held.words;
    const words = people?.words(id) ?? { name: '', model: null };
    said.set(id, { words, at: now });
    return words;
  }

  /** Each tag's size as last measured, for its words and the page's scale then. */
  const sizes = new WeakMap<HTMLDivElement, { text: string; scale: number; width: number; height: number }>();

  /** One tag's element, by key, drawn once with its lines and the kind's colour at its edge. */
  function tagOf(key: string, lines: readonly string[], colour: DataViewHex, person: boolean): HTMLDivElement {
    let tag = tags.get(key);
    const text = lines.join('\n');
    if (tag === undefined) {
      tag = document.createElement('div');
      tag.className = person ? 'wu-data-tag wu-data-person' : 'wu-data-tag';
      tagLayer.append(tag);
      tags.set(key, tag);
    }
    if (tag.dataset.text !== text) {
      tag.dataset.text = text;
      // The product's own marker before the words (the landing page's upright mark), in the kind's colour.
      const mark = document.createElement('span');
      mark.className = 'wu-data-mark';
      tag.replaceChildren(mark, ...lines.map((line, index) => {
        const made = document.createElement('span');
        made.className = index === 0 ? 'wu-data-line' : 'wu-data-line wu-data-under';
        made.textContent = line;
        return made;
      }));
    }
    if (tag.style.getPropertyValue('--data-kind') !== colour) tag.style.setProperty('--data-kind', colour);
    return tag;
  }

  /**
   * Places the tags of what is near: nearest first, none over another or over a walker's face or body but their own,
   * each at the first of its places clear of them (a building's faces, a street's points along its middle line), and
   * none for a thing seen smaller than a tag can stand for (bigEnough).
   */
  function drawTags(now: number): void {
    const camera = binding.camera.camera;
    if (mix <= 0.02 || camera === null) {
      for (const tag of tags.values()) show(tag, false);
      return;
    }
    const from = eye();
    const point = binding.camera.getPosition().clone();
    const project = (at: Vec): { x: number; y: number } | null => {
      const screen = camera.worldToScreen(point.set(at[0], at[1], at[2]));
      return screen.z > 0 ? { x: screen.x, y: screen.y } : null;
    };
    // The camera's CSS pixels to a radian, as the tags are laid out.
    const css = 0.5 * innerHeight * camera.projectionMatrix.data[5]!;
    const asked = { count: 0 };
    const wanted: { key: string; lines: readonly string[]; colour: DataViewHex; person: boolean; places: { x: number; y: number }[]; distance: number }[] = [];
    for (const thing of near) {
      if (thing.hang === 'line') {
        const places: { x: number; y: number; off: number; distance: number }[] = [];
        for (const at of streetLine(thing) as Vec[]) {
          const distance = Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]);
          if (distance > REACH.street) continue;
          const screen = project(at);
          if (screen === null || screen.y < innerHeight * 0.5 || screen.x < 0 || screen.x > innerWidth) continue;
          if (inSight(`${thing.id}:${at.join(',')}`, 'line', at, from, now, asked)) places.push({ ...screen, off: Math.abs(screen.x - innerWidth / 2), distance });
        }
        places.sort((a, b) => a.off - b.off);
        if (places.length > 0) wanted.push({ key: thing.id, lines: [thing.words], colour: colourOf(thing.kind), person: false, places, distance: places[0]!.distance });
        continue;
      }
      const size = Math.max(thing.max[0] - thing.min[0], thing.max[1] - thing.min[1], thing.max[2] - thing.min[2]);
      const places: { x: number; y: number }[] = [];
      let distance = Infinity;
      for (const at of tagAnchors(thing, from) as Vec[]) {
        const away = Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]);
        if (!bigEnough(size, away, css)) continue;
        const screen = project(at);
        if (screen === null) continue;
        if (!inSight(`${thing.id}:${at.join(',')}`, thing.hang === 'face' ? 'face' : 'top', at, from, now, asked)) continue;
        places.push(screen);
        distance = Math.min(distance, away);
      }
      if (places.length > 0) wanted.push({ key: thing.id, lines: [thing.words], colour: colourOf(thing.kind), person: false, places, distance });
    }
    // Every walker in view near enough: their tag, and their face and body, which no other tag may cover.
    const blocked: ReturnType<typeof walkerBoxes> = [];
    for (const one of people?.everyone() ?? []) {
      const at: Vec = [one.head.x, one.head.y, one.head.z];
      const distance = Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]);
      if (distance > REACH.person) continue;
      const screen = project(at);
      if (screen === null) continue;
      const key = `person:${one.id}`;
      blocked.push(...walkerBoxes({ owner: key, x: screen.x, y: screen.y, distance }, css));
      if (!inSight(key, 'person', at, from, now, asked)) continue;
      wanted.push({ key, lines: personLines(wordsOf(one.id, now)), colour: style.boxes.selectedColour, person: true, places: [screen], distance });
    }
    // Measured on their own elements once for their words and the page's scale, then placed: each sits just over its
    // place, centred on it. Nothing is written to a tag that has not changed, so a still view lays out nothing.
    const scale = Number.parseFloat(host.style.getPropertyValue('--ui-scale')) || 1;
    const lift = 6 * scale;
    const measured = wanted.map((one) => {
      const tag = tagOf(one.key, one.lines, one.colour, one.person);
      let size = sizes.get(tag);
      if (size === undefined || size.text !== tag.dataset.text || size.scale !== scale) {
        show(tag, true);
        size = { text: tag.dataset.text ?? '', scale, width: tag.offsetWidth, height: tag.offsetHeight };
        sizes.set(tag, size);
      }
      const corner = (at: { x: number; y: number }) => ({ x: Math.round(at.x - size!.width / 2), y: Math.round(at.y - size!.height - lift) });
      const [first, ...rest] = one.places.map(corner);
      return { key: one.key, tag, width: size.width, height: size.height, distance: one.distance, x: first!.x, y: first!.y, also: rest };
    });
    const placed = placeTags(measured, { width: innerWidth, height: innerHeight, most: style.tags.maxCount, blocked }) as { key: string; x: number; y: number }[];
    const opacity = String(smooth((mix - 0.15) / 0.5));
    const shown = new Set<HTMLDivElement>();
    const byKey = new Map(measured.map((one) => [one.key, one.tag]));
    for (const one of placed) {
      const tag = byKey.get(one.key);
      if (tag === undefined) continue;
      shown.add(tag);
      const transform = `translate(${one.x}px, ${one.y}px)`;
      if (tag.style.transform !== transform) tag.style.transform = transform;
      if (tag.style.opacity !== opacity) tag.style.opacity = opacity;
    }
    for (const tag of tags.values()) show(tag, shown.has(tag));
  }

  /** Shows or hides a tag, writing only a change. */
  function show(tag: HTMLDivElement, on: boolean): void {
    if (tag.hidden === on) tag.hidden = !on;
  }

  function setMix(next: number): void {
    mix = Math.min(1, Math.max(0, next));
    slider.value = String(Math.round(mix * 1000));
    slider.style.setProperty('--fill', `${(mix * 100).toFixed(1)}%`);
  }

  function glideTo(next: number, now = performance.now()): void {
    target = next;
    glide = reduced() ? null : { from: mix, to: next, start: now };
    if (glide === null) setMix(next);
  }

  slider.addEventListener('input', () => {
    glide = null;
    setMix(Number(slider.value) / 1000);
    target = mix;
    binding.invalidate();
  });
  // The slider keeps its arrows: they move it, not the person, while it has the focus.
  slider.addEventListener('keydown', (event) => { if (event.code.startsWith('Arrow')) event.stopPropagation(); });

  return {
    works: tile !== null,
    get shown() { return !card.hidden; },
    toggle() {
      if (tile === null) return;
      if (card.hidden) {
        card.hidden = false;
        onOpen();
        begin();
        glideTo(1);
      } else glideTo(0);
    },
    close() {
      if (card.hidden) return false;
      glideTo(0);
      return true;
    },
    frame(now) {
      if (glide !== null) {
        const t = Math.min(1, (now - glide.start) / GLIDE_MS);
        setMix(glide.from + (glide.to - glide.from) * smooth(t));
        if (t >= 1) glide = null;
      }
      // Samples taken a little each frame, the nearest set's first: each set taken again once the eye has walked its
      // step from where it was taken, and the world layer read again now and then for surfaces drawn since.
      if (overlay !== null) {
        const at = eye();
        SETS.forEach(({ step }, set) => {
          const from = takenAt[set] ?? null;
          if (taking[set] === null && from !== null && apart(at, from) >= step) takeSet(set, at);
        });
        if (now - lateAt >= LATE_MS) { lateAt = now; borrowNew(at, false); }
        work(SAMPLE_MS);
      }
      if (overlay !== null && now - thingsAt > 250) {
        thingsAt = now;
        const from = eye();
        near = things.filter((thing) => {
          const middle = [0, 1, 2].map((axis) => (thing.min[axis]! + thing.max[axis]!) / 2);
          const reach = thing.hang === 'line' ? Infinity : REACH.thing + Math.hypot(thing.max[0] - thing.min[0], thing.max[2] - thing.min[2]) / 2;
          return Math.hypot(middle[0]! - from[0], middle[1]! - from[1], middle[2]! - from[2]) <= reach;
        });
      }
      // A walker drawn from afar shows their points only while they are drawn so.
      for (const one of held) {
        if (!one.mover || one.instance.visible === one.shown) continue;
        one.shown = one.instance.visible;
        for (const list of one.drawn) for (const allocation of list) allocation.setWeight(one.shown ? mix : 0);
        binding.invalidate();
      }
      // A surface the world no longer draws (a walker gone, their points let go of themselves) is let go of; one drawn
      // again later is borrowed anew.
      const gone = (one: Walker): boolean => one.instance.mesh === null || (one.points !== null && one.points.gone);
      if (walkers.some(gone)) walkers = walkers.filter((one) => !gone(one));
      if (held.some((one) => one.instance.mesh === null)) {
        held = held.filter((one) => {
          if (one.instance.mesh !== null) return true;
          for (const list of one.drawn) { allocated -= countOf(list); for (const allocation of list) allocation.destroy(); }
          return false;
        });
      }
      for (const one of walkers) {
        if (one.instance.visible === one.shown) continue;
        one.shown = one.instance.visible;
        one.points?.setShown(one.shown);
      }
      // A surface the world dresses again while the view shows (a signal's lamp changing colour) has its new dress
      // borrowed as its first was.
      if (overlay !== null && shownMix > 0) {
        for (const one of held) {
          const now = one.instance.material;
          if (now === (one.dark.copy as Material) || now === null || one.instance.mesh === null) continue;
          const copy = darkOf(now);
          if (copy === null) continue;
          one.original = now;
          one.dark = copy.dark;
          dress(one.instance, now, copy.dark, copy.made, one.castShadow);
        }
      }
      // The world's air follows the slider every frame, in case the world aims it again while the view shows.
      if (overlay !== null) air(mix);
      if (mix !== shownMix) {
        shownMix = mix;
        darken(mix);
        for (const one of held) for (const list of one.drawn) for (const allocation of list) allocation.setWeight(one.shown ? mix : 0);
        walkerPoints?.setWeight(mix);
        binding.invalidate();
      }
      drawTags(now);
      // The GPU's share, stepped by the frame times measured once the sets are taken and the town is mostly data;
      // a step down that leaves the frames as slow is taken back (keepStep), so a page slow for other reasons keeps them.
      if (overlay !== null && queues.every((queue) => queue.length === 0) && mix >= 0.5 && lastFrame !== null) {
        intervals.push(now - lastFrame);
        if (intervals.length > 90) intervals.shift();
        if (now - stepAt >= 1000) {
          stepAt = now;
          const next = keepStep({ keep, floor: KEEP_FLOOR, intervals, now, downAt, tried, heldUntil });
          downAt = next.downAt; tried = next.tried; heldUntil = next.heldUntil;
          if (next.keep !== keep) { setKeep(next.keep); intervals.length = 0; binding.invalidate(); }
        }
      } else intervals.length = 0;
      lastFrame = now;
      // Back at the world with the card closing: everything is put back and let go.
      if (target === 0 && glide === null && mix === 0 && overlay !== null) {
        card.hidden = true;
        end();
      }
    },
    dispose() {
      end();
      card.remove();
      tagLayer.remove();
    },
  };
}

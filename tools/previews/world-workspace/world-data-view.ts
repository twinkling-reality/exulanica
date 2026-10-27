// The data view in a made town ([X] Data): one small card with one slider, from the world to its data. As it moves,
// the town's surfaces go dark and glowing points sampled from them take their place, each coloured by the kind of
// record it stands on, over the data view's dark ground; each thing the town's records name gets a thin box and a
// tag in the catalogs' words, and each person drawn here a tag with their name and, under it, the model that decides
// for them where one does. Nothing is kept or picked: closing the card puts every surface back as it was.
// The look is the product's data view style (atlas-core's DATA_VIEW_STYLE), drawn by the product's own parts: the
// sampled surface (representation-binding.ts), the point draw (data-view/points.ts), and the dark ground and the
// boxes (data-view/overlay.ts). What the town's things are, their words and where a tag goes are
// data-view-things.mjs's; whether a wall stands between the eye and a tag is scene-sight.ts's.
//
// A town is seen from its own street, so its surfaces go dark rather than dissolve: each keeps standing where it is,
// in the ground's colour, and so hides what is behind it, its own points drawn over it (the style's pull brings each
// point that far toward the eye). Dissolved, as a district seen from above dissolves, every building's points would
// show through every other's.
import {
  DATA_VIEW_STYLE, REPRESENTATION_POINTS_PER_SUBJECT, dataViewKindColour, dataViewRgb,
  type DataViewHex, type DataViewStyle, type RepresentationSubject,
} from '../../../web/packages/atlas-core/src/index.ts';
import type { AtlasBinding } from '../../../web/packages/atlas-react/src/playcanvas/atlas-binding.ts';
import { createDataViewPoints } from '../../../web/packages/atlas-react/src/playcanvas/data-view/points.ts';
import { DataViewOverlay } from '../../../web/packages/atlas-react/src/playcanvas/data-view/overlay.ts';
import type { LoadedGeneratedTile } from '../../../web/packages/atlas-react/src/playcanvas/generated-tile/tile-runtime.ts';
import { meshSurfaceArea, sampledMeshSurfacePositions, staticMeshRepresentation } from '../../../web/packages/atlas-react/src/playcanvas/representation-binding.ts';
import {
  REPRESENTATION_POINTS_PER_UPDATE,
  type RepresentationPointAllocation, type RepresentationReport,
} from '../../../web/packages/atlas-react/src/playcanvas/representation-runtime.ts';
import { personLines, placeTags, pointBoxes, pointKinds, streetLine, surfaceOf, tagAnchors, townThings } from './data-view-things.mjs';
import { sceneHit, sceneSight } from './scene-sight.ts';
import { DATA_WORDS } from './world-words.mjs';
import './world-data-view.css';

/**
 * How much denser than the style's density a town's built surfaces are sampled: the style's density is set for a
 * district seen from above, and a town is seen from its own street, where that density leaves a wall as scattered dots.
 */
const BUILT_DENSITY = 4;
/** The most points a town's data view draws: under the 2,187,735 the data view's frame budget measured (atlas-core). */
const TOWN_POINTS = 1_500_000;
/** Ground beyond this many metres from the eye when the view opens gets no points: it is beyond what a tag reaches. */
const GROUND_REACH = 240;
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
type Surface = 'wall' | 'road' | 'path' | 'kerb' | 'plant' | 'furniture' | 'ground' | 'vehicle' | 'backdrop';
type Material = MeshInstance['material'];
/** A colour as a standard material holds it. */
interface Colour { r: number; g: number; b: number; set(r: number, g: number, b: number): unknown }
/** A standard material, as the darkening reads and writes it. */
interface Darkenable { clone(): Darkenable; update(): void; destroy(): void; diffuse: Colour; emissive: Colour; specular?: Colour; specularityFactor?: number }
/** A material's dark copy and the colours it is darkened from. */
interface Dark { readonly copy: Darkenable; readonly diffuse: Vec; readonly emissive: Vec; readonly specular: Vec | null; readonly specularity: number | null }
interface Held { readonly instance: MeshInstance; readonly original: Material; readonly dark: Dark; readonly allocations: readonly RepresentationPointAllocation[]; readonly points: number }
interface Planned { readonly instance: MeshInstance; readonly surface: Surface; readonly count: number }

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

export function mountDataView({ host, binding, people = null, onOpen = () => {}, style = DATA_VIEW_STYLE }: {
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
  let held: Held[] = [], queue: Planned[] = [], allocated = 0;
  let things: readonly Thing[] = [], near: readonly Thing[] = [], nearAt = -Infinity;
  let kinds: ReturnType<typeof pointKinds> | null = null;
  let overlay: DataViewOverlay | null = null;
  let sight: { face: ReturnType<typeof sceneSight>; top: ReturnType<typeof sceneSight>; person: ReturnType<typeof sceneSight>; line: ReturnType<typeof sceneSight> } | null = null;
  const seen = new Map<string, { seen: boolean; at: number }>();
  const tags = new Map<string, HTMLDivElement>();
  const reduced = (): boolean => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const eye = (): Vec => { const at = binding.camera.getPosition(); return [at.x, at.y, at.z]; };
  /** Each borrowed material's dark copy, one for every surface that wears it. */
  const darks = new Map<Material, Dark>();
  const ground = dataViewRgb(style.ground.colour);

  /** A material's dark copy, made once: the same material, its colours to be eased toward the ground's. */
  function darkOf(material: Material): Dark | null {
    const held = darks.get(material);
    if (held !== undefined) return held;
    if (!darkenable(material)) return null;
    const copy = material.clone();
    const dark: Dark = {
      copy, diffuse: rgb(material.diffuse), emissive: rgb(material.emissive),
      specular: material.specular ? rgb(material.specular) : null,
      specularity: typeof material.specularityFactor === 'number' ? material.specularityFactor : null,
    };
    darks.set(material, dark);
    return dark;
  }

  /** Eases every dark copy toward the ground: its own colour and shine out by `weight`, the ground's colour in. */
  function darken(weight: number): void {
    const keep = 1 - weight;
    for (const dark of darks.values()) {
      dark.copy.diffuse.set(dark.diffuse[0] * keep, dark.diffuse[1] * keep, dark.diffuse[2] * keep);
      dark.copy.emissive.set(dark.emissive[0] * keep + ground[0] * weight, dark.emissive[1] * keep + ground[1] * weight, dark.emissive[2] * keep + ground[2] * weight);
      if (dark.specular !== null && dark.copy.specular) dark.copy.specular.set(dark.specular[0] * keep, dark.specular[1] * keep, dark.specular[2] * keep);
      if (dark.specularity !== null) dark.copy.specularityFactor = dark.specularity * keep;
      dark.copy.update();
    }
    for (const one of held) one.instance.material = (weight > 0 ? one.dark.copy : one.original) as Material;
  }

  /** Everything drawn in the world layer the data view can borrow, with how many points each gets. */
  function plan(at: Vec): Planned[] {
    const world = binding.app.scene.layers.getLayerByName('World');
    const found: { instance: MeshInstance; surface: Surface; area: number }[] = [];
    for (const instance of new Set<MeshInstance>(world?.meshInstances ?? [])) {
      if (!instance.visible || instance.instancingData || instance.skinInstance || instance.morphInstance) continue;
      const surface = surfaceOf(instance.material?.name ?? '', instance.node?.name ?? '') as Surface | null;
      if (surface === null) continue;
      if (surface === 'ground') {
        const c = instance.aabb.center;
        if (Math.hypot(c.x - at[0], c.z - at[2]) - Math.hypot(instance.aabb.halfExtents.x, instance.aabb.halfExtents.z) > GROUND_REACH) continue;
      }
      const positions: number[] = [], indices: number[] = [];
      instance.mesh.getPositions(positions);
      instance.mesh.getIndices(indices);
      const area = positions.length >= 9 ? meshSurfaceArea(positions, indices) : 0;
      if (Number.isFinite(area) && area > 0) found.push({ instance, surface, area });
    }
    // The backdrop, beyond the town, goes dark with it and has no points of its own.
    const wanted = (one: { surface: Surface; area: number }): number => one.surface === 'backdrop' ? 0
      : one.area * style.points.densityPerSquareMetre * (one.surface === 'ground' ? 1 : BUILT_DENSITY);
    const total = found.reduce((sum, one) => sum + wanted(one), 0);
    const scale = total > TOWN_POINTS ? TOWN_POINTS / total : 1;
    return found.map((one) => ({ instance: one.instance, surface: one.surface, count: Math.min(REPRESENTATION_POINTS_PER_SUBJECT, Math.round(wanted(one) * scale)) }));
  }

  /** Borrows one surface: its dark copy, and its points grouped by the kind of record each stands on. */
  function borrow({ instance, surface, count }: Planned): number {
    const original = instance.material;
    const dark = darkOf(original);
    if (dark === null) return 0;
    const allocations: RepresentationPointAllocation[] = [];
    let points = 0;
    const positions: number[] = [], indices: number[] = [];
    instance.mesh.getPositions(positions);
    instance.mesh.getIndices(indices);
    const samples = count >= 1 ? sampledMeshSurfacePositions(positions, indices, count) : null;
    if (samples !== null && kinds !== null) {
      const m = instance.node.getWorldTransform().data;
      const byKind = new Map<string, number[]>();
      for (let at = 0; at + 2 < samples.length; at += 3) {
        const x = samples[at]!, y = samples[at + 1]!, z = samples[at + 2]!;
        const kind = kinds.kindAt(surface, m[0]! * x + m[4]! * y + m[8]! * z + m[12]!, m[1]! * x + m[5]! * y + m[9]! * z + m[13]!, m[2]! * x + m[6]! * y + m[10]! * z + m[14]!) ?? 'object';
        let list = byKind.get(kind);
        if (list === undefined) { list = []; byKind.set(kind, list); }
        list.push(x, y, z);
      }
      for (const [kind, local] of byKind) {
        const allocation = createDataViewPoints({ device: binding.device, node: instance.node, positions: new Float32Array(local), style, subjectId: `town:${kind}` });
        if (allocation === null) continue;
        allocation.setLook?.({ colour: colourOf(kind), treatment: 'points', gain: 1 });
        allocation.setWeight(mix);
        allocations.push(allocation);
        points += allocation.pointCount;
      }
    }
    held.push({ instance, original, dark, allocations, points });
    // Its dark copy takes the slider's weight with the others on the next frame.
    shownMix = -1;
    return points;
  }

  /** Reads the town and lines up its surfaces; each is borrowed over the frames that follow. */
  function begin(): void {
    if (tile === null || overlay !== null) return;
    const at = eye();
    const tiles = townTiles(tile, at);
    things = townThings(tiles) as readonly Thing[];
    kinds = pointKinds(pointBoxes(tiles));
    // What stands in a tag's way is read before any point is drawn, so the points are never in its way.
    const hit = sceneHit(binding.app);
    sight = { face: sceneSight(hit, OWN.face), top: sceneSight(hit, OWN.top), person: sceneSight(hit, OWN.person), line: sceneSight(hit, OWN.line) };
    queue = plan(at);
    overlay = new DataViewOverlay({
      device: binding.device, app: binding.app, camera: binding.camera,
      report: () => report(),
      worldBounds: (subject) => (subject.bounds === null ? null : corners(subject.bounds.min, subject.bounds.max)),
      reducedMotion: reduced,
      invalidate: () => binding.invalidate(),
    }, style);
  }

  /** Puts every surface back as it was and lets go of everything drawn. */
  function end(): void {
    for (const one of held) {
      if (one.instance.material === (one.dark.copy as Material)) one.instance.material = one.original;
      for (const allocation of one.allocations) allocation.destroy();
    }
    for (const dark of darks.values()) dark.copy.destroy();
    darks.clear();
    held = []; queue = []; allocated = 0; things = []; near = []; nearAt = -Infinity; kinds = null; sight = null;
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
        resolved: { subjectId: subject.subjectId, renderedWeight: 1 - mix, pointWeight: 0, pointLabel: null, blend: 'none' as const, boxes: mix > 0, labels: false, ids: false, data: true, binary: false, colourKey: thing.kind, geometryVisible: true, reasons: [] },
        allocatedPoints: 0, plannedPoints: 0,
      };
    })];
    return {
      intent: { pointMix: mix, boxes: true, labels: false, ids: false, data: true, binary: 'off', colour: 'kind' },
      subjects: entries, allocatedPoints: allocated, allocatedBytes: 0, pointBudget: TOWN_POINTS,
      perSubjectLimit: REPRESENTATION_POINTS_PER_SUBJECT, pendingSubjects: queue.length, selection: null,
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
      tag.replaceChildren(...lines.map((line, index) => {
        const made = document.createElement('span');
        made.className = index === 0 ? 'wu-data-line' : 'wu-data-line wu-data-under';
        made.textContent = line;
        return made;
      }));
    }
    if (tag.style.getPropertyValue('--data-kind') !== colour) tag.style.setProperty('--data-kind', colour);
    return tag;
  }

  /** Places the tags of what is near, nearest first, none over another. */
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
    const asked = { count: 0 };
    const wanted: { key: string; lines: readonly string[]; colour: DataViewHex; person: boolean; x: number; y: number; distance: number }[] = [];
    for (const thing of near) {
      if (thing.hang === 'line') {
        let best: { x: number; y: number; distance: number } | null = null;
        for (const at of streetLine(thing) as Vec[]) {
          const distance = Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]);
          if (distance > REACH.street) continue;
          const screen = project(at);
          if (screen === null || screen.y < innerHeight * 0.5 || screen.x < 0 || screen.x > innerWidth) continue;
          if (best !== null && Math.abs(screen.x - innerWidth / 2) >= Math.abs(best.x - innerWidth / 2)) continue;
          if (inSight(`${thing.id}:${at.join(',')}`, 'line', at, from, now, asked)) best = { ...screen, distance };
        }
        if (best !== null) wanted.push({ key: thing.id, lines: [thing.words], colour: colourOf(thing.kind), person: false, ...best });
        continue;
      }
      for (const at of tagAnchors(thing, from) as Vec[]) {
        const screen = project(at);
        if (screen === null) continue;
        if (!inSight(`${thing.id}:${at.join(',')}`, thing.hang === 'face' ? 'face' : 'top', at, from, now, asked)) continue;
        wanted.push({ key: thing.id, lines: [thing.words], colour: colourOf(thing.kind), person: false, x: screen.x, y: screen.y, distance: Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]) });
        break;
      }
    }
    for (const one of people?.everyone() ?? []) {
      const at: Vec = [one.head.x, one.head.y, one.head.z];
      const distance = Math.hypot(at[0] - from[0], at[1] - from[1], at[2] - from[2]);
      if (distance > REACH.person) continue;
      const screen = project(at);
      if (screen === null || !inSight(`person:${one.id}`, 'person', at, from, now, asked)) continue;
      wanted.push({ key: `person:${one.id}`, lines: personLines(wordsOf(one.id, now)), colour: style.boxes.selectedColour, person: true, x: screen.x, y: screen.y, distance });
    }
    // Measured on their own elements once for their words and the page's scale, then placed: each sits just over its
    // anchor, centred on it. Nothing is written to a tag that has not changed, so a still view lays out nothing.
    const scale = Number.parseFloat(host.style.getPropertyValue('--ui-scale')) || 1;
    const measured = wanted.map((one) => {
      const tag = tagOf(one.key, one.lines, one.colour, one.person);
      show(tag, true);
      let size = sizes.get(tag);
      if (size === undefined || size.text !== tag.dataset.text || size.scale !== scale) {
        size = { text: tag.dataset.text ?? '', scale, width: tag.offsetWidth, height: tag.offsetHeight };
        sizes.set(tag, size);
      }
      return { ...one, tag, width: size.width, height: size.height };
    });
    const lift = 6 * scale;
    const kept = new Set(placeTags(measured.map((one) => ({ ...one, x: one.x - one.width / 2, y: one.y - one.height - lift })), {
      width: innerWidth, height: innerHeight, most: style.tags.maxCount,
    }).map((one: { readonly key: string }) => one.key));
    const opacity = String(smooth((mix - 0.15) / 0.5));
    const placed = new Set<HTMLDivElement>();
    for (const one of measured) {
      if (!kept.has(one.key)) continue;
      placed.add(one.tag);
      const transform = `translate(${Math.round(one.x - one.width / 2)}px, ${Math.round(one.y - one.height - lift)}px)`;
      if (one.tag.style.transform !== transform) one.tag.style.transform = transform;
      if (one.tag.style.opacity !== opacity) one.tag.style.opacity = opacity;
    }
    for (const tag of tags.values()) show(tag, placed.has(tag));
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
      // Borrowed a few surfaces a frame, as the product's own data view prepares its points.
      let budget = REPRESENTATION_POINTS_PER_UPDATE;
      while (queue.length > 0 && budget > 0 && overlay !== null) {
        const next = queue.shift()!;
        const points = borrow(next);
        allocated += points;
        budget -= Math.max(1, next.count);
      }
      if (overlay !== null && now - nearAt > 250) {
        nearAt = now;
        const from = eye();
        near = things.filter((thing) => {
          const middle = [0, 1, 2].map((axis) => (thing.min[axis]! + thing.max[axis]!) / 2);
          const reach = thing.hang === 'line' ? Infinity : REACH.thing + Math.hypot(thing.max[0] - thing.min[0], thing.max[2] - thing.min[2]) / 2;
          return Math.hypot(middle[0]! - from[0], middle[1]! - from[1], middle[2]! - from[2]) <= reach;
        });
      }
      if (mix !== shownMix) {
        shownMix = mix;
        darken(mix);
        for (const one of held) for (const allocation of one.allocations) allocation.setWeight(mix);
        binding.invalidate();
      }
      drawTags(now);
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

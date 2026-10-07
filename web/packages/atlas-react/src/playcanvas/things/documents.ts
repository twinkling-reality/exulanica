/**
 * The parts of the things documents the drawing reads, and the library list that names them.
 *
 * The host serves its thing library by digest (`GET /things/library` and
 * `GET /things/library/{content_sha256}`, THINGS's routes): the kinds, the looks, the body plans
 * catalog and every look's container. The Python readers (`exulanica/things`) are authoritative and
 * the host serves only what they admit; this module reads what drawing needs and refuses by name
 * anything shaped otherwise, so a document the drawing cannot read is drawn as nothing with its
 * reason, never guessed at. Nothing here decides what a thing does: a kind is read for its body (its
 * size and the plan its looks fit) and for how it is held, and a look for how it is drawn.
 *
 * Pure: no renderer.
 */

import type { BodyPlanEntry, PlanBone, PlanSocket } from './skeleton.js';

export const THING_LIBRARY_PROFILE = 'exulanica.thing-library/v1';
export const LOOK_PROFILE = 'exulanica.look/v1';
export const THING_KIND_PROFILE = 'exulanica.thing-kind/v1';

export type ThingDocumentRefusal =
  | 'thing_library_invalid'
  | 'thing_kind_invalid'
  | 'look_invalid'
  | 'body_plans_invalid';

export class ThingDocumentRefused extends Error {
  override readonly name = 'ThingDocumentRefused';
  constructor(readonly reason: ThingDocumentRefusal, readonly field: string, message: string) {
    super(message);
  }
}

/** A document named by key, version and the SHA-256 of its canonical bytes. */
export interface DocumentReference {
  readonly key: string;
  readonly version: number;
  readonly sha256: string;
}

export interface ContainerReference {
  readonly sha256: string;
  readonly bytes: number;
  readonly media_type: string;
}

/** How each look kind is drawn; a look kind the drawing does not know is drawn as nothing. */
export const LOOK_KINDS = ['catalog_person', 'skinned', 'rigid_on_bones', 'light', 'static', 'look_role', 'none'] as const;
export type LookKind = (typeof LOOK_KINDS)[number];

export interface LibraryKind {
  readonly kind: string;
  readonly version: number;
  readonly sha256: string;
  readonly label: string;
  readonly class: 'being' | 'object';
  readonly bodyPlan: string;
  /** The kind's looks, the first its default. */
  readonly looks: readonly DocumentReference[];
}

export interface LibraryLook {
  readonly look: string;
  readonly version: number;
  readonly sha256: string;
  readonly label: string;
  readonly bodyPlan: string;
  readonly lookKind: string;
  readonly container: ContainerReference | null;
}

export interface ThingLibraryList {
  readonly kinds: readonly LibraryKind[];
  readonly looks: readonly LibraryLook[];
  readonly bodyPlansSha256: string;
}

export interface Grip {
  readonly x_mm: number;
  readonly y_mm: number;
  readonly z_mm: number;
  readonly axis: '+x' | '-x' | '+y' | '-y' | '+z' | '-z';
}

/** What drawing reads of a kind: its body and how it is held. */
export interface KindDrawing {
  readonly kind: string;
  readonly version: number;
  readonly label: string;
  readonly class: 'being' | 'object';
  readonly bodyPlan: string;
  readonly heightMm: { readonly from: number; readonly to: number } | null;
  readonly radiusMm: number | null;
  readonly boxMm: { readonly width: number; readonly depth: number; readonly height: number } | null;
  /** How a holdable thing is gripped, or null for a thing nobody holds. */
  readonly grip: Grip | null;
  readonly looks: readonly DocumentReference[];
}

export interface SkinnedRig {
  readonly bones: Readonly<Record<string, string>>;
  readonly clips: Readonly<Record<string, string>>;
  readonly sockets: Readonly<Record<string, string>>;
  readonly groundSpeedMmPerS: Readonly<Record<string, number>>;
}

/** What drawing reads of a look. */
export interface LookDrawing {
  readonly look: string;
  readonly version: number;
  readonly label: string;
  readonly bodyPlan: string;
  readonly lookKind: string;
  readonly container: ContainerReference | null;
  readonly rig: SkinnedRig | null;
  readonly heightMm: number | null;
  readonly sampling: 'linear' | 'nearest';
  readonly light: { readonly colour: string; readonly intensityMilli: number; readonly radiusMm: number } | null;
  readonly role: string | null;
}

type Json = Record<string, unknown>;
const HEX64 = /^[0-9a-f]{64}$/u;
const KEY = /^[a-z][a-z0-9_-]{0,63}$/u;
const PLAN = /^[a-z][a-z0-9_-]{0,47}\/v[1-9][0-9]{0,3}$/u;
const COLOUR = /^#[0-9a-f]{6}$/u;
const AXES = ['+x', '-x', '+y', '-y', '+z', '-z'] as const;

function reader(reason: ThingDocumentRefusal) {
  const fail = (field: string, message: string): never => {
    throw new ThingDocumentRefused(reason, field, `${field}: ${message}`);
  };
  const object = (value: unknown, field: string): Json =>
    typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Json) : fail(field, 'is not an object');
  const list = (value: unknown, field: string): readonly unknown[] => (Array.isArray(value) ? value : fail(field, 'is not a list'));
  const text = (value: unknown, field: string, pattern?: RegExp): string =>
    typeof value === 'string' && (pattern === undefined || pattern.test(value)) ? value : fail(field, pattern ? `is not text of the form ${pattern.source}` : 'is not text');
  const whole = (value: unknown, field: string, minimum = 0): number =>
    typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum ? value : fail(field, `is not a whole number from ${minimum}`);
  const reference = (value: unknown, field: string, name: string): DocumentReference => {
    const row = object(value, field);
    return Object.freeze({ key: text(row[name], `${field}.${name}`, KEY), version: whole(row['version'], `${field}.version`, 1), sha256: text(row['sha256'], `${field}.sha256`, HEX64) });
  };
  const container = (value: unknown, field: string): ContainerReference | null => {
    if (value === null) return null;
    const row = object(value, field);
    const media = text(row['media_type'], `${field}.media_type`);
    if (media !== 'model/gltf-binary') fail(`${field}.media_type`, 'is not model/gltf-binary');
    return Object.freeze({ sha256: text(row['sha256'], `${field}.sha256`, HEX64), bytes: whole(row['bytes'], `${field}.bytes`, 1), media_type: media });
  };
  return { fail, object, list, text, whole, reference, container };
}

/** Read the host's library list, or refuse it by name. */
export function readThingLibrary(value: unknown): ThingLibraryList {
  const r = reader('thing_library_invalid');
  const body = r.object(value, 'library');
  if (body['profile'] !== undefined && body['profile'] !== THING_LIBRARY_PROFILE) r.fail('library.profile', `is not ${THING_LIBRARY_PROFILE}`);
  const kinds = r.list(body['kinds'], 'kinds').map((value, i): LibraryKind => {
    const row = r.object(value, `kinds[${i}]`);
    const kindClass = r.text(row['class'], `kinds[${i}].class`);
    if (kindClass !== 'being' && kindClass !== 'object') r.fail(`kinds[${i}].class`, 'is neither being nor object');
    return Object.freeze({
      kind: r.text(row['kind'], `kinds[${i}].kind`, KEY),
      version: r.whole(row['version'], `kinds[${i}].version`, 1),
      sha256: r.text(row['sha256'], `kinds[${i}].sha256`, HEX64),
      label: r.text(row['label'], `kinds[${i}].label`),
      class: kindClass as 'being' | 'object',
      bodyPlan: r.text(row['body_plan'], `kinds[${i}].body_plan`, PLAN),
      looks: Object.freeze(r.list(row['looks'], `kinds[${i}].looks`).map((look, j) => r.reference(look, `kinds[${i}].looks[${j}]`, 'look'))),
    });
  });
  const looks = r.list(body['looks'], 'looks').map((value, i): LibraryLook => {
    const row = r.object(value, `looks[${i}]`);
    return Object.freeze({
      look: r.text(row['look'], `looks[${i}].look`, KEY),
      version: r.whole(row['version'], `looks[${i}].version`, 1),
      sha256: r.text(row['sha256'], `looks[${i}].sha256`, HEX64),
      label: r.text(row['label'], `looks[${i}].label`),
      bodyPlan: r.text(row['body_plan'], `looks[${i}].body_plan`, PLAN),
      lookKind: r.text(row['look_kind'], `looks[${i}].look_kind`, KEY),
      container: r.container(row['container'] ?? null, `looks[${i}].container`),
    });
  });
  const plans = r.object(body['body_plans'], 'body_plans');
  return Object.freeze({
    kinds: Object.freeze(kinds),
    looks: Object.freeze(looks),
    bodyPlansSha256: r.text(plans['sha256'], 'body_plans.sha256', HEX64),
  });
}

/** Read what drawing needs of a thing kind document. */
export function readKindDrawing(value: unknown): KindDrawing {
  const r = reader('thing_kind_invalid');
  const body = r.object(value, 'kind');
  if (body['profile'] !== THING_KIND_PROFILE) r.fail('profile', `is not ${THING_KIND_PROFILE}`);
  const kindClass = r.text(body['class'], 'class');
  if (kindClass !== 'being' && kindClass !== 'object') r.fail('class', 'is neither being nor object');
  const bodyRow = r.object(body['body'], 'body');
  const plan = r.text(bodyRow['plan'], 'body.plan', PLAN);
  const heightRow = bodyRow['height_mm'];
  const boxRow = bodyRow['box_mm'];
  const height = heightRow === undefined ? null : (() => {
    const h = r.object(heightRow, 'body.height_mm');
    const from = r.whole(h['from'], 'body.height_mm.from', 1);
    const to = r.whole(h['to'], 'body.height_mm.to', from);
    return Object.freeze({ from, to });
  })();
  const box = boxRow === undefined ? null : (() => {
    const b = r.object(boxRow, 'body.box_mm');
    return Object.freeze({ width: r.whole(b['width'], 'body.box_mm.width', 1), depth: r.whole(b['depth'], 'body.box_mm.depth', 1), height: r.whole(b['height'], 'body.box_mm.height', 1) });
  })();
  const radius = bodyRow['radius_mm'] === undefined ? null : r.whole(bodyRow['radius_mm'], 'body.radius_mm', 1);
  let grip: Grip | null = null;
  for (const [i, offer] of r.list(body['offers'] ?? [], 'offers').entries()) {
    const row = r.object(offer, `offers[${i}]`);
    if (row['key'] !== 'holdable') continue;
    const parameters = r.object(row['parameters'], `offers[${i}].parameters`);
    const g = r.object(parameters['grip'], `offers[${i}].parameters.grip`);
    const axis = r.text(parameters['axis'], `offers[${i}].parameters.axis`);
    if (!(AXES as readonly string[]).includes(axis)) r.fail(`offers[${i}].parameters.axis`, 'is not one of the six axes');
    const signed = (v: unknown, f: string) => (typeof v === 'number' && Number.isSafeInteger(v) ? v : r.fail(f, 'is not a whole number'));
    grip = Object.freeze({
      x_mm: signed(g['x_mm'], `offers[${i}].parameters.grip.x_mm`),
      y_mm: signed(g['y_mm'], `offers[${i}].parameters.grip.y_mm`),
      z_mm: signed(g['z_mm'], `offers[${i}].parameters.grip.z_mm`),
      axis: axis as Grip['axis'],
    });
  }
  return Object.freeze({
    kind: r.text(body['kind'], 'kind', KEY),
    version: r.whole(body['version'], 'version', 1),
    label: r.text(body['label'], 'label'),
    class: kindClass as 'being' | 'object',
    bodyPlan: plan,
    heightMm: height,
    radiusMm: radius,
    boxMm: box,
    grip,
    looks: Object.freeze(r.list(body['looks'], 'looks').map((look, i) => r.reference(look, `looks[${i}]`, 'look'))),
  });
}

/** Read what drawing needs of a look document. */
export function readLookDrawing(value: unknown): LookDrawing {
  const r = reader('look_invalid');
  const body = r.object(value, 'look');
  if (body['profile'] !== LOOK_PROFILE) r.fail('profile', `is not ${LOOK_PROFILE}`);
  const sampling = r.text(body['sampling'], 'sampling');
  if (sampling !== 'linear' && sampling !== 'nearest') r.fail('sampling', 'is neither linear nor nearest');
  const lightRow = body['light'] ?? null;
  const light = lightRow === null ? null : (() => {
    const l = r.object(lightRow, 'light');
    return Object.freeze({
      colour: r.text(l['colour'], 'light.colour', COLOUR),
      intensityMilli: r.whole(l['intensity_milli'], 'light.intensity_milli', 1),
      radiusMm: r.whole(l['radius_mm'], 'light.radius_mm', 1),
    });
  })();
  const rigRow = body['rig'] ?? null;
  const rig = rigRow === null ? null : (() => {
    const g = r.object(rigRow, 'rig');
    const names = (v: unknown, f: string): Readonly<Record<string, string>> => {
      const row = r.object(v ?? {}, f);
      return Object.freeze(Object.fromEntries(Object.entries(row).map(([k, name]) => [k, r.text(name, `${f}.${k}`)])));
    };
    const speeds = r.object(g['ground_speed_mm_per_s'] ?? {}, 'rig.ground_speed_mm_per_s');
    return Object.freeze({
      bones: names(g['bones'], 'rig.bones'),
      clips: names(g['clips'], 'rig.clips'),
      sockets: names(g['sockets'], 'rig.sockets'),
      groundSpeedMmPerS: Object.freeze(Object.fromEntries(Object.entries(speeds).map(([k, v]) => [k, r.whole(v, `rig.ground_speed_mm_per_s.${k}`, 1)]))),
    });
  })();
  const height = body['height_mm'] ?? null;
  return Object.freeze({
    look: r.text(body['look'], 'look', KEY),
    version: r.whole(body['version'], 'version', 1),
    label: r.text(body['label'], 'label'),
    bodyPlan: r.text(body['body_plan'], 'body_plan', PLAN),
    lookKind: r.text(body['look_kind'], 'look_kind', KEY),
    container: r.container(body['container'] ?? null, 'container'),
    rig,
    heightMm: height === null ? null : r.whole(height, 'height_mm', 1),
    sampling: sampling as 'linear' | 'nearest',
    light,
    role: body['role'] === null || body['role'] === undefined ? null : r.text(body['role'], 'role'),
  });
}

/** Read the body plans catalog into entries the skeleton reads, by `key/vN`. */
export function readBodyPlans(value: unknown): ReadonlyMap<string, BodyPlanEntry> {
  const r = reader('body_plans_invalid');
  const body = r.object(value, 'catalog');
  if (body['catalog_id'] !== 'body-plans') r.fail('catalog_id', 'is not body-plans');
  const plans = new Map<string, BodyPlanEntry>();
  for (const [i, entry] of r.list(body['entries'], 'entries').entries()) {
    const row = r.object(entry, `entries[${i}]`);
    const key = r.text(row['key'], `entries[${i}].key`, KEY);
    const version = r.whole(row['version'], `entries[${i}].version`, 1);
    const bones = r.list(row['bones'], `entries[${i}].bones`).map((bone, j): PlanBone => {
      const b = r.object(bone, `entries[${i}].bones[${j}]`);
      const parent = b['parent'] === null ? null : r.text(b['parent'], `entries[${i}].bones[${j}].parent`);
      if (typeof b['required'] !== 'boolean') r.fail(`entries[${i}].bones[${j}].required`, 'is not true or false');
      return Object.freeze({ name: r.text(b['name'], `entries[${i}].bones[${j}].name`), parent, required: b['required'] as boolean });
    });
    const sockets = r.list(row['sockets'], `entries[${i}].sockets`).map((socket, j): PlanSocket => {
      const s = r.object(socket, `entries[${i}].sockets[${j}]`);
      return Object.freeze({
        key: r.text(s['key'], `entries[${i}].sockets[${j}].key`),
        bone: s['bone'] === null ? null : r.text(s['bone'], `entries[${i}].sockets[${j}].bone`),
        holds: r.whole(s['holds'], `entries[${i}].sockets[${j}].holds`, 1),
        length_mm_maximum: r.whole(s['length_mm_maximum'], `entries[${i}].sockets[${j}].length_mm_maximum`, 1),
        grip_section_mm_maximum: s['grip_section_mm_maximum'] === null ? null : r.whole(s['grip_section_mm_maximum'], `entries[${i}].sockets[${j}].grip_section_mm_maximum`, 1),
      });
    });
    const names = new Set(bones.map((b) => b.name));
    if (names.size !== bones.length) r.fail(`entries[${i}].bones`, 'names a bone twice');
    for (const [j, b] of bones.entries()) if (b.parent !== null && !names.has(b.parent)) r.fail(`entries[${i}].bones[${j}].parent`, `names no bone of ${key}/v${version}`);
    for (const [j, s] of sockets.entries()) if (s.bone !== null && !names.has(s.bone)) r.fail(`entries[${i}].sockets[${j}].bone`, `names no bone of ${key}/v${version}`);
    plans.set(`${key}/v${version}`, Object.freeze({ key, version, bones: Object.freeze(bones), sockets: Object.freeze(sockets) }));
  }
  return plans;
}

/**
 * The height a body with a look is drawn at: the look's natural height, kept inside the kind's
 * height range, so swapping looks never makes a kind's thing taller or shorter than its kind allows.
 */
export function drawnHeightMm(kind: KindDrawing, look: LookDrawing): number | null {
  const natural = look.heightMm;
  if (kind.heightMm === null) return natural;
  if (natural === null) return kind.heightMm.from;
  return Math.min(kind.heightMm.to, Math.max(kind.heightMm.from, natural));
}

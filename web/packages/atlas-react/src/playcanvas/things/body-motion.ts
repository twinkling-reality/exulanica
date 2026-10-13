/**
 * The figures a drafted body's motion is drawn by, read from the one data file that states each
 * with its reason: `assets/catalogs/thing-presentation/body-motion.v2.json`, or its first version
 * (`body-motion.v1.json`), which states no postures.
 *
 * Presentation only: nothing here changes where a society records a being, what it does or what it
 * says. A page that hands the drawing no table draws a drafted body's legs and arms as it draws
 * anyone's and holds every other stated chain at rest; a table with no postures draws every body
 * standing, whatever its state says it is doing.
 */

export const BODY_MOTION_PROFILE = 'exulanica.body-motion/v1';
/** The second version: the first's figures, and the postures a body is drawn in by what it is doing. */
export const BODY_MOTION_V2_PROFILE = 'exulanica.body-motion/v2';

/**
 * How a body is drawn while its state says it is doing something: its hips lowered by a share of
 * how far its legs reach down (its feet kept where they stand), a head the plan names bowed, and
 * whether it is drawn speaking. Standing is all three at none.
 */
export interface BodyPosture {
  readonly lowerShare: number;
  readonly headBow: number;
  readonly speaks: boolean;
}

/** Standing: what a body with no posture for what it is doing, or doing nothing, is drawn in. */
export const STANDING: BodyPosture = Object.freeze({ lowerShare: 0, headBow: 0, speaks: false });

/** The postures of a table, the activity each is drawn for, and how long a body takes to settle into one. */
export interface BodyPostures {
  readonly blendSeconds: number;
  readonly postures: ReadonlyMap<string, BodyPosture>;
  /** Activity key (a society's `action.kind`) to posture key. */
  readonly activities: ReadonlyMap<string, string>;
}

/** The table as the drawing reads it: radians, seconds, metres, shares from 0 to 1. */
export interface BodyMotion {
  /** Strides a second from which a walk is drawn at its full stride. */
  readonly fullWalkCadence: number;
  /** How far a neck and its head turn to look about, in all, and how long one look to both sides takes. */
  readonly lookAbout: number;
  readonly lookAboutPeriod: number;
  /** How far a head nods while its being speaks, and how many beats of speech a second. */
  readonly nod: number;
  readonly speechBeats: number;
  /** How far a jaw opens on a beat of speech. */
  readonly jawOpen: number;
  /** How far each joint of a tail or a hanging tentacle bends in its wave, the wave's period, and how far each next joint runs behind, in cycles. */
  readonly wave: number;
  readonly wavePeriod: number;
  readonly waveLag: number;
  /** The share of the way to the body's back a wing's segments are folded, how far below level its trailing side hangs, and how far a folded wing settles on a step. */
  readonly wingFold: number;
  readonly wingDroop: number;
  readonly wingSettle: number;
  /** How far a fin sways. */
  readonly finSway: number;
  /** The steepest a legless body's spine turns from its heading in its wave, and the wave's length as a share of the spine's. */
  readonly spineWave: number;
  readonly spineWavelength: number;
  /** The speed, metres a second, the ends of a turning body may sweep at. */
  readonly turnEndSpeed: number;
  /** The postures a body is drawn in by what it is doing; null for a table that states none. */
  readonly postures?: BodyPostures | null;
}

/** The posture a body doing `activity` is drawn in by `motion`: standing where none is stated. */
export function postureFor(motion: BodyMotion | null, activity: string | null | undefined): BodyPosture {
  const table = motion?.postures ?? null;
  if (table === null || activity == null) return STANDING;
  const key = table.activities.get(activity);
  return key === undefined ? STANDING : table.postures.get(key) ?? STANDING;
}

/**
 * A body settling from one posture into the next over the table's blend: its hips and head move
 * from where they were drawn to where the new posture holds them, eased at both ends, and it speaks
 * from the moment the new posture says so. Presentation only, clocked by the drawing's own seconds.
 */
export class PostureBlend {
  private from: BodyPosture = STANDING;
  private to: BodyPosture = STANDING;
  private progress = 1;

  /** The posture drawn now, after `seconds` more toward `wanted`; `atOnce` settles it immediately. */
  step(wanted: BodyPosture, seconds: number, blendSeconds: number, atOnce = false): BodyPosture {
    if (wanted !== this.to) {
      this.from = this.now();
      this.to = wanted;
      this.progress = 0;
    }
    this.progress = atOnce || blendSeconds <= 0 ? 1 : Math.min(1, this.progress + Math.max(0, seconds) / blendSeconds);
    return this.now();
  }

  private now(): BodyPosture {
    const t = this.progress * this.progress * (3 - 2 * this.progress);
    if (t >= 1) return this.to;
    return {
      lowerShare: this.from.lowerShare + (this.to.lowerShare - this.from.lowerShare) * t,
      headBow: this.from.headBow + (this.to.headBow - this.from.headBow) * t,
      speaks: this.to.speaks,
    };
  }
}

/** The ground a body that states its extent covers, metres from its middle: across it, and along the way it faces. */
export interface Footprint {
  readonly halfAcross: number;
  readonly halfAlong: number;
}

/**
 * The footprint of a body whose kind states `extentMm`, drawn at `scale` of it, and the fastest it
 * turns, radians a second: the rate at which the ends of its longer side sweep at the table's
 * speed. Null turn rate with no table: the body then turns at once, as anyone does.
 */
export function bodyGround(extentMm: { readonly length: number; readonly width: number }, scale: number, motion: BodyMotion | null): { readonly footprint: Footprint; readonly turnRate: number | null } {
  const footprint = { halfAcross: (extentMm.width / 2000) * scale, halfAlong: (extentMm.length / 2000) * scale };
  return { footprint, turnRate: motion === null ? null : motion.turnEndSpeed / Math.max(footprint.halfAcross, footprint.halfAlong) };
}

interface Row {
  readonly field: keyof BodyMotion;
  readonly unit: string;
  readonly from: number;
  readonly to: number;
  /** What one unit of the file's value is in the table's own (millimetres to metres). */
  readonly scale?: number;
}

/** Every entry the table needs, by its key in the file, with the unit and the range it is read in. */
const ROWS: Readonly<Record<string, Row>> = {
  full_walk_strides_per_second: { field: 'fullWalkCadence', unit: 'per_second', from: 0.05, to: 10 },
  look_about_rad: { field: 'lookAbout', unit: 'radian', from: 0, to: 1 },
  look_about_period_seconds: { field: 'lookAboutPeriod', unit: 'second', from: 1, to: 600 },
  nod_rad: { field: 'nod', unit: 'radian', from: 0, to: 1 },
  speech_beats_per_second: { field: 'speechBeats', unit: 'per_second', from: 0.1, to: 10 },
  jaw_open_rad: { field: 'jawOpen', unit: 'radian', from: 0, to: 1.5 },
  wave_rad: { field: 'wave', unit: 'radian', from: 0, to: 1 },
  wave_period_seconds: { field: 'wavePeriod', unit: 'second', from: 0.2, to: 600 },
  wave_lag_cycles: { field: 'waveLag', unit: 'cycle', from: 0, to: 1 },
  wing_fold_share: { field: 'wingFold', unit: 'share', from: 0, to: 1 },
  wing_droop_rad: { field: 'wingDroop', unit: 'radian', from: 0, to: 1.5708 },
  wing_settle_rad: { field: 'wingSettle', unit: 'radian', from: 0, to: 0.5 },
  fin_sway_rad: { field: 'finSway', unit: 'radian', from: 0, to: 1 },
  spine_wave_rad: { field: 'spineWave', unit: 'radian', from: 0, to: 1.2 },
  spine_wavelength_share: { field: 'spineWavelength', unit: 'share', from: 0.1, to: 1 },
  turn_end_speed_mm_per_second: { field: 'turnEndSpeed', unit: 'millimetre_per_second', from: 100, to: 100_000, scale: 0.001 },
};

/** Each figure of a posture, by its key in the file, with the range it is read in. */
const POSTURE_FIGURES = {
  lower_share: { from: 0, to: 0.6 },
  head_bow_rad: { from: 0, to: 0.8 },
} as const;

/** Read the body motion catalog, either version, or refuse it by what is wrong with it. */
export function readBodyMotion(value: unknown): BodyMotion {
  const refuse = (what: string): never => {
    throw new Error(`body motion catalog: ${what}`);
  };
  if (typeof value !== 'object' || value === null || Array.isArray(value)) refuse('is not a document');
  const document = value as {
    readonly profile?: unknown; readonly entries?: unknown;
    readonly posture_blend?: unknown; readonly postures?: unknown; readonly activity_postures?: unknown;
  };
  if (document.profile !== BODY_MOTION_PROFILE && document.profile !== BODY_MOTION_V2_PROFILE) {
    refuse(`is neither ${BODY_MOTION_PROFILE} nor ${BODY_MOTION_V2_PROFILE}`);
  }
  if (!Array.isArray(document.entries)) refuse('states no entries');
  const table: Partial<Record<keyof BodyMotion, number>> = {};
  for (const raw of document.entries as readonly unknown[]) {
    const entry = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
    const key = entry['key'];
    const row = typeof key === 'string' && Object.hasOwn(ROWS, key) ? ROWS[key]! : refuse(`states an entry this page does not read: ${String(key)}`);
    if (table[row.field] !== undefined) refuse(`states ${String(key)} twice`);
    if (entry['unit'] !== row.unit) refuse(`${String(key)} is not in ${row.unit}`);
    const stated = entry['value'];
    if (typeof stated !== 'number' || !Number.isFinite(stated) || stated < row.from || stated > row.to) {
      refuse(`${String(key)} is not a figure from ${row.from} to ${row.to}`);
    }
    if (typeof entry['class'] !== 'string' || typeof entry['reason'] !== 'string' || entry['reason'].length === 0) {
      refuse(`${String(key)} states no class or no reason`);
    }
    table[row.field] = (stated as number) * (row.scale ?? 1);
  }
  for (const [key, row] of Object.entries(ROWS)) if (table[row.field] === undefined) refuse(`states no ${key}`);
  const postures = document.profile === BODY_MOTION_V2_PROFILE ? readPostures(document, refuse) : null;
  return Object.freeze({ ...(table as Omit<BodyMotion, 'postures'>), postures });
}

const record = (raw: unknown): Record<string, unknown> =>
  (typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;

/** The postures a second version states: every one with its reason, and every activity naming one stated. */
function readPostures(
  document: { readonly posture_blend?: unknown; readonly postures?: unknown; readonly activity_postures?: unknown },
  refuse: (what: string) => never,
): BodyPostures {
  const blend = record(document.posture_blend);
  const seconds = blend['value'];
  if (blend['unit'] !== 'second' || typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0.05 || seconds > 10) {
    refuse('posture_blend is not a figure of seconds from 0.05 to 10');
  }
  if (typeof blend['class'] !== 'string' || typeof blend['reason'] !== 'string' || blend['reason'].length === 0) {
    refuse('posture_blend states no class or no reason');
  }
  if (!Array.isArray(document.postures) || document.postures.length === 0) refuse('states no postures');
  const postures = new Map<string, BodyPosture>();
  for (const raw of document.postures as readonly unknown[]) {
    const entry = record(raw);
    const key = entry['key'];
    if (typeof key !== 'string' || key.length === 0) refuse('states a posture with no key');
    if (postures.has(key as string)) refuse(`states the posture ${String(key)} twice`);
    const figures: Partial<Record<keyof typeof POSTURE_FIGURES, number>> = {};
    for (const [name, range] of Object.entries(POSTURE_FIGURES) as [keyof typeof POSTURE_FIGURES, { from: number; to: number }][]) {
      const stated = entry[name];
      if (typeof stated !== 'number' || !Number.isFinite(stated) || stated < range.from || stated > range.to) {
        refuse(`the posture ${String(key)}'s ${name} is not a figure from ${range.from} to ${range.to}`);
      }
      figures[name] = stated as number;
    }
    if (typeof entry['speaks'] !== 'boolean') refuse(`the posture ${String(key)} does not say whether it speaks`);
    if (typeof entry['class'] !== 'string' || typeof entry['reason'] !== 'string' || entry['reason'].length === 0) {
      refuse(`the posture ${String(key)} states no class or no reason`);
    }
    postures.set(key as string, Object.freeze({
      lowerShare: figures.lower_share!, headBow: figures.head_bow_rad!, speaks: entry['speaks'] as boolean,
    }));
  }
  if (!Array.isArray(document.activity_postures)) refuse('states no activity_postures');
  const activities = new Map<string, string>();
  for (const raw of document.activity_postures as readonly unknown[]) {
    const entry = record(raw);
    const activity = entry['activity'];
    const posture = entry['posture'];
    if (typeof activity !== 'string' || activity.length === 0) refuse('names a posture for no activity');
    if (activities.has(activity as string)) refuse(`names a posture for ${String(activity)} twice`);
    if (typeof posture !== 'string' || !postures.has(posture)) refuse(`draws ${String(activity)} in a posture it does not state`);
    if (typeof entry['reason'] !== 'string' || entry['reason'].length === 0) refuse(`gives no reason for drawing ${String(activity)} so`);
    activities.set(activity as string, posture as string);
  }
  return Object.freeze({ blendSeconds: seconds as number, postures, activities });
}

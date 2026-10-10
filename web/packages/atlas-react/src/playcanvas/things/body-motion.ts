/**
 * The figures a drafted body's motion is drawn by, read from the one data file that states each
 * with its reason: `assets/catalogs/thing-presentation/body-motion.v1.json`.
 *
 * Presentation only: nothing here changes where a society records a being, what it does or what it
 * says. A page that hands the drawing no table draws a drafted body's legs and arms as it draws
 * anyone's and holds every other stated chain at rest.
 */

export const BODY_MOTION_PROFILE = 'exulanica.body-motion/v1';

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

/** Read the body motion catalog, or refuse it by what is wrong with it. */
export function readBodyMotion(value: unknown): BodyMotion {
  const refuse = (what: string): never => {
    throw new Error(`body motion catalog: ${what}`);
  };
  if (typeof value !== 'object' || value === null || Array.isArray(value)) refuse('is not a document');
  const document = value as { readonly profile?: unknown; readonly entries?: unknown };
  if (document.profile !== BODY_MOTION_PROFILE) refuse(`is not ${BODY_MOTION_PROFILE}`);
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
  return Object.freeze(table as BodyMotion);
}

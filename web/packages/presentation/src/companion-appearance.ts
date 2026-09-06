/**
 * Versioned Companion appearance data. Visual identity is a device preference, never graph fact.
 *
 * Version three replaces the rejected humanoid primitive with the verified geometric-avatar
 * grammar used by Grok Bot and documented by the MIT-licensed Bloub reference implementation:
 * one silhouette and two slit eyes, with no torso, limbs, mouth, antenna, halo, or 3D renderer.
 */
export type CompanionOperationalState =
  | 'resting'
  | 'attending'
  | 'uncertain'
  | 'working'
  | 'settled';

/*
 * The catalogs are the single source of truth for what a person may choose.
 *
 * The variant types are derived from these arrays rather than written beside them, and the
 * geometry and colour tables below are total records over those types. Adding an entry here is
 * therefore a compile error until it has a silhouette, an eye pose or a colour pair, and the app's
 * option lists and preference validator read these same arrays. Before this, the three axes were
 * declared in three places that derived from nothing, so a variant could validate in one and
 * silently reset in another.
 *
 * Order is presentation order. It is what Customize lists, so it is part of the contract.
 */
export const COMPANION_BODY_VARIANTS = Object.freeze([
  'circle',
  'pebble',
  'squircle',
  'capsule',
  'cloud',
  'droplet',
  'arch',
  'bead',
  'lozenge',
] as const);

export const COMPANION_COLOR_VARIANTS = Object.freeze([
  'ink',
  'rose',
  'orange',
  'periwinkle',
  'mint',
  'ember',
  'iris',
  'slate',
] as const);

export const COMPANION_FACE_VARIANTS = Object.freeze([
  'neutral',
  'attentive',
  'curious',
  'happy',
  'sleepy',
  'wide',
  'wink',
  'focused',
] as const);

export type CompanionBodyVariant = (typeof COMPANION_BODY_VARIANTS)[number];
export type CompanionColorVariant = (typeof COMPANION_COLOR_VARIANTS)[number];
export type CompanionFaceVariant = (typeof COMPANION_FACE_VARIANTS)[number];

export interface CompanionAppearanceConfigurationV3 {
  readonly companionModelVersion: 3;
  readonly bodyVariant: CompanionBodyVariant;
  readonly colorVariant: CompanionColorVariant;
  readonly faceVariant: CompanionFaceVariant;
  readonly bodyColor: string;
  readonly eyeColor: string;
  readonly motionProfile: 'gaze-and-blink';
  readonly reducedMotionProfile: 'still-expression';
}

export type CompanionAppearanceConfiguration = CompanionAppearanceConfigurationV3;

const BODY = new Set<CompanionBodyVariant>(COMPANION_BODY_VARIANTS);
const COLOR = new Set<CompanionColorVariant>(COMPANION_COLOR_VARIANTS);
const FACE = new Set<CompanionFaceVariant>(COMPANION_FACE_VARIANTS);
const COLORS: Readonly<Record<CompanionColorVariant, readonly [string, string]>> = Object.freeze({
  ink: ['#0a0a0c', '#f7f5ef'],
  rose: ['#f13f8e', '#28101b'],
  orange: ['#ff8a35', '#2b1405'],
  periwinkle: ['#637ff2', '#0c1747'],
  mint: ['#43caa9', '#062a25'],
  ember: ['#e2483a', '#2c0c08'],
  iris: ['#8b5cf0', '#180b33'],
  slate: ['#5b6e7a', '#eef3f5'],
});

export interface CompanionAppearanceSelection {
  readonly body: CompanionBodyVariant;
  readonly color: CompanionColorVariant;
  readonly face: CompanionFaceVariant;
}

export function companionAppearanceConfiguration(
  selection: CompanionAppearanceSelection,
): CompanionAppearanceConfiguration {
  const [bodyColor, eyeColor] = COLORS[selection.color];
  return Object.freeze({
    companionModelVersion: 3,
    bodyVariant: selection.body,
    colorVariant: selection.color,
    faceVariant: selection.face,
    bodyColor,
    eyeColor,
    motionProfile: 'gaze-and-blink',
    reducedMotionProfile: 'still-expression',
  });
}

/*
 * The resting presence.
 *
 * It was pink because pink was the avatar in a supplied reference crop, which is a reason to
 * offer the colour and not a reason to make it the default. Against a world made of light it was
 * the most saturated thing on screen by a distance and read as a sticker on the field. Ink is the
 * same near-black the rest of the interface reads in, so the Companion arrives belonging to the
 * world. Every other colour stays one click away in Customize, and this choice is a device
 * preference: it never enters a style version or a graph assertion.
 */
export const DEFAULT_COMPANION = companionAppearanceConfiguration({
  body: 'circle',
  color: 'ink',
  face: 'neutral',
});

/** Compatibility names for callers that persisted the earlier native experiment. */
export const DEFAULT_NATIVE_COMPANION = DEFAULT_COMPANION;
export const NATIVE_COMPANION_PROTOTYPE = DEFAULT_COMPANION;

export interface CompanionAppearanceResolution {
  readonly configuration: CompanionAppearanceConfiguration;
  readonly issues: readonly string[];
}

export function resolveCompanionAppearance(value: unknown): CompanionAppearanceResolution {
  if (typeof value !== 'object' || value === null) {
    return { configuration: DEFAULT_COMPANION, issues: ['configuration-not-an-object'] };
  }
  const record = value as Record<string, unknown>;
  if (record['companionModelVersion'] === 1 || record['companionModelVersion'] === 2) {
    return { configuration: DEFAULT_COMPANION, issues: ['migrated-rejected-prototype'] };
  }
  if (record['companionModelVersion'] !== 3) {
    return { configuration: DEFAULT_COMPANION, issues: ['unsupported-model-version'] };
  }
  const body = record['bodyVariant'] as CompanionBodyVariant;
  const color = record['colorVariant'] as CompanionColorVariant;
  const face = record['faceVariant'] as CompanionFaceVariant;
  if (!BODY.has(body) || !COLOR.has(color) || !FACE.has(face)) {
    return { configuration: DEFAULT_COMPANION, issues: ['invalid-v3-configuration'] };
  }
  return {
    configuration: companionAppearanceConfiguration({ body, color, face }),
    issues: [],
  };
}

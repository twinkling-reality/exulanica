/** Versioned device preferences. The authored Atlas landscape is not a theme picker. */

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  productWorldStyleReferences,
  resolveWorldStyleParameters,
  type CompanionBodyVariant,
  type CompanionColorVariant,
  type CompanionFaceVariant,
  type WorldArtProfileId,
  type WorldStyleParameters,
} from '@exulanica/presentation';

export const PREFERENCES_KEY = 'exulanica.atlas.preferences.v1';

export type AppearancePreference = 'dawn';
export type ContrastPreference = 'standard' | 'high';
export type TransparencyPreference = 'layered' | 'reduced';
export type VignettePreference = 'off' | 'subtle' | 'strong';
export type TurnPreference = 'smooth' | 'snap';
export type TransitionPreference = 'system' | 'motion' | 'fade';
export type CompanionInitiativePreference = 'normal' | 'minimal' | 'off';
/*
 * Companion appearance is the versioned V3 family, so these names are the contract's, not a second
 * copy of it. A copy is how a variant comes to validate in presentation and reset here.
 */
export type CompanionBodyPreference = CompanionBodyVariant;
export type CompanionColorPreference = CompanionColorVariant;
export type CompanionFacePreference = CompanionFaceVariant;

export interface AtlasPreferences {
  readonly version: 1;
  readonly appearance: AppearancePreference;
  readonly contrast: ContrastPreference;
  readonly transparency: TransparencyPreference;
  readonly worldArtProfile: WorldArtProfileId;
  readonly worldArtProfileVersion: number;
  readonly worldStyleParameters: WorldStyleParameters;
  readonly fieldOfView: number;
  /** Multiplier over the measured default rather than engine units exposed as a user setting. */
  readonly mouseSensitivity: number;
  readonly vignette: VignettePreference;
  readonly cameraBob: boolean;
  /**
   * A region plan held in the corner while traversing.
   *
   * Off by default, deliberately. The world is meant to be its own coordinate system, so the
   * beacons and the field come first and this is the fallback for anyone the world does not
   * orient on its own. A toggle is not the permanent HUD the design rules out; a default-on one
   * would be.
   */
  readonly regionMinimap: boolean;
  readonly turnMode: TurnPreference;
  readonly transition: TransitionPreference;
  readonly companionInitiative: CompanionInitiativePreference;
  readonly companionBody: CompanionBodyPreference;
  readonly companionColor: CompanionColorPreference;
  readonly companionFace: CompanionFacePreference;
  /** Retained for version-one preference compatibility; the encounter now has a fixed composition. */
  readonly companionSide: 'left' | 'right';
}

export const DEFAULT_PREFERENCES: AtlasPreferences = Object.freeze({
  version: 1,
  appearance: 'dawn',
  contrast: 'standard',
  transparency: 'layered',
  worldArtProfile: 'origin-landscape',
  worldArtProfileVersion: 1,
  worldStyleParameters: resolveWorldStyleParameters('origin-landscape'),
  fieldOfView: 70,
  mouseSensitivity: 1,
  vignette: 'subtle',
  cameraBob: false,
  regionMinimap: false,
  turnMode: 'smooth',
  transition: 'system',
  companionInitiative: 'normal',
  companionBody: 'circle',
  companionColor: 'ink',
  companionFace: 'neutral',
  companionSide: 'right',
});

interface PreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const APPEARANCE = new Set<AppearancePreference>(['dawn']);
const CONTRAST = new Set<ContrastPreference>(['standard', 'high']);
const TRANSPARENCY = new Set<TransparencyPreference>(['layered', 'reduced']);
// Alternate profiles remain renderer test fixtures. Stored legacy choices return to the one
// authored product identity instead of silently keeping an abandoned experimental treatment.
const WORLD_ART_PROFILE = new Set(productWorldStyleReferences().map(
  (reference) => `${reference.profileId}@${reference.profileVersion}`,
));
const VIGNETTE = new Set<VignettePreference>(['off', 'subtle', 'strong']);
const TURN = new Set<TurnPreference>(['smooth', 'snap']);
const TRANSITION = new Set<TransitionPreference>(['system', 'motion', 'fade']);
const INITIATIVE = new Set<CompanionInitiativePreference>(['normal', 'minimal', 'off']);
const COMPANION_BODY = new Set<CompanionBodyPreference>(COMPANION_BODY_VARIANTS);
const COMPANION_COLOR = new Set<CompanionColorPreference>(COMPANION_COLOR_VARIANTS);
const COMPANION_FACE = new Set<CompanionFacePreference>(COMPANION_FACE_VARIANTS);

const finiteIn = (value: unknown, min: number, max: number): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max;

/** Invalid or newer data falls back field by field; one bad value never bricks the menu. */
export function normalisePreferences(value: unknown): AtlasPreferences {
  const record = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
  const requestedWorldProfile = typeof record['worldArtProfile'] === 'string'
    ? record['worldArtProfile']
    : DEFAULT_PREFERENCES.worldArtProfile;
  const requestedWorldProfileVersion = Number.isSafeInteger(record['worldArtProfileVersion']) &&
    (record['worldArtProfileVersion'] as number) > 0
    ? (record['worldArtProfileVersion'] as number)
    : DEFAULT_PREFERENCES.worldArtProfileVersion;
  const worldProfileAvailable = WORLD_ART_PROFILE.has(
    `${requestedWorldProfile}@${requestedWorldProfileVersion}`,
  );
  const worldArtProfile = worldProfileAvailable
    ? requestedWorldProfile
    : DEFAULT_PREFERENCES.worldArtProfile;
  const worldArtProfileVersion = worldProfileAvailable
    ? requestedWorldProfileVersion
    : DEFAULT_PREFERENCES.worldArtProfileVersion;
  const companionV3 = COMPANION_BODY.has(record['companionBody'] as CompanionBodyPreference) &&
    COMPANION_COLOR.has(record['companionColor'] as CompanionColorPreference) &&
    COMPANION_FACE.has(record['companionFace'] as CompanionFacePreference);
  return Object.freeze({
    version: 1,
    appearance: APPEARANCE.has(record['appearance'] as AppearancePreference)
      ? (record['appearance'] as AppearancePreference)
      : DEFAULT_PREFERENCES.appearance,
    contrast: CONTRAST.has(record['contrast'] as ContrastPreference)
      ? (record['contrast'] as ContrastPreference)
      : DEFAULT_PREFERENCES.contrast,
    transparency: TRANSPARENCY.has(record['transparency'] as TransparencyPreference)
      ? (record['transparency'] as TransparencyPreference)
      : DEFAULT_PREFERENCES.transparency,
    worldArtProfile,
    worldArtProfileVersion,
    worldStyleParameters: resolveWorldStyleParameters(
      worldArtProfile,
      worldProfileAvailable &&
      typeof record['worldStyleParameters'] === 'object' && record['worldStyleParameters'] !== null
        ? (record['worldStyleParameters'] as Readonly<Record<string, unknown>>)
        : {},
      worldArtProfileVersion,
    ),
    fieldOfView: finiteIn(record['fieldOfView'], 60, 90)
      ? record['fieldOfView']
      : DEFAULT_PREFERENCES.fieldOfView,
    mouseSensitivity: finiteIn(record['mouseSensitivity'], 0.5, 2)
      ? record['mouseSensitivity']
      : DEFAULT_PREFERENCES.mouseSensitivity,
    vignette: VIGNETTE.has(record['vignette'] as VignettePreference)
      ? (record['vignette'] as VignettePreference)
      : DEFAULT_PREFERENCES.vignette,
    cameraBob:
      typeof record['cameraBob'] === 'boolean'
        ? record['cameraBob']
        : DEFAULT_PREFERENCES.cameraBob,
    regionMinimap:
      typeof record['regionMinimap'] === 'boolean'
        ? record['regionMinimap']
        : DEFAULT_PREFERENCES.regionMinimap,
    turnMode: TURN.has(record['turnMode'] as TurnPreference)
      ? (record['turnMode'] as TurnPreference)
      : DEFAULT_PREFERENCES.turnMode,
    transition: TRANSITION.has(record['transition'] as TransitionPreference)
      ? (record['transition'] as TransitionPreference)
      : DEFAULT_PREFERENCES.transition,
    companionInitiative: INITIATIVE.has(
      record['companionInitiative'] as CompanionInitiativePreference,
    )
      ? (record['companionInitiative'] as CompanionInitiativePreference)
      : DEFAULT_PREFERENCES.companionInitiative,
    companionBody: companionV3
      ? (record['companionBody'] as CompanionBodyPreference)
      : DEFAULT_PREFERENCES.companionBody,
    companionColor: companionV3
      ? (record['companionColor'] as CompanionColorPreference)
      : DEFAULT_PREFERENCES.companionColor,
    companionFace: companionV3
      ? (record['companionFace'] as CompanionFacePreference)
      : DEFAULT_PREFERENCES.companionFace,
    companionSide:
      record['companionSide'] === 'left' || record['companionSide'] === 'right'
        ? record['companionSide']
        : DEFAULT_PREFERENCES.companionSide,
  });
}

export function readPreferences(storage: PreferenceStorage): AtlasPreferences {
  try {
    const encoded = storage.getItem(PREFERENCES_KEY);
    return encoded === null ? DEFAULT_PREFERENCES : normalisePreferences(JSON.parse(encoded));
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

export function writePreferences(storage: PreferenceStorage, value: AtlasPreferences): void {
  storage.setItem(PREFERENCES_KEY, JSON.stringify(normalisePreferences(value)));
}

export function resolvedAppearance(
  preference: AppearancePreference,
  _systemDark: boolean,
): AppearancePreference {
  return preference;
}

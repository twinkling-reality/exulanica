/**
 * The reviewed interaction settings, as data: what each one is, which preference holds it, and
 * which the settings page offers.
 *
 * The capabilities, their ranges, choices and defaults, and whether the settings page offers each,
 * are the server's registry (`exulanica/world/interaction-policy-registry.v1.json`). The settings
 * page draws its controls from `GET /world/interactions/catalog`, which serves that registry; the
 * device's stored preferences are checked against the same file as it is bundled, because they are
 * read before any request can answer. Nothing here restates a range or a choice. What the page adds
 * is its own: the preference field each capability is held in on this device, and the words each
 * control is shown with (held to the registry by interaction-settings.test.ts).
 */

import registryText from '../../../../exulanica/world/interaction-policy-registry.v1.json?raw';
/** A capability's value, as the registry types it. */
export type InteractionValue = boolean | number | string;

/** Device preferences as this module reads them: by field name, never by their own module. */
type Preferences = object;

export type CapabilityKind = 'integer' | 'choice' | 'toggle';

/** One reviewed capability, as the registry states it and the catalog serves it. */
export interface InteractionCapability {
  readonly key: string;
  readonly kind: CapabilityKind;
  readonly default: InteractionValue;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly choices: readonly string[];
  /** Whether the settings page offers a control for it. */
  readonly shownInSettings: boolean;
}

const KINDS: readonly CapabilityKind[] = ['integer', 'choice', 'toggle'];

/** The capabilities of a registry document or a served catalog, or a refusal naming the defect. */
export function readCapabilities(document: unknown): readonly InteractionCapability[] {
  const capabilities = (document as { capabilities?: unknown } | null)?.capabilities;
  if (!Array.isArray(capabilities)) throw new Error('not an interaction capability catalog');
  return capabilities.map((raw: Record<string, unknown>): InteractionCapability => {
    const kind = KINDS.find((known) => known === raw['kind']);
    if (typeof raw['key'] !== 'string' || kind === undefined || typeof raw['shown_in_settings'] !== 'boolean') {
      throw new Error(`an interaction capability is malformed: ${String(raw['key'])}`);
    }
    return Object.freeze({
      key: raw['key'],
      kind,
      default: raw['default'] as InteractionValue,
      minimum: typeof raw['minimum'] === 'number' ? raw['minimum'] : null,
      maximum: typeof raw['maximum'] === 'number' ? raw['maximum'] : null,
      choices: Object.freeze(Array.isArray(raw['choices']) ? raw['choices'].map(String) : []),
      shownInSettings: raw['shown_in_settings'],
    });
  });
}

/** The registry as bundled: the file the server reads, for checks made before any request. */
export const REGISTRY: ReadonlyMap<string, InteractionCapability> = new Map(
  readCapabilities(JSON.parse(registryText)).map((capability) => [capability.key, capability]),
);

function registered(key: string): InteractionCapability {
  const capability = REGISTRY.get(key);
  if (capability === undefined) throw new Error(`the interaction registry states no ${key}`);
  return capability;
}

/** Whether `value` is one of the capability's choices. */
export function isChoiceOf(key: string, value: unknown): value is string {
  return typeof value === 'string' && registered(key).choices.includes(value);
}

/**
 * How a capability is held in this device's preferences, both ways. `scale` is how many of the
 * capability's units one unit of the preference is (the look sensitivity is stored in thousandths).
 * `transition` is the one preference with a value of the device's own: `system` follows the
 * operating system's reduced-motion setting, and is sent as the choice it resolves to.
 */
export interface PreferenceBinding {
  /** The preference's field in `AtlasPreferences` (preferences.ts). */
  readonly field: string;
  readonly scale?: number;
  readonly followsSystem?: { readonly value: string; readonly reduced: string; readonly full: string };
}

/**
 * Each capability's preference field, or null for one this device holds no preference for.
 * `disclosure.provenance-detail` is null: nothing on the page reads it.
 */
export const PREFERENCE_BINDINGS: Readonly<Record<string, PreferenceBinding | null>> = {
  'comfort.field-of-view-degrees': { field: 'fieldOfView' },
  'comfort.look-sensitivity-milli': { field: 'mouseSensitivity', scale: 1000 },
  'comfort.vignette': { field: 'vignette' },
  'comfort.camera-bob': { field: 'cameraBob' },
  'navigation.turn-mode': { field: 'turnMode' },
  'navigation.transition-style': {
    field: 'transition',
    followsSystem: { value: 'system', reduced: 'fade', full: 'motion' },
  },
  'disclosure.provenance-detail': null,
  'initiative.mode': { field: 'companionInitiative' },
};

/** The capability value a preference holds, as the server is sent it. */
export function capabilityValue(
  binding: PreferenceBinding,
  preferences: Preferences,
  systemReducedMotion: boolean,
): InteractionValue {
  const value = (preferences as Readonly<Record<string, unknown>>)[binding.field] as InteractionValue;
  if (binding.followsSystem !== undefined && value === binding.followsSystem.value) {
    return systemReducedMotion ? binding.followsSystem.reduced : binding.followsSystem.full;
  }
  return binding.scale === undefined ? value : Math.round((value as number) * binding.scale);
}

/** The preference a capability value is held as, or undefined for a value the registry refuses. */
export function preferenceValue(key: string, value: unknown): InteractionValue | undefined {
  const capability = registered(key);
  const binding = PREFERENCE_BINDINGS[key];
  if (binding === null || binding === undefined) return undefined;
  switch (capability.kind) {
    case 'toggle':
      return typeof value === 'boolean' ? value : undefined;
    case 'choice':
      return isChoiceOf(key, value) ? value : undefined;
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value)
        && capability.minimum !== null && capability.maximum !== null
        && value >= capability.minimum && value <= capability.maximum
        ? value / (binding.scale ?? 1)
        : undefined;
  }
}

/** Whether a stored preference value is one the registry's capability allows, in its own units. */
export function isPreferenceOf(key: string, value: unknown): boolean {
  const binding = PREFERENCE_BINDINGS[key];
  if (binding === null || binding === undefined) return false;
  if (binding.followsSystem !== undefined && value === binding.followsSystem.value) return true;
  const capability = registered(key);
  if (capability.kind === 'integer') {
    return typeof value === 'number' && Number.isFinite(value)
      && capability.minimum !== null && capability.maximum !== null
      && value * (binding.scale ?? 1) >= capability.minimum
      && value * (binding.scale ?? 1) <= capability.maximum;
  }
  return preferenceValue(key, value) !== undefined;
}

/** What a control is shown with. A choice's words are keyed by the registry's choices. */
export interface SettingWords {
  readonly label: string;
  readonly note?: string;
  readonly choices?: Readonly<Record<string, string>>;
  /** How a range control's value is written, in the preference's own units. */
  readonly shown?: (value: number) => string;
  /** The step of a range control, in the preference's own units. */
  readonly step?: number;
}

/** The words of every capability the registry states, shown or not, so showing one needs no code. */
export const SETTING_WORDS: Readonly<Record<string, SettingWords>> = {
  'comfort.field-of-view-degrees': { label: 'Field of view', shown: (value) => `${value}°`, step: 1 },
  'comfort.look-sensitivity-milli': {
    label: 'Look sensitivity', shown: (value) => `${value.toFixed(1)}×`, step: 0.1,
  },
  'comfort.vignette': {
    label: 'Comfort vignette',
    note: 'Darkens the periphery while traversing; it does not hide evidence.',
    choices: { off: 'Off', subtle: 'Subtle', strong: 'Strong' },
  },
  'comfort.camera-bob': { label: 'Camera bob' },
  'navigation.turn-mode': { label: 'Turning', choices: { smooth: 'Smooth', snap: 'Snap' } },
  'navigation.transition-style': { label: 'Transitions', choices: { motion: 'Motion', fade: 'Fade' } },
  'disclosure.provenance-detail': {
    label: 'Provenance detail', choices: { standard: 'Standard', expanded: 'Expanded' },
  },
  'initiative.mode': {
    label: 'Companion initiative', choices: { normal: 'Normal', minimal: 'Minimal', off: 'Off' },
  },
};

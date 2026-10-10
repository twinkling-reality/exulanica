/**
 * A world's setting: the hour and sky, the colours it restates, what lies on its roofs and ground
 * and the ground beyond it, stated once for one world and drawn over the look the world wears.
 *
 * A style pack (`style-pack.ts`) is shared and says how a world is drawn. A setting
 * (`exulanica.world-setting/v1`) is one world's own: changes to one of its pack's light presets, the
 * colour some look roles are drawn in, the colour of their upward faces, swatches of the pack
 * restated, and the ground beyond the world. Like a pack it never says where anything is.
 *
 * NOTHING OF A PERSON. A world's appearance versions are history no erasure rewrites, and a setting
 * is stored on one, so a setting holds whole numbers, colours and identifiers only: it never holds a
 * person's words or a digest of them, and the reader refuses any other key.
 *
 * CHECKED AGAINST THE PACK IT IS DRAWN OVER. `readWorldSetting` reads a setting's shape and
 * `applyWorldSetting` applies it to a resolved pack, which is the check: the preset it changes is
 * read again by the pack reader's own rule for a preset, what it names must be the pack's, and what
 * it draws is held to two legibility rules. The result is a resolved pack, so everything that draws
 * a pack draws a setting with no other change.
 *
 * What a setting may change, the rules' figures and the bounds are data
 * (`assets/style-packs/settings/setting-rules.v1.json`), read by this reader and the server's
 * (`exulanica/world/world_settings.py`). The shared case file
 * `assets/style-packs/settings/setting-cases.v1.json` holds both to the same verdict on every case:
 * the same refusal by reason and path, or the same digest of the setting and of the pack as drawn.
 *
 * Pure: no DOM, no Node, no renderer.
 */
import {
  StylePackRefusal,
  canonicalJson,
  splitLookRole,
  stylePackReading,
  type LookFamily,
  type ResolvedStylePack,
  type Srgb8,
  type StylePackLightPreset,
  type StylePackSurface,
  type StylePackSwatch,
} from './style-pack.js';

export const WORLD_SETTING_PROFILE = 'exulanica.world-setting/v1';
export const WORLD_SETTING_RULES_PROFILE = 'exulanica.world-setting-rules/v1';
export const WORLD_SETTING_ORIGINS = ['authored', 'drafted'] as const;
/** The swatch keys a setting adds for the roles and upward faces it colours. */
export const WORLD_SETTING_SURFACE_SWATCH = 'setting_surface_';
export const WORLD_SETTING_UP_SWATCH = 'setting_up_';
/** A swatch a setting adds: matt, as a pack's painted surfaces are. */
const ROUGHNESS_PERMILLE = 900;
/**
 * What a drafted setting says of the call that drafted it: identifiers, each of a shape that holds
 * no sentence. A world's appearance is history no erasure rewrites, so a setting states nothing of a
 * person: not their words and not a digest of them. An execution id is a UUID as the host writes
 * one, and none of the three may be 64 hexadecimal characters, the shape of a SHA-256.
 */
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;
const PROMPT_VERSION = /^[a-z0-9][a-z0-9.-]{0,63}$/;
const EXECUTION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST_SHAPED = /^[0-9a-f]{64}$/;
const IDENTIFIERS = ['model_id', 'prompt_version', 'execution_id'] as const;

export type WorldSettingRefusalReason = 'shape' | 'range' | 'reference' | 'duplicate' | 'licence' | 'legibility';

/** A setting refused by name: the reason, and the path of the first fault. */
export class WorldSettingRefusal extends Error {
  constructor(readonly reason: WorldSettingRefusalReason, readonly path: string, detail: string) {
    super(`${path === '' ? 'setting' : path}: ${detail}`);
    this.name = 'WorldSettingRefusal';
  }
}

export type WorldSettingProvenance =
  | { readonly kind: 'authored' }
  | { readonly kind: 'drafted'; readonly model_id: string; readonly prompt_version: string; readonly execution_id: string };

export interface WorldSetting {
  readonly profile: typeof WORLD_SETTING_PROFILE;
  readonly origin: (typeof WORLD_SETTING_ORIGINS)[number];
  readonly provenance: WorldSettingProvenance;
  /** The named parts it was composed from, one an axis, in the axes' order; none for a setting stated outright. */
  readonly parts: readonly { readonly axis: string; readonly key: string }[];
  /** Changes to the pack's preset `from`, each a dotted path of a preset replaced whole. */
  readonly light: { readonly from: string; readonly changes: Readonly<Record<string, unknown>> } | null;
  /** The colour a look role's surfaces are drawn in. */
  readonly surfaces: Readonly<Record<string, { readonly srgb8: Srgb8; readonly emission_permille?: number }>>;
  /** The colour a look role's upward faces take, or null for none. */
  readonly up: Readonly<Record<string, Srgb8 | null>>;
  /** Swatches of the pack restated: a colour, an emission, or both. */
  readonly swatches: Readonly<Record<string, { readonly srgb8?: Srgb8; readonly emission_permille?: number }>>;
  /** The ground beyond the world. */
  readonly edge: { readonly ground: Srgb8 } | null;
}

/** What a setting may change and what it is held to, as the rules file states them. */
export interface WorldSettingRules {
  readonly lightChanges: readonly string[];
  readonly openLightMinimum: number;
  readonly groundPairs: readonly (readonly [string, string])[];
  readonly groundContrastMinimumPermille: number;
  /**
   * The named parts a setting may say it was composed from, by axis. A setting's `parts` holds no
   * other name, so it holds no word of a caller's own.
   */
  readonly partNames: Readonly<Record<string, readonly string[]>>;
  readonly maximumParts: number;
  readonly maximumSurfaces: number;
  readonly maximumUp: number;
  readonly maximumSwatches: number;
  /** `assets/colour/srgb8-linear16.v1.json`: every sRGB byte's linear value times 65535. */
  readonly linear: readonly number[];
}

const { object, optional, integer, oneOf, literal, pattern, text, nullable, srgb8, list, record, lightPreset, KEY } = stylePackReading;

const fail = (reason: WorldSettingRefusalReason, path: string, detail: string): never => {
  throw new WorldSettingRefusal(reason, path, detail);
};
/** Run a pack reader's rule, its refusal restated as a setting's under `prefix`. */
function held<T>(prefix: string, read: () => T): T {
  try {
    return read();
  } catch (error) {
    if (!(error instanceof StylePackRefusal)) throw error;
    const detail = error.message.slice(error.message.indexOf(': ') + 2);
    return fail(error.reason, `${prefix}${error.path}`, detail);
  }
}

/** The rules file and the colour table, as parsed JSON, read for what both readers use. */
export function readWorldSettingRules(rules: unknown, colourTable: unknown): WorldSettingRules {
  const whole = integer(0, 2 ** 31 - 1);
  const words = text(600);
  const axisKey = (key: string, path: string): void => {
    if (!KEY.test(key)) throw new StylePackRefusal('shape', path, 'must be a key');
  };
  const stated = held('', () => object(rules, '', {
    profile: literal(WORLD_SETTING_RULES_PROFILE),
    about: words,
    light_changes: (v, p) => object(v, p, { paths: list(text(80), 1, 64), reason: words }),
    open_light: (v, p) => object(v, p, { minimum: whole, class: words, reason: words, source: words }),
    ground_contrast: (v, p) => object(v, p, { pairs: list(list(text(80), 2, 2), 1, 16), minimum_permille: whole, class: words, reason: words, source: words }),
    part_names: (v, p) => object(v, p, { names: record(axisKey, list(pattern(KEY, 'a key'), 1, 64), 16), class: words, reason: words }),
    bounds: (v, p) => object(v, p, { parts: whole, surfaces: whole, up: whole, swatches: whole, class: words, reason: words }),
  })) as {
    part_names: { names: Record<string, string[]> };
    light_changes: { paths: string[] };
    open_light: { minimum: number };
    ground_contrast: { pairs: [string, string][]; minimum_permille: number };
    bounds: { parts: number; surfaces: number; up: number; swatches: number };
  };
  const values = (colourTable as { values?: unknown }).values;
  if (!Array.isArray(values) || values.length !== 256) throw new WorldSettingRefusal('shape', '', 'the colour table states 256 linear values');
  return {
    lightChanges: stated.light_changes.paths,
    openLightMinimum: stated.open_light.minimum,
    groundPairs: stated.ground_contrast.pairs,
    groundContrastMinimumPermille: stated.ground_contrast.minimum_permille,
    partNames: stated.part_names.names,
    maximumParts: stated.bounds.parts,
    maximumSurfaces: stated.bounds.surfaces,
    maximumUp: stated.bounds.up,
    maximumSwatches: stated.bounds.swatches,
    linear: values as number[],
  };
}

function provenance(value: unknown, path: string): WorldSettingProvenance {
  const kind = value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>)['kind'] : undefined;
  if (kind === 'authored') return object(value, path, { kind: literal('authored') }) as unknown as WorldSettingProvenance;
  if (kind === 'drafted') {
    const drafted = object(value, path, {
      kind: literal('drafted'), model_id: pattern(MODEL_ID, 'a model id'), prompt_version: pattern(PROMPT_VERSION, 'a prompt version'),
      execution_id: pattern(EXECUTION_ID, 'an execution id'),
    }) as Record<string, unknown>;
    for (const name of IDENTIFIERS) {
      if (DIGEST_SHAPED.test(drafted[name] as string)) throw new StylePackRefusal('shape', `${path}.${name}`, 'must not have the shape of a digest');
    }
    return drafted as unknown as WorldSettingProvenance;
  }
  throw new StylePackRefusal('range', `${path}.kind`, `must be one of ${WORLD_SETTING_ORIGINS.join(', ')}`);
}

/**
 * Read a setting's shape, or refuse it with the first rule it breaks, by reason and path. What it
 * names in a pack is checked when it is applied (`applyWorldSetting`).
 */
export function readWorldSetting(value: unknown, rules: WorldSettingRules): WorldSetting {
  const ruleKey = (key: string, path: string): void => {
    if (!KEY.test(key)) throw new StylePackRefusal('shape', path, 'must be a key');
  };
  const roleKey = (key: string, path: string): void => {
    splitLookRole(key, path);
  };
  const changeKey = (key: string, path: string): void => {
    if (!rules.lightChanges.includes(key)) throw new StylePackRefusal('reference', path, 'is not a value of a light preset a setting may change');
  };
  const restated = (item: unknown, path: string): Record<string, unknown> => {
    const swatch = object(item, path, { srgb8: optional(srgb8), emission_permille: optional(integer(0, 1000)) });
    if (Object.keys(swatch).length === 0) throw new StylePackRefusal('shape', path, 'must state a colour or an emission');
    return swatch;
  };
  const setting = held('', () => object(value, '', {
    profile: literal(WORLD_SETTING_PROFILE),
    origin: oneOf(WORLD_SETTING_ORIGINS),
    provenance,
    parts: list((v, p) => object(v, p, { axis: pattern(KEY, 'a key'), key: pattern(KEY, 'a key') }), 0, rules.maximumParts),
    light: nullable((v, p) => object(v, p, {
      from: pattern(KEY, 'a preset key'),
      changes: record(changeKey, (item) => item, rules.lightChanges.length),
    })),
    surfaces: record(roleKey, (v, p) => object(v, p, { srgb8, emission_permille: optional(integer(0, 1000)) }), rules.maximumSurfaces),
    up: record(roleKey, nullable(srgb8), rules.maximumUp),
    swatches: record(ruleKey, restated, rules.maximumSwatches),
    edge: nullable((v, p) => object(v, p, { ground: srgb8 })),
  })) as unknown as WorldSetting;
  if (setting.provenance.kind !== setting.origin) fail('reference', 'provenance.kind', 'must equal the origin');
  const axes = new Set<string>();
  setting.parts.forEach((part, index) => {
    if (!Object.hasOwn(rules.partNames, part.axis)) fail('reference', `parts[${index}].axis`, 'is not an axis the rules list');
    if (!rules.partNames[part.axis]!.includes(part.key)) fail('reference', `parts[${index}].key`, 'is not a part the rules list for its axis');
    if (axes.has(part.axis)) fail('duplicate', `parts[${index}].axis`, `repeats ${JSON.stringify(part.axis)}`);
    axes.add(part.axis);
  });
  return setting;
}

/** The setting's canonical bytes; their SHA-256 is its identity. */
export function canonicalWorldSettingBytes(setting: WorldSetting): Uint8Array {
  return new TextEncoder().encode(canonicalJson(setting));
}

/** Rec. 709 luminance of an sRGB colour, linear, 0 to 65535. */
function luma(colour: Srgb8, rules: WorldSettingRules): number {
  const [red, green, blue] = colour.map((channel) => rules.linear[channel]!) as [number, number, number];
  return Math.floor((2126 * red + 7152 * green + 722 * blue) / 10000);
}

/** The sine of an angle from 0 to 180 degrees, per mille, by Bhaskara's rational form in whole numbers. */
function sinePermille(millidegrees: number): number {
  const product = millidegrees * (180_000 - millidegrees);
  return Math.floor((4000 * product) / (40_500_000_000 - product));
}

/**
 * How much light a person standing in the open is drawn in under `preset`: the sun on level ground
 * plus the sky's image light, through the exposure. A whole number with no unit of its own,
 * compared only with the rules' floor; a guard against a setting nobody can see in, not a model of
 * the renderer.
 */
export function openLight(preset: StylePackLightPreset, rules: WorldSettingRules): number {
  const direct = Math.floor((preset.sun.intensity_permille * luma(preset.sun.colour, rules) * sinePermille(preset.sun.elevation_mdeg)) / 1_000_000);
  const above = Math.floor((luma(preset.sky.zenith, rules) + luma(preset.sky.horizon, rules)) / 2);
  const ambient = Math.floor((preset.environment.intensity_permille * preset.sky.intensity_permille * above) / 1_000_000);
  return Math.floor((preset.exposure_permille * (direct + ambient)) / 1000);
}

/**
 * The lighter colour's luminance over the darker's, each raised by a twentieth of white as the WCAG
 * contrast ratio raises them, in parts per thousand: 1000 for two colours equally light.
 */
export function contrastPermille(first: Srgb8, second: Srgb8, rules: WorldSettingRules): number {
  const one = luma(first, rules);
  const other = luma(second, rules);
  return Math.floor((1000 * (Math.max(one, other) + 3277)) / (Math.min(one, other) + 3277));
}

/** The colour a town's surface of `role` is drawn in; null when it is drawn from a texture set or not dressed. */
function roleColour(swatches: ReadonlyMap<string, StylePackSwatch>, surfaces: Readonly<Record<string, StylePackSurface>>, role: string): Srgb8 | null {
  const family = role.slice(0, role.indexOf('.'));
  for (const name of [role, `${family}.default`]) {
    const surface = surfaces[name];
    if (surface !== undefined) return 'swatch' in surface ? swatches.get(surface.swatch)?.srgb8 ?? null : null;
  }
  return null;
}

const sameColour = (one: Srgb8, other: Srgb8 | null): boolean => other !== null && one[0] === other[0] && one[1] === other[1] && one[2] === other[2];

/**
 * `pack` as a world with `setting` is drawn, or the first rule the setting breaks. `setting` is one
 * `readWorldSetting` returned. In order: its swatches, the roles it colours, their upward faces,
 * the ground beyond, its light, then the two legibility rules over what it changed (a pair of
 * colours the setting left as the look has them is the look's own). The pack's
 * default preset becomes the one the setting changes, so a caller draws the result as any pack.
 */
export function applyWorldSetting(
  pack: ResolvedStylePack,
  setting: WorldSetting,
  families: ReadonlyMap<string, LookFamily>,
  rules: WorldSettingRules,
): ResolvedStylePack {
  const swatches = new Map(pack.swatches);
  const surfaces: Record<string, StylePackSurface> = { ...pack.surfaces };
  const sorted = <T>(entries: Readonly<Record<string, T>>): [string, T][] => Object.entries(entries).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  for (const [part, prefix] of [['surfaces', WORLD_SETTING_SURFACE_SWATCH], ['up', WORLD_SETTING_UP_SWATCH]] as const) {
    const taken = [...swatches.keys()].filter((key) => key.startsWith(prefix)).sort();
    if (Object.keys(setting[part]).length > 0 && taken.length > 0) {
      fail('duplicate', part, `the look states a swatch ${JSON.stringify(taken[0])}, a key a setting's own take`);
    }
  }
  for (const [key, stated] of sorted(setting.swatches)) {
    const base = pack.swatches.get(key);
    if (base === undefined) return fail('reference', `swatches.${key}`, 'names no swatch of the look');
    swatches.set(key, { ...base, ...stated });
  }
  sorted(setting.surfaces).forEach(([role, colour], index) => {
    const family = families.get(role.slice(0, role.indexOf('.')));
    if (family === undefined) return fail('reference', `surfaces.${role}`, 'names no look family');
    if (family.dressing !== 'surface' && family.dressing !== 'both') fail('reference', `surfaces.${role}`, 'names a family no surface dresses');
    const key = `${WORLD_SETTING_SURFACE_SWATCH}${index}`;
    swatches.set(key, { key, srgb8: colour.srgb8, roughness_permille: ROUGHNESS_PERMILLE, metalness_permille: 0, emission_permille: colour.emission_permille ?? 0 });
    surfaces[role] = { swatch: key, up: surfaces[role]?.up ?? null };
    return undefined;
  });
  sorted(setting.up).forEach(([role, colour], index) => {
    const dressed = surfaces[role];
    if (dressed === undefined) return fail('reference', `up.${role}`, 'names no surface the look or the setting dresses');
    if (colour === null) {
      surfaces[role] = { ...dressed, up: null };
      return undefined;
    }
    const key = `${WORLD_SETTING_UP_SWATCH}${index}`;
    swatches.set(key, { key, srgb8: colour, roughness_permille: ROUGHNESS_PERMILLE, metalness_permille: 0, emission_permille: 0 });
    surfaces[role] = { ...dressed, up: key };
    return undefined;
  });
  let edge = pack.edge;
  if (setting.edge !== null) {
    if (edge === null) return fail('reference', 'edge', 'the look draws no ground beyond the world');
    edge = { ...edge, ground: setting.edge.ground };
  }
  let light = pack.light;
  const stated = setting.light;
  if (stated !== null) {
    const from = light.presets[stated.from];
    if (from === undefined || !Object.hasOwn(light.presets, stated.from)) return fail('reference', 'light.from', 'names no preset of the look');
    const changed = structuredClone(from) as unknown as Record<string, unknown>;
    for (const [path, value] of Object.entries(stated.changes)) {
      const names = path.split('.');
      let holder = changed;
      for (const parent of names.slice(0, -1)) holder = holder[parent] as Record<string, unknown>;
      holder[names[names.length - 1]!] = structuredClone(value);
    }
    const preset = held('light.changes.', () => lightPreset(changed, ''));
    light = { default_preset: stated.from, presets: { ...light.presets, [stated.from]: preset } };
    const lit = openLight(preset, rules);
    if (lit < rules.openLightMinimum) {
      fail('legibility', 'light', `a person in the open stands in ${lit} of light, below the least a setting may leave, ${rules.openLightMinimum}`);
    }
  }
  if (Object.keys(setting.surfaces).length > 0 || Object.keys(setting.swatches).length > 0) {
    for (const [first, second] of rules.groundPairs) {
      const one = roleColour(swatches, surfaces, first);
      const other = roleColour(swatches, surfaces, second);
      if (one === null || other === null) continue;
      // The look's own colours, which the setting left as they are.
      if (sameColour(one, roleColour(pack.swatches, pack.surfaces, first)) && sameColour(other, roleColour(pack.swatches, pack.surfaces, second))) continue;
      const apart = contrastPermille(one, other, rules);
      if (apart < rules.groundContrastMinimumPermille) {
        fail('legibility', 'surfaces', `${first} and ${second} are ${apart} per mille apart in lightness, nearer than the least a setting may leave, ${rules.groundContrastMinimumPermille}`);
      }
    }
  }
  return { ...pack, light, edge, swatches, surfaces };
}

/**
 * The canonical bytes of what a setting changes of a pack as it is drawn: the preset, the ground
 * beyond, every swatch in key order and every surface. The server's reader writes the same bytes,
 * so one digest holds both to the same drawing.
 */
export function drawnWorldSettingBytes(pack: ResolvedStylePack): Uint8Array {
  const keys = [...pack.swatches.keys()].sort();
  return new TextEncoder().encode(canonicalJson({
    edge: pack.edge,
    preset: pack.light.presets[pack.light.default_preset],
    surfaces: pack.surfaces,
    swatches: keys.map((key) => pack.swatches.get(key)),
  }));
}

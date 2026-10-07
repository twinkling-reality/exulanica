/**
 * Style packs: the data object that decides how a world looks.
 *
 * A pack is a manifest (`exulanica.style-pack/v1`) and the files it lists. It states the light a
 * world stands in (named presets of sky, fog, sun and finish), a shading model, the ground beyond
 * the world, a palette, and what dresses each LOOK ROLE (`family.leaf`, the vocabulary world kinds
 * and generated pieces share): a surface material for the surface families, pieces for the module
 * families. A pack never states structure: no slot, engine role, position, collision or route
 * reaches it, so choosing or changing a pack can never move a world's topology.
 *
 * INTEGERS ONLY, SO TWO LANGUAGES AGREE ON ONE DIGEST. Every number in a manifest is a whole number
 * in a stated unit (per mille, millimetres, millidegrees, millionths), and the manifest's identity
 * is the SHA-256 of its canonical bytes (keys sorted, no whitespace, ASCII with lowercase \u
 * escapes). The backend's reader (`exulanica/world/style_packs.py`) writes the same bytes, and the
 * shared case file `assets/style-packs/manifest-cases.v1.json` holds both readers to the same
 * verdict on every case, including the digest of each valid one.
 *
 * WHAT IS INJECTED. Which look families exist and how each is dressed is the world kinds' catalog
 * (`assets/catalogs/world-kinds/look-family.v1.json`); which texture sets exist is the texture
 * manifest. Both are passed in, so this module holds no copy of either.
 *
 * Pure: no DOM, no Node, no renderer.
 */

export const STYLE_PACK_PROFILE = 'exulanica.style-pack/v1';
export const STYLE_PACK_COLOUR_ENCODING = 'exulanica.srgb8-linear16/v1';
/** A person's own work, kept for their own workspace and never public. Only an uploaded pack may state it. */
export const STYLE_PACK_OWN_WORK = 'LicenseRef-Exulanica-Own-Work';
export const STYLE_PACK_LICENCES = ['CC0-1.0', 'CC-BY-4.0', STYLE_PACK_OWN_WORK] as const;
export const STYLE_PACK_ORIGINS = ['authored', 'uploaded', 'drafted', 'generated', 'imported'] as const;
/** The pictures a pack may carry, as its one preview: what it looks like, for a person choosing. */
export const STYLE_PACK_IMAGE_MEDIA_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const;
export const STYLE_PACK_MEDIA_TYPES = ['model/gltf-binary', 'image/jpeg', 'image/png', 'image/webp'] as const;
/** The media type each listed file's extension must state. */
export const STYLE_PACK_EXTENSION_MEDIA_TYPES: Readonly<Record<string, (typeof STYLE_PACK_MEDIA_TYPES)[number]>> = Object.freeze({
  glb: 'model/gltf-binary', jpg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
});
/** A pack's preview picture, at most. */
export const STYLE_PACK_PREVIEW_MAX_BYTES = 512 * 1024;
export const STYLE_PACK_TONE_MAPPINGS = ['aces', 'aces2', 'neutral', 'filmic', 'linear'] as const;
/**
 * The sun shadow filters a pack may choose. PCSS soft shadows are not among them: measured at 26 to
 * 27 ms a frame on its own, it alone breaks the frame budget, so it stays a quality setting a person
 * chooses in the render look, never one a pack declares.
 */
export const STYLE_PACK_SHADOW_FILTERS = ['pcf1', 'pcf3', 'pcf5'] as const;
export const STYLE_PACK_SHADING_MODELS = ['pbr', 'toon', 'flat'] as const;
/** Every file a pack lists, together, at most. */
export const STYLE_PACK_MAX_TOTAL_BYTES = 64 * 1024 * 1024;
export const STYLE_PACK_MAX_SWATCHES = 64;
export const STYLE_PACK_MAX_VARIANTS = 8;
export const STYLE_PACK_MAX_PRESETS = 6;
export const STYLE_PACK_MAX_FILES = 512;

export type StylePackLicence = (typeof STYLE_PACK_LICENCES)[number];
export type StylePackOrigin = (typeof STYLE_PACK_ORIGINS)[number];
export type Srgb8 = readonly [number, number, number];

export type StylePackRefusalReason = 'shape' | 'range' | 'reference' | 'duplicate' | 'licence';

export class StylePackRefusal extends Error {
  override readonly name = 'StylePackRefusal';
  constructor(readonly reason: StylePackRefusalReason, readonly path: string, detail: string) {
    super(`${path === '' ? 'manifest' : path}: ${detail}`);
  }
}

export interface StylePackSkyPreset {
  readonly zenith: Srgb8;
  readonly horizon: Srgb8;
  readonly ground: Srgb8;
  readonly bounce_ground: Srgb8;
  readonly intensity_permille: number;
  readonly sun_glow_permille: number;
  readonly sun_disc_permille: number;
  readonly clouds: {
    readonly cover_permille: number;
    readonly colour: Srgb8;
    readonly shade: Srgb8;
    readonly scale_permille: number;
    readonly seed: number;
  } | null;
  readonly face_texels: number;
}

export type StylePackFog =
  | { readonly kind: 'linear'; readonly start_mm: number; readonly end_mm: number; readonly colour: Srgb8 }
  | { readonly kind: 'exp2'; readonly density_micro: number; readonly colour: Srgb8 };

export interface StylePackLightPreset {
  readonly exposure_permille: number;
  readonly tone_mapping: (typeof STYLE_PACK_TONE_MAPPINGS)[number];
  readonly sky: StylePackSkyPreset;
  readonly fog: StylePackFog;
  readonly sun: {
    readonly elevation_mdeg: number;
    readonly azimuth_mdeg: number;
    readonly colour: Srgb8;
    readonly intensity_permille: number;
    readonly shadow: { readonly filter: (typeof STYLE_PACK_SHADOW_FILTERS)[number] };
  };
  readonly environment: { readonly intensity_permille: number };
  readonly contact_shadow: { readonly mode: 'lighting' | 'combine'; readonly radius_mm: number; readonly intensity_permille: number };
  readonly post: {
    readonly bloom: { readonly intensity_permille: number; readonly blur_level: number } | null;
    readonly grading: { readonly brightness_permille: number; readonly contrast_permille: number; readonly saturation_permille: number; readonly tint: Srgb8 };
    readonly enhance: {
      readonly shadows_permille: number;
      readonly highlights_permille: number;
      readonly midtones_permille: number;
      readonly vibrance_permille: number;
      readonly dehaze_permille: number;
    };
    readonly vignette: {
      readonly intensity_permille: number;
      readonly inner_permille: number;
      readonly outer_permille: number;
      readonly curvature_permille: number;
      readonly colour: Srgb8;
    } | null;
    readonly taa: boolean;
  };
}

export interface StylePackSwatch {
  readonly key: string;
  readonly srgb8: Srgb8;
  readonly roughness_permille: number;
  readonly metalness_permille: number;
  readonly emission_permille: number;
}

export type StylePackSurface =
  | { readonly swatch: string; readonly up: string | null }
  | { readonly texture_set: string; readonly up: string | null };

export interface StylePackVariant {
  readonly file: string;
  readonly lod1: string | null;
  /** The piece's own size, as authored: width along its front, depth, height. */
  readonly size_mm: readonly [number, number, number];
  /**
   * Per axis of `size_mm` (width, depth, height): null, or the zone `[low, high]` that stretches to
   * meet a fill slot, in millimetres from the piece's low face on that axis (left, back, base). What
   * lies below `low` and above `high` keeps its size, so a frame keeps its bars whatever the hole.
   */
  readonly stretch_mm: readonly [StretchZone | null, StretchZone | null, StretchZone | null];
}

export type StretchZone = readonly [number, number];

export interface StylePackFile {
  readonly path: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly media_type: (typeof STYLE_PACK_MEDIA_TYPES)[number];
}

export type StylePackProvenance =
  | { readonly kind: 'authored' }
  | { readonly kind: 'uploaded' }
  | { readonly kind: 'drafted'; readonly model_id: string; readonly prompt_version: string; readonly execution_id: string; readonly words_sha256: string }
  | { readonly kind: 'generated'; readonly receipts: readonly string[] }
  | { readonly kind: 'imported'; readonly source_reference: string };

export interface StylePackManifest {
  readonly profile: typeof STYLE_PACK_PROFILE;
  readonly pack_id: string;
  readonly version: number;
  readonly title: string;
  readonly description: string;
  readonly tags: readonly string[];
  readonly origin: StylePackOrigin;
  readonly provenance: StylePackProvenance;
  readonly licence: { readonly id: StylePackLicence; readonly attribution: string | null };
  readonly authors: readonly string[];
  /** The listed picture that shows what the pack looks like, or null; absent (none) from a manifest written before it existed. */
  readonly preview?: string | null;
  readonly base: { readonly pack_id: string; readonly version: number; readonly manifest_sha256: string } | null;
  readonly light: { readonly default_preset: string; readonly presets: Readonly<Record<string, StylePackLightPreset>> } | null;
  readonly shading: {
    readonly model: (typeof STYLE_PACK_SHADING_MODELS)[number];
    readonly toon: { readonly shadow_edge_permille: number; readonly light_edge_permille: number; readonly band_share_permille: number; readonly softness_permille: number } | null;
    readonly ink: Srgb8 | null;
  } | null;
  readonly edge: { readonly ground: Srgb8; readonly drop_mm: number; readonly reach_mm: number } | null;
  readonly palette: { readonly encoding: typeof STYLE_PACK_COLOUR_ENCODING; readonly swatches: readonly StylePackSwatch[] };
  readonly surfaces: Readonly<Record<string, StylePackSurface>>;
  readonly modules: Readonly<Record<string, { readonly variants: readonly StylePackVariant[] }>>;
  readonly files: readonly StylePackFile[];
}

/** How the world kinds' catalog says a family is dressed and fitted. */
export interface LookFamily {
  readonly fit: 'contain' | 'fill' | 'tile' | 'surface';
  readonly dressing: 'module' | 'surface' | 'both' | 'catalog' | 'primitive';
  /** Per mille; 0 for every family whose fit is not fill. */
  readonly fillMinimumPermille: number;
  readonly fillMaximumPermille: number;
}

/** What a manifest is checked against that is not the manifest's own. */
export interface StylePackContext {
  readonly families: ReadonlyMap<string, LookFamily>;
  readonly textureSets: ReadonlySet<string>;
}

// ------------------------------------------------------------------------------------- reading

const PACK_ID = /^[a-z][a-z0-9-]{0,31}(\.[a-z][a-z0-9-]{0,31}){1,3}$/;
const KEY = /^[a-z][a-z0-9_]{0,31}$/;
const TAG = /^[a-z][a-z0-9-]{0,23}$/;
const LEAF = /^[a-z][a-z0-9_]{0,47}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const PATH = /^[a-z0-9][a-z0-9_-]{0,63}(\/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.glb$/;
const IMAGE_PATH = /^[a-z0-9][a-z0-9_-]{0,63}(\/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.(jpg|png|webp)$/;
const FILE_PATH = /^[a-z0-9][a-z0-9_-]{0,63}(\/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.(glb|jpg|png|webp)$/;
const TEXT_MAX = { title: 80, description: 400, author: 120, attribution: 400, reference: 400, model: 200, prompt: 120 } as const;

type Json = unknown;
/**
 * A field a manifest may leave out. A field added within a profile is optional and its absence keeps
 * the meaning a manifest had before the field existed, so every manifest written under the profile
 * still reads. A manifest that leaves it out is returned without it, as given, so its bytes and
 * digest are its own; a reader of the result takes the absence as that earlier meaning.
 */
interface Optional {
  readonly read: (value: Json, path: string) => unknown;
}
const optional = (read: (value: Json, path: string) => unknown): Optional => ({ read });
type Fields = Readonly<Record<string, ((value: Json, path: string) => unknown) | Optional>>;

const fail = (reason: StylePackRefusalReason, path: string, detail: string): never => {
  throw new StylePackRefusal(reason, path, detail);
};
const join = (path: string, key: string): string => (path === '' ? key : `${path}.${key}`);

function object(value: Json, path: string, fields: Fields): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail('shape', path, 'must be an object');
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) if (!Object.hasOwn(fields, key)) fail('shape', path, `has an unknown key ${JSON.stringify(key)}`);
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(fields)) {
    if (!Object.hasOwn(record, key)) {
      if (typeof field !== 'function') continue;
      fail('shape', path, `is missing ${JSON.stringify(key)}`);
    }
    out[key] = (typeof field === 'function' ? field : field.read)(record[key], join(path, key));
  }
  return out;
}

const integer = (min: number, max: number) => (value: Json, path: string): number => {
  if (typeof value !== 'number') return fail('shape', path, 'must be a whole number');
  // JSON.parse reads a whole number too long for a double as Infinity; the other reader holds it exactly and finds it out of range.
  if (!Number.isFinite(value)) return fail('range', path, `must be within ${min} to ${max}`);
  if (!Number.isInteger(value)) return fail('shape', path, 'must be a whole number');
  if (value < min || value > max) fail('range', path, `must be within ${min} to ${max}`);
  return value;
};
const boolean = (value: Json, path: string): boolean => (typeof value === 'boolean' ? value : fail('shape', path, 'must be true or false'));
const oneOf = <T extends string>(values: readonly T[]) => (value: Json, path: string): T =>
  (typeof value === 'string' && (values as readonly string[]).includes(value) ? (value as T) : fail('range', path, `must be one of ${values.join(', ')}`));
const literal = (expected: string) => (value: Json, path: string): string => (value === expected ? expected : fail('shape', path, `must be ${JSON.stringify(expected)}`));
const pattern = (re: RegExp, what: string) => (value: Json, path: string): string =>
  (typeof value === 'string' && re.test(value) ? value : fail('shape', path, `must be ${what}`));
/** A surrogate code unit outside a pair: JSON can escape one, but it is no character. */
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
/** The Unicode Bidi_Control characters: marks, embeddings, overrides and isolates. */
const BIDI_CONTROL = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/;
const text = (max: number, allowEmpty = false) => (value: Json, path: string): string => {
  if (typeof value !== 'string') return fail('shape', path, 'must be text');
  // No leading or trailing space, and no control character: the same rule in every reader.
  if (value.startsWith(' ') || value.endsWith(' ') || (!allowEmpty && value.length === 0)) fail('shape', path, 'must be trimmed text, not empty');
  if (LONE_SURROGATE.test(value)) fail('shape', path, 'must hold no lone surrogate');
  if (value.length > max) fail('range', path, `must be at most ${max} characters`);
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f-\u009f]/.test(value)) fail('shape', path, 'must hold no control characters');
  if (BIDI_CONTROL.test(value)) fail('shape', path, 'must hold no bidirectional control characters');
  return value;
};
const nullable = <T>(read: (value: Json, path: string) => T) => (value: Json, path: string): T | null => (value === null ? null : read(value, path));
const srgb8 = (value: Json, path: string): Srgb8 => {
  if (!Array.isArray(value) || value.length !== 3) return fail('shape', path, 'must be three sRGB bytes');
  return value.map((channel, index) => integer(0, 255)(channel, `${path}[${index}]`)) as unknown as Srgb8;
};
const list = <T>(read: (value: Json, path: string) => T, min: number, max: number) => (value: Json, path: string): T[] => {
  if (!Array.isArray(value)) return fail('shape', path, 'must be a list');
  if (value.length < min || value.length > max) fail('range', path, `must hold ${min} to ${max} items`);
  return value.map((item, index) => read(item, `${path}[${index}]`));
};
const record = <T>(readKey: (key: string, path: string) => void, read: (value: Json, path: string) => T, max: number) => (value: Json, path: string): Record<string, T> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return fail('shape', path, 'must be an object');
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > max) fail('range', path, `must hold at most ${max} entries`);
  const out: Record<string, T> = {};
  for (const [key, item] of entries) {
    readKey(key, join(path, key));
    out[key] = read(item, join(path, key));
  }
  return out;
};

const permille = (min: number, max: number) => integer(min, max);

function lightPreset(value: Json, path: string): StylePackLightPreset {
  return object(value, path, {
    exposure_permille: permille(250, 4000),
    tone_mapping: oneOf(STYLE_PACK_TONE_MAPPINGS),
    sky: (v, p) => object(v, p, {
      zenith: srgb8, horizon: srgb8, ground: srgb8, bounce_ground: srgb8,
      intensity_permille: permille(250, 4000),
      sun_glow_permille: permille(0, 2000),
      sun_disc_permille: permille(0, 64_000),
      clouds: nullable((c, q) => object(c, q, {
        cover_permille: permille(0, 1000), colour: srgb8, shade: srgb8, scale_permille: permille(250, 4000), seed: integer(0, 2_147_483_647),
      })),
      face_texels: (t, q) => {
        const n = integer(64, 256)(t, q);
        if (![64, 128, 256].includes(n)) fail('range', q, 'must be one of 64, 128, 256');
        return n;
      },
    }),
    fog: (v, p) => {
      const kind = v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>)['kind'] : undefined;
      if (kind === 'linear') {
        const fog = object(v, p, { kind: literal('linear'), start_mm: integer(40_000, 60_000), end_mm: integer(61_000, 4_000_000), colour: srgb8 });
        if ((fog['end_mm'] as number) <= (fog['start_mm'] as number)) fail('range', p, 'end_mm must lie beyond start_mm');
        return fog;
      }
      if (kind === 'exp2') return object(v, p, { kind: literal('exp2'), density_micro: integer(100, 6000), colour: srgb8 });
      return fail('range', join(p, 'kind'), 'must be one of linear, exp2');
    },
    sun: (v, p) => {
      const sun = object(v, p, {
        elevation_mdeg: integer(5000, 85_000),
        azimuth_mdeg: integer(0, 360_000),
        colour: srgb8,
        intensity_permille: permille(0, 10_000),
        shadow: (s, q) => object(s, q, { filter: oneOf(STYLE_PACK_SHADOW_FILTERS) }),
      });
      return sun;
    },
    environment: (v, p) => object(v, p, { intensity_permille: permille(50, 4000) }),
    contact_shadow: (v, p) => object(v, p, { mode: oneOf(['lighting', 'combine'] as const), radius_mm: integer(100, 3000), intensity_permille: permille(50, 1000) }),
    post: (v, p) => object(v, p, {
      bloom: nullable((b, q) => object(b, q, { intensity_permille: permille(0, 200), blur_level: integer(1, 16) })),
      grading: (g, q) => object(g, q, { brightness_permille: permille(500, 1500), contrast_permille: permille(500, 1500), saturation_permille: permille(0, 2000), tint: srgb8 }),
      enhance: (e, q) => object(e, q, {
        shadows_permille: permille(-1000, 1000), highlights_permille: permille(-1000, 1000), midtones_permille: permille(-1000, 1000),
        vibrance_permille: permille(-1000, 1000), dehaze_permille: permille(-1000, 1000),
      }),
      vignette: nullable((g, q) => object(g, q, {
        intensity_permille: permille(0, 1000), inner_permille: permille(0, 1500), outer_permille: permille(0, 2000), curvature_permille: permille(100, 10_000), colour: srgb8,
      })),
      taa: boolean,
    }),
  }) as unknown as StylePackLightPreset;
}

function provenance(value: Json, path: string): StylePackProvenance {
  const kind = value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>)['kind'] : undefined;
  switch (kind) {
    case 'authored':
    case 'uploaded':
      return object(value, path, { kind: literal(kind) }) as unknown as StylePackProvenance;
    case 'drafted':
      return object(value, path, {
        kind: literal('drafted'), model_id: text(TEXT_MAX.model), prompt_version: text(TEXT_MAX.prompt),
        execution_id: text(TEXT_MAX.prompt), words_sha256: pattern(SHA256, 'a lowercase SHA-256'),
      }) as unknown as StylePackProvenance;
    case 'generated':
      return object(value, path, { kind: literal('generated'), receipts: list(pattern(SHA256, 'a lowercase SHA-256'), 1, 512) }) as unknown as StylePackProvenance;
    case 'imported':
      return object(value, path, { kind: literal('imported'), source_reference: text(TEXT_MAX.reference) }) as unknown as StylePackProvenance;
    default:
      return fail('range', join(path, 'kind'), `must be one of ${STYLE_PACK_ORIGINS.join(', ')}`);
  }
}

/** A look role's family and leaf, or a refusal naming the role. */
export function splitLookRole(role: string, path: string): { family: string; leaf: string } {
  const dot = role.indexOf('.');
  const family = dot < 0 ? '' : role.slice(0, dot);
  const leaf = dot < 0 ? '' : role.slice(dot + 1);
  if (!KEY.test(family) || !LEAF.test(leaf)) fail('shape', path, `${JSON.stringify(role)} is not a look role family.leaf`);
  return { family, leaf };
}

/**
 * Read a manifest, or refuse it with the first rule it breaks, by name and path. The checks that
 * need the whole manifest (references between sections, duplicates, the budget of the files
 * together) follow the shape checks, in a fixed order, so both readers name the same first fault.
 */
export function readStylePackManifest(value: Json, context: StylePackContext): StylePackManifest {
  const lookRoleKey = (dressings: readonly LookFamily['dressing'][]) => (key: string, path: string): void => {
    const { family } = splitLookRole(key, path);
    const known = context.families.get(family);
    if (known === undefined) fail('reference', path, `names no look family ${JSON.stringify(family)}`);
    if (!dressings.includes(known!.dressing)) fail('reference', path, `family ${JSON.stringify(family)} is not dressed this way`);
  };
  const manifest = object(value, '', {
    profile: literal(STYLE_PACK_PROFILE),
    pack_id: pattern(PACK_ID, 'a namespaced id such as exulanica.cozy-town'),
    version: integer(1, 1_000_000),
    title: text(TEXT_MAX.title),
    description: text(TEXT_MAX.description, true),
    tags: list(pattern(TAG, 'a lowercase tag'), 0, 12),
    origin: oneOf(STYLE_PACK_ORIGINS),
    provenance,
    licence: (v, p) => object(v, p, { id: oneOf(STYLE_PACK_LICENCES), attribution: nullable(text(TEXT_MAX.attribution)) }),
    authors: list(text(TEXT_MAX.author), 1, 16),
    // Added after the first packs were published: a manifest from before it names none.
    preview: optional(nullable(pattern(IMAGE_PATH, 'a lowercase relative path ending .jpg, .png or .webp'))),
    base: nullable((v, p) => object(v, p, {
      pack_id: pattern(PACK_ID, 'a namespaced id such as exulanica.cozy-town'), version: integer(1, 1_000_000), manifest_sha256: pattern(SHA256, 'a lowercase SHA-256'),
    })),
    light: nullable((v, p) => object(v, p, {
      default_preset: pattern(KEY, 'a preset key'),
      presets: record((key, q) => { if (!KEY.test(key)) fail('shape', q, 'must be a preset key'); }, lightPreset, STYLE_PACK_MAX_PRESETS),
    })),
    shading: nullable((v, p) => object(v, p, {
      model: oneOf(STYLE_PACK_SHADING_MODELS),
      toon: nullable((t, q) => object(t, q, {
        shadow_edge_permille: permille(0, 1000), light_edge_permille: permille(0, 1000), band_share_permille: permille(0, 1000), softness_permille: permille(5, 200),
      })),
      ink: nullable(srgb8),
    })),
    edge: nullable((v, p) => object(v, p, { ground: srgb8, drop_mm: integer(200, 5000), reach_mm: integer(200_000, 8_000_000) })),
    palette: (v, p) => object(v, p, {
      encoding: literal(STYLE_PACK_COLOUR_ENCODING),
      swatches: list((s, q) => object(s, q, {
        key: pattern(KEY, 'a swatch key'), srgb8, roughness_permille: permille(0, 1000), metalness_permille: permille(0, 1000), emission_permille: permille(0, 1000),
      }), 0, STYLE_PACK_MAX_SWATCHES),
    }),
    surfaces: record(lookRoleKey(['surface', 'both']), (v, p) => {
      const keys = v !== null && typeof v === 'object' && !Array.isArray(v) ? Object.keys(v as object) : [];
      return keys.includes('texture_set')
        ? object(v, p, { texture_set: pattern(/^[a-z0-9][a-z0-9.-]{0,63}$/, 'a texture set id'), up: nullable(pattern(KEY, 'a swatch key')) })
        : object(v, p, { swatch: pattern(KEY, 'a swatch key'), up: nullable(pattern(KEY, 'a swatch key')) });
    }, 256),
    modules: record(lookRoleKey(['module', 'both']), (v, p) => object(v, p, {
      variants: list((item, q) => object(item, q, {
        file: pattern(PATH, 'a lowercase relative path ending .glb'),
        lod1: nullable(pattern(PATH, 'a lowercase relative path ending .glb')),
        size_mm: (s, r) => {
          if (!Array.isArray(s) || s.length !== 3) return fail('shape', r, 'must be width, depth and height in millimetres');
          return s.map((n, i) => integer(1, 50_000)(n, `${r}[${i}]`));
        },
        stretch_mm: (s, r) => {
          if (!Array.isArray(s) || s.length !== 3) return fail('shape', r, 'must be a zone or null for width, depth and height');
          return s.map((zone, i) => nullable((z, q) => {
            if (!Array.isArray(z) || z.length !== 2) return fail('shape', q, 'must be a low and a high in millimetres');
            return z.map((n, k) => integer(0, 50_000)(n, `${q}[${k}]`));
          })(zone, `${r}[${i}]`));
        },
      }), 1, STYLE_PACK_MAX_VARIANTS),
    }), 512),
    files: list((v, p) => object(v, p, {
      path: pattern(FILE_PATH, 'a lowercase relative path ending .glb, .jpg, .png or .webp'),
      sha256: pattern(SHA256, 'a lowercase SHA-256'),
      bytes: integer(1, STYLE_PACK_MAX_TOTAL_BYTES),
      media_type: oneOf(STYLE_PACK_MEDIA_TYPES),
    }), 0, STYLE_PACK_MAX_FILES),
  }) as unknown as StylePackManifest;
  return checkWhole(manifest, context);
}

function checkWhole(manifest: StylePackManifest, context: StylePackContext): StylePackManifest {
  if (manifest.provenance.kind !== manifest.origin) fail('reference', 'provenance.kind', 'must equal the origin');
  if (manifest.licence.id === 'CC-BY-4.0' && manifest.licence.attribution === null) fail('licence', 'licence.attribution', 'is required for CC-BY-4.0');
  if (manifest.licence.id === 'CC0-1.0' && manifest.licence.attribution !== null) fail('licence', 'licence.attribution', 'must be null for CC0-1.0');
  if (manifest.licence.id === STYLE_PACK_OWN_WORK && manifest.origin !== 'uploaded') fail('licence', 'licence.id', `${STYLE_PACK_OWN_WORK} is for an uploaded pack only`);
  if (manifest.licence.id === STYLE_PACK_OWN_WORK && manifest.licence.attribution !== null) fail('licence', 'licence.attribution', `must be null for ${STYLE_PACK_OWN_WORK}`);
  if (manifest.base === null && (manifest.light === null || manifest.shading === null)) {
    fail('reference', manifest.light === null ? 'light' : 'shading', 'is required in a pack with no base');
  }
  if (manifest.light !== null && !Object.hasOwn(manifest.light.presets, manifest.light.default_preset)) {
    fail('reference', 'light.default_preset', 'names no preset');
  }
  if (manifest.shading !== null && (manifest.shading.model === 'toon') !== (manifest.shading.toon !== null)) {
    fail('reference', 'shading.toon', 'is stated exactly when the model is toon');
  }
  const toon = manifest.shading?.toon ?? null;
  if (toon !== null && toon.shadow_edge_permille >= toon.light_edge_permille) fail('range', 'shading.toon', 'shadow_edge_permille must lie below light_edge_permille');
  const swatchKeys = new Set<string>();
  const colours = new Set<string>();
  manifest.palette.swatches.forEach((swatch, index) => {
    if (swatchKeys.has(swatch.key)) fail('duplicate', `palette.swatches[${index}].key`, `repeats ${JSON.stringify(swatch.key)}`);
    swatchKeys.add(swatch.key);
    const colour = swatch.srgb8.join(',');
    if (colours.has(colour)) fail('duplicate', `palette.swatches[${index}].srgb8`, 'repeats a colour another swatch has');
    colours.add(colour);
  });
  for (const [role, surface] of Object.entries(manifest.surfaces)) {
    if ('swatch' in surface && !swatchKeys.has(surface.swatch)) fail('reference', `surfaces.${role}.swatch`, `names no swatch ${JSON.stringify(surface.swatch)}`);
    if ('texture_set' in surface && !context.textureSets.has(surface.texture_set)) fail('reference', `surfaces.${role}.texture_set`, `names no texture set ${JSON.stringify(surface.texture_set)}`);
    if (surface.up !== null && !swatchKeys.has(surface.up)) fail('reference', `surfaces.${role}.up`, `names no swatch ${JSON.stringify(surface.up)}`);
  }
  const listed = new Map<string, StylePackFile>();
  let total = 0;
  manifest.files.forEach((file, index) => {
    if (listed.has(file.path)) fail('duplicate', `files[${index}].path`, `repeats ${JSON.stringify(file.path)}`);
    if (index > 0 && manifest.files[index - 1]!.path > file.path) fail('shape', `files[${index}].path`, 'files must be listed in path order');
    const stated = STYLE_PACK_EXTENSION_MEDIA_TYPES[file.path.slice(file.path.lastIndexOf('.') + 1)]!;
    if (file.media_type !== stated) fail('shape', `files[${index}].media_type`, `must be ${stated} for its extension`);
    if ((STYLE_PACK_IMAGE_MEDIA_TYPES as readonly string[]).includes(file.media_type) && file.bytes > STYLE_PACK_PREVIEW_MAX_BYTES) {
      fail('range', `files[${index}].bytes`, `a picture is at most ${STYLE_PACK_PREVIEW_MAX_BYTES} bytes`);
    }
    listed.set(file.path, file);
    total += file.bytes;
  });
  if (total > STYLE_PACK_MAX_TOTAL_BYTES) fail('range', 'files', `must total at most ${STYLE_PACK_MAX_TOTAL_BYTES} bytes`);
  const used = new Set<string>();
  for (const [role, module] of Object.entries(manifest.modules)) {
    module.variants.forEach((variant, index) => {
      for (const [field, path] of [['file', variant.file], ['lod1', variant.lod1]] as const) {
        if (path === null) continue;
        if (!listed.has(path)) fail('reference', `modules.${role}.variants[${index}].${field}`, `names no listed file ${JSON.stringify(path)}`);
        used.add(path);
      }
      const stretched = variant.stretch_mm.some((zone) => zone !== null);
      if (stretched && context.families.get(splitLookRole(role, 'modules').family)?.fit !== 'fill') {
        fail('reference', `modules.${role}.variants[${index}].stretch_mm`, 'stretches only a piece of a fill family');
      }
      variant.stretch_mm.forEach((zone, axis) => {
        if (zone !== null && !(zone[0] < zone[1] && zone[1] <= variant.size_mm[axis]!)) {
          fail('range', `modules.${role}.variants[${index}].stretch_mm[${axis}]`, 'must lie within the piece, low below high');
        }
      });
    });
  }
  const preview = manifest.preview ?? null;
  if (preview !== null) {
    if (!listed.has(preview)) fail('reference', 'preview', `names no listed file ${JSON.stringify(preview)}`);
    used.add(preview);
  }
  for (const path of listed.keys()) if (!used.has(path)) fail('reference', 'files', `lists ${JSON.stringify(path)}, which nothing uses`);
  return manifest;
}

// ------------------------------------------------------------------------------ canonical bytes

/** Canonical JSON: keys sorted, no whitespace, ASCII with lowercase \u escapes, whole numbers only. */
export function canonicalJson(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new StylePackRefusal('shape', '', 'a canonical manifest holds whole numbers only');
    return String(value);
  }
  if (typeof value === 'string') {
    return JSON.stringify(value).replace(/[\u0080-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value === 'object') {
    const keys = Object.keys(value as object).sort();
    return `{${keys.map((key) => `${canonicalJson(key)}:${canonicalJson((value as Record<string, unknown>)[key])}`).join(',')}}`;
  }
  throw new StylePackRefusal('shape', '', `a canonical manifest holds no ${typeof value}`);
}

export function canonicalStylePackBytes(manifest: StylePackManifest): Uint8Array {
  return new TextEncoder().encode(canonicalJson(manifest));
}

// ------------------------------------------------------------------------------------ resolving

/** A pack with its base chain applied: every section stated, nearest first. */
export interface ResolvedStylePack {
  readonly chain: readonly StylePackManifest[];
  readonly light: NonNullable<StylePackManifest['light']>;
  readonly shading: NonNullable<StylePackManifest['shading']>;
  readonly edge: StylePackManifest['edge'];
  readonly swatches: ReadonlyMap<string, StylePackSwatch>;
  readonly surfaces: Readonly<Record<string, StylePackSurface>>;
  readonly modules: Readonly<Record<string, ResolvedModule>>;
}

/** A module as resolved: its variants and files, and the manifest of the chain that stated it. */
export interface ResolvedModule {
  readonly variants: readonly StylePackVariant[];
  readonly files: ReadonlyMap<string, StylePackFile>;
  /** Index into `chain` of the manifest that stated this module, whose palette its pieces are coloured in. */
  readonly stated: number;
}

/**
 * The swatch key a piece's colour stands for: looked up in the palette of the manifest that stated
 * the piece's module, then in each base below it. Null when no palette there holds the colour.
 */
export function swatchKeyOf(pack: ResolvedStylePack, module: ResolvedModule, srgb8: readonly [number, number, number]): string | null {
  for (let index = module.stated; index < pack.chain.length; index += 1) {
    const found = pack.chain[index]!.palette.swatches.find((swatch) => swatch.srgb8[0] === srgb8[0] && swatch.srgb8[1] === srgb8[1] && swatch.srgb8[2] === srgb8[2]);
    if (found !== undefined) return found.key;
  }
  return null;
}

/**
 * Apply a pack's base chain, nearest last in `chain` (the pack itself first). A leaf, a swatch or a
 * preset the pack states replaces the base's; anything it leaves out is the base's.
 */
export function resolveStylePack(chain: readonly StylePackManifest[]): ResolvedStylePack {
  if (chain.length === 0 || chain.length > 4) throw new StylePackRefusal('reference', 'base', 'a pack resolves through one to four manifests');
  for (let i = 0; i + 1 < chain.length; i += 1) {
    const base = chain[i]!.base;
    if (base === null || base.pack_id !== chain[i + 1]!.pack_id || base.version !== chain[i + 1]!.version) {
      throw new StylePackRefusal('reference', 'base', `${chain[i]!.pack_id} does not name ${chain[i + 1]!.pack_id} as its base`);
    }
  }
  if (chain[chain.length - 1]!.base !== null) throw new StylePackRefusal('reference', 'base', 'the chain ends at a pack that names a base');
  const swatches = new Map<string, StylePackSwatch>();
  const surfaces: Record<string, StylePackSurface> = {};
  const modules: Record<string, ResolvedModule> = {};
  let light: StylePackManifest['light'] = null;
  let shading: StylePackManifest['shading'] = null;
  let edge: StylePackManifest['edge'] | undefined;
  for (let index = chain.length - 1; index >= 0; index -= 1) {
    const manifest = chain[index]!;
    for (const swatch of manifest.palette.swatches) swatches.set(swatch.key, swatch);
    Object.assign(surfaces, manifest.surfaces);
    const files = new Map(manifest.files.map((file) => [file.path, file] as const));
    for (const [role, module] of Object.entries(manifest.modules)) modules[role] = { variants: module.variants, files, stated: index };
    if (manifest.light !== null) light = manifest.light;
    if (manifest.shading !== null) shading = manifest.shading;
    if (manifest.base === null || manifest.edge !== null) edge = manifest.edge;
  }
  return { chain, light: light!, shading: shading!, edge: edge ?? null, swatches, surfaces, modules };
}

/** A slot as a world kind states it: millimetres, base centre, front +y, up +z. */
export interface StyleSlot {
  readonly identity: string;
  readonly lookRole: string;
  readonly positionMm: readonly [number, number, number];
  readonly yawQuarterTurns: 0 | 1 | 2 | 3;
  readonly boxMm: readonly [number, number, number];
}

export type Dressing =
  | { readonly kind: 'surface'; readonly role: string; readonly surface: StylePackSurface; readonly swatch: StylePackSwatch | null; readonly up: StylePackSwatch | null }
  | {
      readonly kind: 'module';
      readonly role: string;
      readonly variant: number;
      readonly file: StylePackFile;
      readonly lod1: StylePackFile | null;
      /** Scale along the piece's own x (width), y (height) and z (depth), glTF axes; 1 where it stretches. */
      readonly scale: readonly [number, number, number];
      /** Where the piece stretches, on glTF axes x, y, z. */
      readonly stretch: AxisStretches;
      /** For a tiled family: how many copies run along the slot's width, centred. */
      readonly copies: number;
    };

/**
 * A stretched axis: the zone between `low` and `high` (millimetres from the piece's low face on the
 * axis) becomes `length` long, and what lies above `high` moves with it, so the piece meets `box`.
 */
export interface AxisStretch {
  readonly low: number;
  readonly high: number;
  readonly length: number;
  readonly box: number;
}

export type AxisStretches = readonly [AxisStretch | null, AxisStretch | null, AxisStretch | null];

/** Where a coordinate `p` (millimetres from the piece's low face) lands in its slot. */
export function stretchCoordinate(stretch: AxisStretch, p: number): number {
  if (p <= stretch.low) return p;
  if (p >= stretch.high) return p + stretch.length - (stretch.high - stretch.low);
  return stretch.low + ((p - stretch.low) * stretch.length) / (stretch.high - stretch.low);
}

/** FNV-1a over UTF-8: the variant a part's identity picks, the same in every runtime. */
export function variantIndex(identity: string, leaf: string, count: number): number {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(`${identity}|${leaf}`)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) % count;
}

/**
 * What dresses one slot: the leaf, then the family's `default` leaf, in the resolved pack (its base
 * chain already applied); null when neither is dressed or no variant fits, which the caller draws
 * as the engine's primitive. `accepts` is what the slot can take: a texture set a tile already drew
 * takes only a surface, a hole a tile left takes only a piece, and a primitive takes either, a
 * surface before a piece at each leaf.
 */
export function resolveLookRole(
  pack: ResolvedStylePack,
  slot: StyleSlot,
  families: ReadonlyMap<string, LookFamily>,
  accepts: 'surface' | 'module' | 'either' = 'either',
): Dressing | null {
  const { family, leaf } = splitLookRole(slot.lookRole, 'lookRole');
  const kind = families.get(family);
  if (kind === undefined) return null;
  const surfaces = accepts !== 'module' && (kind.dressing === 'surface' || kind.dressing === 'both');
  const modules = accepts !== 'surface' && (kind.dressing === 'module' || kind.dressing === 'both');
  for (const role of leaf === 'default' ? [slot.lookRole] : [slot.lookRole, `${family}.default`]) {
    if (surfaces) {
      const surface = pack.surfaces[role];
      if (surface !== undefined) {
        return {
          kind: 'surface', role, surface,
          swatch: 'swatch' in surface ? pack.swatches.get(surface.swatch) ?? null : null,
          up: surface.up === null ? null : pack.swatches.get(surface.up) ?? null,
        };
      }
    }
    if (modules) {
      const module = pack.modules[role];
      if (module === undefined) continue;
      const count = module.variants.length;
      const first = variantIndex(slot.identity, leaf, count);
      for (let step = 0; step < count; step += 1) {
        const index = (first + step) % count;
        const variant = module.variants[index]!;
        const fitted = fit(kind, variant.size_mm, slot.boxMm, variant.stretch_mm);
        if (fitted === null) continue;
        return {
          kind: 'module', role, variant: index,
          file: module.files.get(variant.file)!,
          lod1: variant.lod1 === null ? null : module.files.get(variant.lod1)!,
          scale: fitted.scale, stretch: fitted.stretch, copies: fitted.copies,
        };
      }
    }
  }
  return null;
}

/**
 * How a piece of `size` (width, depth, height) meets a slot's box (width, depth, height): uniform
 * to fit inside (contain); each axis to the box (fill), by its stretch zone where the variant states
 * one and the box leaves the zone some length, else by scaling within the family's bounds; copies
 * along the width, each scaled to share it exactly (tile). Scales and stretches are on glTF axes:
 * x width, y height, z depth.
 */
export function fit(
  family: LookFamily,
  size: readonly [number, number, number],
  box: readonly [number, number, number],
  stretch: StylePackVariant['stretch_mm'] = [null, null, null],
): { readonly scale: readonly [number, number, number]; readonly stretch: AxisStretches; readonly copies: number } | null {
  const [w, d, h] = size;
  const [bw, bd, bh] = box;
  const none = [null, null, null] as const;
  switch (family.fit) {
    case 'contain': {
      const s = Math.min(bw / w, bd / d, bh / h);
      return { scale: [s, s, s], stretch: none, copies: 1 };
    }
    case 'fill': {
      // glTF axis order (x width, y height, z depth) over the size order (width, depth, height).
      const axes = [0, 2, 1].map((i) => {
        const zone = stretch[i]!;
        const length = zone === null ? 0 : box[i]! - (zone[0] + size[i]! - zone[1]);
        if (zone !== null) return length > 0 ? { scale: 1, stretch: { low: zone[0], high: zone[1], length, box: box[i]! } } : null;
        const scale = box[i]! / size[i]!;
        const ok = scale * 1000 >= family.fillMinimumPermille && scale * 1000 <= family.fillMaximumPermille;
        return ok ? { scale, stretch: null } : null;
      });
      if (axes.some((axis) => axis === null)) return null;
      const [x, y, z] = axes as { scale: number; stretch: AxisStretch | null }[];
      return { scale: [x!.scale, y!.scale, z!.scale], stretch: [x!.stretch, y!.stretch, z!.stretch], copies: 1 };
    }
    case 'tile': {
      const copies = Math.max(1, Math.round(bw / w));
      const sx = bw / (copies * w);
      const s = Math.min(bd / d, bh / h, 1);
      return { scale: [sx, s, s], stretch: none, copies };
    }
    default:
      return null;
  }
}

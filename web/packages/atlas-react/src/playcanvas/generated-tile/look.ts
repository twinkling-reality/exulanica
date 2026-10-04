/**
 * How a generated street is lit and seen: one versioned, validated descriptor.
 *
 * Every look parameter the generated tile runtime uses lives here and nowhere else, so a change to
 * the look is a change to this object, reviewed as one diff and carried as one id and version. The
 * corridor lane iterates on the street's appearance by editing this descriptor; nothing in the
 * runtime modules carries a literal that changes how a surface reads.
 *
 * THE VALIDATOR IS THE CONTRACT. {@link validateTileLook} refuses an unknown key, a missing key, a
 * value of the wrong kind, and a value outside its stated range. Three ranges are the architecture
 * table's look targets rather than engine limits, and they are enforced here so that a later edit
 * cannot drift off target without failing a test:
 *
 * - fog onset 40 to 60 m (`fog.startM`);
 * - an environment probe, always on (`environment` has no off switch);
 * - contact shadowing at kerb, doorway and cornice (`contactShadow` has no off switch, and its
 *   radius must reach the smallest of the three, a kerb at 100 mm, without spanning a storey).
 *
 * WHAT IS NOT HERE. Geometry, UV scale and texture choice are world data: they come from the tile's
 * records and the texture set's physical extent, never from a look. A look may shade a surface; it
 * may never decide what a surface is made of.
 *
 * Colours are linear-light RGB in 0 to 1, angles are degrees, distances are metres.
 */

export const TILE_LOOK_ID = 'exulanica.generated-tile-look';

export type TileToneMapping = 'aces' | 'aces2' | 'neutral' | 'filmic' | 'linear';
export type TileShadowFilter = 'pcf3' | 'pcf5';
export type TileContactShadowMode = 'lighting' | 'combine';
export type Rgb = readonly [number, number, number];

/** The tile look: the default descriptor, as section 6 of the runtime document measures it. */
export interface TileLookV1 {
  readonly id: typeof TILE_LOOK_ID;
  readonly version: number;
  readonly exposure: number;
  readonly toneMapping: TileToneMapping;
  /** The sky the camera clears to and the probe is built from. */
  readonly sky: {
    readonly zenith: Rgb;
    readonly horizon: Rgb;
    readonly ground: Rgb;
  };
  readonly fog: {
    /** Linear fog: none before `startM`, full at `endM`. */
    readonly startM: number;
    readonly endM: number;
    readonly colour: Rgb;
  };
  readonly sun: {
    readonly elevationDeg: number;
    readonly azimuthDeg: number;
    readonly colour: Rgb;
    readonly intensity: number;
    readonly shadow: {
      readonly resolution: number;
      readonly distanceM: number;
      readonly cascades: number;
      readonly cascadeDistribution: number;
      readonly bias: number;
      readonly normalOffsetBias: number;
      readonly filter: TileShadowFilter;
    };
  };
  /** Image-based light from a probe built from `sky`. */
  readonly environment: {
    readonly intensity: number;
    /** Edge length of the prefiltered atlas, in texels. */
    readonly atlasSize: number;
    /** Edge length of the cubemap the gradient is drawn into, in texels. */
    readonly sourceSize: number;
  };
  /** Screen-space ambient occlusion: the contact shadowing at kerb, doorway and cornice. */
  readonly contactShadow: {
    readonly mode: TileContactShadowMode;
    readonly radiusM: number;
    readonly intensity: number;
    readonly samples: number;
    readonly power: number;
    readonly minAngleDeg: number;
    readonly blur: boolean;
    /** Fraction of the frame's resolution the occlusion is computed at. */
    readonly scale: number;
  };
  readonly surface: {
    /** Normal map strength. 1 is the set's own relief. */
    readonly normalStrength: number;
    readonly anisotropy: number;
    /**
     * Parallax from the set's height map. Off unless a measurement shows it helps at eye level
     * within budget; the tile runtime's documentation records the measurement that decided it.
     */
    readonly parallax: boolean;
    readonly parallaxFactor: number;
  };
  /** The stated unavailable surface: a pattern that cannot be read as architecture. */
  readonly unavailable: {
    readonly ink: Rgb;
    readonly ground: Rgb;
    /** Stripe period in texels of the pattern texture. */
    readonly stripeTexels: number;
    /** Physical size one repeat of the pattern covers on a surface, in millimetres. */
    readonly tileMm: number;
  };
}

/**
 * Version 1. The values are the starting point the tile runtime was measured with; the corridor
 * lane's iterations change them here, bumping `version` whenever a value changes.
 */
export const TILE_LOOK_V1: TileLookV1 = deepFreeze({
  id: TILE_LOOK_ID,
  version: 1,
  exposure: 1.0,
  toneMapping: 'aces',
  sky: {
    zenith: [0.32, 0.47, 0.72],
    horizon: [0.78, 0.83, 0.88],
    ground: [0.23, 0.22, 0.21],
  },
  fog: {
    startM: 50,
    endM: 420,
    colour: [0.74, 0.79, 0.85],
  },
  sun: {
    elevationDeg: 38,
    azimuthDeg: 142,
    colour: [1.0, 0.93, 0.82],
    intensity: 2.6,
    shadow: {
      resolution: 2048,
      distanceM: 90,
      cascades: 3,
      cascadeDistribution: 0.6,
      bias: 0.12,
      normalOffsetBias: 0.08,
      filter: 'pcf3',
    },
  },
  environment: {
    intensity: 1.0,
    atlasSize: 512,
    sourceSize: 64,
  },
  contactShadow: {
    // `combine` darkens direct light too. `lighting` touches only ambient, and measured in sunlight
    // it darkened the kerb's foot by 7 per cent, which does not read as contact at all.
    mode: 'combine',
    radiusM: 0.6,
    intensity: 0.6,
    samples: 12,
    power: 2,
    minAngleDeg: 10,
    blur: true,
    scale: 1,
  },
  surface: {
    normalStrength: 1,
    anisotropy: 8,
    parallax: false,
    parallaxFactor: 0,
  },
  unavailable: {
    ink: [0.9, 0.05, 0.6],
    ground: [0.02, 0.02, 0.02],
    stripeTexels: 16,
    tileMm: 1200,
  },
});

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}

export class TileLookError extends Error {
  override readonly name = 'TileLookError';
}

type Shape =
  | { readonly kind: 'number'; readonly min: number; readonly max: number; readonly integer?: boolean }
  | { readonly kind: 'rgb' }
  | { readonly kind: 'boolean' }
  | { readonly kind: 'enum'; readonly values: readonly string[] }
  | { readonly kind: 'literal'; readonly value: string }
  | { readonly kind: 'object'; readonly fields: Readonly<Record<string, Shape>> }
  /** The shape, or null: a section a look may leave out by saying so. */
  | { readonly kind: 'nullable'; readonly shape: Shape }
  /** One of several object shapes, chosen by the value of one key every variant has. */
  | { readonly kind: 'variant'; readonly key: string; readonly variants: Readonly<Record<string, Shape>> };

const num = (min: number, max: number, integer = false): Shape => ({ kind: 'number', min, max, integer });
const rgb: Shape = { kind: 'rgb' };
const obj = (fields: Readonly<Record<string, Shape>>): Shape => ({ kind: 'object', fields });

const SHAPE: Shape = obj({
  id: { kind: 'literal', value: TILE_LOOK_ID },
  version: num(1, 1_000_000, true),
  exposure: num(0.25, 4),
  toneMapping: { kind: 'enum', values: ['aces', 'aces2', 'neutral', 'filmic', 'linear'] },
  sky: obj({ zenith: rgb, horizon: rgb, ground: rgb }),
  // The architecture target: onset 40 to 60 m, where the shipped district had 420 m.
  fog: obj({ startM: num(40, 60), endM: num(61, 2000), colour: rgb }),
  sun: obj({
    elevationDeg: num(5, 85),
    azimuthDeg: num(0, 360),
    colour: rgb,
    intensity: num(0, 10),
    shadow: obj({
      resolution: { kind: 'enum', values: ['512', '1024', '2048', '4096'] },
      distanceM: num(10, 400),
      cascades: num(1, 4, true),
      cascadeDistribution: num(0, 1),
      bias: num(0, 1),
      normalOffsetBias: num(0, 1),
      filter: { kind: 'enum', values: ['pcf3', 'pcf5'] },
    }),
  }),
  environment: obj({
    intensity: num(0.05, 4),
    atlasSize: { kind: 'enum', values: ['256', '512', '1024'] },
    sourceSize: { kind: 'enum', values: ['32', '64', '128'] },
  }),
  // A kerb is 100 mm; a storey is about 3 m. The radius must see the first and not smear the second.
  contactShadow: obj({
    mode: { kind: 'enum', values: ['lighting', 'combine'] },
    radiusM: num(0.1, 3),
    intensity: num(0.05, 1),
    samples: num(1, 64, true),
    power: num(0.1, 10),
    minAngleDeg: num(1, 90),
    blur: { kind: 'boolean' },
    scale: num(0.5, 1),
  }),
  surface: obj({
    normalStrength: num(0, 2),
    anisotropy: num(1, 16, true),
    parallax: { kind: 'boolean' },
    parallaxFactor: num(0, 1),
  }),
  unavailable: obj({ ink: rgb, ground: rgb, stripeTexels: num(4, 64, true), tileMm: num(200, 5000, true) }),
});

function check(value: unknown, shape: Shape, path: string): void {
  const fail = (message: string): never => { throw new TileLookError(`${path}: ${message}`); };
  switch (shape.kind) {
    case 'literal':
      if (value !== shape.value) fail(`must be ${JSON.stringify(shape.value)}`);
      return;
    case 'boolean':
      if (typeof value !== 'boolean') fail('must be true or false');
      return;
    case 'enum': {
      // Numeric enums (texel sizes) are written as numbers and listed as strings.
      const spelled = typeof value === 'number' && Number.isInteger(value) ? String(value) : value;
      if (typeof spelled !== 'string' || !shape.values.includes(spelled)) fail(`must be one of ${shape.values.join(', ')}`);
      if (typeof value === 'string' && shape.values.every((item) => /^[0-9]+$/.test(item))) fail('must be a number');
      return;
    }
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) fail('must be a finite number');
      if ((value as number) < shape.min || (value as number) > shape.max) fail(`must be within ${shape.min} to ${shape.max}`);
      if (shape.integer === true && !Number.isInteger(value)) fail('must be a whole number');
      return;
    case 'rgb':
      if (!Array.isArray(value) || value.length !== 3 ||
          !value.every((channel) => typeof channel === 'number' && Number.isFinite(channel) && channel >= 0 && channel <= 1)) {
        fail('must be three linear channels within 0 to 1');
      }
      return;
    case 'object': {
      if (value === null || typeof value !== 'object' || Array.isArray(value)) fail('must be an object');
      const record = value as Record<string, unknown>;
      for (const key of Object.keys(record)) {
        if (!(key in shape.fields)) fail(`has an unknown key ${JSON.stringify(key)}`);
      }
      for (const [key, field] of Object.entries(shape.fields)) {
        if (!(key in record)) fail(`is missing ${JSON.stringify(key)}`);
        check(record[key], field, path === '' ? key : `${path}.${key}`);
      }
      return;
    }
    case 'nullable':
      if (value !== null) check(value, shape.shape, path);
      return;
    case 'variant': {
      if (value === null || typeof value !== 'object' || Array.isArray(value)) fail('must be an object');
      const chosen = (value as Record<string, unknown>)[shape.key];
      const variant = typeof chosen === 'string' && Object.hasOwn(shape.variants, chosen) ? shape.variants[chosen] : undefined;
      if (variant === undefined) fail(`${shape.key} must be one of ${Object.keys(shape.variants).join(', ')}`);
      check(value, variant!, path);
      return;
    }
  }
}

/** Refuse anything that is not a complete, in-range look. Returns a frozen copy. */
export function validateTileLook(value: unknown): TileLookV1 {
  check(value, SHAPE, '');
  const look = value as TileLookV1;
  if (look.fog.endM <= look.fog.startM) throw new TileLookError('fog: endM must lie beyond startM');
  if (!look.surface.parallax && look.surface.parallaxFactor !== 0) {
    throw new TileLookError('surface: parallaxFactor must be 0 while parallax is off');
  }
  return deepFreeze(structuredClone(look));
}

/** The unit vector the sun's light travels along, in world space (+Y up). */
export function sunDirection(look: { readonly sun: { readonly elevationDeg: number; readonly azimuthDeg: number } }): readonly [number, number, number] {
  const elevation = (look.sun.elevationDeg * Math.PI) / 180;
  const azimuth = (look.sun.azimuthDeg * Math.PI) / 180;
  const horizontal = Math.cos(elevation);
  return [-horizontal * Math.sin(azimuth), -Math.sin(elevation), -horizontal * Math.cos(azimuth)];
}

/*
 * THE RENDER LOOK: the light, sky, atmosphere and finish a style pack chooses.
 *
 * A second descriptor beside the tile look, not a new version of it: the tile look's `version`
 * counts changes to its values, and these are new capabilities. Every one is a reviewed renderer
 * capability with bounded parameters; a pack chooses and sets them and can never supply code. The
 * tile look stays the default, so a world draws exactly as before until a pack names a render look.
 *
 * What it adds over the tile look, each bounded here and applied in `environment.ts`:
 *
 * - a high dynamic range sky drawn from a function (gradient, sun disc and glow, clouds), and image
 *   light prefiltered from the same function with a neutral ground below the horizon, so a coloured
 *   ground in the picture does not tint every wall;
 * - exponential fog as well as linear fog (a linear fog keeps the 40 to 60 m onset target);
 * - a shadow filter choice (one tap, three, five, or soft contact-hardening PCSS);
 * - the camera frame's bloom, grading, colour enhancement, vignette and temporal anti-aliasing;
 * - a shading model: physically based, toon (two lit bands) or flat (faceted), and ink lines;
 * - ground beyond the tiles, so a world never stands on a plane in a void.
 *
 * The environment probe and the contact shadowing keep their tile-look rule: no off switch.
 */

export const RENDER_LOOK_ID = 'exulanica.render-look';

export type ShadingModel = 'pbr' | 'toon' | 'flat';
export type RenderShadowFilter = 'pcf1' | 'pcf3' | 'pcf5' | 'pcss';

export interface RenderClouds {
  /** Share of the sky above the horizon the clouds cover, 0 to 1. */
  readonly cover: number;
  readonly colour: Rgb;
  /** The colour of a cloud's side away from the sun. */
  readonly shade: Rgb;
  /** Larger draws larger clouds. */
  readonly scale: number;
  /** Which clouds: the same seed always draws the same sky. */
  readonly seed: number;
}

export interface RenderSky {
  readonly zenith: Rgb;
  readonly horizon: Rgb;
  readonly ground: Rgb;
  /** What the image light sees below the horizon. */
  readonly bounceGround: Rgb;
  /** Linear radiance multiplier for the whole sky. */
  readonly intensity: number;
  /** Brightness of the glow round the sun, in multiples of the sun's colour. */
  readonly sunGlow: number;
  /** Radiance of the sun's disc, in multiples of the sun's colour; drawn in the sky, never in the image light. */
  readonly sunDisc: number;
  readonly clouds: RenderClouds | null;
  /** Edge length of each face of the sky cubemap, in texels. */
  readonly faceTexels: number;
}

export type RenderFog =
  | { readonly kind: 'linear'; readonly startM: number; readonly endM: number; readonly colour: Rgb }
  | { readonly kind: 'exp2'; readonly density: number; readonly colour: Rgb };

export interface RenderPost {
  readonly bloom: { readonly intensity: number; readonly blurLevel: number } | null;
  readonly grading: { readonly brightness: number; readonly contrast: number; readonly saturation: number; readonly tint: Rgb };
  readonly enhance: { readonly shadows: number; readonly highlights: number; readonly midtones: number; readonly vibrance: number; readonly dehaze: number };
  readonly vignette: { readonly intensity: number; readonly inner: number; readonly outer: number; readonly curvature: number; readonly colour: Rgb } | null;
  readonly taa: boolean;
}

export interface RenderToon {
  /** Lit share of the diffuse light at which shade turns to the first lit band. */
  readonly shadowEdge: number;
  /** Lit share at which the first band turns to full light. */
  readonly lightEdge: number;
  /** Brightness of the first band, as a share of full light. */
  readonly bandShare: number;
  /** Width of each band's edge: 0.005 is a hard line, 0.2 a soft one. */
  readonly softness: number;
}

export interface RenderShading {
  readonly model: ShadingModel;
  /** Present exactly when the model is toon. */
  readonly toon: RenderToon | null;
  /** Ink lines on creases and outlines of the world's structure, or none. */
  readonly ink: Rgb | null;
}

export interface RenderEdge {
  /** The ground beyond the tiles, linear colour. */
  readonly ground: Rgb;
  /** How far below the tiles' datum it lies: below every carriageway, so it never shows through one. */
  readonly dropM: number;
  /** How far it reaches from the world's middle, in metres. */
  readonly reachM: number;
}

export interface RenderLook {
  readonly id: typeof RENDER_LOOK_ID;
  readonly version: number;
  readonly exposure: number;
  readonly toneMapping: TileToneMapping;
  readonly sky: RenderSky;
  readonly fog: RenderFog;
  readonly sun: {
    readonly elevationDeg: number;
    readonly azimuthDeg: number;
    readonly colour: Rgb;
    readonly intensity: number;
    readonly shadow: {
      readonly resolution: number;
      readonly distanceM: number;
      readonly cascades: number;
      readonly cascadeDistribution: number;
      readonly bias: number;
      readonly normalOffsetBias: number;
      readonly filter: RenderShadowFilter;
      /** Penumbra size for PCSS; 0 for every other filter. */
      readonly penumbra: number;
    };
  };
  readonly environment: TileLookV1['environment'];
  readonly contactShadow: TileLookV1['contactShadow'];
  readonly surface: TileLookV1['surface'];
  readonly post: RenderPost;
  readonly shading: RenderShading;
  readonly edge: RenderEdge | null;
  readonly unavailable: TileLookV1['unavailable'];
}

/**
 * Either descriptor the runtime draws with. The tile runtime takes a `TileLook` and passes it on
 * unread except for its id, version, surface and unavailable rules, which both descriptors state
 * alike; the environment reads which one it is by its id.
 */
export type TileLook = TileLookV1 | RenderLook;

export const isRenderLook = (look: TileLook): look is RenderLook => look.id === RENDER_LOOK_ID;

const nullable = (shape: Shape): Shape => ({ kind: 'nullable', shape });
const enumOf = (...values: string[]): Shape => ({ kind: 'enum', values });

/** The tile look's sections a render look keeps unchanged, by the same bounds. */
const tileField = (name: string): Shape => (SHAPE as { readonly fields: Readonly<Record<string, Shape>> }).fields[name]!;

const RENDER_SHAPE: Shape = obj({
  id: { kind: 'literal', value: RENDER_LOOK_ID },
  version: num(1, 1_000_000, true),
  exposure: num(0.25, 4),
  toneMapping: enumOf('aces', 'aces2', 'neutral', 'filmic', 'linear'),
  sky: obj({
    zenith: rgb, horizon: rgb, ground: rgb, bounceGround: rgb,
    intensity: num(0.25, 4),
    sunGlow: num(0, 2),
    sunDisc: num(0, 64),
    clouds: nullable(obj({ cover: num(0, 1), colour: rgb, shade: rgb, scale: num(0.25, 4), seed: num(0, 2_147_483_647, true) })),
    faceTexels: enumOf('64', '128', '256'),
  }),
  fog: {
    kind: 'variant',
    key: 'kind',
    variants: {
      // The architecture target holds for a linear fog: onset 40 to 60 m.
      linear: obj({ kind: { kind: 'literal', value: 'linear' }, startM: num(40, 60), endM: num(61, 4000), colour: rgb }),
      // At the most, 0.006 per metre leaves nine tenths of a surface 50 m away unfogged.
      exp2: obj({ kind: { kind: 'literal', value: 'exp2' }, density: num(0.0001, 0.006), colour: rgb }),
    },
  },
  sun: obj({
    elevationDeg: num(5, 85),
    azimuthDeg: num(0, 360),
    colour: rgb,
    intensity: num(0, 10),
    shadow: obj({
      resolution: enumOf('1024', '2048', '4096'),
      distanceM: num(10, 400),
      cascades: num(1, 4, true),
      cascadeDistribution: num(0, 1),
      bias: num(0, 1),
      normalOffsetBias: num(0, 1),
      filter: enumOf('pcf1', 'pcf3', 'pcf5', 'pcss'),
      penumbra: num(0, 64),
    }),
  }),
  environment: tileField('environment'),
  contactShadow: tileField('contactShadow'),
  surface: tileField('surface'),
  post: obj({
    bloom: nullable(obj({ intensity: num(0, 0.2), blurLevel: num(1, 16, true) })),
    grading: obj({ brightness: num(0.5, 1.5), contrast: num(0.5, 1.5), saturation: num(0, 2), tint: rgb }),
    enhance: obj({ shadows: num(-1, 1), highlights: num(-1, 1), midtones: num(-1, 1), vibrance: num(-1, 1), dehaze: num(-1, 1) }),
    vignette: nullable(obj({ intensity: num(0, 1), inner: num(0, 1.5), outer: num(0, 2), curvature: num(0.1, 10), colour: rgb })),
    taa: { kind: 'boolean' },
  }),
  shading: obj({
    model: enumOf('pbr', 'toon', 'flat'),
    toon: nullable(obj({ shadowEdge: num(0, 1), lightEdge: num(0, 1), bandShare: num(0, 1), softness: num(0.005, 0.2) })),
    ink: nullable(rgb),
  }),
  edge: nullable(obj({ ground: rgb, dropM: num(0.2, 5), reachM: num(200, 8000) })),
  unavailable: tileField('unavailable'),
});

/** Refuse anything that is not a complete, in-range render look. Returns a frozen copy. */
export function validateRenderLook(value: unknown): RenderLook {
  check(value, RENDER_SHAPE, '');
  const look = value as RenderLook;
  if (look.fog.kind === 'linear' && look.fog.endM <= look.fog.startM) throw new TileLookError('fog: endM must lie beyond startM');
  if (!look.surface.parallax && look.surface.parallaxFactor !== 0) {
    throw new TileLookError('surface: parallaxFactor must be 0 while parallax is off');
  }
  if ((look.shading.model === 'toon') !== (look.shading.toon !== null)) {
    throw new TileLookError('shading: toon bands are stated exactly when the model is toon');
  }
  if (look.shading.toon !== null && look.shading.toon.shadowEdge >= look.shading.toon.lightEdge) {
    throw new TileLookError('shading.toon: shadowEdge must lie below lightEdge');
  }
  if (look.sun.shadow.filter !== 'pcss' && look.sun.shadow.penumbra !== 0) {
    throw new TileLookError('sun.shadow: penumbra must be 0 unless the filter is pcss');
  }
  return deepFreeze(structuredClone(look));
}

/** Either descriptor, validated by its own rules: the id says which. */
export function validateLook(value: unknown): TileLook {
  const id = value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as { id?: unknown }).id : undefined;
  return id === RENDER_LOOK_ID ? validateRenderLook(value) : validateTileLook(value);
}

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

export interface TileLook {
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
export const TILE_LOOK_V1: TileLook = deepFreeze({
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
    mode: 'lighting',
    radiusM: 0.9,
    intensity: 0.6,
    samples: 12,
    power: 3,
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
  | { readonly kind: 'object'; readonly fields: Readonly<Record<string, Shape>> };

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
  }
}

/** Refuse anything that is not a complete, in-range look. Returns a frozen copy. */
export function validateTileLook(value: unknown): TileLook {
  check(value, SHAPE, '');
  const look = value as TileLook;
  if (look.fog.endM <= look.fog.startM) throw new TileLookError('fog: endM must lie beyond startM');
  if (!look.surface.parallax && look.surface.parallaxFactor !== 0) {
    throw new TileLookError('surface: parallaxFactor must be 0 while parallax is off');
  }
  return deepFreeze(structuredClone(look));
}

/** The unit vector the sun's light travels along, in world space (+Y up). */
export function sunDirection(look: TileLook): readonly [number, number, number] {
  const elevation = (look.sun.elevationDeg * Math.PI) / 180;
  const azimuth = (look.sun.azimuthDeg * Math.PI) / 180;
  const horizontal = Math.cos(elevation);
  return [-horizontal * Math.sin(azimuth), -Math.sin(elevation), -horizontal * Math.cos(azimuth)];
}

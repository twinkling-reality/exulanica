/**
 * The data view's look, as one versioned and validated descriptor.
 *
 * Every look parameter the data end of the representation slider uses lives here and nowhere
 * else: the palette by origin and by subject kind, point size and its attenuation, glow, depth
 * fade, the dash shape of the visualization treatment and its motion, the dark ground, box line
 * colour, link colour and tag typography. Shaders and overlays receive these values; they do not
 * carry literals of their own.
 *
 * WHY THIS IS NOT IN THE WORLD STYLE REGISTRY. The registry (`exulanica/world/style-registry.v1.json`)
 * is server authority over how a world is composed: the browser compares the served catalog with
 * its own copy, the database holds a third copy, and a value change there needs a migration. The
 * data view is none of that. It is a client presentation over records the view already holds; it
 * writes nothing, enters no digest, and never changes what a world is. Putting it in the registry
 * would turn a look into stored world state and into part of the style handshake, which is exactly
 * what the data view rules forbid. So it is a versioned descriptor here, in plain JSON-compatible
 * data, and its id and version travel into every display record instead.
 *
 * A change to any value is a new version. The descriptor is validated when this module loads, so a
 * bad edit fails every test that imports atlas-core rather than drawing something unexplained.
 */

/** The closed origin set, restated so this module has no import cycle with representation.ts. */
const ORIGINS = ['inferred', 'authored', 'generated', 'external'] as const;
/** Subject kinds every version colours. */
const SUBJECT_KINDS = ['scene', 'object', 'geometry-group'] as const;
/** Version 1's closed kind list: the subject kinds and the city.v1 identity record kinds. */
const KINDS_V1 = [
  ...SUBJECT_KINDS,
  'city.massing', 'city.facade', 'city.surface_material', 'city.vitrine', 'city.premises',
] as const;
/** A city grammar record kind. `city.tile` is a tile header, never a subject. */
const CITY_KIND = /^city\.(?!tile$)[a-z][a-z0-9_]{0,63}$/;
const MAX_KINDS = 128;

export type DataViewOriginKey = (typeof ORIGINS)[number];
/**
 * A key of the kind palette. Version 1 names exactly its closed list; from version 2 the palette
 * declares its own city record kinds as data, beside the three subject kinds.
 */
export type DataViewKindKey = string;
/** Lowercase `#rrggbb`, a display colour. The data view shaders write it without tone mapping. */
export type DataViewHex = string;

export interface DataViewStyle {
  readonly id: 'exulanica.data-view';
  readonly version: number;
  /**
   * What the background fades to as points come in: the sky, and every pixel a dissolving surface
   * has given up. `rise` is how many times faster than the slider it darkens, so the ground is
   * dark by the time a surface is half dissolved.
   */
  readonly ground: { readonly colour: DataViewHex; readonly strength: number; readonly rise: number };
  readonly points: {
    /** Sprite width in world metres; the camera's own projection turns it into pixels. */
    readonly sizeMetres: number;
    readonly minPixels: number;
    readonly maxPixels: number;
    /** Samples per square metre of a sampled surface, before the frame budget scales them down. */
    readonly densityPerSquareMetre: number;
    /** Display gain of one point, 0 to 1. Additive, so overlapping points brighten. */
    readonly intensity: number;
    /** How many times faster than the slider a subject's points reach full strength. */
    readonly rise: number;
    /** How far towards the viewer a sample is drawn, so its own dissolving surface cannot hide it. */
    readonly pullMetres: number;
    /** Gain of the subject selected in the panel, relative to the others. */
    readonly selectedGain: number;
    /** Gain of every subject that is not selected while one is. */
    readonly unselectedGain: number;
    readonly glow: {
      /** Squared radius, as a fraction of the sprite, of the solid core. */
      readonly core: number;
      /** Exponential falloff of the halo over the squared radius. */
      readonly falloff: number;
      /** Halo strength relative to the core. */
      readonly halo: number;
    };
    readonly depthFade: {
      readonly startMetres: number;
      readonly endMetres: number;
      readonly density: number;
    };
    /**
     * Beyond `keepAllWithinMetres` a stable subset of samples is drawn, falling with the square of
     * distance, and each survivor is brightened by up to `maxGain` for the ones left out.
     */
    readonly thinning: {
      readonly keepAllWithinMetres: number;
      readonly maxGain: number;
    };
  };
  /** The visualization treatment: short vertical dashes with a slow falling band. */
  readonly dashes: {
    /** Half width of a dash as a fraction of its sprite. */
    readonly halfWidth: number;
    /** Dash sprites are this many times a point sprite. */
    readonly sizeScale: number;
    /** Bands per metre of height. */
    readonly bandsPerMetre: number;
    /** Band travel, in bands per second. Zero, or reduced motion, holds it still. */
    readonly bandsPerSecond: number;
    /** How much a band dims the dash between its crests, 0 to 1. */
    readonly bandDepth: number;
  };
  readonly palette: {
    readonly origin: Readonly<Record<DataViewOriginKey, DataViewHex>>;
    readonly kind: Readonly<Record<DataViewKindKey, DataViewHex>>;
  };
  readonly boxes: {
    readonly colour: DataViewHex;
    readonly opacity: number;
    readonly selectedColour: DataViewHex;
    readonly selectedOpacity: number;
    /** 1 draws whole edges; less draws that fraction of each edge from every corner. */
    readonly cornerFraction: number;
  };
  readonly links: {
    readonly colour: DataViewHex;
    readonly opacity: number;
    readonly maxCount: number;
  };
  readonly tags: {
    readonly fontFamily: string;
    readonly fontSizePixels: number;
    readonly textColour: DataViewHex;
    readonly backgroundColour: DataViewHex;
    readonly backgroundOpacity: number;
    readonly maxCount: number;
  };
}

/** Version 1. The owner's reference: a dark ground, warm glowing points, thin boxes, small tags. */
export const DATA_VIEW_STYLE_V1 = {
  id: 'exulanica.data-view',
  version: 1,
  ground: { colour: '#06080c', strength: 0.94, rise: 2.5 },
  points: {
    sizeMetres: 0.3,
    minPixels: 1.5,
    maxPixels: 6,
    densityPerSquareMetre: 4,
    intensity: 0.85,
    rise: 2,
    pullMetres: 0.2,
    selectedGain: 1.35,
    unselectedGain: 0.55,
    glow: { core: 0.16, falloff: 4, halo: 0.45 },
    depthFade: { startMetres: 150, endMetres: 1800, density: 0.9 },
    thinning: { keepAllWithinMetres: 160, maxGain: 3 },
  },
  dashes: {
    halfWidth: 0.2,
    sizeScale: 1.8,
    bandsPerMetre: 0.25,
    bandsPerSecond: 0.35,
    bandDepth: 0.55,
  },
  palette: {
    origin: {
      inferred: '#ffc266',
      authored: '#fff0b8',
      generated: '#ff8f3f',
      external: '#6fd3ff',
    },
    kind: {
      'scene': '#ffcf70',
      'object': '#8fe3ff',
      'geometry-group': '#ff9a4a',
      'city.massing': '#ff9a4a',
      'city.facade': '#ffd27a',
      'city.surface_material': '#d9a3ff',
      'city.vitrine': '#6fe0c8',
      'city.premises': '#c6f07a',
    },
  },
  boxes: {
    colour: '#ffd79a',
    opacity: 0.5,
    selectedColour: '#ffffff',
    selectedOpacity: 0.95,
    cornerFraction: 1,
  },
  links: { colour: '#ffd79a', opacity: 0.4, maxCount: 64 },
  tags: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    fontSizePixels: 10,
    textColour: '#ffe9c9',
    backgroundColour: '#0a0c11',
    backgroundOpacity: 0.78,
    maxCount: 48,
  },
} as const;

/**
 * Version 2. Every value of version 1 unchanged, and the kind palette declares a colour for every
 * city grammar version 2 record kind that can be a spatial subject (it states an extent). Buildings
 * stay warm, streets and their parts cool, land green, objects on the street distinct. The relation
 * records (junction approach, signal) are never subjects and have none; the surface material keeps
 * its version 1 colour for version 1 subjects only.
 */
export const DATA_VIEW_STYLE_V2 = {
  ...DATA_VIEW_STYLE_V1,
  version: 2,
  palette: {
    origin: DATA_VIEW_STYLE_V1.palette.origin,
    kind: {
      ...DATA_VIEW_STYLE_V1.palette.kind,
      'city.rooftop_object': '#ffb86b',
      'city.ground_bay': '#ffe08a',
      'city.entrance': '#fff3b0',
      'city.district': '#9fd98b',
      'city.block': '#b5e37a',
      'city.parcel': '#d4ee8e',
      'city.terrain': '#7fcf9a',
      'city.street': '#6fd3ff',
      'city.street_segment': '#5fb8ff',
      'city.street_node': '#a9c8ff',
      'city.junction': '#7aa8ff',
      'city.lane': '#58e0f0',
      'city.lane_connection': '#8ff0f5',
      'city.crossing': '#e8f4ff',
      'city.road_marking': '#f5f7ff',
      'city.curb_edge': '#b0bfd8',
      'city.parking_space': '#9fb6ff',
      'city.street_furniture': '#ff7fbf',
      'city.street_tree': '#5ee39a',
    },
  },
} as const;

const HEX = /^#[0-9a-f]{6}$/;

function fail(path: string, why: string): never {
  throw new TypeError(`Unsupported data view style: ${path} ${why}`);
}

function record(value: unknown, path: string, keys: readonly string[]): Readonly<Record<string, unknown>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(path, 'is not an object');
  const actual = Object.keys(value);
  const unknown = actual.find(key => !keys.includes(key));
  if (unknown !== undefined) fail(`${path}.${unknown}`, 'is not a known key');
  const missing = keys.find(key => !Object.hasOwn(value, key));
  if (missing !== undefined) fail(`${path}.${missing}`, 'is missing');
  return value as Readonly<Record<string, unknown>>;
}

function number(value: unknown, path: string, min: number, max: number, integer = false): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max
    || (integer && !Number.isSafeInteger(value))) {
    fail(path, `is not a${integer ? 'n integer' : ' number'} from ${min} to ${max}`);
  }
  return value;
}

function hex(value: unknown, path: string): DataViewHex {
  if (typeof value !== 'string' || !HEX.test(value)) fail(path, 'is not a lowercase #rrggbb colour');
  return value;
}

function text(value: unknown, path: string, maxLength: number, pattern: RegExp): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength || !pattern.test(value)) {
    fail(path, 'is not supported text');
  }
  return value;
}

/**
 * Validate a descriptor and return a deep-frozen copy. Unknown keys, missing keys, wrong types and
 * out-of-range values are refused, at every level, with the path of the first offending key.
 */
export function dataViewStyle(value: unknown): DataViewStyle {
  const root = record(value, 'style', ['id', 'version', 'ground', 'points', 'dashes', 'palette', 'boxes', 'links', 'tags']);
  if (root['id'] !== 'exulanica.data-view') fail('style.id', 'is not exulanica.data-view');
  const version = number(root['version'], 'style.version', 1, 2, true);
  const ground = record(root['ground'], 'style.ground', ['colour', 'strength', 'rise']);
  const points = record(root['points'], 'style.points', [
    'sizeMetres', 'minPixels', 'maxPixels', 'densityPerSquareMetre', 'intensity', 'rise', 'pullMetres',
    'selectedGain', 'unselectedGain', 'glow', 'depthFade', 'thinning',
  ]);
  const glow = record(points['glow'], 'style.points.glow', ['core', 'falloff', 'halo']);
  const fade = record(points['depthFade'], 'style.points.depthFade', ['startMetres', 'endMetres', 'density']);
  const thinning = record(points['thinning'], 'style.points.thinning', ['keepAllWithinMetres', 'maxGain']);
  const dashes = record(root['dashes'], 'style.dashes', ['halfWidth', 'sizeScale', 'bandsPerMetre', 'bandsPerSecond', 'bandDepth']);
  const palette = record(root['palette'], 'style.palette', ['origin', 'kind']);
  const origin = record(palette['origin'], 'style.palette.origin', ORIGINS);
  const kindKeys = version === 1 ? [...KINDS_V1] : declaredKinds(palette['kind']);
  const kind = record(palette['kind'], 'style.palette.kind', kindKeys);
  const boxes = record(root['boxes'], 'style.boxes', ['colour', 'opacity', 'selectedColour', 'selectedOpacity', 'cornerFraction']);
  const links = record(root['links'], 'style.links', ['colour', 'opacity', 'maxCount']);
  const tags = record(root['tags'], 'style.tags', [
    'fontFamily', 'fontSizePixels', 'textColour', 'backgroundColour', 'backgroundOpacity', 'maxCount',
  ]);
  const minPixels = number(points['minPixels'], 'style.points.minPixels', 1, 64);
  const maxPixels = number(points['maxPixels'], 'style.points.maxPixels', 1, 64);
  if (maxPixels < minPixels) fail('style.points.maxPixels', 'is below minPixels');
  const startMetres = number(fade['startMetres'], 'style.points.depthFade.startMetres', 0, 100_000);
  const endMetres = number(fade['endMetres'], 'style.points.depthFade.endMetres', 0, 100_000);
  if (endMetres <= startMetres) fail('style.points.depthFade.endMetres', 'is not beyond startMetres');
  const style: DataViewStyle = {
    id: 'exulanica.data-view',
    version,
    ground: {
      colour: hex(ground['colour'], 'style.ground.colour'),
      strength: number(ground['strength'], 'style.ground.strength', 0, 1),
      rise: number(ground['rise'], 'style.ground.rise', 1, 16),
    },
    points: {
      sizeMetres: number(points['sizeMetres'], 'style.points.sizeMetres', 0.001, 10),
      minPixels,
      maxPixels,
      densityPerSquareMetre: number(points['densityPerSquareMetre'], 'style.points.densityPerSquareMetre', 0.001, 10_000),
      intensity: number(points['intensity'], 'style.points.intensity', 0, 1),
      rise: number(points['rise'], 'style.points.rise', 1, 16),
      pullMetres: number(points['pullMetres'], 'style.points.pullMetres', 0, 5),
      selectedGain: number(points['selectedGain'], 'style.points.selectedGain', 1, 4),
      unselectedGain: number(points['unselectedGain'], 'style.points.unselectedGain', 0, 1),
      glow: {
        core: number(glow['core'], 'style.points.glow.core', 0, 1),
        falloff: number(glow['falloff'], 'style.points.glow.falloff', 0, 64),
        halo: number(glow['halo'], 'style.points.glow.halo', 0, 4),
      },
      depthFade: {
        startMetres,
        endMetres,
        density: number(fade['density'], 'style.points.depthFade.density', 0, 16),
      },
      thinning: {
        keepAllWithinMetres: number(thinning['keepAllWithinMetres'], 'style.points.thinning.keepAllWithinMetres', 1, 100_000),
        maxGain: number(thinning['maxGain'], 'style.points.thinning.maxGain', 1, 16),
      },
    },
    dashes: {
      halfWidth: number(dashes['halfWidth'], 'style.dashes.halfWidth', 0.01, 1),
      sizeScale: number(dashes['sizeScale'], 'style.dashes.sizeScale', 1, 8),
      bandsPerMetre: number(dashes['bandsPerMetre'], 'style.dashes.bandsPerMetre', 0, 100),
      bandsPerSecond: number(dashes['bandsPerSecond'], 'style.dashes.bandsPerSecond', 0, 10),
      bandDepth: number(dashes['bandDepth'], 'style.dashes.bandDepth', 0, 1),
    },
    palette: {
      origin: Object.fromEntries(ORIGINS.map(key => [key, hex(origin[key], `style.palette.origin.${key}`)])) as Record<DataViewOriginKey, DataViewHex>,
      kind: Object.fromEntries(kindKeys.map(key => [key, hex(kind[key], `style.palette.kind.${key}`)])) as Record<DataViewKindKey, DataViewHex>,
    },
    boxes: {
      colour: hex(boxes['colour'], 'style.boxes.colour'),
      opacity: number(boxes['opacity'], 'style.boxes.opacity', 0, 1),
      selectedColour: hex(boxes['selectedColour'], 'style.boxes.selectedColour'),
      selectedOpacity: number(boxes['selectedOpacity'], 'style.boxes.selectedOpacity', 0, 1),
      cornerFraction: number(boxes['cornerFraction'], 'style.boxes.cornerFraction', 0.05, 1),
    },
    links: {
      colour: hex(links['colour'], 'style.links.colour'),
      opacity: number(links['opacity'], 'style.links.opacity', 0, 1),
      maxCount: number(links['maxCount'], 'style.links.maxCount', 0, 1024, true),
    },
    tags: {
      fontFamily: text(tags['fontFamily'], 'style.tags.fontFamily', 160, /^[A-Za-z0-9 ,\-_"']+$/),
      fontSizePixels: number(tags['fontSizePixels'], 'style.tags.fontSizePixels', 6, 32),
      textColour: hex(tags['textColour'], 'style.tags.textColour'),
      backgroundColour: hex(tags['backgroundColour'], 'style.tags.backgroundColour'),
      backgroundOpacity: number(tags['backgroundOpacity'], 'style.tags.backgroundOpacity', 0, 1),
      maxCount: number(tags['maxCount'], 'style.tags.maxCount', 0, 1024, true),
    },
  };
  return deepFreeze(style);
}

/** The kind keys a version 2 palette declares: the subject kinds, then its own city record kinds. */
function declaredKinds(value: unknown): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail('style.palette.kind', 'is not an object');
  const keys = Object.keys(value);
  if (keys.length > MAX_KINDS) fail('style.palette.kind', `declares more than ${MAX_KINDS} kinds`);
  const unknown = keys.find(key => !(SUBJECT_KINDS as readonly string[]).includes(key) && !CITY_KIND.test(key));
  if (unknown !== undefined) fail(`style.palette.kind.${unknown}`, 'is not a known key');
  return [...SUBJECT_KINDS, ...keys.filter(key => CITY_KIND.test(key))];
}

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/** The descriptor every data view draw uses. Validated once, here. */
export const DATA_VIEW_STYLE: DataViewStyle = dataViewStyle(DATA_VIEW_STYLE_V2);

/** `id@version`, the form a display record carries. */
export function dataViewStyleName(style: DataViewStyle): string {
  return `${style.id}@${style.version}`;
}

/** A validated hex colour as three display components from 0 to 1. */
export function dataViewRgb(colour: DataViewHex): readonly [number, number, number] {
  if (!HEX.test(colour)) throw new TypeError('Data view colours are lowercase #rrggbb');
  const value = Number.parseInt(colour.slice(1), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

/** A kind version 1's closed list names. */
export function isDataViewKindKey(value: string): value is DataViewKindKey {
  return (KINDS_V1 as readonly string[]).includes(value);
}

/** The colour a style declares for a kind, or undefined when it declares none. Never a fallback. */
export function dataViewKindColour(style: Pick<DataViewStyle, 'palette'>, kind: string): DataViewHex | undefined {
  return Object.hasOwn(style.palette.kind, kind) ? style.palette.kind[kind] : undefined;
}

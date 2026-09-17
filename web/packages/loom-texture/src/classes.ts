import { canonicalJson } from './canonical-json.js';
import { floorDiv } from './integer.js';

/**
 * MATERIAL CLASSES, AND EXACTLY WHAT A CONTAINER OF EACH CLASS HOLDS.
 *
 * A set is drawn by its class and by nothing else: never by its id, its title or its family. The
 * class says how a renderer draws it, and the class with the maker's kind says which maps the
 * container holds, in which order and packed how. Nothing here is a default. A reader holds a
 * container to exactly one of the layouts below, and a class or layout it was not written for is
 * a refusal, never a guess.
 *
 * The meanings are glTF 2.0's wherever glTF has one:
 *
 *   - `opaque`: metallic-roughness, `alphaMode: OPAQUE`. Every set published before this module.
 *   - `cutout`: `alphaMode: MASK` with the cutoff below, lit on both faces. Foliage.
 *   - `decal`: `alphaMode: BLEND` on geometry laid over another surface. Road paint.
 *   - `glazing`: metalness 0 with `KHR_materials_transmission` and `KHR_materials_ior`. The base
 *     colour tints transmitted light; where transmission is below 255 the rest is a film lit with
 *     the same colour and roughness.
 *
 * The list is closed and append-only: a class is never renamed, and a new one (an emissive class,
 * once daylight is modelled) is a new entry that every reader refuses until it is taught it.
 */
export const MATERIAL_CLASSES = ['opaque', 'cutout', 'decal', 'glazing'] as const;
export type MaterialClass = (typeof MATERIAL_CLASSES)[number];

/**
 * How a set's texels came to be. A procedural maker computes every texel from a recipe, so its
 * set rebakes exactly and may leave out what a rebake restores. A model-made set is a generative
 * model's output: GPU generation is not bit-exact, so its stored bytes are the artifact, and it
 * ships every map the model produced.
 */
export const MAKER_KINDS = ['procedural', 'model'] as const;
export type MakerKind = (typeof MAKER_KINDS)[number];

/** The four-map opaque layout every set published before material classes uses. */
export const SET_PROFILE_V1 = 'exulanica.texture-set/v1';
/** A container that states its class, its maker's kind and that class's layout. */
export const SET_PROFILE_V2 = 'exulanica.texture-set/v2';
export const SET_PROFILES = [SET_PROFILE_V1, SET_PROFILE_V2] as const;
export type SetProfile = (typeof SET_PROFILES)[number];

/** The classes whose procedural makers bake a height field, and so state its range and cavity. */
export const RELIEF_CLASSES: readonly MaterialClass[] = ['opaque', 'cutout', 'decal'];

export const NORMAL_CONVENTION = 'glTF: +X toward increasing u, +Y toward row 0, +Z out of the surface';

/** One map, exactly as a header states it, less its offset and length. */
export interface MapDescriptor {
  readonly name: string;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
  readonly decode: string;
  readonly space?: 'tangent';
  readonly convention?: string;
}

export const BASE_COLOR: MapDescriptor = {
  name: 'base_color',
  components: 3,
  holds: ['red', 'green', 'blue'],
  srgb: true,
  decode: 'sRGB transfer function to linear reflectance',
};

/** Colour and coverage in one map, as `SRGB8_ALPHA8` holds them: sRGB colour, linear coverage. */
export const BASE_COLOR_COVERAGE: MapDescriptor = {
  name: 'base_color_coverage',
  components: 4,
  holds: ['red', 'green', 'blue', 'coverage'],
  srgb: true,
  decode:
    'red, green and blue: sRGB transfer function to linear reflectance; coverage: b / 255, '
    + 'linear, 0 where nothing covers',
};

export const NORMAL_XYZ: MapDescriptor = {
  name: 'normal',
  components: 3,
  holds: ['normal_x', 'normal_y', 'normal_z'],
  srgb: false,
  decode: 'n = 2 * b / 255 - 1 per component, then normalise',
  space: 'tangent',
  convention: NORMAL_CONVENTION,
};

/**
 * A tangent-space normal points out of its surface, so z follows from x and y. A procedural set
 * stores two components and the renderer rebuilds the third where it uploads, in arithmetic that
 * enters no digest.
 */
export const NORMAL_XY: MapDescriptor = {
  name: 'normal',
  components: 2,
  holds: ['normal_x', 'normal_y'],
  srgb: false,
  decode: 'x = 2 * b / 255 - 1, and y likewise; z = sqrt(max(0, 1 - x * x - y * y)); then normalise',
  space: 'tangent',
  convention: NORMAL_CONVENTION,
};

export const ORM: MapDescriptor = {
  name: 'orm',
  components: 3,
  holds: ['occlusion', 'roughness', 'metalness'],
  srgb: false,
  decode: 'b / 255, linear; occlusion 255 is unoccluded; roughness is perceptual',
};

export const TRANSMISSION_ROUGHNESS: MapDescriptor = {
  name: 'transmission_roughness',
  components: 2,
  holds: ['transmission', 'roughness'],
  srgb: false,
  decode:
    'b / 255, linear; transmission 255 passes all the light the surface does not reflect; '
    + 'roughness is perceptual',
};

export const HEIGHT: MapDescriptor = {
  name: 'height',
  components: 1,
  holds: ['height'],
  srgb: false,
  decode: 'mm = b * height_range_mm / 255, above the lowest point the set can hold',
};

/** One map to frame: how the header states it, and its bytes. */
export interface FramedMap {
  readonly descriptor: MapDescriptor;
  readonly bytes: Uint8Array;
}

/** `exulanica.texture-set/v1`: the only v1 layout, and every v1 set is `opaque`. */
export const V1_LAYOUT: readonly MapDescriptor[] = [BASE_COLOR, NORMAL_XYZ, ORM, HEIGHT];

/** Which maps a model produced beyond its class's required ones. A procedural maker has no say. */
export interface ModelMaps {
  readonly normal: boolean;
  readonly height: boolean;
}

function colourMap(materialClass: MaterialClass): MapDescriptor {
  return materialClass === 'cutout' || materialClass === 'decal' ? BASE_COLOR_COVERAGE : BASE_COLOR;
}

function surfaceMap(materialClass: MaterialClass): MapDescriptor {
  return materialClass === 'glazing' ? TRANSMISSION_ROUGHNESS : ORM;
}

/**
 * The one layout a v2 container of this class and maker kind holds.
 *
 * A procedural set: its colour map, a two-component normal unless it is glazing (float glass is
 * flat), and its surface map, with no height map, because the height field rebakes exactly from
 * the pinned recipe and no renderer draws it. A model-made set: its colour map, the normal as the
 * model produced it (three components) if it produced one, its surface map, and the height map if
 * it produced one, because a model-made set cannot be rebaked.
 */
export function classLayout(
  materialClass: MaterialClass,
  makerKind: MakerKind,
  produced: ModelMaps = { normal: false, height: false },
): readonly MapDescriptor[] {
  if (makerKind === 'procedural') {
    return materialClass === 'glazing'
      ? [BASE_COLOR, TRANSMISSION_ROUGHNESS]
      : [colourMap(materialClass), NORMAL_XY, ORM];
  }
  return [
    colourMap(materialClass),
    ...(produced.normal ? [NORMAL_XYZ] : []),
    surfaceMap(materialClass),
    ...(produced.height ? [HEIGHT] : []),
  ];
}

/** What a manifest entry states of a map: the packing, without the prose. */
export interface Channel {
  readonly map: string;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
}

export function channelsOf(layout: readonly MapDescriptor[]): Channel[] {
  return layout.map((map) => ({
    map: map.name,
    components: map.components,
    holds: [...map.holds],
    srgb: map.srgb,
  }));
}

/**
 * Every layout a container of this profile and class may hold, as manifest channels. A manifest
 * entry names no maker kind, so it may list the procedural layout or any model-made one; the
 * container's own header then says which it is, and must agree.
 */
export function allowedChannels(profile: SetProfile, materialClass: MaterialClass): Channel[][] {
  if (profile === SET_PROFILE_V1) return materialClass === 'opaque' ? [channelsOf(V1_LAYOUT)] : [];
  const layouts = [classLayout(materialClass, 'procedural')];
  for (const normal of [false, true]) {
    for (const height of [false, true]) {
      layouts.push(classLayout(materialClass, 'model', { normal, height }));
    }
  }
  const seen = new Set<string>();
  const out: Channel[][] = [];
  for (const layout of layouts) {
    const channels = channelsOf(layout);
    const key = canonicalJson(channels);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(channels);
    }
  }
  return out;
}

/**
 * The coverage a cutout set is tested against, as glTF's default `alphaCutoff` of 0.5 reads in a
 * byte. A cutout maker designs its coverage field around this one threshold, and the share of
 * texels at or above it is what a renderer keeps in every mip level.
 */
export const ALPHA_CUTOFF = 128;
/**
 * Soda-lime float glass is about 1.52; glTF's `KHR_materials_ior` default is 1.5, which gives the
 * 0.04 reflectance at normal incidence every physically based renderer assumes for glass.
 */
export const GLAZING_IOR_MILLIONTHS = 1_500_000;

/**
 * The share of texels whose coverage is at least {@link ALPHA_CUTOFF}, in thousandths, floored.
 * Measured by the bake and measured again by every reader, so a header cannot state another.
 */
export function coveragePermille(colourCoverage: Uint8Array): number {
  const texels = colourCoverage.length / 4;
  let covered = 0;
  for (let at = 3; at < colourCoverage.length; at += 4) {
    if (colourCoverage[at]! >= ALPHA_CUTOFF) covered += 1;
  }
  return floorDiv(covered * 1000, texels);
}

/**
 * What a header states under `class`: the numbers a class fixes, each with its reason above, and
 * the one a bake measures. Nothing here is a number a person would name; those are recipe controls.
 */
export function classParameters(
  materialClass: MaterialClass,
  measuredCoveragePermille: number | null,
): Record<string, number | boolean> {
  const coverage = (): number => {
    if (measuredCoveragePermille === null) {
      throw new Error(`a ${materialClass} set states the coverage its bake measured`);
    }
    return measuredCoveragePermille;
  };
  switch (materialClass) {
    case 'opaque':
      return {};
    case 'cutout':
      // A leaf is seen from both of its sides.
      return { alpha_cutoff: ALPHA_CUTOFF, coverage_permille: coverage(), double_sided: true };
    case 'decal':
      return { coverage_permille: coverage() };
    case 'glazing':
      // A street is seen from outside its windows.
      return { double_sided: false, ior_millionths: GLAZING_IOR_MILLIONTHS };
  }
}

export const isMaterialClass = (value: unknown): value is MaterialClass =>
  typeof value === 'string' && (MATERIAL_CLASSES as readonly string[]).includes(value);

export const isMakerKind = (value: unknown): value is MakerKind =>
  typeof value === 'string' && (MAKER_KINDS as readonly string[]).includes(value);

export const isSetProfile = (value: unknown): value is SetProfile =>
  typeof value === 'string' && (SET_PROFILES as readonly string[]).includes(value);

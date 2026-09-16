/**
 * Renderer-neutral visual model shared by authored, personalized, and agent-composed worlds.
 * This file contains no catalog entries and no profile-specific branching.
 */

export type WorldExpansionForm = 'living-buds' | 'survey-stakes';

const WORLD_EXPANSION_FORMS = new Set<WorldExpansionForm>(['living-buds', 'survey-stakes']);

/**
 * How a world draws its atmosphere and the surface a person walks on.
 *
 * These exist because the two decisions are genuinely per-world and genuinely visual: one world
 * stacks a horizon, another opens a single colour field. Before this token the renderer had no
 * way to say that, so it asked for the profile's ID instead, which is exactly the hard-coded
 * one-world exception the world model is supposed to make unnecessary.
 */
export type WorldAtmosphereForm = 'layered-horizon' | 'diffuse-canvas';
export type WorldSurfaceForm = 'reflective-tide' | 'paper-contour';

const WORLD_ATMOSPHERE_FORMS = new Set<WorldAtmosphereForm>(['layered-horizon', 'diffuse-canvas']);
const WORLD_SURFACE_FORMS = new Set<WorldSurfaceForm>(['reflective-tide', 'paper-contour']);

/** A surface may recede almost into the atmosphere, but it may never be authored out of existence. */
export const MIN_SURFACE_PRESENCE = 0.25;
const WORLD_UI_TEXTURES = new Set(['paper-grain', 'contour-grid', 'none']);
const WORLD_UI_BLEND_MODES = new Set(['normal', 'multiply', 'soft-light']);
const WORLD_UI_EASINGS = new Set(['linear', 'cubic-bezier(0.2, 0.7, 0.2, 1)']);
const WORLD_UI_FONT_FAMILIES = new Set([
  '"Avenir Next", "Segoe UI Variable", ui-sans-serif, system-ui, sans-serif',
  '"Avenir Next", "Segoe UI Variable Display", ui-sans-serif, system-ui, sans-serif',
  'ui-monospace, "SFMono-Regular", Consolas, monospace',
  '"Avenir Next", Avenir, ui-sans-serif, system-ui, sans-serif',
  '"Arial Narrow", "Avenir Next Condensed", ui-sans-serif, system-ui, sans-serif',
]);

export interface WorldPalette {
  readonly sky: string;
  readonly haze: string;
  readonly terrain: string;
  readonly terrainLift: string;
  readonly path: string;
  readonly stone: string;
  readonly stoneShadow: string;
  readonly paper: string;
  readonly brass: string;
  readonly sun: string;
}

/**
 * What the interface is made of.
 *
 * The interface used to be derived entirely from `WorldPalette`, which describes the 3D scene.
 * That made single roots serve unrelated jobs: `brass` was the world's warm signal AND
 * user-provenance AND caution, and `terrain` was the ground AND the reading colour AND the plate
 * AND capture-provenance. There was no root meaning "the hue this interface is built from", so
 * one had to be synthesised by mixing the ground with the air, and a world that authored a light
 * ground silently lost every structural colour it had.
 *
 * Five roots, one job each. A recipe may omit this entirely, in which case it is derived from the
 * world palette exactly as before, so an existing profile keeps its appearance and a new one can
 * choose to say what its interface is made of instead of inheriting an accident.
 */
export interface WorldInterfacePalette {
  /** The reading colour. Every textual role descends from this hue. */
  readonly ink: string;
  /** The material a summoned surface is made of. */
  readonly plate: string;
  /** The interface's own hue: accent, focus, active state, selection. */
  readonly structure: string;
  /** The warm mark: user-provided provenance and the evidence accent. */
  readonly evidence: string;
  /** The cool mark: inference, uncertainty, unresolved. */
  readonly uncertain: string;
}

export interface WorldUiColors {
  readonly ground: string;
  readonly surface: string;
  readonly raised: string;
  readonly ink: string;
  readonly body: string;
  readonly muted: string;
  readonly accent: string;
  readonly secondary: string;
  readonly focus: string;
  readonly warning: string;
  readonly error: string;
  readonly user: string;
  readonly capture: string;
  readonly inference: string;
  readonly external: string;
  /**
   * The same four provenance meanings at mark strength.
   *
   * A dot, a band rule and a callout edge are graphical objects, not text, and the requirement
   * for those is 3:1 rather than 4.5. Correcting them to the reading floor took the one bright
   * colour this world authored, `#f96858`, and shipped it as `#be2f25`: the hue survived and the
   * light went out of it. Two strengths per meaning keeps text readable without turning every
   * saturated mark into a darker version of the body copy.
   */
  readonly userMark: string;
  readonly captureMark: string;
  readonly inferenceMark: string;
  readonly externalMark: string;
  readonly companionSurface: string;
  readonly companionSurfaceHover: string;
  readonly companionText: string;
  readonly companionAccent: string;
  readonly companionSecondary: string;
  readonly companionInk: string;
  readonly companionUnavailable: string;
  readonly shadow: string;
  readonly vignette: string;
}

export interface WorldUiRecipe {
  readonly typography: {
    readonly body: string;
    readonly display: string;
    readonly utility: string;
    readonly companion: string;
  };
  readonly material: {
    readonly worldBlur: number;
    readonly systemBlur: number;
    readonly companionBlur: number;
    readonly worldSaturation: number;
    readonly systemSaturation: number;
    readonly companionSaturation: number;
    readonly textureOpacity: number;
  };
  readonly texture: {
    readonly kind: 'paper-grain' | 'contour-grid' | 'none';
    readonly blendMode: 'normal' | 'multiply' | 'soft-light';
  };
  readonly motion: {
    readonly quickMs: number;
    readonly standardMs: number;
    readonly deliberateMs: number;
    readonly idleCycleMs: number;
    readonly workingCycleMs: number;
    readonly staggerMs: number;
    readonly easing: string;
  };
}

export interface WorldUiStyle extends WorldUiRecipe {
  /** Derived from the world palette. A recipe cannot supply an unrelated component palette. */
  readonly colors: WorldUiColors;
}

export interface WorldArtProfileSource {
  readonly profileId: string;
  readonly profileVersion: number;
  readonly displayName: string;
  readonly description: string;
  readonly compatibilityKey: 'atlas-topology-v1';
  readonly geometry: {
    readonly expansion: WorldExpansionForm;
    readonly evidenceSpread: number;
    readonly detailCount: number;
    readonly expansionCount: number;
  };
  /**
   * Atmosphere and traversal-surface treatment. `surfacePresence` scales how strongly the ground
   * reads against the atmosphere; it does not decide whether the ground is drawn. Navigation,
   * collision, and the map field are unaffected by every value here.
   */
  readonly field: {
    readonly atmosphere: WorldAtmosphereForm;
    readonly surface: WorldSurfaceForm;
    readonly surfacePresence: number;
  };
  readonly material: {
    readonly emissiveStrength: number;
    readonly opacity: number;
    readonly metalness: number;
    readonly gloss: number;
    readonly edgeStrength: number;
  };
  readonly palette: WorldPalette;
  /** Omitted means "derive my interface from my scene", which is the historical behaviour. */
  readonly interfacePalette?: WorldInterfacePalette;
  readonly semanticChannels: {
    readonly provenance: readonly ['hue', 'shape'];
    readonly confirmation: readonly ['hue', 'stroke'];
    readonly focus: readonly ['contrast', 'outline'];
  };
  readonly ui: WorldUiRecipe;
}

/** A compiled profile is immutable and contains the contrast-corrected component roles. */
export interface WorldArtProfile extends Omit<WorldArtProfileSource, 'ui'> {
  readonly ui: WorldUiStyle;
}

const HEX = /^#[0-9a-f]{6}$/i;
/** Exactly these five, so a recipe cannot smuggle an unbounded sixth interface colour. */
const INTERFACE_PALETTE_ROOTS = [
  'ink', 'plate', 'structure', 'evidence', 'uncertain',
] as const satisfies readonly (keyof WorldInterfacePalette)[];
const channel = (hex: string, offset: number): number => Number.parseInt(hex.slice(offset, offset + 2), 16);

export const mixHex = (from: string, to: string, amount: number): string => {
  const t = Math.max(0, Math.min(1, amount));
  const mixed = [1, 3, 5].map((offset) =>
    Math.round(channel(from, offset) * (1 - t) + channel(to, offset) * t));
  return `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
};

const relativeLuminance = (hex: string): number => {
  const linear = [1, 3, 5].map((offset) => {
    const value = channel(hex, offset) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return linear[0]! * 0.2126 + linear[1]! * 0.7152 + linear[2]! * 0.0722;
};

export const contrastRatio = (foreground: string, background: string): number => {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
};

/**
 * Perceptual lightness, so darkening a colour does not also drain it.
 *
 * Mixing toward `#000000` in sRGB scales all three channels by the same factor. The channel
 * *ratio* survives and the channel *difference* does not, so a pale tint darkens into grey:
 * `#eef7f2` taken to a readable value arrives at `#545756`, four points of chroma out of the
 * twelve it started with. Every structural role in this file is a darkened world colour, so that
 * one property decided what the whole interface looked like. OKLCH separates lightness from hue
 * and chroma and lets a role be moved along one axis without losing the other two.
 */
interface Oklch {
  readonly l: number;
  readonly c: number;
  readonly h: number;
}

const toLinear = (value: number): number =>
  (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
const toGamma = (value: number): number =>
  (value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055);

const toOklch = (hex: string): Oklch => {
  const [red, green, blue] = [1, 3, 5].map((offset) => toLinear(channel(hex, offset) / 255)) as
    [number, number, number];
  const long = Math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue);
  const medium = Math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue);
  const short = Math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue);
  const lightness = 0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short;
  const a = 1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short;
  const b = 0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short;
  return { l: lightness, c: Math.hypot(a, b), h: Math.atan2(b, a) };
};

const oklabChannels = (lightness: number, a: number, b: number): readonly number[] => {
  const long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [
    toGamma(4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short),
    toGamma(-1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short),
    toGamma(-0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short),
  ];
};

/**
 * Back to sRGB, giving up chroma rather than hue when the request is outside the gamut.
 *
 * A hue that shifts under clipping is a different colour, and provenance reads by hue. Reducing
 * chroma at the requested lightness keeps the mark identifiable as the same one.
 */
const fromOklch = ({ l, c, h }: Oklch): string => {
  const inGamut = (chroma: number): readonly number[] | null => {
    const channels = oklabChannels(l, Math.cos(h) * chroma, Math.sin(h) * chroma);
    return channels.every((value) => value >= -0.001 && value <= 1.001) ? channels : null;
  };
  let resolved = inGamut(c);
  if (resolved === null) {
    let low = 0;
    let high = c;
    resolved = oklabChannels(l, 0, 0);
    for (let iteration = 0; iteration < 24; iteration += 1) {
      const chroma = (low + high) / 2;
      const attempt = inGamut(chroma);
      if (attempt === null) high = chroma; else { resolved = attempt; low = chroma; }
    }
  }
  return `#${resolved
    .map((value) => Math.round(Math.max(0, Math.min(1, value)) * 255).toString(16).padStart(2, '0'))
    .join('')}`;
};

/**
 * A world colour read perceptually.
 *
 * Exposed because "did this world's hue survive derivation" is not answerable from a hex string,
 * and it is exactly the question a green test suite failed to ask while the interface lost every
 * colour it had. `lightness` is 0 to 1, `chroma` is OKLCH chroma, and `hue` is radians.
 */
export function perceptualColour(hex: string): {
  readonly lightness: number;
  readonly chroma: number;
  readonly hue: number;
} {
  const { l, c, h } = toOklch(hex);
  return Object.freeze({ lightness: l, chroma: c, hue: h });
}

/**
 * Construct a colour from perceptual lightness, chroma and hue.
 *
 * Exported because a hue is a circle and there is no pair of authored endpoints a circle can be
 * mixed between, so a module that takes a hue as a parameter has to build its colours rather than
 * interpolate them. This is the only constructor, so gamut mapping stays in one place.
 */
export function oklchHex(lightness: number, chroma: number, hue: number): string {
  return fromOklch({ l: lightness, c: Math.max(0, chroma), h: hue });
}

/**
 * Place a world colour at an authored lightness, keeping its hue.
 *
 * `chromaFloor` rescues a hue a world did author from vanishing at low lightness. `chromaCeiling`
 * is the opposite guard and exists for structure: a role that means nothing by being coloured has
 * to stay under a cap however saturated the world is.
 */
const toneAt = (
  hex: string,
  lightness: number,
  chromaFloor = 0,
  chromaCeiling = Number.POSITIVE_INFINITY,
): string => {
  const { c, h } = toOklch(hex);
  return fromOklch({ l: lightness, c: Math.min(chromaCeiling, Math.max(c, chromaFloor)), h });
};

/**
 * The contrast floor, walked along lightness rather than toward black.
 *
 * This only ever rescues a role that fails its minimum. It is not allowed to be the thing that
 * decides what a role looks like, which is what it had become.
 */
const accessibleTone = (candidate: string, background: string, minimum: number): string => {
  if (contrastRatio(candidate, background) >= minimum) return candidate;
  const { l, c, h } = toOklch(candidate);
  const darken = relativeLuminance(background) > 0.35;
  let low = darken ? 0 : l;
  let high = darken ? l : 1;
  let resolved = fromOklch({ l: darken ? 0 : 1, c, h });
  for (let iteration = 0; iteration < 20; iteration += 1) {
    const lightness = (low + high) / 2;
    const walked = fromOklch({ l: lightness, c, h });
    if (contrastRatio(walked, background) >= minimum) {
      resolved = walked;
      if (darken) low = lightness; else high = lightness;
    } else if (darken) {
      high = lightness;
    } else {
      low = lightness;
    }
  }
  return resolved;
};

/**
 * The authored lightness ladder.
 *
 * Every role is placed at a perceptual lightness first and only then checked against its contrast
 * floor, because the previous derivation had no ladder at all: it handed each role a near-white
 * world colour, and `accessibleTone` was the only thing that ever darkened it. Every role
 * therefore landed within 0.06 of its own floor, so the whole interface occupied two values, 7:1
 * for `ink` and 4.5:1 for the other twelve, and no amount of component work could build a
 * hierarchy out of it. Contrast correction is a floor. It is not a colour picker.
 */
const INTERFACE_LIGHTNESS = Object.freeze({
  ink: 0.3,
  body: 0.46,
  muted: 0.52,
  accent: 0.51,
  secondary: 0.53,
  focus: 0.58,
  warning: 0.52,
  error: 0.48,
  user: 0.53,
  capture: 0.52,
  inference: 0.53,
  external: 0.53,
  companionAccent: 0.52,
  companionSecondary: 0.51,
  companionUnavailable: 0.53,
  shadow: 0.22,
  vignette: 0.36,
});

/**
 * The smallest chroma a structural role may arrive at.
 *
 * A world is allowed to be grey. Survey Relief authors every root under 0.07 chroma and must stay
 * a drab ledger. What a world may not do is lose a hue it did author, which is what happened when
 * the ground root moved to a near-white tint: 0.012 chroma survives being placed at low lightness
 * arithmetically and disappears visually. This floor is small enough that an intentionally grey
 * palette stays grey and large enough that a pale one still reads as coloured. It lifts chroma; it
 * never chooses a hue, so a profile's identity still decides what colour the interface is.
 */
const STRUCTURE_CHROMA_FLOOR = 0.008;

/**
 * The most colour a structural role may carry.
 *
 * Reading text, panel material, shadow and the Companion's own surface are structure. They say
 * nothing by being coloured, and colouring them is how an interface ends up teal: every one of
 * these was a darkened world hue and the result was a product where the type, the rules, the
 * focus ring and the speech band were all tinted and none of that tint meant anything.
 *
 * Hue is reserved for the roles that carry meaning, which is provenance, caution and error, plus
 * one accent. A world still shows through here, because the ceiling is a cap and not a conversion
 * to grey: a warm world reads warm and a cool world reads cool, at the strength of a paper stock
 * rather than of a colour.
 */
const STRUCTURE_CHROMA_CEILING = 0.014;
const EVIDENCE_CHROMA_FLOOR = 0.03;

/**
 * The reading floor, with the margin a real surface costs.
 *
 * `surface` is the lightest reading ground a world has, near-white for a light world. A role
 * corrected to exactly 4.5 against it is not at 4.5 anywhere a component actually puts it: a
 * held plate is made of a paper a few points darker than the theoretical white, and that alone
 * took every mid role to 3.9. Deriving against the lightest possible ground and shipping the bare
 * minimum is how a palette passes its own test and fails on screen, so the mid roles clear the
 * requirement against `surface` by enough to survive the surfaces built from it. The lightness
 * ladder above is set so this rarely engages; it is the safety net, not the author.
 */
const READING_FLOOR = 5.2;

/** Graphical objects and controls, which WCAG separates from text at 3:1. */
const MARK_FLOOR = 3;

/**
 * The interface a world gets when it does not say what its interface is made of.
 *
 * This is the historical derivation, preserved exactly, so an existing profile is unchanged by
 * the arrival of authored interface roots. Structure reads from the ground and the air together:
 * reading it from the ground alone was only ever right while the ground was dark, and the moment
 * a world authored a light field every structural role went grey.
 */
export function interfacePaletteFromWorld(palette: WorldPalette): WorldInterfacePalette {
  return Object.freeze({
    ink: mixHex(palette.terrain, palette.sky, 0.5),
    plate: mixHex(palette.paper, palette.sun, 0.18),
    structure: palette.sky,
    evidence: palette.brass,
    uncertain: palette.stoneShadow,
  });
}

/**
 * Semantic interface roles, from five roots that mean one job each.
 *
 * They used to be read off `WorldPalette`, which describes the 3D scene, so single scene parts
 * served unrelated interface jobs and a world that changed its ground silently changed its
 * reading colour, its plate and two of its provenance marks at the same time.
 */
export function deriveWorldUiColors(
  palette: WorldPalette,
  authored?: WorldInterfacePalette,
): WorldUiColors {
  const face = authored ?? interfacePaletteFromWorld(palette);
  const ground = toneAt(mixHex(palette.haze, face.plate, 0.3),
    toOklch(mixHex(palette.haze, face.plate, 0.3)).l, 0, STRUCTURE_CHROMA_CEILING);
  const surface = toneAt(mixHex(palette.haze, face.plate, 0.58),
    toOklch(mixHex(palette.haze, face.plate, 0.58)).l, 0, STRUCTURE_CHROMA_CEILING);
  const raised = toneAt(face.plate, toOklch(face.plate).l, 0, STRUCTURE_CHROMA_CEILING);
  const structural = (lightness: number): string =>
    toneAt(face.ink, lightness, STRUCTURE_CHROMA_FLOOR, STRUCTURE_CHROMA_CEILING);
  /*
   * The Companion speaks from the same paper everything else is written on.
   *
   * These roles used to resolve to a dark surface with light text, which was right while the held
   * plates were dark too. Once the plates became paper the speech band, the choice rail and the
   * utilities were the only dark slabs left in the product, and a presence that is meant to be in
   * the world instead read as a panel pasted over it. The polarity flips as a set: `text` is the
   * reading colour on paper, and `ink` stays the light one because components use it on top of
   * `text` and `accent` as backgrounds, which is how the speaker-name pill inverts.
   */
  const companionSurface = toneAt(mixHex(face.plate, face.ink, 0.07),
    toOklch(mixHex(face.plate, face.ink, 0.07)).l, 0, STRUCTURE_CHROMA_CEILING);
  return Object.freeze({
    ground,
    surface,
    raised,
    ink: accessibleTone(structural(INTERFACE_LIGHTNESS.ink), raised, 7),
    body: accessibleTone(structural(INTERFACE_LIGHTNESS.body), surface, READING_FLOOR),
    muted: accessibleTone(structural(INTERFACE_LIGHTNESS.muted), surface, READING_FLOOR),
    // The single accent. Focus, active state and the one control worth pointing at, and nothing
    // else: it is the interface's only decorative hue and it is spent in very few places.
    accent: accessibleTone(toneAt(face.structure, INTERFACE_LIGHTNESS.accent), surface, READING_FLOOR),
    secondary: accessibleTone(toneAt(face.evidence, INTERFACE_LIGHTNESS.secondary), surface, READING_FLOOR),
    focus: accessibleTone(toneAt(face.structure, INTERFACE_LIGHTNESS.focus), ground, 3),
    // Caution and user-provided provenance were the same colour while `brass` was the only root
    // with any chroma left. They are different questions and the palette already carries a second
    // warm root for the second one.
    warning: accessibleTone(toneAt(palette.path, INTERFACE_LIGHTNESS.warning), surface, READING_FLOOR),
    error: accessibleTone(
      toneAt(mixHex('#a6404c', face.evidence, 0.12), INTERFACE_LIGHTNESS.error), surface, READING_FLOOR),
    user: accessibleTone(toneAt(face.evidence, INTERFACE_LIGHTNESS.user), surface, READING_FLOOR),
    // The provenance triad is read as three marks side by side, so the three must separate by hue
    // and not only by shape. They take the world's growth, air-shadow and warm roots.
    capture: accessibleTone(
      toneAt(palette.terrainLift, INTERFACE_LIGHTNESS.capture, EVIDENCE_CHROMA_FLOOR), surface, READING_FLOOR),
    inference: accessibleTone(
      toneAt(face.uncertain, INTERFACE_LIGHTNESS.inference, EVIDENCE_CHROMA_FLOOR),
      surface, READING_FLOOR),
    external: accessibleTone(
      toneAt(mixHex(face.uncertain, face.evidence, 0.4), INTERFACE_LIGHTNESS.external,
        EVIDENCE_CHROMA_FLOOR), surface, READING_FLOOR),
    // Marks keep the lightness the world authored and only move if they fail 3:1.
    userMark: accessibleTone(face.evidence, surface, MARK_FLOOR),
    captureMark: accessibleTone(
      toneAt(palette.terrainLift, toOklch(palette.terrainLift).l, EVIDENCE_CHROMA_FLOOR),
      surface, MARK_FLOOR),
    inferenceMark: accessibleTone(face.uncertain, surface, MARK_FLOOR),
    externalMark: accessibleTone(
      mixHex(face.uncertain, face.evidence, 0.4), surface, MARK_FLOOR),
    companionSurface,
    companionSurfaceHover: toneAt(mixHex(face.plate, face.ink, 0.14),
      toOklch(mixHex(face.plate, face.ink, 0.14)).l, 0, STRUCTURE_CHROMA_CEILING),
    companionText: accessibleTone(structural(INTERFACE_LIGHTNESS.ink), companionSurface, 7),
    companionAccent: accessibleTone(
      structural(INTERFACE_LIGHTNESS.companionAccent), companionSurface, READING_FLOOR),
    companionSecondary: accessibleTone(
      structural(INTERFACE_LIGHTNESS.companionSecondary), companionSurface, READING_FLOOR),
    companionInk: companionSurface,
    companionUnavailable: accessibleTone(
      toneAt(face.uncertain, INTERFACE_LIGHTNESS.companionUnavailable), companionSurface,
      READING_FLOOR),
    shadow: structural(INTERFACE_LIGHTNESS.shadow),
    vignette: structural(INTERFACE_LIGHTNESS.vignette),
  });
}

/**
 * A structural tone guaranteed to separate from the world's own paper.
 *
 * A landmark exists to be found from across the field. On a near-white world its stone body is
 * the same value as the air behind it, so the orientation it is supposed to provide disappears.
 * This keeps the silhouette readable from the palette a world already authored, rather than from
 * a colour hard-coded for one world.
 */
export function worldSilhouetteTone(palette: WorldPalette): string {
  return accessibleTone(palette.stoneShadow, palette.paper, 2.6);
}

const freezeSource = (source: WorldArtProfileSource): WorldArtProfileSource => Object.freeze({
  ...source,
  geometry: Object.freeze({ ...source.geometry }),
  field: Object.freeze({ ...source.field }),
  material: Object.freeze({ ...source.material }),
  palette: Object.freeze({ ...source.palette }),
  ...(source.interfacePalette === undefined
    ? {}
    : { interfacePalette: Object.freeze({ ...source.interfacePalette }) }),
  semanticChannels: Object.freeze({
    provenance: Object.freeze([...source.semanticChannels.provenance]) as readonly ['hue', 'shape'],
    confirmation: Object.freeze([...source.semanticChannels.confirmation]) as readonly ['hue', 'stroke'],
    focus: Object.freeze([...source.semanticChannels.focus]) as readonly ['contrast', 'outline'],
  }),
  ui: Object.freeze({
    typography: Object.freeze({ ...source.ui.typography }),
    material: Object.freeze({ ...source.ui.material }),
    texture: Object.freeze({ ...source.ui.texture }),
    motion: Object.freeze({ ...source.ui.motion }),
  }),
});

export function validateWorldArtProfileSource(source: WorldArtProfileSource): void {
  if (!/^[a-z][a-z0-9-]*$/.test(source.profileId)) {
    throw new TypeError(`invalid world profile ID: ${source.profileId}`);
  }
  if (!Number.isSafeInteger(source.profileVersion) || source.profileVersion < 1) {
    throw new TypeError(`invalid world profile version: ${source.profileId}`);
  }
  if (source.displayName.trim().length === 0 || source.description.trim().length === 0) {
    throw new TypeError(`world profile metadata is incomplete: ${source.profileId}`);
  }
  if (source.compatibilityKey !== 'atlas-topology-v1') {
    throw new TypeError(`unsupported topology compatibility: ${source.profileId}`);
  }
  if (!WORLD_EXPANSION_FORMS.has(source.geometry.expansion)) {
    throw new TypeError(`unregistered world geometry form: ${source.profileId}`);
  }
  for (const [name, number] of Object.entries(source.geometry)) {
    if (typeof number === 'number' && (!Number.isFinite(number) || number < 0)) {
      throw new TypeError(`invalid ${source.profileId} geometry token ${name}`);
    }
  }
  if (
    !WORLD_ATMOSPHERE_FORMS.has(source.field.atmosphere) ||
    !WORLD_SURFACE_FORMS.has(source.field.surface)
  ) throw new TypeError(`unregistered world field treatment: ${source.profileId}`);
  if (
    !Number.isFinite(source.field.surfacePresence) ||
    source.field.surfacePresence < MIN_SURFACE_PRESENCE ||
    source.field.surfacePresence > 1
  ) throw new TypeError(`invalid ${source.profileId} surface presence`);
  for (const [name, number] of Object.entries(source.material)) {
    if (!Number.isFinite(number) || number < 0 || number > 1) {
      throw new TypeError(`invalid ${source.profileId} material token ${name}`);
    }
  }
  for (const [name, colour] of Object.entries(source.palette)) {
    if (!HEX.test(colour)) throw new TypeError(`invalid ${source.profileId} palette token ${name}`);
  }
  if (source.interfacePalette !== undefined) {
    const face = source.interfacePalette;
    for (const name of INTERFACE_PALETTE_ROOTS) {
      if (!HEX.test(face[name])) {
        throw new TypeError(`invalid ${source.profileId} interface token ${name}`);
      }
    }
    if (Object.keys(face).length !== INTERFACE_PALETTE_ROOTS.length) {
      throw new TypeError(`unexpected ${source.profileId} interface palette roots`);
    }
  }
  for (const [name, family] of Object.entries(source.ui.typography)) {
    if (!WORLD_UI_FONT_FAMILIES.has(family)) {
      throw new TypeError(`unregistered ${source.profileId} UI font ${name}`);
    }
  }
  for (const [name, amount] of Object.entries(source.ui.material)) {
    const max = name === 'textureOpacity' ? 1 : name.endsWith('Saturation') ? 4 : 64;
    if (!Number.isFinite(amount) || amount < 0 || amount > max) {
      throw new TypeError(`invalid ${source.profileId} UI material ${name}`);
    }
  }
  for (const [name, duration] of Object.entries(source.ui.motion)) {
    if (
      name !== 'easing' &&
      (
        typeof duration !== 'number' || duration < 0 || duration > 10_000 ||
        (name.endsWith('CycleMs') && duration === 0)
      )
    ) throw new TypeError(`invalid ${source.profileId} UI motion ${name}`);
  }
  if (!WORLD_UI_TEXTURES.has(source.ui.texture.kind) || !WORLD_UI_BLEND_MODES.has(source.ui.texture.blendMode)) {
    throw new TypeError(`unregistered ${source.profileId} UI texture`);
  }
  if (!WORLD_UI_EASINGS.has(source.ui.motion.easing)) {
    throw new TypeError(`unregistered ${source.profileId} UI easing`);
  }
  if (
    source.semanticChannels.provenance.join(':') !== 'hue:shape' ||
    source.semanticChannels.confirmation.join(':') !== 'hue:stroke' ||
    source.semanticChannels.focus.join(':') !== 'contrast:outline'
  ) {
    throw new TypeError(`protected semantic channels changed: ${source.profileId}`);
  }
}

/** Validate, derive semantic UI roles, and freeze one compiled profile. */
export function createWorldArtProfile(source: WorldArtProfileSource): WorldArtProfile {
  validateWorldArtProfileSource(source);
  const frozen = freezeSource(source);
  const colors = deriveWorldUiColors(frozen.palette, frozen.interfacePalette);
  return Object.freeze({
    ...frozen,
    ui: Object.freeze({ ...frozen.ui, colors }),
  });
}

/** Fresh mutable copy used only inside the trusted capability compiler. */
export function copyWorldArtProfileSource(source: WorldArtProfileSource): WorldArtProfileSource {
  return {
    ...source,
    geometry: { ...source.geometry },
    field: { ...source.field },
    material: { ...source.material },
    palette: { ...source.palette },
    ...(source.interfacePalette === undefined
      ? {}
      : { interfacePalette: { ...source.interfacePalette } }),
    semanticChannels: {
      provenance: [...source.semanticChannels.provenance],
      confirmation: [...source.semanticChannels.confirmation],
      focus: [...source.semanticChannels.focus],
    },
    ui: {
      typography: { ...source.ui.typography },
      material: { ...source.ui.material },
      texture: { ...source.ui.texture },
      motion: { ...source.ui.motion },
    },
  };
}

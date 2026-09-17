/**
 * Looks: versioned recipes over catalog entries, their deterministic draw, and the canonical
 * description a renderer builds from.
 *
 * A look never carries identity, position or simulation state. An inhabitant's default look is
 * a pure function of its stable id and a named draw domain, so a replay draws the same person the
 * same way. The draw uses exact integer arithmetic over a SHA-256 counter stream, which the
 * backend reproduces byte for byte (`exulanica.world.character_appearance.draw_look`).
 */
import {
  catalogBase,
  catalogFamily,
  catalogMaterial,
  type CatalogBase,
  type CatalogFamily,
  type CatalogPart,
  type CharacterCatalog,
  type TriangularRange,
} from './catalog.js';
import { canonicalJson, canonicalSha256, sha256 } from './digest.js';

export const CHARACTER_LOOK_PROFILE = 'exulanica.character-look/v1';
export const CHARACTER_DRAW_PROFILE = 'exulanica.character-draw/v1';
export const CHARACTER_RENDERABLE_PROFILE = 'exulanica.character-renderable/v1';

export interface CharacterLook {
  readonly profile: typeof CHARACTER_LOOK_PROFILE;
  readonly familyId: string;
  readonly baseId: string;
  /** Part slots name a part id, or null for an empty optional slot. */
  readonly parts: Readonly<Record<string, string | null>>;
  readonly materials: Readonly<Record<string, string>>;
  readonly colours: Readonly<Record<string, string>>;
  readonly parameters: Readonly<Record<string, number>>;
}

export type CharacterDetail = 'near' | 'far';

function fail(why: string): never {
  throw new TypeError(`Character look: ${why}`);
}

function exactKeys(record: Readonly<Record<string, unknown>>, expected: readonly string[], what: string): void {
  const keys = Object.keys(record).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((k, i) => k !== wanted[i])) fail(`${what} must be exactly ${wanted.join(', ')}`);
}

/** Validate a look against its family. Returns the resolved family and base. */
export function validateLook(catalog: CharacterCatalog, look: CharacterLook): { family: CatalogFamily; base: CatalogBase } {
  if (look.profile !== CHARACTER_LOOK_PROFILE) fail('unsupported profile');
  const family = catalogFamily(catalog, look.familyId);
  const base = catalogBase(family, look.baseId);
  const partSlots = family.slots.filter((s) => s.kind === 'part');
  const materialSlots = family.slots.filter((s) => s.kind === 'material');
  const colourSlots = family.slots.filter((s) => s.kind === 'colour');
  exactKeys(look.parts, partSlots.map((s) => s.slot), 'parts');
  exactKeys(look.materials, materialSlots.map((s) => s.slot), 'materials');
  exactKeys(look.colours, colourSlots.map((s) => s.slot), 'colours');
  exactKeys(look.parameters, family.parameters.map((p) => p.key), 'parameters');
  for (const slot of partSlots) {
    const id = look.parts[slot.slot];
    if (id === null) {
      if (!slot.optional) fail(`${slot.slot} is required`);
      continue;
    }
    if (!base.parts.some((p) => p.partId === id && p.slot === slot.slot)) fail(`${id} is not a ${slot.slot} on ${base.baseId}`);
  }
  for (const slot of materialSlots) {
    if (!(base.materials[slot.slot] ?? []).includes(look.materials[slot.slot]!)) fail(`${look.materials[slot.slot]} is not a ${slot.slot} on ${base.baseId}`);
  }
  for (const slot of colourSlots) {
    if (!(family.colours[slot.slot] ?? []).some((c) => c.key === look.colours[slot.slot])) fail(`${look.colours[slot.slot]} is not a ${slot.slot}`);
  }
  for (const parameter of family.parameters) {
    const value = look.parameters[parameter.key]!;
    const bounds = parameter.unit === 'mm' ? base.heightMillimetres : parameter;
    if (!Number.isSafeInteger(value) || value < bounds.min || value > bounds.max) fail(`${parameter.key} is outside ${bounds.min}..${bounds.max}`);
  }
  return { family, base };
}

export function lookSha256(look: CharacterLook): string {
  return canonicalSha256(look);
}

export const DESIGNED_LOOKS_PROFILE = 'exulanica.character-looks/v1';

/** Looks someone designed: starting points to choose from, and each body's default. */
export interface DesignedLooks {
  readonly profile: typeof DESIGNED_LOOKS_PROFILE;
  readonly catalogId: string;
  readonly defaults: { readonly player: string; readonly bases: Readonly<Record<string, string>> };
  readonly looks: readonly { readonly lookId: string; readonly label: string; readonly look: CharacterLook }[];
}

/** The same rules as `exulanica.world.character_appearance.designed_looks`. */
export function validateDesignedLooks(catalog: CharacterCatalog, looks: DesignedLooks): DesignedLooks {
  if (looks.profile !== DESIGNED_LOOKS_PROFILE || looks.catalogId !== catalog.catalogId) fail('designed looks name another catalog or profile');
  const ids = new Set<string>();
  for (const entry of looks.looks) {
    exactKeys(entry, ['lookId', 'label', 'look'], 'a designed look');
    if (ids.has(entry.lookId)) fail(`${entry.lookId} is designed twice`);
    ids.add(entry.lookId);
    validateLook(catalog, entry.look);
  }
  exactKeys(looks.defaults, ['player', 'bases'], 'designed defaults');
  for (const id of [looks.defaults.player, ...Object.values(looks.defaults.bases)]) {
    if (!ids.has(id)) fail(`designed default ${id} is not a designed look`);
  }
  const bases = catalog.families.flatMap((family) => family.bases.map((base) => base.baseId));
  exactKeys(looks.defaults.bases, bases, 'designed base defaults');
  for (const [baseId, id] of Object.entries(looks.defaults.bases)) {
    if (looks.looks.find((entry) => entry.lookId === id)!.look.baseId !== baseId) fail(`${baseId} default look is over another base`);
  }
  return looks;
}

export function designedLook(looks: DesignedLooks, lookId: string): CharacterLook {
  const entry = looks.looks.find((candidate) => candidate.lookId === lookId);
  if (!entry) throw new TypeError(`Unknown designed look ${lookId}`);
  return entry.look;
}

/** A reproducible stream of 32-bit integers from SHA-256 in counter mode. */
export class DrawStream {
  private readonly seed: Uint8Array;
  private block: Uint8Array = new Uint8Array(0);
  private offset = 0;
  private counter = 0;
  constructor(domain: string, subjectId: string) {
    this.seed = new TextEncoder().encode(canonicalJson({ domain, profile: CHARACTER_DRAW_PROFILE, subject: subjectId }));
  }
  next(): number {
    if (this.offset + 4 > this.block.length) {
      const input = new Uint8Array(this.seed.length + 4);
      input.set(this.seed);
      new DataView(input.buffer).setUint32(this.seed.length, this.counter++);
      this.block = sha256(input);
      this.offset = 0;
    }
    const value = new DataView(this.block.buffer, this.block.byteOffset + this.offset, 4).getUint32(0);
    this.offset += 4;
    return value;
  }
  /** An integer in [0, bound), exact: floor(u32 * bound / 2^32). */
  below(bound: number): number {
    if (!Number.isSafeInteger(bound) || bound < 1 || bound > 0x200000) throw new RangeError('draw bound out of range');
    return Math.floor((this.next() * bound) / 0x100000000);
  }
  /** A weighted key; keys iterate in sorted order so object insertion order never matters. */
  weighted(weights: Readonly<Record<string, number>>): string {
    const keys = Object.keys(weights).sort();
    const total = keys.reduce((sum, key) => sum + weights[key]!, 0);
    let pick = this.below(total);
    for (const key of keys) {
      pick -= weights[key]!;
      if (pick < 0) return key;
    }
    throw new Error('unreachable weighted draw');
  }
  /** Triangular integer draw by exact inverse CDF. */
  triangular(range: TriangularRange): number {
    const span = range.max - range.min;
    if (span === 0) return range.min;
    const left = range.mode - range.min;
    const right = range.max - range.mode;
    const u = this.next();
    if (span > 0x100000 || span * left > 0x1fffff || span * right > 0x1fffff) throw new RangeError('triangular range too wide');
    if (u * span < left * 0x100000000) {
      return range.min + isqrt(Math.floor((u * span * left) / 0x100000000));
    }
    return range.max - isqrt(Math.floor(((0x100000000 - 1 - u) * span * right) / 0x100000000));
  }
}

export function isqrt(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) throw new RangeError('isqrt needs a non-negative safe integer');
  let root = Math.floor(Math.sqrt(value));
  while (root * root > value) root -= 1;
  while ((root + 1) * (root + 1) <= value) root += 1;
  return root;
}

/** The default look of a subject in a named draw domain. */
export function drawLook(catalog: CharacterCatalog, domain: string, subjectId: string): CharacterLook {
  const profile = catalog.population.find((p) => p.domain === domain);
  if (!profile) throw new TypeError(`Unknown character draw domain ${domain}`);
  const family = catalogFamily(catalog, profile.familyId);
  const stream = new DrawStream(domain, subjectId);
  const baseId = stream.weighted(profile.bases);
  const base = catalogBase(family, baseId);
  const choices = profile.choices[baseId]!;
  const parts: Record<string, string | null> = {};
  const materials: Record<string, string> = {};
  const colours: Record<string, string> = {};
  const parameters: Record<string, number> = {};
  for (const slot of family.slots) {
    if (slot.kind === 'part') {
      const id = stream.weighted(choices[slot.slot]!);
      parts[slot.slot] = id === 'none' ? null : id;
    } else if (slot.kind === 'material') {
      materials[slot.slot] = stream.weighted(choices[slot.slot]!);
    } else {
      colours[slot.slot] = stream.weighted(profile.colours[slot.slot]!);
    }
  }
  for (const parameter of family.parameters) {
    parameters[parameter.key] = stream.triangular(profile.parameters[baseId]![parameter.key]!);
  }
  const look: CharacterLook = { profile: CHARACTER_LOOK_PROFILE, familyId: family.familyId, baseId: base.baseId, parts, materials, colours, parameters };
  validateLook(catalog, look);
  return look;
}

export interface RenderablePart {
  readonly slot: string;
  readonly partId: string;
  readonly node: string;
  readonly asset: CatalogPart['asset'] | null;
  readonly materialId: string;
  readonly tint: string | null;
}

export interface CharacterRenderableDescription {
  readonly profile: typeof CHARACTER_RENDERABLE_PROFILE;
  readonly detail: CharacterDetail;
  readonly familyId: string;
  readonly baseId: string;
  readonly base: CatalogBase['asset'] | null;
  readonly heightMillimetres: number;
  /** Uniform model scale relative to the base's rest height, in millionths. */
  readonly scaleMicro: number;
  readonly skinMaterial: string;
  readonly parts: readonly RenderablePart[];
  readonly hideMask: number;
  readonly morphWeightsMilli: Readonly<Record<string, number>>;
  readonly farColours: { readonly skin: string; readonly hair: string | null; readonly upper: string; readonly lower: string; readonly shoes: string };
  readonly lookSha256: string;
}

function tintFor(family: CatalogFamily, look: CharacterLook, part: CatalogPart): string | null {
  const slot = family.slots.find((s) => s.kind === 'colour' && s.appliesTo === part.slot);
  if (!slot || !part.tint) return null;
  const key = look.colours[slot.slot];
  return (family.colours[slot.slot] ?? []).find((c) => c.key === key)?.rgb ?? null;
}

export function heightParameter(family: CatalogFamily): string {
  return family.parameters.find((p) => p.unit === 'mm')!.key;
}

function multiply(a: string, b: string): string {
  const channel = (text: string, i: number) => Number.parseInt(text.slice(1 + i * 2, 3 + i * 2), 16);
  return `#${[0, 1, 2].map((i) => Math.round((channel(a, i) * channel(b, i)) / 255).toString(16).padStart(2, '0')).join('')}`;
}

/**
 * The canonical renderable description of a look at a detail level. Equal looks give equal bytes.
 * 'far' names no part assets: it keeps silhouette, palette and height only.
 */
export function describeLook(catalog: CharacterCatalog, look: CharacterLook, detail: CharacterDetail): CharacterRenderableDescription {
  const { family, base } = validateLook(catalog, look);
  const parts: RenderablePart[] = [];
  let hideMask = 0;
  for (const slot of family.slots.filter((s) => s.kind === 'part')) {
    const id = look.parts[slot.slot];
    if (!id) continue;
    const part = base.parts.find((p) => p.partId === id)!;
    if (part.hideBit !== undefined) hideMask |= 1 << part.hideBit;
    // A material slot applying to this part replaces the part's authored default.
    const materialSlot = family.slots.find((s) => s.kind === 'material' && s.appliesTo === slot.slot);
    const override = materialSlot ? look.materials[materialSlot.slot] : undefined;
    parts.push({
      slot: slot.slot,
      partId: part.partId,
      node: part.node,
      asset: detail === 'near' ? part.asset ?? null : null,
      materialId: override ?? part.material,
      tint: tintFor(family, look, part),
    });
  }
  parts.sort((a, b) => (a.slot < b.slot ? -1 : a.slot > b.slot ? 1 : 0));
  const morphWeightsMilli: Record<string, number> = {};
  for (const parameter of family.parameters) {
    if (!parameter.negative && !parameter.positive) continue;
    const value = look.parameters[parameter.key]!;
    if (parameter.negative) morphWeightsMilli[parameter.negative] = value < 0 ? -value : 0;
    if (parameter.positive) morphWeightsMilli[parameter.positive] = value > 0 ? value : 0;
  }
  const height = look.parameters[heightParameter(family)]!;
  const skinSlot = family.slots.find((s) => s.kind === 'material' && s.appliesTo === 'body');
  if (!skinSlot) throw new TypeError(`${family.familyId} declares no body material slot`);
  const skin = look.materials[skinSlot.slot]!;
  const partColours = (slot: string) => {
    const part = parts.find((p) => p.slot === slot);
    if (!part) return null;
    const colours = base.parts.find((p) => p.partId === part.partId)!.farColours;
    return part.tint ? { upper: multiply(colours.upper, part.tint), lower: multiply(colours.lower, part.tint) } : colours;
  };
  const skinColour = catalogMaterial(family, skin).averageColour;
  const outfit = partColours('outfit');
  const shoes = partColours('shoes');
  const hair = partColours('hair');
  const description = {
    profile: CHARACTER_RENDERABLE_PROFILE,
    detail,
    familyId: family.familyId,
    baseId: base.baseId,
    base: detail === 'near' ? base.asset : null,
    heightMillimetres: height,
    scaleMicro: Math.round((height * 1_000_000) / base.restHeightMillimetres),
    skinMaterial: skin,
    parts,
    hideMask,
    morphWeightsMilli,
    farColours: {
      skin: skinColour,
      hair: hair?.upper ?? null,
      upper: outfit?.upper ?? skinColour,
      lower: outfit?.lower ?? skinColour,
      shoes: shoes?.lower ?? skinColour,
    },
    lookSha256: lookSha256(look),
  } satisfies CharacterRenderableDescription;
  return description;
}

export function describeLookBytes(catalog: CharacterCatalog, look: CharacterLook, detail: CharacterDetail): string {
  return canonicalJson(describeLook(catalog, look, detail));
}

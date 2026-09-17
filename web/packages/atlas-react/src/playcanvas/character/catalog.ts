/**
 * The character catalog: every body, garment, hairstyle and material a look may name.
 *
 * A catalog is data. Families declare their slots, parameters and colour slots; adding a
 * garment or a hairstyle adds an entry and never a code path. Every asset entry carries its
 * pinned bytes, licence and source so a renderer can refuse anything it cannot verify.
 */

export const CHARACTER_CATALOG_PROFILE = 'exulanica.character-catalog/v1';

export interface CatalogAssetRef {
  readonly assetKey: string;
  readonly mediaType: 'model/gltf-binary';
  readonly contentSha256: string;
  readonly byteSize: number;
  /** Repository path relative to `assets/characters/`, for development delivery and review. */
  readonly file: string;
}

export interface CatalogSource {
  readonly title: string;
  readonly url: string;
  readonly revision: string;
  /** Path inside the pinned source tree, when an entry came from one file there. */
  readonly path?: string;
}

export interface CatalogLicence {
  readonly id: 'CC0-1.0';
  readonly file: string;
  readonly sha256: string;
}

export interface CatalogClip {
  readonly name: string;
  readonly durationMilli: number;
  /** Ground speed of the clip's planted feet at the base's rest height, 0 for in-place clips. */
  readonly speedMillimetresPerSecond: number;
}

export type CatalogSlotKind = 'part' | 'material' | 'colour';

export interface CatalogSlot {
  readonly slot: string;
  readonly label: string;
  readonly kind: CatalogSlotKind;
  readonly optional: boolean;
  /** For material and colour slots: the part slot they apply to, or `body` for the skin. */
  readonly appliesTo?: string;
}

export interface CatalogParameter {
  readonly key: string;
  readonly label: string;
  /** `mm` is standing height, bounded per base; `milli` values are morph weights in thousandths. */
  readonly unit: 'mm' | 'milli';
  readonly min: number;
  readonly max: number;
  /** Morph targets driven by this parameter: negative values weight `negative`, positive `positive`. */
  readonly negative?: string;
  readonly positive?: string;
}

export interface CatalogPart {
  readonly partId: string;
  readonly slot: string;
  readonly label: string;
  /** Node name in the base or wearable container. */
  readonly node: string;
  /** Absent for parts carried inside the base container (face parts). */
  readonly asset?: CatalogAssetRef;
  /** Bit in the base body's `_HIDE` attribute for body surface this part covers. */
  readonly hideBit?: number;
  readonly material: string;
  readonly tint?: 'hair';
  readonly morphTargets: readonly string[];
  readonly triangles: number;
  /** Simplified colours for distant forms: `upper` and `lower` split at the hips. */
  readonly farColours: { readonly upper: string; readonly lower: string };
  readonly source: CatalogSource;
}

export interface CatalogBase {
  readonly baseId: string;
  readonly label: string;
  readonly asset: CatalogAssetRef;
  readonly restHeightMillimetres: number;
  /** Signed ground offset of the idle's first frame, micrometres. */
  readonly idleFloorMicrometres: number;
  readonly heightMillimetres: { readonly min: number; readonly max: number; readonly default: number };
  readonly eyeHeightMillimetres: number;
  readonly clips: Readonly<Record<'idle' | 'walk' | 'run' | 'interact' | 'wave', CatalogClip>>;
  readonly morphTargets: readonly string[];
  readonly bodyNode: string;
  readonly bodyTriangles: number;
  readonly parts: readonly CatalogPart[];
  /** Materials each material slot may use on this base. */
  readonly materials: Readonly<Record<string, readonly string[]>>;
  readonly source: CatalogSource;
}

export interface CatalogMaterial {
  readonly materialId: string;
  readonly label: string;
  readonly kind: 'skin' | 'eyes' | 'eyebrows' | 'eyelashes' | 'hair' | 'outfit' | 'shoes';
  readonly asset: CatalogAssetRef;
  readonly roles: { readonly baseColor: number; readonly normal?: number; readonly opacity?: number };
  readonly alphaMode: 'OPAQUE' | 'MASK';
  readonly alphaCutoffMilli?: number;
  readonly doubleSided: boolean;
  readonly roughnessMilli: number;
  readonly tint?: 'normalised';
  readonly averageColour: string;
  readonly source: CatalogSource;
}

export interface CatalogColour {
  readonly key: string;
  readonly label: string;
  readonly rgb: string;
}

export interface CatalogFamily {
  readonly familyId: string;
  readonly label: string;
  readonly summary: string;
  readonly kind: 'layered-people';
  readonly rigId: string;
  readonly joints: readonly string[];
  readonly licence: CatalogLicence;
  readonly slots: readonly CatalogSlot[];
  readonly parameters: readonly CatalogParameter[];
  readonly colours: Readonly<Record<string, readonly CatalogColour[]>>;
  readonly bases: readonly CatalogBase[];
  readonly materials: readonly CatalogMaterial[];
}

/** Weighted choices for a named draw domain. Weights are positive integers. */
export interface PopulationProfile {
  readonly domain: string;
  readonly familyId: string;
  readonly bases: Readonly<Record<string, number>>;
  /** Per base, per slot, weights over part or material ids; `none` names an empty optional slot. */
  readonly choices: Readonly<Record<string, Readonly<Record<string, Readonly<Record<string, number>>>>>>;
  readonly colours: Readonly<Record<string, Readonly<Record<string, number>>>>;
  /** Per base, per parameter, a triangular integer distribution. */
  readonly parameters: Readonly<Record<string, Readonly<Record<string, TriangularRange>>>>;
}

export interface TriangularRange {
  readonly min: number;
  readonly mode: number;
  readonly max: number;
}

export interface CharacterCatalog {
  readonly profile: typeof CHARACTER_CATALOG_PROFILE;
  readonly catalogId: string;
  readonly revision: number;
  readonly families: readonly CatalogFamily[];
  readonly population: readonly PopulationProfile[];
}

const HEX = /^#[0-9a-f]{6}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const KEY = /^[a-z0-9][a-z0-9._:/-]{0,199}$/;

function fail(path: string, why: string): never {
  throw new TypeError(`Character catalog ${path}: ${why}`);
}

function checkAsset(asset: CatalogAssetRef, path: string): void {
  if (asset.mediaType !== 'model/gltf-binary') fail(path, 'only GLB containers are admitted');
  if (!KEY.test(asset.assetKey)) fail(path, 'asset key is malformed');
  if (!DIGEST.test(asset.contentSha256)) fail(path, 'digest is malformed');
  if (!Number.isSafeInteger(asset.byteSize) || asset.byteSize <= 0 || asset.byteSize > 32 * 1024 * 1024) fail(path, 'byte size is out of range');
  if (!/^[a-z0-9][a-z0-9._/-]*\.glb$/.test(asset.file) || asset.file.includes('..')) fail(path, 'file path is malformed');
}

function unique<T>(values: readonly T[], path: string): void {
  if (new Set(values).size !== values.length) fail(path, 'identifiers must be unique');
}

/** Structural and referential validation. Throws on the first inconsistency. */
export function validateCharacterCatalog(catalog: CharacterCatalog): CharacterCatalog {
  if (catalog.profile !== CHARACTER_CATALOG_PROFILE) fail('profile', 'unsupported profile');
  if (!Number.isSafeInteger(catalog.revision) || catalog.revision < 1) fail('revision', 'must be a positive integer');
  unique(catalog.families.map((f) => f.familyId), 'families');
  const assetKeys: string[] = [];
  for (const family of catalog.families) {
    const at = `family ${family.familyId}`;
    if (family.kind !== 'layered-people') fail(at, 'unknown family kind');
    unique(family.slots.map((s) => s.slot), `${at} slots`);
    unique(family.parameters.map((p) => p.key), `${at} parameters`);
    const materials = new Map(family.materials.map((m) => [m.materialId, m]));
    unique(family.materials.map((m) => m.materialId), `${at} materials`);
    for (const material of family.materials) {
      checkAsset(material.asset, `${at} material ${material.materialId}`);
      assetKeys.push(material.asset.assetKey);
      if (!HEX.test(material.averageColour)) fail(`${at} material ${material.materialId}`, 'average colour is malformed');
    }
    for (const [slot, colours] of Object.entries(family.colours)) {
      if (!family.slots.some((s) => s.slot === slot && s.kind === 'colour')) fail(`${at} colours`, `${slot} is not a colour slot`);
      unique(colours.map((c) => c.key), `${at} colours ${slot}`);
      for (const colour of colours) if (!HEX.test(colour.rgb)) fail(`${at} colours ${slot}`, `${colour.key} is malformed`);
    }
    for (const parameter of family.parameters) {
      if (!Number.isSafeInteger(parameter.min) || !Number.isSafeInteger(parameter.max) || parameter.min > parameter.max) fail(`${at} parameter ${parameter.key}`, 'range is malformed');
      if (parameter.unit === 'milli' && (parameter.min < -1000 || parameter.max > 1000)) fail(`${at} parameter ${parameter.key}`, 'morph weights stay within one full target');
    }
    if (family.parameters.filter((p) => p.unit === 'mm').length !== 1) fail(at, 'exactly one height parameter is required');
    for (const slot of family.slots) {
      if (slot.kind === 'part' && slot.appliesTo !== undefined) fail(`${at} slot ${slot.slot}`, 'part slots apply to themselves');
      if (slot.kind !== 'part' && slot.appliesTo !== 'body' && !family.slots.some((s) => s.kind === 'part' && s.slot === slot.appliesTo)) fail(`${at} slot ${slot.slot}`, 'must apply to a part slot or the body');
    }
    unique(family.bases.map((b) => b.baseId), `${at} bases`);
    for (const base of family.bases) {
      const where = `${at} base ${base.baseId}`;
      checkAsset(base.asset, where);
      assetKeys.push(base.asset.assetKey);
      const { min, max, default: fallback } = base.heightMillimetres;
      if (!(min <= fallback && fallback <= max)) fail(where, 'height default is outside its range');
      unique(base.parts.map((p) => p.partId), `${where} parts`);
      const bits = base.parts.flatMap((p) => (p.hideBit === undefined ? [] : [p.hideBit]));
      unique(bits, `${where} hide bits`);
      for (const part of base.parts) {
        const partAt = `${where} part ${part.partId}`;
        if (!family.slots.some((s) => s.slot === part.slot && s.kind === 'part')) fail(partAt, `unknown part slot ${part.slot}`);
        if (part.asset) {
          checkAsset(part.asset, partAt);
          assetKeys.push(part.asset.assetKey);
        }
        if (part.hideBit !== undefined && !(Number.isInteger(part.hideBit) && part.hideBit >= 0 && part.hideBit < 16)) fail(partAt, 'hide bit is out of range');
        if (!materials.has(part.material)) fail(partAt, `unknown material ${part.material}`);
        if (!HEX.test(part.farColours.upper) || !HEX.test(part.farColours.lower)) fail(partAt, 'far colours are malformed');
        for (const target of part.morphTargets) if (!base.morphTargets.includes(target)) fail(partAt, `unknown morph target ${target}`);
      }
      for (const [slot, ids] of Object.entries(base.materials)) {
        if (!family.slots.some((s) => s.slot === slot && s.kind === 'material')) fail(where, `${slot} is not a material slot`);
        for (const id of ids) if (!materials.has(id)) fail(where, `unknown material ${id}`);
      }
      for (const slot of family.slots) {
        if (slot.kind === 'part' && !slot.optional && !base.parts.some((p) => p.slot === slot.slot)) fail(where, `required slot ${slot.slot} has no part`);
        if (slot.kind === 'material' && !(base.materials[slot.slot]?.length)) fail(where, `material slot ${slot.slot} has no choice`);
      }
    }
  }
  unique(assetKeys, 'asset keys');
  for (const profile of catalog.population) {
    const family = catalog.families.find((f) => f.familyId === profile.familyId);
    if (!family) fail(`population ${profile.domain}`, 'unknown family');
    for (const [baseId, weight] of Object.entries(profile.bases)) {
      const base = family.bases.find((b) => b.baseId === baseId);
      if (!base || !(Number.isSafeInteger(weight) && weight > 0)) fail(`population ${profile.domain}`, `bad base weight ${baseId}`);
      const choices = profile.choices[baseId] ?? {};
      for (const slot of family.slots) {
        if (slot.kind === 'colour') continue;
        const options = choices[slot.slot];
        if (!options || !Object.keys(options).length) fail(`population ${profile.domain}`, `${baseId} has no ${slot.slot} choices`);
        for (const [id, w] of Object.entries(options)) {
          if (!(Number.isSafeInteger(w) && w > 0)) fail(`population ${profile.domain}`, `${id} weight must be a positive integer`);
          const known = slot.kind === 'part'
            ? base.parts.some((p) => p.partId === id && p.slot === slot.slot) || (id === 'none' && slot.optional)
            : (base.materials[slot.slot] ?? []).includes(id);
          if (!known) fail(`population ${profile.domain}`, `${id} is not a ${slot.slot} choice on ${baseId}`);
        }
      }
      for (const parameter of family.parameters) {
        const range = profile.parameters[baseId]?.[parameter.key];
        if (!range) fail(`population ${profile.domain}`, `${baseId} has no ${parameter.key} distribution`);
        const { min: low, mode, max: high } = range;
        const bounds = parameter.unit === 'mm' ? base.heightMillimetres : parameter;
        if (![low, mode, high].every(Number.isSafeInteger) || !(bounds.min <= low && low <= mode && mode <= high && high <= bounds.max)) {
          fail(`population ${profile.domain}`, `${baseId} ${parameter.key} distribution is outside its range`);
        }
      }
    }
    for (const [slot, weights] of Object.entries(profile.colours)) {
      const palette = family.colours[slot];
      if (!palette) fail(`population ${profile.domain}`, `unknown colour slot ${slot}`);
      for (const [key, w] of Object.entries(weights)) {
        if (!palette.some((c) => c.key === key) || !(Number.isSafeInteger(w) && w > 0)) fail(`population ${profile.domain}`, `bad ${slot} colour weight ${key}`);
      }
    }
  }
  return catalog;
}

export function catalogFamily(catalog: CharacterCatalog, familyId: string): CatalogFamily {
  const family = catalog.families.find((f) => f.familyId === familyId);
  if (!family) throw new TypeError(`Unknown character family ${familyId}`);
  return family;
}

export function catalogBase(family: CatalogFamily, baseId: string): CatalogBase {
  const base = family.bases.find((b) => b.baseId === baseId);
  if (!base) throw new TypeError(`Unknown ${family.familyId} base ${baseId}`);
  return base;
}

export function catalogMaterial(family: CatalogFamily, materialId: string): CatalogMaterial {
  const material = family.materials.find((m) => m.materialId === materialId);
  if (!material) throw new TypeError(`Unknown ${family.familyId} material ${materialId}`);
  return material;
}

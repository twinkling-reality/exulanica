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

/** The studio steps a choice is offered on. */
export const STUDIO_SECTIONS = ['body', 'face', 'style'] as const;
export type StudioSection = (typeof STUDIO_SECTIONS)[number];

/** How the studio offers a slot or parameter: where, in what order, and in what words. */
export interface StudioPresentation {
  readonly section: StudioSection;
  readonly order: number;
  /** Swatches show each choice's colour; otherwise choices are named. */
  readonly display?: 'swatch';
  /** Slider step, in the parameter's own unit. */
  readonly step?: number;
  /** Words for a signed morph weight below, at and above zero. */
  readonly wording?: { readonly negative: string; readonly neutral: string; readonly positive: string };
}

export interface CatalogSlot extends StudioPresentation {
  readonly slot: string;
  readonly label: string;
  readonly kind: CatalogSlotKind;
  readonly optional: boolean;
  /** For material and colour slots: the part slot they apply to, or `body` for the skin. */
  readonly appliesTo?: string;
}

export interface CatalogParameter extends StudioPresentation {
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

/** Joints a posture's far form follows, measured on the baked clip. */
export const POSTURE_JOINTS = [
  'pelvis', 'chest', 'neck', 'head',
  'leftHip', 'leftKnee', 'leftAnkle', 'leftToe', 'leftShoulder', 'leftElbow', 'leftWrist',
  'rightHip', 'rightKnee', 'rightAnkle', 'rightToe', 'rightShoulder', 'rightElbow', 'rightWrist',
] as const;
export type PostureJoint = (typeof POSTURE_JOINTS)[number];

/** A posture on one base: its clip, and where its joints are at the clip's first frame. */
export interface CatalogBasePosture {
  readonly clip: CatalogClip;
  /**
   * How high the lowest point of the seat rests above the ground a standing person stands on, at
   * the base's rest height and the clip's first frame. A posture drawn on a seat puts this point
   * on it; one drawn on the ground rests it a little into the ground.
   */
  readonly seatMillimetres: number;
  /** Millimetres in the asset's own frame: +Y up, the body facing +Z. */
  readonly jointsMillimetres: Readonly<Record<PostureJoint, readonly [number, number, number]>>;
}

/** The fitted body's widths at rest, measured by the preparation, which the far form is built to. */
export interface CatalogFarForm {
  readonly shoulderWidthMillimetres: number;
  readonly hipWidthMillimetres: number;
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
  readonly farForm: CatalogFarForm;
  /** Every posture the family declares, fitted to this base. */
  readonly postures: Readonly<Record<string, CatalogBasePosture>>;
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
  /** Every mesh drawn with this material carries its baked ambient occlusion as vertex colour. */
  readonly vertexOcclusion?: true;
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
  /** Postures besides standing and moving, each baked on every base. */
  readonly postures: readonly { readonly key: string; readonly label: string }[];
  /**
   * How an activity the simulation states is drawn: activity key to posture key. An activity
   * named nowhere here is drawn standing.
   */
  readonly activityPostures: Readonly<Record<string, string>>;
  /**
   * How an activity performed on a seat is drawn: activity key to posture key. A person drawn at a
   * seat takes this posture; an activity named nowhere here, or a person at no seat, is drawn by
   * `activityPostures`.
   */
  readonly seatPostures: Readonly<Record<string, string>>;
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

function checkPresentation(shown: StudioPresentation, path: string): void {
  if (!STUDIO_SECTIONS.includes(shown.section)) fail(path, 'studio section is unknown');
  if (!Number.isSafeInteger(shown.order)) fail(path, 'studio order must be an integer');
  if (shown.step !== undefined && !(Number.isSafeInteger(shown.step) && shown.step > 0)) fail(path, 'studio step must be a positive integer');
  if (shown.display !== undefined && shown.display !== 'swatch') fail(path, 'studio display is unknown');
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
    for (const shown of [...family.slots.map((s) => ({ key: s.slot, ...s })), ...family.parameters]) checkPresentation(shown, `${at} ${shown.key}`);
    unique(family.postures.map((p) => p.key), `${at} postures`);
    for (const posture of family.postures) if (!KEY.test(posture.key)) fail(`${at} posture ${posture.key}`, 'key is malformed');
    for (const [activity, posture] of [...Object.entries(family.activityPostures), ...Object.entries(family.seatPostures)]) {
      if (!KEY.test(activity)) fail(`${at} activity ${activity}`, 'key is malformed');
      if (!family.postures.some((p) => p.key === posture)) fail(`${at} activity ${activity}`, `unknown posture ${posture}`);
    }
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
      for (const width of [base.farForm.shoulderWidthMillimetres, base.farForm.hipWidthMillimetres]) {
        if (!Number.isSafeInteger(width) || width <= 0 || width > base.restHeightMillimetres) fail(where, 'far form widths are malformed');
      }
      const postureKeys = Object.keys(base.postures).sort();
      const declared = family.postures.map((p) => p.key).sort();
      if (postureKeys.length !== declared.length || postureKeys.some((k, i) => k !== declared[i])) fail(where, 'postures must be exactly the family\'s');
      for (const [key, posture] of Object.entries(base.postures)) {
        if (!Number.isSafeInteger(posture.clip.durationMilli) || posture.clip.durationMilli <= 0 || posture.clip.speedMillimetresPerSecond !== 0) fail(`${where} posture ${key}`, 'clip is malformed');
        if (!Number.isSafeInteger(posture.seatMillimetres) || Math.abs(posture.seatMillimetres) > base.restHeightMillimetres) fail(`${where} posture ${key}`, 'seat height is malformed');
        for (const joint of POSTURE_JOINTS) {
          const point = posture.jointsMillimetres[joint];
          if (!point || point.length !== 3 || !point.every(Number.isSafeInteger)) fail(`${where} posture ${key}`, `joint ${joint} is malformed`);
        }
      }
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

/**
 * The posture an activity is drawn in, or null for standing. `seated` says the person is drawn at a
 * seat, where the family's seat posture for the activity is taken when it declares one.
 */
export function activityPosture(family: CatalogFamily, activity: string | null | undefined, seated = false): string | null {
  if (!activity) return null;
  return (seated ? family.seatPostures[activity] : undefined) ?? family.activityPostures[activity] ?? null;
}

/** The posture an activity performed on a seat is drawn in, or null where none is declared. */
export function seatPosture(family: CatalogFamily, activity: string | null | undefined): string | null {
  return activity ? family.seatPostures[activity] ?? null : null;
}

export function catalogMaterial(family: CatalogFamily, materialId: string): CatalogMaterial {
  const material = family.materials.find((m) => m.materialId === materialId);
  if (!material) throw new TypeError(`Unknown ${family.familyId} material ${materialId}`);
  return material;
}

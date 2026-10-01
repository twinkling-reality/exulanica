/**
 * Parametric body catalogs, as the host publishes them: declared controls, and bodies prepared per
 * recipe that the native character runtime draws.
 *
 * The document mirrors `exulanica.world.character_parametric` and is checked here with the same
 * rules before anything reads it. Every number is an integer in its field's unit: controls in
 * whole centimetres or thousandths of the builder's own value, a body's frame in millionths of the
 * asset's unit, clip speeds in millimetres per second. A body is drawn only with the descriptor its
 * publication or its preparation receipt measured from its bytes, never one guessed from the
 * recipe.
 */
import type { AuthoredObjectAssetReference } from '../scene-objects.js';
import type { NativeCharacterDescriptor } from '../native-character.js';

export const PARAMETRIC_CATALOG_PROFILE = 'exulanica.parametric-character-catalog/v1';

export interface ParametricControl {
  readonly key: string;
  readonly label: string;
  readonly group: string;
  /** `cm` for whole centimetres, `milli` for thousandths of the builder's control value. */
  readonly unit: 'cm' | 'milli';
  readonly min: number;
  readonly max: number;
  readonly default: number;
  readonly step: number;
  readonly lowLabel?: string | null;
  readonly highLabel?: string | null;
}

export interface ParametricChoice {
  readonly key: string;
  readonly label: string;
  readonly default: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
}

export interface ParametricClip {
  readonly name: string;
  readonly speedMillimetresPerSecond: number;
}

/** How the renderer frames one prepared body, measured from its bytes. */
export interface ParametricDescriptor {
  readonly unitScaleMillionths: number;
  readonly nativeStandingHeightMillionths: number;
  readonly nativeGroundOffsetMillionths: number;
  readonly forwardYawDegrees: number;
  readonly clips: Readonly<Record<'idle' | 'walk' | 'run', ParametricClip>>;
  readonly materialSlots: Readonly<Record<string, readonly string[]>>;
}

export interface ParametricRepresentation {
  readonly representationId: string;
  readonly values: Readonly<Record<string, number | string>>;
  readonly recipeInputSha256: string;
  readonly asset: {
    readonly assetKey: string;
    readonly mediaType: 'model/gltf-binary';
    readonly contentSha256: string;
    readonly byteSize: number;
    readonly file: string;
  };
  readonly importReceiptSha256: string;
  readonly preparationReceiptSha256: string;
  readonly descriptor: ParametricDescriptor;
  readonly measurements: Readonly<Record<string, number>>;
}

export interface ParametricFamily {
  readonly familyId: string;
  readonly kind: 'parametric-body';
  readonly label: string;
  readonly licence: { readonly id: 'CC0-1.0'; readonly file: string; readonly sha256: string };
  readonly sources: readonly { readonly title: string; readonly url: string; readonly revision: string }[];
  readonly permittedUses: readonly 'authored-avatar'[];
  readonly controls: readonly ParametricControl[];
  readonly choices: readonly ParametricChoice[];
  readonly presets: readonly { readonly label: string; readonly values: Readonly<Record<string, number | string>> }[];
  readonly rig: { readonly rigId: string; readonly joints: readonly string[]; readonly hips: string; readonly feet: readonly [string, string] };
  readonly clips: Readonly<Record<'idle' | 'walk' | 'run', string>>;
  readonly colourSlots: Readonly<Record<string, string>>;
  readonly preparation: { readonly preparerId: string; readonly preparerVersion: number; readonly sourceLockSha256: string };
  readonly budget: Readonly<Record<string, number>>;
  readonly representations: readonly ParametricRepresentation[];
}

export interface ParametricCatalog {
  readonly profile: typeof PARAMETRIC_CATALOG_PROFILE;
  readonly catalogId: string;
  readonly revision: number;
  readonly families: readonly ParametricFamily[];
}

const DIGEST = /^[0-9a-f]{64}$/;
const HEX = /^#[0-9a-f]{6}$/;

function fail(path: string, why: string): never {
  throw new TypeError(`Parametric catalog ${path}: ${why}`);
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

/** Structural checks matching the backend's models. Throws on the first inconsistency. */
export function validateParametricCatalog(catalog: ParametricCatalog): ParametricCatalog {
  if (catalog.profile !== PARAMETRIC_CATALOG_PROFILE) fail('profile', 'unsupported profile');
  if (!integer(catalog.revision) || catalog.revision < 1) fail('revision', 'must be a positive integer');
  const families: readonly ParametricFamily[] = catalog.families ?? [];
  if (families.length === 0) fail('families', 'at least one family');
  const ids = new Set<string>();
  for (const family of families) {
    const at = `family ${family.familyId}`;
    if (family.kind !== 'parametric-body' || ids.has(family.familyId)) fail(at, 'unknown kind or repeated id');
    ids.add(family.familyId);
    if (!family.permittedUses.every((use) => use === 'authored-avatar')) fail(at, 'a parametric body is for the authored avatar only');
    const keys = new Set<string>();
    for (const control of family.controls) {
      if (keys.has(control.key)) fail(at, `control ${control.key} repeated`);
      keys.add(control.key);
      if (![control.min, control.max, control.default, control.step].every(integer) || control.step <= 0) fail(at, `control ${control.key} is not integral`);
      if (!(control.min <= control.default && control.default <= control.max)) fail(at, `control ${control.key} default is outside its range`);
    }
    for (const choice of family.choices) {
      if (keys.has(choice.key)) fail(at, `choice ${choice.key} repeated`);
      keys.add(choice.key);
      if (!choice.options.some((option) => option.value === choice.default)) fail(at, `choice ${choice.key} default is not an option`);
    }
    if (!family.rig.joints.includes(family.rig.hips) || !family.rig.feet.every((foot) => family.rig.joints.includes(foot))) fail(at, 'calibration joints are not rig joints');
    for (const colour of Object.values(family.colourSlots)) if (!HEX.test(colour)) fail(at, 'a colour slot is malformed');
    if (!DIGEST.test(family.licence.sha256) || !DIGEST.test(family.preparation.sourceLockSha256)) fail(at, 'a pinned digest is malformed');
    for (const representation of family.representations) checkRepresentation(family, representation, at);
  }
  return catalog;
}

function checkRepresentation(family: ParametricFamily, representation: ParametricRepresentation, at: string): void {
  const where = `${at} representation ${representation.representationId}`;
  if (!DIGEST.test(representation.recipeInputSha256) || !DIGEST.test(representation.asset.contentSha256)) fail(where, 'a digest is malformed');
  if (!integer(representation.asset.byteSize) || representation.asset.byteSize <= 0 || representation.asset.byteSize > 32 * 1024 * 1024) fail(where, 'byte size is out of range');
  validateParametricValues(family, representation.values);
  checkDescriptor(representation.descriptor, where);
}

function checkDescriptor(descriptor: ParametricDescriptor, where: string): void {
  if (![descriptor.unitScaleMillionths, descriptor.nativeStandingHeightMillionths, descriptor.nativeGroundOffsetMillionths, descriptor.forwardYawDegrees].every(integer)) fail(where, 'the frame is not integral');
  if (descriptor.unitScaleMillionths <= 0 || descriptor.nativeStandingHeightMillionths <= 0) fail(where, 'the frame is not positive');
  for (const role of ['idle', 'walk', 'run'] as const) {
    const clip = descriptor.clips[role];
    if (!clip || !integer(clip.speedMillimetresPerSecond) || (role === 'idle' ? clip.speedMillimetresPerSecond !== 0 : clip.speedMillimetresPerSecond <= 0)) fail(where, `${role} clip is malformed`);
  }
}

/** Refuse values that are not exactly the family's controls and choices, each inside its declaration. */
export function validateParametricValues(family: ParametricFamily, values: Readonly<Record<string, number | string>>): void {
  const expected = [...family.controls.map((c) => c.key), ...family.choices.map((c) => c.key)].sort();
  const given = Object.keys(values).sort();
  if (expected.length !== given.length || expected.some((key, i) => key !== given[i])) fail(family.familyId, 'values name exactly the family controls and choices');
  for (const control of family.controls) {
    const value = values[control.key];
    if (!integer(value) || value < control.min || value > control.max) fail(family.familyId, `${control.key} is outside ${control.min}..${control.max}`);
  }
  for (const choice of family.choices) {
    if (!choice.options.some((option) => option.value === values[choice.key])) fail(family.familyId, `${choice.key} is not a declared choice`);
  }
}

/**
 * The native runtime's descriptor for one prepared body: the family's rig and clips with the frame
 * measured from that body. `asset` is where its bytes are fetched from, a reviewed asset key or a
 * preparation the workspace holds.
 */
export function parametricNativeDescriptor(
  family: ParametricFamily,
  descriptor: ParametricDescriptor,
  asset: AuthoredObjectAssetReference,
): NativeCharacterDescriptor {
  checkDescriptor(descriptor, family.familyId);
  const scale = descriptor.unitScaleMillionths / 1_000_000;
  return {
    asset,
    rigId: family.rig.rigId,
    joints: family.rig.joints,
    unitScale: scale,
    forwardYawDegrees: descriptor.forwardYawDegrees,
    groundOffset: descriptor.nativeGroundOffsetMillionths / 1_000_000,
    standingHeight: descriptor.nativeStandingHeightMillionths / 1_000_000,
    clips: {
      idle: { name: descriptor.clips.idle.name, metresPerSecond: 0 },
      walk: { name: descriptor.clips.walk.name, metresPerSecond: descriptor.clips.walk.speedMillimetresPerSecond / 1000 },
      run: { name: descriptor.clips.run.name, metresPerSecond: descriptor.clips.run.speedMillimetresPerSecond / 1000 },
    },
    rootMotion: { mode: 'in-place' },
    materialSlots: Object.fromEntries(Object.entries(descriptor.materialSlots).map(([slot, materials]) => [slot, { materials }])),
    morphParameters: {},
    variantSlots: {},
  };
}

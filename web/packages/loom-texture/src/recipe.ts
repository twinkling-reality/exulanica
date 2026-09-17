import { canonicalJson } from './canonical-json.js';
import { MAKER_KINDS, MATERIAL_CLASSES, type MaterialClass, RELIEF_CLASSES } from './classes.js';

/**
 * Recipes and makers as data.
 *
 * A texture set is the output of a MAKER applied to a RECIPE. Both are objects in their own right,
 * each canonical JSON with a profile, each identified by the sha256 of its bytes:
 *
 *   - A maker manifest says which knobs a maker has: every control's key, kind, unit, range, group,
 *     label and explanation, plus the cross-parameter rules a recipe must satisfy. The maker's code
 *     is versioned; its manifest is what anything outside the code reads.
 *   - A recipe names a maker and version and gives a value for every control, the seed, the
 *     resolution and the physical extent. Nothing is left to a default: a recipe that omits a
 *     control is refused, so a recipe always means the same thing even if a default changes.
 *
 * The published library is eight recipes. A person's variant, a recipe a model proposes, and a
 * recipe fitted to a photograph are the same kind of object, and all of them are checked here and
 * by `exulanica.materials` in Python. Both read the shared cases in `test/recipe-cases.json` and
 * must return exactly the same problems for each, in the same order, so the two languages refuse
 * exactly the same objects for exactly the same reasons.
 *
 * Every number is an integer in a stated unit. `q16` is a fraction in 1/65536ths, `mm_1024ths` a
 * length in 1/1024 mm, and the rest are what they say.
 */
export const RECIPE_PROFILE = 'exulanica.texture-recipe/v1';
/** A procedural maker of the four-map opaque sets published before material classes. */
export const MAKER_PROFILE = 'exulanica.texture-maker/v1';
/**
 * A maker that states the material class its sets are, and is one of two kinds: `procedural`,
 * whose sets rebake exactly from a recipe, or `model`, whose sets are a generative model's output,
 * stored as made. A model-made maker states how its one generation ran and which optional maps the
 * model produced, and declares no controls: GPU generation is not bit-exact, so a variation is a
 * new generation, published as a new version, never a replay.
 */
export const MAKER_PROFILE_V2 = 'exulanica.texture-maker/v2';

export const UNITS = [
  'mm',
  'mm_1024ths',
  'q16',
  'percent',
  'permille',
  'count',
  'cells_per_tile',
] as const;
export type Unit = (typeof UNITS)[number];

/** Stated so an interface can group controls without knowing the maker. */
export const GROUPS = ['colour', 'module', 'relief', 'wear', 'detail', 'finish', 'lighting'] as const;
export type Group = (typeof GROUPS)[number];

export const SURFACES = ['vertical', 'horizontal'] as const;

interface ControlBase {
  readonly key: string;
  readonly group: Group;
  readonly label: string;
  readonly explanation: string;
}

export interface IntegerControl extends ControlBase {
  readonly kind: 'integer';
  readonly unit: Unit;
  readonly minimum: number;
  readonly maximum: number;
  readonly default: number;
}

export interface IntegerListControl extends ControlBase {
  readonly kind: 'integer_list';
  readonly unit: Unit;
  readonly minimum: number;
  readonly maximum: number;
  readonly minimum_items: number;
  readonly maximum_items: number;
  readonly default: readonly number[];
}

export interface ChoiceControl extends ControlBase {
  readonly kind: 'choice';
  readonly options: readonly string[];
  readonly default: string;
}

/** An sRGB colour, three bytes. */
export interface ColourControl extends ControlBase {
  readonly kind: 'srgb';
  readonly default: readonly [number, number, number];
}

/** A palette: between `minimum_items` and `maximum_items` sRGB colours. */
export interface PaletteControl extends ControlBase {
  readonly kind: 'srgb_list';
  readonly minimum_items: number;
  readonly maximum_items: number;
  readonly default: readonly (readonly [number, number, number])[];
}

export type Control =
  | IntegerControl
  | IntegerListControl
  | ChoiceControl
  | ColourControl
  | PaletteControl;

/**
 * An integer expression over a recipe: an integer control, an extent axis, a constant, or a sum or
 * product of expressions. Small on purpose; it is evaluated in two languages.
 */
export type Expression =
  | { readonly param: string }
  | { readonly extent: 'u' | 'v' }
  | { readonly constant: number }
  | { readonly sum: readonly Expression[] }
  | { readonly product: readonly Expression[] };

/** A constraint may apply only when a choice control has a given value. */
export interface Condition {
  readonly param: string;
  readonly equals: string;
}

export type Constraint =
  | {
      readonly kind: 'equal' | 'less' | 'less_or_equal';
      readonly left: Expression;
      readonly right: Expression;
      readonly when?: Condition;
      readonly explanation: string;
    }
  | {
      readonly kind: 'even';
      readonly value: Expression;
      readonly when?: Condition;
      readonly explanation: string;
    };

interface ManifestBase {
  readonly maker_id: string;
  readonly version: number;
  readonly family: string;
  readonly surface: (typeof SURFACES)[number];
  readonly truth: 'invented';
  readonly controls: readonly Control[];
  readonly constraints: readonly Constraint[];
}

export interface MakerManifestV1 extends ManifestBase {
  readonly profile: typeof MAKER_PROFILE;
  /** Procedural makers compute every texel from the recipe; nothing else is read. */
  readonly kind: 'procedural';
}

export interface ProceduralMakerManifest extends ManifestBase {
  readonly profile: typeof MAKER_PROFILE_V2;
  readonly kind: 'procedural';
  readonly material_class: MaterialClass;
}

/** How one generation ran, stated in full, because it can never be run again to the same bytes. */
export interface Generation {
  readonly model: { readonly id: string; readonly revision: string; readonly weights_sha256: string };
  /** Every input the model was conditioned on, by role and by the digest of its bytes. */
  readonly conditioning: readonly { readonly role: string; readonly sha256: string }[];
  /** Exactly one of a prompt or the parameters it was given. */
  readonly inputs:
    | { readonly prompt: string }
    | { readonly parameters: Readonly<Record<string, number | string>> };
  readonly seed: number;
  readonly sampler: Readonly<Record<string, number | string>> & { readonly name: string };
  readonly runtime: {
    readonly hardware: string;
    readonly libraries: readonly { readonly name: string; readonly version: string }[];
  };
}

export interface ModelMakerManifest extends ManifestBase {
  readonly profile: typeof MAKER_PROFILE_V2;
  readonly kind: 'model';
  readonly material_class: MaterialClass;
  readonly generation: Generation;
  /** The optional maps the model produced. A map not produced is absent, never filled in. */
  readonly maps_produced: { readonly normal: boolean; readonly height: boolean };
}

export type MakerManifest = MakerManifestV1 | ProceduralMakerManifest | ModelMakerManifest;

/** The material class a maker's sets are: every v1 maker's sets are opaque. */
export function materialClassOf(manifest: MakerManifest): MaterialClass {
  return manifest.profile === MAKER_PROFILE ? 'opaque' : manifest.material_class;
}

export type ParameterValue =
  | number
  | string
  | readonly number[]
  | readonly (readonly [number, number, number])[];

export interface Recipe {
  readonly profile: typeof RECIPE_PROFILE;
  readonly maker: { readonly id: string; readonly version: number };
  readonly seed: number;
  readonly resolution: { readonly width: number; readonly height: number };
  readonly extent_mm: { readonly u: number; readonly v: number };
  readonly parameters: Readonly<Record<string, ParameterValue>>;
}

/**
 * Controls every procedural maker whose class bakes a height field declares, which the bake reads
 * without asking the maker: the height scale and how occlusion is measured. Each is an integer in
 * the stated unit with a range inside the stated bounds, because the bake divides by the first and
 * third. A glazing maker declares none of them, and a model-made maker declares no controls at all.
 */
export const COMMON_CONTROLS: Readonly<
  Record<string, { readonly unit: Unit; readonly minimum: number; readonly maximum: number }>
> = {
  height_range_mm: { unit: 'mm', minimum: 1, maximum: 64 },
  occlusion_radius_mm: { unit: 'mm', minimum: 1, maximum: 64 },
  occlusion_depth_mm: { unit: 'mm', minimum: 1, maximum: 64 },
  occlusion_strength_permille: { unit: 'permille', minimum: 0, maximum: 1000 },
};

/**
 * Controls every procedural glazing maker declares, because its header declares the film from them
 * (`GlazingFilm` in `classes.ts`): the film's colour, and its roughness in thousandths.
 */
export const GLAZING_CONTROLS: Readonly<
  Record<string, { readonly kind: 'srgb' } | { readonly kind: 'integer'; readonly unit: Unit; readonly minimum: number; readonly maximum: number }>
> = {
  film_colour: { kind: 'srgb' },
  film_roughness_permille: { kind: 'integer', unit: 'permille', minimum: 0, maximum: 1000 },
};

export const MAKER_ID = /^[a-z][a-z0-9.-]*$/;
export const CONTROL_KEY = /^[a-z][a-z0-9_]*$/;
const FAMILY = /^[a-z][a-z0-9-]*$/;
const PRINTABLE = /^[\x20-\x7e]*$/;
/** The largest resolution a recipe may ask for, per axis. The decoded budget is 1024. */
export const MAXIMUM_RESOLUTION = 1024;
export const MINIMUM_RESOLUTION = 16;
/** The largest physical extent a tile may state, per axis, in mm. */
export const MAXIMUM_EXTENT_MM = 100_000;
/**
 * A conservative bound on how steep a height field may be: the height range, times the texels
 * along an axis, at most this many times that axis's extent in mm. With x that ratio on u and y on
 * v, `maps.normalMap` sums the squares of slopes up to x * 2^19 and y * 2^19 with 2^40, and
 * `isqrt` is exact below 2^52. At 32 on both axes the sum is about 2^49. The true edge is near 90
 * on both axes at once, or near 128 on one, so 32 is a deliberate margin, not the point where
 * exactness fails.
 */
export const HEIGHT_RANGE_TEXEL_LIMIT = 32;
/** How deep an expression may nest. */
export const MAXIMUM_EXPRESSION_DEPTH = 8;

const MANIFEST_KEYS = [
  'profile',
  'maker_id',
  'version',
  'kind',
  'family',
  'surface',
  'truth',
  'controls',
  'constraints',
];
const PROCEDURAL_MANIFEST_KEYS = [
  'profile',
  'maker_id',
  'version',
  'kind',
  'material_class',
  'family',
  'surface',
  'truth',
  'controls',
  'constraints',
];
const MODEL_MANIFEST_KEYS = [...PROCEDURAL_MANIFEST_KEYS, 'generation', 'maps_produced'];
const GENERATION_KEYS = ['model', 'conditioning', 'inputs', 'seed', 'sampler', 'runtime'];
const HEX64 = /^[0-9a-f]{64}$/;
const BASE_KEYS = ['key', 'kind', 'group', 'label', 'explanation', 'default'];
const CONTROL_KEYS: ReadonlyMap<string, readonly string[]> = new Map([
  ['integer', [...BASE_KEYS, 'unit', 'minimum', 'maximum']],
  ['integer_list', [...BASE_KEYS, 'unit', 'minimum', 'maximum', 'minimum_items', 'maximum_items']],
  ['choice', [...BASE_KEYS, 'options']],
  ['srgb', BASE_KEYS],
  ['srgb_list', [...BASE_KEYS, 'minimum_items', 'maximum_items']],
]);
const COMPARISONS = ['equal', 'less', 'less_or_equal'];
const RECIPE_KEYS = ['profile', 'maker', 'seed', 'resolution', 'extent_mm', 'parameters'];
const EXPRESSION_SHAPE = 'an expression has exactly one of param, extent, constant, sum, product';

const isInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value);
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string =>
  typeof value === 'string' && value.trim() !== '' && PRINTABLE.test(value);
const isPowerOfTwo = (value: number): boolean => value > 0 && (value & (value - 1)) === 0;
const has = (value: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);
const inside = (value: unknown, list: readonly string[]): boolean =>
  typeof value === 'string' && list.includes(value);

function sameKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value).sort();
  const wanted = [...keys].sort();
  return present.length === wanted.length && present.every((key, index) => key === wanted[index]);
}

function checkColour(value: unknown): boolean {
  return Array.isArray(value)
    && value.length === 3
    && value.every((channel) => isInteger(channel) && channel >= 0 && channel <= 255);
}

function checkValue(control: Control, value: unknown): string | null {
  switch (control.kind) {
    case 'integer':
      if (!isInteger(value)) return 'is an integer';
      if (value < control.minimum || value > control.maximum) {
        return `is between ${control.minimum} and ${control.maximum}`;
      }
      return null;
    case 'integer_list':
      if (!Array.isArray(value)) return 'is a list of integers';
      if (value.length < control.minimum_items || value.length > control.maximum_items) {
        return `holds ${control.minimum_items} to ${control.maximum_items} integers`;
      }
      if (!value.every((item) => isInteger(item) && item >= control.minimum && item <= control.maximum)) {
        return `holds integers between ${control.minimum} and ${control.maximum}`;
      }
      return null;
    case 'choice':
      return inside(value, control.options) ? null : `is one of ${control.options.join(', ')}`;
    case 'srgb':
      return checkColour(value) ? null : 'is three bytes of sRGB';
    case 'srgb_list':
      if (!Array.isArray(value)) return 'is a list of sRGB colours';
      if (value.length < control.minimum_items || value.length > control.maximum_items) {
        return `holds ${control.minimum_items} to ${control.maximum_items} colours`;
      }
      return value.every(checkColour) ? null : 'holds only three-byte sRGB colours';
  }
}

/** Why a control declaration is malformed, or null. Its default is checked separately. */
function controlShapeProblem(control: Record<string, unknown>): string | null {
  const keys = typeof control.kind === 'string' ? CONTROL_KEYS.get(control.kind) : undefined;
  if (keys === undefined) {
    return 'kind is one of integer, integer_list, choice, srgb, srgb_list';
  }
  if (!sameKeys(control, keys)) {
    return `a control of kind ${control.kind} has exactly ${keys.join(', ')}`;
  }
  if (typeof control.key !== 'string' || !CONTROL_KEY.test(control.key)) {
    return 'key is lowercase letters, digits and underscores, starting with a letter';
  }
  if (!inside(control.group, GROUPS)) return `group is one of ${GROUPS.join(', ')}`;
  if (!isText(control.label) || !isText(control.explanation)) {
    return 'label and explanation are non-empty printable ASCII';
  }
  if (control.kind === 'integer' || control.kind === 'integer_list') {
    if (!inside(control.unit, UNITS)) return `unit is one of ${UNITS.join(', ')}`;
    if (!isInteger(control.minimum) || !isInteger(control.maximum)
      || control.minimum > control.maximum) {
      return 'minimum and maximum are integers, minimum first';
    }
  }
  if (control.kind === 'integer_list' || control.kind === 'srgb_list') {
    const least = control.kind === 'srgb_list' ? 1 : 0;
    if (!isInteger(control.minimum_items) || !isInteger(control.maximum_items)
      || control.minimum_items < least || control.minimum_items > control.maximum_items) {
      return `minimum_items and maximum_items are integers, at least ${least}, minimum first`;
    }
  }
  if (control.kind === 'choice') {
    const options = control.options;
    if (!Array.isArray(options) || options.length === 0 || !options.every(isText)
      || new Set(options).size !== options.length) {
      return 'options are distinct non-empty printable ASCII, at least one';
    }
  }
  return null;
}

function expressionProblem(
  expression: unknown,
  integerKeys: ReadonlySet<string>,
  depth: number,
): string | null {
  if (depth > MAXIMUM_EXPRESSION_DEPTH) {
    return `an expression nests at most ${MAXIMUM_EXPRESSION_DEPTH} deep`;
  }
  if (!isObject(expression) || Object.keys(expression).length !== 1) return EXPRESSION_SHAPE;
  if (has(expression, 'param')) {
    if (typeof expression.param !== 'string') return 'param names a control by its key';
    return integerKeys.has(expression.param)
      ? null
      : `${expression.param} is not an integer control of this maker`;
  }
  if (has(expression, 'extent')) {
    return expression.extent === 'u' || expression.extent === 'v' ? null : 'extent is u or v';
  }
  if (has(expression, 'constant')) {
    return isInteger(expression.constant) ? null : 'a constant is an integer';
  }
  const terms = has(expression, 'sum')
    ? expression.sum
    : has(expression, 'product') ? expression.product : undefined;
  if (terms === undefined) return EXPRESSION_SHAPE;
  if (!Array.isArray(terms) || terms.length === 0) return 'a sum or product has at least one term';
  for (const term of terms) {
    const problem = expressionProblem(term, integerKeys, depth + 1);
    if (problem !== null) return problem;
  }
  return null;
}

function constraintProblem(
  constraint: unknown,
  integerKeys: ReadonlySet<string>,
  choices: ReadonlyMap<string, readonly string[]>,
): string | null {
  if (!isObject(constraint)) return 'a constraint is an object';
  const comparison = inside(constraint.kind, COMPARISONS);
  if (!comparison && constraint.kind !== 'even') {
    return 'kind is one of equal, less, less_or_equal, even';
  }
  const keys = comparison
    ? ['kind', 'left', 'right', 'explanation']
    : ['kind', 'value', 'explanation'];
  const conditioned = has(constraint, 'when');
  if (!sameKeys(constraint, conditioned ? [...keys, 'when'] : keys)) {
    return `a constraint of kind ${String(constraint.kind)} has exactly ${keys.join(', ')}, `
      + 'and may have when';
  }
  if (!isText(constraint.explanation)) return 'explanation is non-empty printable ASCII';
  for (const side of comparison ? ['left', 'right'] : ['value']) {
    const problem = expressionProblem(constraint[side], integerKeys, 1);
    if (problem !== null) return `${side}: ${problem}`;
  }
  if (conditioned) {
    const when = constraint.when;
    if (!isObject(when) || !sameKeys(when, ['param', 'equals'])) {
      return 'when has exactly param and equals';
    }
    const options = typeof when.param === 'string' ? choices.get(when.param) : undefined;
    if (options === undefined) return 'when names a choice control of this maker';
    if (!inside(when.equals, options)) return 'when equals one of that choice\'s options';
  }
  return null;
}

const isSettings = (value: unknown): value is Record<string, number | string> =>
  isObject(value)
  && Object.entries(value).every(([key, item]) => CONTROL_KEY.test(key) && (isInteger(item) || isText(item)));

/** Why a model-made maker's record of its generation is not well formed, or an empty list. */
function generationProblems(generation: unknown): string[] {
  if (!isObject(generation) || !sameKeys(generation, GENERATION_KEYS)) {
    return [`generation has exactly ${GENERATION_KEYS.join(', ')}`];
  }
  const problems: string[] = [];
  const model = generation.model;
  if (!isObject(model) || !sameKeys(model, ['id', 'revision', 'weights_sha256'])
    || !isText(model.id) || !isText(model.revision)
    || typeof model.weights_sha256 !== 'string' || !HEX64.test(model.weights_sha256)) {
    problems.push(
      'generation: model has exactly an id and a revision, non-empty printable ASCII, and the '
        + 'weights_sha256 of its weights',
    );
  }
  const conditioning = generation.conditioning;
  const inputs = Array.isArray(conditioning) ? conditioning : [];
  const conditioned = Array.isArray(conditioning)
    && inputs.every((input) => isObject(input) && sameKeys(input, ['role', 'sha256'])
      && isText(input.role) && typeof input.sha256 === 'string' && HEX64.test(input.sha256))
    && new Set(inputs.map((input) => (input as Record<string, unknown>).role)).size === inputs.length;
  if (!conditioned) {
    problems.push('generation: conditioning is a list of inputs, each a distinct role and the sha256 of its bytes');
  }
  const given = generation.inputs;
  const prompt = isObject(given) && sameKeys(given, ['prompt']) && isText(given.prompt);
  const parameters = isObject(given) && sameKeys(given, ['parameters']) && isSettings(given.parameters)
    && Object.keys(given.parameters).length > 0;
  if (!prompt && !parameters) {
    problems.push(
      'generation: inputs has exactly a prompt, non-empty printable ASCII, or parameters, '
        + 'integers and printable ASCII under lowercase keys',
    );
  }
  if (!isInteger(generation.seed) || generation.seed < 0 || generation.seed > 0xffffffff) {
    problems.push('generation: seed is an unsigned 32-bit integer');
  }
  const sampler = generation.sampler;
  if (!isSettings(sampler) || !isText(sampler.name)) {
    problems.push(
      'generation: sampler has a name and its settings, integers and printable ASCII under '
        + 'lowercase keys',
    );
  }
  const runtime = generation.runtime;
  const libraries = isObject(runtime) && Array.isArray(runtime.libraries) ? runtime.libraries : [];
  const ran = isObject(runtime) && sameKeys(runtime, ['hardware', 'libraries']) && isText(runtime.hardware)
    && libraries.length > 0
    && libraries.every((library) => isObject(library) && sameKeys(library, ['name', 'version'])
      && isText(library.name) && isText(library.version))
    && new Set(libraries.map((library) => (library as Record<string, unknown>).name)).size === libraries.length;
  if (!ran) {
    problems.push(
      'generation: runtime has exactly the hardware and its libraries, at least one, each a '
        + 'distinct name and its version',
    );
  }
  return problems;
}

/** Why `candidate` is not a well-formed maker manifest, or an empty list. */
export function manifestProblems(candidate: unknown): string[] {
  const v2 = isObject(candidate) && candidate.profile === MAKER_PROFILE_V2;
  const model = v2 && (candidate as Record<string, unknown>).kind === 'model';
  const keys = !v2 ? MANIFEST_KEYS : model ? MODEL_MANIFEST_KEYS : PROCEDURAL_MANIFEST_KEYS;
  if (!isObject(candidate) || !sameKeys(candidate, keys)) {
    return [`a maker manifest has exactly ${keys.join(', ')}`];
  }
  const problems: string[] = [];
  if (candidate.profile !== MAKER_PROFILE && !v2) {
    problems.push(`profile is ${MAKER_PROFILE} or ${MAKER_PROFILE_V2}`);
  }
  if (typeof candidate.maker_id !== 'string' || !MAKER_ID.test(candidate.maker_id)) {
    problems.push('maker_id is lowercase letters, digits, dots and hyphens, starting with a letter');
  }
  if (!isInteger(candidate.version) || candidate.version < 1) {
    problems.push('version is a positive integer');
  }
  if (!v2 && candidate.kind !== 'procedural') problems.push('kind is procedural');
  if (v2 && !inside(candidate.kind, MAKER_KINDS)) problems.push(`kind is one of ${MAKER_KINDS.join(', ')}`);
  if (v2 && !inside(candidate.material_class, MATERIAL_CLASSES)) {
    problems.push(`material_class is one of ${MATERIAL_CLASSES.join(', ')}`);
  }
  if (typeof candidate.family !== 'string' || !FAMILY.test(candidate.family)) {
    problems.push('family is lowercase letters, digits and hyphens, starting with a letter');
  }
  if (!inside(candidate.surface, SURFACES)) problems.push(`surface is one of ${SURFACES.join(', ')}`);
  if (candidate.truth !== 'invented') problems.push('truth is invented');
  if (model) {
    problems.push(...generationProblems(candidate.generation));
    const produced = candidate.maps_produced;
    if (!isObject(produced) || !sameKeys(produced, ['normal', 'height'])
      || typeof produced.normal !== 'boolean' || typeof produced.height !== 'boolean') {
      problems.push('maps_produced has exactly normal and height, each true or false');
    }
  }
  if (!Array.isArray(candidate.controls)) return [...problems, 'controls is a list'];
  if (!Array.isArray(candidate.constraints)) return [...problems, 'constraints is a list'];
  if (model && candidate.controls.length > 0) {
    problems.push('a model-made maker declares no controls; a variation is a new generation and a new version');
  }
  if (model && candidate.constraints.length > 0) {
    problems.push('a model-made maker declares no constraints');
  }

  const declared = new Map<string, Control>();
  candidate.controls.forEach((control: unknown, index: number) => {
    if (!isObject(control)) {
      problems.push(`controls[${index}]: a control is an object`);
      return;
    }
    const shape = controlShapeProblem(control);
    if (shape !== null) {
      problems.push(`controls[${index}]: ${shape}`);
      return;
    }
    const typed = control as unknown as Control;
    if (declared.has(typed.key)) {
      problems.push(`controls[${index}]: ${typed.key} is declared twice`);
      return;
    }
    declared.set(typed.key, typed);
    const problem = checkValue(typed, typed.default);
    if (problem !== null) problems.push(`controls[${index}]: default ${problem}`);
  });
  // A v1 maker is opaque. A procedural maker of a class that bakes a height field declares the
  // controls the bake reads; a glazing maker, which bakes none, declares none of them.
  const relief = !v2 || (!model && RELIEF_CLASSES.includes(candidate.material_class as MaterialClass));
  for (const [key, bounds] of Object.entries(COMMON_CONTROLS)) {
    const control = declared.get(key);
    if (relief && (control === undefined || control.kind !== 'integer' || control.unit !== bounds.unit
      || control.minimum < bounds.minimum || control.maximum > bounds.maximum)) {
      problems.push(
        `${key} is an integer control in ${bounds.unit} within ${bounds.minimum} to `
          + `${bounds.maximum}, because the bake reads it`,
      );
    }
    if (!relief && !model && candidate.material_class === 'glazing' && control !== undefined) {
      problems.push(`${key} is not a control of a glazing maker, whose bake reads no height field`);
    }
  }
  if (v2 && !model && candidate.material_class === 'glazing') {
    for (const [key, wanted] of Object.entries(GLAZING_CONTROLS)) {
      const control = declared.get(key);
      if (wanted.kind === 'srgb') {
        if (control === undefined || control.kind !== 'srgb') {
          problems.push(`${key} is an srgb control, because the header declares the film from it`);
        }
      } else if (control === undefined || control.kind !== 'integer' || control.unit !== wanted.unit
        || control.minimum < wanted.minimum || control.maximum > wanted.maximum) {
        problems.push(
          `${key} is an integer control in ${wanted.unit} within ${wanted.minimum} to `
            + `${wanted.maximum}, because the header declares the film from it`,
        );
      }
    }
  }

  const integerKeys = new Set(
    [...declared.values()].filter((control) => control.kind === 'integer').map((control) => control.key),
  );
  const choices = new Map(
    [...declared.values()]
      .filter((control): control is ChoiceControl => control.kind === 'choice')
      .map((control) => [control.key, control.options]),
  );
  candidate.constraints.forEach((constraint: unknown, index: number) => {
    const problem = constraintProblem(constraint, integerKeys, choices);
    if (problem !== null) problems.push(`constraints[${index}]: ${problem}`);
  });
  if (problems.length === 0) {
    try {
      canonicalJson(candidate);
    } catch {
      problems.push('a manifest is canonical JSON: integers and printable ASCII only');
    }
  }
  return problems;
}

/** An expression's value, or null where the arithmetic leaves the safe integer range. */
export function evaluate(expression: Expression, recipe: Recipe): number | null {
  if ('param' in expression) {
    const value = recipe.parameters[expression.param];
    if (!isInteger(value)) {
      throw new Error(`expression names ${expression.param}, which is not an integer control`);
    }
    return value;
  }
  if ('extent' in expression) return recipe.extent_mm[expression.extent];
  if ('constant' in expression) return expression.constant;
  const adding = 'sum' in expression;
  let total = adding ? 0 : 1;
  for (const term of adding ? expression.sum : expression.product) {
    const value = evaluate(term, recipe);
    if (value === null) return null;
    total = adding ? total + value : total * value;
    if (!Number.isSafeInteger(total)) return null;
  }
  return total;
}

/** Whether a constraint holds; null where its arithmetic leaves the safe integer range. */
function holds(constraint: Constraint, recipe: Recipe): boolean | null {
  if (constraint.when !== undefined
    && recipe.parameters[constraint.when.param] !== constraint.when.equals) {
    return true;
  }
  if (constraint.kind === 'even') {
    const value = evaluate(constraint.value, recipe);
    return value === null ? null : value % 2 === 0;
  }
  const left = evaluate(constraint.left, recipe);
  const right = evaluate(constraint.right, recipe);
  if (left === null || right === null) return null;
  switch (constraint.kind) {
    case 'equal':
      return left === right;
    case 'less':
      return left < right;
    case 'less_or_equal':
      return left <= right;
  }
}

/**
 * Why `candidate` is not a valid recipe for `manifest`, or an empty list. The manifest must
 * already be well-formed; `manifestProblems` is the check for that.
 */
export function recipeProblems(candidate: unknown, manifest: MakerManifest): string[] {
  if (!isObject(candidate) || !sameKeys(candidate, RECIPE_KEYS)) {
    return [`a recipe has exactly ${RECIPE_KEYS.join(', ')}`];
  }
  const problems: string[] = [];
  if (candidate.profile !== RECIPE_PROFILE) problems.push(`profile is ${RECIPE_PROFILE}`);
  const maker = candidate.maker;
  if (!isObject(maker) || !sameKeys(maker, ['id', 'version'])
    || maker.id !== manifest.maker_id || maker.version !== manifest.version) {
    problems.push(`maker is ${manifest.maker_id} version ${manifest.version}`);
  }
  if (!isInteger(candidate.seed) || candidate.seed < 0 || candidate.seed > 0xffffffff) {
    problems.push('seed is an unsigned 32-bit integer');
  }
  const resolution = candidate.resolution;
  if (!isObject(resolution) || !sameKeys(resolution, ['width', 'height'])
    || ![resolution.width, resolution.height].every(
      (axis) => isInteger(axis) && isPowerOfTwo(axis)
        && axis >= MINIMUM_RESOLUTION && axis <= MAXIMUM_RESOLUTION,
    )) {
    problems.push(
      `resolution is a power of two from ${MINIMUM_RESOLUTION} to ${MAXIMUM_RESOLUTION} on each axis`,
    );
  }
  const extent = candidate.extent_mm;
  if (!isObject(extent) || !sameKeys(extent, ['u', 'v'])
    || ![extent.u, extent.v].every(
      (axis) => isInteger(axis) && axis > 0 && axis <= MAXIMUM_EXTENT_MM,
    )) {
    problems.push(`extent_mm is a whole-millimetre u and v from 1 to ${MAXIMUM_EXTENT_MM}`);
  }
  const parameters = candidate.parameters;
  if (!isObject(parameters)) return [...problems, 'parameters is an object'];
  const declared = new Set(manifest.controls.map((control) => control.key));
  const undeclared = Object.keys(parameters)
    .filter((key) => !declared.has(key))
    .map((key) => (PRINTABLE.test(key) ? key : 'a key that is not printable ASCII'))
    .sort();
  for (const key of undeclared) {
    problems.push(`parameters: ${key} is not a control of ${manifest.maker_id}`);
  }
  for (const control of manifest.controls) {
    if (!has(parameters, control.key)) {
      problems.push(`parameters: ${control.key} is missing; a recipe states every control`);
      continue;
    }
    const problem = checkValue(control, parameters[control.key]);
    if (problem !== null) problems.push(`parameters: ${control.key} ${problem}`);
  }
  if (problems.length > 0) return problems;

  const recipe = candidate as unknown as Recipe;
  if (manifest.kind === 'model' && recipe.seed !== manifest.generation.seed) {
    problems.push('seed is the seed the model generated with');
  }
  const range = recipe.parameters.height_range_mm;
  if (isInteger(range)
    && (range * recipe.resolution.width > HEIGHT_RANGE_TEXEL_LIMIT * recipe.extent_mm.u
      || range * recipe.resolution.height > HEIGHT_RANGE_TEXEL_LIMIT * recipe.extent_mm.v)) {
    problems.push(
      `height_range_mm times the texels on an axis is at most ${HEIGHT_RANGE_TEXEL_LIMIT} times `
        + 'that axis in mm, a margin that keeps the bake\'s normals exact',
    );
  }
  for (const constraint of manifest.constraints) {
    const verdict = holds(constraint, recipe);
    if (verdict === null) {
      problems.push(`${constraint.explanation} (its arithmetic leaves the safe integer range)`);
    } else if (!verdict) {
      problems.push(constraint.explanation);
    }
  }
  return problems;
}

/** Refuse, naming every problem, or return the recipe typed. */
export function checkRecipe(candidate: unknown, manifest: MakerManifest): Recipe {
  const problems = recipeProblems(candidate, manifest);
  if (problems.length > 0) {
    throw new Error(`not a valid ${manifest.maker_id} recipe: ${problems.join('; ')}`);
  }
  return candidate as Recipe;
}

/** The recipe a maker's defaults make, with the given seed, resolution and extent. */
export function defaultRecipe(
  manifest: MakerManifest,
  seed: number,
  resolution: { width: number; height: number },
  extent: { u: number; v: number },
): Recipe {
  return {
    profile: RECIPE_PROFILE,
    maker: { id: manifest.maker_id, version: manifest.version },
    seed,
    resolution,
    extent_mm: extent,
    parameters: Object.fromEntries(manifest.controls.map((control) => [control.key, control.default])),
  };
}

/** Typed reads from a checked recipe. A wrong kind here is a maker bug, so it throws. */
export const read = {
  integer(recipe: Recipe, key: string): number {
    const value = recipe.parameters[key];
    if (!isInteger(value)) throw new Error(`${key} is not an integer in this recipe`);
    return value;
  },
  integers(recipe: Recipe, key: string): readonly number[] {
    const value = recipe.parameters[key];
    if (!Array.isArray(value) || !value.every(isInteger)) {
      throw new Error(`${key} is not an integer list in this recipe`);
    }
    return value as readonly number[];
  },
  choice(recipe: Recipe, key: string): string {
    const value = recipe.parameters[key];
    if (typeof value !== 'string') throw new Error(`${key} is not a choice in this recipe`);
    return value;
  },
  colour(recipe: Recipe, key: string): readonly [number, number, number] {
    const value = recipe.parameters[key];
    if (!checkColour(value)) throw new Error(`${key} is not a colour in this recipe`);
    return value as unknown as readonly [number, number, number];
  },
  palette(recipe: Recipe, key: string): readonly (readonly [number, number, number])[] {
    const value = recipe.parameters[key];
    if (!Array.isArray(value) || !value.every(checkColour)) {
      throw new Error(`${key} is not a palette in this recipe`);
    }
    return value as readonly (readonly [number, number, number])[];
  },
};

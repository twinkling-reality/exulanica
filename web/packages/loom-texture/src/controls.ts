import type { CavitySpec } from './definition.js';
import {
  COMMON_CONTROLS,
  type ChoiceControl,
  type ColourControl,
  type Condition,
  type Constraint,
  type Control,
  type Expression,
  type Group,
  type IntegerControl,
  type IntegerListControl,
  type PaletteControl,
  type Recipe,
  type Unit,
  read,
} from './recipe.js';
import type { Srgb } from './srgb.js';

/**
 * Builders for maker manifests, so a manifest reads as a list of knobs rather than as JSON.
 * Every builder returns a plain object with no undefined members, because manifests are
 * canonical JSON and published as objects of their own.
 */

export function integer(
  key: string,
  group: Group,
  unit: Unit,
  range: readonly [number, number],
  value: number,
  label: string,
  explanation: string,
): IntegerControl {
  return {
    key,
    kind: 'integer',
    group,
    unit,
    minimum: range[0],
    maximum: range[1],
    default: value,
    label,
    explanation,
  };
}

export function integers(
  key: string,
  group: Group,
  unit: Unit,
  range: readonly [number, number],
  items: readonly [number, number],
  value: readonly number[],
  label: string,
  explanation: string,
): IntegerListControl {
  return {
    key,
    kind: 'integer_list',
    group,
    unit,
    minimum: range[0],
    maximum: range[1],
    minimum_items: items[0],
    maximum_items: items[1],
    default: value,
    label,
    explanation,
  };
}

export function choice(
  key: string,
  group: Group,
  options: readonly string[],
  value: string,
  label: string,
  explanation: string,
): ChoiceControl {
  return { key, kind: 'choice', group, options, default: value, label, explanation };
}

export function colour(key: string, value: Srgb, label: string, explanation: string): ColourControl {
  return { key, kind: 'srgb', group: 'colour', default: value, label, explanation };
}

export function palette(
  key: string,
  value: readonly Srgb[],
  items: readonly [number, number],
  label: string,
  explanation: string,
): PaletteControl {
  return {
    key,
    kind: 'srgb_list',
    group: 'colour',
    minimum_items: items[0],
    maximum_items: items[1],
    default: value,
    label,
    explanation,
  };
}

/**
 * The controls every maker declares: the height scale and how occlusion is measured. Their units
 * and ranges are `COMMON_CONTROLS`, which `manifestProblems` holds every manifest to.
 */
export function commonControls(values: {
  readonly heightRangeMm: number;
  readonly occlusionRadiusMm: number;
  readonly occlusionDepthMm: number;
  readonly occlusionStrengthPermille: number;
}): Control[] {
  const common = (
    key: string,
    group: Group,
    value: number,
    label: string,
    explanation: string,
  ): IntegerControl => {
    const bounds = COMMON_CONTROLS[key]!;
    return integer(key, group, bounds.unit, [bounds.minimum, bounds.maximum], value, label, explanation);
  };
  return [
    common('height_range_mm', 'relief', values.heightRangeMm, 'Height range',
      'Millimetres between the lowest and highest point the height map can hold.'),
    common('occlusion_radius_mm', 'lighting', values.occlusionRadiusMm, 'Occlusion radius',
      'How far around each point the surface is compared to find crevices.'),
    common('occlusion_depth_mm', 'lighting', values.occlusionDepthMm, 'Occlusion depth',
      'How far below its surroundings a point must sit to be fully shadowed.'),
    common('occlusion_strength_permille', 'lighting', values.occlusionStrengthPermille,
      'Occlusion strength', 'The darkest a crevice can get, in thousandths.'),
  ];
}

export const heightRangeOf = (recipe: Recipe): number => read.integer(recipe, 'height_range_mm');

export function cavityOf(recipe: Recipe): CavitySpec {
  return {
    radiusMm: read.integer(recipe, 'occlusion_radius_mm'),
    depthMm: read.integer(recipe, 'occlusion_depth_mm'),
    strengthPermille: read.integer(recipe, 'occlusion_strength_permille'),
  };
}

export const param = (key: string): Expression => ({ param: key });
export const constant = (value: number): Expression => ({ constant: value });
export const extent = (axis: 'u' | 'v'): Expression => ({ extent: axis });
export const sum = (...terms: Expression[]): Expression => ({ sum: terms });
export const product = (...terms: Expression[]): Expression => ({ product: terms });

const conditioned = <T extends object>(body: T, when?: Condition): T =>
  when === undefined ? body : { ...body, when };

export function equal(
  left: Expression,
  right: Expression,
  explanation: string,
  when?: Condition,
): Constraint {
  return conditioned({ kind: 'equal' as const, left, right, explanation }, when);
}

export function less(
  left: Expression,
  right: Expression,
  explanation: string,
  when?: Condition,
): Constraint {
  return conditioned({ kind: 'less' as const, left, right, explanation }, when);
}

export function lessOrEqual(
  left: Expression,
  right: Expression,
  explanation: string,
  when?: Condition,
): Constraint {
  return conditioned({ kind: 'less_or_equal' as const, left, right, explanation }, when);
}

export function even(value: Expression, explanation: string, when?: Condition): Constraint {
  return conditioned({ kind: 'even' as const, value, explanation }, when);
}

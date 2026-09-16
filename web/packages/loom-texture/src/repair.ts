import type { Maker } from './maker.js';
import { type Expression, type ParameterValue, type Recipe, evaluate } from './recipe.js';

/**
 * Repair a recipe the way a person changing one control would repair the rest.
 *
 * Changing a brick's length breaks the rule that the bricks span the tile; the person making that
 * change would make the tile longer, not give up. So, in order:
 *
 *   1. a count an `even` rule needs even, while that rule applies, is raised by one if its range
 *      allows;
 *   2. an extent a module rule pins (`equal(expression, extent)`, with no extent in the
 *      expression) is set to the expression's value;
 *   3. an extent a proportion rule pins (`equal(product(..., extent, ...), extent)`, with exactly
 *      one extent in the product) is divided out, when the division is exact.
 *
 * Nothing else changes, and a repaired recipe is not thereby valid: the caller still checks it.
 * Used by the maker sweep and by the dataset sampler, so both reach the same corners.
 */
const mentionsExtent = (expression: Expression): boolean =>
  'extent' in expression
  || ('sum' in expression && expression.sum.some(mentionsExtent))
  || ('product' in expression && expression.product.some(mentionsExtent));

export function repairRecipe(maker: Maker, recipe: Recipe): Recipe {
  const { constraints, controls } = maker.manifest;
  const parameters: Record<string, ParameterValue> = { ...recipe.parameters };
  for (const constraint of constraints) {
    if (constraint.kind !== 'even' || !('param' in constraint.value)) continue;
    if (constraint.when !== undefined
      && parameters[constraint.when.param] !== constraint.when.equals) continue;
    const count = constraint.value.param;
    const current = parameters[count];
    const control = controls.find((candidate) => candidate.key === count);
    if (typeof current === 'number' && current % 2 !== 0
      && control?.kind === 'integer' && current < control.maximum) {
      parameters[count] = current + 1;
    }
  }
  let repaired: Recipe = { ...recipe, parameters };
  const extent = { ...repaired.extent_mm };
  for (const constraint of constraints) {
    if (constraint.kind !== 'equal' || !('extent' in constraint.right)) continue;
    if (mentionsExtent(constraint.left)) continue;
    const pinned = evaluate(constraint.left, repaired);
    if (pinned !== null && pinned > 0) extent[constraint.right.extent] = pinned;
  }
  repaired = { ...repaired, extent_mm: { ...extent } };
  for (const constraint of constraints) {
    if (constraint.kind !== 'equal' || !('extent' in constraint.right)) continue;
    if (!('product' in constraint.left)) continue;
    const terms = constraint.left.product;
    const axes = terms.filter((term): term is { readonly extent: 'u' | 'v' } => 'extent' in term);
    const rest = terms.filter((term) => !mentionsExtent(term));
    if (axes.length !== 1 || axes.length + rest.length !== terms.length) continue;
    const factor = evaluate({ product: rest }, repaired);
    const whole = extent[constraint.right.extent];
    if (factor !== null && factor > 0 && whole % factor === 0) {
      extent[axes[0]!.extent] = whole / factor;
    }
  }
  return { ...repaired, extent_mm: extent };
}

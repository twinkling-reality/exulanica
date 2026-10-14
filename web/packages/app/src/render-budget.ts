/**
 * The render budget catalog (`assets/catalogs/world-kinds/render-budget.v2.json`): by scene form,
 * the most a look may spend on sun shadows, contact shadowing, multisampling and resolution, and
 * the quality levels. The file's bytes are bundled, read once and refused by name if they are not
 * the catalog.
 */
import { readRenderBudget, type RenderBudget } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/render-budget.v2.json?raw';

export const RENDER_BUDGET: RenderBudget = readRenderBudget(catalogText);

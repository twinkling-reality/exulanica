/**
 * The render budget: by the form of a scene, the most a look may spend on its costliest passes.
 *
 * A look (a style pack's light and finish) chooses its sun shadows and its contact shadowing for how
 * a world should look. What those cost depends on what the scene holds, and the render budget
 * catalog (`assets/catalogs/world-kinds/render-budget.v1.json`) states, for each scene form, a cap on
 * each: how many shadow cascades, how large a shadow map, how far shadows reach, how many samples and
 * at what fraction of the frame contact shadowing is computed. A look's value above its cap is drawn
 * at the cap; a value under it is drawn as chosen. Every cap carries a class and a reason, and a cap
 * whose class is `ceiling` is the look's own ceiling, so it changes nothing.
 *
 * Presentation only: a cap changes how a scene is drawn, never what is in it, where anything is or
 * what a click finds.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const RENDER_BUDGET_CATALOG_ID = 'render-budget';

/** The scene forms a cap is stated for: every one must be stated, and no other. */
export const RENDER_FORMS = Object.freeze(['open_site', 'indoor_site', 'terrain', 'town_tiles'] as const);
export type RenderForm = (typeof RENDER_FORMS)[number];

/** Where a cap comes from: the look's own ceiling, a measured trade, or a chosen default. */
export type RenderCapClass = 'ceiling' | 'measured' | 'chosen';

/** What one scene form may spend, in the look's own units. */
export interface RenderCaps {
  readonly form: RenderForm;
  readonly sunShadowCascades: number;
  readonly sunShadowResolutionPx: number;
  readonly sunShadowDistanceM: number;
  readonly contactShadowSamples: number;
  /** A fraction of the frame's resolution, from 0.5 to 1. */
  readonly contactShadowScale: number;
}

export interface RenderBudget {
  readonly version: number;
  readonly byForm: ReadonlyMap<RenderForm, RenderCaps>;
}

/**
 * The range each cap may take: the range every look descriptor accepts for that value (`look.ts`
 * `validateTileLook` and `validateRenderLook`; `budgeted-look.test.ts` holds both to it), so a look
 * lowered to any cap is still a look, and a cap at the ceiling is the look as chosen. The shadow map
 * floor is the render look's, 1024 texels: the tile look also allows 512, which a cap never asks for.
 */
export const RENDER_CAP_RANGES = Object.freeze({
  sun_shadow_cascades: Object.freeze({ least: 1, most: 4 }),
  sun_shadow_resolution_px: Object.freeze({ least: 1024, most: 4096 }),
  sun_shadow_distance_m: Object.freeze({ least: 10, most: 400 }),
  contact_shadow_samples: Object.freeze({ least: 1, most: 64 }),
  contact_shadow_scale_permille: Object.freeze({ least: 500, most: 1000 }),
});
type CapKey = keyof typeof RENDER_CAP_RANGES;
const CAP_KEYS = Object.keys(RENDER_CAP_RANGES) as CapKey[];

/** Shadow maps are square powers of two the engine allocates; a cap names one of them. */
const SHADOW_RESOLUTIONS: readonly number[] = [1024, 2048, 4096];

const CLASSES: readonly RenderCapClass[] = ['ceiling', 'measured', 'chosen'];

function refuse(where: string, detail: string): never {
  throw new TypeError(`render budget catalog: ${where} ${detail}`);
}

function isForm(value: unknown): value is RenderForm {
  return typeof value === 'string' && (RENDER_FORMS as readonly string[]).includes(value);
}

function cap(value: unknown, where: string, key: CapKey): number {
  if (typeof value !== 'object' || value === null) return refuse(where, 'must state most, class and reason');
  const stated = value as Record<string, unknown>;
  const known = new Set(['most', 'class', 'reason']);
  for (const field of Object.keys(stated)) if (!known.has(field)) refuse(where, `states an unknown field ${JSON.stringify(field)}`);
  const { least, most } = RENDER_CAP_RANGES[key];
  const figure = stated['most'];
  if (typeof figure !== 'number' || !Number.isInteger(figure)) return refuse(`${where}.most`, 'must be a whole number');
  if (figure > most) return refuse(`${where}.most`, `is ${figure}, above the look's ceiling of ${most}`);
  if (figure < least) return refuse(`${where}.most`, `is ${figure}, below the look's floor of ${least}`);
  if (key === 'sun_shadow_resolution_px' && !SHADOW_RESOLUTIONS.includes(figure)) {
    return refuse(`${where}.most`, `must be one of ${SHADOW_RESOLUTIONS.join(', ')}`);
  }
  const kind = stated['class'];
  if (!CLASSES.includes(kind as RenderCapClass)) return refuse(`${where}.class`, `must be one of ${CLASSES.join(', ')}`);
  if (kind === 'ceiling' && figure !== most) return refuse(where, `is classed as the ceiling but states ${figure}, not ${most}`);
  const reason = stated['reason'];
  if (typeof reason !== 'string' || reason.trim() === '') return refuse(where, 'gives no reason');
  return figure;
}

/** Read the catalog's text, or refuse it by naming the first form or cap that is not one. */
export function readRenderBudget(text: string): RenderBudget {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== RENDER_BUDGET_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the render budget catalog');
  const version = document.catalog_version;
  if (typeof version !== 'number' || !Number.isInteger(version) || version < 1) return refuse('catalog_version', 'must be a whole number from 1');
  const byForm = new Map<RenderForm, RenderCaps>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const form = entry?.['key'];
    if (!isForm(form)) return refuse('an entry', `names the form ${JSON.stringify(form)}, which is none of ${RENDER_FORMS.join(', ')}`);
    if (byForm.has(form)) return refuse(form, 'is stated twice');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(form, 'gives no reason');
    const caps = entry['caps'];
    if (typeof caps !== 'object' || caps === null) return refuse(form, 'states no caps');
    const stated = caps as Record<string, unknown>;
    for (const key of Object.keys(stated)) if (!(key in RENDER_CAP_RANGES)) refuse(form, `caps an unknown value ${JSON.stringify(key)}`);
    for (const key of CAP_KEYS) if (!(key in stated)) refuse(form, `states no cap for ${key}`);
    const figure = (key: CapKey): number => cap(stated[key], `${form}.${key}`, key);
    byForm.set(form, Object.freeze({
      form,
      sunShadowCascades: figure('sun_shadow_cascades'),
      sunShadowResolutionPx: figure('sun_shadow_resolution_px'),
      sunShadowDistanceM: figure('sun_shadow_distance_m'),
      contactShadowSamples: figure('contact_shadow_samples'),
      contactShadowScale: figure('contact_shadow_scale_permille') / 1000,
    }));
  }
  for (const form of RENDER_FORMS) if (!byForm.has(form)) refuse(form, 'is not stated');
  return Object.freeze({ version, byForm });
}

/** The caps of one scene form, or a refusal naming a form the budget does not know. */
export function renderCapsFor(budget: RenderBudget, form: string): RenderCaps {
  const caps = isForm(form) ? budget.byForm.get(form) : undefined;
  if (caps === undefined) throw new TypeError(`render budget: no caps for the form ${JSON.stringify(form)}; the forms are ${RENDER_FORMS.join(', ')}`);
  return caps;
}

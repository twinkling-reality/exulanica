/**
 * Values read from tokens.css itself, for the few places code needs a token's value rather than
 * its name: the world's meaning roles are corrected against the application's own surfaces
 * (theme.ts), which are chosen in tokens.css and nowhere else.
 */

import css from './tokens.css?raw';

/** The `--name: value` pairs of the first rule whose selector is exactly `selector`. */
export function tokenBlock(selector: string): ReadonlyMap<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`tokens.css has no ${selector}`);
  const open = css.indexOf('{', start);
  const end = css.indexOf('}', open);
  const values = new Map<string, string>();
  for (const match of css.slice(open + 1, end).matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
    values.set(match[1]!, match[2]!.trim());
  }
  return values;
}

const SURFACE_ROLES = ['--color-surface-solid', '--color-surface-raised', '--color-surface-sunken'] as const;

function surfaces(selector: string): readonly string[] {
  const own = tokenBlock(selector);
  return SURFACE_ROLES.map((role) => {
    const value = own.get(role);
    if (value === undefined || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error(`tokens.css ${selector} ${role} is not a colour`);
    return value;
  });
}

/** The application's reading surfaces in each scheme: solid, raised and sunken. */
export const BRAND_SURFACES: Readonly<Record<'light' | 'dark', readonly string[]>> = Object.freeze({
  light: surfaces(':root'),
  dark: surfaces(":root[data-ui-scheme='dark']"),
});

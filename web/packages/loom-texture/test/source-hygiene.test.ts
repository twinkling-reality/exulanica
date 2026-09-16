import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The bake's determinism, checked where it is written rather than where it is reviewed.
 *
 * Every byte this package writes is a function of the library files and the source, nothing else.
 * A clock, an ambient random source or an environment read anywhere in `src/` would make that a
 * claim instead of a property, so this reads the source files itself, the way the backend's
 * model-manifest test keeps model identifiers out of Python source.
 *
 * Two lists. The first holds anywhere in a file, comments included, because nothing in this
 * package has a reason to name them at all. The second is the transcendental arithmetic V8 only
 * approximates (see `src/integer.ts`); it is matched in code with comments removed, since the
 * source explains in prose why it avoids them.
 */
const SOURCE = fileURLToPath(new URL('../src/', import.meta.url));

const NEVER: readonly [string, RegExp][] = [
  ['Math.random', /Math\s*\.\s*random/],
  ['Date', /\bDate\b/],
  ['hrtime', /hrtime/],
  ['process.env', /process\s*\.\s*env\b/],
  ['randomUUID', /randomUUID/],
  ['getRandomValues', /getRandomValues/],
  ['randomBytes', /randomBytes/],
  ['randomInt', /randomInt/],
  ['performance.now', /performance\s*\.\s*now/],
  ['node:os', /['"](?:node:)?os['"]/],
];

const APPROXIMATED = /Math\s*\.\s*(?:pow|exp|expm1|log|log1p|log2|log10|sin|cos|tan|asin|acos|atan|atan2|sinh|cosh|tanh|asinh|acosh|atanh|cbrt|hypot|fround)\b|\s\*\*\s|\*\*=/;

/** `Math.sqrt` is exact only behind `isqrt`'s correction, so that is the one file allowed it. */
const SQUARE_ROOT = /Math\s*\.\s*sqrt\b/;
const SQUARE_ROOT_ALLOWED = new Set(['integer.ts']);

function walk(directory: string): string[] {
  return readdirSync(directory)
    .flatMap((name) => {
      const path = join(directory, name);
      return statSync(path).isDirectory() ? walk(path) : [path];
    })
    .filter((path) => path.endsWith('.ts'))
    .sort();
}

const withoutComments = (text: string): string =>
  text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"])\/\/.*$/gm, '$1');

function violations(label: string, text: string): string[] {
  const found: string[] = [];
  for (const [name, pattern] of NEVER) {
    if (pattern.test(text)) found.push(`${label}: ${name}`);
  }
  const code = withoutComments(text);
  const approximated = code.match(APPROXIMATED);
  if (approximated !== null) found.push(`${label}: ${approximated[0].trim()}`);
  if (SQUARE_ROOT.test(code) && !SQUARE_ROOT_ALLOWED.has(label)) {
    found.push(`${label}: Math.sqrt outside integer.ts`);
  }
  return found;
}

const files = walk(SOURCE);
const label = (path: string): string => relative(SOURCE, path).split('\\').join('/');

describe('the bake has no source of nondeterminism', () => {
  it('names no clock, ambient randomness or environment read, anywhere in src', () => {
    const found = files.flatMap((path) => violations(label(path), readFileSync(path, 'utf8')));
    expect(found).toEqual([]);
  });

  it('walks every module, including the nested ones', () => {
    const walked = new Set(files.map(label));
    for (const required of [
      'catalog.ts',
      'cli.ts',
      'container.ts',
      'integer.ts',
      'library.ts',
      'maps.ts',
      'noise.ts',
      'objects.ts',
      'publish.ts',
      'recipe.ts',
      'srgb.ts',
      'inspect/png.ts',
      'inspect/contact-sheet.ts',
      'makers/index.ts',
      'makers/ashlar.ts',
      'makers/asphalt.ts',
      'makers/brick.ts',
      'makers/concrete.ts',
      'makers/kerb.ts',
      'makers/metal.ts',
      'makers/paving.ts',
      'makers/render.ts',
    ]) {
      expect(walked, `the sweep does not read ${required}`).toContain(required);
    }
  });

  it('catches each banned name when one is planted', () => {
    const planted = [
      'const now = Date.now();',
      'const r = Math.random();',
      'const t = process.hrtime();',
      'const home = process.env.HOME;',
      'const id = crypto.randomUUID();',
      "import { cpus } from 'node:os';",
      'const p = Math.pow(2, 0.5);',
      'const q = 2 ** 0.5;',
      'const s = Math.sqrt(2);',
    ];
    for (const line of planted) {
      expect(violations('planted.ts', line), line).not.toEqual([]);
    }
    // And the prose that explains the rule does not trip the arithmetic check.
    expect(violations('planted.ts', '/** `Math.pow` is refused here. */\nconst x = 1;')).toEqual([]);
  });
});

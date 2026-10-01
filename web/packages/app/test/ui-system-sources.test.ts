import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/*
 * Tokens are the only source of stacking layers and colours in the interface.
 *
 * - No app stylesheet or inline style sets a numeric z-index: every layer is a name from the one
 *   table in ui/system/tokens.css.
 * - The system stylesheets (components, layout, bridge) name no colour literal at all.
 * - Stylesheets written before the system still hold colour literals. Each is listed with the
 *   count it holds today as a ceiling; migrating a file lowers its number, and a new literal
 *   fails here. The list only shrinks.
 */

const SRC = new URL('../src/', import.meta.url).pathname;

function files(dir: string, suffixes: readonly string[]): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...files(path, suffixes));
    else if (suffixes.some((suffix) => entry.name.endsWith(suffix))) out.push(path);
  }
  return out;
}

const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(/g;
const withoutComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

/**
 * Colour literals in stylesheets that predate the system: a ceiling per file, never raised. A file
 * not listed may hold none.
 */
const LEGACY_COLOUR_CEILING: Readonly<Record<string, number>> = {
  'ui/character-studio.css': 59,
  'ui/living-world-inspector.css': 10,
  'ui/redesign.css': 77,
  'ui/society-comparison.css': 71,
};

describe('design tokens', () => {
  it('no app stylesheet or inline style sets a numeric z-index', () => {
    const offenders: string[] = [];
    for (const path of files(SRC, ['.css', '.ts'])) {
      if (path.endsWith('ui/system/tokens.css')) continue;
      const text = withoutComments(readFileSync(path, 'utf8'));
      for (const match of text.matchAll(/z-index:\s*-?\d/g)) {
        offenders.push(`${relative(SRC, path)}: ${match[0]}`);
      }
      for (const match of text.matchAll(/zIndex\s*=\s*['"`]?-?\d/g)) {
        offenders.push(`${relative(SRC, path)}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('every z token a stylesheet names is defined in the one table', () => {
    const tokens = readFileSync(join(SRC, 'ui/system/tokens.css'), 'utf8');
    const defined = new Set([...tokens.matchAll(/(--z-[a-z0-9-]+):/g)].map((m) => m[1]));
    const used = new Set<string>();
    for (const path of files(SRC, ['.css', '.ts'])) {
      for (const match of readFileSync(path, 'utf8').matchAll(/var\((--z-[a-z0-9-]+)\)/g)) used.add(match[1]!);
    }
    expect([...used].filter((name) => !defined.has(name))).toEqual([]);
  });

  it('the system stylesheets name no colour literal', () => {
    for (const name of ['components.css', 'layout.css', 'bridge.css']) {
      const text = withoutComments(readFileSync(join(SRC, 'ui/system', name), 'utf8'));
      expect([...text.matchAll(COLOUR)].map((m) => m[0]), name).toEqual([]);
    }
  });

  it('stylesheets that predate the system add no colour literal', () => {
    const counts: Record<string, number> = {};
    for (const path of files(SRC, ['.css'])) {
      const name = relative(SRC, path);
      if (name.startsWith('ui/system/')) continue;
      counts[name] = [...withoutComments(readFileSync(path, 'utf8')).matchAll(COLOUR)].length;
    }
    const over = Object.entries(counts)
      .filter(([name, count]) => count > (LEGACY_COLOUR_CEILING[name] ?? 0))
      .map(([name, count]) => `${name}: ${count} > ${LEGACY_COLOUR_CEILING[name] ?? 0}`);
    expect(over).toEqual([]);
  });

  it('only the icon table imports lucide', () => {
    const importers = files(SRC, ['.ts'])
      .filter((path) => /from\s+['"]lucide/.test(readFileSync(path, 'utf8')))
      .map((path) => relative(SRC, path));
    expect(importers).toEqual(['ui/system/icon.ts']);
  });
});

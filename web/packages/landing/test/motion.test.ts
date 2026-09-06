import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Motion on the landing page is held to two rules, and both are properties of the stylesheet
 * rather than of any one animation, so they are checked as text.
 *
 * The first rule is that a looping animation rests where the page is designed to sit. Every loop
 * here starts and ends on the composition the title screen would hold if nothing moved. That is
 * what makes the reduced-motion collapse honest: stopping the page yields the intended artwork,
 * not a frozen halfway pose. A loop whose ends disagree also visibly jumps once per cycle.
 *
 * The second rule is that reduced motion actually stops it, which the parallel frontend track in
 * frontier-roadmap.md states as an exit criterion for this surface.
 */

const read = (relative: string): string =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const PAGE = read('../src/style.css');
const ARTWORK = read('../src/ui/gradient-forms/style.css');

interface Keyframes {
  readonly name: string;
  readonly steps: ReadonlyMap<string, string>;
}

/** Extract each `@keyframes` block by counting braces; a regular expression cannot nest. */
function keyframes(source: string): readonly Keyframes[] {
  const found: Keyframes[] = [];
  const opener = /@keyframes\s+([\w-]+)\s*\{/g;
  let match = opener.exec(source);
  while (match !== null) {
    let depth = 1;
    let index = opener.lastIndex;
    while (index < source.length && depth > 0) {
      if (source[index] === '{') depth += 1;
      if (source[index] === '}') depth -= 1;
      index += 1;
    }
    const body = source.slice(opener.lastIndex, index - 1);
    const steps = new Map<string, string>();
    for (const step of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const declarations = step[2]!.replace(/\s+/g, ' ').trim().replace(/;$/, '');
      for (const offset of step[1]!.split(',')) steps.set(offset.trim(), declarations);
    }
    found.push({ name: match[1]!, steps });
    match = opener.exec(source);
  }
  return found;
}

/**
 * Split on commas that separate whole animations, not on the ones inside `var()` fallbacks and
 * `cubic-bezier()` arguments.
 */
function splitAnimations(declaration: string): readonly string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < declaration.length; index += 1) {
    const character = declaration[index];
    if (character === '(') depth += 1;
    else if (character === ')') depth -= 1;
    else if (character === ',' && depth === 0) {
      parts.push(declaration.slice(start, index));
      start = index + 1;
    }
  }
  parts.push(declaration.slice(start));
  return parts;
}

/** Animation names this stylesheet runs forever, read from its own `infinite` shorthands. */
function looping(source: string): ReadonlySet<string> {
  const names = new Set<string>();
  for (const declaration of source.matchAll(/animation:\s*([^;]+);/g)) {
    for (const shorthand of splitAnimations(declaration[1]!)) {
      if (!/\binfinite\b/.test(shorthand)) continue;
      const name = shorthand.trim().split(/\s+/)[0];
      if (name !== undefined && name !== 'none') names.add(name);
    }
  }
  return names;
}

describe('landing motion', () => {
  it('finds the loops it is meant to be checking', () => {
    expect(looping(PAGE)).toEqual(
      new Set(['wordmark-sheen', 'companion-breathe', 'companion-blink-track']),
    );
    expect(looping(ARTWORK)).toEqual(new Set(['gradient-forms-color']));
  });

  it('starts and ends every looping animation on the resting composition', () => {
    for (const source of [PAGE, ARTWORK]) {
      const loops = looping(source);
      const blocks = keyframes(source).filter((block) => loops.has(block.name));
      for (const block of blocks) {
        expect(block.steps.get('0%'), `${block.name} has no 0% step`).toBeDefined();
        expect(block.steps.get('100%'), `${block.name} has no 100% step`).toBeDefined();
        expect(block.steps.get('0%'), `${block.name} does not end where it starts`).toBe(
          block.steps.get('100%'),
        );
      }
      expect(blocks.length).toBeGreaterThan(0);
    }
  });

  it('stops every loop under reduced motion', () => {
    const block = PAGE.slice(PAGE.indexOf('@media (prefers-reduced-motion: reduce)'));
    expect(block).toContain('animation-duration: 0.01ms !important');
    expect(block).toContain('animation-iteration-count: 1 !important');
    for (const selector of ['.companion-menu-life', '.companion-menu-blink', '.companion-menu-face', '.wordmark']) {
      expect(block).toContain(selector);
    }
    expect(ARTWORK).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*gradient-forms-shift[\s\S]*animation: none !important/,
    );
  });

  /*
   * The artwork is a poster. It is drawn at 120vw and scaled 2.5 by the camera on the
   * informational surfaces, reaching about 93 megapixels of device pixels through a clip path, an
   * alpha mask and a soft-light grain, so invalidating it per frame makes the page flicker. A
   * per-field drift was built, measured and removed. The only motion it may carry is the color
   * cross-fade, which changes an opacity on a layer that is already rasterized.
   */
  it('animates nothing inside the artwork except the palette cross-fade', () => {
    expect(ARTWORK).not.toContain('will-change');
    expect(ARTWORK).not.toContain('gradient-forms-field');
    expect(ARTWORK).not.toContain('transform:');
    // The reduced-motion rule also declares `animation`, to switch it off; only what it runs counts.
    const animated = (ARTWORK.match(/animation:[^;]+;/g) ?? []).filter(
      (declaration) => !declaration.includes('none'),
    );
    expect(animated).toHaveLength(1);
    expect(animated[0]).toContain('gradient-forms-color');
  });
});

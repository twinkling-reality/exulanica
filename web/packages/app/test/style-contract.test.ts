import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const baseStyles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const redesignStyles = readFileSync(new URL('../src/ui/redesign.css', import.meta.url), 'utf8');
const companionStyles = readFileSync(
  new URL('../src/ui/companion-layout.css', import.meta.url),
  'utf8',
);
const componentStyles = [
  baseStyles,
  readFileSync(new URL('../src/appearance.css', import.meta.url), 'utf8'),
  // The first per-view stylesheet in the package. Added here rather than left outside, because a
  // file this test does not read is a file the palette and motion rules do not apply to.
  readFileSync(new URL('../src/ui/object-placement.css', import.meta.url), 'utf8'),
  companionStyles,
].join('\n');
const worldStyleAdapter = readFileSync(new URL('../src/theme.ts', import.meta.url), 'utf8');

describe('world-owned interface style contract', () => {
  it('keeps palette literals out of component styles', () => {
    expect(componentStyles).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(componentStyles).not.toMatch(/\brgba?\(/i);
    expect(componentStyles).not.toMatch(/\bhsla?\(/i);
  });

  it('routes the world skin through semantic tokens while keeping shape system-owned', () => {
    for (const declaration of componentStyles.matchAll(/font-family:\s*([^;]+);/g)) {
      expect(declaration[1]).toContain('var(--');
    }
    expect(componentStyles).not.toMatch(/transition:[^;]*\b\d+(?:ms|s)\b/);
    expect(componentStyles).not.toMatch(/saturate\(\s*\d/);
    expect(componentStyles).toContain('var(--ui-speech-radius)');
    expect(componentStyles).toContain('var(--ui-texture-image)');
    expect(componentStyles).toContain('var(--ui-companion-blur)');
    expect(componentStyles).toContain('var(--motion-easing)');
    expect(componentStyles).toContain("[data-transparency='reduced']");
    expect(componentStyles).toContain("[data-contrast='high'] .status");
    expect(componentStyles).toContain('color: var(--ui-companion-ink)');
    expect(componentStyles).toContain('background-color: var(--ui-companion-surface)');
    expect(worldStyleAdapter).not.toMatch(/['"]--(?:radius-|ui-choice-radius|ui-speech-radius)['"]\s*:/);
  });

  it('does not reveal closed panels when traversal begins', () => {
    const traversalRule = componentStyles.match(
      /#shell\[data-mode='traverse'\] > :where\([^}]+\)\s*\{([^}]*)\}/,
    );
    expect(traversalRule?.[1]).toContain('pointer-events: none');
    expect(traversalRule?.[1]).not.toContain('opacity');
    expect(componentStyles).toContain("#shell[data-index='open'] .rail");
  });

  it('keeps Companion layout in its canonical stylesheet', () => {
    expect(baseStyles).not.toContain('Fixed visual-novel composition');
    expect(baseStyles).not.toMatch(
      /\.companion-(?:speech|choice-rail)\s*\{[^}]*position:\s*fixed/,
    );
    expect(baseStyles).not.toMatch(
      /\.companion-encounter\[data-state='open'\]\s*\{[^}]*inset:\s*0/,
    );
    expect(redesignStyles).not.toMatch(
      /\.companion-encounter\[data-state='open'\]\s*\{[^}]*position:\s*fixed/,
    );
    expect(redesignStyles).not.toMatch(/\.companion-stage[^{]*\{[^}]*position:\s*absolute/);
    expect(companionStyles).toContain(
      "#shell .companion-encounter[data-state='open']",
    );
  });

  it('scrolls the photo drawer beneath its header, never under it', () => {
    const rule = (selector: string): string => {
      const found = [...redesignStyles.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^}]*)\}/g)]
        .filter((match) => match[1]?.trim() === selector);
      expect(found, selector).toHaveLength(1);
      return found[0]?.[2] ?? '';
    };
    // The drawer itself does not scroll: its header and body are stacked in it.
    const drawer = rule('#shell .photos-drawer');
    expect(drawer).toMatch(/overflow:\s*hidden/);
    expect(drawer).toMatch(/flex-direction:\s*column/);
    // Only the body scrolls, so its scrollport starts where the header ends.
    const body = rule('#shell .photos-drawer-body');
    expect(body).toMatch(/overflow:\s*auto/);
    expect(body).toMatch(/min-height:\s*0/);
    // A focus ring at the body's top edge stays inside it, sized from the ring's own tokens.
    expect(body).toMatch(
      /scroll-padding-block:\s*calc\(var\(--focus-ring-width\) \+ var\(--focus-ring-offset\)\)/,
    );
    expect(redesignStyles).toMatch(
      /:focus-visible \{ outline: var\(--focus-ring-width\) solid var\(--focus\); outline-offset: var\(--focus-ring-offset\); \}/,
    );
    expect(rule('#shell .photos-drawer-header')).not.toMatch(/position:\s*sticky|margin:\s*-/);
    expect(redesignStyles).not.toMatch(/\.photos-drawer[^{]*\{[^}]*position:\s*sticky/);
  });

  it('defines one open Companion arrival animation', () => {
    const allStyles = [baseStyles, redesignStyles, companionStyles].join('\n');
    const animatedOpenRules = allStyles.match(
      /[^{}]*\.companion-encounter\[data-state='open'\][^{}]*\{[^{}]*\banimation:\s*diegetic-plane-arrive/g,
    );
    expect(animatedOpenRules).toHaveLength(1);
  });
});

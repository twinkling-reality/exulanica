import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const componentStyles = [
  readFileSync(new URL('../src/style.css', import.meta.url), 'utf8'),
  readFileSync(new URL('../src/appearance.css', import.meta.url), 'utf8'),
  // The first per-view stylesheet in the package. Added here rather than left outside, because a
  // file this test does not read is a file the palette and motion rules do not apply to.
  readFileSync(new URL('../src/ui/object-placement.css', import.meta.url), 'utf8'),
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
});

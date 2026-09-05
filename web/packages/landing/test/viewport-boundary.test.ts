import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { MIN_HEIGHT, MIN_WIDTH, boundaryReason } from '../src/ui/viewport-boundary.js';

const desktop = { width: 1440, height: 900, coarsePointer: false };

describe('the viewport boundary', () => {
  it('lets a normal desktop window through', () => {
    expect(boundaryReason(desktop)).toBeNull();
  });

  it('admits a window exactly on both thresholds', () => {
    expect(boundaryReason({ width: MIN_WIDTH, height: MIN_HEIGHT, coarsePointer: false })).toBeNull();
  });

  it('blocks a window one pixel under either threshold', () => {
    expect(boundaryReason({ ...desktop, width: MIN_WIDTH - 1 })).toBe('narrow');
    expect(boundaryReason({ ...desktop, height: MIN_HEIGHT - 1 })).toBe('short');
  });

  /**
   * The ordering is the point of this one. A phone in landscape can clear both size thresholds,
   * and telling its owner to widen the window would be advice they cannot act on. The reason has
   * to be the input model, because the input model is what actually cannot be satisfied.
   */
  it('reports touch ahead of size, even when the size would also fail', () => {
    expect(boundaryReason({ width: 320, height: 480, coarsePointer: true })).toBe('touch');
    expect(boundaryReason({ width: 1440, height: 900, coarsePointer: true })).toBe('touch');
  });
});

describe('the landing atmosphere', () => {
  it('uses reusable vector forms without retired figure assets or world field', () => {
    const style = readFileSync('packages/landing/src/style.css', 'utf8');
    const document = readFileSync('packages/landing/index.html', 'utf8');
    const main = readFileSync('packages/landing/src/main.ts', 'utf8');
    const title = readFileSync('packages/landing/src/ui/title.ts', 'utf8');

    expect(title).toContain('createGradientForms(HOME_FORMS)');
    expect(style).not.toContain('.memory-crescent');
    expect(style).not.toContain('var(--field-image)');
    expect(style).not.toContain('background-image: url(');
    expect(document).not.toContain('/figures/');
    expect(document).not.toContain('id="grain"');
    expect(main).not.toContain('buildFigures');
    expect(title).not.toContain("el('img'");
    expect(title).not.toMatch(/orimera[12]/i);
  });
});

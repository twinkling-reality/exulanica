import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('the landing atmosphere', () => {
  it('excludes retired figure assets and the world field', () => {
    const style = readFileSync('packages/landing/src/style.css', 'utf8');
    const document = readFileSync('packages/landing/index.html', 'utf8');
    const main = readFileSync('packages/landing/src/main.ts', 'utf8');
    const title = readFileSync('packages/landing/src/ui/title.ts', 'utf8');

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

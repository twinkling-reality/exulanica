import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { ORIGIN_LANDSCAPE, contrastRatio } from '@exulanica/presentation';

import { brandMeaningProperties } from '../src/theme.js';
import { BRAND_SURFACES, tokenBlock } from '../src/ui/system/token-values.js';

/*
 * The application's surfaces are the brand's; the world's meaning roles (provenance, caution,
 * error) are drawn on them too. Each role keeps the world's hue and reads at its floor on every
 * brand surface, light and dark: text at 4.5, marks at 3.
 */

const bridge = readFileSync(new URL('../src/ui/system/bridge.css', import.meta.url), 'utf8');
const MARKS = ['user-mark', 'capture-mark', 'inference-mark', 'external-mark'];

describe('the world’s meaning roles on brand surfaces', () => {
  const properties = brandMeaningProperties(ORIGIN_LANDSCAPE.ui.colors);

  for (const [scheme, prefix] of [['light', '--on-brand-'], ['dark', '--on-brand-dark-']] as const) {
    it(`read at their floor on every ${scheme} surface`, () => {
      const failing: string[] = [];
      for (const [name, value] of Object.entries(properties)) {
        if (!name.startsWith(prefix) || (scheme === 'light' && name.startsWith('--on-brand-dark-'))) continue;
        const role = name.slice(prefix.length);
        const floor = MARKS.includes(role) ? 3 : 4.5;
        for (const surface of BRAND_SURFACES[scheme]) {
          const ratio = contrastRatio(value, surface);
          if (ratio < floor) failing.push(`${name} ${value} on ${surface}: ${ratio.toFixed(2)}`);
        }
      }
      expect(failing).toEqual([]);
    });
  }

  it('keeps a role the world gave that already reads', () => {
    // Aeroheart's error text clears the reading floor on the light brand surfaces as derived.
    expect(properties['--on-brand-error']).toBe(ORIGIN_LANDSCAPE.ui.colors.error);
  });

  it('bridge.css reads only roles theme.ts writes, and every one it writes', () => {
    const read = new Set([...bridge.matchAll(/var\((--on-brand-[a-z-]+)\)/g)].map((m) => m[1]!));
    expect([...read].sort()).toEqual(Object.keys(properties).sort());
  });
});

describe('words on the brand blend', () => {
  it('read at AA on both ends of the blend', () => {
    const root = tokenBlock(':root');
    for (const end of ['--brand-blue', '--brand-yellow']) {
      expect(contrastRatio(root.get('--color-text-on-brand')!, root.get(end)!), end).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('are not redefined by the dark scheme, because the blend stays pale', () => {
    expect(tokenBlock(":root[data-ui-scheme='dark']").has('--color-text-on-brand')).toBe(false);
    expect(tokenBlock(":root[data-ui-scheme='dark']").has('--brand-blend')).toBe(false);
  });
});

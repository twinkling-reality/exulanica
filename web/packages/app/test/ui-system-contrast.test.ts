import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/*
 * Every text role reads at WCAG AA (4.5:1) on every surface role, in the light and the dark scheme,
 * from the values in tokens.css. Disabled text is exempt (WCAG 1.4.3) and so is not checked. The
 * surface is checked as its solid colour: over the world it is that colour at 94 percent, and
 * Reduced transparency makes it exactly that.
 */

const css = readFileSync(new URL('../src/ui/system/tokens.css', import.meta.url), 'utf8');

function block(selector: string): Map<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`no ${selector}`);
  const open = css.indexOf('{', start);
  const end = css.indexOf('}', open);
  const values = new Map<string, string>();
  for (const match of css.slice(open + 1, end).matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) values.set(match[1]!, match[2]!.trim());
  return values;
}

function hex(value: string): string {
  const found = /#([0-9a-fA-F]{6})/.exec(value);
  if (found === null) throw new Error(`not a hex colour: ${value}`);
  return found[1]!;
}

function luminance(colour: string): number {
  const channel = (index: number) => {
    const c = parseInt(colour.slice(index, index + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

const contrast = (a: string, b: string): number => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

const TEXT = ['--color-text', '--color-text-muted', '--color-text-faint', '--color-accent-text',
  '--color-positive-text', '--color-caution-text', '--color-danger-text', '--color-info-text'];
const SURFACES = ['--color-surface-solid', '--color-surface-raised', '--color-surface-sunken'];

describe('token contrast', () => {
  for (const [scheme, selector] of [['light', ':root {'], ['dark', ":root[data-ui-scheme='dark'] {"]] as const) {
    it(`every text role reads at AA on every surface, ${scheme}`, () => {
      const base = block(':root {');
      const own = scheme === 'light' ? base : new Map([...base, ...block(selector)]);
      const failing: string[] = [];
      const pairs: [string, string][] = [
        ...TEXT.flatMap((text) => SURFACES.map((surface): [string, string] => [text, surface])),
        // The signal (selected, live) carries its own ink, and the accent's words on what is selected.
        ['--color-signal-ink', '--color-signal'],
        ['--color-accent-text', '--color-signal'],
        ['--color-text', '--color-signal'],
      ];
      for (const [text, surface] of pairs) {
        const ratio = contrast(hex(own.get(text)!), hex(own.get(surface)!));
        if (ratio < 4.5) failing.push(`${text} on ${surface}: ${ratio.toFixed(2)}`);
      }
      expect(failing).toEqual([]);
    });
  }

  it('following the system chooses exactly the dark scheme', () => {
    expect(block("  :root[data-ui-scheme='system'] {")).toEqual(block(":root[data-ui-scheme='dark'] {"));
    // The stage (the way in) is dark in every scheme, with exactly the dark values.
    expect(block("[data-ui-stage='dark'] {")).toEqual(block(":root[data-ui-scheme='dark'] {"));
  });

  it('the marks over the world read at AA whatever world is behind them, in every scheme alike', () => {
    // A mark's fill is translucent and the same in every scheme, so it is checked composited over the
    // brightest and the darkest world, and its words composited over that.
    const base = block(':root {');
    const rgba = (value: string): [number, number, number, number] => {
      const found = /#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?\b/.exec(value);
      if (found === null) throw new Error(`not a hex colour: ${value}`);
      const [r, g, b] = [0, 2, 4].map((at) => parseInt(found[1]!.slice(at, at + 2), 16)) as [number, number, number];
      return [r, g, b, found[2] === undefined ? 1 : parseInt(found[2], 16) / 255];
    };
    const over = (top: [number, number, number, number], under: string): string => [0, 2, 4]
      .map((at, i) => Math.round(top[i]! * top[3] + parseInt(under.slice(at, at + 2), 16) * (1 - top[3])).toString(16).padStart(2, '0'))
      .join('');
    const failing: string[] = [];
    for (const world of ['ffffff', '000000']) {
      for (const [text, fill] of [
        ['--color-world-mark-ink', '--color-world-mark'],
        ['--color-world-mark-ink', '--color-world-mark-soft'],
        ['--color-world-mark-ink', '--color-world-mark-line'],
        ['--color-world-mark-ink-muted', '--color-world-mark-line'],
        ['--color-world-mark-person-ink', '--color-world-mark-person'],
      ] as const) {
        const backdrop = over(rgba(base.get(fill)!), world);
        const ratio = contrast(over(rgba(base.get(text)!), backdrop), backdrop);
        if (ratio < 4.5) failing.push(`${text} on ${fill} over #${world}: ${ratio.toFixed(2)}`);
      }
    }
    expect(failing).toEqual([]);
    // No scheme sets them: they sit over the world, whose colours no theme sets.
    expect([...block(":root[data-ui-scheme='dark'] {").keys()].filter((name) => name.startsWith('--color-world-mark'))).toEqual([]);
  });

  it('words on the accent and on danger read at AA', () => {
    const base = block(':root {');
    expect(contrast(hex(base.get('--color-text-on-accent')!), hex(base.get('--color-accent')!))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(hex(base.get('--color-text-on-status')!), hex(base.get('--color-danger')!))).toBeGreaterThanOrEqual(4.5);
  });
});

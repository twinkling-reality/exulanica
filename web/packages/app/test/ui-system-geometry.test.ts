import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// -- Region geometry from the real stylesheets ------------------------------------------------------
//
// The regions are fixed boxes computed in layout.css from the size tokens in tokens.css. This
// evaluates those expressions for real viewports and checks that the boxes the regions own never
// meet: the top bar, the rail and the inspector column are disjoint, and the free world area the
// dock, toasts and heads-up stack centre in lies strictly between the rail and the inspector.

const read = (name: string) => readFileSync(new URL(`../src/ui/system/${name}`, import.meta.url), 'utf8');

function rootBlock(css: string): string {
  const start = css.indexOf(':root {');
  return css.slice(start, css.indexOf('\n}', start));
}

function declarations(block: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of block.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) found.set(match[1]!, match[2]!.trim());
  return found;
}

function px(expression: string, vars: Map<string, string>, depth = 0): number {
  if (depth > 20) throw new Error(`unresolvable ${expression}`);
  const text = expression.trim().replace(/^calc\((.*)\)$/s, '$1');
  const resolved = text.replace(/var\((--[a-z0-9-]+)\)/g, (_, name: string) => {
    const value = vars.get(name);
    if (value === undefined) throw new Error(`no ${name}`);
    return `(${px(value, vars, depth + 1)})`;
  }).replace(/(-?\d+(?:\.\d+)?)px/g, '$1');
  if (!/^[\d\s.+\-*/()]+$/.test(resolved)) throw new Error(`not a pixel expression: ${expression}`);
  return Function(`return (${resolved});`)() as number;
}

function shellVars(layoutCss: string, inspectorOpen: boolean): Map<string, string> {
  const vars = declarations(rootBlock(read('tokens.css')));
  const shellBlock = layoutCss.slice(layoutCss.indexOf('#shell {'), layoutCss.indexOf('}', layoutCss.indexOf('#shell {')));
  for (const [name, value] of declarations(shellBlock)) vars.set(name, value);
  if (inspectorOpen) {
    const open = layoutCss.indexOf('#shell[data-inspector-open] {');
    for (const [name, value] of declarations(layoutCss.slice(open, layoutCss.indexOf('}', open)))) vars.set(name, value);
  }
  return vars;
}

type Box = { left: number; top: number; right: number; bottom: number };
const meets = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

describe('region geometry', () => {
  const layoutCss = read('layout.css');
  for (const [width, height] of [[1440, 900], [1280, 800], [1024, 700]] as const) {
    for (const inspectorOpen of [false, true]) {
      it(`keeps the regions apart at ${width}x${height}, inspector ${inspectorOpen ? 'open' : 'closed'}`, () => {
        const v = shellVars(layoutCss, inspectorOpen);
        const gap = px('var(--region-gap)', v);
        const topBar: Box = { left: gap, top: gap, right: width - gap, bottom: gap + px('var(--topbar-height)', v) };
        const layoutTop = px('var(--layout-top)', v);
        const rail: Box = { left: gap, top: layoutTop, right: gap + px('var(--rail-width)', v), bottom: height - gap };
        const inspector: Box = {
          left: width - gap - px('var(--inspector-width)', v), top: layoutTop, right: width - gap, bottom: height - gap,
        };
        const world: Box = {
          left: px('var(--layout-left)', v), top: layoutTop,
          right: width - px('var(--layout-right)', v), bottom: height - px('var(--layout-bottom)', v),
        };
        expect(meets(topBar, rail)).toBe(false);
        expect(meets(topBar, inspector)).toBe(false);
        expect(meets(rail, inspector)).toBe(false);
        expect(meets(world, rail)).toBe(false);
        if (inspectorOpen) expect(meets(world, inspector)).toBe(false);
        expect(world.right - world.left).toBeGreaterThan(px('var(--dock-width)', v) / 2);
      });
    }
  }
});

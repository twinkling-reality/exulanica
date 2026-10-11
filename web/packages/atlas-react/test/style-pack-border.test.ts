/**
 * A ground's broken border as its colour chunk carries it: the working set into a chunk once, off
 * until a plane states values, and the values a plane states.
 *
 * Nothing here runs a shader: the cut itself is seen in frames. What is held is what a device is
 * handed, and that a device the working is not written for is handed none.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type * as pc from 'playcanvas';
import { BORDER_NEIGHBOURS_MOST, readGroundBorders, readSurfacePatterns, type PlaneBorder } from '@exulanica/atlas-core';
import { BORDER_PARAMETERS, bordersRun, clearPlaneBorder, setPlaneBorder, withBorder } from '../src/playcanvas/style-pack/border-material.js';
import { patternChunks } from '../src/playcanvas/style-pack/pattern-material.js';

// Relative to web/, where the suite runs.
const BORDERS = readGroundBorders(readFileSync('../assets/catalogs/world-kinds/ground-border.v1.json', 'utf8'));
const PATTERNS = readSurfacePatterns(readFileSync('../assets/catalogs/world-kinds/surface-pattern.v1.json', 'utf8'));
const balanced = (text: string): boolean => {
  const closes: Record<string, string> = { ')': '(', '}': '{' };
  const open: string[] = [];
  for (const character of text) {
    if (character === '(' || character === '{') open.push(character);
    else if (character in closes && open.pop() !== closes[character]) return false;
  }
  return open.length === 0;
};

describe('the border\'s working in a colour chunk', () => {
  // The engine's own colour chunk, in its shape: one colour function.
  const plain = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n\tdAlbedo = material_diffuse.rgb;\n}\n';

  it('is set before the chunk\'s own text with its call first in the colour function, once', () => {
    const albedo = 'void getAlbedo() {';
    const set = withBorder(plain);
    expect(set.split(albedo)).toHaveLength(2);
    // The call is the colour function's first statement, so a point cut away costs nothing more.
    expect(set.slice(set.indexOf(albedo) + albedo.length).trimStart().startsWith('exuBorderCut();')).toBe(true);
    // The chunk's own colour is all still there, after it.
    expect(set.endsWith(plain.slice(plain.indexOf(albedo) + albedo.length))).toBe(true);
    expect(balanced(set)).toBe(true);
    // One rectangle and one shape for the plane and for each neighbour its working carries.
    for (let n = 0; n < BORDER_NEIGHBOURS_MOST; n += 1) expect(set).toContain(`uniform vec4 exuOverShape${n};`);
    expect(set).not.toContain(`exuOverShape${BORDER_NEIGHBOURS_MOST}`);
    // Set again, nothing changes: a material two grounds wear carries it once.
    expect(withBorder(set)).toBe(set);
  });

  it('is off unless a plane states its own values: the first thing the working does is leave where none is stated', () => {
    const set = withBorder(plain);
    const opens = 'void exuBorderCut() {';
    expect(set.slice(set.indexOf(opens) + opens.length).replace(/\s+/g, ' ').trimStart().startsWith('float mode = exuBorderShape.w; if (mode <= 0.0) return;')).toBe(true);
  });

  it('goes into a pattern\'s chunk as into a plain one, and refuses a chunk with no one colour function', () => {
    const grain = patternChunks(PATTERNS.byMaterial.get('sand')!, null).glsl;
    const set = withBorder(grain);
    expect(set).toContain('exuPatternNoise');
    expect(set.split('exuBorderCut();')).toHaveLength(2);
    expect(balanced(set)).toBe(true);
    // A border set into nothing would silently draw none.
    expect(() => withBorder('void other() {}')).toThrow('no one colour function');
    expect(() => withBorder(`${grain}\nvoid getAlbedo() {}`)).toThrow('no one colour function');
  });

  it('runs on the WebGL2 device it is written for and on no other', () => {
    expect(bordersRun({ isWebGPU: false } as pc.GraphicsDevice)).toBe(true);
    expect(bordersRun({} as pc.GraphicsDevice)).toBe(true);
    expect(bordersRun({ isWebGPU: true } as pc.GraphicsDevice)).toBe(false);
  });
});

describe('the values a plane states for its border', () => {
  const held = () => {
    const values = new Map<string, number[]>();
    const instance = {
      setParameter: (name: string, data: number[]) => void values.set(name, data),
      deleteParameter: (name: string) => void values.delete(name),
    } as unknown as pc.MeshInstance;
    return { values, instance };
  };
  const sand = BORDERS.byMaterial.get('sand')!;
  const lake = BORDERS.byMaterial.get('lake')!;
  const soil = BORDERS.byMaterial.get('soil')!;

  it('are its rectangle and each neighbour\'s in the world\'s metres from where the site lies, and how each is read', () => {
    const { values, instance } = held();
    const plan: PlaneBorder = {
      own: sand,
      over: [
        { identity: 'path', rectMm: [0, 0, 2000, 30_000], border: soil, as: 'over' },
        { identity: 'lake', rectMm: [5000, 2000, 19_000, 28_000], border: lake, as: 'water' },
        { identity: 'deck', rectMm: [2000, 0, 4000, 3000], border: null, as: 'over' },
      ],
      overLeftOut: 0,
    };
    // A site whose origin lies 100 m east and 50 m south of the world's. West 2 m to east 21 m,
    // south 0 to north 30 m: the world's z runs south, so the north edge is the lesser z.
    setPlaneBorder(instance, [2000, 0, 21_000, 30_000], plan, [100, 50]);
    expect(values.get('exuBorder')).toEqual([102, 20, 121, 50]);
    // Its own edge in metres, read 1: a ground that breaks over.
    expect(values.get('exuBorderShape')).toEqual([0.26, 0.32, 7, 1]);
    expect(values.get('exuOver0')).toEqual([100, 20, 102, 50]);
    expect(values.get('exuOverShape0')).toEqual([0.2, 0.24, 4.5, 1]);
    // A water it reaches is read 2.
    expect(values.get('exuOver1')).toEqual([105, 22, 119, 48]);
    expect(values.get('exuOverShape1')).toEqual([0.12, 0.15, 6, 2]);
    // A ground laid to a line lies over it with no edge and no wander: a ruled cut.
    expect(values.get('exuOverShape2')).toEqual([0, 0, 1, 1]);
    // A neighbour it has none of is off.
    expect(values.get('exuOver3')).toEqual([0, 0, 0, 0]);
    expect(values.get('exuOverShape3')).toEqual([0, 0, 0, 0]);
    expect([...values.keys()].sort()).toEqual([...BORDER_PARAMETERS].sort());
    clearPlaneBorder(instance);
    expect(values.size).toBe(0);
  });

  it('read a ground that lies under as 2, and a ruled ground that only gives way as an edge of nothing', () => {
    const water = held();
    setPlaneBorder(water.instance, [0, 0, 1000, 1000], { own: lake, over: [{ identity: 'shore', rectMm: [0, 0, 5000, 5000], border: sand, as: 'over' }], overLeftOut: 0 }, [0, 0]);
    expect(water.values.get('exuBorderShape')).toEqual([0.12, 0.15, 6, 2]);
    expect(water.values.get('exuOverShape0')).toEqual([0.26, 0.32, 7, 1]);
    const lane = held();
    setPlaneBorder(lane.instance, [0, 0, 1000, 1000], { own: null, over: [], overLeftOut: 0 }, [0, 0]);
    expect(lane.values.get('exuBorderShape')).toEqual([0, 0, 1, 1]);
  });
});

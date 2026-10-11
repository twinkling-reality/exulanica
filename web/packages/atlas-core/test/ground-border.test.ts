import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { BORDER_NEIGHBOURS_MOST, borderReachMm, planBorders, readGroundBorders, type GroundPlane } from '../src/ground-border.js';
import { readSurfaceMaterials } from '../src/surface-material.js';

// Relative to web/, where the suite runs: the files a deployment ships.
const text = readFileSync('../assets/catalogs/world-kinds/ground-border.v1.json', 'utf8');
const BORDERS = readGroundBorders(text);
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const border = (key: string) => BORDERS.byMaterial.get(key)!;

describe('the ground border catalog', () => {
  it('states an edge for grounds a person walks and for water, each a material the surface catalog knows', () => {
    expect(BORDERS.version).toBe(1);
    const known = new Map(MATERIALS.materials.map((material) => [material.key, material]));
    for (const [key, one] of BORDERS.byMaterial) {
      // Water lies under and nothing else does: the one exception to the drawing's own layering.
      expect(one.lies, key).toBe(known.get(key)!.families.includes('water') ? 'under' : 'over');
    }
    expect([...BORDERS.byMaterial.keys()]).toEqual(expect.arrayContaining(['grass', 'soil', 'sand', 'forest_floor', 'cobble', 'paving', 'lake', 'harbour', 'sea']));
    // What is laid to a line keeps one: a floor, a deck and a carpet state no edge at all.
    for (const ruled of ['floor', 'timber', 'carpet', 'concrete', 'tile']) expect(BORDERS.byMaterial.has(ruled), ruled).toBe(false);
  });

  it('lets no ground reach farther from its ruled line than land may reach over water, and says the farthest', () => {
    const document = JSON.parse(text) as { entries: { lies: string; shore_reach_most_mm?: number }[] };
    const shoreMost = Math.min(...document.entries.filter((entry) => entry.lies === 'under').map((entry) => entry.shore_reach_most_mm!));
    const reaches = [...BORDERS.byMaterial.values()].map(borderReachMm);
    expect(Math.max(...reaches)).toBeLessThanOrEqual(shoreMost);
    expect(BORDERS.greatestReachMm).toBe(Math.max(...reaches));
    // A reach is the wander and half the break: 320 mm of wander and a 260 mm break reach 450 mm.
    expect(borderReachMm(border('sand'))).toBe(450);
    // Narrow against a path: the widest wander is under a sixth of a two metre path.
    expect(Math.max(...[...BORDERS.byMaterial.values()].map((one) => one.wanderMm))).toBeLessThanOrEqual(320);
  });

  it('refuses a file that is not the catalog, an entry stated twice, one with no reason, and figures that break nothing or reach too far', () => {
    const document = JSON.parse(text) as { entries: Record<string, unknown>[] };
    const grass = document.entries.find((entry) => entry['key'] === 'grass')!;
    const lake = document.entries.find((entry) => entry['key'] === 'lake')!;
    const withEntries = (...entries: Record<string, unknown>[]) => JSON.stringify({ ...document, entries });
    expect(() => readGroundBorders(JSON.stringify({ ...document, catalog_id: 'site-scenery' }))).toThrow('is not the ground border catalog');
    expect(() => readGroundBorders(JSON.stringify({ ...document, catalog_version: 0 }))).toThrow('catalog_version');
    expect(() => readGroundBorders(withEntries({ ...grass, key: 'Grass' }))).toThrow('has the key "Grass"');
    expect(() => readGroundBorders(withEntries(grass, grass))).toThrow('grass is stated twice');
    expect(() => readGroundBorders(withEntries({ ...grass, reason: ' ' }))).toThrow('grass gives no reason');
    expect(() => readGroundBorders(withEntries({ ...grass, lies: 'beside' }))).toThrow('grass.lies');
    expect(() => readGroundBorders(withEntries({ ...grass, edge_mm: 2.5 }))).toThrow('grass.edge_mm');
    expect(() => readGroundBorders(withEntries({ ...grass, wander_period_mm: 0 }))).toThrow('grass.wander_period_mm');
    expect(() => readGroundBorders(withEntries({ ...grass, edge_mm: 0, wander_mm: 0 }))).toThrow('grass breaks nothing');
    // Only what lies under states how far a ground may reach over it.
    expect(() => readGroundBorders(withEntries({ ...grass, shore_reach_most_mm: 600 }))).toThrow('grass states a shore reach');
    const { shore_reach_most_mm: _, ...dryLake } = lake;
    expect(() => readGroundBorders(withEntries(dryLake))).toThrow('lake states a shore reach');
    // The cap holds every ground, the water's own edge too: 601 mm of reach against a 600 mm cap.
    expect(() => readGroundBorders(withEntries({ ...grass, wander_mm: 481 }, lake))).toThrow('grass reaches 601 mm, farther than the 600 mm');
    expect(readGroundBorders(withEntries({ ...grass, wander_mm: 480 }, lake)).greatestReachMm).toBe(600);
    expect(() => readGroundBorders(withEntries(grass, { ...lake, shore_reach_most_mm: 100 }))).toThrow('farther than the 100 mm');
  });
});

/** A ground rectangle: west, south, east, north in metres, its layer in millimetres, its material. */
const plane = (identity: string, [w, s, e, n]: number[], layerMm: number, material: string | null): GroundPlane => ({
  identity, rectMm: [w! * 1000, s! * 1000, e! * 1000, n! * 1000], layerMm, border: material === null ? null : border(material),
});
const plan = (planes: GroundPlane[], base: string | null = 'base', beyond = true) => planBorders(planes, base, beyond, BORDERS.greatestReachMm);
const names = (planned: ReturnType<typeof plan>, identity: string) => planned.get(identity)!.over.map((one) => `${one.identity}:${one.as}`);

describe('the borders of a place\'s grounds', () => {
  // A camp: a forest floor over all of it, a clearing and a shore side by side, a path up the
  // middle over both, a lake in the shore laid higher than the path, and a tent's floor.
  const camp = [
    plane('base', [0, 0, 80, 100], 0, 'forest_floor'),
    plane('path', [39, 0, 41, 100], 12, 'soil'),
    plane('clearing', [0, 0, 39, 100], 6, 'grass'),
    plane('tent', [30, 20, 35, 25], 24, null),
    plane('shore', [41, 0, 80, 100], 6, 'sand'),
    plane('lake', [46, 2, 78, 98], 18, 'lake'),
  ];

  it('breaks the upper ground over the lower by the drawing\'s own layers, and runs the lower on under it', () => {
    const planned = plan(camp);
    // The path lies over the clearing and the shore: each gives way to it and is worked against it.
    expect(names(planned, 'clearing')).toEqual(['path:over']);
    expect(planned.get('clearing')!.own).toBe(border('grass'));
    // Nothing lies over the path: it is cut by its own edge alone.
    expect(planned.get('path')).toEqual({ own: border('soil'), over: [], overLeftOut: 0 });
    // A tent's floor is laid to a line and drawn higher: it simply covers, and is not worked at all.
    expect(planned.has('tent')).toBe(false);
    expect(names(planned, 'clearing')).not.toContain('tent:over');
  });

  it('takes the later of two grounds at one height as the upper', () => {
    const side = [plane('base', [0, 0, 20, 20], 0, 'sand'), plane('first', [0, 0, 10, 20], 6, 'grass'), plane('second', [10, 0, 20, 20], 6, 'soil')];
    const planned = plan(side);
    expect(names(planned, 'first')).toEqual(['second:over']);
    expect(names(planned, 'second')).toEqual([]);
  });

  it('lays water under whatever ground it meets, however high the drawing lays it: the land reaches it and it gives way', () => {
    const planned = plan(camp);
    // The lake is drawn higher than the shore and the path, and still lies under both.
    expect(names(planned, 'lake')).toEqual(['shore:over']);
    expect(planned.get('lake')!.own!.lies).toBe('under');
    // The shore is worked against the path over it and against the water it reaches, each as what it is.
    expect(names(planned, 'shore')).toEqual(['path:over', 'lake:water']);
    // The path is five metres from the lake, farther than any edge reaches: neither knows the other.
    expect(names(planned, 'path')).toEqual([]);
  });

  it('keeps a ground laid to a line ruled beside water, and gives way under a broken ground over it', () => {
    const quay = [
      plane('base', [0, 0, 40, 40], 0, 'grass'),
      plane('deck', [0, 10, 10, 20], 12, null),
      plane('harbour', [10, 10, 30, 20], 18, 'harbour'),
      plane('lane', [0, 22, 40, 25], 6, null),
      plane('cobbles', [0, 23, 40, 40], 12, 'cobble'),
    ];
    const planned = plan(quay);
    // A deck states no edge: it reaches no water and nothing lies over it, so it is drawn as before.
    expect(planned.has('deck')).toBe(false);
    // The water still gives way to it, on the deck's ruled line.
    expect(planned.get('harbour')!.over.map((one) => [one.identity, one.as, one.border])).toEqual([['deck', 'over', null]]);
    // A ruled lane under broken cobbles gives way where the cobbles are drawn, and keeps its own edge ruled.
    expect(planned.get('lane')).toEqual({ own: null, over: [{ identity: 'cobbles', rectMm: [0, 23_000, 40_000, 40_000], border: border('cobble'), as: 'over' }], overLeftOut: 0 });
  });

  it('breaks the ground over the whole place only where a ground beyond is drawn, and works nothing else against it', () => {
    expect(plan(camp).get('base')).toEqual({ own: border('forest_floor'), over: [], overLeftOut: 0 });
    // With nothing beyond, a break would open onto nothing: the outer edge stays ruled.
    expect(plan(camp, 'base', false).has('base')).toBe(false);
    // A base that states no edge is never worked.
    const floor = [plane('base', [0, 0, 20, 20], 0, null), plane('rug', [5, 5, 10, 10], 6, 'grass')];
    expect(plan(floor).has('base')).toBe(false);
    expect(plan(floor).get('rug')).toEqual({ own: border('grass'), over: [], overLeftOut: 0 });
    // A place with no ground over all of it has no base: every ground is worked by the one rule.
    const none = plan([plane('a', [0, 0, 10, 10], 6, 'grass'), plane('b', [5, 0, 15, 10], 12, 'soil')], null);
    expect(names(none, 'a')).toEqual(['b:over']);
  });

  it('knows a neighbour as far as either edge may reach and no farther', () => {
    const reach = (BORDERS.greatestReachMm + borderReachMm(border('soil'))) / 1000;
    const apart = (gap: number) => plan([
      plane('base', [0, 0, 40, 20], 0, 'sand'),
      plane('lawn', [0, 0, 10, 20], 6, 'grass'),
      plane('track', [10 + gap, 0, 12 + gap, 20], 12, 'soil'),
    ]);
    expect(names(apart(0), 'lawn')).toEqual(['track:over']);
    expect(names(apart(reach), 'lawn')).toEqual(['track:over']);
    expect(names(apart(reach + 0.001), 'lawn')).toEqual([]);
  });

  it('keeps the most overlapping neighbours where a ground has more than its working carries, and counts the rest', () => {
    const strips = Array.from({ length: BORDER_NEIGHBOURS_MOST + 2 }, (_, n) => plane(`strip-${n}`, [n * 10, 0, n * 10 + 2, 10 + n], 12, 'soil'));
    const planned = plan([plane('base', [0, 0, 100, 100], 0, 'sand'), plane('field', [0, 0, 100, 100], 6, 'grass'), ...strips]);
    // The longest strips are kept, longest first; the two shortest are counted.
    expect(names(planned, 'field')).toEqual([5, 4, 3, 2].map((n) => `strip-${n}:over`));
    expect(planned.get('field')!.overLeftOut).toBe(2);
    // Of two that overlap alike, the one whose name sorts first comes first: the same answer every time.
    const twins = plan([plane('field', [0, 0, 30, 10], 6, 'grass'), plane('b', [20, 0, 22, 10], 12, 'soil'), plane('a', [10, 0, 12, 10], 12, 'soil')], null);
    expect(names(twins, 'field')).toEqual(['a:over', 'b:over']);
  });
});

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readSiteScenery, sceneryBeyond, type SiteScenery } from '../src/site-scenery.js';

/*
 * Scenery beyond a made place, by arithmetic on a place a test states: 80 m east to west and 60 m
 * north to south from its own origin. Nothing here opens a world.
 */
const text = readFileSync(new URL('../../../../assets/catalogs/world-kinds/site-scenery.v1.json', import.meta.url), 'utf8');
const catalog = readSiteScenery(text);
const PLACE = { widthMm: 80_000, depthMm: 60_000 };
const WORLD = 'world:generated:3844173e-c3fe-44e7-a701-d11b16bb974d';
const forest = catalog.byMaterial.get('forest_floor')!;

/** How far beyond the place's rectangle a point is, worked here apart from the code under test. */
const beyond = (xMm: number, yMm: number): number => {
  const dx = Math.max(0, -xMm, xMm - PLACE.widthMm), dy = Math.max(0, -yMm, yMm - PLACE.depthMm);
  return Math.sqrt(dx * dx + dy * dy);
};

describe('the site scenery catalog', () => {
  it('states trees beyond a forest floor, stones beyond sand, a tree here and there beyond grass, and nothing else', () => {
    expect([...catalog.byMaterial.keys()].sort()).toEqual(['forest_floor', 'grass', 'sand']);
    expect([...catalog.byMaterial.values()].map((one) => [one.key, one.stands])).toEqual([['forest_floor', 'tree'], ['sand', 'stone'], ['grass', 'tree']]);
    // Every count is a budget and every entry gives its reason, which says the count is one.
    const document = JSON.parse(text) as { entries: { key: string; reason: string; most: number }[] };
    for (const entry of document.entries) {
      expect(entry.reason).toContain('rendering budget');
      expect(entry.most).toBeGreaterThan(0);
    }
    // A wood is denser than open country: its squares are smaller and more of them hold a tree.
    const grass = catalog.byMaterial.get('grass')!;
    expect(forest.spacingMm).toBeLessThan(grass.spacingMm);
    expect(forest.nearKeepPermille).toBeGreaterThan(grass.nearKeepPermille);
  });

  it('refuses a file that is not the catalog, an entry stated twice, one with no reason, and figures that cannot be held', () => {
    const document = JSON.parse(text) as { entries: Record<string, unknown>[] };
    const withFirst = (change: Record<string, unknown>) => JSON.stringify({ ...document, entries: [{ ...document.entries[0], ...change }] });
    expect(() => readSiteScenery(JSON.stringify({ ...document, catalog_id: 'roof-form' }))).toThrow('is not the site scenery catalog');
    expect(() => readSiteScenery(JSON.stringify({ ...document, entries: [document.entries[0], document.entries[0]] }))).toThrow('stated twice');
    expect(() => readSiteScenery(withFirst({ reason: ' ' }))).toThrow('gives no reason');
    expect(() => readSiteScenery(withFirst({ stands: 'dune' }))).toThrow('stands');
    expect(() => readSiteScenery(withFirst({ spacing_mm: 0 }))).toThrow('spacing_mm');
    expect(() => readSiteScenery(withFirst({ to_mm: 3000 }))).toThrow('ends no farther out than it begins');
    expect(() => readSiteScenery(withFirst({ edge_thin_mm: 200_000 }))).toThrow('thins toward the place');
    expect(() => readSiteScenery(withFirst({ height_mm: [9000, 5000] }))).toThrow('most under its least');
    expect(() => readSiteScenery(withFirst({ most: 0 }))).toThrow('most');
    expect(() => readSiteScenery(withFirst({ near_keep_permille: 1.5 }))).toThrow('near_keep_permille');
  });
});

describe('the scenery that stands beyond one place', () => {
  const pieces = sceneryBeyond(WORLD, PLACE, forest);

  it('stands only beyond the place\'s rectangle, no nearer than its margin and no farther than its reach', () => {
    expect(pieces.length).toBeGreaterThan(100);
    for (const piece of pieces) {
      const inside = piece.xMm >= 0 && piece.xMm <= PLACE.widthMm && piece.yMm >= 0 && piece.yMm <= PLACE.depthMm;
      expect(inside).toBe(false);
      const far = beyond(piece.xMm, piece.yMm);
      expect(far).toBeGreaterThanOrEqual(forest.fromMm - 0.5);
      expect(far).toBeLessThanOrEqual(forest.toMm + 0.5);
      expect(piece.beyondMm).toBe(Math.round(far));
      // Whole millimetres, a size within the entry's, a width that is the entry's share of the height.
      expect([piece.xMm, piece.yMm, piece.heightMm, piece.widthMm].every(Number.isInteger)).toBe(true);
      expect(piece.heightMm).toBeGreaterThanOrEqual(forest.heightMm[0]);
      expect(piece.heightMm).toBeLessThanOrEqual(forest.heightMm[1]);
      expect(piece.widthMm).toBe(Math.floor(piece.heightMm * forest.widthPermille / 1000));
      expect(piece.stands).toBe('tree');
    }
    // No two share a square, so none stands on another.
    expect(new Set(pieces.map((piece) => piece.identity)).size).toBe(pieces.length);
  });

  it('is the same every time for one world, and another world\'s is its own', () => {
    expect(sceneryBeyond(WORLD, PLACE, forest)).toEqual(pieces);
    const other = sceneryBeyond('world:generated:another', PLACE, forest);
    expect(other.length).toBeGreaterThan(100);
    const here = new Set(pieces.map((piece) => `${piece.xMm},${piece.yMm}`));
    // The squares are the same grid; where each tree stands in its square, and which squares hold one, are not.
    expect(other.filter((piece) => here.has(`${piece.xMm},${piece.yMm}`)).length).toBeLessThan(other.length / 20);
    // Stated here in whole millimetres, so a machine that placed them otherwise would fail: the three nearest.
    expect(pieces.slice(0, 3).map((piece) => [piece.identity, piece.xMm, piece.yMm, piece.beyondMm, piece.heightMm, piece.quarterTurns])).toMatchInlineSnapshot(`
      [
        [
          "-1:8",
          -3489,
          61852,
          3950,
          6391,
          3,
        ],
        [
          "5:9",
          39227,
          64564,
          4564,
          8558,
          1,
        ],
        [
          "8:-1",
          60276,
          -5190,
          5190,
          7231,
          0,
        ],
      ]
    `);
  });

  it('keeps to its budget, the nearest first, and thins toward the place', () => {
    expect(pieces.length).toBeLessThanOrEqual(forest.most);
    for (let i = 1; i < pieces.length; i += 1) expect(pieces[i]!.beyondMm).toBeGreaterThanOrEqual(pieces[i - 1]!.beyondMm);
    // A budget of forty keeps the forty nearest of the same trees.
    const few: SiteScenery = { ...forest, most: 40 };
    expect(sceneryBeyond(WORLD, PLACE, few)).toEqual(pieces.slice(0, 40));
    // Thinning toward the place: with no budget in the way, the 8 m next to the margin hold fewer trees
    // for their ground than the 8 m beyond the thinning ground do.
    const all = sceneryBeyond(WORLD, PLACE, { ...forest, most: 100_000 });
    const band = (from: number, to: number) => all.filter((piece) => piece.beyondMm >= from && piece.beyondMm < to).length;
    const ground = (from: number, to: number) => (PLACE.widthMm + 2 * to) * (PLACE.depthMm + 2 * to) - (PLACE.widthMm + 2 * from) * (PLACE.depthMm + 2 * from);
    const nearShare = band(forest.fromMm, forest.fromMm + 8000) / ground(forest.fromMm, forest.fromMm + 8000);
    const fullFrom = forest.fromMm + forest.edgeThinMm;
    const fullShare = band(fullFrom, fullFrom + 8000) / ground(fullFrom, fullFrom + 8000);
    expect(nearShare).toBeLessThan(fullShare / 3);
    // With no thinning ground the same 8 m are as full as any.
    const wall = sceneryBeyond(WORLD, PLACE, { ...forest, edgeThinMm: 0, most: 100_000 });
    const wallNear = wall.filter((piece) => piece.beyondMm >= forest.fromMm && piece.beyondMm < forest.fromMm + 8000).length;
    expect(wallNear).toBeGreaterThan(3 * band(forest.fromMm, forest.fromMm + 8000));
  });

  it('keeps its margin and its reach where nothing else would: with no thinning ground, no budget, and a margin of nothing', () => {
    // Open country cut small, so every band of the ground holds pieces: nothing thins toward the
    // place and no budget ends it early, and still none stands nearer than 6 m or farther than 60 m.
    const open: SiteScenery = { ...catalog.byMaterial.get('grass')!, spacingMm: 2000, nearKeepPermille: 1000, farKeepPermille: 1000, toMm: 60_000, most: 100_000 };
    const all = sceneryBeyond(WORLD, PLACE, open);
    expect(open.fromMm).toBe(6000);
    expect(Math.min(...all.map((piece) => piece.beyondMm))).toBeGreaterThanOrEqual(6000);
    expect(Math.min(...all.map((piece) => piece.beyondMm))).toBeLessThan(6000 + 500);
    expect(Math.max(...all.map((piece) => piece.beyondMm))).toBeLessThanOrEqual(60_000);
    expect(Math.max(...all.map((piece) => piece.beyondMm))).toBeGreaterThan(60_000 - 500);
    // Past a corner the reach is a quarter circle, not the square the grid is cut from: the squares
    // out to the reach each way are a ninth more than the ground the reach covers.
    const squares = ((PLACE.widthMm + 120_000) * (PLACE.depthMm + 120_000) - PLACE.widthMm * PLACE.depthMm) / (2000 * 2000);
    expect(all.length).toBeLessThan(squares * 0.97);
    // A margin of nothing still keeps the place itself clear: a piece may stand at the edge, never inside.
    const edge = sceneryBeyond(WORLD, PLACE, { ...open, fromMm: 0 });
    expect(edge.length).toBeGreaterThan(all.length);
    expect(edge.some((piece) => piece.beyondMm < 2000)).toBe(true);
    for (const piece of edge) {
      expect(piece.xMm >= 0 && piece.xMm <= PLACE.widthMm && piece.yMm >= 0 && piece.yMm <= PLACE.depthMm).toBe(false);
    }
  });

  it('gives a place of no size nothing, and stones their own shape', () => {
    expect(sceneryBeyond(WORLD, { widthMm: 0, depthMm: 60_000 }, forest)).toEqual([]);
    const sand = catalog.byMaterial.get('sand')!;
    const stones = sceneryBeyond(WORLD, PLACE, sand);
    expect(stones.length).toBeGreaterThan(20);
    expect(stones.length).toBeLessThanOrEqual(sand.most);
    for (const stone of stones) {
      expect(stone.stands).toBe('stone');
      // Low and wide: wider than it is high.
      expect(stone.widthMm).toBeGreaterThan(stone.heightMm);
    }
  });
});

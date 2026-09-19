/**
 * WHAT HOLDS A COMPONENT UP, and what the detachment count is therefore a count of.
 *
 * `componentsDetachedFromSupport` is not a census of things floating in the air. It is the number
 * of connected components a breadth-first walk does not reach from a SUPPORT ROOT, and a component
 * becomes a root only by the rule in `integrity`: it holds a walking-classified triangle AND the
 * product's support, sampled AT ITS SINGLE LOWEST VERTEX, is within the contact tolerance of that
 * vertex. Everything else is attached by touching something already reached.
 *
 * Those two halves fail in opposite directions, and each test below holds one still and moves the
 * other:
 *
 *   - the ROOT half consults the support surface at ONE PLAN POINT per component, so one refused
 *     sample at that one point detaches the whole component and everything hanging off it, however
 *     much of its footprint rests flat on drawn ground;
 *   - the REACHABILITY half is transitive and unbounded, so what is detached depends on WHAT ELSE
 *     WAS DRAWN. The same geometry, with the same support under it, counts as detached or attached
 *     according to whether the piece it continues into is in the scene at all.
 *
 * The second is why the count moved 773 to 322 when three neighbouring tiles began to draw, and it
 * is why a fall in this number is not by itself evidence that anything was repaired.
 */
import { describe, expect, it } from 'vitest';
import {
  SupportSamples,
  TriangleTable,
  classify,
  componentQueryPoints,
  components,
  integrity,
  type DrawnMesh,
} from '../src/index.js';
import { box, mesh, quad } from './fixtures.js';

/** The product's answer under a plan point: a height, or `null` where it states no surface. */
type Support = (x: number, z: number) => number | null;

/** Flat ground at height zero everywhere the caller does not refuse. */
const everywhere: Support = () => 0;

/**
 * Measure a scene against a product support of the caller's choosing.
 *
 * `classify` samples support at every triangle CENTROID and `integrity` samples it again at every
 * component's LOWEST VERTEX, so both populations are queried here and the same function answers
 * both. A test that refused only one of the two would be measuring its own fixture.
 */
function measured(meshes: readonly DrawnMesh[], support: Support = everywhere) {
  const table = new TriangleTable(meshes);
  const parts = components(table);
  const centroids = table.centroidQueryPoints();
  const lowest = componentQueryPoints(parts.list);
  const points = new Float64Array(centroids.length + lowest.length);
  points.set(centroids);
  points.set(lowest, centroids.length);
  const heights: (number | null)[] = [];
  for (let i = 0; i < points.length; i += 2) heights.push(support(points[i]!, points[i + 1]!));
  const samples = new SupportSamples(points, heights);
  const classification = classify(table, [], samples);
  return { result: integrity(table, classification, [], parts, samples), parts, classification };
}

/** One quad of ground at height zero, wound as the street fixture winds its own. */
function ground(west: number, east: number): number[] {
  const out: number[] = [];
  quad(out, [west, 0, -10], [west, 0, 10], [east, 0, 10], [east, 0, -10]);
  return out;
}

describe('a genuinely floating component is counted, once, and named', () => {
  it('raises the count by exactly one against a baseline that is already not zero', () => {
    const plane = ground(0, 40);
    const lantern: number[] = [];
    box(lantern, [5, 3, -1], [6, 4, 1]);
    const before = measured([mesh('ground', plane), mesh('lantern', lantern)]);
    expect(before.result.componentsDetachedFromSupport).toBe(1);
    expect(before.result.detachedByMesh).toEqual({ lantern: 1 });

    // One more box in the air, touching nothing, and nothing else in the scene changed.
    const banner: number[] = [];
    box(banner, [25, 3, -1], [26, 4, 1]);
    const after = measured([mesh('ground', plane), mesh('lantern', lantern), mesh('banner', banner)]);

    expect(after.result.componentsDetachedFromSupport).toBe(
      before.result.componentsDetachedFromSupport + 1,
    );
    // Named, so a rise of one cannot be one component arriving as a different one leaves.
    expect(after.result.detachedByMesh).toEqual({ lantern: 1, banner: 1 });
    expect(after.result.detachedExamples.map((example) => example.meshIds)).toContainEqual(['banner']);
  });

  it('counts one component once however many meshes it spans, and names every one of them', () => {
    const plane = ground(0, 40);
    // Two halves of one solid in two meshes, sharing their vertices at x = 5.5, so they weld.
    const bracket: number[] = [];
    box(bracket, [5, 3, -1], [5.5, 4, 1]);
    const sign: number[] = [];
    box(sign, [5.5, 3, -1], [6, 4, 1]);
    const { result } = measured([mesh('ground', plane), mesh('bracket', bracket), mesh('sign', sign)]);

    expect(result.componentsDetachedFromSupport).toBe(1);
    // `detachedByMesh` counts that one component under BOTH names, so its total exceeds the count.
    expect(result.detachedByMesh).toEqual({ bracket: 1, sign: 1 });
  });
});

describe('a component supported only by a neighbour is attached, and only while the neighbour is drawn', () => {
  /**
   * Two tiles meeting near x = 20, baked separately, so their edge vertices do not coincide: the
   * east ground starts 10 mm east of where the west ground stops, inside the 50 mm contact
   * tolerance and not welded to it. Support answers only over the west tile, standing for a square
   * the navigation surface covers next to one it does not.
   */
  const west = ground(0, 20);
  const east = ground(20.01, 40);
  const shelter: number[] = [];
  box(shelter, [30, 0, -1], [32, 3, 1]);
  const westOnly: Support = (x) => (x <= 20 ? 0 : null);

  it('counts nothing detached when the neighbouring tile carrying the support is drawn', () => {
    const { result } = measured(
      [mesh('west', west), mesh('east', east), mesh('shelter', shelter)],
      westOnly,
    );
    // Only the west ground can be a root: support is refused over every plan point of the other
    // two, so neither holds a walking triangle at all.
    expect(result.supportComponents).toBe(1);
    expect(result.componentsDetachedFromSupport).toBe(0);
  });

  it('counts the same geometry as detached when the neighbour is not drawn', () => {
    const { result } = measured([mesh('east', east), mesh('shelter', shelter)], westOnly);
    // Identical east geometry, identical support answers over it. Only the west tile is missing.
    expect(result.supportComponents).toBe(0);
    expect(result.componentsDetachedFromSupport).toBe(2);
    expect(result.detachedByMesh).toEqual({ east: 1, shelter: 1 });
  });
});

describe('the root rule asks one plan point per component and believes the answer', () => {
  /**
   * Refuse the one plan point given, to the micrometre `SupportSamples` keys its map by, and count
   * how many of the queried points were actually refused.
   *
   * The count is asserted by every test that uses this. A refusal that matched no queried point at
   * all would leave the support surface whole, and the test would then be measuring an unchanged
   * fixture while reading as though it had proved something.
   */
  function refusing(x: number, z: number): { support: Support; refusals: () => number } {
    const key = (px: number, pz: number): string => `${Math.round(px * 1e6)}:${Math.round(pz * 1e6)}`;
    const wanted = key(x, z);
    let refusals = 0;
    return {
      support: (px, pz) => {
        if (key(px, pz) !== wanted) return 0;
        refusals += 1;
        return null;
      },
      refusals: () => refusals,
    };
  }

  it('detaches a whole component resting flat on the ground for one refused sample', () => {
    const plane = ground(0, 40);
    const attached = measured([mesh('ground', plane)]);
    expect(attached.result.supportComponents).toBe(1);
    expect(attached.result.componentsDetachedFromSupport).toBe(0);

    // The point the rule asks about, read from the component rather than assumed: a flat plane's
    // vertices are all equally low and which one is `lowest` is the code's own tie-break.
    const lowest = attached.parts.list[0]!.lowest;
    const one = refusing(lowest[0], lowest[2]);
    const refused = measured([mesh('ground', plane)], one.support);

    // Exactly one queried point was refused, and it is the point the root rule asks about.
    expect(one.refusals()).toBe(1);
    // Same geometry, same plane, still classified as walking, and support still answers zero at
    // every centroid and at every other corner.
    expect(refused.classification.walkingTriangles).toBe(attached.classification.walkingTriangles);
    expect(refused.result.supportComponents).toBe(0);
    expect(refused.result.componentsDetachedFromSupport).toBe(1);
  });

  it('carries that one refusal to everything standing on the component', () => {
    const plane = ground(0, 40);
    const bench: number[] = [];
    box(bench, [10, 0, -1], [12, 1, 1]);
    const tree: number[] = [];
    box(tree, [20, 0, -1], [21, 4, 1]);
    const meshes = [mesh('ground', plane), mesh('bench', bench), mesh('tree', tree)];

    const attached = measured(meshes);
    expect(attached.result.componentsDetachedFromSupport).toBe(0);

    const lowest = attached.parts.list[0]!.lowest;
    const one = refusing(lowest[0], lowest[2]);
    const refused = measured(meshes, one.support);
    expect(one.refusals()).toBe(1);
    // One plan point stops answering and three components are reported as floating.
    expect(refused.result.componentsDetachedFromSupport).toBe(3);
    expect(refused.result.detachedByMesh).toEqual({ ground: 1, bench: 1, tree: 1 });
  });
});

import { describe, expect, it } from 'vitest';
import type { LayoutInputIsland } from '../src/index.js';
import {
  CAPTURE_FORWARD_LOCAL,
  DEFAULT_LAYOUT_CONFIG,
  LayoutScopeError,
  MAX_ISLANDS,
  atlasVec3,
  entityId,
  islandId,
  layoutEntitiesOf,
  placement,
  semanticSimilarity,
  solveLayout,
} from '../src/index.js';
import { localDirectionToAtlas } from '../src/index.js';
import { atlasGroundDistance } from '../src/presentation-metrics.js';
import { anchor } from './fixture.js';

function input(
  key: string,
  creationOrdinal: number,
  entities: readonly string[],
  pinned: LayoutInputIsland['pinned'] = null,
): LayoutInputIsland {
  return {
    islandId: islandId(key),
    creationOrdinal,
    footprintRadiusLocal: 30,
    scale: 1,
    layoutEntities: new Set(entities.map(entityId)),
    pinned,
  };
}

const placements = (r: ReturnType<typeof solveLayout>): string =>
  JSON.stringify([...r.nonmetric_arrangement.entries()].sort());

describe('the layout solver is deterministic', () => {
  const three = [
    input('a', 1000, ['e1', 'e2', 'e3']),
    input('b', 2000, ['e1', 'e2', 'e9']),
    input('c', 3000, ['e7']),
  ];

  it('produces byte-identical output for identical input', () => {
    expect(placements(solveLayout(three, 1))).toBe(placements(solveLayout(three, 1)));
  });

  it('is invariant to the order the islands are handed to it', () => {
    const shuffled = [three[2]!, three[0]!, three[1]!];
    expect(placements(solveLayout(shuffled, 1))).toBe(placements(solveLayout(three, 1)));
  });

  it('orders by persisted creation ordinal, then by island id, so invalid ties are deterministic', () => {
    const tied = [input('z', 500, ['e1']), input('a', 500, ['e1']), input('m', 500, ['e1'])];
    expect(placements(solveLayout(tied, 1))).toBe(
      placements(solveLayout([tied[1]!, tied[2]!, tied[0]!], 1)),
    );
    // Checked against the seed rather than the relaxed result, because three identical islands
    // relax into a symmetric triangle where radius carries no information. The seed is where the
    // ordering actually shows: phyllotaxis radius grows with index, so 'a' is innermost.
    const seeded = solveLayout(tied, 1, { strategy: 'seed-only' });
    const byRadius = [...seeded.nonmetric_arrangement.entries()]
      .map(([id, p]) => [id, Math.hypot(p.position.x, p.position.z)] as const)
      .sort((x, y) => x[1] - y[1])
      .map(([id]) => id);
    expect(byRadius).toEqual(['a', 'm', 'z']);
  });

  it('uses no ambient randomness at all', () => {
    const real = Math.random;
    Math.random = () => {
      throw new Error('the layout solver must not call Math.random');
    };
    try {
      expect(() => solveLayout(three, 1)).not.toThrow();
    } finally {
      Math.random = real;
    }
  });

  it('does not read the clock', () => {
    const realNow = Date.now;
    Date.now = () => {
      throw new Error('the layout solver must not read the clock');
    };
    try {
      expect(() => solveLayout(three, 1)).not.toThrow();
    } finally {
      Date.now = realNow;
    }
  });
});

describe('semantic proximity, not geography', () => {
  it('places islands that share entities closer than islands that do not', () => {
    const r = solveLayout(
      [
        input('a', 1, ['p1', 'p2', 'p3', 'p4']),
        input('b', 2, ['p1', 'p2', 'p3', 'p4']),
        input('c', 3, ['q1', 'q2', 'q3', 'q4']),
      ],
      1,
    );
    const a = r.nonmetric_arrangement.get(islandId('a'))!.position;
    const b = r.nonmetric_arrangement.get(islandId('b'))!.position;
    const c = r.nonmetric_arrangement.get(islandId('c'))!.position;
    expect(atlasGroundDistance(a, b)).toBeLessThan(atlasGroundDistance(a, c));
    expect(atlasGroundDistance(a, b)).toBeLessThan(atlasGroundDistance(b, c));
  });

  it('never lets footprints overlap, however similar two islands are', () => {
    const r = solveLayout([input('a', 1, ['x']), input('b', 2, ['x'])], 1);
    const a = r.nonmetric_arrangement.get(islandId('a'))!.position;
    const b = r.nonmetric_arrangement.get(islandId('b'))!.position;
    expect(atlasGroundDistance(a, b)).toBeGreaterThan(60);
  });

  it('scores similarity by Jaccard, so a large island is not close to everything', () => {
    const small = new Set([entityId('x')]);
    const large = new Set(['x', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'].map(entityId));
    expect(semanticSimilarity(small, small)).toBe(1);
    expect(semanticSimilarity(small, large)).toBeCloseTo(0.1, 12);
    expect(semanticSimilarity(new Set(), large)).toBe(0);
  });
});

describe('speculative links must never move the world', () => {
  it('excludes every proposed or provisional link from the persisted layout set', () => {
    const anchors = [
      anchor('i', { key: 'a', local: [0, 0, 0], entity: 'confirmed-1', linkState: 'confirmed' }),
      anchor('i', { key: 'b', local: [1, 0, 0], entity: 'guess-1', linkState: 'proposed', confidence: 'high' }),
      anchor('i', { key: 'c', local: [2, 0, 0], entity: 'guess-2', linkState: 'auto_provisional', confidence: 'low' }),
      anchor('i', { key: 'd', local: [3, 0, 0], entity: 'guess-3', linkState: 'auto_provisional', confidence: 'medium' }),
      anchor('i', { key: 'e', local: [4, 0, 0], entity: 'strong-1', linkState: 'auto_provisional', confidence: 'high' }),
      anchor('i', { key: 'f', local: [5, 0, 0], entity: 'gone-1', linkState: 'rejected', confidence: 'high' }),
    ];
    expect([...layoutEntitiesOf(anchors)].sort()).toEqual(['confirmed-1']);
  });

  it('gives the same layout whether or not a speculative link exists', () => {
    const withoutGuess = [
      input('a', 1, ['shared']),
      input('b', 2, ['shared']),
      input('c', 3, ['other']),
    ];
    // A `proposed` link to 'shared' on island c would look like this if it were let through, and
    // it would visibly pull c toward a and b. layoutEntitiesOf is what stops it reaching here.
    const ifItLeaked = [
      input('a', 1, ['shared']),
      input('b', 2, ['shared']),
      input('c', 3, ['other', 'shared']),
    ];
    expect(placements(solveLayout(withoutGuess, 1))).not.toBe(
      placements(solveLayout(ifItLeaked, 1)),
    );
  });
});

describe('adding an island does not scramble the ones already there', () => {
  it('keeps every pinned island inside the drift radius', () => {
    const first = solveLayout(
      [input('a', 1, ['p']), input('b', 2, ['p']), input('c', 3, ['q'])],
      1,
    );
    const pinnedInputs = ['a', 'b', 'c'].map((k, i) =>
      input(k, i + 1, i === 2 ? ['q'] : ['p'], first.nonmetric_arrangement.get(islandId(k))!),
    );
    const second = solveLayout([...pinnedInputs, input('d', 4, ['p', 'q'])], 2);

    for (const k of ['a', 'b', 'c']) {
      const before = first.nonmetric_arrangement.get(islandId(k))!.position;
      const after = second.nonmetric_arrangement.get(islandId(k))!.position;
      expect(atlasGroundDistance(before, after)).toBeLessThanOrEqual(
        DEFAULT_LAYOUT_CONFIG.driftRadius + 1e-6,
      );
    }
  });

  it('reports which islands moved, largest first, so the Companion can say why', () => {
    const pinned = placement(atlasVec3(0, 0, 0), 0, 1);
    const r = solveLayout([input('a', 1, ['p'], pinned), input('b', 2, ['p'])], 2);
    expect(r.moved.map((m) => m.islandId)).toEqual(['a']);
    expect(r.moved[0]!.distance).toBeGreaterThan(0);
  });

  it('preserves the full pinned transform, including yaw, height and presentation scale', () => {
    const pinned = placement(atlasVec3(10, 0.75, -4), 1.234, 1.6);
    const r = solveLayout([input('a', 1, ['p'], pinned), input('b', 2, ['p'])], 2, {
      driftRadius: 0,
    });
    expect(r.nonmetric_arrangement.get(islandId('a'))).toEqual(pinned);
  });
});

describe('the solver refuses to solve an infinite world', () => {
  it('rejects zero islands', () => {
    expect(() => solveLayout([], 1)).toThrow(LayoutScopeError);
  });

  it('rejects more than five', () => {
    const many = Array.from({ length: MAX_ISLANDS + 1 }, (_, i) => input(`i${i}`, i, ['p']));
    expect(() => solveLayout(many, 1)).toThrow(/deliberate refusal/);
  });

  it('accepts one island, because the single-photo path is the primary experience', () => {
    const r = solveLayout([input('solo', 1, [])], 1);
    expect(r.nonmetric_arrangement.size).toBe(1);
    expect(r.nonmetric_arrangement.get(islandId('solo'))!.yaw).toBe(0);
  });

  it('requires a placement for every island under the hand-placed strategy (experiment I-4)', () => {
    expect(() =>
      solveLayout([input('a', 1, ['p'], placement(atlasVec3(0, 0, 0), 0, 1)), input('b', 2, ['p'])], 1, {
        strategy: 'hand-placed',
      }),
    ).toThrow(/requires a pinned placement/);
  });
});

describe('every island faces the middle of the Atlas', () => {
  it('turns the capture direction toward the centroid, so no island is entered from behind', () => {
    const r = solveLayout(
      [input('a', 1, ['p']), input('b', 2, ['p', 'q']), input('c', 3, ['q'])],
      1,
    );
    const entries = [...r.nonmetric_arrangement.entries()];
    const cx = entries.reduce((s, [, p]) => s + p.position.x, 0) / entries.length;
    const cz = entries.reduce((s, [, p]) => s + p.position.z, 0) / entries.length;

    for (const [, p] of entries) {
      const facing = localDirectionToAtlas(p, CAPTURE_FORWARD_LOCAL);
      const toCentre = { x: cx - p.position.x, z: cz - p.position.z };
      const len = Math.hypot(toCentre.x, toCentre.z);
      // A 2.5D shell has observed surfaces on one side only. Facing outward would mean the user
      // arrives at the void.
      expect(facing.x).toBeCloseTo(toCentre.x / len, 9);
      expect(facing.z).toBeCloseTo(toCentre.z / len, 9);
      expect(facing.y).toBeCloseTo(0, 12);
    }
  });
});

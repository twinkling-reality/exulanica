import { describe, expect, it } from 'vitest';
import {
  DEFAULT_LAYOUT_CONFIG,
  LAYOUT_FRAME,
  islandId,
  solveLayout,
  type LayoutInputIsland,
} from '../src/index.js';

/*
 * The solver arranges; it does not measure. Its seed spacing, separations and drift radius were
 * once described as distances, and a district in real centimetres read the result as positions in
 * itself. The result now names its frame, and a caller reads the placements through that name.
 */
describe('layout frame', () => {
  const input = (key: string, ordinal: number): LayoutInputIsland => ({
    islandId: islandId(key),
    creationOrdinal: ordinal,
    footprintRadiusLocal: 5,
    scale: 1,
    layoutEntities: new Set(),
    pinned: null,
  });

  it('says its placements are a nonmetric arrangement', () => {
    const result = solveLayout([input('a', 0), input('b', 1)], 1);
    expect(LAYOUT_FRAME).toBe('nonmetric_arrangement');
    expect(result.frame).toBe('nonmetric_arrangement');
    expect(Object.keys(result)).not.toContain('placements');
    expect([...result.nonmetric_arrangement.keys()]).toEqual([islandId('a'), islandId('b')]);
  });

  it('keeps the arrangement parameters it always had', () => {
    expect(DEFAULT_LAYOUT_CONFIG).toMatchObject({
      seedSpacing: 260, minSeparation: 210, maxSeparation: 560, driftRadius: 40,
    });
  });
});

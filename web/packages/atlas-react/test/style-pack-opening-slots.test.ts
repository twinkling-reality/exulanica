/**
 * Window slots, held to what the facade records state by arithmetic of this test's own: one slot per
 * bay per storey a facade's grid lists, as wide as the grid's opening, as deep as its reveal, as tall
 * as its jambs (an arched head's rise stays out of the slot), set into the wall half that depth from
 * the tier edge the facade stands on, and facing out of the building.
 */
import { describe, expect, it } from 'vitest';
import { bakeTile, decodeOwd } from '@exulanica/loom-tess/core';
import { openingSlots } from '../src/playcanvas/style-pack/opening-slots.js';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
// Relative to web/, where the suite runs.
const fixtureBytes = (): Uint8Array => new Uint8Array(readFileSync('packages/loom-tess/test/fixtures/tile-conformance.json'));
const nodeSha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');

describe('the window slots of a baked tile', () => {
  it('give one slot per opening the facades the tile owns state, at the opening\'s size and place', async () => {
    const { container } = await bakeTile(fixtureBytes(), nodeSha256);
    const records = decodeOwd(container).header.records;
    const slots = openingSlots(records);
    const owned = records.filter((r) => r.kind === 'city.facade' && r.membership === 'owned');
    const massings = new Map(records.filter((r) => r.kind === 'city.massing').map((r) => [r.fields['identity'] as string, r.fields as any]));
    let expected = 0;
    let arched = 0;
    for (const record of owned) {
      const facade = record.fields as any;
      const mine = slots.filter((slot) => slot.facadeIdentity === facade.identity);
      const perGrid = facade.openings.map((grid: any) => facade.bays.count * grid.storeys.length);
      expected += perGrid.reduce((a: number, b: number) => a + b, 0);
      if (facade.openings.length === 0) continue;
      const grid = facade.openings[0];
      // The tier edge the facade stands on, from its building's own ring.
      const ring = massings.get(facade.building_identity).tiers[facade.tier_ordinal].ring_mm;
      const from = ring[facade.edge_ordinal];
      const to = ring[(facade.edge_ordinal + 1) % ring.length];
      const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
      for (const slot of mine) {
        expect(slot.boxMm[0]).toBe(grid.width_mm);
        expect(slot.boxMm[1]).toBe(grid.reveal_depth_mm);
        expect(slot.boxMm[2]).toBe(grid.height_mm);
        if (grid.head_rise_mm > 0) arched += 1;
        // Distance from the edge's line, on the inside: half the reveal.
        const cross = ((to[0] - from[0]) * (slot.positionMm[1] - from[1]) - (to[1] - from[1]) * (slot.positionMm[0] - from[0])) / length;
        expect(cross).toBeCloseTo(grid.reveal_depth_mm / 2, 6);
        // The front is a unit vector across the edge, to its right.
        expect(slot.front[0] * (to[0] - from[0]) + slot.front[1] * (to[1] - from[1])).toBeCloseTo(0, 6);
        expect(Math.hypot(...slot.front)).toBeCloseTo(1, 12);
      }
    }
    expect(expected).toBeGreaterThan(0);
    // The fixture's arched heads (a 250 mm rise) are among the slots measured.
    expect(arched).toBeGreaterThan(0);
    expect(slots).toHaveLength(expected);
    expect(new Set(slots.map((slot) => slot.identity)).size).toBe(slots.length);
  }, 60_000);

  it('give none for a halo facade, so a building at a tile boundary is dressed once', async () => {
    const { container } = await bakeTile(fixtureBytes(), nodeSha256);
    const records = decodeOwd(container).header.records.map((r) => (r.kind === 'city.facade' ? { ...r, membership: 'halo' } : r));
    expect(openingSlots(records)).toHaveLength(0);
  }, 60_000);
});

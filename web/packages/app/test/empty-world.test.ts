// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '@exulanica/graph-client';
import { buildEmptyWorld } from '../src/ui/empty-world.js';

function snapshotWithIslands(count: number): GraphSnapshot {
  return {
    stateVersion: 11,
    entities: [],
    occurrences: [],
    islands: Array.from({ length: count }, (_, index) => ({
      islandId: `island-${index}`,
      captureIds: [`capture-${index}`],
      firstCapturedAtMs: null,
      lastCapturedAtMs: null,
      positionedCaptureCount: 0,
      spreadMetres: null,
      rung: null,
      rungCaptureCount: 0,
    })),
    matchProposals: [],
    neverSame: [],
    deletedEntityIds: [],
  };
}

describe('the empty authenticated world', () => {
  it('renders a semantic terminal state when withdrawal leaves no live islands', () => {
    const view = buildEmptyWorld(snapshotWithIslands(0));

    expect(view).not.toBeNull();
    expect(view?.matches('[role="status"][data-empty-world]')).toBe(true);
    // main.ts shows this only when no world opened, so that is what it says.
    expect(view?.querySelector('h1')?.textContent).toBe('Your world did not open');
    // The same surface as the sign-in screen and a refusal, so the three cannot drift apart.
    expect(view?.classList.contains('gate')).toBe(true);
    // One sentence. The photo panel mounted underneath this surface is what somebody does next,
    // so nothing here repeats it, and nothing explains storage policy to somebody with no photos.
    expect(view?.querySelectorAll('p, h1')).toHaveLength(1);
    // frontier-roadmap.md: a public surface names the product, never the runtime behind it.
    expect(view?.textContent ?? '').not.toMatch(/\bAtlas\b/u);
    // It never says or implies that anything of theirs was destroyed.
    expect(view?.textContent ?? '').not.toMatch(/deleted|removed|destroyed|erased|lost/iu);
  });

  it('leaves every non-empty graph to the Atlas renderer', () => {
    expect(buildEmptyWorld(snapshotWithIslands(1))).toBeNull();
  });
});

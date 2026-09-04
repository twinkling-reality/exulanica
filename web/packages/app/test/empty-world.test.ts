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
    expect(view?.querySelector('h1')?.textContent).toBe('No live memories are available');
    expect(view?.textContent).toContain('Source files retained by policy remain outside the Atlas');
  });

  it('leaves every non-empty graph to the Atlas renderer', () => {
    expect(buildEmptyWorld(snapshotWithIslands(1))).toBeNull();
  });
});

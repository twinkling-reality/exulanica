// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

const observed = vi.hoisted(() => ({ sourceOptions: null as Record<string, unknown> | null }));

vi.mock('../src/world-style-api.js', () => ({
  WorldStyleContractError: class WorldStyleContractError extends Error {},
  WorldStyleClient: class WorldStyleClient {
    async connect() {
      const current = {
        versionId: 'style-saved',
        topologyDigest: 'style-topology',
        globalStyle: {
          profileId: 'origin-landscape', profileVersion: 1, parameters: {},
        },
      };
      return { state: { currentTopologyDigest: 'style-topology', current }, versions: [current] };
    }
  },
}));

vi.mock('../src/source-media-api.js', () => ({
  SourceMediaClient: class SourceMediaClient {
    constructor(options: Record<string, unknown>) { observed.sourceOptions = options; }
    async load() { return { catalog: new Map(), issues: [], dispose: vi.fn() }; }
  },
}));

import { createSessionState } from '../src/composition/session-state.js';
import { openWorldEntryContext } from '../src/composition/session-and-geometry.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

describe('saved world source wiring', () => {
  beforeEach(() => { observed.sourceOptions = null; });

  it('addresses source media through the saved structural snapshot', async () => {
    const state = createSessionState();
    state.credentials = { baseUrl: 'https://exulanica.test/api', token: 'private' };
    const entry: SavedWorldEntry = {
      entryId: 'entry-1', worldId: 'world:saved', title: 'Saved world', sourceKind: 'personal',
      sourceSnapshotId: 'snapshot-saved', sourceSnapshotSha256: 'a'.repeat(64),
      authoredScene: null, authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64),
      authoredEditSeq: 0, currentAuthoredStateSha256: 'b'.repeat(64),
      currentAuthoredEditSeq: 0, styleVersionId: 'style-saved', revision: 1,
      availability: 'available', unavailableReason: null, sourceAttachments: [],
      createdAt: '2026-09-20T00:00:00Z', updatedAt: '2026-09-20T00:00:00Z',
    };

    await openWorldEntryContext(state, entry);

    expect(observed.sourceOptions).toMatchObject({
      worldId: 'world:saved', sourceSnapshotId: 'snapshot-saved',
    });
  });
});

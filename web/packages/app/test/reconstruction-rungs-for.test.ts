import { describe, expect, it } from 'vitest';
import { sceneDisplayFrame } from '@exulanica/atlas-core';
import type { ReconstructionSceneRecord } from '@exulanica/graph-client';
import { reconstructionRungsFor } from '../src/composition/session-and-geometry.js';

/** The first personal place as the graph now sends it: recorded 4, three unplaced maps. */
const unposed: ReconstructionSceneRecord = {
  sceneId: 'scene-1', islandId: 'region-1', generatedGeometry: [],
  memberDigest: '1'.repeat(64), poseReceiptSha256: '2'.repeat(64), placementReceiptSha256: '3'.repeat(64),
  gateDigest: '4'.repeat(64), recordedRung: 4, recordedReasons: [], displayedRung: 3, displayReasons: [],
  memberCount: 3, registeredMemberCount: 0, receiptState: 'available', placementState: 'none_placed',
  renderingSubstrate: 'unposed_point_maps', hiddenPersonCount: 0, maskedMemberCount: 0, members: [],
};

const frame = sceneDisplayFrame(
  [{ position: [0, 1.6, 0], forward: [0, 0, -1], up: [0, 1, 0] },
    { position: [0, 1.6, 0], forward: [-1, 0, 0], up: [0, 1, 0] }],
  [[-3, 0, -8], [4, 2, -1]],
);

describe('reconstructionRungsFor', () => {
  it('shows unposed depth at rung 3 whatever the pose recorded, and never claims recovered cameras', () => {
    const [row] = reconstructionRungsFor([unposed], new Map([['scene-1', 'unposed_point_maps']]), new Set(),
      new Map([['scene-1', frame]]));
    expect(row!.recordedRung).toBe(4);
    expect(row!.displayedRung).toBe(3);
    expect(row!.renderingSubstrate).toBe('unposed_point_maps');
    expect(row!.reasons.join(' ')).not.toContain('recovered cameras');
    expect(row!.reasons.join(' ')).toContain('no photograph’s position was recovered');
  });

  it('falls to rung 4 when the browser could draw none of it', () => {
    const [row] = reconstructionRungsFor([unposed], new Map());
    expect(row!.displayedRung).toBe(4);
    expect(row!.renderingSubstrate).toBe('source_photographs');
  });
});

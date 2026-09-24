import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../src/index.js';

/**
 * A scene joined where its photographs were taken reaches the client as the server wrote it: the
 * record's state and residuals on the scene, each member's measured transform beside its depth,
 * and nothing at all from a server that sends neither.
 */

const MATRIX = [
  0.866, 0, -0.51, 0,
  0, 0.99, 0, 0,
  0.495, 0, 0.8925, 0,
  0, 0, 0, 1,
];

function scene(extra: Record<string, unknown>, member: Record<string, unknown>) {
  return {
    scene_id: 'scene-1',
    member_digest: '1'.repeat(64),
    pose_receipt_sha256: '2'.repeat(64),
    placement_receipt_sha256: '3'.repeat(64),
    gate_digest: '4'.repeat(64),
    recorded_rung: 4,
    recorded_reasons: [],
    displayed_rung: 3 as const,
    display_reasons: [],
    member_count: 2,
    registered_member_count: 0,
    receipt_state: 'available' as const,
    placement_state: 'none_placed' as const,
    rendering_substrate: 'unposed_point_maps' as const,
    members: [
      { capture_id: 'c1', ordinal: 0, registered: false, exclusion_reason: 'pose-not-registered', placement: null, ...member },
      { capture_id: 'c2', ordinal: 1, registered: false, exclusion_reason: 'pose-not-registered', placement: null },
    ],
    ...extra,
  };
}

function adapt(row: ReturnType<typeof scene>) {
  return adaptSnapshot({
    state_version: 1, entities: [], occurrences: [], proposals: [], scene_groups: [],
    reconstruction_scenes: [row] as never, never_same: [], deleted_entity_ids: [],
  }).reconstructionScenes![0]!;
}

describe('a standpoint scene on the wire', () => {
  it('carries the record and each member’s measured transform, renamed and unchanged', () => {
    const adapted = adapt(scene({
      standpoint: {
        artifact_id: 'artifact-s',
        content_sha256: '5'.repeat(64),
        state: 'joined',
        member_count: 2,
        joined_member_count: 1,
        reference_capture_id: 'c1',
        rotation_residual_max_millidegrees: 40,
        scale_residual_max_ppm: 3000,
        up_method: 'camera-horizontal-axes',
        implied_roll_max_millidegrees: 900,
        excluded: [{ capture_id: 'c2', reason: 'insufficient_overlap' }],
      },
    }, {
      standpoint_placement: { scene_from_opm_row_major: MATRIX, depth_scale: 1.02, lateral_scale: 0.97 },
    }));
    expect(adapted.standpoint).toEqual({
      artifactId: 'artifact-s',
      contentSha256: '5'.repeat(64),
      state: 'joined',
      memberCount: 2,
      joinedMemberCount: 1,
      referenceCaptureId: 'c1',
      rotationResidualMaxMillidegrees: 40,
      scaleResidualMaxPpm: 3000,
      upMethod: 'camera-horizontal-axes',
      impliedRollMaxMillidegrees: 900,
      excluded: [{ captureId: 'c2', reason: 'insufficient_overlap' }],
    });
    expect(adapted.members[0]!.standpointPlacement)
      .toEqual({ sceneFromOpmRowMajor: MATRIX, depthScale: 1.02, lateralScale: 0.97 });
    expect(adapted.members[1]!.standpointPlacement).toBeNull();
  });

  it('reads a server that sends no standpoint as having none', () => {
    const adapted = adapt(scene({}, {}));
    expect(adapted.standpoint).toBeNull();
    expect(adapted.members.map((member) => member.standpointPlacement)).toEqual([null, null]);
  });
});

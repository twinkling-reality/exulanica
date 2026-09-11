// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  atlasVec3,
  islandId as toIslandId,
  localVec3,
  makeIsland,
  placement,
  type Island,
} from '@exulanica/atlas-core';
import { calibratedCameraFrustum, type SceneInspectionView } from '@exulanica/atlas-react/playcanvas';
import type { GraphSnapshot, OccurrenceRecord, ReconstructionSceneRecord } from '@exulanica/graph-client';

import { SegmentOverlayRuntime, type SegmentOverlayEngine } from '../../atlas-react/src/playcanvas/atlas-binding.js';
import {
  SEGMENT_PICK_TOLERANCE_CANVAS_PX,
  bindSegments,
  classifySamples,
  colourKeyOf,
  createSegmentSession,
  mountSegments,
  pickSegmentSample,
  planSegmentTints,
  projectToCanvas,
  segmentColor,
  segmentGrid,
  segmentPalette,
  segmentsFirst,
  type DrawnScene,
  type MountedSegments,
  type SegmentPickCamera,
  type SegmentsDependencies,
} from '../src/composition/segments.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { mountWritePath } from '../src/composition/write-path.js';
import { PREVIEW_GRAPH, PREVIEW_IDS } from '../src/dev/preview-graph.js';
import type { EvidenceCache } from '../src/evidence.js';
import { SegmentsUnavailable, parseSceneSegments, type SceneSegments } from '../src/scene-segments-api.js';
import { openSession } from '../src/session.js';
import type { CompanionStage } from '../src/ui/companion-stage.js';
import { buildDetail } from '../src/ui/detail.js';

/**
 * The scene segments surface, from the outside.
 *
 * Four promises are tested here, each in the form the brief states it. A segment's colour is a
 * property of its entity and nothing else. With the overlay off, the renderer is not called at all
 * and a click in the inspector is click-to-evidence exactly as before. A click resolves to a segment
 * first, within a stated eight pixels and through the projection the renderer draws with, and only
 * then falls back. And naming a segment is the Index's own flow: the same draft, the same
 * confirmation panel, and nothing sent until Confirm, which is checked against the real session,
 * the real gate and the real commit transport over a scripted `fetch`.
 *
 * The artifact is the backend's: `graph-client/test/fixtures/scene-segments.json` is the body
 * `GET /scene-segments/{id}` serves for the scene the backend's own tests build, and it is parsed
 * here as it arrives. Segments are voxels in the scene frame, so the surface's one piece of
 * geometry is the lift's own rule for which cell a sample lands in, tested at the cell edges.
 */

// Read from the workspace root vitest runs in: under happy-dom, `import.meta.url` is not a file URL.
const FIXTURE = JSON.parse(readFileSync(
  `${process.cwd()}/packages/graph-client/test/fixtures/scene-segments.json`, 'utf8',
)) as Record<string, unknown>;

const SCENE_ID = '11111111-1111-4111-8111-111111111111';
const POINTS = '22222222-2222-4222-8222-222222222222';
const SUBJECT = '55555555-5555-4555-8555-555555555555';
const segmentId = (n: number) => n.toString(16).padStart(32, '0');
const REGION = toIslandId(PREVIEW_IDS.regionStudio);
const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
/** Five centimetres a cell, so each sample below sits alone in its own. */
const EDGE = 50_000;

const cellOf = (point: readonly number[]) => point.map((value) => Math.floor((value * 1_000_000) / EDGE));

function wire(segments: readonly Record<string, unknown>[], over: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    scene_id: SCENE_ID,
    state: 'available',
    reason: null,
    artifact: { artifact_id: '66666666-6666-4666-8666-666666666666', content_sha256: 'f'.repeat(64), byte_size: 100 },
    pose_receipt_sha256: 'b'.repeat(64),
    placement_receipt_sha256: 'c'.repeat(64),
    gate_receipt_sha256: 'd'.repeat(64),
    grid: { frame: 'scene', voxel_size_microunits: EDGE },
    policy: { person_segments: 'reviewed-region-with-subject-and-shown-consent-only' },
    segments,
    withheld_segment_count: 0,
    stale_inputs: [],
    ...over,
  };
}

const votes = { views: 4, min: 2, median: 3, max: 4, fraction_min_millionths: 500000, fraction_median_millionths: 750000 };

function segment(n: number, voxels: readonly (readonly number[])[], over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    segment_id: segmentId(n),
    kind: 'object',
    label: 'chair',
    subject_id: null,
    display_name: null,
    voxel_count: voxels.length,
    voxels,
    bounds_microunits: { min: [0, 0, 0], max: [1, 1, 1] },
    centroid_microunits: [0, 0, 0],
    samples: { point_map: 12, gaussian: 0 },
    votes,
    regions: [{ capture_id: PREVIEW_IDS.captureStudio, kind: 'object_mask', span_id: PREVIEW_IDS.spanStudioChair, region_key: null, samples: 12 }],
    occurrence_ids: [],
    ...over,
  };
}

const person = (n: number, voxels: readonly (readonly number[])[], displayName: string | null) => segment(n, voxels, {
  kind: 'person', label: null, subject_id: SUBJECT, display_name: displayName,
  regions: [{ capture_id: PREVIEW_IDS.captureStudio, kind: 'person_region', span_id: null, region_key: 'a'.repeat(64), samples: 9 }],
});

const RECORD = {
  sceneId: SCENE_ID,
  islandId: REGION,
  memberDigest: 'a'.repeat(64),
  poseReceiptSha256: 'b'.repeat(64),
  placementReceiptSha256: 'c'.repeat(64),
  // The gate DECISION's digest, which is never the gate receipt's content hash the artifact names.
  gateDigest: '9'.repeat(64),
  trainedGeometry: null,
  members: [{ captureId: PREVIEW_IDS.captureStudio, placement: { artifactId: POINTS, contentSha256: 'e'.repeat(64), sceneFromOpmRowMajor: IDENTITY } }],
} as unknown as ReconstructionSceneRecord;

const DRAWN: DrawnScene = {
  sceneId: SCENE_ID, islandId: REGION,
  assets: [{ artifactId: POINTS, kind: 'point_map', sampleCount: 6, drawnSceneFromLocal: IDENTITY }],
};

// -- the artifact -----------------------------------------------------------------------------------

describe('the published scene segments body', () => {
  it('reads the backend fixture as it is served: a person by subject and no name, an object by label', () => {
    const parsed = parseSceneSegments(FIXTURE);
    expect(parsed.state).toBe('available');
    expect(parsed.voxelSizeMicrounits).toBe(459682);
    expect(parsed.withheldSegmentCount).toBe(0);
    const [someone, sign] = parsed.segments;
    expect([someone!.kind, someone!.label, someone!.displayName]).toEqual(['person', null, null]);
    expect(someone!.subjectId).toMatch(/^[0-9a-f-]{36}$/);
    expect(someone!.voxels.length).toBe(45 * 3);
    expect([sign!.kind, sign!.label, sign!.subjectId]).toEqual(['object', 'trail sign', null]);
    expect(sign!.occurrenceIds).toHaveLength(3);
    expect(sign!.votes).toEqual({ views: 3, min: 2, median: 3, max: 3, fractionMinMillionths: 666666, fractionMedianMillionths: 1000000 });
  });

  it('ignores a field the server adds, and refuses one it renamed, retyped or mixed', () => {
    expect(parseSceneSegments({ ...wire([segment(1, [[0, 0, 0]])]), a_later_field: true }).segments).toHaveLength(1);
    const refuse = (value: unknown) => expect(() => parseSceneSegments(value)).toThrow(SegmentsUnavailable);
    refuse({ ...wire([]), schema_version: 2 });
    refuse(wire([segment(1, [[0, 0, 0]], { kind: 'person', label: 'person', subject_id: SUBJECT })]));
    refuse(wire([segment(1, [[0, 0, 0]], { subject_id: SUBJECT })]));
    refuse(wire([segment(1, [[0, 0, 0]], { voxel_count: 2 })]));
    refuse(wire([segment(1, [[0, 0, 0]], { votes: { ...votes, min: 4 } })]));
    refuse(wire([segment(1, [[0, 0, 0]])], { state: 'stale' }));
    refuse(wire([segment(1, [[0, 0, 0]])], { grid: null }));
    refuse(wire([segment(1, [[0, 0, 0]]), segment(1, [[1, 0, 0]])]));
    refuse(wire([], { grid: { frame: 'display', voxel_size_microunits: EDGE } }));
    expect(() => parseSceneSegments(wire([]), '44444444-4444-4444-8444-444444444444')).toThrow(/different scene/);
  });

  it('reads a scene with no segments to give, with its reason', () => {
    const parsed = parseSceneSegments(wire([], { state: 'stale', reason: 'A region moved.', stale_inputs: ['person_region'], grid: null }));
    expect([parsed.state, parsed.reason, parsed.staleInputs]).toEqual(['stale', 'A region moved.', ['person_region']]);
  });
});

// -- the voxel rule ---------------------------------------------------------------------------------

describe('a drawn sample is tinted by the cell the lift would put it in', () => {
  it('floors each axis at the cell edge, the way `_voxels` does, negative coordinates included', () => {
    const [a, b] = parseSceneSegments(wire([segment(1, [[2, 0, -1]]), segment(2, [[1, 0, -1]])])).segments;
    const grid = segmentGrid([a!, b!], new Map([[a!.segmentId, 1], [b!.segmentId, 2]]), EDGE)!;
    const at = (x: number, z: number) => classifySamples(Float32Array.from([x, 0.01, z]), IDENTITY, grid)[0];
    expect(at(0.1, -0.01)).toBe(1);
    expect(at(0.0999, -0.01)).toBe(2);
    expect(at(0.1, 0)).toBe(0);
    expect(at(0.15, -0.05)).toBe(0);
  });

  it('places samples with the graph’s own transform, not the display frame the renderer draws with', () => {
    const local = Float32Array.from([0.01, 0.01, 0.01, 1.01, 0.01, 0.01]);
    const segments = parseSceneSegments(wire([segment(1, [cellOf([0.01, 0.01, 0.01])])]));
    const displayed = { ...DRAWN.assets[0]!, sampleCount: 2, drawnSceneFromLocal: [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] };
    const bound = bindSegments(segments, { ...DRAWN, assets: [displayed] }, RECORD, false);
    const plan = planSegmentTints(segments, bound, () => local);
    expect(plan.tints.map((tint) => [tint.slot, [...tint.indices]])).toEqual([[1, [0]]]);
  });

  it('gives a cell two segments share to the one listed first, and counts it', () => {
    const shared = [3, 3, 3];
    const [first, second] = parseSceneSegments(wire([person(1, [shared], null), segment(2, [shared, [4, 3, 3]])])).segments;
    const grid = segmentGrid([first!, second!], new Map([[first!.segmentId, 1], [second!.segmentId, 2]]), EDGE)!;
    expect(grid.contested).toBe(1);
    const centre = (cell: readonly number[]) => cell.map((index) => ((index + 0.5) * EDGE) / 1_000_000);
    expect([...classifySamples(Float32Array.from([...centre(shared), ...centre([4, 3, 3])]), IDENTITY, grid)]).toEqual([1, 2]);
  });

  it('tints every sample that lies in the published fixture’s own cells as that segment', () => {
    const parsed = parseSceneSegments(FIXTURE);
    const slots = new Map(parsed.segments.map((item, index) => [item.segmentId, index + 1]));
    const grid = segmentGrid(parsed.segments, slots, parsed.voxelSizeMicrounits!)!;
    const edge = parsed.voxelSizeMicrounits! / 1_000_000;
    for (const [index, item] of parsed.segments.entries()) {
      const centres: number[] = [];
      for (let at = 0; at < item.voxels.length; at += 3) centres.push(...[0, 1, 2].map((axis) => (item.voxels[at + axis]! + 0.5) * edge));
      const classified = classifySamples(Float32Array.from(centres), IDENTITY, grid);
      // Every cell of the first segment is its own; a later one may lose a shared cell to it.
      if (index === 0) expect(new Set(classified)).toEqual(new Set([1]));
      expect(classified.filter((slot) => slot === index + 1).length).toBe(item.voxels.length / 3 - (index === 0 ? 0 : grid.contested));
    }
  });
});

// -- colour -----------------------------------------------------------------------------------------

describe('a segment wears its entity colour, and nothing else decides it', () => {
  const MARA = '00000000-0000-4000-8000-000000000101';

  it('is the same colour for the same entity on every call, pinned so a build cannot move it', () => {
    expect(segmentColor(MARA)).toEqual(segmentColor(MARA));
    expect(segmentColor(MARA).map((channel) => Number(channel.toFixed(4)))).toEqual([0.1714, 0.7349, 0.9079]);
    for (const channel of segmentColor('any entity at all')) {
      expect(channel).toBeGreaterThanOrEqual(0);
      expect(channel).toBeLessThanOrEqual(1);
    }
  });

  it('keys a person by subject, an object by its linked entity, and otherwise by the segment', () => {
    const snapshot = { occurrences: [{ occurrenceId: PREVIEW_IDS.occurrenceStudioPlace, entityId: PREVIEW_IDS.entityGlasshouse }] } as unknown as GraphSnapshot;
    const [someone, linked, bare] = parseSceneSegments(wire([
      person(1, [[0, 0, 0]], null),
      segment(2, [[1, 0, 0]], { occurrence_ids: [PREVIEW_IDS.occurrenceStudioPlace] }),
      segment(3, [[2, 0, 0]]),
    ])).segments;
    expect(colourKeyOf(someone!, snapshot)).toBe(SUBJECT);
    expect(colourKeyOf(linked!, snapshot)).toBe(PREVIEW_IDS.entityGlasshouse);
    expect(colourKeyOf(bare!, snapshot)).toBe(segmentId(3));
  });

  it('does not depend on the other segments or their order', () => {
    const snapshot = { occurrences: [] } as unknown as GraphSnapshot;
    const parsed = parseSceneSegments(FIXTURE);
    const colours = (items: SceneSegments['segments']) => {
      const slotOf = new Map(items.map((item, index) => [item.segmentId, index + 1]));
      const palette = segmentPalette({ slotOf, segmentOfSlot: new Map(items.map((item, index) => [index + 1, item])) }, null, snapshot);
      return new Map(items.map((item) => [item.segmentId, palette.get(slotOf.get(item.segmentId)!)!.slice(0, 3)]));
    };
    const forward = colours(parsed.segments);
    const backward = colours([...parsed.segments].reverse());
    for (const [id, colour] of forward) expect(backward.get(id)).toEqual(colour);
  });

  it('spreads identifiers that differ only in their last digits, which the browser showed as one green', () => {
    const colours = ['101', '102', '103', '104', '105'].map((tail) => segmentColor(`00000000-0000-4000-8000-000000000${tail}`));
    for (let i = 0; i < colours.length; i += 1) {
      for (let j = i + 1; j < colours.length; j += 1) {
        const [a, b] = [colours[i]!, colours[j]!];
        expect(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])).toBeGreaterThan(0.05);
      }
    }
  });
});

// -- projection, tolerance and the order a click is answered in -------------------------------------

function cross(a: readonly number[], b: readonly number[]): number[] {
  return [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];
}
function unit(v: readonly number[]): number[] {
  const length = Math.hypot(...v);
  return v.map((value) => value / length);
}

/** The pipeline as matrices, the way the engine builds it: look-at, then perspective or frustum. */
function throughMatrices(camera: SegmentPickCamera, canvas: { width: number; height: number }, point: readonly number[]) {
  const near = 0.08;
  const far = 1200;
  const z = unit(camera.forward.map((value) => -value));
  const x = unit(cross(camera.up, z));
  const y = cross(z, x);
  const d = point.map((value, index) => value - camera.position[index]!);
  const view = [x, y, z].map((axis) => axis.reduce((sum, value, index) => sum + value * d[index]!, 0));
  const aspect = canvas.width / canvas.height;
  let projection: number[][];
  if (camera.calibration === null) {
    const f = 1 / Math.tan((camera.fovYDeg * Math.PI) / 360);
    projection = [[f / aspect, 0, 0, 0], [0, f, 0, 0], [0, 0, (far + near) / (near - far), (2 * far * near) / (near - far)], [0, 0, -1, 0]];
  } else {
    const { left: l, right: r, bottom: b, top: t } = calibratedCameraFrustum(camera.calibration, aspect, near);
    projection = [
      [(2 * near) / (r - l), 0, (r + l) / (r - l), 0],
      [0, (2 * near) / (t - b), (t + b) / (t - b), 0],
      [0, 0, -(far + near) / (far - near), (-2 * far * near) / (far - near)],
      [0, 0, -1, 0],
    ];
  }
  const clip = projection.map((row) => row.reduce((sum, value, index) => sum + value * [...view, 1][index]!, 0));
  return { x: ((clip[0]! / clip[3]! + 1) / 2) * canvas.width, y: ((1 - clip[1]! / clip[3]!) / 2) * canvas.height };
}

const CANVAS = { width: 800, height: 600 };
const AHEAD: SegmentPickCamera = { position: [0, 1.6, 5], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 60, calibration: null };

/** The atlas point that projects to a canvas pixel at a given depth, for the camera above. */
function pointAt(px: number, py: number, depth: number): [number, number, number] {
  const f = 1 / Math.tan(Math.PI / 6);
  const ndcX = (2 * px) / CANVAS.width - 1;
  const ndcY = 1 - (2 * py) / CANVAS.height;
  return [(ndcX * (CANVAS.width / CANVAS.height) / f) * depth, 1.6 + (ndcY / f) * depth, 5 - depth];
}

describe('a click is answered by a segment first, within a stated tolerance', () => {
  it('projects through the same camera the renderer draws with', () => {
    const tilted: SegmentPickCamera = {
      position: [3, 2, -1], forward: unit([-0.4, -0.2, -1]) as [number, number, number],
      up: unit([0.1, 1, 0]) as [number, number, number], fovYDeg: 47, calibration: null,
    };
    const calibrated: SegmentPickCamera = {
      ...tilted,
      calibration: { model: 'SIMPLE_RADIAL', width: 3060, height: 4080, fx: 3100, fy: 3120, cx: 1490, cy: 2070, parameters: [0.01] },
    };
    for (const camera of [tilted, calibrated]) {
      for (const point of [[0, 0, -6], [1.5, 2.2, -4], [2.8, 1.9, -3.5], [-2, -1, -9]] as const) {
        const mine = projectToCanvas(camera, CANVAS, point)!;
        const reference = throughMatrices(camera, CANVAS, point);
        expect(mine.x).toBeCloseTo(reference.x, 6);
        expect(mine.y).toBeCloseTo(reference.y, 6);
      }
    }
    expect(projectToCanvas(AHEAD, CANVAS, [0, 1.6, 6])).toBeNull();
  });

  it('selects within eight screen pixels and refuses beyond them', () => {
    expect(SEGMENT_PICK_TOLERANCE_CANVAS_PX).toBe(8);
    const asset = (px: number) => [{
      artifactId: POINTS, indices: Uint32Array.from([4]), slots: Uint8Array.from([1]),
      positions: Float32Array.from(pointAt(px, 300, 4)),
    }];
    expect(pickSegmentSample(asset(407.9), AHEAD, CANVAS, { x: 400, y: 300 })?.pixelDistance).toBeCloseTo(7.9, 3);
    expect(pickSegmentSample(asset(408.1), AHEAD, CANVAS, { x: 400, y: 300 })).toBeNull();
  });

  it('takes the front sample among those as near as the nearest, and never a closer one further out', () => {
    const positions = Float32Array.from([...pointAt(402, 300, 5), ...pointAt(403, 300, 3), ...pointAt(406.5, 300, 1)]);
    const pick = pickSegmentSample([{ artifactId: POINTS, indices: Uint32Array.from([0, 1, 2]), slots: Uint8Array.from([1, 2, 3]), positions }],
      AHEAD, CANVAS, { x: 400, y: 300 });
    expect(pick?.slot).toBe(2);
  });

  it('asks the segment before the evidence, and the evidence only when no segment answered', () => {
    const order: string[] = [];
    const status = {
      inspectorRoot: document.createElement('aside'),
      resolveEvidenceAt: (x: number, y: number) => { order.push(`evidence ${x},${y}`); },
    };
    let answer = true;
    const wrapped = segmentsFirst(status, (x, y) => { order.push(`segment ${x},${y}`); return answer; });
    wrapped.resolveEvidenceAt(10, 20);
    answer = false;
    wrapped.resolveEvidenceAt(30, 40);
    expect(order).toEqual(['segment 10,20', 'segment 30,40', 'evidence 30,40']);
    expect(wrapped.inspectorRoot).toBe(status.inspectorRoot);
  });
});

// -- what an artifact is bound to ------------------------------------------------------------------

describe('segments are refused unless they describe the geometry drawn here', () => {
  const parsed = parseSceneSegments(wire([segment(1, [[0, 0, 0]])]));

  it('binds a drawn asset through its graph placement when the receipts agree', () => {
    const bound = bindSegments(parsed, DRAWN, RECORD, false);
    expect(bound.assets.map((item) => [item.asset.artifactId, item.sceneFromLocal])).toEqual([[POINTS, IDENTITY]]);
    expect(bound.notices).toEqual([]);
  });

  it('refuses the whole artifact when the scene or a receipt differs', () => {
    const differ = (over: Partial<ReconstructionSceneRecord>) => bindSegments(parsed, DRAWN, { ...RECORD, ...over }, false);
    expect(differ({ poseReceiptSha256: 'f'.repeat(64) }).assets).toEqual([]);
    expect(differ({ placementReceiptSha256: 'f'.repeat(64) }).assets).toEqual([]);
    expect(bindSegments(parsed, DRAWN, undefined, false).assets).toEqual([]);
    expect(bindSegments(parsed, { ...DRAWN, sceneId: '77777777-7777-4777-8777-777777777777' }, RECORD, false).notices[0]).toMatch(/different scene/);
  });

  it('does not compare the gate decision digest with the gate receipt hash', () => {
    // Two different digests of two different things, which disagree for every real scene: on the
    // volcanic scene the graph said `1eb52108...` and the artifact `57189a4b...`. The route refuses
    // segments bound to another gate receipt before any reach this side.
    expect(RECORD.gateDigest).not.toBe(parsed.gateReceiptSha256);
    const bound = bindSegments(parsed, DRAWN, RECORD, false);
    expect(bound.assets.map((item) => item.asset.artifactId)).toEqual([POINTS]);
    expect(bound.notices).toEqual([]);
  });

  it('skips an asset the graph holds no placement for, and says so', () => {
    const bound = bindSegments(parsed, DRAWN, { ...RECORD, members: [] } as unknown as ReconstructionSceneRecord, false);
    expect(bound.assets).toEqual([]);
    expect(bound.notices[0]).toMatch(/no placement for drawn asset/);
  });

  it('binds the preview through its drawn transform, and says nothing was compared', () => {
    const preview = bindSegments(parsed, { ...DRAWN, sceneId: 'legacy:x' }, undefined, true);
    expect(preview.assets).toHaveLength(1);
    expect(preview.verified).toBe(false);
    expect(preview.notices[0]).toMatch(/No receipt was compared/);
  });
});

// -- the surface -----------------------------------------------------------------------------------

const region = (): Island => makeIsland({
  islandId: REGION,
  createdAt: 0,
  placement: placement(atlasVec3(0, 0, 0), 0, 1),
  rung: 3,
  scaleIsMetric: false,
  footprintRadiusLocal: 20,
  viewpointLocal: localVec3(0, 0, 0),
  anchors: [],
  layoutEntities: new Set(),
});

const INSPECTING: SceneInspectionView = {
  id: 'view-1', sceneId: SCENE_ID, islandId: REGION, kind: 'source-camera', artifactIds: [POINTS],
  captureIds: [PREVIEW_IDS.captureStudio], poseReceiptSha256: null, calibration: null, projection: 'opm-estimate',
  position: [0, 1.6, 5], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 60, sourceAspect: 4 / 3,
};

/** Six drawn samples, each alone in its cell, at known pixels from the inspection camera. */
const SAMPLES = [
  pointAt(300, 300, 5), pointAt(320, 300, 5), pointAt(500, 300, 5),
  pointAt(520, 300, 5), pointAt(600, 400, 5), pointAt(620, 400, 5),
];
const cells = (...indices: number[]) => indices.map((index) => cellOf(SAMPLES[index]!));

function fakeEngine(): SegmentOverlayEngine {
  return {
    maxTextureSize: 4096,
    texture: () => ({ texture: {}, write: () => undefined, destroy: () => undefined }),
    pointGroups: () => ({ setLens: () => undefined, destroy: () => undefined }),
  };
}

function harness(segments: SceneSegments, snapshot: GraphSnapshot, over: Partial<SegmentsDependencies> = {}) {
  const visual = {
    island: region(),
    entity: {},
    cloud: { pointCount: SAMPLES.length },
    pointMap: {
      sceneId: SCENE_ID, artifactId: POINTS, islandId: REGION, map: { position: Float32Array.from(SAMPLES.flat()) },
      sceneFromOpmRowMajor: IDENTITY, localUnitsToSceneUnits: 1,
    },
  };
  const overlay = new SegmentOverlayRuntime([visual as never], [], fakeEngine, {
    lensPrepared: () => false, settle: () => undefined, invalidate: () => undefined,
  });
  const apply = vi.spyOn(overlay, 'apply');
  const setPalette = vi.spyOn(overlay, 'setPalette');
  const binding = {
    islands: [visual],
    trainedScenes: [],
    scene: { islands: [visual.island] },
    inspectionView: null as SceneInspectionView | null,
    cameraPose: () => ({ position: atlasVec3(0, 1.6, 5), forward: atlasVec3(0, 0, -1) }),
    segmentOverlay: overlay,
    navigateToIsland: vi.fn(() => ({ ok: true })),
  };
  const canvas = document.createElement('canvas');
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) });
  const state = { atlas: { binding }, credentials: null, issued: 0 } as unknown as SessionState;
  const env = { preview: false, canvas } as unknown as AppEnvironment;
  const mounted = mountSegments({
    env,
    state,
    snapshot,
    segmentSession: createSegmentSession(),
    session: { stage: vi.fn(), stateVersion: () => snapshot.stateVersion },
    confirm: { root: document.createElement('aside'), show: vi.fn(), reportFailure: vi.fn(), hide: vi.fn() },
    hideOtherConfirms: vi.fn(),
    inspect: vi.fn(),
    showWorld: vi.fn(),
    showTravelStatus: vi.fn(),
    travelUsesReducedMotion: () => true,
    load: async () => segments,
    ...over,
  });
  document.body.append(mounted.root);
  return { mounted, binding, apply, setPalette, state };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const toggle = (mounted: MountedSegments) => mounted.root.querySelector<HTMLButtonElement>('.scene-segments-toggle')!.click();
const rows = (mounted: MountedSegments) => [...mounted.root.querySelectorAll<HTMLElement>('.scene-segment')];

function snapshotWith(entities: readonly Record<string, unknown>[] = [], occurrences: readonly Partial<OccurrenceRecord>[] = []): GraphSnapshot {
  return {
    stateVersion: 3, entities, occurrences, islands: [], reconstructionScenes: [RECORD],
    matchProposals: [], neverSame: [], deletedEntityIds: [],
  } as unknown as GraphSnapshot;
}

let mounted: MountedSegments | null = null;
beforeEach(() => { document.body.replaceChildren(); });
afterEach(() => { mounted?.dispose(); mounted = null; });

describe('with the overlay off, nothing changes', () => {
  it('makes no call on the renderer, and a click in the inspector is click-to-evidence', async () => {
    const h = harness(parseSceneSegments(wire([segment(1, cells(0, 1))])), snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    h.binding.inspectionView = INSPECTING;
    const evidence = vi.fn();
    segmentsFirst({ resolveEvidenceAt: evidence }, h.mounted.resolveAt).resolveEvidenceAt(300, 300);

    expect(h.apply).not.toHaveBeenCalled();
    expect(h.setPalette).not.toHaveBeenCalled();
    expect(evidence).toHaveBeenCalledWith(300, 300);
    expect(rows(h.mounted)).toEqual([]);
    expect(h.mounted.root.querySelector('.scene-segments-toggle')?.getAttribute('aria-pressed')).toBe('false');
  });

  it('switched on and off again, calls the renderer once to put the overlay up and once to take it down', async () => {
    const h = harness(parseSceneSegments(wire([segment(1, cells(0, 1))])), snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    expect(h.apply).toHaveBeenCalledTimes(1);
    const overlay = h.apply.mock.calls[0]![0]!;
    expect(overlay.islandId).toBe(REGION);
    expect(overlay.tints.map((tint) => [tint.slot, tint.artifactId, [...tint.indices]])).toEqual([[1, POINTS, [0, 1]]]);
    toggle(h.mounted);
    await settle();
    expect(h.apply.mock.calls.map((call) => call[0] === null)).toEqual([false, true]);
    expect(h.binding.segmentOverlay.report).toBeNull();
  });
});

describe('selecting a segment in the inspector', () => {
  async function inspecting() {
    const segments = parseSceneSegments(wire([
      segment(1, cells(0, 1)),
      segment(2, cells(2, 3), { label: 'lamp' }),
    ]));
    const h = harness(segments, snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    h.binding.inspectionView = INSPECTING;
    return h;
  }

  it('selects the segment under a tinted sample and does not ask for evidence', async () => {
    const h = await inspecting();
    const evidence = vi.fn();
    segmentsFirst({ resolveEvidenceAt: evidence }, h.mounted.resolveAt).resolveEvidenceAt(503, 302);
    expect(evidence).not.toHaveBeenCalled();
    const selected = h.mounted.root.querySelector<HTMLElement>('.scene-segment[aria-current="true"]');
    expect(selected?.textContent).toContain('lamp');
    expect(selected?.textContent).toMatch(/nearest tinted sample was 3\.6 screen pixels/);
    // Emphasis follows selection: the lamp at full strength, the chair receded.
    const palette = h.setPalette.mock.calls.at(-1)![0];
    expect([...palette.values()].map((colour) => colour[3])).toEqual([0.28, 1]);
  });

  it('falls back to click-to-evidence where no tinted sample is within eight pixels', async () => {
    const h = await inspecting();
    const evidence = vi.fn();
    segmentsFirst({ resolveEvidenceAt: evidence }, h.mounted.resolveAt).resolveEvidenceAt(410, 300);
    expect(evidence).toHaveBeenCalledWith(410, 300);
    expect(h.mounted.root.querySelector('.scene-segment[aria-current="true"]')).toBeNull();
  });

  it('highlights a segment while its row is pointed at, and lets go when the pointer leaves', async () => {
    const h = await inspecting();
    const lamp = rows(h.mounted).find((row) => row.textContent?.includes('lamp'))!;
    lamp.dispatchEvent(new MouseEvent('mouseenter'));
    expect([...h.setPalette.mock.calls.at(-1)![0].values()].map((colour) => colour[3])).toEqual([0.28, 1]);
    lamp.dispatchEvent(new MouseEvent('mouseleave'));
    expect([...h.setPalette.mock.calls.at(-1)![0].values()].map((colour) => colour[3])).toEqual([0.78, 0.78]);
  });

  it('travels to the segment region and emphasises it on arrival', async () => {
    const h = await inspecting();
    rows(h.mounted)[1]!.querySelector<HTMLButtonElement>('.scene-segment-travel')!.click();
    expect(h.binding.navigateToIsland).toHaveBeenCalledWith(REGION, true);
    expect(h.mounted.root.querySelector('.scene-segment[aria-current="true"]')?.textContent).toContain('lamp');
  });

  it('lists a segment whose cells hold nothing drawn here, and says why it is not tinted', async () => {
    const h = harness(parseSceneSegments(wire([segment(1, [[999, 999, 999]])])), snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    expect(rows(h.mounted)[0]!.textContent).toContain('Not tinted: no sample drawn here falls in any of its voxels.');
    expect(h.apply).not.toHaveBeenCalled();
  });
});

describe('a person segment', () => {
  async function showing(body: SceneSegments) {
    const h = harness(body, snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    rows(h.mounted)[0]!.querySelector<HTMLButtonElement>('.scene-segment-select')!.click();
    return h;
  }

  it('is unnamed unless the server sends a name, and says what consent lets it be shown', async () => {
    const h = await showing(parseSceneSegments(wire([person(1, cells(0), null)])));
    const text = h.mounted.root.textContent ?? '';
    expect(rows(h.mounted)[0]!.querySelector('.scene-segment-heading')?.textContent).toBe('Unnamed person');
    expect(text).toContain('presentation state is shown');
    expect(text).toContain('No naming receipt is held for this person, so no name is shown.');
    expect(text).toContain('the naming flow has nothing to name');
  });

  it('shows the name the server sends, and only while it sends it', async () => {
    const h = await showing(parseSceneSegments(wire([person(1, cells(0), 'Mara')])));
    expect(rows(h.mounted)[0]!.querySelector('.scene-segment-heading')?.textContent).toBe('Mara');
    expect(h.mounted.root.textContent).toContain('A naming receipt is held for this person');
  });

  it('counts the people the server withheld rather than drawing none and saying there were none', async () => {
    const h = await showing(parseSceneSegments(wire([segment(1, cells(0))], { withheld_segment_count: 2 })));
    expect(h.mounted.root.textContent).toContain('2 segments were withheld by a live consent check or the read policy');
  });
});

// -- naming, against the real session and a scripted server -----------------------------------------

describe('naming a segment is the Index naming flow, confirmed before it is committed', () => {
  const API = 'https://exulanica.test/api';
  const CHAIR = PREVIEW_IDS.occurrenceStudioChair;
  let requests: { method: string; path: string; body: unknown }[];
  let version: number;

  beforeEach(() => {
    requests = [];
    version = PREVIEW_GRAPH.state_version;
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      const path = new URL(url).pathname.replace(/^\/api/, '');
      const method = init.method ?? 'GET';
      requests.push({ method, path, body: init.body === undefined ? undefined : JSON.parse(String(init.body)) });
      if (method === 'GET' && path === '/graph') return json({ ...PREVIEW_GRAPH, state_version: version });
      if (method === 'POST' && path === '/identity/name') {
        version += 1;
        return json({ entity_id: '66666666-6666-4666-8666-666666666666', occurrence_id: CHAIR, display_name: 'Rattan chair' });
      }
      return json({ code: 'not_found', detail: 'not scripted' }, 404);
    }));
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  async function openFlow(occurrenceIds: readonly string[] = [CHAIR]) {
    const opened = await openSession({ baseUrl: API, token: 'token' });
    const snapshot = { ...opened.initial, reconstructionScenes: [RECORD] } as GraphSnapshot;
    const state = { atlas: null, credentials: null, issued: 0, snapshot, selected: null } as unknown as SessionState;
    const remount = vi.fn(async () => undefined);
    const detail = buildDetail({} as EvidenceCache, {
      onName: (occurrence) => writePath.propose(occurrence),
      onEvidenceOpened: () => undefined, onLocate: () => undefined, onClose: () => undefined,
    });
    const writePath = mountWritePath({
      env: { preview: false } as unknown as AppEnvironment,
      state,
      session: opened.session,
      snapshot,
      companionStage: () => ({ setState: vi.fn() }) as unknown as CompanionStage,
      detailRoot: () => detail.root,
      onConfirmVisibilityChange: () => undefined,
      remount,
    });
    document.body.append(detail.root, writePath.confirm.root);
    const segments = parseSceneSegments(wire([segment(1, cells(0, 1), { occurrence_ids: occurrenceIds })]));
    const h = harness(segments, snapshot, { session: opened.session, confirm: writePath.confirm });
    Object.assign(h.state, { snapshot, issued: 0 });
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    h.binding.inspectionView = INSPECTING;
    return { h, writePath, detail, snapshot, remount };
  }

  const nameSegment = (h: ReturnType<typeof harness>, name: string) => {
    rows(h.mounted)[0]!.querySelector<HTMLButtonElement>('.scene-segment-select')!.click();
    const form = h.mounted.root.querySelector<HTMLFormElement>('.scene-segment-name')!;
    form.querySelector('input')!.value = name;
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  };

  it('stages the Index draft, renders the same confirmation, and sends nothing until Confirm', async () => {
    const { h, writePath, detail, snapshot } = await openFlow();
    const occurrence = snapshot.occurrences.find((item) => item.occurrenceId === CHAIR)!;
    expect(occurrence.entityId).toBeNull();

    // The Index, naming the same detection with the same words.
    detail.showOccurrence(occurrence);
    detail.root.querySelector<HTMLInputElement>('.name-offer input')!.value = 'Rattan chair';
    detail.root.querySelector<HTMLFormElement>('.name-offer')!.dispatchEvent(new Event('submit', { cancelable: true }));
    const fromIndex = writePath.confirm.root.textContent;
    writePath.confirm.root.querySelector<HTMLButtonElement>('button.ghost')!.click();
    expect(writePath.confirm.root.hidden).toBe(true);

    nameSegment(h, 'Rattan chair');
    expect(writePath.confirm.root.hidden).toBe(false);
    expect(writePath.confirm.root.textContent).toBe(fromIndex);
    expect(requests.map((request) => `${request.method} ${request.path}`)).toEqual(['GET /graph']);

    writePath.confirm.root.querySelector<HTMLButtonElement>('button.primary')!.click();
    await vi.waitFor(() => expect(requests.some((request) => request.method === 'POST')).toBe(true));
    await settle();
    const posts = requests.filter((request) => request.method === 'POST');
    expect(posts).toEqual([{ method: 'POST', path: '/identity/name', body: { occurrence_id: CHAIR, display_name: 'Rattan chair' } }]);
  });

  it('commits nothing when the confirmation is cancelled', async () => {
    const { h, writePath, remount } = await openFlow();
    nameSegment(h, 'Rattan chair');
    writePath.confirm.root.querySelector<HTMLButtonElement>('button.ghost')!.click();
    await settle();
    expect(requests.filter((request) => request.method !== 'GET')).toEqual([]);
    expect(remount).not.toHaveBeenCalled();
  });

  it('re-reads the graph and remounts after the commit, as the Index does', async () => {
    const { h, writePath, remount } = await openFlow();
    nameSegment(h, 'Rattan chair');
    writePath.confirm.root.querySelector<HTMLButtonElement>('button.primary')!.click();
    await vi.waitFor(() => expect(remount).toHaveBeenCalledOnce());
    expect(requests.map((request) => `${request.method} ${request.path}`))
      .toEqual(['GET /graph', 'POST /identity/name', 'GET /graph', 'GET /graph']);
  });

  it('shows the graph’s name and offers no form for a segment whose detections are already linked', async () => {
    const { h } = await openFlow([PREVIEW_IDS.occurrenceStudioPlace]);
    rows(h.mounted)[0]!.querySelector<HTMLButtonElement>('.scene-segment-select')!.click();
    expect(h.mounted.root.querySelector('.scene-segment-name')).toBeNull();
    expect(rows(h.mounted)[0]!.querySelector('.scene-segment-heading')?.textContent).toBe('Glasshouse');
    expect(h.mounted.root.textContent).toContain('The graph names this chair Glasshouse.');
  });
});

describe('the scene segments stylesheet', () => {
  const css = readFileSync(`${process.cwd()}/packages/app/src/ui/scene-segments.css`, 'utf8');

  it('names no colour and no duration of its own', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toMatch(/\brgba?\(/i);
    expect(css).not.toMatch(/\bhsla?\(/i);
    expect(css).not.toMatch(/transition:[^;]*\b\d+(?:ms|s)\b/);
  });

  it('leaves the Index and the Map as the proof lens does', () => {
    expect(css).toContain("#shell:not([data-primary='world']) .scene-segments");
    expect(css).toContain("#shell[data-camera='map'] .scene-segments");
  });
});

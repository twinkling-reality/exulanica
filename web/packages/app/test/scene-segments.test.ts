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
  colourKeyOf,
  createSegmentSession,
  mountSegments,
  pickSegmentSample,
  planSegmentTints,
  projectToCanvas,
  segmentColor,
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
import { SEGMENTS_PROFILE, SegmentsUnavailable, parseSceneSegments, type SceneSegments } from '../src/scene-segments-api.js';
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
 */

// Read from the workspace root vitest runs in: under happy-dom, `import.meta.url` is not a file URL.
const FIXTURE = JSON.parse(readFileSync(
  `${process.cwd()}/packages/graph-client/test/fixtures/scene-segments.json`, 'utf8',
)) as Record<string, unknown>;

const SCENE_ID = '11111111-1111-4111-8111-111111111111';
const POINTS = '22222222-2222-4222-8222-222222222222';
const segmentId = (n: number) => `33333333-3333-4333-8333-${String(n).padStart(12, '0')}`;
const REGION = toIslandId(PREVIEW_IDS.regionStudio);

function wire(segments: readonly Record<string, unknown>[], over: Record<string, unknown> = {}) {
  return {
    profile: SEGMENTS_PROFILE,
    scene_id: SCENE_ID,
    bound_to: {
      member_digest: 'a'.repeat(64),
      pose_receipt_sha256: 'b'.repeat(64),
      placement_receipt_sha256: 'c'.repeat(64),
      region_digest: 'd'.repeat(64),
    },
    method: {
      masks: { model: 'facebook/sam2.1-hiera-tiny', revision: 'r1', licence: 'Apache-2.0' },
      boxes: null,
      projection: 'masked-geometry',
      views: 4,
    },
    assets: [{ artifact_id: POINTS, kind: 'point_map', content_sha256: 'e'.repeat(64), sample_count: 6 }],
    segments,
    ...over,
  };
}

const segment = (n: number, over: Record<string, unknown> = {}): Record<string, unknown> => ({
  segment_id: segmentId(n),
  entity_id: null,
  entity_class: 'object',
  label: 'chair',
  vote_count: 3,
  confidence: 'medium',
  occurrence_ids: [],
  person: null,
  samples: [{ artifact_id: POINTS, index_runs: [[0, 2]] }],
  ...over,
});

const RECORD = {
  sceneId: SCENE_ID,
  islandId: REGION,
  memberDigest: 'a'.repeat(64),
  poseReceiptSha256: 'b'.repeat(64),
  placementReceiptSha256: 'c'.repeat(64),
  trainedGeometry: null,
  members: [{ captureId: PREVIEW_IDS.captureStudio, placement: { artifactId: POINTS, contentSha256: 'e'.repeat(64) } }],
} as unknown as ReconstructionSceneRecord;

const DRAWN: DrawnScene = { sceneId: SCENE_ID, islandId: REGION, assets: [{ artifactId: POINTS, kind: 'point_map', sampleCount: 6 }] };

// -- the artifact -----------------------------------------------------------------------------------

describe('the segment artifact', () => {
  it('reads the provisional fixture: two bound assets, five segments, one person with consent and no name', () => {
    const parsed = parseSceneSegments(FIXTURE);
    expect(parsed.assets.map((asset) => [asset.kind, asset.sampleCount])).toEqual([['point_map', 190570], ['trained_geometry', 512]]);
    expect(parsed.segments.map((item) => item.label)).toEqual(['person', 'bicycle', 'paper bag', 'planter', 'glasshouse']);
    const person = parsed.segments[0]!;
    expect(person.person).toEqual({
      reviewState: 'screened', state: 'shown', consent: { presence: 'granted', naming: 'granted', likeness: 'granted' },
    });
    expect(JSON.stringify(person)).not.toMatch(/display_?name/i);
    expect(parsed.segments.every((item) => item.samples.every((samples) => samples.count > 0))).toBe(true);
  });

  it('refuses what cannot be an answer about the geometry it names', () => {
    const refuse = (value: unknown) => expect(() => parseSceneSegments(value)).toThrow(SegmentsUnavailable);
    refuse({ ...wire([segment(1)]), profile: 'exulanica.scene-segments/v0' });
    refuse(wire([segment(1, { samples: [{ artifact_id: POINTS, index_runs: [[0, 3], [2, 1]] }] })]));
    refuse(wire([segment(1, { samples: [{ artifact_id: POINTS, index_runs: [[5, 2]] }] })]));
    refuse(wire([segment(1, { vote_count: 5 })]));
    refuse(wire([segment(1, { entity_class: 'person', person: null })]));
    refuse(wire([segment(1, { samples: [{ artifact_id: '99999999-9999-4999-8999-999999999999', index_runs: [[0, 1]] }] })]));
    expect(() => parseSceneSegments(wire([segment(1)]), '44444444-4444-4444-8444-444444444444')).toThrow(/different scene/);
  });

  it('reads a consent it does not recognise, or one that is missing, as not recorded', () => {
    const parsed = parseSceneSegments(wire([segment(1, {
      entity_class: 'person', person: { review_state: 'screened', consent: { presence: 'granted', naming: 'maybe' } },
    })]));
    expect(parsed.segments[0]!.person!.consent).toEqual({ presence: 'granted', naming: 'not_recorded', likeness: 'not_recorded' });
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

  it('does not depend on the other segments, their order, or the region', () => {
    const segments = parseSceneSegments(FIXTURE);
    const reversed = { ...segments, segments: [...segments.segments].reverse() };
    const bound = bindSegments(segments, { sceneId: segments.sceneId, islandId: REGION, assets: [{ artifactId: segments.assets[0]!.artifactId, kind: 'point_map', sampleCount: 190570 }] }, undefined, true);
    const colourOf = (value: SceneSegments) => {
      const plan = planSegmentTints(value, bound);
      const palette = segmentPalette(plan, null);
      return new Map([...plan.slotOf.values()].map((slot) => [colourKeyOf(plan.segmentOfSlot.get(slot)!), palette.get(slot)!.slice(0, 3)]));
    };
    const first = colourOf(segments);
    const second = colourOf(reversed);
    expect([...first.keys()].sort()).toEqual([...second.keys()].sort());
    for (const [key, colour] of first) expect(second.get(key)).toEqual(colour);
    // The same entity in another scene's artifact, under another segment id, is the same colour.
    expect(colourKeyOf({ entityId: MARA, segmentId: segmentId(9) })).toBe(colourKeyOf({ entityId: MARA, segmentId: segmentId(1) }));
  });

  it('spreads identifiers that differ only in their last digits, which the browser showed as one green', () => {
    const keys = ['101', '102', '103', '104', '105'].map((tail) => `00000000-0000-4000-8000-000000000${tail}`);
    const colours = keys.map(segmentColor);
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

describe('segments tint only the bytes they were computed against', () => {
  const parsed = parseSceneSegments(wire([segment(1)]));

  it('binds an asset whose scene receipts, digest and sample count all agree', () => {
    const bound = bindSegments(parsed, DRAWN, RECORD, false);
    expect([...bound.assets.keys()]).toEqual([POINTS]);
    expect(bound.notices).toEqual([]);
  });

  it('refuses the whole artifact when a scene receipt differs, and an asset whose bytes or count differ', () => {
    const differ = (over: Partial<ReconstructionSceneRecord>) => bindSegments(parsed, DRAWN, { ...RECORD, ...over }, false);
    expect(differ({ poseReceiptSha256: 'f'.repeat(64) }).assets.size).toBe(0);
    expect(differ({ placementReceiptSha256: 'f'.repeat(64) }).assets.size).toBe(0);
    expect(differ({ memberDigest: 'f'.repeat(64) }).assets.size).toBe(0);
    expect(bindSegments(parsed, DRAWN, undefined, false).assets.size).toBe(0);
    const rebuilt = differ({ members: [{ placement: { artifactId: POINTS, contentSha256: 'f'.repeat(64) } }] } as never);
    expect(rebuilt.assets.size).toBe(0);
    expect(rebuilt.notices[0]).toMatch(/not the ones the segments were computed against/);
    const resampled = bindSegments(parsed, { ...DRAWN, assets: [{ artifactId: POINTS, kind: 'point_map', sampleCount: 7 }] }, RECORD, false);
    expect(resampled.notices[0]).toMatch(/draws 7 samples and the segments index 6/);
  });

  it('binds the preview by sample count alone, and says that it did', () => {
    const preview = bindSegments(parsed, { ...DRAWN, sceneId: 'legacy:x', assets: [{ artifactId: 'legacy:x:0', kind: 'point_map', sampleCount: 6 }] }, undefined, true);
    expect(preview.assets.get(POINTS)?.artifactId).toBe('legacy:x:0');
    expect(preview.verified).toBe(false);
    expect(preview.notices[0]).toMatch(/sample count only/);
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

function fakeEngine(): SegmentOverlayEngine {
  return {
    maxTextureSize: 4096,
    texture: () => ({ texture: {}, write: () => undefined, destroy: () => undefined }),
    pointGroups: () => ({ setLens: () => undefined, destroy: () => undefined }),
  };
}

function harness(segments: SceneSegments, snapshot: GraphSnapshot, over: Partial<SegmentsDependencies> = {}) {
  const positions = Float32Array.from([
    ...pointAt(300, 300, 5), ...pointAt(320, 300, 5), ...pointAt(500, 300, 5),
    ...pointAt(520, 300, 5), ...pointAt(600, 400, 5), ...pointAt(620, 400, 5),
  ]);
  const visual = {
    island: region(),
    entity: {},
    cloud: { pointCount: 6 },
    pointMap: { sceneId: SCENE_ID, artifactId: POINTS, islandId: REGION, map: { position: positions }, sceneFromOpmRowMajor: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], localUnitsToSceneUnits: 1 },
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
  const confirmShown: unknown[] = [];
  const mounted = mountSegments({
    env,
    state,
    snapshot,
    segmentSession: createSegmentSession(),
    session: { stage: vi.fn(), stateVersion: () => snapshot.stateVersion },
    confirm: { root: document.createElement('aside'), show: (...args: unknown[]) => { confirmShown.push(args); }, reportFailure: vi.fn(), hide: vi.fn() },
    hideOtherConfirms: vi.fn(),
    inspect: vi.fn(),
    showWorld: vi.fn(),
    showTravelStatus: vi.fn(),
    travelUsesReducedMotion: () => true,
    load: async () => segments,
    ...over,
  });
  document.body.append(mounted.root);
  return { mounted, binding, apply, setPalette, state, confirmShown };
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
    const h = harness(parseSceneSegments(wire([segment(1)])), snapshotWith());
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
    const h = harness(parseSceneSegments(wire([segment(1)])), snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    expect(h.apply).toHaveBeenCalledTimes(1);
    expect(h.apply.mock.calls[0]![0]).toMatchObject({ islandId: REGION, tints: [{ slot: 1, artifactId: POINTS }] });
    toggle(h.mounted);
    await settle();
    expect(h.apply.mock.calls.map((call) => call[0] === null)).toEqual([false, true]);
    expect(h.binding.segmentOverlay.report).toBeNull();
  });
});

describe('selecting a segment in the inspector', () => {
  async function inspecting() {
    const segments = parseSceneSegments(wire([
      segment(1, { samples: [{ artifact_id: POINTS, index_runs: [[0, 2]] }] }),
      segment(2, { label: 'lamp', vote_count: 2, samples: [{ artifact_id: POINTS, index_runs: [[2, 2]] }] }),
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
});

describe('a person segment', () => {
  const PERSON = '55555555-5555-4555-8555-555555555555';
  const person = (consent: Record<string, string>, label = 'Mara Kowalski') => segment(1, {
    entity_id: PERSON, entity_class: 'person', label, vote_count: 4,
    person: { review_state: 'screened', state: 'present', consent },
  });

  it('never shows a name the graph withheld, and says what consent is recorded', async () => {
    const h = harness(parseSceneSegments(wire([person({ presence: 'granted', likeness: 'withdrawn' })])),
      snapshotWith([{ entityId: PERSON, kind: 'person', displayName: null }]));
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    rows(h.mounted)[0]!.querySelector<HTMLButtonElement>('.scene-segment-select')!.click();
    const text = h.mounted.root.textContent ?? '';
    expect(text).toContain('Unnamed person');
    expect(text).not.toContain('Mara Kowalski');
    expect(text).toContain('Presence consent: granted. Naming consent: not recorded. Likeness consent: withdrawn.');
  });

  it('shows the name the graph gives, and only that one', async () => {
    const h = harness(parseSceneSegments(wire([person({ presence: 'granted', naming: 'granted' }, 'person')])),
      snapshotWith([{ entityId: PERSON, kind: 'person', displayName: 'Mara' }]));
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    expect(rows(h.mounted)[0]!.querySelector('.scene-segment-heading')?.textContent).toBe('Mara');
  });

  it('is listed and not tinted without recorded presence consent', async () => {
    const h = harness(parseSceneSegments(wire([person({ presence: 'withdrawn' })])), snapshotWith());
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    expect(rows(h.mounted)[0]!.textContent).toContain('Not tinted: no presence consent is recorded for this person.');
    expect(h.apply).not.toHaveBeenCalled();
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

  async function openFlow() {
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
    const segments = parseSceneSegments(wire([segment(1, { label: 'chair', occurrence_ids: [CHAIR] })]));
    const h = harness(segments, snapshot, { session: opened.session, confirm: writePath.confirm });
    (h.state as { issued: number }).issued = 0;
    Object.assign(h.state, { snapshot });
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    h.binding.inspectionView = INSPECTING;
    return { h, writePath, detail, snapshot, state, remount };
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

  it('offers no naming form for a segment whose detections the graph already links', async () => {
    const segments = parseSceneSegments(wire([segment(1, { occurrence_ids: [PREVIEW_IDS.occurrenceStudioPlace] })]));
    const opened = await openSession({ baseUrl: API, token: 'token' });
    const h = harness(segments, { ...opened.initial, reconstructionScenes: [RECORD] } as GraphSnapshot);
    mounted = h.mounted;
    await h.mounted.begin();
    toggle(h.mounted);
    await settle();
    rows(h.mounted)[0]!.querySelector<HTMLButtonElement>('.scene-segment-select')!.click();
    expect(h.mounted.root.querySelector('.scene-segment-name')).toBeNull();
    expect(h.mounted.root.textContent).toMatch(/already linked to an entity/);
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

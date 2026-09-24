import { describe, expect, it, vi } from 'vitest';
import { composeDisplayFrame } from '@exulanica/atlas-core';
import { scenePointMapViewpoint } from '@exulanica/atlas-react/playcanvas';
import type { ReconstructionSceneRecord } from '@exulanica/graph-client';
import { GeometryClient, standpointArrangementSentence } from '../src/geometry-api.js';
import { reconstructionRungsFor } from '../src/composition/session-and-geometry.js';

/**
 * A scene pose placed nothing, joined by the server's standpoint record: the client draws its
 * members from the transforms the server measured, never from the arrangement it would otherwise
 * derive, and says which it is showing.
 *
 * The container is rebuilt here for the reason `geometry-api.test.ts` gives: what is under test is
 * that real bytes, checked against a real digest, reach a decoder that was given no help.
 */

const CAPTURE_A = '11111111-1111-4111-8111-111111111111';
const CAPTURE_B = '22222222-2222-4222-8222-222222222222';
const CAPTURE_C = '33333333-3333-4333-8333-333333333333';
const REGION = '99999999-9999-4999-8999-999999999999';
const ARTIFACTS = [
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
];

const align = (n: number): number => Math.ceil(n / 16) * 16;

type Point = readonly [number, number, number];

function buildOpm(points: readonly Point[]): ArrayBuffer {
  const count = points.length;
  const sizes = { position: count * 12, color: count * 4, tags: count * 4 };
  const min = [0, 1, 2].map((axis) => Math.min(...points.map((point) => point[axis]!)));
  const max = [0, 1, 2].map((axis) => Math.max(...points.map((point) => point[axis]!)));
  const header = (offsets: [number, number, number]) => ({
    format: 'exulanica-point-map', version: 2, pointCount: count, rung: 3, frame: 'local',
    up: '+Y', forward: '-Z', units: 'metres', metric: true,
    viewpoint: { position: [0, 0, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: 55, aspect: 4 / 3 },
    sourceImage: { width: 400, height: 300 },
    modelImage: { width: 400, height: 300 },
    bounds: { min, max },
    colorAlpha: 'support',
    segments: [{ id: 0, name: 'unsegmented', cls: 'unknown' }],
    sections: [
      { name: 'position', type: 'float32', components: 3, normalized: false, byteOffset: offsets[0], byteLength: sizes.position },
      { name: 'color', type: 'uint8', components: 4, normalized: true, byteOffset: offsets[1], byteLength: sizes.color },
      { name: 'tags', type: 'uint16', components: 2, normalized: false, byteOffset: offsets[2], byteLength: sizes.tags },
    ],
  });
  const probe = new TextEncoder().encode(JSON.stringify(header([0, 0, 0])));
  const dataStart = 8 + align(probe.length + 96);
  const positionAt = align(dataStart);
  const colorAt = align(positionAt + sizes.position);
  const tagsAt = align(colorAt + sizes.color);
  const bytes = new Uint8Array(align(tagsAt + sizes.tags));
  const view = new DataView(bytes.buffer);
  const headerBytes = new TextEncoder().encode(JSON.stringify(header([positionAt, colorAt, tagsAt])));
  bytes.set(new TextEncoder().encode('OPM1'), 0);
  view.setUint32(4, headerBytes.length, true);
  bytes.set(headerBytes, 8);
  points.forEach((point, i) => {
    point.forEach((value, axis) => view.setFloat32(positionAt + i * 12 + axis * 4, value, true));
    bytes[colorAt + i * 4 + 3] = 200;
  });
  return bytes.buffer;
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function serve(bodies: ReadonlyMap<string, ArrayBuffer>) {
  const requests: string[] = [];
  const fetch = vi.fn(async (input: string | URL | Request) => {
    const path = new URL(String(input)).pathname;
    requests.push(path);
    return new Response(bodies.get(path.split('/').at(-1)!)!, {
      status: 200, headers: { 'content-type': 'application/vnd.exulanica.point-map' },
    });
  });
  return { fetch, requests };
}

const LATERAL = 0.97;
const DEPTH = 1.02;
/** Where the floor is below the standpoint, in the depth model's units. */
const FLOOR = -1.5;

/** A turn of `yaw` degrees about +Y after a pitch of `pitch` degrees about +X, row major 3 x 3. */
function rotation(yaw: number, pitch: number): number[] {
  const [a, b] = [(yaw * Math.PI) / 180, (pitch * Math.PI) / 180];
  const y = [Math.cos(a), 0, Math.sin(a), 0, 1, 0, -Math.sin(a), 0, Math.cos(a)];
  const x = [1, 0, 0, 0, Math.cos(b), -Math.sin(b), 0, Math.sin(b), Math.cos(b)];
  return [0, 1, 2].flatMap((row) => [0, 1, 2].map((col) =>
    y[row * 3]! * x[col]! + y[row * 3 + 1]! * x[3 + col]! + y[row * 3 + 2]! * x[6 + col]!));
}

/** `R diag(lateral x depth, lateral x depth, depth)` as the server writes it, row major 4 x 4. */
function standpointMatrix(r: readonly number[]): number[] {
  const scales = [LATERAL * DEPTH, LATERAL * DEPTH, DEPTH];
  return [0, 1, 2].flatMap((row) => [...[0, 1, 2].map((col) => r[row * 3 + col]! * scales[col]!), 0])
    .concat([0, 0, 0, 1]);
}

/**
 * A floor ahead of a camera turned by `r`, in that camera's own units: the scene points
 * `(x, FLOOR, z)` taken back through the server's transform, so every member holds one floor.
 */
function floorSeenFrom(r: readonly number[]): Point[] {
  const points: Point[] = [];
  for (const across of [-2, -1, 0, 1, 2]) {
    for (const ahead of [2, 3, 5, 8]) {
      const world = [across, FLOOR, -ahead];
      // Ahead of this camera: turn the floor patch with the camera's heading.
      const heading = Math.atan2(r[2]!, r[8]!);
      const turned = [
        world[0]! * Math.cos(heading) + world[2]! * Math.sin(heading),
        world[1]!,
        -world[0]! * Math.sin(heading) + world[2]! * Math.cos(heading),
      ];
      const camera = [0, 1, 2].map((col) =>
        r[col]! * turned[0]! + r[3 + col]! * turned[1]! + r[6 + col]! * turned[2]!);
      points.push([camera[0]! / (LATERAL * DEPTH), camera[1]! / (LATERAL * DEPTH), camera[2]! / DEPTH]);
    }
  }
  return points;
}

interface Member {
  readonly r: readonly number[] | null;
  readonly bytes: ArrayBuffer;
  readonly digest: string;
}

/** Members turned by `[yaw, pitch]`, or apart from the arrangement when null. */
async function membersTurned(turns: readonly (readonly [number, number] | null)[]): Promise<Member[]> {
  return Promise.all(turns.map(async (turn) => {
    const r = turn === null ? null : rotation(turn[0], turn[1]);
    const bytes = buildOpm(floorSeenFrom(r ?? rotation(75, 0)));
    return { r, bytes, digest: await sha256(bytes) };
  }));
}

function joinedScene(members: readonly Member[], state: 'joined' | 'withdrawn' = 'joined'): ReconstructionSceneRecord {
  const captures = [CAPTURE_A, CAPTURE_B, CAPTURE_C];
  const rows = members.map(({ r, bytes, digest }, index) => {
    const joined = state === 'joined' && r !== null;
    // A joined scene's member outside the arrangement comes with no depth at all.
    const offered = state !== 'joined' || r !== null;
    return {
      captureId: captures[index]!,
      ordinal: index,
      personRegions: [],
      personReviewState: 'screened' as const,
      registered: false,
      exclusionReason: 'pose-not-registered',
      placement: null,
      unposedPointMap: offered ? {
        artifactId: ARTIFACTS[index]!,
        contentSha256: digest,
        container: 'opm/2',
        state: 'available' as const,
        reference: {
          href: `/geometry/${ARTIFACTS[index]}`,
          authorization: 'workspace-bearer' as const,
          contentSha256: digest,
          byteSize: bytes.byteLength,
        },
      } : null,
      standpointPlacement: joined
        ? { sceneFromOpmRowMajor: standpointMatrix(r), depthScale: DEPTH, lateralScale: LATERAL }
        : null,
    };
  });
  return {
    sceneId: 'scene-1',
    islandId: REGION,
    generatedGeometry: [],
    memberDigest: '1'.repeat(64),
    poseReceiptSha256: '2'.repeat(64),
    placementReceiptSha256: '3'.repeat(64),
    gateDigest: '4'.repeat(64),
    recordedRung: 4,
    recordedReasons: [],
    displayedRung: 3,
    displayReasons: [],
    memberCount: 3,
    registeredMemberCount: 0,
    receiptState: 'available',
    placementState: 'none_placed',
    renderingSubstrate: 'unposed_point_maps',
    hiddenPersonCount: 0,
    maskedMemberCount: 0,
    members: rows,
    standpoint: {
      artifactId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      contentSha256: '5'.repeat(64),
      state,
      memberCount: 3,
      joinedMemberCount: state === 'joined' ? 2 : 0,
      referenceCaptureId: state === 'joined' ? CAPTURE_A : null,
      rotationResidualMaxMillidegrees: state === 'joined' ? 40 : null,
      scaleResidualMaxPpm: state === 'joined' ? 3000 : null,
      upMethod: state === 'joined' ? 'camera-horizontal-axes' : null,
      impliedRollMaxMillidegrees: state === 'joined' ? 900 : null,
      excluded: state === 'joined' ? [{ captureId: CAPTURE_C, reason: 'moved_between_photographs' }] : [],
    },
  };
}

const regions = new Map([[CAPTURE_A, REGION as never], [CAPTURE_B, REGION as never], [CAPTURE_C, REGION as never]]);

async function load(members: readonly Member[], state: 'joined' | 'withdrawn' = 'joined') {
  const { fetch, requests } = serve(new Map(members.map(({ bytes }, index) => [ARTIFACTS[index]!, bytes])));
  const scene = joinedScene(members, state);
  const session = await new GeometryClient({
    baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
  }).loadScenes([scene], regions);
  return { scene, session, requests };
}

describe('a scene joined where its photographs were taken', () => {
  it('draws its members from the server\u2019s measured transforms under one display frame', async () => {
    const { scene, session, requests } = await load(await membersTurned([[0, 0], [-30, 0], null]));

    expect(session.issues).toEqual([]);
    // The member outside the arrangement is not fetched: it opens as a photograph.
    expect(requests).toEqual([`/api/geometry/${ARTIFACTS[0]}`, `/api/geometry/${ARTIFACTS[1]}`]);
    expect(session.placedPointMaps.map((placed) => placed.arrangement)).toEqual(['standpoint', 'standpoint']);
    expect(session.renderingByScene.get('scene-1')).toBe('unposed_point_maps');
    const frame = session.displayFrames.get('scene-1')!;
    session.placedPointMaps.forEach((placed, index) => {
      const measured = composeDisplayFrame(frame, scene.members[index]!.standpointPlacement!.sceneFromOpmRowMajor);
      placed.sceneFromOpmRowMajor.forEach((value, lane) => expect(value).toBeCloseTo(measured[lane]!, 9));
      expect(placed.localUnitsToSceneUnits).toBeCloseTo(frame.scale * DEPTH, 12);
      // One standpoint, stood at eye height above the floor the photographs hold.
      const [x, y, z] = scenePointMapViewpoint(placed);
      expect([x, z]).toEqual([expect.closeTo(0, 9), expect.closeTo(0, 9)]);
      expect(y).toBeCloseTo(frame.eyeHeight, 6);
    });
    expect(frame.scale).toBeCloseTo(frame.eyeHeight / -FLOOR, 6);
  });

  it('keeps the measured up and the floor when a member was pitched', async () => {
    const { session } = await load(await membersTurned([[0, 0], [-30, -20], null]));
    expect(session.issues).toEqual([]);
    const frame = session.displayFrames.get('scene-1')!;
    // No turn at all: the record's up stands, and the pitched member's box, whose corners fall
    // below the floor it holds, does not shrink the scene.
    const linear = [0, 1, 2, 4, 5, 6, 8, 9, 10].map((lane) => frame.displayFromSceneRowMajor[lane]! / frame.scale);
    linear.forEach((value, index) => expect(value).toBeCloseTo([1, 0, 0, 0, 1, 0, 0, 0, 1][index]!, 9));
    expect(frame.scale).toBeCloseTo(frame.eyeHeight / -FLOOR, 6);
  });

  it('falls back to the unmeasured arrangement when the record is withheld', async () => {
    const { session } = await load(await membersTurned([[0, 0], [-30, 0], null]), 'withdrawn');
    expect(session.placedPointMaps.map((placed) => placed.arrangement))
      .toEqual(['unmeasured-fan', 'unmeasured-fan', 'unmeasured-fan']);
  });

  it('tells the visitor the arrangement is measured only when it is the one drawn', async () => {
    const members = await membersTurned([[0, 0], [-30, 0], null]);
    const frame = { scale: 1, metric: false } as never;
    const [shown] = reconstructionRungsFor([joinedScene(members)], new Map([['scene-1', 'unposed_point_maps']]),
      new Set(), new Map([['scene-1', frame]]));
    expect(shown!.measuredArrangement).toBe(true);
    expect(shown!.reasons).toContain(standpointArrangementSentence(frame));
    const [withheld] = reconstructionRungsFor([joinedScene(members, 'withdrawn')],
      new Map([['scene-1', 'unposed_point_maps']]), new Set(), new Map([['scene-1', frame]]));
    expect(withheld!.measuredArrangement).toBe(false);
    expect(withheld!.reasons).not.toContain(standpointArrangementSentence(frame));
  });
});

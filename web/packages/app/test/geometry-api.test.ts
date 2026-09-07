import { describe, expect, it, vi } from 'vitest';
import { displayCameraTransform, identityDisplayFrame, sceneDisplayFrame } from '@exulanica/atlas-core';
import { readFileSync } from 'node:fs';
import type { ReconstructionSceneRecord } from '@exulanica/graph-client';
import {
  GeometryClient,
  regionsByCapture,
  type GeometryLoadMeasurement,
  displayFrameSentence,
} from '../src/geometry-api.js';

/**
 * The production reconstruction boundary, ADR-0009 D10 from the client's side.
 *
 * The container is rebuilt here rather than imported. A test directory is not a package export
 * and the app may not reach into `@exulanica/atlas-react`'s, and the duplication is the same one
 * the decoder itself carries for the same reason: what is under test is that real bytes, checked
 * against a real digest, reach a decoder that was given no help.
 */

const CAPTURE_A = '11111111-1111-4111-8111-111111111111';
const CAPTURE_B = '22222222-2222-4222-8222-222222222222';
const REGION = '99999999-9999-4999-8999-999999999999';

const align = (n: number): number => Math.ceil(n / 16) * 16;

/** A minimal, valid `.opm`. `seed` changes the bytes so two maps are distinguishable. */
function buildOpm(seed = 0, count = 4): ArrayBuffer {
  const sizes = { position: count * 12, color: count * 4, tags: count * 4 };
  const header = (offsets: [number, number, number]) => ({
    format: 'exulanica-point-map',
    version: 2,
    pointCount: count,
    rung: 3,
    frame: 'local',
    up: '+Y',
    forward: '-Z',
    units: 'metres',
    metric: true,
    viewpoint: {
      position: [0, 1.55, 0],
      forward: [0, 0, -1],
      up: [0, 1, 0],
      fovYDeg: 55,
      aspect: 4 / 3,
    },
    sourceImage: { width: 400, height: 300 },
    modelImage: { width: 400, height: 300 },
    bounds: { min: [-3, 0, -8], max: [4, 2, -1] },
    colorAlpha: 'confidence',
    segments: [{ id: 0, name: 'ground', cls: 'ground' }],
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
  const total = align(tagsAt + sizes.tags);

  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  const headerBytes = new TextEncoder().encode(
    JSON.stringify(header([positionAt, colorAt, tagsAt])),
  );
  bytes.set(new TextEncoder().encode('OPM1'), 0);
  view.setUint32(4, headerBytes.length, true);
  bytes.set(headerBytes, 8);
  for (let i = 0; i < count; i += 1) {
    view.setFloat32(positionAt + i * 12, i + seed, true);
    bytes[colorAt + i * 4 + 3] = 200;
  }
  return bytes.buffer;
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

const descriptor = (overrides: Record<string, unknown> = {}) => {
  const { reference: given, ...rest } = overrides;
  const row = {
    capture_id: CAPTURE_A,
    artifact_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    kind: 'point_map',
    stage_key: 'depth',
    stage_version: 1,
    container: 'opm/2',
    state: 'available',
    reason: null,
    needs_repair: false,
    ...rest,
  };
  if (given === null) return { ...row, reference: null };
  return {
    ...row,
    reference: {
      href: `/geometry/${row.artifact_id}`,
      authorization: 'workspace-bearer',
      content_sha256: '0'.repeat(64),
      byte_size: 0,
      ...(given as Record<string, unknown> | undefined),
    },
  };
};

/** A server that answers the list with `rows` and every byte request with `bytes`. */
function serve(rows: unknown[], bytes: ArrayBuffer, etag?: string) {
  const requests: { path: string; init: RequestInit }[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    requests.push({ path, init });
    if (path.endsWith('/geometry')) return json(rows);
    return new Response(bytes, {
      status: 200,
      headers: {
        'content-type': 'application/vnd.exulanica.point-map',
        ...(etag === undefined ? {} : { etag: `"${etag}"` }),
      },
    });
  });
  return { fetch, requests };
}

const regions = new Map([[CAPTURE_A, REGION as never], [CAPTURE_B, REGION as never]]);

function trainedFixture(): ArrayBuffer {
  return Uint8Array.from(readFileSync(`${process.cwd()}/test-data/compressor-3.3.3-format-only.sog`)).buffer;
}

function trainedScene(digest: string, size: number): ReconstructionSceneRecord {
  const scene = sceneRecord(digest, size);
  return { ...scene, members: scene.members.map((member) => ({ ...member, placement: null })),
    renderingSubstrate: 'gaussian_splats', trainedGeometry: {
      artifactId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', contentSha256: digest,
      container: 'sog/1', state: 'available',
      sceneFromAssetRowMajor: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      bounds: { min: [-1, -1, -1], max: [1, 1, 1] },
      reference: { href: '/scene-geometry/cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        authorization: 'workspace-bearer', contentSha256: digest, byteSize: size },
    } };
}

describe('trained scene authenticated delivery', () => {
  const camera = {
    sceneFromCameraRowMajor: [1, 0, 0, 2, 0, 1, 0, 3, 0, 0, 1, 4, 0, 0, 0, 1],
    projection: 'pinhole' as const,
    calibration: { model: 'PINHOLE', width: 800, height: 600, fx: 810, fy: 620, cx: 390, cy: 280,
      parameters: [810, 620, 390, 280] },
  };
  it('delivers accepted calibrated cameras with a trained scene when every OPM is absent', async () => {
    const bytes = trainedFixture();
    const digest = await sha256(bytes);
    const original = trainedScene(digest, bytes.byteLength);
    const scene = { ...original, members: original.members.map((member) => ({ ...member, recoveredCamera: camera })) };
    const { fetch, requests } = serve([], bytes);
    const loaded = await new GeometryClient({ baseUrl: 'https://exulanica.test', token: 'synthetic-token', fetch })
      .loadScenes([scene], regions);
    expect(loaded.placedPointMaps).toEqual([]);
    expect(loaded.trainedGeometry).toHaveLength(1);
    expect(loaded.recoveredCameras.map((camera) => camera.captureId)).toEqual([CAPTURE_A, CAPTURE_B]);
    // The display frame moves the camera into the region's upright walking frame; calibration,
    // projection and identity are untouched and the camera axes stay unit length.
    const frame = loaded.displayFrames.get(original.sceneId)!;
    expect(frame.metric).toBe(false);
    expect(loaded.recoveredCameras[0]).toMatchObject({ calibration: camera.calibration, projection: camera.projection,
      captureId: CAPTURE_A, poseReceiptSha256: original.poseReceiptSha256, sceneId: original.sceneId, islandId: REGION,
      sceneFromCameraRowMajor: displayCameraTransform(frame, camera.sceneFromCameraRowMajor) });
    expect(Math.hypot(...[0, 4, 8].map((i) => loaded.recoveredCameras[0]!.sceneFromCameraRowMajor[i]!))).toBeCloseTo(1, 9);
    expect(requests.map((request) => request.path)).toEqual(['/scene-geometry/cccccccc-cccc-4ccc-8ccc-cccccccccccc']);
    expect(loaded.issues).toEqual([]);
  });

  it('rejects unaccepted, unregistered, or scaled camera descriptors without blocking source fallback', async () => {
    const original = sceneRecord('a'.repeat(64), 0);
    const member = { ...original.members[0]!, placement: null, recoveredCamera: camera };
    const scenes: ReconstructionSceneRecord[] = [
      { ...original, receiptState: 'invalid', members: [member] },
      { ...original, members: [{ ...member, registered: false }] },
      { ...original, members: [{ ...member, recoveredCamera: { ...camera,
        sceneFromCameraRowMajor: camera.sceneFromCameraRowMajor.map((v, i) => i === 0 ? 2 : v) } }] },
      { ...original, poseReceiptSha256: null, members: [member] },
    ];
    for (const scene of scenes) {
      const { fetch, requests } = serve([], new ArrayBuffer(0));
      const loaded = await new GeometryClient({ baseUrl: 'https://exulanica.test', token: 'synthetic-token', fetch })
        .loadScenes([scene], regions);
      expect(loaded.recoveredCameras).toEqual([]);
      expect(loaded.renderingByScene.get(scene.sceneId)).toBe('source_photographs');
      expect(requests).toEqual([]);
    }
  });

  it('passes exact verified SOG bytes to the renderer boundary without claiming a successful GPU load', async () => {
    const bytes = trainedFixture();
    const digest = await sha256(bytes);
    const { fetch, requests } = serve([], bytes);
    const measurements: GeometryLoadMeasurement[] = [];
    const loaded = await new GeometryClient({ baseUrl: 'https://exulanica.test', token: 'workspace-token', fetch },
      (measurement) => measurements.push(measurement)).loadScenes([trainedScene(digest, bytes.byteLength)], regions);
    expect(requests).toHaveLength(1);
    expect(new Headers(requests[0]!.init.headers).get('Authorization')).toBe('Bearer workspace-token');
    expect(requests[0]!.path).toBe('/scene-geometry/cccccccc-cccc-4ccc-8ccc-cccccccccccc');
    expect(loaded.trainedGeometry).toHaveLength(1);
    expect(loaded.trainedGeometry[0]!.bytes).toEqual(bytes);
    expect(loaded.trainedGeometry[0]!.pointCount).toBe(512);
    expect(loaded.renderingByScene.get('scene-1')).toBe('source_photographs');
    expect(loaded.issues).toEqual([]);
    expect(measurements[0]!.receivedBytes).toBe(bytes.byteLength);
  });

  it('refuses wrong digests, external paths, missing bytes, and unavailable verification', async () => {
    const bytes = trainedFixture();
    const digest = await sha256(bytes);
    const original = trainedScene(digest, bytes.byteLength);
    const source = original.trainedGeometry!;
    const wrongDigest = 'f'.repeat(64);
    const cases: readonly [ReconstructionSceneRecord, string, number][] = [
      [{ ...original, trainedGeometry: { ...source, contentSha256: wrongDigest,
        reference: { ...source.reference!, contentSha256: wrongDigest } } }, 'verification_failed', 1],
      [{ ...original, trainedGeometry: { ...source,
        reference: { ...source.reference!, href: 'https://elsewhere.test/scene.sog' } } }, 'error', 0],
      [{ ...original, trainedGeometry: { ...source, state: 'bytes_missing', reference: null } }, 'bytes_missing', 0],
    ];
    for (const [scene, state, expectedRequests] of cases) {
      const { fetch, requests } = serve([], bytes);
      const loaded = await new GeometryClient({ baseUrl: 'https://exulanica.test', token: 'private', fetch })
        .loadScenes([scene], regions);
      expect(loaded.trainedGeometry).toEqual([]);
      expect(loaded.issues.map((issue) => issue.state)).toEqual([state]);
      expect(requests).toHaveLength(expectedRequests);
    }
    vi.stubGlobal('crypto', {});
    try {
      const { fetch, requests } = serve([], bytes);
      const loaded = await new GeometryClient({ baseUrl: 'https://exulanica.test', token: 'private', fetch })
        .loadScenes([original], regions);
      expect(loaded.issues[0]!.state).toBe('unverifiable');
      expect(loaded.trainedGeometry).toEqual([]);
      expect(requests).toHaveLength(0);
    } finally { vi.unstubAllGlobals(); }
  });
});

function sceneRecord(
  contentSha256: string,
  byteSize: number,
  secondDigest = contentSha256,
): ReconstructionSceneRecord {
  const member = (captureId: string, ordinal: number, artifactId: string, digest: string) => ({
    captureId,
    ordinal,
    // These fixtures are synthetic geometry with nobody in the frame: screened, and empty. That
    // is deliberately not the same as leaving them out, which would mean nobody had looked.
    personRegions: [],
    personReviewState: 'screened' as const,
    registered: true,
    exclusionReason: null,
    placement: {
      artifactId,
      contentSha256: digest,
      container: 'opm/2',
      sceneFromOpmRowMajor: [
        1, 0, 0, ordinal * 3,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
      ],
      localUnitsToSceneUnits: 1,
      scaleStatus: 'colmap-correspondence-fit' as const,
      state: 'available' as const,
      reference: {
        href: `/geometry/${artifactId}`,
        authorization: 'workspace-bearer' as const,
        contentSha256: digest,
        byteSize,
      },
    },
  });
  return {
    sceneId: 'scene-1',
    islandId: REGION,
    generatedGeometry: [],
    memberDigest: '1'.repeat(64),
    poseReceiptSha256: '2'.repeat(64),
    placementReceiptSha256: '3'.repeat(64),
    gateDigest: '4'.repeat(64),
    recordedRung: 3,
    recordedReasons: [],
    displayedRung: 3,
    displayReasons: [],
    memberCount: 2,
    registeredMemberCount: 2,
    receiptState: 'available',
    placementState: 'available',
    renderingSubstrate: 'posed_point_maps',
    hiddenPersonCount: 0,
    maskedMemberCount: 0,
    members: [
      member(CAPTURE_A, 0, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', contentSha256),
      member(CAPTURE_B, 1, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', secondDigest),
    ],
  };
}

describe('production reconstruction geometry', () => {
  it('refuses legacy identity placement before fetching any bytes', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const { fetch, requests } = serve([], bytes);
    const old = sceneRecord(digest, bytes.byteLength);
    const legacy = {
      ...old,
      members: old.members.map((member) => ({
        ...member, placement: { ...member.placement, scaleStatus: 'unvalidated-identity' },
      })),
    } as unknown as ReconstructionSceneRecord;
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).loadScenes([legacy], regions);
    expect(requests).toEqual([]);
    expect(session.placedPointMaps).toEqual([]);
    expect(session.renderingByScene.get('scene-1')).toBe('source_photographs');
    expect(session.issues.map((issue) => issue.state)).toEqual(['unplaced', 'unplaced']);
  });
  it('loads every digest-verified point map in a posed scene with its distinct transform', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const { fetch, requests } = serve([], bytes);
    const measurements: GeometryLoadMeasurement[] = [];
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }, (measurement) => measurements.push(measurement))
      .loadScenes([sceneRecord(digest, bytes.byteLength)], regions);

    expect(session.issues).toEqual([]);
    expect(session.placedPointMaps).toHaveLength(2);
    // Receipt transforms put the maps at scene x = 0 and 3; the display frame keeps that distinct
    // 3-unit separation, scaled, and centres the scene on the region's vertical axis.
    const frame = session.displayFrames.get('scene-1')!;
    const xs = session.placedPointMaps.map((value) => value.sceneFromOpmRowMajor[3]!);
    expect(xs[1]! - xs[0]!).toBeCloseTo(3 * frame.scale, 9);
    expect(session.placedPointMaps.map((value) => value.localUnitsToSceneUnits)).toEqual([frame.scale, frame.scale]);
    expect(session.renderingByScene.get('scene-1')).toBe('posed_point_maps');
    expect(requests.map((request) => request.path)).toEqual([
      '/api/geometry/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '/api/geometry/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    ]);
    expect(measurements.map((measurement) => ({
      artifactId: measurement.artifactId,
      expectedBytes: measurement.expectedBytes,
      receivedBytes: measurement.receivedBytes,
      reused: measurement.reused,
    }))).toEqual([
      {
        artifactId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        expectedBytes: bytes.byteLength,
        receivedBytes: bytes.byteLength,
        reused: false,
      },
      {
        artifactId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        expectedBytes: bytes.byteLength,
        receivedBytes: bytes.byteLength,
        reused: false,
      },
    ]);
    for (const measurement of measurements) {
      expect(measurement.fetchMs).toBeGreaterThanOrEqual(0);
      expect(measurement.verifyMs).toBeGreaterThanOrEqual(0);
      expect(measurement.decodeMs).toBeGreaterThanOrEqual(0);
    }
  });

  it('composes the display scale into the declared scalar exactly once', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const { fetch } = serve([], bytes);
    const base = sceneRecord(digest, bytes.byteLength);
    // Receipt placements at twice the OPM scale, rotated so each camera looks straight down at its
    // map: the geometry then lies below the cameras, the frame has a real ground to stand on, and
    // the display scale is not one, so a scalar left unscaled cannot pass the placement validator.
    const doubledLookingDown = (ordinal: number) => [
      2, 0, 0, ordinal * 3,
      0, 0, 2, 0,
      0, -2, 0, 0,
      0, 0, 0, 1,
    ];
    const doubled = { ...base, members: base.members.map((member) => ({ ...member, placement: {
      ...member.placement!, sceneFromOpmRowMajor: doubledLookingDown(member.ordinal), localUnitsToSceneUnits: 2,
    } })) };
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).loadScenes([doubled], regions);
    const frame = session.displayFrames.get('scene-1')!;
    expect(frame.scale).toBeGreaterThan(0);
    expect(frame.scale).not.toBeCloseTo(1, 3);
    expect(session.issues).toEqual([]);
    expect(session.placedPointMaps).toHaveLength(2);
    for (const placed of session.placedPointMaps) {
      expect(placed.localUnitsToSceneUnits).toBeCloseTo(2 * frame.scale, 9);
      const m = placed.sceneFromOpmRowMajor;
      expect(Math.hypot(m[0]!, m[4]!, m[8]!)).toBeCloseTo(placed.localUnitsToSceneUnits, 9);
    }
  });

  it('draws only the scenes its regions display and reports the rest without fetching', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const { fetch, requests } = serve([], bytes);
    const shown = sceneRecord(digest, bytes.byteLength);
    const superseded = { ...shown, sceneId: 'scene-0', members: shown.members.slice(0, 1), memberCount: 1,
      registeredMemberCount: 1 };
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).loadScenes([superseded, shown], regions, undefined, new Set(['scene-1']));

    expect(session.issues).toEqual([expect.objectContaining({ sceneId: 'scene-0', state: 'not_displayed' })]);
    expect(session.issues[0]!.reason).toMatch(/not drawn/u);
    expect(session.renderingByScene.get('scene-0')).toBe('source_photographs');
    expect(session.renderingByScene.get('scene-1')).toBe('posed_point_maps');
    expect(session.placedPointMaps).toHaveLength(2);
    expect(requests.map((request) => request.path)).toEqual([
      '/api/geometry/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '/api/geometry/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    ]);
    // Without the set every scene still loads, which is the contract older callers rely on.
    const everything = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).loadScenes([superseded], regions);
    expect(everything.renderingByScene.get('scene-0')).toBe('posed_point_maps');
  });

  it('keeps valid scene members when one map is corrupt and falls back when none verify', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const wrong = 'f'.repeat(64);
    const partialServer = serve([], bytes);
    const partial = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch: partialServer.fetch,
    }).loadScenes([sceneRecord(digest, bytes.byteLength, wrong)], regions);
    expect(partial.placedPointMaps).toHaveLength(1);
    expect(partial.issues[0]!.state).toBe('verification_failed');
    expect(partial.renderingByScene.get('scene-1')).toBe('posed_point_maps');

    const failedServer = serve([], bytes);
    const failed = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch: failedServer.fetch,
    }).loadScenes([sceneRecord(wrong, bytes.byteLength, wrong)], regions);
    expect(failed.placedPointMaps).toHaveLength(0);
    expect(failed.renderingByScene.get('scene-1')).toBe('source_photographs');
  });

  it('fetches with a bearer, verifies against the descriptor, and decodes', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const { fetch, requests } = serve(
      [descriptor({ reference: { content_sha256: digest, byte_size: bytes.byteLength } })],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.issues).toEqual([]);
    expect(session.pointMaps.get(REGION as never)?.header.pointCount).toBe(4);
    expect(requests.map((request) => request.path)).toEqual([
      '/api/geometry',
      '/api/geometry/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    ]);
    // The credential is in a header on both calls and in no URL. What it unlocks is somebody's
    // photograph library, and a token in a query string ends up in a proxy log.
    for (const request of requests) {
      expect((request.init.headers as Record<string, string>).authorization)
        .toBe('Bearer private-token');
      expect(request.path).not.toContain('private-token');
    }
  });

  it('refuses bytes that do not hash to the digest the descriptor named', async () => {
    const bytes = buildOpm();
    const { fetch } = serve(
      [descriptor({ reference: { content_sha256: 'a'.repeat(64), byte_size: bytes.byteLength } })],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues).toHaveLength(1);
    expect(session.issues[0]!.state).toBe('verification_failed');
  });

  it('verifies against the descriptor and not against the response that carried the bytes', async () => {
    /**
     * The case the whole design turns on. A response whose ETag agrees with its own body proves
     * nothing: a client checking the body against that header is checking the response against
     * itself. Only the descriptor, which named the digest before the transfer began, is a second
     * opinion.
     */
    const substituted = buildOpm(7);
    const { fetch } = serve(
      [descriptor({ reference: {
        content_sha256: await sha256(buildOpm(0)),
        byte_size: substituted.byteLength,
      } })],
      substituted,
      await sha256(substituted),
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues[0]!.state).toBe('verification_failed');
  });

  it('refuses a body of the wrong length before it hashes anything', async () => {
    const bytes = buildOpm();
    const { fetch } = serve(
      [descriptor({ reference: {
        content_sha256: await sha256(bytes), byte_size: bytes.byteLength + 1,
      } })],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.issues[0]!.state).toBe('verification_failed');
    expect(session.issues[0]!.reason).toContain('bytes');
  });

  it('loads nothing at all when the page has no SubtleCrypto', async () => {
    /**
     * A page served over a non-secure context cannot meet D10's third requirement, so it meets
     * none of them. Decoding unverified bytes because checking became inconvenient is the trade
     * this design exists to refuse.
     */
    const bytes = buildOpm();
    const { fetch, requests } = serve(
      [descriptor({ reference: {
        content_sha256: await sha256(bytes), byte_size: bytes.byteLength,
      } })],
      bytes,
    );
    vi.stubGlobal('crypto', {});
    try {
      const session = await new GeometryClient({
        baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
      }).load(regions);
      expect(session.pointMaps.size).toBe(0);
      expect(session.issues[0]!.state).toBe('unverifiable');
      // And it never asked for the bytes it could not have checked.
      expect(requests.map((request) => request.path)).toEqual(['/api/geometry']);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('attempts one reconstruction per region even when that one fails', async () => {
    /**
     * The region is marked before the fetch, not after the decode. Marking it after would let a
     * region of sixteen photographs behind a mangling proxy fetch every one of them, at a few
     * megabytes each, to draw nothing.
     */
    const bytes = buildOpm();
    const { fetch, requests } = serve(
      [
        descriptor({ reference: { content_sha256: 'c'.repeat(64), byte_size: bytes.byteLength } }),
        descriptor({
          capture_id: CAPTURE_B,
          artifact_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          reference: { content_sha256: await sha256(bytes), byte_size: bytes.byteLength },
        }),
      ],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues.map((issue) => issue.state))
      .toEqual(['verification_failed', 'unplaced']);
    // One list request and exactly one byte request, not two.
    expect(requests).toHaveLength(2);
  });

  it('hands a map it already decoded back rather than fetching it again', async () => {
    const bytes = buildOpm();
    const reference = { content_sha256: await sha256(bytes), byte_size: bytes.byteLength };
    const client = new GeometryClient({
      baseUrl: 'https://exulanica.test/api',
      token: 'private-token',
      fetch: serve([descriptor({ reference })], bytes).fetch,
    });
    const first = await client.load(regions);
    expect(first.byArtifact.size).toBe(1);

    const second = serve([descriptor({ reference })], bytes);
    const again = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch: second.fetch,
    }).load(regions, first.byArtifact);

    expect(again.pointMaps.get(REGION as never)).toBe(first.pointMaps.get(REGION as never));
    expect(second.requests.map((request) => request.path)).toEqual(['/api/geometry']);
  });

  it('loses a region whose descriptor has gone, which is how a deletion reaches the renderer', async () => {
    const bytes = buildOpm();
    const reference = { content_sha256: await sha256(bytes), byte_size: bytes.byteLength };
    const client = new GeometryClient({
      baseUrl: 'https://exulanica.test/api',
      token: 'private-token',
      fetch: serve([descriptor({ reference })], bytes).fetch,
    });
    const first = await client.load(regions);
    expect(first.pointMaps.size).toBe(1);

    // The photograph was deleted, so the server no longer lists it. The held map must not
    // survive the list that stopped naming it.
    const after = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api',
      token: 'private-token',
      fetch: serve([], bytes).fetch,
    }).load(regions, first.byArtifact);

    expect(after.pointMaps.size).toBe(0);
    expect(after.byArtifact.size).toBe(0);
  });

  it('reports a state it has never heard of for that descriptor alone', async () => {
    /**
     * A closed union would be validated at list level and would take every region's geometry
     * away from every older client the day the wire gains a state for ADR-0009 D6 or D8.
     */
    const bytes = buildOpm();
    const { fetch } = serve(
      [
        descriptor({ capture_id: CAPTURE_B, state: 'withheld', reference: null }),
        descriptor({ reference: {
          content_sha256: await sha256(bytes), byte_size: bytes.byteLength,
        } }),
      ],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.issues.map((issue) => issue.state)).toEqual(['error']);
    expect(session.issues[0]!.reason).toContain('withheld');
    // And the descriptor it did understand still drew.
    expect(session.pointMaps.size).toBe(1);
  });

  it('abandons a request that never answers rather than hanging the world', async () => {
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/geometry')) {
        return json([descriptor({ reference: { content_sha256: 'd'.repeat(64), byte_size: 4 } })]);
      }
      // A half-open connection: it settles only when the signal aborts.
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(init.signal!.reason));
      });
    });
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
      signal: AbortSignal.timeout(20),
    }).load(regions);

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues[0]!.state).toBe('timed_out');
  });

  it('draws one reconstruction per region and counts the rest rather than hiding them', async () => {
    const bytes = buildOpm();
    const digest = await sha256(bytes);
    const reference = { content_sha256: digest, byte_size: bytes.byteLength };
    const { fetch, requests } = serve(
      [
        descriptor({ reference }),
        descriptor({
          capture_id: CAPTURE_B,
          artifact_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          reference: {
            ...reference,
            href: '/geometry/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          },
        }),
      ],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.pointMaps.size).toBe(1);
    expect(session.issues).toHaveLength(1);
    expect(session.issues[0]!.state).toBe('unplaced');
    expect(session.issues[0]!.captureId).toBe(CAPTURE_B);
    expect(session.issues[0]!.reason).toContain('placement record');
    // The second region's bytes were never fetched. It would have been three megabytes to draw
    // nothing with.
    expect(requests).toHaveLength(2);
  });

  it('keeps missing bytes, an unreadable container and a deletion distinct, and fetches none of them', async () => {
    const bytes = buildOpm();
    const { fetch, requests } = serve(
      [
        descriptor({
          state: 'bytes_missing',
          reason: 'the artifact row survived and its stored object did not',
          reference: null,
        }),
        descriptor({
          capture_id: CAPTURE_B,
          artifact_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          // OPM/1, which this build refuses by name. ADR-0010 D9 is refuse and regenerate, and
          // the descriptor says the version before the transfer starts, so the region is skipped
          // rather than sent several megabytes it could not have read.
          container: 'opm/1',
          reference: { href: '/geometry/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' },
        }),
      ],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues.map((issue) => issue.state))
      .toEqual(['bytes_missing', 'unsupported_container']);
    expect(session.issues[0]!.reason).toContain('stored object');
    expect(requests).toHaveLength(1);
  });

  it('reports a reconstruction the user deleted as deleted', async () => {
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/geometry')) {
        return json([descriptor({ reference: {
          content_sha256: 'b'.repeat(64), byte_size: 16,
        } })]);
      }
      return json({ code: 'tombstoned', detail: 'geometry was deleted' }, 410);
    });
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.issues[0]!.state).toBe('error');
    expect(session.issues[0]!.reason).toBe('This reconstruction was deleted.');
  });

  it('refuses a reference that does not name a local geometry path under a workspace bearer', async () => {
    const bytes = buildOpm();
    const { fetch, requests } = serve(
      [descriptor({ reference: {
        href: 'https://elsewhere.example/geometry/aaaa',
        content_sha256: await sha256(bytes),
        byte_size: bytes.byteLength,
      } })],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions);

    expect(session.issues[0]!.state).toBe('error');
    expect(session.issues[0]!.reason).toContain('provenance');
    expect(requests).toHaveLength(1);
  });

  it('refuses a content hash that is not a SHA-256, once, rather than per region', async () => {
    const { fetch } = serve(
      [descriptor({ reference: { content_sha256: 'not-a-hash', byte_size: 4 } })],
      buildOpm(),
    );
    await expect(new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(regions)).rejects.toThrow(/SHA-256/);
  });

  it('reports a reconstruction whose photograph has no region in this world', async () => {
    const bytes = buildOpm();
    const { fetch, requests } = serve(
      [descriptor({ reference: {
        content_sha256: await sha256(bytes), byte_size: bytes.byteLength,
      } })],
      bytes,
    );
    const session = await new GeometryClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
    }).load(new Map());

    expect(session.pointMaps.size).toBe(0);
    expect(session.issues[0]!.state).toBe('no_region');
    expect(requests).toHaveLength(1);
  });
});

describe('regions are resolved from the snapshot the world was drawn from', () => {
  it('maps every capture an island names, and nothing it does not', () => {
    const byCapture = regionsByCapture([
      { islandId: REGION, captureIds: [CAPTURE_A, CAPTURE_B] },
      { islandId: 'other', captureIds: [] },
    ]);
    expect(byCapture.get(CAPTURE_A)).toBe(REGION);
    expect(byCapture.get(CAPTURE_B)).toBe(REGION);
    expect(byCapture.get('never-ingested')).toBeUndefined();
  });
});

describe('the presentation frame is said out loud beside the rung', () => {
  it('claims upright only when the cameras agreed, and says so when they did not', () => {
    const agreeing = sceneDisplayFrame(
      [
        { position: [0, 3, 4], forward: [0, -0.6, -0.8], up: [0, 0.8, -0.6] },
        { position: [0, 3, -4], forward: [0, -0.6, 0.8], up: [0, 0.8, 0.6] },
      ],
      [[-1, 0, -1], [1, 0.5, 1]],
    );
    expect(agreeing.upMethod).toBe('camera-up-mean');
    expect(displayFrameSentence(agreeing)).toMatch(/^Displayed upright at [0-9.]+× nonmetric exhibit scale, with the recovered cameras at eye height\.$/);

    // A subject photographed from all around and turned over between series: opposite ups.
    const disagreeing = sceneDisplayFrame(
      [
        { position: [1, 0, 0], forward: [-1, 0, 0], up: [0, 1, 0] },
        { position: [-1, 0, 0], forward: [1, 0, 0], up: [0, -1, 0] },
      ],
      [],
    );
    expect(disagreeing.upMethod).toBe('scene-axes');
    expect(displayFrameSentence(disagreeing)).toMatch(
      /^Displayed on its recovered axes at [0-9.]+× nonmetric exhibit scale; its recovered cameras do not agree on an up direction, so no upright is claimed\.$/,
    );

    expect(displayFrameSentence(identityDisplayFrame())).toBe('Displayed on its recovered axes at 1.00× nonmetric exhibit scale.');
  });
});

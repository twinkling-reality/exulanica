import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  OBJECT_ORIGIN_LABELS,
  WorldObjectsClient,
  WorldObjectsContractError,
  objectWriteFailure,
  parseObject,
  parseReceipt,
  parseRegistry,
  parseVersion,
  safeObjectHref,
} from '../src/world-objects-api.js';

/**
 * The authored-object client, against the fixture of a contract nobody has implemented yet.
 *
 * `docs/world-objects-contract.md` is PROVISIONAL and so is
 * `packages/graph-client/test/fixtures/world-objects.json`. That is exactly why these tests read
 * the fixture from disk rather than building the responses inline: when the backend task replaces
 * that file, the parsers are what must fail, loudly and by field name, and a test that had
 * restated the shape in TypeScript would keep passing against a contract that had changed.
 *
 * The fixture is deliberately not all well-formed data. It carries an asset whose bytes are
 * unavailable and an object whose behaviour id this build does not support, because both are
 * states the interface is required to show honestly rather than cases to be filtered out.
 */

const FIXTURE = JSON.parse(readFileSync(
  new URL('../../graph-client/test/fixtures/world-objects.json', import.meta.url),
  'utf8',
)) as { assets: unknown; objects: unknown; placement: unknown };

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

function transport(responses: Readonly<Record<string, unknown>>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const method = init?.method ?? 'GET';
    calls.push({
      method,
      path,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    const answer = responses[`${method} ${path}`];
    if (answer === undefined) return new Response(null, { status: 404 });
    if (answer instanceof Response) return answer.clone();
    return new Response(JSON.stringify(answer), {
      status: 200, headers: { 'content-type': 'application/json' },
    });
  });
  return { calls, fetchImpl };
}

const problem = (status: number, code: string, detail: string) =>
  new Response(JSON.stringify({ code, detail }), {
    status, headers: { 'content-type': 'application/json' },
  });

function client(responses: Readonly<Record<string, unknown>>, ids?: () => string) {
  const { calls, fetchImpl } = transport(responses);
  return {
    calls,
    fetchImpl,
    subject: new WorldObjectsClient({
      baseUrl: 'https://exulanica.test',
      token: 'token',
      fetch: fetchImpl as unknown as typeof globalThis.fetch,
      ...(ids === undefined ? {} : { ids }),
    }),
  };
}

const ASSETS = 'GET /world-objects/assets';
const OBJECTS = 'GET /world-objects/versions/wv-0002/objects';
const PLACE = 'POST /world-objects/versions/wv-0002/objects';

describe('the reviewed asset registry, as the fixture publishes it', () => {
  it('renames every wire key and freezes what it returns', () => {
    const registry = parseRegistry(FIXTURE.assets);
    expect(registry.registryVersion).toBe(1);
    expect(registry.assets.map((asset) => asset.assetId))
      .toEqual(['standing-lantern', 'field-marker', 'withdrawn-figure']);
    const lantern = registry.assets[0]!;
    expect(lantern.label).toBe('Standing lantern');
    expect(lantern.container).toBe('glb/2.0');
    expect(lantern.origin).toBe('fictional-source');
    expect(lantern.footprint).toEqual({ radius: 0.28, height: 1.65 });
    expect(lantern.supportedBehaviours).toEqual(['motion.bounded']);
    expect(lantern.reference).toEqual({
      href: '/world-objects/assets/standing-lantern/bytes',
      contentSha256: '3d0f8a1c7b5e2949d6c81f34a70b52e8cd91647af0328b5d6e1c9407b2a8f351',
      byteSize: 20348,
    });
    expect(Object.isFrozen(registry.assets)).toBe(true);
    expect(Object.isFrozen(lantern.footprint)).toBe(true);
  });

  it('keeps an unavailable asset with a null reference rather than dropping it', () => {
    const registry = parseRegistry(FIXTURE.assets);
    const withdrawn = registry.assets.find((asset) => asset.assetId === 'withdrawn-figure')!;
    expect(withdrawn.reference).toBeNull();
    expect(withdrawn.supportedBehaviours).toEqual([]);
  });

  it('refuses a reference that does not declare workspace-bearer authorization', () => {
    const value = clone(FIXTURE.assets) as { assets: { reference: Record<string, unknown> | null }[] };
    value.assets[0]!.reference!['authorization'] = 'public';
    expect(() => parseRegistry(value)).toThrow(WorldObjectsContractError);
    expect(() => parseRegistry(value)).toThrow(/object asset authorization/);
  });

  it('refuses a remote or query-bearing asset href before anything can fetch it', () => {
    for (const href of [
      'https://elsewhere.test/lantern.glb',
      '/world-objects/assets/a/bytes?token=secret',
      '/geometry/artifacts/a/bytes',
    ]) {
      const value = clone(FIXTURE.assets) as { assets: { reference: Record<string, unknown> }[] };
      value.assets[0]!.reference['href'] = href;
      expect(() => parseRegistry(value)).toThrow(/object asset href/);
    }
    expect(safeObjectHref('/world-objects/assets/a/bytes')).toBe(true);
    expect(safeObjectHref('/world-objects/a#b')).toBe(false);
  });

  it('refuses a digest that is not a SHA-256, and a zero byte size', () => {
    const shortDigest = clone(FIXTURE.assets) as { assets: { reference: Record<string, unknown> }[] };
    shortDigest.assets[0]!.reference['content_sha256'] = 'abc';
    expect(() => parseRegistry(shortDigest)).toThrow(/content hash/);

    const noBytes = clone(FIXTURE.assets) as { assets: { reference: Record<string, unknown> }[] };
    noBytes.assets[0]!.reference['byte_size'] = 0;
    expect(() => parseRegistry(noBytes)).toThrow(/byte size/);
  });

  it('refuses an origin outside the reviewed vocabulary, and a duplicated asset id', () => {
    const badOrigin = clone(FIXTURE.assets) as { assets: { origin: string }[] };
    badOrigin.assets[0]!.origin = 'real';
    expect(() => parseRegistry(badOrigin)).toThrow(/object origin/);

    const duplicated = clone(FIXTURE.assets) as { assets: unknown[] };
    duplicated.assets.push(clone(duplicated.assets[0]));
    expect(() => parseRegistry(duplicated)).toThrow(/object asset registry/);
  });

  it('has a reviewed sentence for every role in the vocabulary', () => {
    for (const asset of parseRegistry(FIXTURE.assets).assets) {
      expect(OBJECT_ORIGIN_LABELS[asset.origin]).toEqual(expect.any(String));
    }
  });
});

describe('an authored world version, as the fixture publishes it', () => {
  it('reads the objects, their transforms and their lineage', () => {
    const version = parseVersion(FIXTURE.objects);
    expect(version.worldVersionId).toBe('wv-0002');
    expect(version.basedOnWorldVersionId).toBe('wv-0001');
    expect(version.objects).toHaveLength(3);
    const first = version.objects[0]!;
    expect(first.objectId).toBe('obj-0001');
    expect(first.regionId).toBe('region-volcanic');
    expect(first.sceneId).toBe('scene-volcanic-01');
    expect(first.sceneFromObject).toHaveLength(16);
    expect(first.sceneFromObject[3]).toBe(0.75);
    expect(first.behaviour).toEqual({
      behaviourId: 'motion.bounded',
      parameters: { axis: 'y', amplitude: 0.35, period: 4 },
    });
  });

  it('carries an object with no behaviour and one with an unsupported behaviour id', () => {
    const version = parseVersion(FIXTURE.objects);
    expect(version.objects[1]!.behaviour).toBeNull();
    // Unsupported ids reach the surface intact. Refusing them here would hide the failure the
    // milestone requires to be visible.
    expect(version.objects[2]!.behaviour?.behaviourId).toBe('motion.orbit');
  });

  it('leaves behaviour parameters unparsed, because the registry owns their vocabulary', () => {
    const version = parseVersion(FIXTURE.objects);
    expect(version.objects[2]!.behaviour?.parameters).toEqual({ radius: 2, period: 8 });
  });

  it('refuses a transform that is the wrong length or carries a non-finite number', () => {
    for (const bad of [[1, 2, 3], new Array(16).fill('x'), [...new Array(15).fill(0), null]]) {
      const value = clone(FIXTURE.objects) as { objects: { scene_from_object: unknown }[] };
      value.objects[0]!.scene_from_object = bad;
      expect(() => parseVersion(value)).toThrow(/object transform/);
    }
  });

  it('refuses two objects sharing an id, and a version with no record hash', () => {
    const duplicated = clone(FIXTURE.objects) as { objects: unknown[] };
    duplicated.objects.push(clone(duplicated.objects[0]));
    expect(() => parseVersion(duplicated)).toThrow(/authored object list/);

    const noHash = clone(FIXTURE.objects) as Record<string, unknown>;
    delete noHash['recorded_sha256'];
    expect(() => parseVersion(noHash)).toThrow(/world version record hash/);
  });

  it('refuses a bare array, a string and null where a record was promised', () => {
    for (const bad of [[], 'objects', null, 7]) {
      expect(() => parseVersion(bad)).toThrow(WorldObjectsContractError);
      expect(() => parseObject(bad)).toThrow(WorldObjectsContractError);
      expect(() => parseRegistry(bad)).toThrow(WorldObjectsContractError);
      expect(() => parseReceipt(bad)).toThrow(WorldObjectsContractError);
    }
  });
});

describe('the client reads both routes and writes through one queue', () => {
  it('sends the bearer to both read routes and holds what came back', async () => {
    const { subject, fetchImpl } = client({ [ASSETS]: FIXTURE.assets, [OBJECTS]: FIXTURE.objects });
    const connected = await subject.connect('wv-0002');
    expect(connected.registry.assets).toHaveLength(3);
    expect(connected.version.objects).toHaveLength(3);
    expect(subject.registry()).toBe(connected.registry);
    expect(subject.version()).toBe(connected.version);
    for (const [, init] of fetchImpl.mock.calls as unknown as [string, RequestInit][]) {
      expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer token');
    }
  });

  it('escapes a world version id into the path rather than interpolating it raw', async () => {
    const { subject, calls } = client({
      'GET /world-objects/versions/wv%2F..%2Fother/objects': FIXTURE.objects,
    });
    await subject.refreshObjects('wv/../other');
    expect(calls[0]!.path).toBe('/world-objects/versions/wv%2F..%2Fother/objects');
  });

  it('mints a proposal id and sends both base tokens on a placement', async () => {
    const { subject, calls } = client(
      { [ASSETS]: FIXTURE.assets, [OBJECTS]: FIXTURE.objects, [PLACE]: FIXTURE.placement },
      () => 'proposal-fixed',
    );
    const { version } = await subject.connect('wv-0002');
    const result = await subject.place(version, {
      assetId: 'standing-lantern',
      regionId: 'region-volcanic',
      sceneId: 'scene-volcanic-01',
      sceneFromObject: [1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 2, 0, 0, 0, 1],
      origin: 'fictional-source',
      behaviour: { behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 0.4, period: 3 } },
    });
    expect(result).toEqual({
      kind: 'recorded',
      receipt: {
        objectId: 'obj-0004',
        worldVersionId: 'wv-0003',
        basedOnWorldVersionId: 'wv-0002',
        recordedSha256: 'c40a7e18b3d962f5074ac1e8b25d3f9016ea7c4b8d20539fe671ba394c02d8f7',
        alreadyRecorded: false,
      },
    });
    const write = calls.find((call) => call.method === 'POST')!;
    expect(write.body).toEqual({
      assetId: 'standing-lantern',
      regionId: 'region-volcanic',
      sceneId: 'scene-volcanic-01',
      sceneFromObject: [1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 2, 0, 0, 0, 1],
      origin: 'fictional-source',
      behaviour: { behaviourId: 'motion.bounded', parameters: { axis: 'y', amplitude: 0.4, period: 3 } },
      proposalId: 'proposal-fixed',
      baseWorldVersionId: 'wv-0002',
      baseRecordedSha256: '9f2b6104c8ad35e7b0146fa9d283517ce640b8fa27d5913e04ac7be6182f0d94',
    });
  });

  it('refuses a malformed transform before it reaches the network', async () => {
    const { subject, calls } = client({ [ASSETS]: FIXTURE.assets, [OBJECTS]: FIXTURE.objects });
    const { version } = await subject.connect('wv-0002');
    const before = calls.length;
    await expect(subject.place(version, {
      assetId: 'standing-lantern',
      regionId: 'region-volcanic',
      sceneId: 'scene-volcanic-01',
      sceneFromObject: [Number.NaN, ...new Array(15).fill(0)],
      origin: 'fictional-source',
      behaviour: null,
    })).rejects.toThrow(/object transform/);
    await expect(subject.move(version, 'obj-0001', [1, 2, 3])).rejects.toThrow(/object transform/);
    expect(calls).toHaveLength(before);
  });

  it('addresses move, behaviour and removal as POSTs carrying the same base tokens', async () => {
    const receipt = { ...(FIXTURE.placement as Record<string, unknown>), object_id: 'obj-0001' };
    const { subject, calls } = client({
      [ASSETS]: FIXTURE.assets,
      [OBJECTS]: FIXTURE.objects,
      'POST /world-objects/versions/wv-0002/objects/obj-0001/transform': receipt,
      'POST /world-objects/versions/wv-0002/objects/obj-0001/behaviour': receipt,
      'POST /world-objects/versions/wv-0002/objects/obj-0001/removal': receipt,
    }, () => 'proposal-fixed');
    const { version } = await subject.connect('wv-0002');

    await subject.move(version, 'obj-0001', [1, 0, 0, 3, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    await subject.setBehaviour(version, 'obj-0001', null);
    await subject.remove(version, 'obj-0001');

    const writes = calls.filter((call) => call.method === 'POST');
    expect(writes.map((call) => call.path)).toEqual([
      '/world-objects/versions/wv-0002/objects/obj-0001/transform',
      '/world-objects/versions/wv-0002/objects/obj-0001/behaviour',
      '/world-objects/versions/wv-0002/objects/obj-0001/removal',
    ]);
    for (const write of writes) {
      expect(write.body).toMatchObject({
        proposalId: 'proposal-fixed',
        baseWorldVersionId: 'wv-0002',
        baseRecordedSha256: '9f2b6104c8ad35e7b0146fa9d283517ce640b8fa27d5913e04ac7be6182f0d94',
      });
    }
    expect(writes[1]!.body).toMatchObject({ behaviour: null });
  });

  it('reports a replayed proposal as a replay rather than as a second object', async () => {
    const replay = { ...(FIXTURE.placement as Record<string, unknown>), already_recorded: true };
    const { subject } = client({ [ASSETS]: FIXTURE.assets, [OBJECTS]: FIXTURE.objects, [PLACE]: replay });
    const { version } = await subject.connect('wv-0002');
    const result = await subject.place(version, {
      assetId: 'field-marker', regionId: 'region-volcanic', sceneId: 'scene-volcanic-01',
      sceneFromObject: new Array(16).fill(0).map((_, i) => (i % 5 === 0 ? 1 : 0)),
      origin: 'appearance-reference', behaviour: null,
    });
    expect(result.kind).toBe('recorded');
    if (result.kind !== 'recorded') throw new Error('unreachable');
    expect(result.receipt.alreadyRecorded).toBe(true);
  });

  it('turns a stale base into a re-read rather than into a thrown failure', async () => {
    const { subject, calls } = client({
      [ASSETS]: FIXTURE.assets,
      [OBJECTS]: FIXTURE.objects,
      [PLACE]: problem(409, 'stale_world_version', 'the world version moved'),
    });
    const { version } = await subject.connect('wv-0002');
    const result = await subject.place(version, {
      assetId: 'field-marker', regionId: 'region-volcanic', sceneId: 'scene-volcanic-01',
      sceneFromObject: new Array(16).fill(0).map((_, i) => (i % 5 === 0 ? 1 : 0)),
      origin: 'appearance-reference', behaviour: null,
    });
    expect(result.kind).toBe('stale');
    if (result.kind !== 'stale') throw new Error('unreachable');
    expect(result.current.worldVersionId).toBe('wv-0002');
    expect(calls.filter((call) =>
      call.method === 'GET' && call.path === '/world-objects/versions/wv-0002/objects'))
      .toHaveLength(2);
  });

  it('rethrows every other refusal instead of deciding it did not matter', async () => {
    for (const [status, code] of [
      [404, 'unknown_reference'], [410, 'tombstoned'], [424, 'unavailable_asset'],
      [422, 'unsupported_behaviour'], [401, 'unauthenticated'],
    ] as const) {
      const { subject } = client({
        [ASSETS]: FIXTURE.assets,
        [OBJECTS]: FIXTURE.objects,
        [PLACE]: problem(status, code, 'no'),
      });
      const { version } = await subject.connect('wv-0002');
      await expect(subject.place(version, {
        assetId: 'field-marker', regionId: 'region-volcanic', sceneId: 'scene-volcanic-01',
        sceneFromObject: new Array(16).fill(0).map((_, i) => (i % 5 === 0 ? 1 : 0)),
        origin: 'appearance-reference', behaviour: null,
      })).rejects.toBeInstanceOf(ApiError);
    }
  });

  it('serializes writes so two edits never race the same base', async () => {
    let inFlight = 0;
    let overlapped = false;
    const fetchSlow = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      if ((init?.method ?? 'GET') === 'GET') {
        const body = path.endsWith('/assets') ? FIXTURE.assets : FIXTURE.objects;
        return new Response(JSON.stringify(body), { status: 200 });
      }
      inFlight += 1;
      if (inFlight > 1) overlapped = true;
      await new Promise((resolve) => { setTimeout(resolve, 5); });
      inFlight -= 1;
      return new Response(JSON.stringify(FIXTURE.placement), { status: 200 });
    });
    const subject = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token',
      fetch: fetchSlow as unknown as typeof globalThis.fetch,
      ids: () => 'proposal-fixed',
    });
    const { version } = await subject.connect('wv-0002');
    const identity = new Array(16).fill(0).map((_, i) => (i % 5 === 0 ? 1 : 0));
    await Promise.all([
      subject.move(version, 'obj-0001', identity),
      subject.move(version, 'obj-0002', identity),
      subject.remove(version, 'obj-0003'),
    ]);
    expect(overlapped).toBe(false);
  });

  it('keeps writing after one write failed, rather than wedging the queue', async () => {
    let first = true;
    const fetchImpl = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      if ((init?.method ?? 'GET') === 'GET') {
        return new Response(
          JSON.stringify(path.endsWith('/assets') ? FIXTURE.assets : FIXTURE.objects),
          { status: 200 },
        );
      }
      if (first) {
        first = false;
        return new Response(JSON.stringify({ code: 'tombstoned', detail: 'gone' }), { status: 410 });
      }
      return new Response(JSON.stringify(FIXTURE.placement), { status: 200 });
    });
    const subject = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token',
      fetch: fetchImpl as unknown as typeof globalThis.fetch, ids: () => 'p',
    });
    const { version } = await subject.connect('wv-0002');
    await expect(subject.remove(version, 'obj-0001')).rejects.toThrow(/tombstoned/);
    await expect(subject.remove(version, 'obj-0002')).resolves.toMatchObject({ kind: 'recorded' });
  });
});

describe('a refusal reaches the surface in words', () => {
  it('says what each documented problem code means', () => {
    expect(objectWriteFailure(new ApiError(401, 'unauthenticated', 'no')))
      .toMatch(/not authorized/);
    expect(objectWriteFailure(new ApiError(404, 'unknown_reference', 'no')))
      .toMatch(/not in this workspace/);
    expect(objectWriteFailure(new ApiError(410, 'tombstoned', 'no'))).toMatch(/withdrawn/);
    expect(objectWriteFailure(new ApiError(424, 'unavailable_asset', 'no')))
      .toMatch(/not in storage/);
    expect(objectWriteFailure(new ApiError(422, 'unsupported_behaviour', 'no')))
      .toMatch(/not one this world supports/);
    expect(objectWriteFailure(new ApiError(422, 'invalid_object_state', 'the transform is not a similarity')))
      .toMatch(/the transform is not a similarity/);
  });

  it('passes an unrecognised code through with its own words', () => {
    expect(objectWriteFailure(new ApiError(500, 'internal', 'something broke')))
      .toBe('internal: something broke');
    expect(objectWriteFailure(new Error('offline'))).toBe('offline');
    expect(objectWriteFailure('nothing')).toBe('the write was refused');
  });

  it('names an invalid response as this client’s own contract failure', () => {
    expect(objectWriteFailure(new WorldObjectsContractError('invalid_response', 'bad shape')))
      .toBe('bad shape');
  });
});

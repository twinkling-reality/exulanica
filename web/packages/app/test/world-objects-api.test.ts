import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  MAX_SCALE_MILLI,
  MAX_YAW_MICRORADIANS,
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  WorldObjectsContractError,
  assertTransform,
  objectWriteFailure,
  parseAsset,
  parseObject,
  parseVersion,
  type AlternateVersion,
} from '../src/world-objects-api.js';

/**
 * The authored-object client, against the published contract fixture.
 *
 * `packages/graph-client/test/fixtures/world-objects.json` is one complete `GET
 * /world/versions/{id}` body, published by the backend task and declared stable: "fields may be
 * added, and no field in it may be renamed, retyped or removed". These tests read it from disk
 * rather than restating its shape in TypeScript, so that when it is replaced the parsers are what
 * fail, loudly and by field name.
 *
 * The fixture is not uniform data on purpose. It carries an object with a behaviour and one
 * without, and an edit log whose newest entry is an `undo` that names the removal before it. Both
 * are states the interface has to read correctly rather than cases to be filtered out.
 */

const FIXTURE = JSON.parse(readFileSync(
  new URL('../../graph-client/test/fixtures/world-objects.json', import.meta.url),
  'utf8',
)) as Record<string, unknown>;

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

function client(responses: Readonly<Record<string, unknown>>) {
  const { calls, fetchImpl } = transport(responses);
  return {
    calls,
    fetchImpl,
    subject: new WorldObjectsClient({
      baseUrl: 'https://exulanica.test',
      token: 'token',
      fetch: fetchImpl as unknown as typeof globalThis.fetch,
    }),
  };
}

const VERSION_ID = FIXTURE['version_id'] as string;
const ASSETS = 'GET /world/assets';
const VERSIONS = 'GET /world/versions';
const VERSION = `GET /world/versions/${VERSION_ID}`;
const ADD = `POST /world/versions/${VERSION_ID}/objects`;

const registryRows = () => (FIXTURE['objects'] as { asset: unknown }[]).map((row) => row.asset);

const transform = (over: Record<string, number> = {}) => ({
  xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 785_398, scaleMilli: 1000, ...over,
});

describe('the published version body, as the fixture publishes it', () => {
  it('renames every wire key of the envelope and freezes what it returns', () => {
    const version = parseVersion(FIXTURE);
    expect(version.schemaVersion).toBe(1);
    expect(version.versionId).toBe(VERSION_ID);
    expect(version.worldId).toBe('atlas:default');
    expect(version.parentVersionId).toBeNull();
    expect(version.title).toBe('Lantern study');
    expect(version.origin).toBe('authored');
    expect(version.styleVersionId).toBeNull();
    expect(version.stateSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(version.editSeq).toBe(5);
    expect(version.sourceInvalidated).toBe(false);
    expect(Object.isFrozen(version.objects)).toBe(true);
    expect(version.elementOverrides).toEqual([]);
  });

  it('reads an object, its embedded registry row and its fixed-point transform', () => {
    const version = parseVersion(FIXTURE);
    const lantern = version.objects.find((object) => object.objectId === 'object:lantern')!;
    expect(lantern.regionId).toBe('region-a');
    expect(lantern.origin).toEqual({ kind: 'authored', role: 'fictional' });
    expect(lantern.removed).toBe(false);
    expect(lantern.transform).toEqual({
      coordinateSpace: 'region_local',
      coordinateUnit: 'millimetre',
      xMm: 1200,
      yMm: 0,
      zMm: -450,
      yawMicroradians: 785_398,
      scaleMilli: 1000,
    });
    expect(lantern.asset.assetKey).toBe('cc0.marker-pillar');
    expect(lantern.asset.mediaType).toBe('model/gltf-binary');
    expect(lantern.asset.licenceId).toBe('CC0-1.0');
    expect(lantern.asset.availability).toBe('available');
    expect(lantern.asset.contentSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(lantern.behaviour).toEqual({
      behaviourKey: 'motion.bounded-path',
      behaviourVersion: 1,
      parameters: { axis: 'x', easing: 'smooth', travel_mm: 2000, period_milliseconds: 4000 },
    });
  });

  it('carries an object with no behaviour at all', () => {
    const version = parseVersion(FIXTURE);
    expect(version.objects.find((o) => o.objectId === 'object:plinth')!.behaviour).toBeNull();
  });

  it('leaves behaviour parameters unparsed, because the registry owns their vocabulary', () => {
    const lantern = parseVersion(FIXTURE).objects[0]!;
    expect(lantern.behaviour?.parameters['travel_mm']).toBe(2000);
  });

  it('reads the edit log in order, including an undo that names the edit it reversed', () => {
    const version = parseVersion(FIXTURE);
    expect(version.edits.map((edit) => edit.editSeq)).toEqual([1, 2, 3, 4, 5]);
    expect(version.edits.map((edit) => edit.kind))
      .toEqual(['add_object', 'add_object', 'move_object', 'remove_object', 'undo']);
    const undo = version.edits.at(-1)!;
    const removal = version.edits.find((edit) => edit.kind === 'remove_object')!;
    expect(undo.undoneEditId).toBe(removal.editId);
    // The removal was taken back, so the object it named is present and not removed.
    expect(version.objects.find((o) => o.objectId === undo.objectId)?.removed).toBe(false);
  });

  it('leaves the next undoable edit computable: the newest no undo already names', () => {
    const version = parseVersion(FIXTURE);
    const undone = new Set(version.edits.flatMap((e) => (e.undoneEditId === null ? [] : [e.undoneEditId])));
    const candidates = version.edits.filter((e) => e.kind !== 'undo' && !undone.has(e.editId));
    expect(candidates.map((e) => e.editSeq)).toEqual([1, 2, 3]);
    expect(candidates.at(-1)!.kind).toBe('move_object');
  });

  it('refuses an origin role outside the two the contract allows', () => {
    const value = clone(FIXTURE) as { objects: { origin: { role: string } }[] };
    value.objects[0]!.origin.role = 'documentary';
    expect(() => parseVersion(value)).toThrow(WorldObjectsContractError);
    expect(() => parseVersion(value)).toThrow(/authored object role/);
  });

  it('refuses a transform field that is not a whole number', () => {
    for (const [field, bad] of [
      ['x_mm', 1200.5], ['yaw_microradians', '0'], ['scale_milli', null],
    ] as const) {
      const value = clone(FIXTURE) as { objects: { transform: Record<string, unknown> }[] };
      value.objects[0]!.transform[field] = bad;
      expect(() => parseVersion(value)).toThrow(/transform/);
    }
  });

  it('refuses a state digest that is not a SHA-256, and a missing removal flag', () => {
    const badDigest = clone(FIXTURE) as Record<string, unknown>;
    badDigest['state_sha256'] = 'abc';
    expect(() => parseVersion(badDigest)).toThrow(/version state hash/);

    const noFlag = clone(FIXTURE) as { objects: Record<string, unknown>[] };
    delete noFlag.objects[0]!['removed'];
    expect(() => parseVersion(noFlag)).toThrow(/authored object removal/);
  });

  it('refuses two objects sharing an id', () => {
    const duplicated = clone(FIXTURE) as { objects: unknown[] };
    duplicated.objects.push(clone(duplicated.objects[0]));
    expect(() => parseVersion(duplicated)).toThrow(/authored object list/);
  });

  it('refuses a bare array, a string and null where a record was promised', () => {
    for (const bad of [[], 'version', null, 7]) {
      expect(() => parseVersion(bad)).toThrow(WorldObjectsContractError);
      expect(() => parseObject(bad)).toThrow(WorldObjectsContractError);
      expect(() => parseAsset(bad)).toThrow(WorldObjectsContractError);
    }
  });

  it('has a reviewed sentence for both roles in the vocabulary', () => {
    expect(OBJECT_ROLE_LABELS.fictional).toEqual(expect.any(String));
    expect(OBJECT_ROLE_LABELS.personal).toEqual(expect.any(String));
  });

  it('names no href at all, because an asset is addressed by key and checked by digest', () => {
    // The strongest form of "no remote asset URL is accepted": there is no URL on the wire to
    // accept. The bytes path is derived from `asset_key` by the renderer and never carried.
    expect(JSON.stringify(FIXTURE)).not.toContain('href');
    expect(JSON.stringify(FIXTURE)).not.toContain('http');
  });
});

describe('a transform is bounded before it costs a round trip', () => {
  it('accepts the fixture’s own transform', () => {
    expect(() => assertTransform(transform())).not.toThrow();
  });

  it('refuses a yaw outside one turn, which the server declares non-negative', () => {
    expect(() => assertTransform(transform({ yawMicroradians: -1 }))).toThrow(/yaw_microradians/);
    expect(() => assertTransform(transform({ yawMicroradians: MAX_YAW_MICRORADIANS + 1 })))
      .toThrow(/yaw_microradians/);
    expect(() => assertTransform(transform({ yawMicroradians: MAX_YAW_MICRORADIANS }))).not.toThrow();
  });

  it('refuses a scale of zero and one past the declared ceiling', () => {
    expect(() => assertTransform(transform({ scaleMilli: 0 }))).toThrow(/scale_milli/);
    expect(() => assertTransform(transform({ scaleMilli: MAX_SCALE_MILLI + 1 }))).toThrow(/scale_milli/);
  });

  it('refuses a float, because no IEEE-754 value may reach the digest', () => {
    expect(() => assertTransform(transform({ xMm: 1200.5 }))).toThrow(/x_mm/);
    expect(() => assertTransform(transform({ zMm: Number.NaN }))).toThrow(/z_mm/);
  });
});

describe('the client reads both routes and writes through one queue', () => {
  it('opens the newest version when none is named, and holds what came back', async () => {
    const { subject, fetchImpl } = client({ [ASSETS]: registryRows(), [VERSIONS]: [FIXTURE] });
    const connected = await subject.connect();
    expect(connected.assets).toHaveLength(2);
    expect(connected.version?.versionId).toBe(VERSION_ID);
    expect(subject.version()).toBe(connected.version);
    for (const [, init] of fetchImpl.mock.calls as unknown as [string, RequestInit][]) {
      expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer token');
    }
  });

  it('reads one named version when it is given one', async () => {
    const { subject, calls } = client({ [ASSETS]: registryRows(), [VERSION]: FIXTURE });
    await subject.connect(VERSION_ID);
    expect(calls.map((call) => call.path)).toContain(`/world/versions/${VERSION_ID}`);
  });

  it('reports no version rather than inventing one when the world has none', async () => {
    const { subject } = client({ [ASSETS]: registryRows(), [VERSIONS]: [] });
    const connected = await subject.connect();
    expect(connected.version).toBeNull();
  });

  it('escapes a version id into the path rather than interpolating it raw', async () => {
    const { subject, calls } = client({
      'GET /world/versions/a%2F..%2Fb': FIXTURE,
    });
    await subject.readVersion('a/../b').catch(() => undefined);
    expect(calls[0]!.path).toBe('/world/versions/a%2F..%2Fb');
  });

  it('sends the base state digest and snake_case fields on a placement', async () => {
    const { subject, calls } = client({
      [ASSETS]: registryRows(), [VERSIONS]: [FIXTURE], [ADD]: FIXTURE,
    });
    const { version } = await subject.connect();
    const result = await subject.place(version as AlternateVersion, {
      objectId: 'object:new',
      assetSha256: 'b'.repeat(64),
      regionId: 'region-a',
      transform: transform(),
      originRole: 'personal',
      behaviour: {
        behaviourKey: 'motion.bounded-path',
        behaviourVersion: 1,
        parameters: { axis: 'y', easing: 'linear', travel_mm: 1000, period_milliseconds: 4000 },
      },
    });
    expect(result.kind).toBe('recorded');

    const write = calls.find((call) => call.method === 'POST')!;
    expect(write.path).toBe(`/world/versions/${VERSION_ID}/objects`);
    expect(write.body).toEqual({
      object_id: 'object:new',
      asset_sha256: 'b'.repeat(64),
      region_id: 'region-a',
      transform: {
        x_mm: 1200, y_mm: 0, z_mm: -450, yaw_microradians: 785_398, scale_milli: 1000,
      },
      origin_role: 'personal',
      behaviour: {
        behaviour_key: 'motion.bounded-path',
        behaviour_version: 1,
        parameters: { axis: 'y', easing: 'linear', travel_mm: 1000, period_milliseconds: 4000 },
      },
      base_state_sha256: FIXTURE['state_sha256'],
    });
    // Not one camelCase key anywhere: the surface accepts snake_case only and forbids extras.
    expect(JSON.stringify(write.body)).not.toMatch(/[a-z][A-Z]/);
  });

  it('takes the whole version from the write, so a write is also the re-read', async () => {
    const moved = { ...clone(FIXTURE), edit_seq: 6 };
    const { subject, calls } = client({
      [ASSETS]: registryRows(), [VERSIONS]: [FIXTURE], [ADD]: moved,
    });
    const { version } = await subject.connect();
    const result = await subject.place(version as AlternateVersion, {
      objectId: 'object:new', assetSha256: 'b'.repeat(64), regionId: 'region-a',
      transform: transform(), originRole: 'fictional', behaviour: null,
    });
    if (result.kind !== 'recorded') throw new Error('unreachable');
    expect(result.version.editSeq).toBe(6);
    expect(subject.version()?.editSeq).toBe(6);
    // One POST and no follow-up GET of the version.
    expect(calls.filter((call) => call.method === 'GET' && call.path.includes('/versions/')))
      .toHaveLength(0);
  });

  it('refuses a malformed transform before it reaches the network', async () => {
    const { subject, calls } = client({ [ASSETS]: registryRows(), [VERSIONS]: [FIXTURE] });
    const { version } = await subject.connect();
    const before = calls.length;
    await expect(subject.place(version as AlternateVersion, {
      objectId: 'object:new', assetSha256: 'b'.repeat(64), regionId: 'region-a',
      transform: transform({ yawMicroradians: -1 }), originRole: 'fictional', behaviour: null,
    })).rejects.toThrow(/yaw_microradians/);
    await expect(subject.move(version as AlternateVersion, 'object:lantern', transform({ scaleMilli: 0 })))
      .rejects.toThrow(/scale_milli/);
    expect(calls).toHaveLength(before);
  });

  it('addresses move, remove and undo at the routes the contract names', async () => {
    const { subject, calls } = client({
      [ASSETS]: registryRows(),
      [VERSIONS]: [FIXTURE],
      [`POST /world/versions/${VERSION_ID}/objects/object%3Alantern/move`]: FIXTURE,
      [`POST /world/versions/${VERSION_ID}/objects/object%3Alantern/remove`]: FIXTURE,
      [`POST /world/versions/${VERSION_ID}/objects/undo`]: FIXTURE,
    });
    const { version } = await subject.connect();
    const base = version as AlternateVersion;

    await subject.move(base, 'object:lantern', transform({ xMm: 1500 }));
    await subject.remove(base, 'object:lantern');
    await subject.undo(base);

    const writes = calls.filter((call) => call.method === 'POST');
    expect(writes.map((call) => call.path)).toEqual([
      `/world/versions/${VERSION_ID}/objects/object%3Alantern/move`,
      `/world/versions/${VERSION_ID}/objects/object%3Alantern/remove`,
      `/world/versions/${VERSION_ID}/objects/undo`,
    ]);
    for (const write of writes) {
      expect(write.body).toMatchObject({ base_state_sha256: FIXTURE['state_sha256'] });
    }
    // Remove and undo are POSTs carrying only the base token, never DELETEs.
    expect(writes[1]!.body).toEqual({ base_state_sha256: FIXTURE['state_sha256'] });
    expect(writes[2]!.body).toEqual({ base_state_sha256: FIXTURE['state_sha256'] });
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false);
  });

  it('turns a stale base into a re-read rather than into a thrown failure', async () => {
    const { subject, calls } = client({
      [ASSETS]: registryRows(),
      [VERSIONS]: [FIXTURE],
      [VERSION]: FIXTURE,
      [ADD]: problem(409, 'stale_object_base', 'the version moved'),
    });
    const { version } = await subject.connect();
    const result = await subject.place(version as AlternateVersion, {
      objectId: 'object:new', assetSha256: 'b'.repeat(64), regionId: 'region-a',
      transform: transform(), originRole: 'fictional', behaviour: null,
    });
    expect(result.kind).toBe('stale');
    if (result.kind !== 'stale') throw new Error('unreachable');
    expect(result.current.versionId).toBe(VERSION_ID);
    expect(calls.filter((call) => call.method === 'GET' && call.path === `/world/versions/${VERSION_ID}`))
      .toHaveLength(1);
  });

  it('rethrows every other refusal instead of deciding it did not matter', async () => {
    for (const [status, code] of [
      [404, 'unknown_reference'], [409, 'invalid_object_state'],
      [409, 'invalidated_source_version'], [424, 'unavailable_asset'],
      [422, 'invalid_object_data'], [401, 'unauthenticated'],
    ] as const) {
      const { subject } = client({
        [ASSETS]: registryRows(),
        [VERSIONS]: [FIXTURE],
        [ADD]: problem(status, code, 'no'),
      });
      const { version } = await subject.connect();
      await expect(subject.place(version as AlternateVersion, {
        objectId: 'object:new', assetSha256: 'b'.repeat(64), regionId: 'region-a',
        transform: transform(), originRole: 'fictional', behaviour: null,
      })).rejects.toBeInstanceOf(ApiError);
    }
  });

  it('serializes writes so two edits never race the same base token', async () => {
    let inFlight = 0;
    let overlapped = false;
    const fetchSlow = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      if ((init?.method ?? 'GET') === 'GET') {
        const body = path === '/world/assets' ? registryRows() : [FIXTURE];
        return new Response(JSON.stringify(body), { status: 200 });
      }
      inFlight += 1;
      if (inFlight > 1) overlapped = true;
      await new Promise((resolve) => { setTimeout(resolve, 5); });
      inFlight -= 1;
      return new Response(JSON.stringify(FIXTURE), { status: 200 });
    });
    const subject = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token',
      fetch: fetchSlow as unknown as typeof globalThis.fetch,
    });
    const { version } = await subject.connect();
    const base = version as AlternateVersion;
    await Promise.all([
      subject.move(base, 'object:lantern', transform()),
      subject.move(base, 'object:plinth', transform()),
      subject.remove(base, 'object:lantern'),
    ]);
    expect(overlapped).toBe(false);
  });

  it('keeps writing after one write failed, rather than wedging the queue', async () => {
    let first = true;
    const fetchImpl = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      if ((init?.method ?? 'GET') === 'GET') {
        return new Response(
          JSON.stringify(path === '/world/assets' ? registryRows() : [FIXTURE]),
          { status: 200 },
        );
      }
      if (first) {
        first = false;
        return new Response(
          JSON.stringify({ code: 'invalid_object_state', detail: 'already removed' }),
          { status: 409 },
        );
      }
      return new Response(JSON.stringify(FIXTURE), { status: 200 });
    });
    const subject = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token',
      fetch: fetchImpl as unknown as typeof globalThis.fetch,
    });
    const { version } = await subject.connect();
    const base = version as AlternateVersion;
    await expect(subject.remove(base, 'object:lantern')).rejects.toThrow(/already removed/);
    await expect(subject.remove(base, 'object:plinth')).resolves.toMatchObject({ kind: 'recorded' });
  });
});

describe('a refusal reaches the surface in words', () => {
  it('says what each documented problem code means', () => {
    expect(objectWriteFailure(new ApiError(401, 'unauthenticated', 'no'))).toMatch(/not authorized/);
    expect(objectWriteFailure(new ApiError(404, 'unknown_reference', 'no')))
      .toMatch(/not in this workspace/);
    expect(objectWriteFailure(new ApiError(409, 'stale_object_base', 'no')))
      .toMatch(/changed while you were deciding/);
    expect(objectWriteFailure(new ApiError(409, 'invalid_object_state', 'already removed')))
      .toMatch(/already removed/);
    expect(objectWriteFailure(new ApiError(409, 'invalidated_source_version', 'no')))
      .toMatch(/was deleted/);
    expect(objectWriteFailure(new ApiError(424, 'unavailable_asset', 'no')))
      .toMatch(/not in storage/);
    expect(objectWriteFailure(new ApiError(422, 'invalid_object_data', 'transform out of range')))
      .toMatch(/transform out of range/);
  });

  it('names the body-shape refusal that arrives with no code of its own', () => {
    // A Pydantic 422 is `{detail: [...]}` with no `code`, so `toApiError` degrades to `http_422`
    // plus the status text. Left alone that reaches a person as "Unprocessable Entity".
    const degraded = new ApiError(422, 'http_422', 'Unprocessable Entity');
    expect(objectWriteFailure(degraded)).toMatch(/refused the shape of this edit/);
    expect(objectWriteFailure(degraded)).not.toMatch(/Unprocessable Entity/);
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


describe('alternate version bootstrap transport', () => {
  it('reads a base before confirmation and submits only that base', async () => {
    const calls: { path: string; method: string; body: unknown; authorization: string | null }[] = [];
    const client = new WorldObjectsClient({ baseUrl: 'https://fixture.test', token: 'fixture',
      fetch: async (input, init) => {
        const path = new URL(String(input)).pathname;
        calls.push({ path, method: init?.method ?? 'GET',
          body: init?.body ? JSON.parse(String(init.body)) : null,
          authorization: new Headers(init?.headers).get('Authorization') });
        return new Response(JSON.stringify(path.endsWith('/current')
          ? { current_topology_digest: 'reviewed-topology' } : { version_id: 'opened-version' }));
      },
    });
    const base = await client.bootstrapBase();
    expect(calls.map(c => c.method)).toEqual(['GET']);
    expect(await client.bootstrapVersion(base)).toBe('opened-version');
    expect(calls[1]).toEqual({ path: '/world/versions/bootstrap', method: 'POST',
      body: { base_topology_digest: 'reviewed-topology' }, authorization: 'Bearer fixture' });
  });
});

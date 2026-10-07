// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import { ThingLibrary, readThingLibrary, type PlacedThingRecord, type ThingLayerOptions, type ThingPick } from '@exulanica/atlas-react/things';
import { THING_PICK_EVENT, mountThings, signalColour, type ThingPickDetail } from '../src/composition/things.js';

// The layer draws and picks in the renderer, tested beside it (atlas-react things-layer.test.ts);
// here it stands in, recording what the page hands it, so the page's own part is what is tested.
const { FakeLayer, layers } = vi.hoisted(() => {
  const made: InstanceType<typeof Fake>[] = [];
  class Fake {
    placed: readonly PlacedThingRecord[] = [];
    picked: ThingPick | null = null;
    destroyed = false;
    constructor(readonly options: ThingLayerOptions) { made.push(this); }
    async setPlaced(things: readonly PlacedThingRecord[]) { this.placed = things; }
    pick() { return { pick: { placedId: this.placed[0]!.thingId, thingId: null, subjectId: null }, distance: 3 }; }
    setPicked(pick: ThingPick | null) { this.picked = pick; }
    get drawn() { return this.placed.map((one) => ({ placedId: one.thingId, lookKind: 'light', look: 'spirit-light/v1' })); }
    get misses() { return []; }
    destroy() { this.destroyed = true; }
  }
  return { FakeLayer: Fake, layers: made };
});
vi.mock('@exulanica/atlas-react/things', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/things')>()),
  ThingLayer: FakeLayer,
}));
import { THING_LIBRARY_PATH, openThingLibrary } from '../src/things-library.js';
import { parseVersion } from '../src/world-objects-api.js';
import { tokenBlock } from '../src/ui/system/token-values.js';

// The committed things catalogs, served as the host's thing library serves them.
const THINGS = join(dirname(fileURLToPath(String(import.meta.url))), '../../../../assets/catalogs/things');
const json = (path: string) => JSON.parse(readFileSync(join(THINGS, path), 'utf8')) as Record<string, unknown>;
const files = (dir: string) => readdirSync(join(THINGS, dir)).filter((n) => n.endsWith('.json')).sort().map((n) => `${dir}/${n}`);
const sha = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const canonical = (value: unknown): Uint8Array => {
  const sorted = (v: unknown): unknown => Array.isArray(v) ? v.map(sorted)
    : typeof v === 'object' && v !== null ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted((v as Record<string, unknown>)[k])])) : v;
  return new TextEncoder().encode(JSON.stringify(sorted(value)));
};

function served() {
  const bytes = new Map<string, Uint8Array>();
  const kinds = files('kinds').map((path) => {
    const doc = json(path); const raw = canonical(doc); bytes.set(sha(raw), raw);
    return { kind: doc['kind'], version: doc['version'], sha256: sha(raw), label: doc['label'], class: doc['class'], body_plan: (doc['body'] as { plan: string }).plan, looks: doc['looks'] };
  });
  const looks = files('looks').map((path) => {
    const doc = json(path); const raw = canonical(doc); bytes.set(sha(raw), raw);
    return { look: doc['look'], version: doc['version'], sha256: sha(raw), label: doc['label'], body_plan: doc['body_plan'], look_kind: doc['look_kind'], container: doc['container'] };
  });
  const plans = new Uint8Array(readFileSync(join(THINGS, 'body-plans.v1.json')));
  bytes.set(sha(plans), plans);
  const list = { profile: 'exulanica.thing-library/v1', kinds, looks, body_plans: { sha256: sha(plans) } };
  const kindRef = (kind: string) => ({ kind, version: 1, sha256: kinds.find((k) => k.kind === kind && k.version === 1)!.sha256 });
  return { list, bytes, kindRef };
}

const placedRow = (thingId: string, kind: { kind: string; version: number; sha256: string }, xMm: number, zMm: number) => ({
  thing_id: thingId, kind, region_id: 'region:starter',
  transform: { coordinate_space: 'region_local', coordinate_unit: 'millimetre', x_mm: xMm, y_mm: 0, z_mm: zMm, yaw_microradians: 0, scale_milli: 1000 },
  origin: { kind: 'authored', role: 'fictional' }, removed: false,
});

describe('the version document\'s placed things', () => {
  it('reads each placed thing: its kind by digest, its region and pose, never a look', () => {
    const { kindRef } = served();
    const version = parseVersion({
      schema_version: 5, version_id: 'v', world_id: 'w', source_snapshot_id: 's', parent_version_id: null, title: 't',
      origin: 'authored', style_version_id: null, state_sha256: '1'.repeat(64), edit_seq: 1, source_invalidated: false,
      created_by: 'a', created_at: '2026-10-06T00:00:00Z', objects: [], element_overrides: [], edits: [],
      things: [placedRow('knight-1', kindRef('knight'), 1000, 2000)],
    });
    expect(version.things).toEqual([{
      thingId: 'knight-1', kind: kindRef('knight'), regionId: 'region:starter',
      transform: { coordinateSpace: 'region_local', coordinateUnit: 'millimetre', xMm: 1000, yMm: 0, zMm: 2000, yawMicroradians: 0, scaleMilli: 1000 },
      origin: { kind: 'authored', role: 'fictional' }, removed: false,
    }]);
  });
});

describe('the host\'s thing library', () => {
  it('reads the list and each file by its digest, with the page\'s credentials', async () => {
    const { list, bytes, kindRef } = served();
    const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>)['Authorization']).toBe('Bearer token');
      const path = String(url).replace('https://example.test', '');
      if (path === THING_LIBRARY_PATH) return new Response(JSON.stringify(list));
      const held = bytes.get(path.slice(THING_LIBRARY_PATH.length + 1));
      return held === undefined ? new Response('', { status: 404 }) : new Response(held.buffer.slice(held.byteOffset, held.byteOffset + held.byteLength) as ArrayBuffer);
    });
    const library = await openThingLibrary({ baseUrl: 'https://example.test', token: 'token' }, fetcher as typeof fetch);
    const knight = kindRef('knight');
    expect((await library.kind({ key: knight.kind, version: 1, sha256: knight.sha256 })).bodyPlan).toBe('humanoid/v1');
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      `https://example.test${THING_LIBRARY_PATH}`, `https://example.test${THING_LIBRARY_PATH}/${knight.sha256}`,
    ]);
  });
});

describe('drawing the placed things and raising a pick', () => {
  it('hands the layer the version\'s things, raises one event for a pick, and rings what the event names', async () => {
    const fixture = served();
    const shell = document.createElement('div');
    const library = new ThingLibrary(readThingLibrary(fixture.list), async () => new ArrayBuffer(0));
    const region = { name: 'region' };
    const things = await mountThings({
      app: {} as never, camera: {} as never, shell, credentials: { baseUrl: 'https://example.test', token: 'token' },
      regionRoot: (id) => (id === 'region:starter' ? region as never : null), invalidate: vi.fn(), reducedMotion: () => false,
      library: async () => library,
    });
    const layer = layers.at(-1)!;
    expect(layer.options.library).toBe(library);
    expect(layer.options.ringColour).toBe(signalColour());
    const version = parseVersion({
      schema_version: 5, version_id: 'v', world_id: 'w', source_snapshot_id: 's', parent_version_id: null, title: 't',
      origin: 'authored', style_version_id: null, state_sha256: '1'.repeat(64), edit_seq: 1, source_invalidated: false,
      created_by: 'a', created_at: '2026-10-06T00:00:00Z', objects: [], element_overrides: [], edits: [],
      things: [placedRow('spirit-1', fixture.kindRef('lantern_spirit'), 0, -3000)],
    });
    await things.setPlaced(version.things!);
    expect(layer.placed).toEqual([{
      thingId: 'spirit-1', kind: fixture.kindRef('lantern_spirit'), regionId: 'region:starter',
      transform: { xMm: 0, yMm: 0, zMm: -3000, yawMicroradians: 0, scaleMilli: 1000 }, removed: false,
    }]);
    const heard: ThingPickDetail[] = [];
    shell.addEventListener(THING_PICK_EVENT, (event) => heard.push((event as CustomEvent<ThingPickDetail>).detail));
    const hit = things.pick([0, 1.25, 2], [0, 0, -1])!;
    things.raise(hit.pick, 'aim');
    expect(heard).toEqual([{ placedId: 'spirit-1', thingId: null, subjectId: null, via: 'aim' }]);
    expect(layer.picked).toEqual({ placedId: 'spirit-1', thingId: null, subjectId: null });
    // A card closing raises the same event with nothing in it, and the ring goes.
    shell.dispatchEvent(new CustomEvent(THING_PICK_EVENT, { detail: null }));
    expect(layer.picked).toBeNull();
    things.destroy();
    expect(layer.destroyed).toBe(true);
    // Once taken down, the page no longer rings what an event names.
    shell.dispatchEvent(new CustomEvent(THING_PICK_EVENT, { detail: { placedId: 'spirit-1', thingId: null, subjectId: null, via: 'mark' } }));
    expect(layer.picked).toBeNull();
  });

  it('rings in the design tokens\' signal colour', () => {
    expect(signalColour()).toBe(tokenBlock(':root').get('--color-signal')!.toLowerCase());
  });
});

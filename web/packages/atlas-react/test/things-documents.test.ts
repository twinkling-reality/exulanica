import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import {
  ThingDocumentRefused,
  drawnHeightMm,
  readBodyPlans,
  readKindDrawing,
  readLookDrawing,
  readThingLibrary,
} from '../src/playcanvas/things/documents.js';
import { LibraryRefused, ThingLibrary } from '../src/playcanvas/things/library.js';
import { placeDrawing, type SeatingLayout } from '../src/playcanvas/society/seating.js';

const THINGS = new URL('../../../../assets/catalogs/things/', import.meta.url);
const read = (path: string) => readFileSync(new URL(path, THINGS));
const json = (path: string) => JSON.parse(read(path).toString('utf8')) as Record<string, unknown>;
const files = (dir: string) => readdirSync(new URL(`${dir}/`, THINGS)).filter((name) => name.endsWith('.json')).map((name) => `${dir}/${name}`);
const sha = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
/** A document's canonical bytes, which its digest names: sorted keys, no white space, UTF-8. */
function canonical(value: unknown): Uint8Array {
  const sorted = (v: unknown): unknown => Array.isArray(v)
    ? v.map(sorted)
    : typeof v === 'object' && v !== null
      ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, sorted((v as Record<string, unknown>)[key])]))
      : v;
  return new TextEncoder().encode(JSON.stringify(sorted(value)));
}

describe('the shipped things documents, read as the drawing reads them', () => {
  it('reads every shipped look with the figures its document states', () => {
    for (const path of files('looks')) {
      const doc = json(path);
      const look = readLookDrawing(doc);
      expect(look.look).toBe(doc['look']);
      expect(look.lookKind).toBe(doc['look_kind']);
      expect(look.bodyPlan).toBe(doc['body_plan']);
      expect(look.container?.sha256 ?? null).toBe((doc['container'] as { sha256: string } | null)?.sha256 ?? null);
      expect(look.heightMm).toBe(doc['height_mm']);
      const light = doc['light'] as { colour: string; intensity_milli: number; radius_mm: number } | null;
      expect(look.light).toEqual(light === null ? null : { colour: light.colour, intensityMilli: light.intensity_milli, radiusMm: light.radius_mm });
    }
  });

  it('reads every shipped kind: its body and, for a holdable thing, its grip', () => {
    for (const path of files('kinds')) {
      const doc = json(path);
      const kind = readKindDrawing(doc);
      const body = doc['body'] as Record<string, unknown>;
      expect(kind.bodyPlan).toBe(body['plan']);
      expect(kind.boxMm).toEqual(body['box_mm'] ?? null);
      expect(kind.heightMm).toEqual(body['height_mm'] ?? null);
      expect(kind.radiusMm).toEqual(body['radius_mm'] ?? null);
      const holdable = (doc['offers'] as { key: string; parameters: Record<string, unknown> }[]).find((offer) => offer.key === 'holdable');
      expect(kind.grip).toEqual(holdable === undefined ? null : { ...(holdable.parameters['grip'] as object), axis: holdable.parameters['axis'] });
      expect(kind.looks.map((look) => look.key)).toEqual((doc['looks'] as { look: string }[]).map((look) => look.look));
    }
  });

  it('reads every shipped kind\'s places, as its one offer stating them says, seats and all', () => {
    for (const path of files('kinds')) {
      const doc = json(path);
      const offer = (doc['offers'] as { key: string; parameters: Record<string, unknown> }[]).find((one) => 'places' in one.parameters);
      const places = offer?.parameters['places'] as { x_mm: number; y_mm: number; faces: string; seat: { x_mm: number; y_mm: number; z_mm: number; faces: string } | null }[] | undefined;
      expect(readKindDrawing(doc).use).toEqual(offer === undefined ? null : {
        affordance: offer.key,
        places: places!.map((place) => ({
          positionMm: [place.x_mm, place.y_mm], faces: place.faces,
          seat: place.seat === null ? null : { positionMm: [place.seat.x_mm, place.seat.y_mm, place.seat.z_mm], faces: place.seat.faces },
        })),
      });
    }
    expect(readKindDrawing(json('kinds/bench.v2.json')).use?.places?.every((place) => place.seat !== null)).toBe(true);
    expect(readKindDrawing(json('kinds/sword.v2.json')).use).toBeNull();
  });

  it('seats a resting person on a placed bench at the place the society recorded, straight or turned', () => {
    const use = readKindDrawing(json('kinds/bench.v2.json')).use!;
    // The two benches and the place points their society recorded on a live town (MOTION, 23 October):
    // one straight, one turned a quarter, their places turned outward to the whole millimetre.
    const layout: SeatingLayout = {
      uses: new Map([['thing:straight', use], ['thing:turned', use]]),
      objects: [
        { objectId: 'straight', assetKey: 'thing:straight', xMm: 126_000, yMm: 0, zMm: -71_500, yawMicroradians: 0, scaleMilli: 1000 },
        { objectId: 'turned', assetKey: 'thing:turned', xMm: 121_000, yMm: 0, zMm: -71_500, yawMicroradians: 1_570_796, scaleMilli: 1000 },
      ],
      targets: new Map([['thing:straight:rest', 'straight'], ['thing:turned:rest', 'turned']]),
    };
    const straight = placeDrawing(layout, 'thing:straight:rest', [126_000, -72_520]);
    expect(straight.kind).toBe('place');
    const sat = (straight as Extract<typeof straight, { kind: 'place' }>).drawing;
    expect(sat.placeIndex).toBe(1);
    expect(sat.seat!.position.map((v) => Math.round(v * 1000))).toEqual([126_000, 480, -71_520]);
    const turned = placeDrawing(layout, 'thing:turned:rest', [119_980, -72_203]);
    expect(turned.kind).toBe('place');
    const turnedSat = (turned as Extract<typeof turned, { kind: 'place' }>).drawing;
    expect(turnedSat.placeIndex).toBe(2);
    expect(turnedSat.seat!.position.map((v) => Math.round(v * 1000))).toEqual([120_980, 480, -72_202]);
    // Faced from the front the bench is turned to, a quarter turn from the straight one's.
    expect(Math.abs(Math.abs(turnedSat.seat!.facing - sat.seat!.facing) - Math.PI / 2)).toBeLessThan(1e-5);
  });

  it('reads the body plans catalog: every bone and socket, the parents resolving', () => {
    const doc = json('body-plans.v1.json') as { entries: { key: string; version: number; bones: unknown[]; sockets: unknown[] }[] };
    const plans = readBodyPlans(doc);
    for (const entry of doc.entries) {
      const plan = plans.get(`${entry.key}/v${entry.version}`)!;
      expect(plan.bones).toEqual(entry.bones);
      expect(plan.sockets).toEqual(entry.sockets);
    }
  });

  it('refuses by name what it cannot read, naming the field', () => {
    const look = json('looks/spirit-light.v1.json');
    const refused = (value: unknown, reader: (v: unknown) => unknown) => {
      try {
        reader(value);
      } catch (error) {
        expect(error).toBeInstanceOf(ThingDocumentRefused);
        return [(error as ThingDocumentRefused).reason, (error as ThingDocumentRefused).field];
      }
      return null;
    };
    expect(refused(look, readLookDrawing)).toBeNull();
    expect(refused({ ...look, profile: 'exulanica.look/v9' }, readLookDrawing)).toEqual(['look_invalid', 'profile']);
    expect(refused({ ...look, sampling: 'cubic' }, readLookDrawing)).toEqual(['look_invalid', 'sampling']);
    expect(refused({ ...look, light: { colour: 'gold', intensity_milli: 1, radius_mm: 1 } }, readLookDrawing)).toEqual(['look_invalid', 'light.colour']);
    const sword = json('looks/primitive-sword.v1.json');
    expect(refused({ ...sword, container: { ...(sword['container'] as object), media_type: 'model/gltf+json' } }, readLookDrawing)).toEqual(['look_invalid', 'container.media_type']);
    const kind = json('kinds/sword.v1.json');
    expect(refused(kind, readKindDrawing)).toBeNull();
    expect(refused({ ...kind, body: { plan: 'rigid' } }, readKindDrawing)).toEqual(['thing_kind_invalid', 'body.plan']);
    const bench = json('kinds/bench.v2.json') as { offers: { key: string; parameters: { places: Record<string, unknown>[] } }[] };
    const sideways = JSON.parse(JSON.stringify(bench)) as typeof bench;
    sideways.offers[0]!.parameters.places[0]!['faces'] = 'up';
    expect(refused(sideways, readKindDrawing)).toEqual(['thing_kind_invalid', 'offers[0].parameters.places[0].faces']);
    expect(refused({ libraries: [] }, readThingLibrary)).toEqual(['thing_library_invalid', 'kinds']);
  });

  it('draws a look at its natural height, kept inside its kind\'s height range', () => {
    const knight = readKindDrawing(json('kinds/knight.v1.json'));
    const blocky = readLookDrawing(json('looks/blocky-knight.v1.json'));
    const range = json('kinds/knight.v1.json')['body'] as { height_mm: { from: number; to: number } };
    expect(drawnHeightMm(knight, blocky)).toBe(Math.min(range.height_mm.to, Math.max(range.height_mm.from, blocky.heightMm!)));
    expect(drawnHeightMm(knight, { ...blocky, heightMm: 2543 })).toBe(range.height_mm.to);
    expect(drawnHeightMm(knight, { ...blocky, heightMm: 900 })).toBe(range.height_mm.from);
  });
});

/** The library list the host would serve for the shipped documents, built from the files. */
function shippedLibrary() {
  const bytes = new Map<string, Uint8Array>();
  // Kinds and looks are served as their canonical bytes; the body plans catalog as its file.
  const kinds = files('kinds').map((path) => {
    const doc = json(path);
    const raw = canonical(doc);
    bytes.set(sha(raw), raw);
    return { kind: doc['kind'], version: doc['version'], sha256: sha(raw), label: doc['label'], class: doc['class'], body_plan: (doc['body'] as { plan: string }).plan, looks: doc['looks'] };
  });
  const looks = files('looks').map((path) => {
    const doc = json(path);
    const raw = canonical(doc);
    bytes.set(sha(raw), raw);
    return { look: doc['look'], version: doc['version'], sha256: sha(raw), label: doc['label'], body_plan: doc['body_plan'], look_kind: doc['look_kind'], container: doc['container'] };
  });
  const plans = new Uint8Array(read('body-plans.v1.json'));
  bytes.set(sha(plans), plans);
  return { list: readThingLibrary({ profile: 'exulanica.thing-library/v1', kinds, looks, body_plans: { sha256: sha(plans) } }), bytes };
}

describe('the thing library, by digest', () => {
  it('names each shipped kind by the digest of its file, as the kinds name their looks', () => {
    const { list } = shippedLibrary();
    for (const kind of list.kinds) {
      for (const look of kind.looks) {
        // A kind's look references are the digests of the look files the library holds.
        expect(list.looks.find((one) => one.look === look.key && one.version === look.version)?.sha256).toBe(look.sha256);
      }
    }
  });

  it('reads a document only after its bytes are held to its digest, once a digest', async () => {
    const { list, bytes } = shippedLibrary();
    const fetch = vi.fn(async (digest: string) => {
      const held = bytes.get(digest)!;
      return held.buffer.slice(held.byteOffset, held.byteOffset + held.byteLength) as ArrayBuffer;
    });
    const library = new ThingLibrary(list, fetch);
    const sword = list.kinds.find((kind) => kind.kind === 'sword' && kind.version === 1)!;
    const named = { key: sword.kind, version: sword.version, sha256: sword.sha256 };
    expect((await library.kind(named)).grip?.axis).toBe('+z');
    await library.kind(named);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect((await library.bodyPlans()).has('humanoid/v1')).toBe(true);
  });

  it('refuses other bytes than the digest names, and a reference the library does not hold', async () => {
    const { list, bytes } = shippedLibrary();
    const sword = list.kinds.find((kind) => kind.kind === 'sword' && kind.version === 1)!;
    const named = { key: sword.kind, version: sword.version, sha256: sword.sha256 };
    const other = bytes.get(list.bodyPlansSha256)!;
    const swapped = new ThingLibrary(list, async () => other.buffer.slice(other.byteOffset, other.byteOffset + other.byteLength) as ArrayBuffer);
    await expect(swapped.kind(named)).rejects.toMatchObject({ reason: 'digest_mismatch' });
    const honest = new ThingLibrary(list, async (digest) => {
      const held = bytes.get(digest)!;
      return held.buffer.slice(held.byteOffset, held.byteOffset + held.byteLength) as ArrayBuffer;
    });
    await expect(honest.kind({ ...named, sha256: '0'.repeat(64) })).rejects.toBeInstanceOf(LibraryRefused);
    await expect(honest.kind({ ...named, sha256: '0'.repeat(64) })).rejects.toMatchObject({ reason: 'not_in_library' });
    // The same refusal never leaves the honest answer unread.
    expect((await honest.kind(named)).kind).toBe('sword');
  });
});

import { describe, expect, it } from 'vitest';
import { LibraryRefused, ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { canonicalBytes, servedLibrary, sha256 } from './things-fixtures.js';

/*
 * A kind a world names by its digest alone is one its workspace keeps, a creature drafted from a
 * person's words: asked of the workspace by that digest, held to it, its key and version its own
 * document's; and the drafted body plan it is drawn on is asked by the digest the kind names and
 * held to it and to the plan its look names. The plan and kind here are written by hand in the
 * shapes the server's builder writes (`exulanica.body-plan/v1`, `exulanica.thing-kind/v1`).
 */

const buffer = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;

const plan = {
  profile: 'exulanica.body-plan/v1',
  key: 'hill_walker',
  version: 1,
  title: 'hill walker',
  bones: [
    { name: 'root', parent: null, required: true },
    { name: 'body', parent: 'root', required: true },
    { name: 'head', parent: 'body', required: true },
  ],
  limbs: [],
  sockets: [],
  size: { extent_mm: { length: { from: 900, to: 1100 }, width: { from: 300, to: 400 }, height: { from: 800, to: 1000 }, span: { from: 0, to: 0 } } },
  reach_mm: null,
  motions: { required: ['idle', 'walk'], optional: [] },
  moves: ['exulanica-movement/walking/v1'],
  reason: 'Written by hand for this test.',
  origin: { kind: 'drafted' },
};
const planRaw = canonicalBytes(plan);
const planDigest = sha256(planRaw);
const kind = {
  profile: 'exulanica.thing-kind/v1',
  kind: 'hill_walker',
  version: 1,
  label: 'hill walker',
  class: 'being',
  body: { plan: 'hill_walker/v1', plan_sha256: planDigest, extent_mm: { length: 1000, width: 350, height: 900, span: 0 } },
  looks: [{ look: 'hill_walker_sketch', version: 1, sha256: 'd'.repeat(64) }],
};
const kindRaw = canonicalBytes(kind);
const kindDigest = sha256(kindRaw);

function store(answers: Readonly<Record<string, Uint8Array>>) {
  const asked: string[] = [];
  const get = (field: string) => async (digest: string) => {
    asked.push(`${field}:${digest}`);
    const found = answers[`${field}:${digest}`];
    return found === undefined ? null : buffer(found);
  };
  const held: HeldThings = { kind: get('kind'), look: get('look'), container: get('container'), plan: get('plan') };
  return { held, asked };
}

describe('a kind a world names by its digest alone', () => {
  it('is read from its workspace by that digest, naming the drafted plan it is drawn on', async () => {
    const served = servedLibrary();
    const { held, asked } = store({ [`kind:${kindDigest}`]: kindRaw });
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const drawing = await library.kind({ source: 'workspace', sha256: kindDigest });
    expect([drawing.kind, drawing.version, drawing.bodyPlan, drawing.bodyPlanSha256]).toEqual(['hill_walker', 1, 'hill_walker/v1', planDigest]);
    expect(asked).toEqual([`kind:${kindDigest}`]);
    // A digest its workspace does not hold is not in the library.
    await expect(library.kind({ source: 'workspace', sha256: 'e'.repeat(64) })).rejects.toThrow(LibraryRefused);
  });

  it('is drawn on the plan its workspace holds at the digest it names, and on no other', async () => {
    const served = servedLibrary();
    const { held } = store({ [`plan:${planDigest}`]: planRaw, [`plan:${'f'.repeat(64)}`]: planRaw });
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const entry = await library.heldPlan(planDigest, 'hill_walker/v1');
    expect(entry?.bones.map((bone) => bone.name)).toEqual(['root', 'body', 'head']);
    // Another plan's name, a digest its workspace does not hold, and bytes that are not the digest's.
    expect(await library.heldPlan(planDigest, 'other_walker/v1')).toBeNull();
    expect(await library.heldPlan('a'.repeat(64), 'hill_walker/v1')).toBeNull();
    await expect(library.heldPlan('f'.repeat(64), 'hill_walker/v1')).rejects.toMatchObject({ reason: 'digest_mismatch' });
  });
});

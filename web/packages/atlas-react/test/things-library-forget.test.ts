import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { LibraryRefused, ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { canonicalBytes, servedLibrary, sha256 } from './things-fixtures.js';

/*
 * A page keeps what it read of a workspace's own kind for as long as it is open. When the kind's
 * maker erases it, the page forgets it too: its kind, its drafted plan and its looks are asked of
 * the workspace again, which no longer holds them. The creature is the dragon this server
 * assembles (`scripts/things/creature_plan_fixtures.py`), with a stand-in for its container.
 */

const fixture = JSON.parse(readFileSync(new URL('./fixtures/creature-plans/dragon.json', import.meta.url), 'utf8')) as {
  plan: unknown; kind: { label: string }; look: { look: string; version: number; container: { sha256: string; bytes: number } };
};
const buffer = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
const container = new TextEncoder().encode('a stand-in for the sketch container of a drafted body');
// The look as the workspace would keep it, naming the stand-in container; the kind names that look.
const look = { ...fixture.look, container: { ...fixture.look.container, sha256: sha256(container), bytes: container.byteLength } };
const lookRaw = canonicalBytes(look);
const planRaw = canonicalBytes(fixture.plan);
const kind = { ...fixture.kind, looks: [{ look: look.look, version: look.version, sha256: sha256(lookRaw) }], body: { ...(fixture.kind as unknown as { body: object }).body, plan_sha256: sha256(planRaw) } };
const kindRaw = canonicalBytes(kind);
const DIGEST = { kind: sha256(kindRaw), look: sha256(lookRaw), plan: sha256(planRaw) };

/** A workspace that holds the creature until it is erased, counting what it is asked. */
function workspace() {
  const asked: string[] = [];
  let erased = false;
  const answer = (field: string, bytes: Readonly<Record<string, Uint8Array>>) => async (digest: string) => {
    asked.push(`${field}:${digest}`);
    const found = erased ? undefined : bytes[digest];
    return found === undefined ? null : buffer(found);
  };
  const held: HeldThings = {
    kind: answer('kind', { [DIGEST.kind]: kindRaw }),
    look: answer('look', { [DIGEST.look]: lookRaw }),
    plan: answer('plan', { [DIGEST.plan]: planRaw }),
    container: answer('container', { [DIGEST.look]: container }),
  };
  return { held, asked, erase: () => { erased = true; } };
}

const refusal = async (promise: Promise<unknown>) => {
  try { await promise; } catch (error) { return error instanceof LibraryRefused ? error.reason : String(error); }
  return 'read';
};

async function readAll(library: ThingLibrary) {
  const document = await library.kindDocument({ source: 'workspace', sha256: DIGEST.kind }) as { label: string };
  const drawing = await library.look({ key: look.look, version: look.version, sha256: DIGEST.look });
  const plan = await library.heldPlan(DIGEST.plan, 'fixture_dragon/v1');
  const bytes = await library.container(drawing.container!);
  return { label: document.label, plan: plan?.key ?? null, container: bytes.byteLength };
}

describe('a creature its maker erased', () => {
  it('is kept by the page while the workspace holds it: read once, then answered from what the page keeps', async () => {
    const served = servedLibrary();
    const { held, asked, erase } = workspace();
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    expect(await readAll(library)).toEqual({ label: 'fixture dragon', plan: 'fixture_dragon', container: container.byteLength });
    expect(asked).toHaveLength(4);
    // Positive control: with nothing forgotten the page still answers after the erasure, from its own copy.
    erase();
    expect(await readAll(library)).toEqual({ label: 'fixture dragon', plan: 'fixture_dragon', container: container.byteLength });
    expect(asked).toHaveLength(4);
  });

  it('is forgotten by the page: its kind, its plan, its look and the look\'s container are asked again and no longer held', async () => {
    const served = servedLibrary();
    const { held, asked, erase } = workspace();
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const drawing = await library.look({ key: look.look, version: look.version, sha256: DIGEST.look });
    await readAll(library);
    erase();
    await library.forgetHeldKind(DIGEST.kind);
    const before = asked.length;
    expect(await refusal(library.kindDocument({ source: 'workspace', sha256: DIGEST.kind }))).toBe('not_in_library');
    expect(await refusal(library.look({ key: look.look, version: look.version, sha256: DIGEST.look }))).toBe('not_in_library');
    expect(await library.heldPlan(DIGEST.plan, 'fixture_dragon/v1')).toBeNull();
    expect(await refusal(library.container(drawing.container!))).not.toBe('read');
    // Each was asked of the workspace again: nothing was answered from memory.
    expect(asked.slice(before).map((one) => one.split(':')[0]).sort()).toEqual(['kind', 'look', 'plan']);
  });

  it('forgets nothing of a shipped kind, and nothing for a kind it never read', async () => {
    const served = servedLibrary();
    const { held, asked } = workspace();
    const fetched: string[] = [];
    const library = new ThingLibrary(served.list, (digest) => { fetched.push(digest); return served.fetch(digest); }, held);
    const knight = served.kindRef('knight', 1);
    const named = { key: knight.kind, version: knight.version, sha256: knight.sha256 };
    const first = await library.kindDocument(named);
    expect(fetched).toEqual([knight.sha256]);
    await library.forgetHeldKind(knight.sha256);
    await library.forgetHeldKind('e'.repeat(64));
    expect(await library.kindDocument(named)).toEqual(first);
    // Still answered from what the page keeps: the shipped library was not asked again.
    expect(fetched).toEqual([knight.sha256]);
    expect(asked).toEqual([]);
  });
});

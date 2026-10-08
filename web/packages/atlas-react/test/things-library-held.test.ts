import { describe, expect, it } from 'vitest';
import { LibraryRefused, ThingLibrary, type HeldThings } from '../src/playcanvas/things/library.js';
import { canonicalBytes, servedLibrary, sha256, thingsJson } from './things-fixtures.js';

/*
 * A look the shipped list does not hold may be the workspace's own: asked by the same digest, held to
 * it, and its container held to the digest its own document names. The workspace's look here is the
 * shipped blocky traveller's document with a container of its own, as a player's built look would be;
 * every digest is the fixture's, computed apart from the library.
 */

const buffer = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;

function workspaceLook(key = 'own-traveller') {
  const container = new TextEncoder().encode('glTF stand-in container of a workspace look');
  const document = {
    ...thingsJson('looks/blocky-traveller.v1.json'),
    look: key,
    label: 'own traveller',
    container: { sha256: sha256(container), bytes: container.byteLength, media_type: 'model/gltf-binary' },
  };
  const raw = canonicalBytes(document);
  return { document, raw, digest: sha256(raw), container };
}

/** A workspace's store holding `looks` by digest, counting what it is asked. */
function store(looks: ReturnType<typeof workspaceLook>[], answer?: (digest: string) => Uint8Array | null) {
  const asked: string[] = [];
  const held: HeldThings = {
    kind: async (digest) => { asked.push(`kind:${digest}`); return null; },
    look: async (digest) => {
      asked.push(`look:${digest}`);
      if (answer !== undefined) { const bytes = answer(digest); return bytes === null ? null : buffer(bytes); }
      const found = looks.find((one) => one.digest === digest);
      return found === undefined ? null : buffer(found.raw);
    },
    container: async (digest) => {
      asked.push(`container:${digest}`);
      const found = looks.find((one) => one.digest === digest);
      return found === undefined ? null : buffer(found.container);
    },
  };
  return { held, asked };
}

const refusal = async (promise: Promise<unknown>) => {
  try { await promise; } catch (error) { return error instanceof LibraryRefused ? error.reason : String(error); }
  return 'read';
};

describe('a workspace\'s own looks beside the shipped library', () => {
  it('reads a look the list lacks from the workspace, its container held to the digest its document names', async () => {
    const served = servedLibrary();
    const own = workspaceLook();
    const { held, asked } = store([own]);
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const drawing = await library.look({ key: 'own-traveller', version: 1, sha256: own.digest });
    expect(drawing.look).toBe('own-traveller');
    expect(drawing.lookKind).toBe('rigid_on_bones');
    expect(drawing.container!.sha256).toBe(sha256(own.container));
    const bytes = new Uint8Array(await library.container(drawing.container!));
    expect(bytes).toEqual(own.container);
    // The container is asked by the look's digest; the card reads the same document.
    expect(asked).toEqual([`look:${own.digest}`, `container:${own.digest}`]);
    expect(await library.lookDocument({ key: 'own-traveller', version: 1, sha256: own.digest })).toEqual(JSON.parse(new TextDecoder().decode(own.raw)));
  });

  it('never asks the workspace for a shipped look', async () => {
    const served = servedLibrary();
    const { held, asked } = store([]);
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest), held);
    const shipped = served.list.looks.find((one) => one.look === 'blocky-traveller')!;
    await library.look({ key: shipped.look, version: shipped.version, sha256: shipped.sha256 });
    expect(asked).toEqual([]);
  });

  it('refuses by name what the workspace does not hold, answers wrongly or names otherwise', async () => {
    const served = servedLibrary();
    const own = workspaceLook();
    const other = workspaceLook('another-look');
    const named = { key: 'own-traveller', version: 1, sha256: own.digest };
    // Absent, withdrawn or another workspace's: a 404, read as not held.
    expect(await refusal(new ThingLibrary(served.list, (d) => served.fetch(d), store([]).held).look(named))).toBe('not_in_library');
    // Other bytes than the digest asked for.
    expect(await refusal(new ThingLibrary(served.list, (d) => served.fetch(d), store([], () => other.raw).held).look(named))).toBe('digest_mismatch');
    // The right bytes, asked by another key: the document names what it is.
    expect(await refusal(new ThingLibrary(served.list, (d) => served.fetch(d), store([own]).held).look({ ...named, key: 'another-look' }))).toBe('not_in_library');
    // No workspace source at all: as before.
    expect(await refusal(new ThingLibrary(served.list, (d) => served.fetch(d)).look(named))).toBe('not_in_library');
    // A container whose bytes are not the digest its document names.
    const swapped = { ...own, container: new TextEncoder().encode('other bytes of the same length as before!!!!') };
    const library = new ThingLibrary(served.list, (d) => served.fetch(d), store([swapped]).held);
    const drawing = await library.look(named);
    expect(await refusal(library.container(drawing.container!))).toMatch(/digest_mismatch|length_mismatch/u);
  });

  it('reads a kind the list lacks from the workspace by its digest', async () => {
    const served = servedLibrary();
    const document = { ...thingsJson('kinds/traveller.v1.json'), kind: 'own-creature' };
    const raw = canonicalBytes(document);
    const digest = sha256(raw);
    const held: HeldThings = { kind: async (d) => (d === digest ? buffer(raw) : null), look: async () => null, container: async () => null };
    const library = new ThingLibrary(served.list, (d) => served.fetch(d), held);
    const kind = await library.kind({ key: 'own-creature', version: 1, sha256: digest });
    expect(kind.bodyPlan).toBe('humanoid/v1');
    expect(await refusal(library.kind({ key: 'own-creature', version: 2, sha256: digest }))).toBe('not_in_library');
  });
});

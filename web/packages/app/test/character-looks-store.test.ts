import { describe, expect, it, vi } from 'vitest';
import { designedLook, type CharacterLook } from '@exulanica/atlas-react/playcanvas';
import { CHARACTER_CATALOG, DESIGNED_LOOKS, SERVED_PEOPLE } from './served-people.js';
import {
  PreviewLookStore,
  StaleLookError,
  WorkspaceLookStore,
  lookFromRecipe,
  recipeFamilyId,
  recipeParameters,
  worldLookTarget,
  type LookStore,
  type SavedChoice,
} from '../src/character-looks-store.js';

const look = (id: string): CharacterLook => designedLook(DESIGNED_LOOKS, id);
/** The host's publications by digest: only the committed people catalog. */
const served = async (digest: string) => (digest === SERVED_PEOPLE.catalogSha256 ? SERVED_PEOPLE : null);
const defaults = (current: SavedChoice | null): SavedChoice => ({
  kind: 'catalog',
  look: look(DESIGNED_LOOKS.defaults.bases[current?.kind === 'catalog' ? current.look.baseId : 'masculine']!),
});

function memoryStorage() {
  const items = new Map<string, string>();
  return { items, getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => void items.set(key, value) };
}

describe('saved look recipes', () => {
  it('round-trip every designed look through the recipe a signed-in world stores', () => {
    for (const entry of DESIGNED_LOOKS.looks) {
      const parameters = recipeParameters(entry.look);
      expect(lookFromRecipe(CHARACTER_CATALOG, recipeFamilyId(entry.look), parameters)).toEqual(entry.look);
    }
  });

  it('refuse a recipe the catalog cannot draw instead of guessing', () => {
    const parameters = { ...recipeParameters(look('suit-masculine')) };
    expect(lookFromRecipe(CHARACTER_CATALOG, 'makehuman-people/v1/feminine', parameters)).toBeNull();
    expect(lookFromRecipe(CHARACTER_CATALOG, 'someone-else/v1/masculine', parameters)).toBeNull();
    expect(lookFromRecipe(CHARACTER_CATALOG, 'makehuman-people/v1/masculine', { ...parameters, heightMillimetres: '1800' })).toBeNull();
    expect(lookFromRecipe(CHARACTER_CATALOG, 'makehuman-people/v1/masculine', { ...parameters, outfit: 'masculine/outfit/cape' })).toBeNull();
  });
});

describe('the preview look store', () => {
  it('appends revisions, refuses a stale base, resets to the body default and restores history', async () => {
    const storage = memoryStorage();
    const store = new PreviewLookStore(defaults, storage, () => CHARACTER_CATALOG);
    expect(await store.read()).toEqual({ revision: 0, current: null });
    const first = await store.save({ kind: 'catalog', look: look('tailored-feminine') }, 0);
    expect(first.revision).toBe(1);
    await expect(store.save({ kind: 'abstract' }, 0)).rejects.toBeInstanceOf(StaleLookError);
    await store.save({ kind: 'abstract' }, 1);
    const reset = await store.reset(2);
    expect(reset.current).toMatchObject({ revision: 3, operation: 'reset', restoredFromRevision: null });
    expect(reset.current!.choice).toEqual({ kind: 'catalog', look: look('everyday-masculine') });
    const restored = await store.reset(3, 1);
    expect(restored.current).toMatchObject({ revision: 4, restoredFromRevision: 1, choice: { kind: 'catalog', look: look('tailored-feminine') } });
    expect((await store.history()).map((entry) => entry.revision)).toEqual([4, 3, 2, 1]);
    // A new page reads the same history, and a write another tab made first is refused here.
    const again = new PreviewLookStore(defaults, storage, () => CHARACTER_CATALOG);
    expect((await again.read()).revision).toBe(4);
    await again.save({ kind: 'catalog', look: look('work-masculine') }, 4);
    await expect(store.save({ kind: 'abstract' }, 4)).rejects.toBeInstanceOf(StaleLookError);
  });

  it('drops unreadable or foreign history and keeps working when storage refuses writes', async () => {
    const storage = memoryStorage();
    storage.items.set('exulanica.character-looks.preview/v1', JSON.stringify({
      profile: 'exulanica.character-look-history/v1',
      revisions: [{ revision: 1, operation: 'save', restoredFromRevision: null, savedAt: 'x', choice: { kind: 'catalog', look: { ...look('suit-masculine'), baseId: 'child' } } }],
    }));
    expect((await new PreviewLookStore(defaults, storage, () => CHARACTER_CATALOG).read()).revision).toBe(0);
    storage.items.set('exulanica.character-looks.preview/v1', '{not json');
    expect((await new PreviewLookStore(defaults, storage, () => CHARACTER_CATALOG).read()).revision).toBe(0);
    const refusing = { getItem: () => null, setItem: () => { throw new Error('quota'); } };
    const store = new PreviewLookStore(defaults, refusing, () => CHARACTER_CATALOG);
    expect((await store.save({ kind: 'abstract' }, 0)).revision).toBe(1);
    expect((await store.read()).current?.choice).toEqual({ kind: 'abstract' });
  });
});

describe('where a signed-in world keeps looks', () => {
  it('is the open world version, as the account, and nowhere without either', () => {
    const entry = { worldId: 'world:authored:1', authoredVersionId: 'v-1' };
    expect(worldLookTarget(entry, 'actor-1')).toEqual({ target: { worldId: 'world:authored:1', versionId: 'v-1', actor: 'actor-1' } });
    expect(worldLookTarget(entry, null)).toEqual({ target: null, missing: 'account' });
    expect(worldLookTarget(null, 'actor-1')).toEqual({ target: null, missing: 'version' });
  });

  it('keeps only catalog people on the server and anything in the visit store', () => {
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch: vi.fn() }, { worldId: 'w', versionId: 'v', actor: 'a' }, served);
    expect(store.keeps({ kind: 'catalog', look: look('suit-masculine') })).toBe(true);
    expect(store.keeps({ kind: 'abstract' })).toBe(false);
    const visit: LookStore = new PreviewLookStore(defaults, null, () => CHARACTER_CATALOG);
    expect(visit.keeps({ kind: 'abstract' })).toBe(true);
  });
});

describe('the signed-in look store', () => {
  const family = (familyId: string) => ({ family_sha256: 'a'.repeat(64), family: { family_id: familyId, default_seed: 0 } });
  const render = {
    catalog_sha256: SERVED_PEOPLE.catalogSha256, catalog_id: SERVED_PEOPLE.catalogId, revision: SERVED_PEOPLE.revision,
    kind: 'layered-people', resolution: 'authored', representation_id: null, dependencies: [],
  };
  const revision = (n: number, chosen: CharacterLook, status = 'available') => ({
    revision: n, operation: 'save', restored_from_revision: null, created_at: '2026-09-17T00:00:00Z', render_status: status,
    render: status === 'available' ? render : null,
    document: { recipe: { family_id: recipeFamilyId(chosen), parameters: recipeParameters(chosen) } },
  });

  it('saves a catalog look as a recipe over its body family and reads it back as the same look', async () => {
    const chosen = look('athletic-feminine');
    const calls: { method: string; url: string; body: unknown }[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      init ??= {};
      calls.push({ method: init.method ?? 'GET', url, body: init.body ? JSON.parse(String(init.body)) : null });
      if (url.includes('/families?')) return Response.json([family('makehuman-people/v1/feminine'), family('makehuman-people/v1/masculine')]);
      if (init.method === 'PUT') return Response.json({ revision: 1, current: revision(1, chosen) });
      return Response.json({ revision: 1, current: revision(1, chosen) });
    });
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { worldId: 'world:authored:1', versionId: 'v 1', actor: 'actor-1' }, served);
    const saved = await store.save({ kind: 'catalog', look: chosen }, 0);
    expect(saved.current?.choice).toEqual({ kind: 'catalog', look: chosen, catalogSha256: SERVED_PEOPLE.catalogSha256 });
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(put.url).toBe('https://world.example/api/world/versions/v%201/characters/avatar/actor-1/appearance?world_id=world%3Aauthored%3A1');
    // Every call names the world, the families and the reads included.
    expect(calls.every((call) => call.url.endsWith('?world_id=world%3Aauthored%3A1'))).toBe(true);
    expect(put.body).toEqual({
      base_revision: 0,
      recipe: { family_id: 'makehuman-people/v1/feminine', family_sha256: 'a'.repeat(64), parameters: recipeParameters(chosen), seed: 0 },
    });
    expect((await store.read()).current?.choice).toEqual({ kind: 'catalog', look: chosen, catalogSha256: SERVED_PEOPLE.catalogSha256 });
    await expect(store.save({ kind: 'abstract' }, 1)).rejects.toThrow(/Only published looks/);
  });

  it('turns a conflicting write into a reload request', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).includes('/families?')
      ? Response.json([family('makehuman-people/v1/masculine')])
      : Response.json({ code: 'stale_appearance', detail: 'appearance changed; reload before saving' }, { status: 409 }));
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { worldId: 'w', versionId: 'v', actor: 'a' }, served);
    await expect(store.save({ kind: 'catalog', look: look('suit-masculine') }, 3)).rejects.toBeInstanceOf(StaleLookError);
    await expect(store.reset(3)).rejects.toBeInstanceOf(StaleLookError);
  });

  it('keeps a saved look it cannot draw as unavailable, by the host\'s code, never as somebody else', async () => {
    const chosen = look('athletic-feminine');
    const reads = [
      { revision: 2, current: revision(2, chosen, 'family_source_unavailable') },
      { revision: 2, current: { ...revision(2, chosen), render: { ...render, catalog_sha256: 'f'.repeat(64) } } },
    ];
    const fetch = vi.fn(async () => Response.json(reads.shift()));
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { worldId: 'w', versionId: 'v', actor: 'a' }, served);
    expect((await store.read()).current?.choice).toEqual({
      kind: 'unavailable', code: 'family_source_unavailable', familyId: 'makehuman-people/v1/feminine',
    });
    // A publication this page cannot be given reads as unavailable too, with its own code.
    expect((await store.read()).current?.choice).toEqual({
      kind: 'unavailable', code: 'catalog_unavailable', familyId: 'makehuman-people/v1/feminine',
    });
  });

  it('reads a conflict as stale only when the host says the look changed', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).includes('/families?')
      ? Response.json([family('makehuman-people/v1/masculine')])
      : Response.json({ code: 'representation_not_prepared', detail: 'not prepared' }, { status: 409 }));
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { worldId: 'w', versionId: 'v', actor: 'a' }, served);
    const refused = store.save({ kind: 'catalog', look: look('suit-masculine') }, 3);
    await expect(refused).rejects.not.toBeInstanceOf(StaleLookError);
  });
});

import { describe, expect, it, vi } from 'vitest';
import { CHARACTER_CATALOG, DESIGNED_LOOKS, designedLook, type CharacterLook } from '@exulanica/atlas-react/playcanvas';
import {
  PreviewLookStore,
  StaleLookError,
  WorkspaceLookStore,
  lookFromRecipe,
  recipeFamilyId,
  recipeParameters,
  type SavedChoice,
} from '../src/character-looks-store.js';

const look = (id: string): CharacterLook => designedLook(DESIGNED_LOOKS, id);
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
    const store = new PreviewLookStore(defaults, storage);
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
    const again = new PreviewLookStore(defaults, storage);
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
    expect((await new PreviewLookStore(defaults, storage).read()).revision).toBe(0);
    storage.items.set('exulanica.character-looks.preview/v1', '{not json');
    expect((await new PreviewLookStore(defaults, storage).read()).revision).toBe(0);
    const refusing = { getItem: () => null, setItem: () => { throw new Error('quota'); } };
    const store = new PreviewLookStore(defaults, refusing);
    expect((await store.save({ kind: 'abstract' }, 0)).revision).toBe(1);
    expect((await store.read()).current?.choice).toEqual({ kind: 'abstract' });
  });
});

describe('the signed-in look store', () => {
  const family = (familyId: string) => ({ family_sha256: 'a'.repeat(64), family: { family_id: familyId, default_seed: 0 } });
  const revision = (n: number, chosen: CharacterLook) => ({
    revision: n, operation: 'save', restored_from_revision: null, created_at: '2026-09-17T00:00:00Z', render_status: 'available',
    document: { recipe: { family_id: recipeFamilyId(chosen), parameters: recipeParameters(chosen) } },
  });

  it('saves a catalog look as a recipe over its body family and reads it back as the same look', async () => {
    const chosen = look('athletic-feminine');
    const calls: { method: string; url: string; body: unknown }[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      init ??= {};
      calls.push({ method: init.method ?? 'GET', url, body: init.body ? JSON.parse(String(init.body)) : null });
      if (url.endsWith('/families')) return Response.json([family('makehuman-people/v1/feminine'), family('makehuman-people/v1/masculine')]);
      if (init.method === 'PUT') return Response.json({ revision: 1, current: revision(1, chosen) });
      return Response.json({ revision: 1, current: revision(1, chosen) });
    });
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { versionId: 'v 1', actor: 'actor-1' });
    const saved = await store.save({ kind: 'catalog', look: chosen }, 0);
    expect(saved.current?.choice).toEqual({ kind: 'catalog', look: chosen });
    const put = calls.find((call) => call.method === 'PUT')!;
    expect(put.url).toBe('https://world.example/api/world/versions/v%201/characters/avatar/actor-1/appearance');
    expect(put.body).toEqual({
      base_revision: 0,
      recipe: { family_id: 'makehuman-people/v1/feminine', family_sha256: 'a'.repeat(64), parameters: recipeParameters(chosen), seed: 0 },
    });
    expect((await store.read()).current?.choice).toEqual({ kind: 'catalog', look: chosen });
    await expect(store.save({ kind: 'abstract' }, 1)).rejects.toThrow(/Only people from the catalog/);
  });

  it('turns a conflicting write into a reload request', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/families')
      ? Response.json([family('makehuman-people/v1/masculine')])
      : Response.json({ code: 'stale_appearance', detail: 'appearance changed; reload before saving' }, { status: 409 }));
    const store = new WorkspaceLookStore({ baseUrl: 'https://world.example/api', token: 't', fetch }, { versionId: 'v', actor: 'a' });
    await expect(store.save({ kind: 'catalog', look: look('suit-masculine') }, 3)).rejects.toBeInstanceOf(StaleLookError);
    await expect(store.reset(3)).rejects.toBeInstanceOf(StaleLookError);
  });
});

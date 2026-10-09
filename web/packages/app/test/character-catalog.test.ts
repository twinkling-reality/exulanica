import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { previewInhabitantSelection, type CharacterLook } from '../src/character-catalog.js';

const catalog = ['look-a', 'look-b', 'look-c', 'look-d'].map(lookId => ({
  lookId, defaultColors: { skin: '#ba9988', cloth: '#554466' }, variationSlots: ['cloth'],
})) as unknown as readonly CharacterLook[];
const subject = (id: string, branchId = 'one'): CharacterSubject => ({
  kind: 'synthetic-inhabitant', societyId: 'society', branchId, inhabitantId: id,
});

describe('fictional catalog defaults', () => {
  it('retains appearance across branch, ordering and repeated residency changes', () => {
    const chosen = previewInhabitantSelection(catalog, subject('person'));
    expect(previewInhabitantSelection([...catalog].reverse(), subject('person', 'two'))).toEqual(chosen);
    expect(previewInhabitantSelection(catalog, subject('person'))).toEqual(chosen);
  });
  it('varies the population while preserving undeclared source surfaces and catalog data', () => {
    const before = JSON.stringify(catalog);
    const choices = Array.from({ length: 24 }, (_, index) => previewInhabitantSelection(catalog, subject(String(index)))!);
    expect(new Set(choices.map(choice => choice.lookId)).size).toBe(4);
    expect(new Set(choices.map(choice => JSON.stringify(choice))).size).toBeGreaterThan(4);
    for (const choice of choices) {
      expect(Object.keys(choice.appearance.colors!)).toEqual(['cloth']);
      expect(choice.appearance.colors!.cloth).toMatch(/^#[a-f0-9]{6}$/);
    }
    expect(JSON.stringify(catalog)).toBe(before);
  });
  it('does not assign fictional appearance to the player or a scene person', () => {
    expect(previewInhabitantSelection(catalog, { kind: 'player', playerId: 'viewer' })).toBeNull();
    expect(previewInhabitantSelection(catalog, { kind: 'scene-person' } as CharacterSubject)).toBeNull();
    expect(previewInhabitantSelection([], subject('person'))).toBeNull();
  });
  it('faces imported preview characters along the world forward axis', () => {
    const committed = (path: string): unknown => JSON.parse(readFileSync(
      new URL(`../../../../assets/characters/${path}`, import.meta.url), 'utf8'));
    const stylized = committed('stylized-looks.json') as { profile: string; looks: CharacterLook[] };
    expect(stylized.profile).toBe('exulanica.character-stylized-looks/v1');
    const looks = [committed('makehuman-parametric-v1/default.look.json') as CharacterLook, ...stylized.looks];
    expect(looks.map(look => look.lookId)).toEqual(['editable-human', 'hoodie', 'casual', 'casual-f', 'formal-f']);
    for (const look of looks) expect(look.descriptor.forwardYawDegrees).toBe(180);
  });
});

describe('signed-in character bytes', () => {
  it('fetch each container as a reviewed asset by its key, with the session credentials', async () => {
    const { workspaceCharacterLoader } = await import('../src/character-catalog.js');
    const seen: { url: string; authorization: string | null }[] = [];
    const fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({ url: String(input), authorization: new Headers(init?.headers).get('authorization') });
      return new Response(new Uint8Array([1, 2, 3, 4]));
    };
    const load = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: 'session', fetch });
    const bytes = await load({ assetKey: 'makehuman.people.feminine.base.v1', mediaType: 'model/gltf-binary', contentSha256: 'a'.repeat(64), byteSize: 4 },
      new AbortController().signal);
    expect(bytes.byteLength).toBe(4);
    expect(seen).toEqual([{ url: 'https://world.example/api/world/assets/makehuman.people.feminine.base.v1/bytes', authorization: 'Bearer session' }]);
  });

  it('fetch a body prepared for the workspace from where its look store says it is delivered', async () => {
    const { workspaceCharacterLoader } = await import('../src/character-catalog.js');
    const seen: string[] = [];
    const fetch = async (input: RequestInfo | URL) => { seen.push(String(input)); return new Response(new Uint8Array([1, 2])); };
    const reference = { assetKey: 'preparation:p-1', mediaType: 'model/gltf-binary', contentSha256: 'b'.repeat(64), byteSize: 2 };
    const signal = new AbortController().signal;
    const load = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: 'session', fetch },
      (preparationId) => `/world/versions/v/characters/avatar/a/appearance/preparations/${preparationId}/bytes?world_id=w`);
    expect((await load(reference, signal)).byteLength).toBe(2);
    expect(seen).toEqual(['https://world.example/api/world/versions/v/characters/avatar/a/appearance/preparations/p-1/bytes?world_id=w']);
    // With nowhere to fetch it from, a prepared body is unavailable by name, never another body.
    const nowhere = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: 'session', fetch });
    await expect(nowhere(reference, signal)).rejects.toThrow('preparation_unavailable');
    expect(seen).toHaveLength(1);
  });

  it('keep at most six reads in flight, so a town of people does not overrun the host', async () => {
    const { workspaceCharacterLoader } = await import('../src/character-catalog.js');
    let inFlight = 0;
    let most = 0;
    const opened: (() => void)[] = [];
    const fetch = async () => {
      inFlight += 1; most = Math.max(most, inFlight);
      await new Promise<void>((resolve) => opened.push(resolve));
      inFlight -= 1;
      return new Response(new Uint8Array([1]));
    };
    const load = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: '', fetch });
    const reference = (n: number) => ({ assetKey: `part-${n}`, mediaType: 'model/gltf-binary', contentSha256: 'a'.repeat(64), byteSize: 1 });
    const all = Array.from({ length: 20 }, (_, n) => load(reference(n), new AbortController().signal));
    let settled = false;
    const finished = Promise.all(all).then(() => { settled = true; });
    // Let each read in flight finish, a turn at a time, until every one has.
    while (!settled) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      opened.splice(0).forEach((open) => open());
    }
    await finished;
    expect(most).toBe(6);
  });

  it('ask again a read the host was too busy for, after the Retry-After it sent', async () => {
    const { workspaceCharacterLoader } = await import('../src/character-catalog.js');
    const answers = [
      new Response(JSON.stringify({ code: 'workspace_capacity_exhausted', detail: 'busy' }), { status: 429, headers: { 'Retry-After': '1' } }),
      new Response(JSON.stringify({ code: 'capacity_exhausted', detail: 'busy' }), { status: 503, headers: { 'Retry-After': '2' } }),
      new Response(new Uint8Array([1, 2, 3])),
    ];
    const fetch = async () => answers.shift()!;
    const waited: number[] = [];
    const load = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: '', fetch }, undefined,
      { wait: async (ms) => { waited.push(ms); } });
    const bytes = await load({ assetKey: 'part', mediaType: 'model/gltf-binary', contentSha256: 'a'.repeat(64), byteSize: 3 }, new AbortController().signal);
    expect(bytes.byteLength).toBe(3);
    expect(waited).toEqual([1000, 2000]);
    // Anything else, such as a missing asset, is not asked again.
    const once = workspaceCharacterLoader({ baseUrl: 'https://world.example/api', token: '', fetch: async () => new Response('{}', { status: 404 }) },
      undefined, { wait: async (ms) => { waited.push(ms); } });
    await expect(once({ assetKey: 'gone', mediaType: 'model/gltf-binary', contentSha256: 'a'.repeat(64), byteSize: 1 }, new AbortController().signal)).rejects.toThrow();
    expect(waited).toEqual([1000, 2000]);
  });
});

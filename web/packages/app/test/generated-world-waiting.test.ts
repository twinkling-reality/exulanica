// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  GENERATED_WORLD_READY_EVENT,
  GENERATED_WORLD_WAITING_ATTRIBUTE,
  type GeneratedWorldReady,
} from '../src/composition/generated-world-ready.js';
import { openGeneratedWorld } from '../src/composition/generated-world.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * While a saved generated world's tiles bake, the page says so and reads the entry again until it
 * can open the world: once every tile is baked, and once one has failed, when opening it again
 * says the world is not drawn rather than leaving the page saying it is being built. A page that
 * was hidden reads again as soon as it is shown, and a page that has left the world stops reading.
 */

const entry = {
  entryId: 'entry-town', worldId: 'world:generated:town', authoredVersionId: 'version',
  generatedGround: {
    recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'region:generated',
    arrivalMm: [128000, 0, -58750], arrivalFacingMm: [0, 3000],
    tiles: [
      { tileX: 0, tileY: 0, tileInputsDigest: '0'.repeat(64), bakedTileId: null, state: 'baking' },
      { tileX: 1, tileY: 0, tileInputsDigest: '1'.repeat(64), bakedTileId: null, state: 'baking' },
    ],
  },
} as unknown as SavedWorldEntry;
const access = { baseUrl: 'https://exulanica.test', token: 't' };

function served(states: readonly string[]): Response {
  return new Response(JSON.stringify({ generated_ground: { tiles: states.map((state) => ({ state })) } }));
}

function setVisibility(state: 'visible' | 'hidden'): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

async function waiting(): Promise<{ shell: HTMLElement; ready: GeneratedWorldReady[] }> {
  const shell = document.createElement('div');
  document.body.append(shell);
  const ready: GeneratedWorldReady[] = [];
  shell.addEventListener(GENERATED_WORLD_READY_EVENT, (event) => {
    ready.push((event as CustomEvent<GeneratedWorldReady>).detail);
  });
  expect(await openGeneratedWorld({ shell } as never, access, entry)).toBeNull();
  expect(shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.getAttribute(GENERATED_WORLD_WAITING_ATTRIBUTE))
    .toBe('baking');
  return { shell, ready };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe('a saved generated world waiting for its tiles', () => {
  it('opens again once every tile is baked, and once a tile has failed', async () => {
    for (const [later, reads] of [[['baked', 'baked'], 2], [['baked', 'failed'], 2]] as const) {
      const fetch = vi.fn()
        .mockResolvedValueOnce(served(['baked', 'baking']))
        .mockResolvedValueOnce(served(later));
      vi.stubGlobal('fetch', fetch);
      const { ready } = await waiting();
      await vi.advanceTimersByTimeAsync(5_000);
      expect(ready).toEqual([]);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(ready).toEqual([{ entryId: 'entry-town' }]);
      // Once it has said so, it reads no more.
      await vi.advanceTimersByTimeAsync(20_000);
      expect(fetch).toHaveBeenCalledTimes(reads);
      document.body.replaceChildren();
    }
  });

  it('reads again as soon as a hidden page is shown', async () => {
    const fetch = vi.fn().mockResolvedValue(served(['baked', 'baked']));
    vi.stubGlobal('fetch', fetch);
    const { ready } = await waiting();
    setVisibility('hidden');
    expect(fetch).not.toHaveBeenCalled();
    setVisibility('visible');
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledOnce();
    expect(ready).toEqual([{ entryId: 'entry-town' }]);
  });

  it('stops reading once its words are taken down, when another world opens', async () => {
    const fetch = vi.fn().mockResolvedValue(served(['baked', 'baking']));
    vi.stubGlobal('fetch', fetch);
    const { shell, ready } = await waiting();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetch).toHaveBeenCalledOnce();
    shell.querySelector(`[${GENERATED_WORLD_WAITING_ATTRIBUTE}]`)?.remove();
    fetch.mockResolvedValue(served(['baked', 'baked']));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledOnce();
    expect(ready).toEqual([]);
  });
});

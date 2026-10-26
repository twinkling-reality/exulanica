// @vitest-environment happy-dom
// A world's painting at its first view (src/composition/world-painting.ts) and on its card
// (src/composition/world-pictures.ts): the world opens where its painting was painted from, the painting lies over
// the live view saying it is invented appearance until the first input that reaches the world, for as long as the live
// camera stands where it was painted from, and a card shows a world's painting first, its first view's or else its newest.
import { describe, expect, it } from 'vitest';
import {
  WORLD_PAINTING_ATTRIBUTE,
  firstViewPainting,
  paintedStart,
  placedCamera,
  showWorldPainting,
  standsAtPainting,
} from '../src/composition/world-painting.js';
import { readPaintedPictures, worldPicture } from '../src/composition/world-pictures.js';
import { parseWorldPainting, type WorldPainting } from '../src/world-paintings-api.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';
import type { GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';

const served = (view: string, sha: string, camera: unknown = {
  position_m: [111.5, 9.11, -2.55], yaw: -1.5, pitch: 0, fov_deg: 70, width: 1280, height: 720,
}) => ({
  view, recipe: 'z-image-depth/v1', sha256: sha.repeat(64).slice(0, 64), width: 1280, height: 720, camera,
  words: { prompt: 'a fishing village' },
  painter: { models: [{ repository: 'Tongyi-MAI/Z-Image', revision: '04cc4abb7c50', licence: 'apache-2.0' }] },
  held_permille: 930, made_at: '2026-10-25T16:40:00+00:00', label: 'invented appearance',
});
/** A camera's world transform, column-major, turned `yaw` about the vertical and standing at `position`. */
const at = (yaw: number, [x, y, z]: readonly [number, number, number]) => [
  Math.cos(yaw), 0, -Math.sin(yaw), 0, 0, 1, 0, 0, Math.sin(yaw), 0, Math.cos(yaw), 0, x, y, z, 1,
];
const frames = () => new Promise((resolve) => setTimeout(resolve, 50));

describe("a world's painting", () => {
  it('opens the world where its newest painting of the first view was painted from', () => {
    const paintings = [served('q2', 'b'), served('first', 'c'), served('first', 'd')].map(parseWorldPainting);
    const first = firstViewPainting(paintings);
    expect(first?.sha256).toBe('c'.repeat(64));
    expect(first?.painter).toBe('Z-Image');
    expect(paintedStart(first!)).toEqual({ x: 111.5, y: 9.11, z: -2.55, yaw: -1.5, pitch: 0 });
    // A painting that states no camera cannot be stood at, so the world opens at its own first view.
    expect(firstViewPainting([parseWorldPainting(served('first', 'e', null))])).toBeNull();
    // Nothing the server sends without its label is shown as a painting.
    expect(() => parseWorldPainting({ ...served('first', 'f'), label: 'a photograph' })).toThrow(TypeError);
  });

  it('lies over the live view saying what it is, and gives way to the first input that reaches the world', () => {
    const holder = document.createElement('div');
    const canvas = document.createElement('canvas');
    const button = document.createElement('button');
    holder.append(canvas);
    document.body.append(holder, button);
    const painting = parseWorldPainting(served('first', 'a')) as WorldPainting;
    showWorldPainting(canvas, painting, 'blob:painting', true, () => true);
    const shown = () => document.querySelectorAll(`[${WORLD_PAINTING_ATTRIBUTE}]`);
    expect(shown()).toHaveLength(2);
    expect(document.body.textContent).toContain('Painted by Z-Image from this world\'s words · invented appearance');
    // A key the page's own controls take leaves it; any key that reaches the world takes it down.
    button.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowRight', bubbles: true }));
    expect(shown()).toHaveLength(2);
    document.body.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyP', bubbles: true }));
    expect(shown()).toHaveLength(0);
    // So does a click on the world.
    showWorldPainting(canvas, painting, 'blob:painting', true, () => true);
    canvas.dispatchEvent(new Event('pointerdown'));
    expect(shown()).toHaveLength(0);
  });

  it('shows only while the live camera stands where it was painted from, looking its way through its lens', async () => {
    const painting = parseWorldPainting(served('first', 'a')) as WorldPainting;
    const there = at(-1.5, [111.5, 9.11, -2.55]);
    expect(standsAtPainting(painting, { transform: there, fovDeg: 70 })).toBe(true);
    expect(standsAtPainting(painting, { transform: at(-1.5, [111.7, 9.11, -2.55]), fovDeg: 70 })).toBe(false);
    expect(standsAtPainting(painting, { transform: at(-1.52, [111.5, 9.11, -2.55]), fovDeg: 70 })).toBe(false);
    expect(standsAtPainting(painting, { transform: there, fovDeg: 80 })).toBe(false);
    const canvas = document.createElement('canvas');
    document.body.append(canvas);
    const shown = () => document.querySelectorAll(`[${WORLD_PAINTING_ATTRIBUTE}]`);
    // A world the page opens at a camera of its own, the view a person left it at, never shows it.
    showWorldPainting(canvas, painting, 'blob:painting', false, () => false);
    expect(shown()).toHaveLength(0);
    // Shown before the world has a camera and while the camera stands there, it goes at once when the camera leaves.
    let standing: boolean | null = null;
    showWorldPainting(canvas, painting, 'blob:painting', false, () => standing);
    standing = true;
    await frames();
    expect(shown()).toHaveLength(2);
    standing = false;
    await frames();
    expect(shown()).toHaveLength(0);
  });

  it('counts the camera only once the world has placed it at its start', () => {
    const painting = parseWorldPainting(served('first', 'a')) as WorldPainting;
    // The renderer makes its camera where it stands by default and places it a few frames after the tile is attached.
    const transform = new Float32Array(at(0, [0, 0, 0]));
    const host = { camera: { camera: { fov: 70 }, getWorldTransform: () => ({ data: transform }) } } as unknown as GeneratedTileHost;
    const tile = { attach: () => ({ metrics: null, dispose: () => undefined }) } as unknown as LoadedGeneratedTile;
    const placed = placedCamera(tile);
    expect(placed.camera()).toBeNull();
    placed.tile.attach(host);
    expect(placed.camera()).toBeNull();
    transform.set(at(-1.5, [111.5, 9.11, -2.55]));
    expect(standsAtPainting(painting, placed.camera()!)).toBe(true);
    // Once placed, it counts wherever it goes, back where it was made too.
    transform.set(at(0, [0, 0, 0]));
    expect(standsAtPainting(painting, placed.camera()!)).toBe(false);
  });

  it("shows a card its world's painting first, and keeps the world's own picture where none can be read", async () => {
    const entry = { entryId: 'entry-1', worldId: 'world-1', picture: null } as unknown as SavedWorldEntry;
    const other = { entryId: 'entry-2', worldId: 'world-2', picture: null } as unknown as SavedWorldEntry;
    const client = {
      async paintings(worldId: string) {
        if (worldId === 'world-2') throw new Error('unreadable');
        // A painting that was not passed for the first view still goes on the card.
        return [parseWorldPainting(served('q2', 'a'))];
      },
      async picture() {
        return new Blob(['a painting'], { type: 'image/jpeg' });
      },
    };
    expect(await readPaintedPictures(client, [entry, other])).toBe(1);
    expect(worldPicture(entry)).toMatch(/^blob:/);
    expect(worldPicture(other)).toBeNull();
  });
});

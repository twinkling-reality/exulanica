import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { WORLD_SCENES, worldEntryHref } from '../src/ui/world-scenes.js';

it('keeps world destinations and image bytes consistent with their capture provenance', () => {
  const directory = new URL('../public/worlds/', import.meta.url);
  const manifest = JSON.parse(readFileSync(new URL('sources.json', directory), 'utf8'));
  for (const scene of WORLD_SCENES) {
    const source = manifest.worlds.find((world: { id: string }) => world.id === scene.id);
    expect(source, scene.id).toBeDefined();
    if (source.showcase === true) {
      // A showcase world opens by its key, and says the sentence it was made from and what made it.
      expect(scene.world).toBe(source.world);
      expect(scene.sentence).toBe(source.sentence);
      expect(scene.title).toBe(source.title);
      expect(source.made.people.length).toBeGreaterThan(0);
      expect(worldEntryHref(scene, 'https://atlas.example/?preview=1')).toBe(`https://atlas.example/?preview=1&world=${source.world}`);
    } else {
      expect(source.recipe).toBe(scene.recipe);
      expect(source.style_pack).toEqual(scene.stylePack);
      expect(source.saved_world_title.split(' · ')[0]).toBe(scene.name);
      expect(source.values).toMatchObject(scene.values);
    }
    expect(scene.image).toBe(`/worlds/${source.image}`);
    const digest = createHash('sha256').update(readFileSync(new URL(source.image, directory))).digest('hex');
    expect(digest).toBe(source.image_sha256);
  }
});

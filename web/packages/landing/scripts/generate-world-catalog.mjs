import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const root = new URL('../', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('public/worlds/sources.json', root), 'utf8'));
const worlds = manifest.worlds.filter(world => world.featured === true).map(world => {
  const bytes = readFileSync(new URL(`public/worlds/${world.image}`, root));
  if (!world.capture_complete || createHash('sha256').update(bytes).digest('hex') !== world.image_sha256) {
    throw new Error(`Capture is incomplete or changed: ${world.id}`);
  }
  if (!world.style_pack || !world.saved_world_title || !world.style_title) throw new Error(`Missing capture metadata: ${world.id}`);
  return Object.fromEntries(['id', 'recipe', 'values', 'style_pack', 'image', 'saved_world_title', 'style_title'].map(key => [key, world[key]]));
});
if (!worlds.length) throw new Error('No featured captures');
writeFileSync(new URL('src/content/world-captures.ts', root), `// Generated from public/worlds/sources.json. Run scripts/generate-world-catalog.mjs.\nexport const WORLD_CAPTURES = ${JSON.stringify(worlds, null, 2)} as const;\n`);

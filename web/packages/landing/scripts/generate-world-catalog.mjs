import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const root = new URL('../', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('public/worlds/sources.json', root), 'utf8'));
// A showcase world is a made world a visitor opens by its key: its sentence, title and what made it come from its
// record; a configuration capture names its recipe and look.
const SHOWCASE_FIELDS = ['id', 'world', 'title', 'sentence', 'image', 'made'];
const CAPTURE_FIELDS = ['id', 'recipe', 'values', 'style_pack', 'image', 'saved_world_title', 'style_title'];
const worlds = manifest.worlds.filter(world => world.featured === true).map(world => {
  const bytes = readFileSync(new URL(`public/worlds/${world.image}`, root));
  if (!world.capture_complete || createHash('sha256').update(bytes).digest('hex') !== world.image_sha256) {
    throw new Error(`Capture is incomplete or changed: ${world.id}`);
  }
  if (world.showcase === true) {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(world.world ?? '') || !world.title || !world.sentence) throw new Error(`Missing showcase identity: ${world.id}`);
    if (!world.made?.main || !Array.isArray(world.made.people) || world.made.spend_usd === undefined) throw new Error(`Missing showcase provenance: ${world.id}`);
    // The people's models stay in sources.json: product code names a model only through the models manifest.
    const { people: _people, ...made } = world.made;
    return Object.fromEntries(SHOWCASE_FIELDS.map(key => [key, key === 'made' ? made : world[key]]));
  }
  if (!world.style_pack || !world.saved_world_title || !world.style_title) throw new Error(`Missing capture metadata: ${world.id}`);
  return Object.fromEntries(CAPTURE_FIELDS.map(key => [key, world[key]]));
});
if (!worlds.length) throw new Error('No featured captures');
const TYPES = `export interface ShowcaseCapture {
  readonly id: string;
  readonly world: string;
  readonly title: string;
  readonly sentence: string;
  readonly image: string;
  readonly made: Readonly<Record<string, unknown>>;
}
export interface ConfigurationCapture {
  readonly id: string;
  readonly recipe: string;
  readonly values: Readonly<Record<string, string | number>>;
  readonly style_pack: { readonly pack_id: string; readonly version: number; readonly manifest_sha256: string };
  readonly image: string;
  readonly saved_world_title: string;
  readonly style_title: string;
}
`;
writeFileSync(new URL('src/content/world-captures.ts', root), `// Generated from public/worlds/sources.json. Run scripts/generate-world-catalog.mjs.\n${TYPES}export const WORLD_CAPTURES: readonly (ShowcaseCapture | ConfigurationCapture)[] = ${JSON.stringify(worlds, null, 2)};\n`);

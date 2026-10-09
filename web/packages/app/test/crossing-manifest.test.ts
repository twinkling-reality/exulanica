// What came across with a visitor and what stayed behind. The manifest here is built the way the
// door builds one (exulanica/door/manifest.py): from a game bridge's own mapping file in bridges/,
// found by its place rather than named (the product names no game), each field's words the mapping
// entry's words and its reason the mapping's reason_words for every field that is not exact. The
// expected lines are that file's words.
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { crossingRows, fetchCrossingManifest, readCrossingManifest } from '../src/crossing-manifest-api.js';

const repository = `${process.cwd()}/..`;

/** The first game bridge mapping file of the second profile: bridges/<bridge>/mod/<mod>/mapping/*.v2.json. */
function bridgeMapping(): string {
  for (const bridge of readdirSync(`${repository}/bridges`).sort()) {
    const mods = `${repository}/bridges/${bridge}/mod`;
    let found: string[] = [];
    try { found = readdirSync(mods); } catch { continue; }
    for (const mod of found.sort()) {
      try {
        const file = readdirSync(`${mods}/${mod}/mapping`).sort().find((name) => name.endsWith('.v2.json'));
        if (file !== undefined) return `${mods}/${mod}/mapping/${file}`;
      } catch { /* a mod with no mapping */ }
    }
  }
  throw new Error('no game bridge mapping file of the second profile in bridges/');
}

const mapping = JSON.parse(readFileSync(bridgeMapping(), 'utf8')) as {
  visitors: { words: string; outcome: string; reason_words?: string }[];
  items: { words: string; outcome: string; reason_words?: string }[];
  actions: { words: string; outcome: string; reason_words?: string }[];
  never_crosses: { words: string; reason_words: string }[];
};

const field = (entry: { words: string; outcome: string; reason_words?: string }, path: string) => ({
  path, disposition: entry.outcome, to: '/somewhere', reason: entry.outcome === 'exact' ? null : entry.reason_words, words: entry.words,
});

/** A player carrying a steel and a wooden sword, as the door accounts for it. */
const manifest = {
  profile: 'exulanica.translation-manifest/v2',
  translator: { key: 'game-mapping', version: 2, sha256: 'a'.repeat(64) },
  source: { format: 'game-arrival', type: 'player', sha256: 'b'.repeat(64) },
  target: { kind: { kind: 'traveller', version: 1 }, look: null },
  fields: [
    field(mapping.visitors[0]!, '/type'),
    field(mapping.items[0]!, '/items/0'),
    field(mapping.items[1]!, '/items/1'),
    field(mapping.actions[0]!, '/actions/0'),
    ...mapping.never_crosses.map((never, index) => ({ path: `/never/${index}`, disposition: 'dropped', to: null, reason: never.reason_words, words: never.words })),
  ],
};

describe('a crossing\'s manifest on the card', () => {
  it('lists what came across, exactly first, then what changed with its reason, in the game\'s own words', () => {
    const rows = crossingRows(manifest)!;
    const exact = [mapping.items[0]!, mapping.actions[0]!].filter((entry) => entry.outcome === 'exact');
    const changed = [mapping.visitors[0]!, mapping.items[1]!].filter((entry) => entry.outcome === 'approximated');
    expect(rows.came).toEqual([
      ...exact.map((entry) => ({ words: entry.words, reason: null })),
      ...changed.map((entry) => ({ words: entry.words, reason: entry.reason_words })),
    ]);
  });

  it('groups what stayed behind by its reason, each reason said once', () => {
    const rows = crossingRows({ ...manifest, fields: [...manifest.fields,
      { path: '/never/again', disposition: 'opaque', to: null, reason: mapping.never_crosses[0]!.reason_words, words: 'its saved inventory' }] })!;
    expect(rows.stayed).toEqual([
      { words: [mapping.never_crosses[0]!.words, 'its saved inventory'], reason: mapping.never_crosses[0]!.reason_words },
      ...mapping.never_crosses.slice(1).map((never) => ({ words: [never.words], reason: never.reason_words })),
    ]);
  });

  it('gives no rows for a first-profile manifest, which states no words, and refuses any other shape', () => {
    expect(crossingRows({ profile: 'exulanica.translation-manifest/v1', fields: [] })).toBeNull();
    expect(() => crossingRows({ ...manifest, profile: 'exulanica.translation-manifest/v3' })).toThrow();
    expect(() => crossingRows({ ...manifest, fields: [{ ...manifest.fields[0]!, disposition: 'guessed' }] })).toThrow();
    expect(() => crossingRows({ ...manifest, fields: [{ ...manifest.fields[1]!, words: '' }] })).toThrow();
  });

  it('reads the route\'s answer: the digest, where it came from, and the stored manifest', () => {
    const read = readCrossingManifest({ manifest_sha256: 'c'.repeat(64), manifest, from: { bridge: 'blockgame', label: 'Block Game', ai: false } });
    expect(read.from).toEqual({ bridge: 'blockgame', label: 'Block Game', ai: false });
    expect(read.rows?.stayed.length).toBe(mapping.never_crosses.length);
    expect(() => readCrossingManifest({ manifest_sha256: 'short', manifest, from: { bridge: 'blockgame', label: 'Block Game', ai: false } })).toThrow();
  });

  it('shows the rows of a visitor whose bridge the deployment no longer declares, with no words for the bridge', () => {
    const read = readCrossingManifest({ manifest_sha256: 'c'.repeat(64), manifest, from: { bridge: 'blockgame', label: null, ai: null } });
    expect(read.from).toEqual({ bridge: 'blockgame', label: null, ai: null });
    expect(read.rows?.stayed.length).toBe(mapping.never_crosses.length);
    expect(() => readCrossingManifest({ manifest_sha256: 'c'.repeat(64), manifest, from: { bridge: 'blockgame', label: null, ai: 'no' } })).toThrow();
    expect(() => readCrossingManifest({ manifest_sha256: 'c'.repeat(64), manifest, from: { bridge: 'blockgame', label: '', ai: false } })).toThrow();
  });

  it('asks for the crossing in the version the card shows', async () => {
    const asked: string[] = [];
    const fetcher = (async (url: string) => {
      asked.push(url);
      return new Response(JSON.stringify({ manifest_sha256: 'c'.repeat(64), manifest, from: { bridge: 'blockgame', label: 'Block Game', ai: false } }));
    }) as unknown as typeof fetch;
    await fetchCrossingManifest({ baseUrl: 'https://example.test', token: 't' }, 'world:authored:a b', 'version-1', 'arrival-1', fetcher);
    expect(asked).toEqual(['https://example.test/door/crossings/arrival-1/manifest?world_id=world%3Aauthored%3Aa%20b&version_id=version-1']);
  });
});

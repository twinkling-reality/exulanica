import { describe, expect, it } from 'vitest';
import { generatedTileEvaluationName, isAtlasPreview } from '../src/config.js';

describe('generated tile evaluation entry: who may ask', () => {
  it('names a tile only on the development preview route', () => {
    const search = '?preview=1&tile=tile-conformance';
    expect(generatedTileEvaluationName(search, isAtlasPreview(search, true))).toBe('tile-conformance');
    // A production build: isAtlasPreview is false whatever the query says.
    expect(generatedTileEvaluationName(search, isAtlasPreview(search, false))).toBeNull();
    // A workspace session: no preview flag, so no tile, even in development.
    expect(generatedTileEvaluationName('?tile=tile-conformance', isAtlasPreview('?tile=tile-conformance', true))).toBeNull();
    expect(generatedTileEvaluationName(search, false)).toBeNull();
  });

  it('accepts a plain name and nothing that could be a path or a URL', () => {
    const name = (tile: string): string | null =>
      generatedTileEvaluationName(`?preview=1&tile=${encodeURIComponent(tile)}`, true);
    expect(name('corridor-1')).toBe('corridor-1');
    expect(name('a'.repeat(64))).toBe('a'.repeat(64));
    for (const refused of [
      '', 'a'.repeat(65), '../tile', 'tile/one', 'Tile', 'tile.owd', '-tile', 'tile-', 'tile--one',
      'https://example.com/tile', '/@fs/etc/passwd', 'tile one', 'tile%2Fone',
    ]) {
      expect(name(refused)).toBeNull();
    }
    expect(generatedTileEvaluationName('?preview=1', true)).toBeNull();
  });
});

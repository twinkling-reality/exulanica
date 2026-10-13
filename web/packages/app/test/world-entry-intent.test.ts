import { describe, expect, it } from 'vitest';
import { matchingRecipeEntry, servedEntryStylePack, worldEntryIntent } from '../src/world-entry-intent.js';
import type { ListedStylePack } from '../src/world-look.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

const requested = { packId: 'exulanica.cozy-town', version: 3, manifestSha256: 'a'.repeat(64) };
const wire = { pack_id: requested.packId, version: requested.version, manifest_sha256: requested.manifestSha256 };
const query = (style: unknown, extra = '') => `?recipe=small_town&style_pack=${encodeURIComponent(JSON.stringify(style))}${extra}`;
const pack: ListedStylePack = {
  pack_id: requested.packId, version: 4, manifest_sha256: 'b'.repeat(64), title: 'Cozy Town',
  description: 'A town look', authors: [], licence: { id: 'CC0', attribution: null },
  earlier_versions: [{ version: 3, manifest_sha256: requested.manifestSha256, preview_sha256: null, preview_media_type: null }],
};

describe('styled world entry intent', () => {
  it('carries a precise pack version with the recipe and values without creating anything', () => {
    const values = { high_street_count: 3, cross_street_hierarchy: 'narrow_street' };
    expect(worldEntryIntent(query(wire, `&values=${encodeURIComponent(JSON.stringify(values))}`)))
      .toEqual({ recipe: 'small_town', values, stylePack: requested });
    expect(worldEntryIntent('?recipe=small_town')).toEqual({ recipe: 'small_town', values: {} });
  });

  it('rejects malformed, oversized, ambiguous or partial bindings instead of dropping the requested look', () => {
    for (const binding of [null, [], {}, { ...wire, version: 0 }, { ...wire, version: 1.5 },
      { ...wire, version: Number.MAX_SAFE_INTEGER + 1 }, { ...wire, manifest_sha256: 'A'.repeat(64) },
      { ...wire, pack_id: '../cozy' }, { ...wire, pack_id: 'a'.repeat(129) }, { ...wire, extra: true },
      { pack_id: wire.pack_id, version: 3 }]) {
      expect(worldEntryIntent(query(binding))).toBeNull();
    }
    expect(worldEntryIntent('?recipe=small_town&style_pack=%7B')).toBeNull();
    expect(worldEntryIntent(`?recipe=small_town&style_pack=${'a'.repeat(1025)}`)).toBeNull();
    expect(worldEntryIntent(query(wire, '&style_pack={}'))).toBeNull();
    expect(worldEntryIntent(query(wire, '&look=toon'))).toBeNull();
  });

  it('preserves exact served historical versions rather than upgrading to the current look', () => {
    expect(servedEntryStylePack(requested, [pack])).toEqual(requested);
    const current = { ...requested, version: pack.version, manifestSha256: pack.manifest_sha256 };
    expect(servedEntryStylePack(current, [pack])).toEqual(current);
  });

  it('refuses an absent pack, digest or mismatched version even when another served pack matches part of it', () => {
    for (const candidate of [
      { ...requested, packId: 'exulanica.toon-town' },
      { ...requested, version: 2 },
      { ...requested, manifestSha256: 'c'.repeat(64) },
      { ...requested, version: 4 },
    ]) expect(() => servedEntryStylePack(candidate, [pack])).toThrow('not available');
    expect(() => servedEntryStylePack(requested, [])).toThrow('not available');
  });

  it('never treats a recipe-only saved entry as evidence that its style matches', () => {
    const saved: SavedWorldEntry = {
      entryId: 'saved', worldId: 'world:generated:one', title: 'A saved town', sourceKind: 'generated',
      sourceSnapshotId: 'source', sourceSnapshotSha256: 'c'.repeat(64), authoredScene: null,
      authoredVersionId: 'authored', authoredStateSha256: 'd'.repeat(64), authoredEditSeq: 0,
      currentAuthoredStateSha256: 'd'.repeat(64), currentAuthoredEditSeq: 0,
      styleVersionId: 'style', revision: 1, availability: 'available', unavailableReason: null,
      sourceAttachments: [], createdAt: '2026-10-11T00:00:00Z', updatedAt: '2026-10-11T00:00:00Z',
      generatedGround: { recipeKey: 'small_town', recipeLabel: 'Small Town', regionId: 'r',
        arrivalMm: [0, 0, 0], arrivalFacingMm: [1, 0], tiles: [], specification: null,
        values: { high_street_count: 3 } },
    };
    expect(matchingRecipeEntry([saved], 'small_town', { high_street_count: 3 })).toBe(saved);
    expect(matchingRecipeEntry([saved], 'small_town', { high_street_count: 3 }, requested)).toBeNull();
  });
});

 it('resolves exact admitted identity across same-id library and workspace packs', () => {
  const own={...pack,source:'workspace' as const,manifest_sha256:'9'.repeat(64),earlier_versions:[]};
  const exact={...requested,version:own.version,manifestSha256:own.manifest_sha256};
  expect(servedEntryStylePack(exact,[pack,own])).toEqual(exact);
 });

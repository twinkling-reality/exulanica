import type { SavedWorldEntry } from './world-entry-api.js';
import type { WorldStylePackBinding } from './world-style-api.js';
import type { ListedStylePack } from './world-look.js';

/** Public recipe links express a selection, never permission to create or open a world. */
export function entryRecipe(search: string): string | null {
  const recipe = new URLSearchParams(search).get('recipe');
  return recipe !== null && /^[a-z][a-z0-9_]{0,63}$/.test(recipe) ? recipe : null;
}

export interface WorldEntryIntent {
  readonly recipe: string;
  readonly values: Readonly<Record<string, number | string>>;
  readonly stylePack?: WorldStylePackBinding;
}

/** Carry configuration data to the existing creation form, whose served schema validates it. */
export function worldEntryIntent(search: string): WorldEntryIntent | null {
  const recipe = entryRecipe(search);
  if (recipe === null) return null;
  const query = new URLSearchParams(search);
  const encoded = query.get('values');
  const style = query.get('style_pack');
  if (query.getAll('style_pack').length > 1 || (style !== null && query.has('look'))) return null;
  if ((encoded?.length ?? 0) > 8192 || (style?.length ?? 0) > 1024) return null;
  try {
    const values: unknown = encoded === null ? {} : JSON.parse(encoded);
    if (values === null || typeof values !== 'object' || Array.isArray(values)) return null;
    const entries = Object.entries(values);
    if (entries.length > 64 || entries.some(([key, value]) =>
      !/^[a-z][a-z0-9_]{0,99}$/.test(key)
      || !(typeof value === 'number' && Number.isSafeInteger(value)
        || typeof value === 'string' && value.length <= 100))) return null;
    let stylePack: WorldStylePackBinding | undefined;
    if (style !== null) {
      const binding: unknown = JSON.parse(style);
      if (binding === null || typeof binding !== 'object' || Array.isArray(binding)) return null;
      const record = binding as Record<string, unknown>;
      if (Object.keys(record).length !== 3
        || typeof record['pack_id'] !== 'string' || !/^[a-z][a-z0-9._-]{0,127}$/.test(record['pack_id'])
        || typeof record['version'] !== 'number' || !Number.isSafeInteger(record['version']) || record['version'] < 1
        || typeof record['manifest_sha256'] !== 'string' || !/^[a-f0-9]{64}$/.test(record['manifest_sha256'])) return null;
      stylePack = { packId: record['pack_id'], version: record['version'], manifestSha256: record['manifest_sha256'] };
    }
    return { recipe, values: Object.fromEntries(entries), ...(stylePack === undefined ? {} : { stylePack }) };
  } catch {
    return null;
  }
}

/** URL data is a request; only a version explicitly served by this installation can be chosen. */
export function servedEntryStylePack(requested: WorldStylePackBinding, packs: readonly ListedStylePack[]): WorldStylePackBinding {
  const versions = packs.filter(item => item.pack_id === requested.packId)
    .flatMap(pack => [pack, ...(pack.earlier_versions ?? [])]);
  if (!versions.some(item => item.version === requested.version && item.manifest_sha256 === requested.manifestSha256)) {
    throw new Error(`The requested look ${requested.packId}, version ${requested.version}, is not available on this installation. Choose another look or use an installation that serves this version.`);
  }
  return { ...requested };
}

/** Resolve only against entries served to this workspace, independent of their display titles. */
export function matchingRecipeEntry(entries: readonly SavedWorldEntry[], recipe: string | null, values: Readonly<Record<string, number | string>> = {}, stylePack?: WorldStylePackBinding): SavedWorldEntry | null {
  // The entry list names a style version, not its pack binding. A styled link therefore opens
  // creation for review instead of substituting or changing a recipe-only match.
  if (recipe === null || stylePack !== undefined) return null;
  return [...entries].filter(entry => entry.generatedGround?.recipeKey === recipe
      && Object.entries(values).every(([key, value]) => entry.generatedGround?.values?.[key] === value))
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt) || a.entryId.localeCompare(b.entryId))[0] ?? null;
}

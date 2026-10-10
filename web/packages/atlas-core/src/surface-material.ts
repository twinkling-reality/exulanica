/**
 * Surface materials: what a surface is drawn in when its look role names a material no style pack
 * states.
 *
 * A world kind's parts name their surfaces by look role (`ground.sand`, `wall.adobe`,
 * `roof.thatched`, `path.desert_track`). A style pack states a surface for some leaves and a
 * `default` for a family, and the pack's one rule (`resolveLookRole`) gives every other leaf that
 * default, so sand, a quay and a beach are all the pack's lawn. The surface material catalog
 * (`assets/catalogs/world-kinds/surface-material.v1.json`) stands between the two: each entry is a
 * material, the words that name it, the families that may wear it and the colour it is drawn in.
 * A leaf is read by its words, so a compound a model wrote (`forest_floor`, `tent_floor`,
 * `lake_shore`) finds its material.
 *
 * THE ORDER (`resolveSurfaceLookRole`): the pack's own dressing for the leaf, exactly as before; then,
 * for a leaf that names a material, the pack's own surface for that material (`family.material`),
 * or the pack's family default where the catalog says that default is this material already (every
 * pack's ground default is a lawn), or the catalog's colour, which the caller draws in the pack's
 * shading; then the family default as before. A pack that knows nothing of sand still draws sand, in
 * its own light, and a pack that wants its own sand states `ground.sand`.
 *
 * `resolveLookRole` is not changed and a town does not come through here: a town's tiles name only
 * leaves its packs state.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

import {
  resolveLookRole, splitLookRole,
  type Dressing, type LookFamily, type ResolvedStylePack, type Srgb8, type StylePackSwatch, type StyleSlot,
} from './style-pack.js';

export const SURFACE_MATERIAL_CATALOG_ID = 'surface-material';

/** One material of the catalog, as read. */
export interface SurfaceMaterial {
  readonly key: string;
  /** The words that name it in a leaf, each a whole leaf or one of a leaf's words. */
  readonly words: readonly string[];
  /** What it is, in plain words, for a person and for the form a model fills. */
  readonly plain: string;
  /** The look families that may wear it. */
  readonly families: readonly string[];
  /** The families whose default in every pack is this material already. */
  readonly familyDefault: readonly string[];
  /** The colour it is drawn in where no pack states its own, as a swatch a material is made from. */
  readonly swatch: StylePackSwatch;
}

/** The catalog as read: its materials in the file's order, which is the order a word is looked up in. */
export interface SurfaceMaterials {
  readonly version: number;
  readonly materials: readonly SurfaceMaterial[];
  /** Every family some material may be worn by: the families a leaf's words are read for. */
  readonly families: ReadonlySet<string>;
}

/** A slot drawn in a catalog material's own colour, under the role a pack would state it by. */
export interface MaterialDressing {
  readonly kind: 'material';
  /** `family.material`: the role a pack states to draw this material its own way. */
  readonly role: string;
  readonly material: SurfaceMaterial;
}

const KEY = /^[a-z][a-z0-9_]{0,39}$/;

function refuse(where: string, detail: string): never {
  throw new TypeError(`surface material catalog: ${where} ${detail}`);
}

function keys(value: unknown, where: string, allowEmpty: boolean): string[] {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) return refuse(where, 'must be a list of keys');
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== 'string' || !KEY.test(item)) return refuse(where, `holds ${JSON.stringify(item)}, which is not a key`);
    if (seen.has(item)) return refuse(where, `names ${item} twice`);
    seen.add(item);
  }
  return [...seen];
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) return refuse(where, `must be a whole number from ${min} to ${max}`);
  return value;
}

/** Read the catalog's text, or refuse it by naming the first entry that is not a material. */
export function readSurfaceMaterials(text: string): SurfaceMaterials {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== SURFACE_MATERIAL_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the surface material catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const materials: SurfaceMaterial[] = [];
  const taken = new Set<string>();
  const families = new Set<string>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = entry?.['key'];
    if (typeof key !== 'string' || !KEY.test(key)) return refuse('an entry', `has the key ${JSON.stringify(key)}`);
    if (taken.has(key)) return refuse(key, 'is stated twice');
    taken.add(key);
    const plain = entry['plain'];
    if (typeof plain !== 'string' || plain.trim() === '' || plain !== plain.trim()) return refuse(key, 'says nothing plain of what it is');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
    const worn = keys(entry['families'], `${key}.families`, false);
    const standsAs = keys(entry['family_default'], `${key}.family_default`, true);
    if (standsAs.some((family) => !worn.includes(family))) return refuse(key, 'is a default of a family it may not be worn by');
    const colour = entry['srgb8'];
    if (!Array.isArray(colour) || colour.length !== 3) return refuse(`${key}.srgb8`, 'must be three sRGB bytes');
    const srgb8 = colour.map((channel, index) => whole(channel, `${key}.srgb8[${index}]`, 0, 255)) as unknown as Srgb8;
    for (const family of worn) families.add(family);
    materials.push(Object.freeze({
      key,
      words: Object.freeze(keys(entry['words'], `${key}.words`, false)),
      plain,
      families: Object.freeze(worn),
      familyDefault: Object.freeze(standsAs),
      swatch: Object.freeze({
        key: `material:${key}`,
        srgb8,
        roughness_permille: whole(entry['roughness_permille'], `${key}.roughness_permille`, 0, 1000),
        metalness_permille: whole(entry['metalness_permille'], `${key}.metalness_permille`, 0, 1000),
        emission_permille: 0,
      }),
    }));
  }
  return Object.freeze({ version, materials: Object.freeze(materials), families });
}

/**
 * The material a leaf names for a family, or null when none of its words names one. The whole leaf
 * is tried first, then each of its words in the order written (`forest_floor` is the forest's
 * floor, `tent_floor` a tent's, `classroom_floor` a plain floor); for each, the first material in
 * the catalog's order that the word names and the family may wear, so `tile` is a floor's tile
 * underfoot and a clay tile on a roof, and a `lake_shore` named for ground is not water.
 */
export function materialOfLeaf(materials: SurfaceMaterials, family: string, leaf: string): SurfaceMaterial | null {
  if (!materials.families.has(family)) return null;
  for (const word of [leaf, ...leaf.split('_')]) {
    const found = materials.materials.find((material) => material.families.includes(family) && material.words.includes(word));
    if (found !== undefined) return found;
  }
  return null;
}

/**
 * Whether a slot's leaf is thrown away: it names no material the catalog knows, in a family the
 * catalog serves, and is not the family's `default`. Such a slot is drawn as its family's default,
 * and a caller counts it so the next catalog is written from the words that were written.
 */
export function unknownSurfaceLeaf(materials: SurfaceMaterials, lookRole: string): boolean {
  const { family, leaf } = splitLookRole(lookRole, 'lookRole');
  return leaf !== 'default' && materials.families.has(family) && materialOfLeaf(materials, family, leaf) === null;
}

/**
 * What dresses one slot of a world made from a kind: `resolveLookRole`'s answer wherever the pack
 * dresses the leaf itself, and otherwise the leaf's material before the family's default (see THE
 * ORDER above). `accepts` is `resolveLookRole`'s: a slot that takes only a piece takes no material.
 */
export function resolveSurfaceLookRole(
  pack: ResolvedStylePack,
  slot: StyleSlot,
  families: ReadonlyMap<string, LookFamily>,
  accepts: 'surface' | 'module' | 'either',
  materials: SurfaceMaterials,
): Dressing | MaterialDressing | null {
  const plain = resolveLookRole(pack, slot, families, accepts);
  if (plain !== null && plain.role === slot.lookRole) return plain;
  const { family, leaf } = splitLookRole(slot.lookRole, 'lookRole');
  const kind = families.get(family);
  if (kind === undefined || accepts === 'module' || leaf === 'default') return plain;
  if (kind.dressing !== 'surface' && kind.dressing !== 'both') return plain;
  const material = materialOfLeaf(materials, family, leaf);
  if (material === null) return plain;
  if (material.familyDefault.includes(family) && plain?.kind === 'surface') return plain;
  const role = `${family}.${material.key}`;
  if (role !== slot.lookRole) {
    const own = resolveLookRole(pack, { ...slot, lookRole: role }, families, 'surface');
    if (own !== null && own.role === role) return own;
  }
  return { kind: 'material', role, material };
}

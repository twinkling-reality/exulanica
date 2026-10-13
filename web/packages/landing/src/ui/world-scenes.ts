import { WORLD_CAPTURES } from '../content/world-captures.js';

/** Genuine app captures. These identifiers describe configurations, not hosted world IDs. */
export interface WorldScene {
  readonly id: string;
  readonly recipe: string;
  readonly title: string;
  readonly image: string;
  readonly alt: string;
  readonly description: string;
  readonly name?: string;
  readonly appearance?: string;
  readonly stylePack?: { readonly pack_id: string; readonly version: number; readonly manifest_sha256: string };
  readonly values: Readonly<Record<string, string | number>>;
}
const LEGACY_WORLD_SCENES: readonly WorldScene[] = [
  { id: 'market-town', recipe: 'market_town', title: 'Market Town', image: '/worlds/market-town.jpg', alt: 'An Exulanica market town with tree-lined sidewalks, storefronts, and vehicles.', description: 'Three tiles, longer blocks, and one high street. A starting point for a town of shops and homes.', values: { city_extent_x_mm: 384000, block_length_mm: 140000, storey_band_low: 2, storey_band_high: 4, high_street_count: 1, cross_street_hierarchy: 'local_street' } },
  { id: 'small-town', recipe: 'small_town', title: 'Small Town', image: '/worlds/small-town.jpg', alt: 'An Exulanica small town street with buildings, trees, traffic signals, and vehicles.', description: 'Two tiles, shorter blocks, and one high street. A compact town to build on.', values: { city_extent_x_mm: 256000, block_length_mm: 90000, storey_band_low: 2, storey_band_high: 4, high_street_count: 1, cross_street_hierarchy: 'local_street' } },
  { id: 'narrow-streets', recipe: 'small_town', title: 'Narrow Streets', image: '/worlds/narrow-streets.jpg', alt: 'A generated town of closely spaced rowhouses and narrow cross streets in Exulanica.', description: 'Narrow cross streets and three-to-five-storey buildings, with rowhouses on the residential lots.', values: { cross_street_hierarchy: 'narrow_street', storey_band_low: 3, storey_band_high: 5, typology_weight_rowhouse_permille: 1000, typology_weight_apartment_block_permille: 0, typology_weight_loft_building_permille: 0, typology_weight_mansion_block_permille: 0, typology_weight_shophouse_permille: 0 } },
  { id: 'three-high-streets', recipe: 'market_town', title: 'Three High Streets', image: '/worlds/three-high-streets.jpg', alt: 'A generated market town with three parallel high streets in Exulanica.', description: 'Three high streets across a market town. A different street network from the one-high-street preset.', values: { high_street_count: 3 } },
];

/** The featured catalog is derived from saved-world capture records, not independent prose. */
export const WORLD_SCENES: readonly WorldScene[] = WORLD_CAPTURES.map(capture => {
  const name = capture.saved_world_title.split(' · ')[0]!;
  const appearance = capture.style_title.replace(/\b\w/g, character => character.toUpperCase());
  const values = capture.values;
  const settings = `${values.storey_band_low}–${values.storey_band_high} Storeys · ${values.high_street_count} High Street${values.high_street_count === 1 ? '' : 's'}`;
  return {
    id: capture.id, recipe: capture.recipe, title: `${name} · ${appearance}`, name, appearance,
    image: `/worlds/${capture.image}`, alt: `${name}, captured in Exulanica with ${appearance}.`,
    description: `${appearance} · ${settings}`, values, stylePack: capture.style_pack,
  };
});

/** Preserve deployment parameters and carry the actual configuration into app selection. */
export function worldEntryHref(scene: WorldScene, atlasHref: string | null): string {
  if (!atlasHref) return '/docs/self-hosting';
  const destination = new URL(atlasHref);
  destination.searchParams.set('recipe', scene.recipe);
  destination.searchParams.set('values', JSON.stringify(scene.values));
  if (scene.stylePack) {
    destination.searchParams.delete('look');
    destination.searchParams.set('style_pack', JSON.stringify(scene.stylePack));
  }
  return destination.href;
}

/** Old preview-page bookmarks retain their configuration-aware application handoff. */
export function retiredWorldDestination(path: string, atlasHref: string | null): string | null {
  const scene = [...WORLD_SCENES, ...LEGACY_WORLD_SCENES].find(scene => `/worlds/${scene.id}` === path.replace(/\/+$/, ''));
  return scene ? worldEntryHref(scene, atlasHref) : null;
}

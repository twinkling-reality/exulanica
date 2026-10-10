/** Genuine app captures. These identifiers describe previews, not hosted world IDs. */
export const WORLD_SCENES = [
  { id: 'market-town', recipe: 'market_town', title: 'Market Town', image: '/worlds/market-town.jpg', alt: 'A rendered market town with tree-lined sidewalks, storefronts, and vehicles.', description: 'Streets, storefronts, and places to gather.' },
  { id: 'small-town', recipe: 'small_town', title: 'Small Town', image: '/worlds/small-town.jpg', alt: 'A rendered small town street with buildings, trees, traffic signals, and vehicles.', description: 'A neighborhood of roads, homes, and trees.' },
] as const;
export type WorldScene = typeof WORLD_SCENES[number];

/** The app owns saved-world selection. Preview names are not workspace world IDs. */
export function worldEntryHref(scene: WorldScene, atlasHref: string | null): string {
  if (!atlasHref) return `/waitlist?world=${scene.id}`;
  const destination = new URL(atlasHref);
  destination.searchParams.set('recipe', scene.recipe);
  return destination.href;
}

/** Old preview-page bookmarks hand off without rendering another description page. */
export function retiredWorldDestination(path: string, atlasHref: string | null): string | null {
  const scene = WORLD_SCENES.find(scene => `/worlds/${scene.id}` === path.replace(/\/+$/, ''));
  return scene ? worldEntryHref(scene, atlasHref) : null;
}

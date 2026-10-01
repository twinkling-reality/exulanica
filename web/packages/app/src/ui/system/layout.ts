/**
 * The layout manager: the one owner of where a surface sits on the screen.
 *
 * It creates the named regions (layout.css gives each its box and its layer from the z table in
 * tokens.css) and is the only code that puts a surface into one. A surface keeps its own
 * open and close behaviour; the layout watches its `hidden` attribute and enforces the region's
 * rule:
 *
 * - `inspector` and `sheet` are exclusive. When a surface there becomes visible, every other
 *   visible surface in the same region is closed through the close handler it was placed with,
 *   so two panels can never be drawn in the same column.
 * - `#shell[data-inspector-open]` is set while anything in `inspector` or `sheet` is visible, so
 *   the dock, toasts and heads-up stack centre themselves in the free part of the world.
 *
 * Nothing here knows what a panel is about.
 */

export const REGION_NAMES = [
  'top-bar', 'tool-rail', 'inspector', 'sheet', 'dock', 'toast', 'hud', 'overlay',
] as const;
export type RegionName = typeof REGION_NAMES[number];

const EXCLUSIVE: ReadonlySet<RegionName> = new Set(['inspector', 'sheet']);
const OPENS_INSPECTOR: ReadonlySet<RegionName> = new Set(['inspector', 'sheet']);
/**
 * The regions a major surface (the World menu, Compare, Settings and the rest) covers: made inert
 * while one is open so Tab stays in it. Toasts stay outside so a notice is still read.
 */
export const MODAL_BACKGROUND_REGIONS: readonly RegionName[] = REGION_NAMES.filter((region) => region !== 'toast');

export interface PlaceOptions {
  /** How the layout closes this surface when another takes its exclusive region. */
  readonly close?: () => void;
  /**
   * An attachment is shown with the region's surfaces (a tab strip above a panel); it never
   * takes the region and is never closed by it.
   */
  readonly attachment?: boolean;
}

export interface Layout {
  readonly regions: Readonly<Record<RegionName, HTMLElement>>;
  /** Put a surface in a region. Moving a node keeps its listeners and state. */
  place(region: RegionName, surface: HTMLElement, options?: PlaceOptions): void;
  /** The visible surfaces of a region, in document order. */
  visible(region: RegionName): readonly HTMLElement[];
  /**
   * Route surfaces that other code appends straight to the shell (a notice a world adds when it
   * opens) into a region, by a selector they match.
   */
  adopt(selector: string, region: RegionName, options?: PlaceOptions): void;
  /** Re-apply the region rules now (after a change the observer cannot see, such as CSS). */
  reflect(): void;
  /** Called after every change in what the regions show; returns the unsubscribe. */
  onChange(listener: () => void): () => void;
  dispose(): void;
}

interface Placement {
  readonly region: RegionName;
  readonly options: PlaceOptions;
  wasVisible: boolean;
}

export function isShown(surface: HTMLElement): boolean {
  if (surface.hidden) return false;
  const view = surface.ownerDocument.defaultView;
  return view === null || view.getComputedStyle(surface).display !== 'none';
}

export function createLayout(shell: HTMLElement): Layout {
  const document = shell.ownerDocument;
  const regions = {} as Record<RegionName, HTMLElement>;
  for (const name of REGION_NAMES) {
    const node = document.createElement('div');
    node.className = 'x-region';
    node.dataset['region'] = name;
    regions[name] = node;
  }
  const placements = new Map<HTMLElement, Placement>();
  const changeListeners = new Set<() => void>();

  let reflecting = false;
  const reflect = (): void => {
    if (reflecting) return;
    reflecting = true;
    try {
      // A newly shown surface in an exclusive region closes the others shown there.
      for (const [surface, placement] of placements) {
        const shown = isShown(surface);
        const opened = shown && !placement.wasVisible;
        placement.wasVisible = shown;
        if (!opened || placement.options.attachment === true || !EXCLUSIVE.has(placement.region)) continue;
        for (const [other, its] of placements) {
          if (other === surface || its.region !== placement.region || its.options.attachment === true) continue;
          if (!isShown(other)) continue;
          if (its.options.close !== undefined) its.options.close();
          else other.hidden = true;
          its.wasVisible = isShown(other);
        }
      }
      const open = [...placements].some(([surface, placement]) =>
        OPENS_INSPECTOR.has(placement.region) && placement.options.attachment !== true && isShown(surface));
      shell.toggleAttribute('data-inspector-open', open);
    } finally {
      reflecting = false;
    }
    for (const listener of changeListeners) listener();
  };

  const observer = new MutationObserver(() => reflect());
  const adoptions: { readonly selector: string; readonly region: RegionName; readonly options: PlaceOptions }[] = [];
  const route = (): void => {
    for (const child of [...shell.children]) {
      if (!(child instanceof HTMLElement) || child.classList.contains('x-region')) continue;
      const rule = adoptions.find((candidate) => child.matches(candidate.selector));
      if (rule !== undefined) layout.place(rule.region, child, rule.options);
    }
  };
  const arrivals = new MutationObserver(route);

  const layout: Layout = {
    regions,
    place(region, surface, options = {}) {
      const target = regions[region];
      if (!target.isConnected) shell.append(target);
      target.append(surface);
      placements.set(surface, { region, options, wasVisible: isShown(surface) });
      observer.observe(surface, { attributes: true, attributeFilter: ['hidden', 'style', 'class'] });
      reflect();
    },
    visible(region) {
      return [...placements].filter(([surface, placement]) =>
        placement.region === region && isShown(surface)).map(([surface]) => surface);
    },
    adopt(selector, region, options = {}) {
      adoptions.push({ selector, region, options });
      if (adoptions.length === 1) arrivals.observe(shell, { childList: true });
      route();
    },
    reflect,
    onChange(listener) {
      changeListeners.add(listener);
      return () => changeListeners.delete(listener);
    },
    dispose() {
      changeListeners.clear();
      observer.disconnect();
      arrivals.disconnect();
      placements.clear();
    },
  };
  return layout;
}

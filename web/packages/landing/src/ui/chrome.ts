/**
 * One signed-out navigation set shared by every landing surface.
 *
 * Resources remains one Companion station. Its ordinary links live in a secondary disclosure, so
 * documentation and source code do not become extra primary destinations.
 */

import { el } from './dom.js';
import { createCompanionMenuMarker } from './companion-menu-marker.js';

export const REPOSITORY_URL = 'https://github.com/twinkling-reality/exulanica';
/** The documents this page is built from, which are the same ones it is checked against. */
export const DOCS_URL = `${REPOSITORY_URL}/tree/main/docs`;

/** Where the visitor is. Informational surfaces retain a direct return to the title. */
export type Surface = 'title' | 'purpose' | 'capabilities';

export interface ChromeActions {
  onHome(): void;
  onPurpose(): void;
  onCapabilities(): void;
}

export interface ChromeOptions extends ChromeActions {
  readonly atlasHref: string | null;
}

/**
 * One destination. Every item remains a native link or button, so the game-title hierarchy does
 * not compromise ordinary browser and assistive-technology navigation.
 */
function destination(
  label: string,
  id: string,
  onPick: () => void,
  href?: string,
  primary = false,
): HTMLElement {
  const inner = [el('span', { class: 'destination-label', text: label })];
  const attrs: Record<string, string> = {
    class: primary ? 'destination destination-primary' : 'destination',
    id,
  };
  if (href !== undefined) {
    const link = el('a', {
      ...attrs,
      href,
      ...(href.startsWith('http') ? { rel: 'noreferrer' } : {}),
    }, inner);
    link.addEventListener('click', onPick);
    return link;
  }
  const b = el('button', { ...attrs, type: 'button' }, inner);
  b.addEventListener('click', onPick);
  return b;
}

export interface Chrome {
  readonly root: HTMLElement;
  setSurface(surface: Surface): void;
}

export function buildChrome(options: ChromeOptions): Chrome {
  const bar = el('nav', { class: 'topbar', 'aria-label': 'Primary navigation' });

  const home = destination('Return', 'path-home', options.onHome, '#title');
  const purpose = destination('Purpose', 'path-purpose', options.onPurpose, '#purpose');
  const capabilities = destination(
    'Capabilities',
    'path-capabilities',
    options.onCapabilities,
    '#capabilities',
  );
  const atlas = destination(
    'Enter Exulanica',
    'path-enter',
    () => {},
    options.atlasHref ?? undefined,
    true,
  );
  const atlasStatus = el('p', {
    class: 'entry-status',
    id: 'atlas-status',
    role: 'status',
    text: 'The world is not connected in this build.',
  });
  if (options.atlasHref === null) {
    const disabledAtlas = atlas as HTMLButtonElement;
    disabledAtlas.disabled = true;
    disabledAtlas.setAttribute('aria-describedby', atlasStatus.id);
  } else {
    atlasStatus.hidden = true;
  }

  const resources = destination('Resources', 'path-resources', () => {});
  resources.setAttribute('aria-expanded', 'false');
  resources.setAttribute('aria-controls', 'resource-links');

  const resourceLinks = el('div', {
    class: 'resource-disclosure',
    id: 'resource-links',
    'aria-label': 'Resources',
  });
  resourceLinks.hidden = true;
  const resourceBack = destination('Back', 'resource-back', () => {});
  const documentation = destination('Documentation', 'resource-docs', () => {}, DOCS_URL);
  const github = destination('GitHub', 'resource-github', () => {}, REPOSITORY_URL);
  resourceLinks.append(resourceBack, documentation, github);

  const left = el('div', { class: 'destinations' });
  const marker = createCompanionMenuMarker();
  left.append(
    marker,
    home,
    atlas,
    atlasStatus,
    purpose,
    capabilities,
    resourceLinks,
    resources,
  );

  const targets = [home, atlas, purpose, capabilities, resources];
  let currentSurface: Surface = 'title';
  let hovered: HTMLElement | null = null;
  let focused: HTMLElement | null = null;
  let previousTarget = atlas;
  let motionPhase = false;
  let outsideListener: ((event: PointerEvent) => void) | null = null;
  let escapeListener: ((event: KeyboardEvent) => void) | null = null;

  const defaultTarget = (): HTMLElement => {
    if (currentSurface === 'purpose') return purpose;
    if (currentSurface === 'capabilities') return capabilities;
    return atlas;
  };

  const placeMarker = (): void => {
    const target = focused ?? hovered ?? defaultTarget();
    marker.dataset['state'] = focused !== null || hovered !== null ? 'attending' : 'resting';
    marker.dataset['target'] = target.id;
    if (target !== previousTarget) {
      const previousIndex = targets.indexOf(previousTarget);
      const nextIndex = targets.indexOf(target);
      const direction = nextIndex >= previousIndex ? 'down' : 'up';
      const distance = Math.max(1, Math.abs(nextIndex - previousIndex));
      marker.style.setProperty('--companion-travel-ms', `${Math.min(400, 280 + (distance - 1) * 60)}ms`);
      motionPhase = !motionPhase;
      marker.dataset['motion'] = `${direction}-${motionPhase ? 'a' : 'b'}`;
      previousTarget = target;
    }
    requestAnimationFrame(() => {
      marker.style.setProperty(
        '--companion-marker-y',
        `${target.offsetTop + target.offsetHeight / 2}px`,
      );
      requestAnimationFrame(() => {
        marker.dataset['positioned'] = 'true';
      });
    });
  };

  const applyPrimaryVisibility = (): void => {
    const resourcesOpen = !resourceLinks.hidden;
    home.hidden = resourcesOpen || currentSurface === 'title';
    atlas.hidden = resourcesOpen || currentSurface !== 'title';
    atlasStatus.hidden =
      resourcesOpen || currentSurface !== 'title' || options.atlasHref !== null;
    purpose.hidden = resourcesOpen;
    capabilities.hidden = resourcesOpen;
  };

  const closeResources = (restoreFocus: boolean): void => {
    if (resourceLinks.hidden) return;
    resourceLinks.hidden = true;
    resources.setAttribute('aria-expanded', 'false');
    applyPrimaryVisibility();
    if (outsideListener) document.removeEventListener('pointerdown', outsideListener);
    if (escapeListener) document.removeEventListener('keydown', escapeListener);
    outsideListener = null;
    escapeListener = null;
    if (restoreFocus) resources.focus({ preventScroll: true });
  };

  const openResources = (): void => {
    if (!resourceLinks.hidden) {
      closeResources(false);
      return;
    }
    resourceLinks.hidden = false;
    resources.setAttribute('aria-expanded', 'true');
    applyPrimaryVisibility();
    focused = resources;
    placeMarker();

    outsideListener = (event): void => {
      if (event.target instanceof Node && left.contains(event.target)) return;
      closeResources(false);
    };
    escapeListener = (event): void => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeResources(true);
    };
    document.addEventListener('pointerdown', outsideListener);
    document.addEventListener('keydown', escapeListener);
  };
  resources.addEventListener('click', openResources);
  resourceBack.addEventListener('click', () => closeResources(true));

  for (const target of targets) {
    target.addEventListener('pointerenter', () => {
      hovered = target;
      placeMarker();
    });
    target.addEventListener('pointerleave', () => {
      if (hovered === target) hovered = null;
      placeMarker();
    });
    target.addEventListener('focus', () => {
      focused = target;
      placeMarker();
    });
    target.addEventListener('blur', () => {
      if (focused === target) focused = null;
      placeMarker();
    });
  }

  resourceLinks.addEventListener('focusin', () => {
    focused = resources;
    placeMarker();
  });
  resourceLinks.addEventListener('focusout', (event) => {
    const next = event.relatedTarget;
    if (next instanceof Node && resourceLinks.contains(next)) return;
    if (focused === resources && document.activeElement !== resources) focused = null;
    placeMarker();
  });

  bar.append(left);

  return {
    root: bar,
    setSurface(surface) {
      currentSurface = surface;
      closeResources(false);
      hovered = null;
      focused = null;
      applyPrimaryVisibility();
      for (const [node, owns] of [
        [purpose, surface === 'purpose'],
        [capabilities, surface === 'capabilities'],
      ] as const) {
        if (owns) node.setAttribute('aria-current', 'page');
        else node.removeAttribute('aria-current');
      }
      placeMarker();
    },
  };
}

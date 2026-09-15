/**
 * One signed-out navigation set shared by every landing surface.
 *
 * Resources remains one Companion station. Its ordinary links live in a secondary disclosure, so
 * documentation, research, and source code do not become extra primary destinations.
 */

import {
  companionAppearanceConfiguration,
  DEFAULT_COMPANION,
  type CompanionBodyVariant,
  type CompanionColorVariant,
} from '@exulanica/presentation';

import { el } from './dom.js';
import { createCompanionMenuMarker, MENU_FACE } from './companion-menu-marker.js';

/**
 * The silhouette the Companion wears at each station.
 *
 * This was a face per station until the faces turned out to be the wrong channel: at this size
 * the relaxed and pleased poses read as squinting rather than as character. Shape carries it
 * instead, the eyes stay open and identical everywhere, and each station keeps its own colour.
 * Meanings are as close to literal as the contract's shapes allow: a doorway at the way in and a
 * circle for return. All of them come from one family of silhouettes, so the marker changes shape
 * between stations without changing what it is.
 */
const STATION_BODY: Readonly<Record<string, CompanionBodyVariant>> = Object.freeze({
  'path-home': 'circle',
  /*
   * Enter and the waitlist share the arch because they share the slot and the job: they are the
   * way in, and only ever one of them exists. A doorway is the honest shape for both.
   */
  'path-enter': 'arch',
  'path-waitlist': 'arch',
  'path-purpose': 'squircle',
  'path-capabilities': 'cloud',
  'path-resources': 'pebble',
});

/**
 * EXPERIMENT: the Companion's own colour, per station.
 *
 * companion-appearance.ts argues against this. It records that the saturated variants read as a
 * sticker on the field and that ink is the default for that reason, and that colour there is a
 * device preference a person sets in Customize rather than something a menu assigns. This is here
 * to see the argument rather than take it on faith. Deleting this map and the two custom
 * properties it sets returns the Companion to one ink identity; nothing else depends on it.
 */
export const STATION_COLOR: Readonly<Record<string, CompanionColorVariant>> = Object.freeze({
  'path-home': 'ink',
  'path-enter': 'mint',
  'path-purpose': 'periwinkle',
  'path-capabilities': 'orange',
  'path-resources': 'rose',
  'path-waitlist': 'iris',
});

/** The contract owns the colours; this only picks which one a station asks for. */
const stationInk = (station: string): { body: string; eye: string } => {
  const configuration = companionAppearanceConfiguration({
    body: DEFAULT_COMPANION.bodyVariant,
    color: STATION_COLOR[station] ?? DEFAULT_COMPANION.colorVariant,
    face: MENU_FACE,
  });
  return { body: configuration.bodyColor, eye: configuration.eyeColor };
};

export const REPOSITORY_URL = 'https://github.com/twinkling-reality/exulanica';
/** The documents this page is built from, which are the same ones it is checked against. */
export const DOCS_URL = `${REPOSITORY_URL}/tree/main/docs`;

/** Where the visitor is. Informational surfaces retain a direct return to the title. */
export type Surface =
  | 'title'
  | 'purpose'
  | 'capabilities'
  | 'research'
  | 'waitlist'
  | 'developers';

export interface ChromeActions {
  onHome(): void;
  onPurpose(): void;
  onCapabilities(): void;
  onResearch(): void;
  onWaitlist(): void;
  onDevelopers(): void;
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
  /*
   * One way in, and it is whichever one is true. Never both.
   *
   * With a world to enter the column leads with Enter Exulanica. Without one it leads with the
   * waitlist, and the Enter station is not rendered at all. Showing the pair together offers a
   * visitor two ways in when only one of them exists, and showing Enter greyed out with a caption
   * saying the world is not connected is the same false promise with a footnote. Only the station
   * that can be acted on is built.
   */
  const connected = options.atlasHref !== null;
  const atlas = destination(
    'Enter Exulanica',
    'path-enter',
    () => {},
    options.atlasHref ?? undefined,
    true,
  );
  const waitlist = destination(
    'Join the waitlist',
    'path-waitlist',
    options.onWaitlist,
    '#waitlist',
    !connected,
  );
  /** Whichever station leads the column. The marker rests here, and it is never a dead control. */
  const wayIn = connected ? atlas : waitlist;

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
  const research = destination('Research', 'path-research', options.onResearch, '#research');
  /*
   * Scaffolded, and the one deliberate dead control on this page.
   *
   * Everything else in this column is either live or absent, and the disabled Enter Exulanica
   * station was deleted for exactly the reason this entry reintroduces: a greyed word is a
   * promise a visitor cannot act on. This one is kept on the operator's instruction so the route
   * and its slot exist before the writing does. Give the page copy and delete the two lines
   * below, and it becomes an ordinary destination.
   */
  const developers = destination('Developers', 'path-developers', options.onDevelopers);
  (developers as HTMLButtonElement).disabled = true;
  developers.setAttribute('aria-describedby', 'developers-pending');
  /*
   * The reason sits beside the control, not inside it. Nested, it joined the button's accessible
   * name, so the entry announced itself as "Developers Not written yet" and the rendered text of
   * the disclosure stopped matching its labels.
   */
  const developersPending = el('span', {
    class: 'sr-only',
    id: 'developers-pending',
    text: 'Not written yet',
  });

  const github = destination('GitHub', 'resource-github', () => {}, REPOSITORY_URL);
  resourceLinks.append(resourceBack, documentation, research, developers, developersPending, github);

  /*
   * The order attention travels down the column, used to stagger an entry's arrival.
   *
   * Return and Enter Exulanica never appear at the same time, so they share the first position.
   * The stylesheet reads this as a delay multiplier; nothing else depends on it, and an entry
   * without one simply arrives first.
   */
  for (const [node, order] of [
    [home, 0],
    [atlas, 0],
    [waitlist, 0],
    [purpose, 2],
    [capabilities, 3],
    [resources, 4],
    [resourceBack, 0],
    [documentation, 1],
    [research, 2],
    [developers, 3],
    [github, 4],
  ] as const) {
    node.style.setProperty('--enter-index', String(order));
  }

  const left = el('div', { class: 'destinations' });
  const marker = createCompanionMenuMarker();
  left.append(marker, home, wayIn, purpose, capabilities, resourceLinks, resources);

  const targets = [home, wayIn, purpose, capabilities, resources];
  let currentSurface: Surface = 'title';
  let hovered: HTMLElement | null = null;
  let focused: HTMLElement | null = null;
  let previousTarget = wayIn;
  let occupied: HTMLElement | null = null;
  let motionPhase = false;
  let outsideListener: ((event: PointerEvent) => void) | null = null;
  let escapeListener: ((event: KeyboardEvent) => void) | null = null;

  const defaultTarget = (): HTMLElement => {
    if (currentSurface === 'purpose') return purpose;
    if (currentSurface === 'capabilities') return capabilities;
    if (currentSurface === 'research') return resources;
    // A connected build has no waitlist station, so the surface rests the Companion on Return.
    if (currentSurface === 'waitlist') return connected ? home : waitlist;
    // Developers has no station the Companion can stand on while it is disabled.
    if (currentSurface === 'developers') return resources;
    return wayIn;
  };

  const placeMarker = (): void => {
    const target = focused ?? hovered ?? defaultTarget();
    marker.dataset['state'] = focused !== null || hovered !== null ? 'attending' : 'resting';
    marker.dataset['target'] = target.id;
    marker.dataset['body'] = STATION_BODY[target.id] ?? 'circle';
    marker.dataset['face'] = MENU_FACE;
    const ink = stationInk(target.id);
    marker.style.setProperty('--companion-body', ink.body);
    marker.style.setProperty('--companion-eye', ink.eye);
    /*
     * The Companion and the station mark are two indicators of one thing, and they share a column,
     * so the mark yields where the character is standing. Before the marks were filled this
     * overlapped invisibly; a filled mark sits on the Companion's face.
     */
    if (occupied !== target) {
      if (occupied) delete occupied.dataset['companion'];
      target.dataset['companion'] = 'here';
      occupied = target;
    }
    if (target !== previousTarget) {
      const previousIndex = targets.indexOf(previousTarget);
      const nextIndex = targets.indexOf(target);
      const direction = nextIndex >= previousIndex ? 'down' : 'up';
      const distance = Math.max(1, Math.abs(nextIndex - previousIndex));
      marker.style.setProperty('--companion-travel-ms', `${Math.min(400, 280 + (distance - 1) * 60)}ms`);
      motionPhase = !motionPhase;
      marker.dataset['motion'] = `${direction}-${motionPhase ? 'a' : 'b'}`;
      // Arriving somewhere new is what a blink is for here: it covers the change of expression,
      // so the eyes are shut at the moment the new pose is revealed rather than morphing.
      marker.dataset['arrive'] = motionPhase ? 'a' : 'b';
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
    // Enter belongs to the title; the waitlist stays reachable from the reading surfaces too.
    atlas.hidden = resourcesOpen || currentSurface !== 'title';
    waitlist.hidden = resourcesOpen;
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
        [research, surface === 'research'],
        [waitlist, surface === 'waitlist'],
        [developers, surface === 'developers'],
      ] as const) {
        if (owns) node.setAttribute('aria-current', 'page');
        else node.removeAttribute('aria-current');
      }
      placeMarker();
    },
  };
}

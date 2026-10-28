import './world-motion.css';
import './front-door.css';
import captures from 'virtual:front-door-captures';
import { createScenePreview, scenePreviewPage } from './front-door-preview.ts';
import { showWorldDetails } from './front-door-details.ts';
import { offerOpenAndDetailsOnly } from './front-door-card.ts';
import { endOpening, handOverOpening } from './world-opening.ts';
import { showBeingMade } from './create-world.ts';
import { offerIntegrations } from './integrations.ts';
import { makeShowcaseCopy, showcaseOffers, type ShowcaseOffer } from './showcase-world.ts';
import { capturedPicture, frontDoorAddress, leadsWithCreate, openWorldAddress, worldAddress } from './front-door-routes.mjs';
import { ownWorldPicture, worldPicture } from '/src/composition/world-pictures.ts';
import { icon, type IconName } from '/src/ui/system/icon.ts';
import type { Credentials } from '/src/config.ts';
import type { WorldOffer } from '/src/composition/world-entry.ts';
import type { SavedWorldEntry } from '/src/world-entry-api.ts';

// The workspace's front door: the chosen world large behind its title, a filmstrip of the saved
// worlds under it, then the installation's showcase worlds the workspace does not hold yet, and Open
// into the workspace's own world view. It rearranges the app's Your worlds (composition/world-entry.ts)
// and keeps that surface's actions, keys and availability rules.

/** The saved world last chosen here, kept in this tab's history so Back and a return find it again. */
const CHOSEN = 'frontDoorEntryId';

/** A card's picture: a private capture of exactly this saved world, else none from here. */
export function frontDoorPicture(entry: SavedWorldEntry): string | null {
  return capturedPicture(captures, entry);
}

/** What stands behind the page and opens a world: its own picture, as its card shows it (`worldPicture`). */
const backdropPicture = (entry: SavedWorldEntry): string | null => frontDoorPicture(entry) ?? ownWorldPicture(entry);

/** Whether a world's land is still baking, which its opening names from its first frame (C3b). */
const stillBaking = (entry: SavedWorldEntry): boolean => entry.generatedGround?.tiles.some((tile) => tile.state === 'baking') ?? false;

/** The saved worlds the front door shows, for Open to hand a world's name and picture to its opening. */
let shownEntries: readonly SavedWorldEntry[] = [];

/** The front door on show, for Open to let its words and controls leave. */
let shownRoot: HTMLElement | null = null;
/** Whether this page's change into a world crosses by a crossfade: only from the live background (world-motion.css). */
let crossing = false;

/**
 * Open's words, controls and the wash under them leave before the page changes, so only the world's picture remains
 * (front-door.css), and Create's making frame with them where a world was made (world-ui-create.css). Settles when
 * they have gone.
 */
async function leaveForTheOpening(): Promise<void> {
  const root = shownRoot;
  if (!root?.isConnected) return;
  const making = document.querySelector<HTMLElement>('.wu-create-host');
  crossing = root.dataset.nativePreview === 'ready';
  root.dataset.leaving = 'true';
  if (making) making.dataset.leaving = 'true';
  // Back to this page restores it as it was left: shown again.
  window.addEventListener('pageshow', () => { delete root.dataset.leaving; if (making) delete making.dataset.leaving; crossing = false; }, { once: true });
  const leave = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--motion-leave')) || 0;
  await new Promise(resolve => window.setTimeout(resolve, leave));
}

/** Open: the workspace's world view of `entryId`. Settles as this page goes, so Open stays busy until then. */
export async function openFromFrontDoor(entryId: string): Promise<void> {
  history.replaceState({ ...history.state, [CHOSEN]: entryId }, '', location.href);
  const entry = shownEntries.find(one => one.entryId === entryId);
  await Promise.all([entry ? handOverOpening(entryId, entry.title, backdropPicture(entry), stillBaking(entry)) : null, leaveForTheOpening()]);
  location.assign(worldAddress(entryId, location.origin));
  return new Promise(resolve => window.addEventListener('pagehide', () => resolve(), { once: true }));
}

/**
 * Opens a world Create a world just made (or reopened, for Blank), or a showcase world's copy just made: through its
 * opening, with its name and `picture` (by default the one its card shows), as Open does for a saved world. Settles as
 * this page goes.
 */
export async function openMadeWorld(entry: SavedWorldEntry, picture: string | null = backdropPicture(entry)): Promise<void> {
  history.replaceState({ ...history.state, [CHOSEN]: entry.entryId }, '', location.href);
  await Promise.all([handOverOpening(entry.entryId, entry.title, picture, stillBaking(entry)), leaveForTheOpening()]);
  location.assign(worldAddress(entry.entryId, location.origin));
  return new Promise(resolve => window.addEventListener('pagehide', () => resolve(), { once: true }));
}

/**
 * Open on a showcase world's card: the workspace's own copy made as its link makes it, then opened as a made world is,
 * behind the picture its card showed (the copy keeps the same one as its own). Rejects, saying why, where none was made.
 */
async function openShowcaseCopy(credentials: Credentials, offered: ShowcaseOffer): Promise<void> {
  const entry = await makeShowcaseCopy(credentials, offered.key);
  return openMadeWorld(entry, offered.picture ?? backdropPicture(entry));
}

/** Back to the front door from a world, with that world chosen. */
export function returnToFrontDoor(entryId: string): void {
  history.replaceState({ ...history.state, [CHOSEN]: entryId }, '', frontDoorAddress(location.origin));
  location.reload();
}

/**
 * Keep the world open here in the address. A world opened within this page, as Create a world's Open
 * world opens one, takes the address Open from the front door gives it, so a reload opens it again;
 * the front door's own history entry keeps it chosen, and Back to that entry shows the front door.
 * Listens until `signal` aborts.
 */
export function keepWorldInAddress(entryId: string, signal: AbortSignal): void {
  const address = openWorldAddress(location.href, entryId);
  if (address !== null) {
    history.replaceState({ ...history.state, [CHOSEN]: entryId }, '', location.href);
    history.pushState(null, '', address);
  }
  // Back from an address this page pushed stays in this document, which still shows the world.
  window.addEventListener('popstate', () => { if (openWorldAddress(location.href, entryId) !== null) location.reload(); }, { signal });
}

/**
 * Rearrange Your worlds into the front door without replacing its actions or availability rules. `offer` is Your worlds'
 * own, which shows the showcase worlds the workspace does not hold yet after its saved worlds.
 */
export function mountFrontDoor({ root, entries, credentials, offer: offerWorlds }: {
  root: HTMLElement; entries: readonly SavedWorldEntry[]; credentials: Credentials | null; offer?: (offers: readonly WorldOffer[]) => void;
}): void {
  // A preview is one world drawn alone; it never holds a front door, or a live preview of its own.
  if (scenePreviewPage()) return;
  // A world that did not open lands here: its opening gives way to the front door.
  endOpening();
  shownEntries = entries;
  shownRoot = root;
  // A page change from here crosses by a crossfade only where Open left the live background; elsewhere it cuts.
  window.addEventListener('pageswap', (event) => {
    if (!crossing) (event as Event & { readonly viewTransition?: { skipTransition(): void } | null }).viewTransition?.skipTransition();
  });
  document.body.classList.add('ux-review');
  root.classList.add('ux-world-entry', 'ux-noveuis');
  const brand = document.createElement('p'); brand.className = 'ux-entry-brand'; brand.textContent = 'exulanica';
  root.querySelector('.your-worlds-corner')!.replaceChildren(brand);

  const hero = document.createElement('section'); hero.className = 'ux-entry-hero'; hero.setAttribute('aria-label', 'Chosen world');
  const title = document.createElement('h1'); title.className = 'ux-entry-title';
  const lede = root.querySelector('.your-worlds-lede')!;
  const actions = root.querySelector('.your-worlds-actions')!;
  offerOpenAndDetailsOnly(root);
  const createRow = root.querySelector('.your-worlds-create-row')!;
  // As on Create: Open is the one white pill, its key inside it; Create a world and Integrations stand at the top right.
  for (const [selector, name] of [['.your-worlds-open', null], ['.your-worlds-create', 'add']] as const) {
    const control = root.querySelector(selector)!;
    if (name) control.prepend(icon(name));
    else {
      control.classList.add('ux-entry-pill');
      const key = document.createElement('span'); key.className = 'ux-entry-key'; key.setAttribute('aria-hidden', 'true'); key.textContent = '↵'; control.append(key);
    }
    const shortcut = control.querySelector('kbd');
    if (shortcut) { if (selector === '.your-worlds-open') shortcut.textContent = 'Enter'; control.append(shortcut); }
  }
  root.querySelector('.your-worlds-corner')!.append(createRow);
  hero.append(title, lede);
  const strip = root.querySelector<HTMLElement>('.your-worlds-strip')!;
  root.insertBefore(hero, strip);
  const preview = createScenePreview(root);
  const arrows = document.createElement('nav'); arrows.className = 'ux-entry-arrows'; arrows.setAttribute('aria-label', 'Choose a world');
  const arrow = (label: string, glyph: IconName, step: number) => {
    const control = document.createElement('button'); control.type = 'button'; control.append(icon(glyph)); control.setAttribute('aria-label', label);
    control.onclick = () => { const cards = [...strip.querySelectorAll<HTMLElement>('.your-worlds-card')]; const current = cards.findIndex(c => c.getAttribute('aria-current') === 'true'); cards[Math.max(0, Math.min(cards.length - 1, current + step))]?.focus(); };
    arrows.append(control); return control;
  };
  const previous = arrow('Previous world', 'forward', -1), next = arrow('Next world', 'forward', 1);
  previous.classList.add('ux-entry-previous');
  root.insertBefore(arrows, strip);
  let selected: SavedWorldEntry | null = null;
  const details = document.createElement('button'); details.type = 'button'; details.className = 'entry-command ux-entry-details-open'; details.textContent = 'Details';
  details.onclick = () => { if (selected && credentials) showWorldDetails(selected, credentials); };
  actions.append(details);

  // A card without a capture shows the picture this browser keeps of its world. The live preview
  // keeps one as it draws (main.ts keeps a picture of every world it mounts), so cards fill in here.
  const refreshPictures = () => {
    for (const card of strip.querySelectorAll<HTMLElement>('.your-worlds-card')) {
      const entry = entries.find(e => e.entryId === card.dataset.entryId);
      const picture = entry ? frontDoorPicture(entry) ?? worldPicture(entry) : null;
      const frame = card.querySelector('.your-worlds-picture');
      if (!picture || !frame) continue;
      const shown = frame.querySelector('img');
      if (shown?.getAttribute('src') === picture) continue;
      const image = shown ?? document.createElement('img');
      image.alt = ''; image.decoding = 'async'; image.src = picture;
      if (!shown) frame.append(image);
    }
  };
  window.addEventListener('storage', refreshPictures);

  // The showcase worlds offered after the saved ones (showcaseOffers), once read.
  let offered: readonly ShowcaseOffer[] = [];
  /** Previous and Next stop at the strip's ends, the offered worlds' cards included once they arrive. */
  const steps = () => {
    const cards = [...strip.querySelectorAll('.your-worlds-card')], index = cards.findIndex(card => card.getAttribute('aria-current') === 'true');
    previous.disabled = index <= 0; next.disabled = index === -1 || index === cards.length - 1;
  };
  let currentId: string | undefined;
  const reflect = () => {
    const card = strip.querySelector<HTMLElement>('.your-worlds-card[aria-current="true"]');
    // A saved world's card names its entry; an offered world's, its showcase key.
    const id = card?.dataset.entryId !== undefined ? `entry:${card.dataset.entryId}` : card?.dataset.offer !== undefined ? `offer:${card.dataset.offer}` : undefined;
    if (!card || id === currentId) return;
    currentId = id;
    const entry = entries.find(e => e.entryId === card.dataset.entryId);
    const showcase = entry ? undefined : offered.find(one => one.key === card.dataset.offer);
    if (!entry && !showcase) return;
    selected = entry ?? null;
    // Details reads a saved world's own facts; a world the workspace does not hold yet has none.
    details.hidden = !entry;
    title.getAnimations().forEach(animation => animation.cancel());
    title.textContent = entry?.title ?? showcase!.title;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) title.animate([{ opacity: 0, filter: 'blur(7px)', transform: 'translateY(5px)' }, { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0px)' }], { duration: 420, easing: 'cubic-bezier(.25,.46,.45,.94)' });
    if (entry) preview.select(entry, backdropPicture(entry));
    else preview.show(showcase!.picture);
    const inset = card.offsetLeft - strip.offsetLeft;
    if (inset < strip.scrollLeft || inset + card.offsetWidth > strip.scrollLeft + strip.clientWidth) strip.scrollTo({ left: Math.max(0, inset - 4), behavior: reduce ? 'instant' : 'smooth' });
    steps();
  };
  const observer = new MutationObserver(() => reflect());
  observer.observe(strip, { attributes: true, attributeFilter: ['aria-current'], subtree: true });
  const lifetime = new MutationObserver(() => {
    if (root.isConnected) return;
    observer.disconnect(); lifetime.disconnect();
    window.removeEventListener('storage', refreshPictures); preview.dispose(); title.getAnimations().forEach(animation => animation.cancel());
  });
  lifetime.observe(root.parentElement!, { childList: true });
  const remembered = history.state?.[CHOSEN];
  // Chosen by its click, which Your worlds answers whether or not this page has the keyboard;
  // a focus alone chooses nothing while the window is in the background.
  const again = remembered ? [...strip.querySelectorAll<HTMLElement>('.your-worlds-card')].find(card => card.dataset.entryId === remembered) : undefined;
  if (again) { again.click(); again.focus({ preventScroll: true }); }
  reflect();
  // A first run with only the untouched starter lands on Create a world, as its own button opens it (aha item 3).
  if (leadsWithCreate(entries, { remembered, pictured: (entry: SavedWorldEntry) => (frontDoorPicture(entry) ?? worldPicture(entry)) !== null })) root.querySelector<HTMLElement>('.your-worlds-create')?.click();
  // A world this person is having made still runs: its card waits here (N12). The offer it reads also says whether
  // this page is the install owner's own, which alone offers Integrations beside Create a world.
  if (credentials) {
    void showBeingMade(root, credentials).then(offer => offerIntegrations(createRow as HTMLElement, offer, { credentials, entries, chosen: () => selected }));
  }
  // The installation's showcase worlds the workspace does not hold yet follow its own worlds, each Open making the
  // workspace's own copy first, as the world's link does.
  if (credentials && offerWorlds) {
    void showcaseOffers(credentials, entries).then((worlds) => {
      if (!root.isConnected || worlds.length === 0) return;
      offered = worlds;
      offerWorlds(worlds.map(one => ({ key: one.key, title: one.title, picture: one.picture, open: () => openShowcaseCopy(credentials, one) })));
      steps();
    });
  }
}

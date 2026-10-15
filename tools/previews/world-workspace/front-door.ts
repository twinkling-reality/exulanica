import './front-door.css';
import captures from 'virtual:front-door-captures';
import { createScenePreview, scenePreviewPage } from './front-door-preview.ts';
import { showWorldDetails } from './front-door-details.ts';
import { endOpening, handOverOpening } from './world-opening.ts';
import { capturedPicture, frontDoorAddress, openWorldAddress, worldAddress } from './front-door-routes.mjs';
import { worldPicture } from '/src/composition/world-pictures.ts';
import { icon, type IconName } from '/src/ui/system/icon.ts';
import type { SavedWorldEntry } from '/src/world-entry-api.ts';

// The workspace's front door: the chosen world large behind its title, a filmstrip of the saved
// worlds under it, and Open into the workspace's own world view. It rearranges the app's Your worlds
// (composition/world-entry.ts) and keeps that surface's actions, keys and availability rules.

/** The saved world last chosen here, kept in this tab's history so Back and a return find it again. */
const CHOSEN = 'frontDoorEntryId';

/** A card's picture: a private capture of exactly this saved world, else none from here. */
export function frontDoorPicture(entry: SavedWorldEntry): string | null {
  return capturedPicture(captures, entry);
}

/** The saved worlds the front door shows, for Open to hand a world's name and picture to its opening. */
let shownEntries: readonly SavedWorldEntry[] = [];

/** Open: the workspace's world view of `entryId`. Settles as this page goes, so Open stays busy until then. */
export async function openFromFrontDoor(entryId: string): Promise<void> {
  history.replaceState({ ...history.state, [CHOSEN]: entryId }, '', location.href);
  const entry = shownEntries.find(one => one.entryId === entryId);
  if (entry) await handOverOpening(entryId, entry.title, frontDoorPicture(entry) ?? worldPicture(entry));
  location.assign(worldAddress(entryId, location.origin));
  return new Promise(resolve => window.addEventListener('pagehide', () => resolve(), { once: true }));
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

/** Rearrange Your worlds into the front door without replacing its actions or availability rules. */
export function mountFrontDoor({ root, entries }: { root: HTMLElement; entries: readonly SavedWorldEntry[] }): void {
  // A preview is one world drawn alone; it never holds a front door, or a live preview of its own.
  if (scenePreviewPage()) return;
  // A world that did not open lands here: its opening gives way to the front door.
  endOpening();
  shownEntries = entries;
  document.body.classList.add('ux-review');
  root.classList.add('ux-world-entry', 'ux-noveuis');
  const brand = document.createElement('p'); brand.className = 'ux-entry-brand'; brand.textContent = 'exulanica';
  root.querySelector('.your-worlds-corner')!.replaceChildren(brand);

  const hero = document.createElement('section'); hero.className = 'ux-entry-hero'; hero.setAttribute('aria-label', 'Chosen world');
  const title = document.createElement('h1'); title.className = 'ux-entry-title';
  const lede = root.querySelector('.your-worlds-lede')!;
  const actions = root.querySelector('.your-worlds-actions')!;
  const createRow = root.querySelector('.your-worlds-create-row')!;
  for (const [selector, name] of [['.your-worlds-open', null], ['.your-worlds-create', 'add']] as const) {
    const control = root.querySelector(selector)!;
    if (name) control.prepend(icon(name));
    else {
      control.classList.add('ux-entry-orb');
      const ring = document.createElement('span'); ring.className = 'ux-orb-icon'; ring.setAttribute('aria-hidden', 'true'); ring.append(icon('forward')); control.append(ring);
    }
    const shortcut = control.querySelector('kbd');
    if (shortcut) { if (selector === '.your-worlds-open') shortcut.textContent = 'Enter'; control.append(shortcut); }
  }
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
  const playback = document.createElement('button'); playback.type = 'button';
  const reflectPlayback = () => { playback.replaceChildren(icon(preview.enabled ? 'pause' : 'play')); playback.setAttribute('aria-label', preview.enabled ? 'Pause the preview' : 'Play the preview'); };
  playback.onclick = () => { preview.toggle(); reflectPlayback(); }; reflectPlayback(); arrows.append(playback, createRow);
  root.insertBefore(arrows, strip);
  let selected: SavedWorldEntry | null = null;
  const details = document.createElement('button'); details.type = 'button'; details.className = 'entry-command ux-entry-details-open'; details.textContent = 'Details';
  details.onclick = () => { if (selected) showWorldDetails(selected); };
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

  let currentId: string | undefined;
  const reflect = () => {
    const card = strip.querySelector<HTMLElement>('.your-worlds-card[aria-current="true"]');
    if (!card || card.dataset.entryId === currentId) return;
    currentId = card.dataset.entryId;
    const entry = entries.find(e => e.entryId === currentId); if (!entry) return;
    selected = entry;
    title.getAnimations().forEach(animation => animation.cancel());
    title.textContent = entry.title;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) title.animate([{ opacity: 0, filter: 'blur(7px)', transform: 'translateY(5px)' }, { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0px)' }], { duration: 420, easing: 'cubic-bezier(.25,.46,.45,.94)' });
    preview.select(entry, frontDoorPicture(entry) ?? card.querySelector('img')?.getAttribute('src') ?? null);
    const inset = card.offsetLeft - strip.offsetLeft;
    if (inset < strip.scrollLeft || inset + card.offsetWidth > strip.scrollLeft + strip.clientWidth) strip.scrollTo({ left: Math.max(0, inset - 4), behavior: reduce ? 'instant' : 'smooth' });
    const cards = [...strip.querySelectorAll('.your-worlds-card')], index = cards.indexOf(card);
    previous.disabled = index === 0; next.disabled = index === cards.length - 1;
  };
  const observer = new MutationObserver(() => reflect());
  observer.observe(strip, { attributes: true, attributeFilter: ['aria-current'], subtree: true });
  const preference = matchMedia('(prefers-reduced-motion: reduce)'); preference.addEventListener('change', reflectPlayback);
  const lifetime = new MutationObserver(() => {
    if (root.isConnected) return;
    observer.disconnect(); lifetime.disconnect(); preference.removeEventListener('change', reflectPlayback);
    window.removeEventListener('storage', refreshPictures); preview.dispose(); title.getAnimations().forEach(animation => animation.cancel());
  });
  lifetime.observe(root.parentElement!, { childList: true });
  const remembered = history.state?.[CHOSEN];
  // Chosen by its click, which Your worlds answers whether or not this page has the keyboard;
  // a focus alone chooses nothing while the window is in the background.
  const again = remembered ? [...strip.querySelectorAll<HTMLElement>('.your-worlds-card')].find(card => card.dataset.entryId === remembered) : undefined;
  if (again) { again.click(); again.focus({ preventScroll: true }); }
  reflect();
}

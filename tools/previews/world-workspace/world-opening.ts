// Opening a world (DESIGN's frame 01, specification 8.1): from the first script of a world's page,
// the world's picture full screen, "Opening", its name, a line that moves only when the loader
// reports a real stage (seams.mjs dispatches the reports), the stage's words, and one tip. It ends
// when the world view mounts (contextual-world.ts) or the front door shows instead (front-door.ts).
import { BAKING_STAGE, OPENING_EVENT, OPENING_HANDOFF_KEY, OPENING_STAGES, STEP_EASE, easedShare, openingProgress, readHandoff } from './opening-steps.mjs';
import { isScenePreview } from './front-door-routes.mjs';
import { OPENING_WORDS } from './world-words.mjs';
import { breath, keyWord, mountUiScale, promptRow, workingWords } from './world-ui.ts';

/** The key this browser keeps a world's picture under (world-pictures.ts). */
const KEPT_PICTURE = 'exulanica.world-picture.v1.';

let shown: { readonly root: HTMLElement; readonly lifetime: AbortController } | null = null;

/** Clears the mark that paints a world's address on the opening's ground from its first frame (index.html). */
function clearFirstFrame(): void {
  delete document.documentElement.dataset.opening;
  document.documentElement.style.removeProperty('background-image');
}

const div = (className: string, text = ''): HTMLDivElement => {
  const made = document.createElement('div'); made.className = className;
  if (text) made.textContent = text;
  return made;
};

function keptPicture(entryId: string): string | null {
  try {
    const value = localStorage.getItem(KEPT_PICTURE + entryId);
    return value !== null && value.startsWith('data:image/') ? value : null;
  } catch { return null; }
}

/**
 * Shows the opening on a world's address; does nothing anywhere else. A scene preview (the front
 * door's live background) draws a world too, but never mounts the world view that ends the opening,
 * so it shows none.
 */
export function mountOpening(): void {
  const entryId = new URLSearchParams(location.search).get('entry');
  if (!entryId || shown !== null || isScenePreview(new URL(location.href))) return;
  let handoff = null;
  try { handoff = readHandoff(sessionStorage.getItem(OPENING_HANDOFF_KEY), entryId); } catch { /* No handoff: a reload. */ }
  const lifetime = new AbortController();
  const root = div('wu-root wu-opening');
  root.setAttribute('role', 'status');
  root.setAttribute('aria-live', 'polite');
  const picture = handoff?.picture ?? keptPicture(entryId);
  // The picture shows at once, as the front door handed it over, and drifts from its first frame (world-motion.css).
  const world = div('wu-opening-world wu-drift');
  if (picture) world.style.backgroundImage = `url(${JSON.stringify(picture)})`;
  const words = div('wu-opening-words');
  const name = document.createElement('h1'); name.className = 'wu-opening-name'; name.textContent = handoff?.title ?? '';
  const line = div('wu-opening-line'), fill = div('wu-opening-fill'), head = div('wu-opening-head');
  head.append(breath(), div('wu-opening-end'));
  line.append(fill, head);
  const step = div('wu-opening-step');
  const over = div('wu-opening-over', OPENING_WORDS.opening);
  words.append(over, name, line, step);
  const tip = div('wu-opening-tip');
  tip.append(div('wu-opening-over', OPENING_WORDS.tip), promptRow(OPENING_WORDS.tipKeys.map((one: { keys: string[]; word: string }) => keyWord(one))));
  // "Opening", the name, the line, the stage words and the tip arrive in reading order; the name as a title.
  [over, name, line, step, tip].forEach((part, order) => {
    part.classList.add(part === name ? 'wu-arrive-title' : 'wu-arrive-words');
    part.style.setProperty('--motion-order', String(order));
  });
  root.append(world, div('wu-opening-fade'), words, tip);
  document.body.append(root);
  // The page's first frame was the opening's ground (index.html); the opening holds the screen from here.
  clearFirstFrame();
  mountUiScale(root, lifetime.signal);
  const reports: string[] = [];
  // A town still baking opens with its bake (C3): from the first frame where the front door's handoff
  // says so (C3b), else at its first share; the share never moves back, and it ends with the bake's
  // report, or with any later stage's where the town read baked before its bake was waited for.
  let stages: readonly { readonly report: string; readonly words: string }[] = handoff?.baking ? [BAKING_STAGE, ...OPENING_STAGES] : OPENING_STAGES, share = 0;
  // Within a running step of the bake the line eases from where it stands toward that step's end, as the served steps
  // state it, never past it nor back (C3c): `served` is the bake's served share, `reach` where its running steps end.
  let served = 0, reach = 0, from = 0, since = 0, ticker = 0;
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stop = (): void => { clearInterval(ticker); ticker = 0; };
  lifetime.signal.addEventListener('abort', stop);
  const ease = (): void => {
    if (still || ticker !== 0 || !(reach > share)) return;
    ticker = window.setInterval(() => {
      share = Math.max(share, easedShare(from, reach, performance.now() - since));
      draw(true);
    }, STEP_EASE.tickMs);
  };
  // The stage words on show; a report's new words take their place as they leave (the catalog's words swap).
  let said: string | null = null;
  const say = (words: string): void => {
    const first = said === null;
    said = words;
    for (const old of step.querySelectorAll<HTMLElement>(':scope > :not([data-leaving])')) {
      // Words newer ones replace before they have arrived were never seen whole: they go at once, never shown to leave.
      if (Number.parseFloat(getComputedStyle(old).opacity) < 1) { old.remove(); continue; }
      old.dataset.leaving = 'true'; old.setAttribute('aria-hidden', 'true');
      old.addEventListener('animationend', (event) => { if (event.target === old) old.remove(); });
      // Where animation is off or never ends, the old words go after their leave all the same.
      window.setTimeout(() => old.remove(), 1000);
    }
    const shown = div('');
    if (words) shown.append(workingWords(words));
    if (!first) {
      // They arrive once the old words have gone (world-ui.css), never together with them.
      shown.dataset.swap = 'true';
      shown.className = 'wu-arrive-words';
      // The head's breath starts again with the new words' shimmer.
      const glow = breath(); glow.dataset.swap = 'true';
      head.firstElementChild?.replaceWith(glow);
    }
    step.append(shown);
  };
  // `tick` is an eased step within a running bake (C3c), whose ticks join without stepping; any other change glides.
  const draw = (tick = false): void => {
    const now = openingProgress(reports, stages, share);
    if (tick) line.dataset.moving = 'tick'; else delete line.dataset.moving;
    const fraction = now.fraction.toFixed(4);
    fill.style.transform = `scaleX(${fraction})`;
    head.style.transform = `translateX(${(now.fraction * 100).toFixed(2)}%)`;
    if ((now.words ?? '') !== said) say(now.words ?? '');
  };
  window.addEventListener(OPENING_EVENT, (event) => {
    const detail = (event as CustomEvent<{ readonly report?: string; readonly title?: string; readonly baking?: number; readonly reach?: number }>).detail;
    if (!detail) return;
    if (typeof detail.baking === 'number') {
      if (reports.includes(BAKING_STAGE.report)) return;
      if (stages === OPENING_STAGES) stages = [BAKING_STAGE, ...OPENING_STAGES];
      const now = Math.max(served, detail.baking);
      const end = Math.max(reach, now, typeof detail.reach === 'number' && Number.isFinite(detail.reach) ? Math.min(1, detail.reach) : 0);
      // A step ended, or a step's end is newly stated: the line eases on from where it stands toward the new end.
      if (now !== served || end !== reach) { served = now; reach = end; from = Math.max(served, share); since = performance.now(); }
      share = Math.max(share, served);
      ease();
    } else if (typeof detail.report === 'string') {
      if (stages !== OPENING_STAGES && !reports.includes(BAKING_STAGE.report)) reports.push(BAKING_STAGE.report);
      if (detail.report !== BAKING_STAGE.report) reports.push(detail.report);
      share = 0; served = 0; reach = 0;
      stop();
    } else return;
    if (!name.textContent && typeof detail.title === 'string') name.textContent = detail.title;
    draw();
  }, { signal: lifetime.signal });
  draw();
  shown = { root, lifetime };
}

/** Ends the opening: it fades over the world (or the front door) and goes. Says whether one was showing. */
export function endOpening(): boolean {
  // Whatever shows next shows on its own ground, the opening's first frame given up even where it never mounted.
  clearFirstFrame();
  if (shown === null) return false;
  const { root, lifetime } = shown;
  shown = null;
  lifetime.abort();
  try { sessionStorage.removeItem(OPENING_HANDOFF_KEY); } catch { /* Nothing kept. */ }
  root.dataset.leaving = 'true';
  // While it fades, its picture returns to its first framing, so it lands on the live world without a double image.
  const picture = root.querySelector<HTMLElement>('.wu-opening-world');
  const framing = picture ? getComputedStyle(picture).transform : '';
  if (picture && framing && framing !== 'none' && typeof picture.animate === 'function') {
    const tokens = getComputedStyle(root);
    picture.animate([{ transform: framing }, { transform: 'none' }], {
      delay: Number.parseFloat(tokens.getPropertyValue('--motion-leave')) || 0,
      duration: Number.parseFloat(tokens.getPropertyValue('--motion-travel')) || 0,
      easing: tokens.getPropertyValue('--ease-glide').trim() || 'ease',
      fill: 'both',
    });
  }
  // Its words leave first; it goes when its own fade ends, not theirs.
  root.addEventListener('animationend', (event) => { if (event.target === root) root.remove(); });
  // Where animation is off, it goes at once.
  if (getComputedStyle(root).animationName === 'none') root.remove();
  return true;
}

/**
 * The front door's Open hands the opening the world's name, the picture its card shows and whether its land is still
 * baking, so a town still baking opens on its bake from the first frame (C3b).
 */
export async function handOverOpening(entryId: string, title: string, shownPicture: string | null, baking = false): Promise<void> {
  let picture: string | null = null;
  if (shownPicture?.startsWith('data:image/')) picture = shownPicture;
  else if (shownPicture?.startsWith('blob:')) {
    // A picture read from the server lives only in this page; carried over as its bytes.
    try {
      const bytes = await (await fetch(shownPicture)).blob();
      picture = await new Promise<string | null>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : null);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(bytes);
      });
    } catch { picture = null; }
  }
  try { sessionStorage.setItem(OPENING_HANDOFF_KEY, JSON.stringify({ entryId, title, picture, baking })); } catch { /* The opening shows without them. */ }
}

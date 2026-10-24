// Opening a world (DESIGN's frame 01, specification 8.1): from the first script of a world's page,
// the world's picture full screen, "Opening", its name, a line that moves only when the loader
// reports a real stage (seams.mjs dispatches the reports), the stage's words, and one tip. It ends
// when the world view mounts (contextual-world.ts) or the front door shows instead (front-door.ts).
import { BAKING_STAGE, OPENING_EVENT, OPENING_HANDOFF_KEY, OPENING_STAGES, openingProgress, readHandoff } from './opening-steps.mjs';
import { isScenePreview } from './front-door-routes.mjs';
import { OPENING_WORDS } from './world-words.mjs';
import { keyWord, mountUiScale, promptRow } from './world-ui.ts';

/** The key this browser keeps a world's picture under (world-pictures.ts). */
const KEPT_PICTURE = 'exulanica.world-picture.v1.';

let shown: { readonly root: HTMLElement; readonly lifetime: AbortController } | null = null;

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
  const world = div('wu-opening-world');
  if (picture) world.style.backgroundImage = `url(${JSON.stringify(picture)})`;
  const words = div('wu-opening-words');
  const name = document.createElement('h1'); name.className = 'wu-opening-name'; name.textContent = handoff?.title ?? '';
  const line = div('wu-opening-line'), fill = div('wu-opening-fill'), end = div('wu-opening-end');
  line.append(fill, end);
  const step = div('wu-opening-step');
  words.append(div('wu-opening-over', OPENING_WORDS.opening), name, line, step);
  const tip = div('wu-opening-tip');
  tip.append(div('wu-opening-over', OPENING_WORDS.tip), promptRow(OPENING_WORDS.tipKeys.map((one: { keys: string[]; word: string }) => keyWord(one))));
  root.append(world, div('wu-opening-fade'), words, tip);
  document.body.append(root);
  mountUiScale(root, lifetime.signal);
  const reports: string[] = [];
  // A town still baking opens with its bake (C3): the stage is added at its first share, the share
  // never moves back, and it ends with the bake's report.
  let stages: readonly { readonly report: string; readonly words: string }[] = OPENING_STAGES, share = 0;
  const draw = (): void => {
    const now = openingProgress(reports, stages, share);
    fill.style.width = `${(now.fraction * 100).toFixed(1)}%`;
    end.style.left = `${(now.fraction * 100).toFixed(1)}%`;
    step.textContent = now.words ?? '';
  };
  window.addEventListener(OPENING_EVENT, (event) => {
    const detail = (event as CustomEvent<{ readonly report?: string; readonly title?: string; readonly baking?: number }>).detail;
    if (!detail) return;
    if (typeof detail.baking === 'number') {
      if (reports.includes(BAKING_STAGE.report)) return;
      if (stages === OPENING_STAGES) stages = [BAKING_STAGE, ...OPENING_STAGES];
      share = Math.max(share, detail.baking);
    } else if (typeof detail.report === 'string') {
      reports.push(detail.report);
      if (detail.report === BAKING_STAGE.report) share = 0;
    } else return;
    if (!name.textContent && typeof detail.title === 'string') name.textContent = detail.title;
    draw();
  }, { signal: lifetime.signal });
  draw();
  shown = { root, lifetime };
}

/** Ends the opening: it fades over the world (or the front door) and goes. Says whether one was showing. */
export function endOpening(): boolean {
  if (shown === null) return false;
  const { root, lifetime } = shown;
  shown = null;
  lifetime.abort();
  try { sessionStorage.removeItem(OPENING_HANDOFF_KEY); } catch { /* Nothing kept. */ }
  root.dataset.leaving = 'true';
  root.addEventListener('animationend', () => root.remove(), { once: true });
  // Where animation is off, it goes at once.
  if (getComputedStyle(root).animationName === 'none') root.remove();
  return true;
}

/** The front door's Open hands the opening the world's name and the picture its card shows. */
export async function handOverOpening(entryId: string, title: string, shownPicture: string | null): Promise<void> {
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
  try { sessionStorage.setItem(OPENING_HANDOFF_KEY, JSON.stringify({ entryId, title, picture })); } catch { /* The opening shows without them. */ }
}

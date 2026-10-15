// The in-world parts only the character moments use (DESIGN's ruling L7): the Running strip (5.9),
// and the pop over a character (5.10). Built from world-ui.ts's tokens and parts; their look lives
// in world-ui-character.css.
import './world-ui-character.css';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

export interface RunStripWords {
  readonly running: string;
  readonly timeLeft: string;
  readonly left: string;
  readonly spent: string;
  readonly of: string;
  readonly stop: string;
}

export interface RunStrip {
  readonly root: HTMLElement;
  set(words: RunStripWords): void;
  remove(): void;
}

/** The Running strip at the top centre while a run is open (5.9). Stop is the caller's. */
export function runStrip({ onStop }: { readonly onStop: () => void }): RunStrip {
  const root = element('div', 'wu-strip wu-glass');
  root.setAttribute('role', 'status');
  const live = element('span', 'wu-strip-dot'); live.setAttribute('aria-hidden', 'true');
  const running = element('span');
  const timeLeft = element('span', 'wu-strip-figure'), left = element('span', 'wu-faint');
  const spent = element('span', 'wu-strip-figure'), of = element('span', 'wu-faint');
  const stop = element('button', 'wu-strip-stop'); stop.type = 'button';
  const square = element('i'); square.setAttribute('aria-hidden', 'true');
  const stopWords = element('span');
  stop.append(square, stopWords);
  stop.addEventListener('click', () => onStop());
  const part = (...items: HTMLElement[]): HTMLElement => { const made = element('div', 'wu-strip-part'); made.append(...items); return made; };
  root.append(part(live, running), part(timeLeft, left), part(spent, of), part(stop));
  const put = (target: HTMLElement, words: string): void => { if (target.textContent !== words) target.textContent = words; };
  return {
    root,
    set(words) {
      put(running, words.running); put(timeLeft, words.timeLeft); put(left, words.left);
      put(spent, words.spent); put(of, words.of); put(stopWords, words.stop);
    },
    remove() { root.remove(); },
  };
}

export interface Pop {
  readonly root: HTMLElement;
  /** Shows what was said (in quotes, italic) or chosen; a newer one replaces it. */
  show(words: string, { said }: { readonly said: boolean }): void;
  place(x: number, y: number): void;
  readonly showing: boolean;
  hide(): void;
}

/** Words over a character whose model acted, while a run is open (5.10). */
export function pop({ scale = () => 1, hold = 3600, out = 600 }: { readonly scale?: () => number; readonly hold?: number; readonly out?: number } = {}): Pop {
  const root = element('div', 'wu-anchored wu-pop');
  root.hidden = true;
  let timer = 0, leaving = 0, showing = false;
  const hide = (): void => { clearTimeout(timer); clearTimeout(leaving); showing = false; root.hidden = true; delete root.dataset.leaving; };
  return {
    root,
    get showing() { return showing; },
    show(words, { said }) {
      hide();
      root.replaceChildren(element('span', said ? 'wu-pop-said' : 'wu-pop-chose', words));
      root.hidden = false; showing = true;
      root.getAnimations().forEach(animation => animation.cancel());
      root.classList.remove('wu-pop-in'); void root.offsetWidth; root.classList.add('wu-pop-in');
      timer = window.setTimeout(() => { root.dataset.leaving = 'true'; leaving = window.setTimeout(hide, out); }, hold);
    },
    place(x, y) {
      const s = scale();
      const at = { x: x - root.offsetWidth / 2, y: y - root.offsetHeight - 12 * s };
      const transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
      if (root.style.transform !== transform) root.style.transform = transform;
    },
    hide,
  };
}

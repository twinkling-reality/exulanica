// The in-world parts only the character moments use (DESIGN's ruling L7): the Running strip (5.9).
// Built from world-ui.ts's tokens and parts; their look lives in world-ui-character.css. The lines over
// characters who talk are world-ui-talk.ts's.
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

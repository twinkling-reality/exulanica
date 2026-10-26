// A chosen character's group in the world (DESIGN's J30, the r05 picture): one soft shade beside them,
// joined to their head by a thin leader, holding their name, what they are doing, the last line they said,
// the keys that work for them now and who decides for them. It replaces the side card of frame 05 and its
// model chip. character-group.mjs decides what it says and where it stands; character-presence.ts shows it
// and places it each frame, so it follows the person and flips side near the screen's edge.
import './character-group.css';
import { chip, glyphRows, setChipLive, shade } from './world-ui.ts';
import { groupHeld, groupPlace } from './character-group.mjs';
import { CHARACTER_WORDS } from './character-words.mjs';

const SVG = 'http://www.w3.org/2000/svg';

/** One key row: what it does, its key, its word and its aria-keyshortcuts value. */
export interface GroupRow { readonly action: string; readonly key: string; readonly word: string; readonly shortcut: string; readonly disabled?: boolean }

/** What the group says (character-group.mjs groupContent). */
export interface GroupContent {
  readonly name: string;
  readonly doing: string | null;
  /** The last line said, in curly quotes, and under it to whom and when; null when nothing was said yet. */
  readonly said: { readonly line: string; readonly under: string | null } | null;
  /** The Run question's line of whose models decide (r08); null in the group's own state. */
  readonly note: string | null;
  readonly rows: readonly GroupRow[];
  /** Who decides for them now, or the run's model and cap; null while their record is read. */
  readonly print: string | null;
  /** Under the print, fainter: when a run stops (r08); null otherwise. */
  readonly after: string | null;
  /** The print is a refusal: in the refused ink, Run dimmed. */
  readonly refused: boolean;
  /** Under the print, an outside AI agent's own words about itself as parts, its declared ones marked (AG1d 2). */
  readonly declared?: readonly { readonly words: string; readonly declared: boolean }[] | null;
}

/** Where the person stands on screen this frame: the top of their head, their box's sides, and a side to prefer (the talking scene's). */
export interface GroupAnchor { readonly head: { readonly x: number; readonly y: number }; readonly bounds: { readonly left: number; readonly right: number }; readonly prefer?: 'right' | 'left' | null }

export interface CharacterGroup {
  readonly root: HTMLElement;
  /** What the group says; null puts it away. */
  set(content: GroupContent | null): void;
  /** Places the group and its leader beside the person; null hides them (the person out of view). */
  place(at: GroupAnchor | null): void;
  /**
   * Holds the group where it last stood, its leader from `edge`, the point at the view's edge its person left by (P7);
   * hidden where it has not stood yet.
   */
  hold(edge: { readonly x: number; readonly y: number }): void;
  remove(): void;
}

/** The rows' figures (TOKENS-FOR-WORLD-UI, a character's group): 32px keys at both sizes, words 19 (18 at 1440). */
const ROW_SIZES = Object.freeze({ glyph: 'max(32px, calc(32 * var(--u)))', rowGap: 'max(16px, calc(16 * var(--u)))', colGap: 'max(16px, calc(16 * var(--u)))', word: 'max(18px, calc(19 * var(--u)))', nudge: 0 });

function text<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, words: string): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  made.className = className;
  made.textContent = words;
  return made;
}

export function characterGroup({ scale, onAction }: { readonly scale: () => number; readonly onAction: (action: string) => void }): CharacterGroup {
  const root = document.createElement('div');
  root.className = 'cg-root';
  root.hidden = true;
  const leader = document.createElementNS(SVG, 'svg');
  leader.setAttribute('class', 'cg-leader');
  leader.setAttribute('aria-hidden', 'true');
  leader.innerHTML = '<path/><circle r="2.6"/>';
  const [line, dot] = [leader.querySelector('path')!, leader.querySelector('circle')!];
  const group = shade();
  group.classList.add('cg-group');
  group.setAttribute('role', 'group');
  root.append(leader, group);
  let shown: string | null = null, placed = '';
  // Where it last stood, for holding it there.
  let last: { readonly x: number; readonly y: number } | null = null;
  const draw = (at: { readonly x: number; readonly y: number; readonly side: string; readonly leader: { readonly from: { x: number; y: number }; readonly elbow: { x: number; y: number }; readonly to: { x: number; y: number } } }) => {
    const transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
    const { from, elbow, to } = at.leader;
    const path = `M${from.x.toFixed(1)} ${from.y.toFixed(1)}L${elbow.x.toFixed(1)} ${elbow.y.toFixed(1)}L${to.x.toFixed(1)} ${to.y.toFixed(1)}`;
    // Each frame moves it only when it moved: the person walks, the camera turns.
    if (transform + path === placed) return;
    placed = transform + path;
    group.style.transform = transform;
    line.setAttribute('d', path);
    dot.setAttribute('cx', from.x.toFixed(1)); dot.setAttribute('cy', from.y.toFixed(1));
    root.dataset.side = at.side;
  };

  return {
    root,
    set(content) {
      if (!content) { shown = null; last = null; root.hidden = true; group.replaceChildren(); return; }
      const key = JSON.stringify(content);
      if (key === shown) return;
      shown = key;
      const parts: HTMLElement[] = [text('h2', 'cg-name', content.name)];
      if (content.doing) parts.push(text('p', 'cg-doing', content.doing));
      if (content.said) {
        parts.push(text('p', 'cg-said', content.said.line));
        if (content.said.under) parts.push(text('p', 'cg-to', content.said.under));
      }
      if (content.note) parts.push(text('p', 'cg-note', content.note));
      if (content.rows.length) {
        const rows = glyphRows(content.rows.map(row => ({ key: row.key, word: row.word, shortcut: row.shortcut, disabled: row.disabled === true, onPress: () => onAction(row.action) })), ROW_SIZES);
        rows.classList.add('cg-rows');
        parts.push(rows);
      }
      if (content.print) {
        const print = text('p', 'cg-print', content.print);
        if (content.refused) { print.classList.add('cg-refused'); print.setAttribute('role', 'status'); }
        if (content.after) { print.append(document.createElement('br'), text('span', 'cg-after', content.after)); }
        parts.push(print);
      }
      if (content.declared) {
        // Its own words exactly as sent, as text: ours in the faint ink, its declared parts in white.
        const declared = document.createElement('p');
        declared.className = 'cg-declared';
        declared.append(...content.declared.map(part => (part.declared ? text('span', 'cg-declared-own', part.words) : document.createTextNode(part.words))));
        parts.push(declared);
      }
      group.dataset.refused = String(content.refused);
      group.replaceChildren(...parts);
      group.setAttribute('aria-label', content.name);
      placed = '';
    },
    place(at) {
      if (!at || shown === null) { root.hidden = true; return; }
      root.hidden = false;
      const at2 = groupPlace({ head: at.head, bounds: at.bounds, size: { width: group.offsetWidth, height: group.offsetHeight },
        viewport: { width: innerWidth, height: innerHeight }, scale: scale(), prefer: at.prefer ?? null });
      last = { x: at2.x, y: at2.y };
      draw(at2);
    },
    hold(edge) {
      if (last === null || shown === null) { root.hidden = true; return; }
      root.hidden = false;
      draw(groupHeld({ last, edge, size: { width: group.offsetWidth, height: group.offsetHeight }, viewport: { width: innerWidth, height: innerHeight }, scale: scale() }));
    },
    remove() { root.remove(); },
  };
}

/**
 * What the label over a looked-at character says (r04): their name (or kind), what they are doing and, where a model
 * decides for them, its name (`model`), with the live dot while a run asks it (`live`).
 */
export interface LookWords {
  readonly name: string; readonly doing: string | null; readonly model?: string | null; readonly live?: boolean;
  /** The chip in the quiet fill (an outside AI agent's, AG1d 1). */
  readonly quiet?: boolean;
}

export interface LookLabel {
  readonly root: HTMLElement;
  /** The words, and whether E chooses this character from here; null hides the label. */
  set(words: LookWords | null, inspectable: boolean): void;
  /** Centres the label over the top of the head on screen, kept inside the view's sides. */
  place(head: { readonly x: number; readonly y: number }): void;
  /** The label's box on screen while it shows (lines over others keep clear of it), else null. */
  box(): { readonly x: number; readonly y: number; readonly width: number; readonly height: number } | null;
  remove(): void;
}

/** The key row's figures (r04): a 24 px key, its letter in Mono 11 as the pills' small caps, a 15 px word. */
const LOOK_ROW_SIZES = Object.freeze({ glyph: 24, rowGap: 8, colGap: 10, word: 15, nudge: 0 });
/** How far over the head the label stands, and the inset from the view's sides, in reference pixels. */
const LOOK_LAYOUT = Object.freeze({ over: 16, inset: 32 });

/**
 * What keeps the world's marks under the panels drawn over them (V10): the looked-at tag and the aim mark are not drawn
 * in a frame where their box crosses a panel drawn now (`panels`, each by its element), and come back as soon as it
 * moves off them or closes.
 */
export function panelCover(panels: () => readonly (Element | null | undefined)[]) {
  const crosses = (box: { readonly left: number; readonly top: number; readonly right: number; readonly bottom: number }): boolean =>
    box.right > box.left && box.bottom > box.top && panels().some((part) => {
      // A panel put away has an empty box, which nothing crosses.
      const panel = part?.getBoundingClientRect();
      return panel !== undefined && box.left < panel.right && box.right > panel.left && box.top < panel.bottom && box.bottom > panel.top;
    });
  return {
    crosses,
    /** Leaves the tag out of this frame where it crosses a panel. */
    clear(label: Pick<LookLabel, 'box' | 'set'>): void {
      const box = label.box();
      if (box && crosses({ left: box.x, top: box.y, right: box.x + box.width, bottom: box.y + box.height })) label.set(null, false);
    },
    /** Hides `element` by its visibility, so its own box is still measured, in a frame where it crosses a panel. */
    cover(element: HTMLElement): void {
      element.style.visibility = !element.hidden && crosses(element.getBoundingClientRect()) ? 'hidden' : '';
    },
  };
}

/**
 * The label over a looked-at character (r04, R-RUN-BUILD-SHEET section 4): the name label grows into one soft label,
 * centred 16 px over the head, on the speech label's shade (.wu-speech, world-ui-talk.css): the name, what they are doing,
 * the model's chip where a model decides for them (DESIGN's aha 19), so the world says who has one before a run and during
 * it, and "[E] Inspect" where E chooses them.
 */
export function lookLabel({ scale, onInspect }: { readonly scale: () => number; readonly onInspect: () => void }): LookLabel {
  const root = shade();
  root.classList.add('wu-speech', 'cg-look');
  root.hidden = true;
  const name = text('p', 'cg-look-name', ''), doing = text('p', 'cg-look-doing', '');
  const model = chip('');
  model.classList.add('cg-look-chip');
  const rows = glyphRows([{ key: 'E', word: CHARACTER_WORDS.inspect, shortcut: 'E', onPress: onInspect }], LOOK_ROW_SIZES);
  rows.classList.add('cg-look-rows');
  root.append(name, doing, model, rows);
  let shown = '', placed = '';
  return {
    root,
    set(words, inspectable) {
      if (!words) { root.hidden = true; return; }
      root.hidden = false;
      const key = JSON.stringify([words, inspectable]);
      if (key === shown) return;
      shown = key;
      name.textContent = words.name;
      doing.textContent = words.doing ?? '';
      doing.hidden = !words.doing;
      model.querySelector('.wu-chip-words')!.textContent = words.model ?? '';
      model.hidden = !words.model;
      model.classList.toggle('wu-quiet', Boolean(words.quiet));
      setChipLive(model, Boolean(words.model && words.live));
      rows.hidden = !inspectable;
      rows.querySelector('button')?.setAttribute('aria-label', `${CHARACTER_WORDS.inspect} ${words.name}`);
    },
    place(head) {
      if (root.hidden) return;
      const s = scale(), half = root.offsetWidth / 2, inset = LOOK_LAYOUT.inset * s;
      const x = Math.max(inset + half, Math.min(innerWidth - inset - half, head.x)), y = head.y - LOOK_LAYOUT.over * s;
      const transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-100%)`;
      if (transform === placed) return;
      placed = transform;
      root.style.transform = transform;
    },
    box() {
      if (root.hidden) return null;
      const box = root.getBoundingClientRect();
      return box.height ? { x: box.left, y: box.top, width: box.width, height: box.height } : null;
    },
    remove() { root.remove(); },
  };
}

// The model gallery's page (G2): M on a chosen person, and the day page's Model, open it as a light page over the world
// faded behind, as History and the decision page are. The rows and every word are model-gallery.mjs's; this draws them,
// moves the focus, and chooses through the host's own write (recordEntityModel), the one the in-world list used. At any
// window on the light pages' frame (world-page-frame.ts): the list and the card's words scroll in their own columns, the
// row in focus kept in view.
import { keepInView, scrollingColumn } from './world-page-frame.ts';
import './model-gallery.css';
import { element, ground, keyButton, orb } from './world-ui-record.ts';
import { GALLERY_WORDS, firstFocus, galleryDetail, galleryPage, moveFocus, rowForKey } from './model-gallery.mjs';
import { CHARACTER_WORDS } from './character-words.mjs';
import { page, type Page } from './world-ui.ts';
import type { SocietyModels } from '/src/society-models-api.ts';

type Json = Record<string, any>;

export interface GalleryHooks {
  /** Where the page is drawn. */
  readonly root: HTMLElement;
  /** The models read now, or null before it is read. */
  read(): SocietyModels | null;
  /** The still of the world behind, or null for the plain ground. */
  still(): string | null;
  /** The row's person's round portrait, as the day page shows it, or null for the first letter of their name. */
  portrait(row: Json): string | null;
  /** Whether the page is a guest's, whose models a host pays for. */
  fromServer(): boolean;
  /** Who it is for, what they are doing and their model now (null: their routine). */
  about(row: Json): { readonly who: Json; readonly doing: string | null; readonly current: Json | null };
  /** Records `selected` (null: the routine) for the row's person under `key`, answering the verified models read. */
  write(row: Json, selected: Json | null, key: string): Promise<SocietyModels>;
  /** A refused write in words. */
  refusal(error: Json, row: Json): string;
  /** A model was chosen and the read verified. */
  chosen(verified: SocietyModels): void;
  /** The page closed: back to where M was pressed. */
  closed(): void;
}

export interface Gallery {
  open(row: Json): void;
  close(): void;
  /** A key while the page is open; true when the page took it. */
  key(event: KeyboardEvent): boolean;
  readonly isOpen: boolean;
}

/** A row's sub-line, each of its parts whole on its line ("decided 26 times here" never breaks inside itself). */
function subLine(sub: string): HTMLElement {
  const line = element('div', 'wu-g2-sub');
  sub.split(' · ').forEach((part, at) => {
    if (at) line.append(' · ');
    line.append(element('span', 'wu-g2-part', part));
  });
  return line;
}

export function mountModelGallery(hooks: GalleryHooks): Gallery {
  let made: Page | null = null;
  let row: Json | null = null;
  let focus = 0, busy = false, refusal: string | null = null, key = crypto.randomUUID();
  /** The row in focus when last drawn, -1 before the first draw; and what reads the scrolling parts again as they resize. */
  let drawnFocus = -1, sizes: ResizeObserver | null = null;

  function view() {
    const read = hooks.read(), about = hooks.about(row as Json), fromServer = hooks.fromServer();
    const shown = galleryPage({ read, who: about.who, doing: about.doing, current: about.current, fromServer });
    return { read, about, fromServer, shown };
  }

  /** Draws the page; with `reveal` (a key or a press moved the focus, even onto the row it was on) the row in focus is brought into view. */
  function draw(reveal = false) {
    if (!made || !row) return;
    const { read, about, shown } = view();
    focus = Math.min(focus, shown.rows.length - 1);
    const content = made.content;
    // What was scrolled stays scrolled across a draw: the list always, the card's words while it shows the same model.
    const was = { list: content.querySelector('.wu-g2-list')?.scrollTop ?? 0, words: content.querySelector('.wu-g2-scroll')?.scrollTop ?? 0 };
    const moved = focus !== drawnFocus;
    drawnFocus = focus;
    sizes?.disconnect();
    content.replaceChildren();
    const head = element('div', 'wu-g2-head wu-frame-head');
    const over = element('div', 'wu-g2-over');
    // The person's round portrait at the start of the over line, sized by the stylesheet's steps.
    const face = orb(String(row.scene?.id ?? ''), 0, hooks.portrait(row), String(about.who?.title ?? ''));
    face.style.width = face.style.height = '';
    face.classList.add('wu-frame-face');
    over.append(face, element('span', '', shown.over));
    head.append(over, element('h1', 'wu-g2-title wu-frame-title', shown.title));
    head.querySelector('h1')!.tabIndex = -1;
    const list = element('div', 'wu-g2-list');
    for (const group of shown.groups) {
      const block = element('div', 'wu-g2-group');
      block.append(element('div', 'wu-g2-label', group.label));
      for (const one of group.rows) {
        const index = shown.rows.indexOf(one);
        const button = element('button', 'wu-g2-row');
        button.type = 'button';
        if (index === focus) button.setAttribute('aria-current', 'true');
        const words = element('div', 'wu-g2-words');
        const name = element('div', 'wu-g2-name', one.name);
        if (one.current) name.append(element('span', 'wu-g2-current', CHARACTER_WORDS.current));
        words.append(name);
        if (one.sub) words.append(subLine(one.sub));
        button.append(element('span', 'wu-g2-num', one.key), words, element('span', 'wu-g2-cost', one.cost));
        button.addEventListener('click', () => { focus = index; refusal = null; draw(true); });
        block.append(button);
      }
      for (const faint of group.faint) {
        const line = element('div', 'wu-g2-row faint');
        const words = element('div', 'wu-g2-words');
        const name = element('div', 'wu-g2-name', faint.name);
        if (faint.current) name.append(element('span', 'wu-g2-current', CHARACTER_WORDS.current));
        words.append(name);
        if (faint.sub) words.append(element('div', 'wu-g2-sub', faint.sub));
        if (faint.line) words.append(element('div', 'wu-g2-sub', faint.line));
        line.append(element('span', 'wu-g2-num empty'), words);
        block.append(line);
      }
      if (group.fold) {
        const fold = element('div', 'wu-g2-fold');
        fold.append(element('div', 'wu-g2-sub', group.fold.line));
        block.append(fold);
      }
      list.append(block);
    }
    const chosenRow = shown.rows[focus];
    const detail = galleryDetail({ read, row: chosenRow, who: about.who });
    // The card's words scroll; its action row and a refusal stay at its bottom.
    const card = element('div', 'wu-g2-detail'), words = element('div', 'wu-g2-scroll');
    const named = element('div', 'wu-g2-named');
    named.append(element('div', 'wu-g2-dname', detail.name));
    if (detail.by) {
      const by = element('div', 'wu-g2-by', `${detail.by} · `);
      if (detail.link) {
        const link = element('a', 'wu-g2-link', GALLERY_WORDS.learnMore);
        link.href = detail.link; link.target = '_blank'; link.rel = 'noopener';
        by.append(link);
      }
      named.append(by);
    }
    words.append(named);
    if (detail.why.length) {
      const why = element('ul', 'wu-g2-why');
      why.append(...detail.why.map((said: string) => element('li', '', said)));
      words.append(why);
    }
    if (detail.words) {
      words.append(element('div', 'wu-g2-k', GALLERY_WORDS.inWords));
      words.append(element('div', 'wu-g2-quote', detail.words.said));
    }
    if (detail.facts.length) {
      const facts = element('div', 'wu-g2-facts');
      for (const fact of detail.facts) facts.append(element('div', 'wu-g2-fk', fact.key), element('div', 'wu-g2-fv', fact.value));
      words.append(facts);
    }
    const listPart = scrollingColumn(list), wordsPart = scrollingColumn(words);
    const act = element('div', 'wu-g2-act');
    act.append(keyButton(['Enter'], detail.act, () => void use(focus)));
    card.append(wordsPart.column, act);
    if (refusal) card.append(element('p', 'wu-g2-refused', refusal));
    if (busy) card.setAttribute('aria-busy', 'true');
    const keys = element('div', 'wu-g2-keys wu-frame-keys');
    for (const one of shown.keys) {
      const item = element('span', 'wu-g2-key');
      one.caps.forEach((cap: string, at: number) => {
        if (at && one.through) item.append(' to ');
        item.append(element('kbd', 'wu-hr-cap', cap));
      });
      item.append(element('span', '', one.word));
      keys.append(item);
    }
    // One grid filling the window: the head, the body with the list and the card, and the key row under them.
    const body = element('div', 'wu-g2-body wu-frame-body'), grid = element('div', 'wu-frame');
    body.append(listPart.column, card);
    grid.append(head, body, keys);
    content.append(...ground(hooks.still()), grid);
    list.scrollTop = was.list;
    if (!moved) words.scrollTop = was.words;
    const focused = list.querySelector<HTMLElement>('[aria-current="true"]');
    if (moved || reveal) keepInView(list, focused);
    listPart.update(); wordsPart.update();
    if (typeof ResizeObserver === 'function') {
      // A window that grows or shrinks keeps the row in focus in view too.
      let height = list.clientHeight;
      sizes = new ResizeObserver(() => {
        if (list.clientHeight !== height) { height = list.clientHeight; keepInView(list, focused); }
        listPart.update(); wordsPart.update();
      });
      sizes.observe(list); sizes.observe(words);
    }
  }

  async function use(index: number) {
    if (!row || busy) return;
    const { shown } = view();
    const chosenRow = shown.rows[index];
    if (!chosenRow) return;
    focus = index; busy = true; refusal = null; draw();
    try {
      const verified = await hooks.write(row, chosenRow.model, key);
      busy = false;
      hooks.chosen(verified);
      close();
    } catch (error) {
      refusal = hooks.refusal(error as Json, row);
      key = crypto.randomUUID();
    } finally {
      busy = false;
      draw();
    }
  }

  function close() {
    if (!made) return;
    sizes?.disconnect(); sizes = null;
    made.close();
    made = null; row = null;
    hooks.closed();
  }

  return {
    get isOpen() { return made !== null; },
    open(opened) {
      if (made) return;
      row = opened; refusal = null; busy = false; key = crypto.randomUUID(); drawnFocus = -1;
      made = page({ form: 'full' });
      made.root.classList.add('wu-record', 'wu-g2');
      made.root.setAttribute('aria-label', CHARACTER_WORDS.chooseModel);
      focus = firstFocus(view().shown);
      made.open(hooks.root);
      draw();
      made.root.querySelector<HTMLElement>('.wu-g2-title')?.focus({ preventScroll: true });
    },
    close,
    key(event) {
      if (!made) return false;
      if (event.metaKey || event.ctrlKey || event.altKey || event.code === 'Tab') return false;
      event.preventDefault();
      if (event.repeat && !event.code.startsWith('Arrow')) return true;
      const shown = view().shown;
      const digit = /^Digit([1-9])$/u.exec(event.code);
      if (event.code === 'Escape' && !busy) close();
      else if (event.code === 'ArrowUp' || event.code === 'ArrowDown') {
        focus = moveFocus(shown, focus, event.code === 'ArrowUp' ? -1 : 1); refusal = null; draw(true);
      } else if (event.code === 'Enter') void use(focus);
      else if (digit) {
        const found = rowForKey(shown, digit[1]);
        if (found) void use(shown.rows.indexOf(found));
      }
      return true;
    },
  };
}

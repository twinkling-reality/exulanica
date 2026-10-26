// The model gallery's page (G2): M on a chosen person, and the day page's Model, open it as a light page over the world
// faded behind, as History and the decision page are. The rows and every word are model-gallery.mjs's; this draws them,
// moves the focus, and chooses through the host's own write (recordEntityModel), the one the in-world list used.
import './model-gallery.css';
import { element, keyButton } from './world-ui-record.ts';
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

  function view() {
    const read = hooks.read(), about = hooks.about(row as Json), fromServer = hooks.fromServer();
    const shown = galleryPage({ read, who: about.who, doing: about.doing, current: about.current, fromServer });
    return { read, about, fromServer, shown };
  }

  function draw() {
    if (!made || !row) return;
    const { read, about, fromServer, shown } = view();
    focus = Math.min(focus, shown.rows.length - 1);
    const content = made.content;
    content.replaceChildren();
    const world = element('div', 'wu-g2-world');
    const still = hooks.still();
    if (still) world.style.backgroundImage = `url("${still}")`;
    const head = element('div', 'wu-g2-head');
    head.append(element('div', 'wu-g2-over', shown.over), element('h1', 'wu-g2-title', shown.title), element('div', 'wu-g2-role', shown.role));
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
        button.append(element('span', 'wu-g2-num', one.key), element('span', `wu-g2-mark${one.model ? '' : ' routine'}`, one.mark), words, element('span', 'wu-g2-cost', one.cost));
        button.addEventListener('click', () => { focus = index; refusal = null; draw(); });
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
        line.append(element('span', 'wu-g2-num empty'), element('span', 'wu-g2-mark', faint.mark), words);
        block.append(line);
      }
      if (group.waiting) block.append(element('div', 'wu-g2-fold', group.waiting));
      if (group.fold) {
        const fold = element('div', 'wu-g2-fold');
        fold.append(element('div', 'wu-g2-sub', group.fold.line), element('div', 'wu-g2-sub', group.fold.sub));
        block.append(fold);
      }
      list.append(block);
    }
    const chosenRow = shown.rows[focus];
    const detail = galleryDetail({ read, row: chosenRow, who: about.who, fromServer });
    const card = element('div', 'wu-g2-detail');
    const top = element('div', 'wu-g2-top');
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
    top.append(element('span', `wu-g2-mark big${chosenRow?.model ? '' : ' routine'}`, detail.mark), named);
    card.append(top);
    if (detail.line) card.append(element('p', 'wu-g2-line', detail.line));
    if (detail.why.length) {
      card.append(element('div', 'wu-g2-k', GALLERY_WORDS.why));
      const why = element('ul', 'wu-g2-why');
      why.append(...detail.why.map((words: string) => element('li', '', words)));
      card.append(why);
    }
    if (detail.words) {
      card.append(element('div', 'wu-g2-k', GALLERY_WORDS.inWords));
      const quote = element('div', 'wu-g2-quote', detail.words.said);
      if (detail.words.from) quote.append(element('span', 'wu-g2-from', detail.words.from));
      card.append(quote);
    }
    if (detail.facts.length) {
      card.append(element('div', 'wu-g2-k', GALLERY_WORDS.fromCard));
      const facts = element('div', 'wu-g2-facts');
      for (const fact of detail.facts) facts.append(element('div', 'wu-g2-fk', fact.key), element('div', 'wu-g2-fv', fact.value));
      card.append(facts);
    }
    const act = element('div', 'wu-g2-act');
    act.append(keyButton(['Enter'], detail.act, () => void use(focus)));
    if (detail.then) act.append(element('span', 'wu-g2-then', detail.then));
    card.append(act);
    if (refusal) card.append(element('p', 'wu-g2-refused', refusal));
    if (busy) card.setAttribute('aria-busy', 'true');
    const keys = element('div', 'wu-g2-keys');
    for (const one of shown.keys) {
      const item = element('span', 'wu-g2-key');
      one.caps.forEach((cap: string, at: number) => {
        if (at && one.through) item.append(' to ');
        item.append(element('kbd', 'wu-hr-cap', cap));
      });
      item.append(element('span', '', one.word));
      keys.append(item);
    }
    content.append(world, element('div', 'wu-g2-wash'), head, list, card, keys);
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
    made.close();
    made = null; row = null;
    hooks.closed();
  }

  return {
    get isOpen() { return made !== null; },
    open(opened) {
      if (made) return;
      row = opened; refusal = null; busy = false; key = crypto.randomUUID();
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
        focus = moveFocus(shown, focus, event.code === 'ArrowUp' ? -1 : 1); refusal = null; draw();
      } else if (event.code === 'Enter') void use(focus);
      else if (digit) {
        const found = rowForKey(shown, digit[1]);
        if (found) void use(shown.rows.indexOf(found));
      }
      return true;
    },
  };
}

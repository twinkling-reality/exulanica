// A decision on the record page (DESIGN's r10, approved 16 October; the R-DAY-DECISION build sheet, section 2 and its
// 1440 rules): History's light page read left to right as a flowchart. What the character's model was told, gathered
// by a thin bracket into one line; the decision's ring with who decided and how many choices there were; the choices
// fanned out to a column, the taken one lit and the rest dashed (twelve drawn, more scrolled with the up and down
// arrows); and the taken one's line running on to the moment's card, with what happened. [J] shows the stored record as
// it is. It draws from what it is given and says what it was asked through `act` (earlier, later, record, compare,
// back); contextual-world.ts reads and answers every other key. Places come from decision-flow.mjs, words from
// decision-words.mjs, the light page's parts from world-ui-record.ts.
import { CHARACTER_WORDS } from './character-words.mjs';
import { COMPARE_WORDS } from './compare-words.mjs';
import { FLOW_LAYOUTS, choiceEnd, flowLayout, flowSize, headBottom, rowMost, titleLines, toldHeight } from './decision-flow.mjs';
import { DECISION_FLOW_WORDS, DECISION_WORDS, choseOneOf, decidedByParts } from './decision-words.mjs';
import { page, type Page } from './world-ui.ts';
import { element, ground, keyButton, keyRow, orbs, pictureBox, px, sentence, type Parts } from './world-ui-record.ts';
import './world-ui-record-decision.css';

/** Who decided (T7): a model, a person playing, or an outside program. */
export type Decider = 'model' | 'person' | 'external';

export interface DecisionPageState {
  /** "06:52 · Day 1 · Teo said to Ines"; with the moments read, "06:52 · Day 1 · Teo met Ines at the bench". */
  readonly over: string;
  /** The words said, in quotes, or what was chosen; empty while the record is read. */
  readonly title: string;
  readonly model: string | null;
  /** "Done at 06:53 · answered in 0.9 s · cost $0.0003", or the answer's time and cost. */
  readonly done: string | null;
  /** What came of it when it was not done, in the choice account's words. */
  readonly verdict: string | null;
  readonly toldLabel: string;
  /** The sections of what the model was told; null while the record is read. */
  readonly told: readonly { readonly label: string; readonly lines: readonly string[]; readonly apart: boolean }[] | null;
  readonly choicesLabel: string;
  readonly choices: readonly { readonly number: number; readonly words: string; readonly chosen: boolean }[];
  readonly earlier: boolean;
  readonly later: boolean;
  /** The stored record as text while [J] shows it, else null. */
  readonly record: string | null;
  /** Why the record could not be read, or null. */
  readonly failure: string | null;
  /** Whether [C] Compare this moment is offered (C1). */
  readonly canCompare: boolean;
  // r10's own parts, each optional: left out, the page draws from the fields above.
  /** What the character decided, in the moment words ("Teo spoke to Ines"; R1): the head's title. Absent: `title`. */
  readonly decided?: string | null;
  /** The line said, its speaker first ("Teo: “Morning, Ines.”"): What happened's words. */
  readonly said?: string | null;
  /** What was done, in the moment words, where nothing was said ("Teo walked to the bench"). */
  readonly action?: string | null;
  /** Who decided (T7). Absent: a model where `model` names one. */
  readonly decider?: Decider | null;
  /** The answer's recorded time and cost (the receipt's latency_ms, cost_usd and cost_known), for the head's small
   * print. Absent: the small print carries `done`. */
  readonly answered?: { readonly latencyMs: number | null; readonly costUsd: string | number | null; readonly costKnown: boolean } | null;
  /** Over the column of choices: "Teo's choices" (choicesOver). Absent: `choicesLabel`. */
  readonly choicesHeading?: string | null;
  /** The moment's picture (R2), as an image address; absent or null, the quiet tile. */
  readonly picture?: string | null;
  /** The moment's people, the first who acted first: each name, and its portrait's address or null for its letter (R2). */
  readonly portraits?: readonly { readonly name: string; readonly url: string | null }[];
  /** The world faded behind the page (a still of the view), as an image address; absent, the plain ground. */
  readonly ground?: string | null;
  /** The personality as written (the context's character): its name and its words, so the page keeps them apart.
   * Absent: read from the Personality section's lines, name then words. */
  readonly personality?: { readonly name: string | null; readonly about: string | null } | null;
}

export interface DecisionPage {
  draw(state: DecisionPageState): void;
  close(): void;
  /** Hides the page while another stands over it, keeping what it shows. */
  hide(hidden: boolean): void;
}

/** The parts of decision-flow.mjs's sizes the page reads. */
interface Size {
  readonly width: number;
  readonly margin: number;
  readonly headTop: number;
  readonly headWidth: number;
  readonly told: { readonly width: number };
}

interface Box { readonly left: number; readonly top: number; readonly width: number }

/** decision-flow.mjs's flow, as the page draws it. */
interface Flow {
  readonly told: Box & { readonly most: number };
  readonly record: Box & { readonly height: number };
  readonly bracket: { readonly path: string; readonly into: string } | null;
  readonly ring: { readonly x: number; readonly y: number; readonly r: number; readonly core: number };
  readonly caption: { readonly x: number; readonly y: number };
  readonly over: { readonly x: number; readonly y: number };
  readonly rows: readonly { readonly index: number; readonly y: number; readonly taken: boolean; readonly path: string; readonly end: { readonly x: number; readonly y: number; readonly r: number } }[];
  readonly offset: number;
  readonly above: number;
  readonly below: number;
  readonly lit: string | null;
  readonly onward: string | null;
  readonly card: { readonly x: number; readonly top: number; readonly width: number; readonly height: number; readonly text: number; readonly orb: number };
  readonly down: { readonly x: number; readonly y: number };
}

type Section = NonNullable<DecisionPageState['told']>[number];
type Written = NonNullable<DecisionPageState['personality']>;
interface Block { readonly words: string; readonly quote: boolean }

const SVG = 'http://www.w3.org/2000/svg';
const kept = (words: string | null | undefined): string | null => words?.trim() || null;

/**
 * A section's blocks, each starting on its own line. The personality keeps the name and the words apart: the name
 * plain, the words as the person wrote them in curly quotes, and with no words the name alone. `written` says which
 * is which; without it, of the lines personalityRecordLines gives (the name, then the words), a line alone is drawn
 * plain, since a name cannot be told from words. Each need is on its own line (J14, J19); the others run on as one
 * paragraph.
 */
function blocksOf(section: Section, written: Written | null): readonly Block[] {
  if (section.label === DECISION_WORDS.personality) {
    const several = section.lines.length > 1;
    const name = written ? kept(written.name) : several ? section.lines.slice(0, -1).join(' ') : kept(section.lines[0]);
    const about = written ? kept(written.about) : several ? kept(section.lines.at(-1)) : null;
    const blocks: Block[] = [...(name ? [{ words: name, quote: false }] : []), ...(about ? [{ words: `“${about}”`, quote: true }] : [])];
    if (blocks.length) return blocks;
  }
  return section.apart ? section.lines.map((words) => ({ words, quote: false })) : [{ words: section.lines.join(' '), quote: false }];
}

/** What the model was told, at its place: below the head, stopping above the window's foot (it scrolls past that). */
function placeTold(told: HTMLElement, at: Flow['told']): void {
  px(told, at.left, at.top, at.width);
  told.style.maxHeight = `${at.most}px`;
}

/** The head's small print: who decided, then the answer's time and cost (or the host's `done` where those are not given). */
function smallPrint(state: DecisionPageState): Parts {
  const decider = state.decider ?? (state.model ? 'model' : null);
  if (state.answered) return decidedByParts({ decider, model: state.model, ...state.answered });
  const named: Parts = decidedByParts({ decider, model: state.model });
  if (!state.done) return named;
  return named.length ? [...named, ` · ${state.done.charAt(0).toLowerCase()}${state.done.slice(1)}`] : [state.done];
}

/** The flow's lines: the bracket and its line into the ring, the ring, the dashed choices, the lit path, the dots. */
function flowMarkup(flow: Flow): string {
  const marks: string[] = [];
  if (flow.bracket) marks.push(`<path class="in" d="${flow.bracket.path}"/>`, `<path class="in" d="${flow.bracket.into}"/>`);
  const { x, y, r, core } = flow.ring;
  marks.push(`<circle class="node" cx="${x}" cy="${y}" r="${r}"/>`, `<circle class="core" cx="${x}" cy="${y}" r="${core}"/>`);
  for (const row of flow.rows) if (!row.taken) marks.push(`<path class="dim" d="${row.path}"/>`);
  if (flow.lit) marks.push(`<path class="lit" d="${flow.lit}"/>`);
  for (const row of flow.rows) marks.push(`<circle class="${row.taken ? 'end lit' : 'end'}" cx="${row.end.x}" cy="${row.end.y}" r="${row.end.r}"/>`);
  if (flow.onward) marks.push(`<path class="lit onward" d="${flow.onward}"/>`);
  return marks.join('');
}

const shortcut = (button: HTMLButtonElement, keys: string): HTMLButtonElement => {
  button.setAttribute('aria-keyshortcuts', keys);
  return button;
};

/** The column's up or down arrow cap, drawn where more choices lie that way; pressing it scrolls one row. */
function moreButton(cap: '↑' | '↓', onPress: () => void): HTMLButtonElement {
  const button = shortcut(element('button', 'wu-rd-more'), cap === '↑' ? 'ArrowUp' : 'ArrowDown');
  button.type = 'button';
  button.append(element('kbd', 'wu-hr-cap', cap));
  button.addEventListener('click', onPress);
  return button;
}

/** Opens the page in `host`; `act` hears earlier, later, record, compare and back. */
export function openDecisionPage(host: HTMLElement, act: (action: string) => void): DecisionPage {
  const sheet: Page = page({ form: 'full' });
  sheet.root.classList.add('wu-record', 'wu-record-decision');
  sheet.keys.remove();
  sheet.open(host);
  const lifetime = new AbortController();
  let last: DecisionPageState | null = null;
  let shown = '';
  // The window the page was last laid out for: its size class and its height.
  let sized = '';
  let flow: Flow | null = null;
  // The column's first row once the person has scrolled it (null: the window that first shows the taken one), and the
  // choices it belongs to; another decision's choices start again from their own window.
  let offset: number | null = null;
  let listed = '';
  const windowOf = () => {
    const layout: Size = flowSize(host.clientWidth || innerWidth);
    const height = host.clientHeight || innerHeight;
    return { layout, height, key: `${layout.width}:${height}` };
  };

  const scroll = (step: number): void => {
    if (!last || !flow || last.record !== null) return;
    const next = Math.max(0, Math.min(flow.offset + flow.below, flow.offset + step));
    if (next === flow.offset) return;
    offset = next;
    render(last);
  };

  function render(state: DecisionPageState): void {
    const { layout, height, key } = windowOf();
    sized = key;
    sheet.root.classList.toggle('wu-hr-narrow', layout === FLOW_LAYOUTS.narrow);
    const heading = state.decided || state.title;
    sheet.root.setAttribute('aria-label', heading || DECISION_WORDS.reading);
    const read = state.record === null && state.told !== null && !state.failure && Boolean(heading);
    const sections = read ? state.told ?? [] : [];
    const choices = read ? state.choices : [];
    const taken = choices.findIndex((choice) => choice.chosen);
    if (read) {
      const identity = JSON.stringify(choices);
      if (identity !== listed) { listed = identity; offset = null; }
    }
    const blocks = sections.map((section) => blocksOf(section, state.personality ?? null));
    const by = smallPrint(state);
    // Where the page cannot measure (before layout, or without one), the head, the told column and the taken row's
    // words are estimated; laid out, they are measured below and the places follow.
    const estimate = {
      head: headBottom(layout, { over: Boolean(state.over), lines: titleLines(layout, heading), by: by.length > 0 }) as number,
      told: blocks.length ? toldHeight(blocks.map((section) => section.map((block) => block.words)), layout.told.width) as number : null,
      end: taken >= 0 ? choiceEnd(layout, choices[taken]!.words, true) as number : null,
    };
    const lay = (head: number, told: number | null, end: number | null): Flow =>
      flowLayout(layout, { count: choices.length, taken, offset, toldHeight: told, takenEnd: end, height, headBottom: head }) as Flow;
    const drawn = lay(estimate.head, estimate.told, estimate.end);
    flow = read ? drawn : null;
    const nodes: Element[] = [...ground(state.ground ?? null)];

    // The head: when and in which moment, what was decided (two lines at most), who decided and what the answer took.
    const head = element('header', 'wu-rd-head');
    px(head, layout.margin, layout.headTop);
    head.style.maxWidth = `${layout.headWidth}px`;
    if (state.over) head.append(element('div', 'wu-hr-over', state.over));
    const title = element('h1', 'wu-rd-title', heading);
    title.tabIndex = -1;
    head.append(title);
    if (by.length) head.append(sentence('p', 'wu-rd-by', by));
    nodes.push(head);

    let told: HTMLElement | null = null, record: HTMLElement | null = null, takenRow: HTMLElement | null = null, lines: SVGSVGElement | null = null;
    if (state.record !== null) {
      record = element('pre', 'wu-rd-record', state.record);
      record.tabIndex = 0;
      record.setAttribute('aria-label', DECISION_WORDS.fullRecord);
      px(record, drawn.record.left, drawn.record.top, drawn.record.width, drawn.record.height);
      nodes.push(record);
    } else {
      // What the model was told; while the record is read, or where it could not be, that alone.
      if (!read || sections.length) {
        told = element('section', 'wu-rd-told');
        placeTold(told, drawn.told);
        told.append(element('p', 'wu-rd-label', state.toldLabel));
        if (state.failure) {
          const note = element('p', 'wu-rd-note', state.failure);
          note.dataset['refused'] = 'true';
          told.append(note);
        } else if (!state.told) told.append(element('p', 'wu-rd-note', DECISION_WORDS.reading));
        sections.forEach((section, at) => {
          const words = element('p', 'wu-rd-words');
          for (const block of blocks[at]!) words.append(element('span', block.quote ? 'wu-rd-block wu-rd-quote' : 'wu-rd-block', block.words));
          const part = element('div', 'wu-rd-section');
          part.append(element('p', 'wu-rd-name', section.label), words);
          told!.append(part);
        });
        nodes.push(told);
      }
      if (read) {
        lines = document.createElementNS(SVG, 'svg');
        lines.setAttribute('class', 'wu-rd-flow');
        lines.setAttribute('aria-hidden', 'true');
        lines.setAttribute('width', String(layout.width));
        lines.setAttribute('height', String(height));
        lines.innerHTML = flowMarkup(drawn);
        nodes.push(lines);

        // Under the ring: who decided and how many choices there were.
        const decider = state.decider ?? (state.model ? 'model' : null);
        const caption = element('div', 'wu-rd-caption');
        px(caption, drawn.caption.x, drawn.caption.y);
        if (decider === 'person' || decider === 'external') caption.append(element('span', 'wu-rd-who', decider === 'person' ? CHARACTER_WORDS.personPlaying : CHARACTER_WORDS.outsideProgram));
        else if (state.model) caption.append(element('span', 'wu-rd-who wu-hr-model', state.model));
        if (taken >= 0) caption.append(element('span', 'wu-rd-count', choseOneOf(choices.length)));
        if (caption.childElementCount) nodes.push(caption);

        // The choices as they were offered, the taken one in the ink with its tag; the arrows' caps where more lie.
        if (choices.length) {
          const columnLabel = state.choicesHeading || state.choicesLabel;
          const column = element('div', 'wu-rd-choices');
          const over = element('div', 'wu-rd-over');
          px(over, drawn.over.x, drawn.over.y);
          over.append(element('p', 'wu-rd-label', columnLabel));
          if (drawn.above) over.append(moreButton('↑', () => scroll(-1)));
          const list = element('ol', 'wu-rd-rows');
          list.setAttribute('aria-label', columnLabel);
          for (const row of drawn.rows) {
            const choice = choices[row.index]!;
            const item = element('li', 'wu-rd-choice');
            item.value = choice.number;
            item.dataset['taken'] = String(row.taken);
            px(item, drawn.over.x, row.y);
            item.style.maxWidth = `${rowMost(layout)}px`;
            item.append(element('span', 'wu-rd-number', String(choice.number)), element('span', 'wu-rd-choice-words', choice.words));
            if (row.taken) {
              item.append(element('span', 'wu-hr-tag', DECISION_WORDS.chosen));
              takenRow = item;
            }
            list.append(item);
          }
          column.append(over, list);
          if (drawn.below) {
            const down = moreButton('↓', () => scroll(1));
            down.classList.add('wu-rd-down');
            px(down, drawn.down.x, drawn.down.y);
            column.append(down);
          }
          nodes.push(column);
        }

        // What happened: the moment's card, its picture and portraits, the line said or what was done.
        const card = element('div', 'wu-rd-moment');
        px(card, drawn.card.x, drawn.card.top, drawn.card.text);
        const picture = pictureBox(state.picture ?? null, drawn.card.width, drawn.card.height);
        const people = state.portraits ?? [];
        if (people.length) picture.append(orbs(people.map((_, at) => String(at)), drawn.card.orb, (id) => people[Number(id)]?.url ?? null, (id) => people[Number(id)]?.name ?? ''));
        const text = element('div', people.length ? 'wu-rd-text' : 'wu-rd-text wu-rd-bare');
        text.append(element('div', 'wu-rd-label', DECISION_FLOW_WORDS.whatHappened));
        if (state.said) text.append(element('div', 'wu-hr-said wu-rd-said', state.said));
        else if (state.action || state.title) text.append(element('div', 'wu-rd-action', state.action || state.title));
        if (state.verdict) text.append(element('p', 'wu-rd-verdict', state.verdict));
        card.append(picture, text);
        nodes.push(card);
      }
    }

    // History's key row, each key only where it works (K6).
    const keys: HTMLButtonElement[] = [];
    if (state.earlier || state.later) keys.push(shortcut(keyButton(['←', '→'], DECISION_WORDS.earlierLater, () => act(state.later ? 'later' : 'earlier')), 'ArrowLeft ArrowRight'));
    if (state.title) keys.push(shortcut(keyButton(['J'], DECISION_WORDS.fullRecord, () => act('record')), 'J'));
    if (state.title && state.canCompare && state.record === null) keys.push(shortcut(keyButton(['C'], COMPARE_WORDS.compareThisMoment, () => act('compare')), 'C'));
    keys.push(shortcut(keyButton(['Esc'], CHARACTER_WORDS.back, () => act('back')), 'Escape'));
    nodes.push(keyRow(keys));
    sheet.content.replaceChildren(...nodes);

    // Laid out: where the head ends places what was told and the record under it; then the told column's height and
    // where the taken row's words end place the bracket and the line on to the card.
    const headHigh = head.offsetHeight;
    if (headHigh > 0) {
      const headEnd = head.offsetTop + headHigh;
      const placed = lay(headEnd, estimate.told, estimate.end);
      if (told) placeTold(told, placed.told);
      if (record) px(record, placed.record.left, placed.record.top, placed.record.width, placed.record.height);
      if (lines) {
        const toldHigh = told?.offsetHeight ?? 0;
        const takenEnd = takenRow ? takenRow.offsetLeft + takenRow.offsetWidth : 0;
        flow = lay(headEnd, blocks.length ? toldHigh || estimate.told : null, takenEnd || estimate.end);
        lines.innerHTML = flowMarkup(flow);
      }
    }

    // The record takes focus while it shows, so the arrows and Space scroll it.
    if (record) record.focus({ preventScroll: true });
    else if (!sheet.root.contains(document.activeElement)) title.focus({ preventScroll: true });
  }

  // The up and down arrows scroll a column of more than twelve choices; every other key is the host's. The page hears
  // them before the host's window listener, which only stops them there.
  document.addEventListener('keydown', (event) => {
    if (event.code !== 'ArrowUp' && event.code !== 'ArrowDown') return;
    if (event.metaKey || event.ctrlKey || event.altKey || sheet.root.hidden || !sheet.root.isConnected) return;
    if (!last || last.record !== null || !flow || flow.above + flow.below === 0) return;
    event.preventDefault();
    scroll(event.code === 'ArrowUp' ? -1 : 1);
  }, { signal: lifetime.signal });
  // A window of another size class or height lays the page out again.
  addEventListener('resize', () => {
    if (last && windowOf().key !== sized) render(last);
  }, { signal: lifetime.signal });

  return {
    draw(state) {
      const key = JSON.stringify(state);
      if (key === shown) return;
      shown = key;
      last = state;
      render(state);
    },
    close() {
      lifetime.abort();
      sheet.close();
      last = null;
      flow = null;
    },
    hide(hidden) { sheet.root.hidden = hidden; },
  };
}

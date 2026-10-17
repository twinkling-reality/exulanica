// A character's last decisions asked again of another model (DESIGN's frame r12, R-DAY-DECISION build sheet section 4
// and "1440 x 900"; rulings C1 to C4), on History's light page: the head with what asking again spent, the answer in
// one sentence, the moments on History's line (a different answer hangs below its moment as a dashed branch, the
// picked moment's dot filled) and the picked moment opened at the right with each answer. While the asks run, frame
// 12a's progress line stands in the answer's place with [Esc] Stop. It draws what it is given and says what it was
// asked through `act` (earlier, later, use, back, stop); contextual-world.ts asks and reads. Words are
// compare-words.mjs's, places compare-line.mjs's, the light page's parts world-ui-record.ts's, and the page's own type,
// colours and sizes world-ui-record-compare.css's; only the places the layout computes are set here.
import { page, type Page } from './world-ui.ts';
import { element, ground, keyButton, keyRow, px, sentence } from './world-ui-record.ts';
import './world-ui-record-compare.css';
import { COMPARE_WORDS, resultSub } from './compare-words.mjs';
import { DOT, PICKED_DOT, TIME_ABOVE, branchPlaces, branchWidth, compareLayout, momentXs, nameParts, saidParts, timeIndexes } from './compare-line.mjs';

export interface CompareRow {
  readonly model: string;
  /** The same model asked again. */
  readonly again: boolean;
  /** What it chose, or "Not asked". */
  readonly what: string;
  /** "As recorded", "Same", "Different", or null where it was not asked. */
  readonly tag: string | null;
}

export interface CompareMark {
  readonly said: boolean;
  readonly differs: boolean;
  readonly hollow: boolean;
}

/** One moment on r12's line. */
export interface CompareLinePoint {
  /** "06:43", or null where the society keeps no clock. */
  readonly time: string | null;
  /** Whether the other model was asked this moment (a stopped or refused asking leaves some unasked). */
  readonly asked: boolean;
  /** The other model's answer, in the decision page's words, where it chose differently; else null. */
  readonly different: string | null;
}

export interface ComparePageState {
  readonly over: string;
  readonly title: string;
  readonly sub: string;
  readonly spent: string;
  readonly moment: { readonly label: string; readonly rows: readonly CompareRow[] } | null;
  /** The answer in words, then the rerun's line under it. */
  readonly eachChose: readonly string[];
  /** One lane per set of answers, in this order: the recorded answers, the asked model's, the recorded model's asked
   * again; none for a single moment. Without `line`, r12's line is drawn from the second. */
  readonly lanes: readonly { readonly name: string; readonly faint: boolean; readonly marks: readonly CompareMark[] }[];
  /** Times under some marks, by the mark's index; used where `line` is absent. */
  readonly times: readonly { readonly index: number; readonly text: string }[];
  readonly focus: number;
  /** "Use Qwen3 235B Instruct for Teo", where the model can be chosen here; else null. */
  readonly use: string | null;
  /** Every moment asked, oldest first. Absent: the line comes from `lanes` and `times`, and only the picked moment's
   * branch carries its answer. */
  readonly line?: readonly CompareLinePoint[];
  /** The other model's name where a branch ends ("Qwen3 235B"); absent, its name as its row gives it. */
  readonly branchName?: string;
  /** While the asks run (C2): "Asking 5 of 24 · $0.0008 of $0.01", in the answer's place with [Esc] Stop; else null. */
  readonly asking?: string | null;
  /** The world's still behind the light page; absent or null, the quiet ground. */
  readonly ground?: string | null;
}

export interface ComparePage {
  draw(state: ComparePageState): void;
  close(): void;
}

/** A moment as the line draws it: whether the other model was asked, whether it chose differently, and its words. */
interface Point { readonly time: string | null; readonly asked: boolean; readonly differs: boolean; readonly words: string | null }
type Time = { readonly index: number; readonly text: string };

const SVG = 'http://www.w3.org/2000/svg';

function shape<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number>): SVGElementTagNameMap[K] {
  const made = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) made.setAttribute(name, String(value));
  return made;
}

/**
 * The line's moments: the host's `line` where it gives one; otherwise the asked model's lane, the second, with the times
 * the host chose and only the picked moment's answer under its branch. The lane is taken by its place, never by its
 * name: after Use, comparing again can ask the model that made the recorded decisions, and both lanes share a name.
 */
function lineOf(state: ComparePageState, other: CompareRow | null): { readonly points: readonly Point[]; readonly times: readonly Time[] | null } {
  if (state.line) {
    return { points: state.line.map(point => ({ time: point.time, asked: point.asked, differs: point.asked && point.different !== null, words: point.different })), times: null };
  }
  const lane = state.lanes[1];
  if (!lane) return { points: [], times: [] };
  const picked = other && other.tag === COMPARE_WORDS.different ? other.what : null;
  return {
    points: lane.marks.map((mark, index) => ({ time: state.times.find(time => time.index === index)?.text ?? null, asked: !mark.hollow, differs: mark.differs, words: index === state.focus ? picked : null })),
    times: state.times,
  };
}

/** Opens the page in `host`; `act` hears earlier, later, use, back and, while the asks run, stop. */
export function openComparePage(host: HTMLElement, act: (action: string) => void): ComparePage {
  const sheet: Page = page({ form: 'full' });
  sheet.root.classList.add('wu-record', 'wu-record-compare');
  sheet.open(host);
  let last: ComparePageState | null = null;
  let shown = '';

  function draw(state: ComparePageState) {
    const width = host.clientWidth || window.innerWidth;
    const layout = compareLayout(width);
    const narrow = layout.narrow;
    const key = JSON.stringify([state, width]);
    last = state;
    if (key === shown) return;
    shown = key;
    sheet.root.classList.toggle('wu-hr-narrow', narrow);
    sheet.root.setAttribute('aria-label', state.title);
    const asking = state.asking ?? null;
    const rows = state.moment?.rows ?? [];
    const other = rows.find(row => !row.again && row.tag !== COMPARE_WORDS.asRecorded) ?? null;
    const names = [...rows.map(row => row.model), ...state.lanes.map(lane => lane.name)];

    // The head (History's): who, how many and when; the title; how they were asked and what asking again spent.
    const head = element('div', 'wu-rc-head');
    px(head, layout.margin, layout.headTop, layout.headWidth);
    const title = element('h1', 'wu-rc-title', state.title);
    title.tabIndex = -1;
    head.append(element('div', 'wu-hr-over', state.over), title, element('p', 'wu-rc-sub', resultSub(state.sub, state.spent)));

    // The answer in words and the rerun's line under it; while the asks run, their progress in its place (C2).
    const answer = element('section', 'wu-rc-answer');
    px(answer, layout.margin, layout.sumTop, layout.sumWidth);
    if (asking) {
      const progress = element('p', 'wu-rc-asking', asking);
      progress.setAttribute('role', 'status');
      answer.append(progress);
    } else {
      state.eachChose.forEach((line, index) => answer.append(sentence('p', index === 0 ? 'wu-rc-sentence' : 'wu-rc-rerun', nameParts(line, names))));
    }

    // The moments on History's line: a hollow dot each, the picked one filled, a moment not asked faint; times every
    // third; a different answer hangs below its moment as a dashed branch ending in the model's name over the answer.
    const { points, times } = lineOf(state, other);
    const count = points.length;
    const focus = Math.max(0, Math.min(count - 1, state.focus));
    const onLine: Element[] = [];
    if (count >= 2) {
      const xs = momentXs(count, layout);
      const svg = shape('svg', { 'aria-hidden': 'true', class: 'wu-rc-line' });
      svg.append(shape('path', { d: `M ${layout.margin} ${layout.lineY} L ${layout.lineTo} ${layout.lineY}`, class: 'line' }));
      const name = state.branchName ?? other?.model ?? '';
      const places = branchPlaces(points.flatMap((point, index) => point.differs ? [{ index, x: xs[index], width: branchWidth(name) }] : []), layout);
      for (const place of places) svg.append(shape('path', { d: place.path, class: 'branch' }));
      points.forEach((point, index) => {
        const picked = index === focus;
        svg.append(shape('circle', { cx: xs[index]!, cy: layout.lineY, r: picked ? PICKED_DOT : DOT, class: 'dot', 'data-index': index, 'data-picked': String(picked), 'data-asked': String(point.asked) }));
      });
      onLine.push(svg);
      const shownTimes = times ?? timeIndexes(xs).flatMap(index => points[index]!.time ? [{ index, text: points[index]!.time! }] : []);
      for (const time of shownTimes) {
        if (time.index >= count) continue;
        const label = element('div', 'wu-rc-time', time.text);
        px(label, xs[time.index]!, layout.lineY - TIME_ABOVE);
        onLine.push(label);
      }
      for (const place of places) {
        if (place.level === null) continue;
        const words = element('div', 'wu-rc-branch');
        words.dataset['index'] = String(place.index);
        words.dataset['side'] = place.side;
        words.dataset['level'] = String(place.level);
        px(words, place.left, place.top, place.width);
        if (name) words.append(element('span', 'wu-rc-branch-name wu-hr-model', name));
        const said = points[place.index]!.words;
        if (said) words.append(element('span', 'wu-rc-branch-words', said));
        onLine.push(words);
      }
    }

    // The picked moment opened at the right: each answer with its 2px rule (the recorded one in the line's colour),
    // the model's name with its tag at the right, and the answer, words said in italic quotes.
    const opened = element('section', 'wu-rc-moment');
    px(opened, layout.openLeft, layout.openTop, layout.openWidth);
    if (state.moment) {
      // One moment's label is its clock alone, or nothing without one (C3).
      if (state.moment.label) opened.append(element('div', 'wu-rc-at wu-hr-time', state.moment.label));
      for (const row of state.moment.rows) {
        const one = element('div', 'wu-rc-row');
        one.dataset['recorded'] = String(row.tag === COMPARE_WORDS.asRecorded);
        one.dataset['tag'] = row.tag ?? '';
        const line = element('div', 'wu-rc-row-head');
        line.append(element('span', 'wu-rc-row-model wu-hr-model', row.model));
        if (row.tag) line.append(element('span', 'wu-rc-row-tag', row.tag));
        const words = element('div', 'wu-rc-row-words');
        for (const part of saidParts(row.what)) words.append(part.said ? element('i', 'wu-hr-said', part.words) : document.createTextNode(part.words));
        one.append(line, words);
        opened.append(one);
      }
    }

    // Keys (History's row), each only where it works (K6); while the asks run, [Esc] Stop alone.
    const keys: HTMLButtonElement[] = [];
    const shortcut = (button: HTMLButtonElement, keysSaid: string) => { button.setAttribute('aria-keyshortcuts', keysSaid); return button; };
    // Pressed, the arrows' key moves to a later moment where one exists, else an earlier one: Compare opens on the newest.
    if (!asking && count >= 2) keys.push(shortcut(keyButton(['←', '→'], COMPARE_WORDS.earlierLater, () => act(focus < count - 1 ? 'later' : 'earlier')), 'ArrowLeft ArrowRight'));
    if (!asking && state.use) keys.push(shortcut(keyButton(['Enter'], state.use, () => act('use')), 'Enter'));
    keys.push(shortcut(asking ? keyButton(['Esc'], COMPARE_WORDS.stop, () => act('stop')) : keyButton(['Esc'], COMPARE_WORDS.back, () => act('back')), 'Escape'));

    sheet.content.replaceChildren(...ground(state.ground ?? null), head, answer, ...onLine, opened, keyRow(keys));
    if (!sheet.root.contains(document.activeElement)) title.focus({ preventScroll: true });
  }

  // The page follows the window's width: the opened moment keeps its margin from the right edge, and below History's
  // threshold the page takes its 1440 sizes.
  const resized = () => { if (last) draw(last); };
  window.addEventListener('resize', resized);
  return {
    draw,
    close() { window.removeEventListener('resize', resized); sheet.close(); },
  };
}

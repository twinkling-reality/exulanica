// A character's decisions asked again (DESIGN's frame 12b, rulings C1 and C2): the moment at the
// playhead with each answer and whether it chose as recorded, what each chose over the moments
// asked, and the band of lanes, one per set of answers, each moment a mark. It draws what it is
// given and says what it was asked through `act` (earlier, later, use, back); contextual-world.ts
// asks and reads. The words are compare-words.mjs's.
import { chip, keyRow, keyWord, label, page, type Page } from './world-ui.ts';
import { COMPARE_WORDS } from './compare-words.mjs';

export interface CompareRow {
  readonly model: string;
  /** The same model asked again: its chip is quiet and its words fainter. */
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

export interface ComparePageState {
  readonly over: string;
  readonly title: string;
  readonly sub: string;
  readonly spent: string;
  readonly moment: { readonly label: string; readonly rows: readonly CompareRow[] } | null;
  /** The first line strong, the second faint. */
  readonly eachChose: readonly string[];
  /** One lane per set of answers; none for a single moment. */
  readonly lanes: readonly { readonly name: string; readonly faint: boolean; readonly marks: readonly CompareMark[] }[];
  /** Times under some marks, by the mark's index. */
  readonly times: readonly { readonly index: number; readonly text: string }[];
  readonly focus: number;
  /** "Use Qwen3 235B Instruct for Teo", where the model can be chosen here; else null. */
  readonly use: string | null;
}

export interface ComparePage {
  draw(state: ComparePageState): void;
  close(): void;
}

const element = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] => {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
};

/** Where mark `index` of `count` sits along a track, as a share of its width (2 % from either end). */
const along = (index: number, count: number): number => count <= 1 ? 0.5 : 0.02 + (index / (count - 1)) * 0.96;

/** Opens the page in `host`; `act` hears earlier, later, use and back. */
export function openComparePage(host: HTMLElement, act: (action: string) => void): ComparePage {
  const sheet: Page = page({ form: 'character' });
  sheet.open(host);
  sheet.root.classList.add('wu-compare');
  let shown = '';
  return {
    draw(state) {
      const key = JSON.stringify(state);
      if (key === shown) return;
      shown = key;
      const content = sheet.content;
      for (const child of [...content.children]) if (child !== sheet.keys) child.remove();
      sheet.root.setAttribute('aria-label', state.title);

      const head = element('div', 'wu-cmp-head');
      const title = element('h1', 'wu-dec-title', state.title);
      title.tabIndex = -1;
      head.append(element('div', 'wu-dec-over wu-small-text wu-faint', state.over), title, element('p', 'wu-page-sub', state.sub));
      if (state.spent) head.append(element('p', 'wu-small-text wu-faint wu-cmp-spent', state.spent));

      const moment = element('section', 'wu-cmp-moment');
      if (state.moment) {
        // One moment's label is its clock alone, or nothing without one (C3).
        if (state.moment.label) moment.append(label(state.moment.label));
        for (const row of state.moment.rows) {
          const line = element('div', row.again ? 'wu-cmp-row wu-cmp-again' : 'wu-cmp-row');
          const held = element('span');
          held.append(chip(row.model, { quiet: row.again }));
          line.append(held, element('span', 'wu-cmp-what', row.what), element('span', row.tag === COMPARE_WORDS.different ? 'wu-cmp-tag wu-cmp-differs' : 'wu-cmp-tag', row.tag ?? ''));
          moment.append(line);
        }
      }

      const each = element('section', 'wu-cmp-each');
      if (state.eachChose.length) {
        each.append(label(COMPARE_WORDS.whatEachChose));
        state.eachChose.forEach((line, index) => each.append(element('p', index === 0 ? 'wu-cmp-each-line' : 'wu-small-text wu-faint wu-cmp-each-faint', line)));
      }

      const parts: HTMLElement[] = [head, moment, each];
      if (state.lanes.length) {
        const band = element('div', 'wu-cmp-band wu-glass');
        const inner = element('div', 'wu-cmp-band-inner');
        const count = state.lanes[0]?.marks.length ?? 0;
        for (const lane of state.lanes) {
          const row = element('div', lane.faint ? 'wu-cmp-lane wu-cmp-faint' : 'wu-cmp-lane');
          const track = element('div', 'wu-cmp-track');
          lane.marks.forEach((mark, index) => {
            const dot = element('i', ['wu-cmp-mark', mark.said ? 'wu-cmp-said' : '', mark.differs ? 'wu-cmp-diff' : '', mark.hollow ? 'wu-cmp-hollow' : ''].filter(Boolean).join(' '));
            dot.style.left = `${(along(index, count) * 100).toFixed(2)}%`;
            track.append(dot);
          });
          row.append(element('div', 'wu-cmp-lane-name', lane.name), track);
          inner.append(row);
        }
        const axis = element('div', 'wu-cmp-axis');
        const ticks = element('div', 'wu-cmp-ticks');
        for (const time of state.times) {
          const tick = element('span', '', time.text);
          tick.style.left = `${(along(time.index, count) * 100).toFixed(2)}%`;
          ticks.append(tick);
        }
        axis.append(element('div'), ticks);
        const playhead = element('div', 'wu-cmp-playhead');
        playhead.style.setProperty('--at', String(along(state.focus, count)));
        inner.append(axis, playhead);
        band.append(inner);
        parts.push(band);
      }
      content.prepend(...parts);

      const keys = [
        ...(state.lanes.length ? [keyWord({ keys: ['←', '→'], word: COMPARE_WORDS.earlierLater, shortcut: 'ArrowLeft ArrowRight' })] : []),
        ...(state.use ? [keyWord({ keys: ['Enter'], word: state.use, shortcut: 'Enter', onPress: () => act('use') })] : []),
        keyWord({ keys: ['Esc'], word: COMPARE_WORDS.back, shortcut: 'Escape', onPress: () => act('back') }),
      ];
      sheet.keys.replaceChildren(...keyRow(keys).children);
      if (!sheet.root.contains(document.activeElement)) title.focus({ preventScroll: true });
    },
    close() { sheet.close(); },
  };
}

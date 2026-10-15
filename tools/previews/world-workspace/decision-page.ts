// One decision over the world (DESIGN's frame 10): when it was asked, what was said or chosen, the
// model, what came of it, then what the character's model was told and the choices it had. [J] shows
// the stored record as it is. It draws from what it is given and says what it was asked through
// `act` (earlier, later, record, back); contextual-world.ts reads. The words are decision-words.mjs's.
import { chip, keyRow, keyWord, label, page, type Page } from './world-ui.ts';
import { CHARACTER_WORDS } from './character-words.mjs';
import { DECISION_WORDS } from './decision-words.mjs';
import { COMPARE_WORDS } from './compare-words.mjs';

export interface DecisionPageState {
  /** "06:52 · Day 1 · Teo said to Ines". */
  readonly over: string;
  /** The words said in quotes, or what was chosen; empty while the record is read. */
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
}

export interface DecisionPage {
  draw(state: DecisionPageState): void;
  close(): void;
}

const element = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] => {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
};

/** Opens the page in `host`; `act` hears earlier, later, record and back. */
export function openDecisionPage(host: HTMLElement, act: (action: string) => void): DecisionPage {
  const sheet: Page = page({ form: 'character' });
  sheet.open(host);
  sheet.root.classList.add('wu-decision');
  let shown = '';
  return {
    draw(state) {
      const key = JSON.stringify(state);
      if (key === shown) return;
      shown = key;
      const content = sheet.content;
      for (const child of [...content.children]) if (child !== sheet.keys) child.remove();
      const head = element('div', 'wu-dec-head');
      const title = element('h1', 'wu-dec-title', state.title);
      title.tabIndex = -1;
      const meta = element('div', 'wu-dec-meta');
      if (state.model) meta.append(chip(state.model, { page: true }));
      if (state.done) meta.append(element('span', 'wu-small-text wu-faint', state.done));
      if (state.over) head.append(element('div', 'wu-dec-over wu-small-text wu-faint', state.over));
      head.append(title, meta);
      if (state.verdict) head.append(element('p', 'wu-small-text wu-dec-verdict', state.verdict));
      sheet.root.setAttribute('aria-label', state.title || DECISION_WORDS.reading);
      const parts: HTMLElement[] = [head];
      if (state.record !== null) {
        const record = element('pre', 'wu-dec-record', state.record);
        record.tabIndex = 0;
        record.setAttribute('aria-label', DECISION_WORDS.fullRecord);
        parts.push(record);
      } else {
        const told = element('section', 'wu-dec-told');
        told.append(label(state.toldLabel));
        if (state.failure) told.append(element('p', 'wu-char-note', state.failure));
        else if (!state.told) told.append(element('p', 'wu-char-note', DECISION_WORDS.reading));
        for (const section of state.told ?? []) {
          const paragraph = element('p', 'wu-told');
          paragraph.append(element('b', '', section.label));
          if (section.apart) for (const line of section.lines) paragraph.append(element('span', 'wu-told-line', line));
          else paragraph.append(section.lines.join(' '));
          told.append(paragraph);
        }
        const choices = element('section', 'wu-dec-choices');
        if (state.choices.length) {
          choices.append(label(state.choicesLabel));
          const list = element('ol', 'wu-choice-rows');
          for (const choice of state.choices) {
            const row = element('li', 'wu-choice-row');
            row.dataset['chosen'] = String(choice.chosen);
            const words = element('span', '', choice.words);
            if (choice.chosen) words.append(element('span', 'wu-choice-chosen', DECISION_WORDS.chosen));
            row.append(element('span', 'wu-choice-number', String(choice.number)), words);
            list.append(row);
          }
          choices.append(list);
        }
        parts.push(told, choices);
      }
      content.prepend(...parts);
      const keys = [
        ...(state.earlier || state.later ? [keyWord({ keys: ['←', '→'], word: DECISION_WORDS.earlierLater, shortcut: 'ArrowLeft ArrowRight' })] : []),
        ...(state.title ? [keyWord({ keys: ['J'], word: DECISION_WORDS.fullRecord, shortcut: 'J', onPress: () => act('record') })] : []),
        ...(state.title && state.canCompare && state.record === null ? [keyWord({ keys: ['C'], word: COMPARE_WORDS.compareThisMoment, shortcut: 'C', onPress: () => act('compare') })] : []),
        keyWord({ keys: ['Esc'], word: CHARACTER_WORDS.back, shortcut: 'Escape', onPress: () => act('back') }),
      ];
      sheet.keys.replaceChildren(...keyRow(keys).children);
      // The record takes focus while it shows, so the arrows and Space scroll it.
      const record = sheet.root.querySelector<HTMLElement>('.wu-dec-record');
      if (record) record.focus({ preventScroll: true });
      else if (!sheet.root.contains(document.activeElement)) title.focus({ preventScroll: true });
    },
    close() { sheet.close(); },
  };
}

// A character's page over the world (DESIGN's frames 06 and 07): who the character is, its model
// and what a run would be on the left; what it did, or the models to choose from, on the right.
// It draws from what it is given and says what it was asked through `act`; contextual-world.ts
// reads, writes and runs. The words are character-words.mjs's and run-words.mjs's.
import { chip, keyRow, keyWord, label, orb, page, type Page } from './world-ui.ts';
import { CHARACTER_WORDS, modelLine, notConnected, routineLine, routineRow, priceWords, whatDid, nothingYet, readingRecord, called } from './character-words.mjs';
import { PERSONALITY_LIMITS, PERSONALITY_WORDS, counter, length, notRead, readsEach } from './personality-words.mjs';

type Who = ReturnType<typeof called>;

export interface DidRow {
  readonly time: string;
  readonly what: string;
  readonly sub: string;
  /** Whether a recorded decision stands behind the row, which [Enter] Inspect decision opens. */
  readonly decision: boolean;
}

export interface ModelChoice {
  /** null for Routine. */
  readonly model: { readonly provider: string; readonly modelId: string; readonly name: string; readonly price: unknown; readonly local?: boolean } | null;
  readonly current: boolean;
}

export interface CharacterPageState {
  readonly who: Who;
  readonly sub: string;
  /** Whether this person may choose the character's model here (the role's write is permitted). */
  readonly assignable: boolean;
  /** The assigned model, or null for the routine; undefined while the models are read. */
  readonly model: { readonly name: string; readonly price: unknown; readonly local?: boolean } | null | undefined;
  /** Whether a run can be asked of a model here: false where no model is connected. */
  readonly connected: boolean;
  /** Whether any model is connected here at all (the models read offers one it can ask). */
  readonly anyConnected: boolean;
  readonly run: {
    readonly open: boolean;
    /** "10 minutes · at most $0.05", or the running line. */
    readonly big: string;
    readonly small: string;
    readonly busy: boolean;
    /** A refusal in plain words, or null. */
    readonly refusal: string | null;
  };
  /** The rows of What Teo did, newest first; null while they are read. */
  readonly did: readonly DidRow[] | null;
  /** The chosen row, which the arrows move; null with none. */
  readonly didFocus: number | null;
  /** Whether [Q] Ask is offered. */
  readonly canAsk: boolean;
  /** Ask's questions in the right column in place of the rows, and an answer once one is read; or null. */
  readonly ask: {
    readonly questions: readonly string[];
    readonly focus: number;
    readonly busy: boolean;
    /** The question answered, its answer's lines (a note line marked), or a failure. */
    readonly asked: string | null;
    readonly answer: readonly { readonly text: string; readonly note: boolean }[] | null;
    readonly failure: string | null;
  } | null;
  readonly lastRun: string | null;
  /**
   * The personality its owner wrote for a being they placed ({ character, shown }), or null for
   * anything else, whose page has no Personality section (spec 8.6).
   */
  readonly personality: { readonly character: { readonly name: string | null; readonly about: string | null } | null; readonly shown: boolean } | null;
  /** The personality being written, or null: its fields hold their own words while a person types. */
  readonly editing: { readonly session: string; readonly refusal: string | null; readonly busy: boolean } | null;
  /** The model list while choosing, or null. */
  readonly choosing: { readonly choices: readonly ModelChoice[] | null; readonly focus: number; readonly refusal: string | null; readonly busy: boolean } | null;
}

export interface CharacterPage {
  draw(state: CharacterPageState): void;
  /** Hides the page while a decision's page shows over the world in its place. */
  hide(hidden: boolean): void;
  close(): void;
}

const element = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] => {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
};

/**
 * Opens the page in `host`; `act` hears model, run, stop, choose (with an index), use, back, row
 * and inspect (with a row's index), ask and question (with a question's index).
 */
export function openCharacterPage(host: HTMLElement, act: (action: string, value?: unknown) => void): CharacterPage {
  const sheet: Page = page({ form: 'character' });
  sheet.open(host);
  sheet.root.setAttribute('aria-label', 'Character');
  let shown = '';
  // The personality's fields while it is written: kept in place, so typing never loses its place.
  let editor: { session: string; refusal: HTMLElement; save: HTMLElement; counts: (() => void) } | null = null;
  return {
    draw(state) {
      const key = JSON.stringify(state);
      if (key === shown) return;
      shown = key;
      if (state.editing && editor?.session === state.editing.session) {
        editor.refusal.textContent = state.editing.refusal ?? '';
        editor.refusal.hidden = !state.editing.refusal;
        editor.save.toggleAttribute('disabled', state.editing.busy);
        editor.counts();
        return;
      }
      editor = null;
      const focused = document.activeElement instanceof HTMLElement && sheet.root.contains(document.activeElement) ? document.activeElement.dataset['focusKey'] ?? null : null;
      const content = sheet.content;
      for (const child of [...content.children]) if (child !== sheet.keys) child.remove();
      const head = element('div', 'wu-char-head');
      const title = element('h1', 'wu-page-title', state.who.title);
      title.tabIndex = -1;
      head.append(title, element('p', 'wu-page-sub', state.sub));
      sheet.root.setAttribute('aria-label', state.who.title);

      const left = element('div', state.choosing ? 'wu-char-left wu-choosing' : 'wu-char-left');
      if (state.editing && state.personality) editor = drawEditor(left, state, act);
      const personality = state.personality && !state.editing ? element('section', 'wu-char-block') : null;
      if (personality && state.personality) {
        personality.dataset['section'] = 'personality';
        personality.append(label(PERSONALITY_WORDS.label));
        const words = [state.personality.character?.name, state.personality.character?.about].filter(Boolean).join('. ');
        if (words) personality.append(element('p', 'wu-quote', state.personality.character?.about ?? state.personality.character?.name ?? ''), element('p', 'wu-small-text wu-faint', PERSONALITY_WORDS.writtenByYou));
        else personality.append(element('p', 'wu-char-note', PERSONALITY_WORDS.none));
        left.append(personality);
      }
      const model = element('section', 'wu-char-block');
      model.dataset['section'] = 'model';
      model.append(label(CHARACTER_WORDS.model));
      if (state.model === undefined) model.append(element('p', 'wu-char-note', CHARACTER_WORDS.readingModels));
      else {
        model.append(state.model ? chip(state.model.name, { page: true }) : chip(CHARACTER_WORDS.routine, { page: true, quiet: true }));
        model.append(element('p', 'wu-small-text wu-faint', modelLine(state.model) ?? ''));
      }
      const run = element('section', 'wu-char-block wu-char-run');
      run.dataset['section'] = 'run';
      run.append(label(CHARACTER_WORDS.run));
      const offered = Boolean(state.model) && state.connected;
      const row = element('div', 'wu-orb-row');
      const button = orb({ word: state.run.open ? CHARACTER_WORDS.stop : CHARACTER_WORDS.run, onPress: () => act(state.run.open ? 'stop' : 'run'), disabled: !offered || state.run.busy });
      button.dataset['focusKey'] = 'run';
      if (!offered) button.tabIndex = -1;
      const words = element('div');
      if (offered) {
        // A line wraps only between its parts, never inside a figure (DESIGN's J9).
        const big = element('p', 'wu-big');
        state.run.big.split(' · ').forEach((part, index) => {
          if (index) big.append(' · ');
          big.append(element('span', 'wu-nowrap', part));
        });
        words.append(big, element('p', 'wu-small-text', state.run.small));
      }
      else words.append(element('p', 'wu-small-text', state.model === null ? routineLine(state.who, state) : state.model ? notConnected(state.who) : ''));
      row.append(button, words);
      run.append(row);
      if (state.run.refusal) {
        const refused = element('p', 'wu-small-text wu-refused', state.run.refusal);
        refused.setAttribute('role', 'status');
        run.append(refused);
      }
      if (!state.editing) left.append(model, run);

      const right = element('section', state.choosing ? 'wu-char-right wu-choosing' : state.editing ? 'wu-char-right wu-dim' : 'wu-char-right');
      if (state.choosing) {
        right.append(label(CHARACTER_WORDS.chooseModel), element('p', 'wu-small-text wu-model-intro', CHARACTER_WORDS.pickingSpendsNothing));
        if (!state.choosing.choices) right.append(element('p', 'wu-char-note', CHARACTER_WORDS.readingModels));
        else {
          right.append(element('div', 'wu-model-head wu-small-text wu-faint', CHARACTER_WORDS.perMillion));
          const list = element('ul', 'wu-model-rows');
          list.setAttribute('role', 'listbox');
          list.setAttribute('aria-label', CHARACTER_WORDS.chooseModel);
          state.choosing.choices.forEach((choice, index) => {
            const item = element('li', 'wu-model-row');
            item.setAttribute('role', 'option');
            item.setAttribute('aria-selected', String(index === state.choosing!.focus));
            item.dataset['current'] = String(choice.current);
            const name = element('span', 'wu-model-name', choice.model ? choice.model.name : CHARACTER_WORDS.routine);
            if (choice.current) name.append(element('span', 'wu-model-current', CHARACTER_WORDS.current));
            item.append(name, element('span', 'wu-model-price', choice.model ? priceWords(choice.model) ?? '' : routineRow()));
            item.addEventListener('click', () => act('choose', index));
            item.addEventListener('dblclick', () => act('use', index));
            list.append(item);
          });
          right.append(list);
        }
        if (state.choosing.refusal) {
          const refused = element('p', 'wu-small-text wu-refused', state.choosing.refusal);
          refused.setAttribute('role', 'status');
          right.append(refused);
        }
      } else if (state.ask) {
        right.append(label(CHARACTER_WORDS.ask));
        const list = element('ul', 'wu-model-rows wu-ask-rows');
        list.setAttribute('role', 'listbox');
        list.setAttribute('aria-label', CHARACTER_WORDS.ask);
        state.ask.questions.forEach((question, index) => {
          const item = element('li', 'wu-model-row wu-ask-row');
          item.setAttribute('role', 'option');
          item.setAttribute('aria-selected', String(index === state.ask!.focus));
          item.append(element('span', 'wu-model-name', question));
          item.addEventListener('click', () => act('question', index));
          list.append(item);
        });
        right.append(list);
        const answer = element('div', 'wu-ask-answer');
        answer.setAttribute('role', 'status');
        if (state.ask.busy) answer.append(element('p', 'wu-char-note', CHARACTER_WORDS.askReading));
        else if (state.ask.failure) answer.append(element('p', 'wu-small-text wu-refused', state.ask.failure));
        else if (state.ask.answer) {
          if (state.ask.asked) answer.append(element('p', 'wu-ask-asked wu-small-text wu-faint', state.ask.asked));
          if (!state.ask.answer.length) answer.append(element('p', 'wu-char-note', CHARACTER_WORDS.noAnswer));
          for (const line of state.ask.answer) answer.append(element('p', line.note ? 'wu-char-note' : 'wu-ask-line', line.text));
        }
        right.append(answer);
      } else {
        right.append(label(whatDid(state.who)));
        if (!state.did) right.append(element('p', 'wu-char-note', readingRecord(state.who)));
        else if (!state.did.length) right.append(element('p', 'wu-char-note', nothingYet(state.who)));
        else {
          const rows = element('div', 'wu-rows');
          state.did.forEach((did, index) => {
            const item = element('div', 'wu-list-row');
            const chosen = index === state.didFocus;
            if (chosen) item.setAttribute('aria-current', 'true');
            const words = element('div');
            words.append(element('div', 'wu-what', did.what), element('div', 'wu-who', did.sub));
            if (chosen && did.decision) {
              const inspect = keyWord({ keys: ['Enter'], word: CHARACTER_WORDS.inspectDecision, shortcut: 'Enter', small: true, onPress: () => act('inspect', index) });
              inspect.classList.add('wu-row-prompt');
              words.append(inspect);
            }
            item.addEventListener('click', () => act('row', index));
            if (did.time) item.append(element('div', 'wu-time', did.time)); else item.dataset['untimed'] = '';
            item.append(words);
            rows.append(item);
          });
          right.append(rows);
        }
        if (state.lastRun) right.append(element('div', 'wu-hairline'), element('p', 'wu-small-text wu-faint', state.lastRun));
      }
      content.prepend(head, left, right);

      const keys = state.choosing
        ? [keyWord({ keys: ['↑', '↓'], word: CHARACTER_WORDS.choose, shortcut: 'ArrowUp ArrowDown' }),
          keyWord({ keys: ['Enter'], word: CHARACTER_WORDS.useThisModel, shortcut: 'Enter', onPress: () => act('use'), disabled: state.choosing.busy || !state.choosing.choices }),
          keyWord({ keys: ['Esc'], word: CHARACTER_WORDS.back, shortcut: 'Escape', onPress: () => act('back') })]
        : state.editing ? []
        : state.ask ? [keyWord({ keys: ['↑', '↓'], word: CHARACTER_WORDS.choose, shortcut: 'ArrowUp ArrowDown' }),
          keyWord({ keys: ['Enter'], word: CHARACTER_WORDS.ask, shortcut: 'Enter', onPress: () => act('question'), disabled: state.ask.busy }),
          keyWord({ keys: ['Esc'], word: CHARACTER_WORDS.back, shortcut: 'Escape', onPress: () => act('back') })]
        : [...(state.assignable ? [keyWord({ keys: ['M'], word: CHARACTER_WORDS.model, shortcut: 'M', onPress: () => act('model') })] : []),
          ...(state.personality ? [keyWord({ keys: ['N'], word: PERSONALITY_WORDS.label, shortcut: 'N', onPress: () => act('personality') })] : []),
          ...(offered ? [keyWord({ keys: ['R'], word: state.run.open ? CHARACTER_WORDS.stop : CHARACTER_WORDS.run, shortcut: 'R', onPress: () => act(state.run.open ? 'stop' : 'run'), disabled: state.run.busy })] : []),
          ...(state.canAsk ? [keyWord({ keys: ['Q'], word: CHARACTER_WORDS.ask, shortcut: 'Q', onPress: () => act('ask') })] : []),
          keyWord({ keys: ['Esc'], word: CHARACTER_WORDS.back, shortcut: 'Escape', onPress: () => act('back') })];
      keys.forEach((prompt, index) => { prompt.dataset['focusKey'] = 'key-' + index; });
      sheet.keys.replaceChildren(...keyRow(keys).children);
      if (editor) return;
      if (focused) (sheet.root.querySelector(`[data-focus-key="${focused}"]`) as HTMLElement | null)?.focus({ preventScroll: true });
      else if (!sheet.root.contains(document.activeElement)) title.focus({ preventScroll: true });
    },
    hide(hidden) { sheet.root.hidden = hidden; },
    close() { sheet.close(); },
  };
}

/**
 * The personality's fields (frame 11): Name and Personality with their counts, what the model makes
 * of it, a refusal where one came, and [Enter] Save, [Esc] Cancel. The fields keep what is typed;
 * each change goes to `act('draft', { name, about })`.
 */
function drawEditor(left: HTMLElement, state: CharacterPageState, act: (action: string, value?: unknown) => void): { session: string; refusal: HTMLElement; save: HTMLElement; counts: () => void } {
  const written = state.personality?.character;
  const field = (labelText: string, value: string, maximum: number, multiline: boolean) => {
    const wrap = element('label', 'wu-char-field');
    const input = multiline ? element('textarea', 'wu-field') : element('input', 'wu-field');
    if (input instanceof HTMLTextAreaElement) input.rows = 4; else input.type = 'text';
    input.value = value;
    input.autocomplete = 'off';
    const count = element('div', 'wu-count', counter(value, maximum));
    wrap.append(label(labelText), input, count);
    return { wrap, input, count, maximum };
  };
  const name = field(PERSONALITY_WORDS.name, written?.name ?? '', PERSONALITY_LIMITS.name, false);
  const about = field(PERSONALITY_WORDS.about, written?.about ?? '', PERSONALITY_LIMITS.about, true);
  const note = element('p', 'wu-small-text', state.personality?.shown ? readsEach(state.who) : notRead(state.who));
  const refusal = element('p', 'wu-small-text wu-refused', state.editing?.refusal ?? '');
  refusal.setAttribute('role', 'status');
  refusal.hidden = !state.editing?.refusal;
  const save = keyWord({ keys: ['Enter'], word: PERSONALITY_WORDS.save, shortcut: 'Enter', onPress: () => act('save') });
  const cancel = keyWord({ keys: ['Esc'], word: PERSONALITY_WORDS.cancel, shortcut: 'Escape', onPress: () => act('back') });
  const row = element('div', 'wu-row wu-char-answers');
  row.append(save, cancel);
  left.append(name.wrap, about.wrap, note, refusal, row);
  const counts = () => {
    for (const one of [name, about]) {
      one.count.textContent = counter(one.input.value, one.maximum);
      one.count.classList.toggle('wu-over', length(one.input.value) > one.maximum);
    }
  };
  for (const one of [name, about]) one.input.addEventListener('input', () => { counts(); act('draft', { name: name.input.value, about: about.input.value }); });
  queueMicrotask(() => about.input.focus({ preventScroll: true }));
  return { session: state.editing!.session, refusal, save, counts };
}

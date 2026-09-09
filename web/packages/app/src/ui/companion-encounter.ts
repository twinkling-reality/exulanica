import type { Turn } from '@exulanica/companion-runtime';
import type { AskUnavailable, CompanionAnswer } from '../companion-ask-api.js';
import {
  buildCompanionChoiceRail,
  type CompanionChoiceHandlers,
} from './companion-choice-rail.js';
import type { CompanionPlacement } from './companion-placement.js';
import { buildCompanionSpeech } from './companion-speech.js';
import { el, replace } from './dom.js';
import type { FirstUsePrompt } from './first-use-guidance.js';

export type CompanionHandlers = CompanionChoiceHandlers;

export type PanelState = 'enter' | 'summon' | 'open';

/** Which of the encounter's four faces is on the screen. */
export type PanelMode = 'turn' | 'asking' | 'answer' | 'failed';

export interface CompanionEncounterOptions {
  readonly speakerName?: string;
}

export interface CompanionEncounter {
  readonly root: HTMLElement;
  setFirstUsePrompt(prompt: FirstUsePrompt | null): void;
  setConfirming(confirming: boolean): void;
  setState(state: PanelState): void;
  state(): PanelState;
  render(turn: Turn | null): void;
  reportRefusal(reasonKey: string): void;
  /**
   * The question went to the library. Shown before the answer, and it is not an answer.
   *
   * Separated from `showAnswer` because the reasoning core has been measured in TENS OF SECONDS
   * on a full packet. A surface with nothing between the question and the reply looks broken for
   * that whole time, and the person's next move is to ask again.
   */
  askStarted(question: string): void;
  showAnswer(answer: CompanionAnswer): void;
  /** Say that the question did not reach an answer. Never a sentence from the copy table alone. */
  reportAskFailure(failure: AskUnavailable): void;
  /** Whether an answer, rather than the turn, is what the panel is currently showing. */
  showingAnswer(): boolean;
  /**
   * What the panel is showing. `pressNumber` and `E` are routed by it.
   *
   * Not derivable from `state`: an open panel showing a question, an open panel showing
   * "Looking through your library" and an open panel showing an answer are three different
   * things to a keyboard, and only the first of them has numbered options on the screen.
   */
  mode(): PanelMode;
  pressNumber(index: number): boolean;
  /** `E` while the encounter is open: show the photograph this turn cites. */
  openEvidence(): boolean;
  setPlacement(placement: CompanionPlacement): void;
  placement(): CompanionPlacement | null;
  hide(): void;
}

export function buildCompanionEncounter(
  handlers: CompanionHandlers,
  options: CompanionEncounterOptions = {},
): CompanionEncounter {
  const speakerName = options.speakerName ?? 'Unnamed Companion';
  const root = el('aside', {
    class: 'companion-encounter',
    'aria-label': 'Companion encounter',
    'aria-live': 'polite',
    'data-state': 'enter',
  });
  /*
   * No design routes here.
   *
   * The encounter carried "Design Companion" and "Design World" as deep links. Whatever the
   * placement, world appearance has nothing to do with being asked whether two photographs show
   * the same person, and offering it mid-question is an invitation to leave the only thing the
   * Companion is for. Customize is already one of the four Atlas commands and is reachable from
   * the encounter like everywhere else.
   */
  const speech = buildCompanionSpeech({ speakerName });
  const choices = buildCompanionChoiceRail(handlers);
  let state: PanelState = 'enter';
  let lastTurn: Turn | null = null;
  /*
   * The answer is held beside the turn rather than in place of it.
   *
   * A question asked mid-turn does not answer the turn's question and must not consume it: the
   * Companion asked something, the person asked something back, and the original is still open.
   * Keeping both means `Back to the question` is a re-render rather than a regenerated turn,
   * which matters because generating a fresh turn would consume a new question from the memory
   * and skip the one nobody answered.
   */
  let answer: CompanionAnswer | null = null;
  /*
   * THE KEYBOARD MAY ONLY REACH WHAT IS ON THE SCREEN.
   *
   * While a question is out the rail is detached, but the rail object still holds the open turn
   * and `main.ts` still routes every digit key to `pressNumber`. Submitting the composer removes
   * the focused input from the document, so focus falls back to `body` and the host's
   * "is the user typing" guard stops firing. A person typing their NEXT question, one that
   * happens to start with a digit, would then select an option they cannot see; on an identity
   * question that option is tier 2, and the confirmation surface would open over
   * "Looking through your library" for a claim about a person that nobody chose.
   *
   * `state` cannot express this, because the panel is genuinely open the whole time. The mode
   * can, and both keyboard routes are gated on it.
   */
  let mode: PanelMode = 'turn';
  /** An answer that arrived while the Companion was away, held until it is summoned back. */
  let pendingFailure: AskUnavailable | null = null;
  let lastQuestion: string | null = null;
  let currentPlacement: CompanionPlacement | null = null;
  let firstUsePrompt: FirstUsePrompt | null = null;

  function renderPrompt(): void {
    root.toggleAttribute('data-first-use', firstUsePrompt !== null);
    if (firstUsePrompt !== null) {
      root.toggleAttribute('data-compact-prompt', firstUsePrompt.compact === true);
      replace(root, [
        el('p', { class: 'companion-prompt' }, [
          el('span', { class: 'companion-prompt-statement', text: firstUsePrompt.statement }),
          el('span', { class: 'companion-prompt-actions' }, firstUsePrompt.actions.map((action) =>
            el('span', { class: 'companion-prompt-action' }, [
              ...(action.key === undefined ? [] : [el('b', { text: action.key })]),
              action.label,
            ]))),
        ]),
      ]);
      return;
    }
    root.removeAttribute('data-compact-prompt');
    replace(root, [
      el(
        'p',
        { class: 'companion-prompt' },
        state === 'enter'
          ? ['Click to look around']
          : ['Press ', el('b', { text: 'X' }), ` to call ${speakerName}`],
      ),
    ]);
  }

  function renderTurn(turn: Turn): void {
    mode = 'turn';
    speech.render(turn);
    choices.render(turn);
    replace(root, [speech.root, choices.root]);
  }

  function renderAnswer(shown: CompanionAnswer): void {
    mode = 'answer';
    speech.renderAnswer(shown);
    choices.renderAnswer(shown, backToQuestion);
    replace(root, [speech.root, choices.root]);
  }

  function renderAsking(question: string): void {
    mode = 'asking';
    speech.renderAsking(question);
    replace(root, [speech.root]);
  }

  function renderFailure(failure: AskUnavailable): void {
    mode = 'failed';
    speech.reportAskFailure(failure);
    // The rail comes back with the turn's own choices, so a question that failed leaves the
    // person exactly where they were rather than in a dead end.
    if (lastTurn !== null) choices.render(lastTurn);
    replace(root, lastTurn === null ? [speech.root] : [speech.root, choices.root]);
  }

  /**
   * Draw whatever the panel is currently about, or the prompt when it is closed.
   *
   * One function rather than a branch at each entry point, because the entry points are the
   * three that arrive ASYNCHRONOUSLY. A question can be out for as long as `ASK_TIMEOUT_MS`, and
   * in that time the person can press Escape, open the Index, or walk away. Rendering an answer
   * into a dismissed Companion would put a sentence on the screen where "Press X to call" was.
   */
  function reflect(): void {
    if (state !== 'open') {
      renderPrompt();
      return;
    }
    if (pendingFailure !== null) renderFailure(pendingFailure);
    else if (answer !== null) renderAnswer(answer);
    else if (mode === 'asking' && lastQuestion !== null) renderAsking(lastQuestion);
    else if (lastTurn !== null) renderTurn(lastTurn);
    else renderPrompt();
  }

  function backToQuestion(): void {
    answer = null;
    pendingFailure = null;
    mode = 'turn';
    root.removeAttribute('data-answering');
    reflect();
  }

  renderPrompt();

  return {
    root,
    setFirstUsePrompt(prompt) {
      firstUsePrompt = prompt;
      if (state !== 'open') renderPrompt();
    },
    setConfirming(confirming) {
      root.toggleAttribute('data-confirming', confirming);
      choices.root.inert = confirming;
      choices.root.setAttribute('aria-hidden', confirming ? 'true' : 'false');
    },
    state: () => state,
    placement: () => currentPlacement,
    setPlacement(placement) {
      currentPlacement = placement;
      root.dataset['presenceSide'] = placement.presenceSide;
      root.dataset['speechSide'] = placement.speechSide;
      root.dataset['choicesSide'] = placement.choicesSide;
      root.dataset['placementBasis'] = placement.basis;
    },
    setState(next) {
      state = next;
      root.dataset['state'] = next;
      reflect();
    },
    render(turn) {
      lastTurn = turn;
      // An arriving turn does not overwrite an answer on the screen. `observeSnapshot` and a
      // completed selection both re-render, and either landing mid-read would take the answer
      // away while the person was still looking at it.
      if (state === 'open' && mode !== 'turn') return;
      if (turn === null || state !== 'open') renderPrompt();
      else renderTurn(turn);
    },
    reportRefusal(reasonKey) {
      speech.reportRefusal(reasonKey);
    },
    askStarted(question) {
      answer = null;
      pendingFailure = null;
      lastQuestion = question;
      mode = 'asking';
      root.setAttribute('data-answering', 'asking');
      reflect();
    },
    showAnswer(shown) {
      answer = shown;
      pendingFailure = null;
      mode = 'answer';
      root.setAttribute('data-answering', 'answered');
      // Held rather than drawn when the Companion is away. The answer is not discarded: it is
      // what the person asked for, and summoning again shows it.
      reflect();
    },
    reportAskFailure(failure) {
      answer = null;
      pendingFailure = failure;
      mode = 'failed';
      root.setAttribute('data-answering', 'failed');
      reflect();
    },
    showingAnswer: () => answer !== null,
    mode: () => mode,
    pressNumber(index) {
      // Only while the numbered options are ON THE SCREEN. See the comment on `mode`: the rail
      // still holds the open turn while a question is out, and a digit typed into the next
      // question would otherwise select an option nobody could see.
      return state === 'open' && mode === 'turn' ? choices.pressNumber(index) : false;
    },
    openEvidence() {
      // A turn cites photographs and so does an answer. Neither of the other two faces does.
      return state === 'open' && (mode === 'turn' || mode === 'answer')
        ? choices.openEvidence()
        : false;
    },
    hide() {
      root.setAttribute('hidden', '');
    },
  };
}

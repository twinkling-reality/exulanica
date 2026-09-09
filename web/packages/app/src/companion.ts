import {
  findOption,
  type CompanionSession,
  type ConfirmationSummary,
  type SelectionOutcome,
  type Turn,
} from '@exulanica/companion-runtime';
import type { EvidenceHandle, GraphSnapshot } from '@exulanica/graph-client';
import { AskUnavailable, type CompanionAnswer } from './companion-ask-api.js';
import type { CompanionEncounter } from './ui/companion-encounter.js';
import { say } from './ui/copy.js';

/**
 * The turn loop. What turns the Companion's engine into a conversation.
 *
 * `companion-runtime` decides everything about a turn: which question, which options, what each
 * option would change, and what tier of consequence it carries. This file decides none of that. It
 * moves outcomes to surfaces, which is why it is short and why it should stay short: the model
 * writes words, the code writes consequences, and a controller that began choosing options would
 * be a third place where consequences are decided.
 *
 * **Every write still goes through the confirmation surface.** A selection returns
 * `awaiting_confirmation` carrying a proposal that is staged and not committed, and the only move
 * made here is handing it to the surface that renders it for reading. This file has no access to
 * commit and cannot acquire one: `Session` exposes stage and commit separately, and the gate never
 * leaves the composition root.
 *
 * **And one branch that is a READ.** Free text on an open turn is parsed into an update proposal
 * draft; when the parser finds no change in the words, `companion-runtime` refuses, and until now
 * that refusal was the end of it. But "when were these taken" is not a malformed answer, it is a
 * question, and `POST /selection/ask` has always been able to answer it. So a refusal that means
 * THE WORDS DESCRIBE NO CHANGE is routed to the answer path instead.
 *
 * That branch cannot write and the shape of it is why: `askQuestion` returns a
 * `CompanionAnswer`, nothing here or downstream turns one into a `ProposalDraft`, and
 * `onAwaitingConfirmation` is reachable only from a `SelectionOutcome` that
 * `companion-runtime` produced. The confirmation surface is never told about an answer.
 *
 * **companion-runtime is unchanged.** It still returns `refused`, still writes no sentence and
 * still knows nothing about a model or an HTTP route. Deciding that a particular refusal means
 * "this was a question" is a composition decision, and composition is what this file is.
 */

/**
 * The refusals that mean "these words are not an edit to this graph", and therefore a question.
 *
 * `refused.couldNotParse` is the parser finding no name and no relation in the words.
 * `refused.noSubject` is the OPEN TURN having nothing to attach a change to, which is the state
 * of every turn on a library with no named entities: `generateTurn` returns the `acknowledge`
 * turn, `subjectEntityId` is null, and `session.say` refuses before it ever reaches the parser.
 * That is the reference workspace exactly, so routing only the first would leave the answer path
 * unreachable on the library it was built to answer questions about.
 *
 * Every other refusal is left alone and stays a refusal. `refused.noTurn` means the panel is not
 * open; `refused.useSubmit` and `refused.tierNotOfferableHere` are statements about a CHOICE, and
 * treating either as a question would answer something nobody asked.
 */
const QUESTION_REFUSALS: ReadonlySet<string> = new Set([
  'refused.couldNotParse',
  'refused.noSubject',
]);

export interface CompanionControllerOptions {
  readonly companion: CompanionSession;
  /** Render a staged proposal for reading. The only route from a turn to a write. */
  onAwaitingConfirmation(proposalId: string, summary: ConfirmationSummary, utterance: string): void;
  /**
   * Ask the library a question in words. Absent on an instance that has no answer path.
   *
   * Injected rather than constructed here for the reason every other collaborator is: this file
   * moves outcomes to surfaces, and a controller that built its own HTTP client would be holding
   * a credential as well.
   */
  readonly askQuestion?: (question: string) => Promise<CompanionAnswer>;
  /**
   * The presence is thinking, or it has stopped.
   *
   * `working` is one of the five operational states in `interaction-model.md` 4.1 and the only
   * one with a distinct render. The presence lives in the composition root, so this reports
   * rather than sets.
   */
  readonly onWorking?: (working: boolean) => void;
}

export interface CompanionController {
  /** The encounter is attached after construction, because its handlers call back here. */
  attach(encounter: CompanionEncounter): void;
  current(): Turn | null;
  advance(nowMs: number): void;
  /** Call the Companion: generate a turn and open the panel onto it. */
  summon(nowMs: number): void;
  /** Send it away. The turn is kept, so summoning again resumes rather than re-asking. */
  dismiss(): void;
  /** Summon if away, dismiss if here. */
  toggle(nowMs: number): void;
  observeSnapshot(snapshot: GraphSnapshot): void;
  select(optionId: string): void;
  submit(optionIds: readonly string[]): void;
  say(text: string): void;
  /** The evidence behind a chip, for opening the photograph it came from. */
  evidenceAt(index: number): EvidenceHandle | null;
  /** The answer on the screen, if one is. Exposed so a test can read what was rendered. */
  answer(): CompanionAnswer | null;
  /** Whether a turn is open. Drives the presence's attending behavior. */
  active(): boolean;
}

export function createCompanionController(
  options: CompanionControllerOptions,
): CompanionController {
  const { companion } = options;
  let turn: Turn | null = null;
  let panel: CompanionEncounter | null = null;
  let answer: CompanionAnswer | null = null;
  /*
   * Which question is the current one.
   *
   * Two questions in flight and the slower one landing second would overwrite the newer answer
   * with the older, and the person would read a reply to something they had already moved on
   * from. The composer can be typed into again while the first is still out, and on this chain
   * the first can take tens of seconds, so this is an ordinary case rather than a race nobody
   * hits.
   */
  let asking = 0;

  const render = (): void => panel?.render(turn);

  function handle(outcome: SelectionOutcome, answer: string): void {
    switch (outcome.kind) {
      case 'advanced':
        turn = outcome.turn;
        render();
        return;
      case 'awaiting_confirmation':
        options.onAwaitingConfirmation(
          outcome.proposal.proposalId,
          outcome.confirmation,
          answer,
        );
        return;
      case 'refused':
        // Reported in the words the refusal used. Rewording it into something friendlier here
        // would be inventing a reason, which is the one thing no surface may do.
        panel?.reportRefusal(outcome.reasonKey);
        return;
    }
  }

  async function ask(question: string): Promise<void> {
    const askQuestion = options.askQuestion;
    if (askQuestion === undefined) return;
    const ticket = (asking += 1);
    answer = null;
    panel?.askStarted(question);
    /*
     * Reported AFTER the caller's own synchronous handling, not during it.
     *
     * `say` is called from an event handler, and a host that reflects turn state on the same tick
     * reflects the state as it was BEFORE the question went out. Measured in the running app:
     * `main.ts`'s `onSay` calls `companionController.say(text)` and then
     * `reflectTurnState(companionController.current())` on the next line, the open turn is
     * `acknowledge`, and the presence went to `working` and back to `resting` inside one tick.
     * The avatar sat still for the whole eighteen seconds.
     *
     * A microtask is enough and is not a guess about timing: it runs after the current
     * synchronous execution completes and before any network work resolves, so the working state
     * is set after the host has finished reflecting and before there is anything to report.
     */
    queueMicrotask(() => {
      if (ticket === asking) options.onWorking?.(true);
    });
    try {
      const answered = await askQuestion(question);
      if (ticket !== asking) return;
      answer = answered;
      panel?.showAnswer(answered);
    } catch (error) {
      if (ticket !== asking) return;
      // Reported as what it was. A canned utterance here would be the Companion saying something
      // it has no evidence for, on the one surface whose whole claim is that it does not.
      panel?.reportAskFailure(
        error instanceof AskUnavailable
          ? error
          : new AskUnavailable('unreachable', error instanceof Error ? error.message : String(error)),
      );
    } finally {
      if (ticket === asking) options.onWorking?.(false);
    }
  }

  function said(text: string): void {
    const outcome = companion.say(text, Date.now());
    if (
      outcome.kind === 'refused' &&
      QUESTION_REFUSALS.has(outcome.reasonKey) &&
      options.askQuestion !== undefined
    ) {
      void ask(text);
      return;
    }
    handle(outcome, text);
  }

  /*
   * The answer, if the surface is still showing one.
   *
   * The ENCOUNTER decides what is on the screen: `Back to the question` clears it there, and a
   * controller that kept its own copy would go on pointing `E` at a photograph nobody could see
   * a citation for. So the panel is asked and this field follows it. With no panel attached
   * there is no surface to disagree with, and the held value is the answer.
   */
  const shownAnswer = (): CompanionAnswer | null => {
    if (panel !== null && !panel.showingAnswer()) answer = null;
    return answer;
  };

  const optionAnswer = (optionId: string): string => {
    if (turn === null) return '';
    const option = findOption(turn, optionId);
    return option === null ? '' : (option.phrasing ?? say(option.textKey));
  };

  return {
    attach(next) {
      panel = next;
      render();
    },
    current: () => turn,
    advance(nowMs) {
      turn = companion.advance(nowMs);
      render();
    },
    summon(nowMs) {
      // Resume rather than re-ask. Generating a fresh turn on every summon would consume a new
      // question each time the user glanced away, and the memory would fill with questions
      // nobody was ever shown.
      if (turn === null) turn = companion.advance(nowMs);
      panel?.setState('open');
      render();
    },
    dismiss() {
      panel?.setState('summon');
    },
    toggle(nowMs) {
      if (panel?.state() === 'open') this.dismiss();
      else this.summon(nowMs);
    },
    observeSnapshot(snapshot) {
      companion.observeSnapshot(snapshot);
    },
    select: (optionId) => handle(companion.select(optionId, Date.now()), optionAnswer(optionId)),
    submit: (optionIds) => handle(
      companion.submit(optionIds, Date.now()),
      optionIds.map(optionAnswer).filter(Boolean).join(', '),
    ),
    say: said,
    // The answer's citations while an answer is showing, the turn's evidence otherwise. One
    // index space, because `E` and the chips are one gesture and the surface showing decides
    // what it points at. A citation whose span could not be located resolves to null and stops
    // there rather than falling through to the turn's evidence, which is a different photograph.
    evidenceAt: (index) => {
      const shown = shownAnswer();
      if (shown !== null) return shown.evidence[index]?.handle ?? null;
      return turn?.evidence[index] ?? null;
    },
    answer: shownAnswer,
    active: () => panel?.state() === 'open',
  };
}

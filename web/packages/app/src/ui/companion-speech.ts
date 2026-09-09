import type { Turn } from '@exulanica/companion-runtime';
import type {
  AnswerProvenance,
  AskUnavailable,
  CompanionAnswer,
} from '../companion-ask-api.js';
import { el, replace } from './dom.js';
import { fill, say } from './copy.js';

export interface CompanionSpeechOptions {
  readonly speakerName: string;
}

export interface CompanionSpeech {
  readonly root: HTMLElement;
  render(turn: Turn): void;
  reportRefusal(reasonKey: string): void;
  /** The question is with the library. Says so, and says nothing about what it will find. */
  renderAsking(question: string): void;
  renderAnswer(answer: CompanionAnswer): void;
  reportAskFailure(failure: AskUnavailable): void;
  /**
   * Say that something was not kept, under whatever is currently being said.
   *
   * Appended rather than substituted, and that ordering is the whole point. An answer that
   * reached the screen and failed to store is still a correct, cited answer to the question that
   * was asked: a durability failure is not an answer failure, and replacing the sentence with a
   * notice would take away the thing the person asked for because a second request went wrong.
   * It is also not silent. A Companion that quietly forgot what it was told to remember is
   * exactly the state this whole path exists to leave, and one that forgets without saying so is
   * worse than one that never claimed to remember.
   */
  noteMemoryFailure(reasonKey: string, detail: string): void;
}

/**
 * How long the answer took, as a person reads a duration.
 *
 * Milliseconds under a second, because the difference between 40 ms and 900 ms is the difference
 * between a cache and a call. Seconds above it to one place, because the reasoning core has been
 * measured at 80 s on a 24-item packet and "80412 ms" is not a duration anybody reads.
 */
function duration(latencyMs: number): string {
  return latencyMs < 1000 ? `${latencyMs} ms` : `${(latencyMs / 1000).toFixed(1)} s`;
}

/**
 * One line saying who wrote the sentence above it.
 *
 * The identifier is the SERVED one, out of the response body. `docs/product-direction.md` makes
 * that the gate rather than a nicety: the executed variant is "recorded rather than inferred
 * from configuration", and a line that named the configured model would be wrong exactly when
 * the fallback fired.
 */
export function provenanceSentence(provenance: AnswerProvenance): string {
  const spent = duration(provenance.latencyMs);
  if (provenance.composed === 'none') return say('provenance.none');

  if (provenance.composed === 'unreadable') {
    // Named when a planner call was recorded, unnamed when both attempts raised before any
    // result reached the recorder. Either way it does not mention a search, because there
    // wasn't one.
    return provenance.plannedBy === null
      ? say('provenance.unreadable')
      : fill('provenance.unreadableNamed', { model: provenance.plannedBy, duration: spent });
  }

  if (provenance.composed === 'search') {
    // A model read the question and none wrote the answer. Falling through to
    // `provenance.none` here, which is what this function used to do whenever no composing
    // model was named, printed "No model was asked" over every abstention the interface
    // produced, because the browser sends no plan and the planner therefore always runs.
    return provenance.plannedBy === null
      ? say('provenance.none')
      : fill('provenance.search', { model: provenance.plannedBy, duration: spent });
  }

  if (provenance.composed === 'discarded') {
    return provenance.servedModel === null
      ? fill('provenance.discardedUnnamed', { duration: spent })
      : fill('provenance.discarded', { model: provenance.servedModel, duration: spent });
  }

  if (provenance.servedModel === null) return say('provenance.none');
  const values = { model: provenance.servedModel, duration: spent };
  return fill(provenance.usedFallback ? 'provenance.modelOnFallback' : 'provenance.model', values);
}

/*
 * The band holds speech, and only speech.
 *
 * It used to carry a control that opened the cited photograph, sitting inside the sentence the
 * Companion had just spoken. Two things were wrong with it and renaming it fixed neither. It put
 * an action in the one region reserved for what the Companion says, while the rail beside it
 * exists to hold what a person can do. And it was a third route to a place already reachable two
 * ways: aiming at the memory and pressing Interact opens that occurrence's detail, and the
 * conversation's own third choice asks to see both moments. The citation did not need a button
 * inside a paragraph; it needed to be somewhere a person looks for actions, and it already was.
 */

export function buildCompanionSpeech(options: CompanionSpeechOptions): CompanionSpeech {
  const root = el('section', {
    class: 'companion-speech',
    'aria-labelledby': 'companion-speaker-name',
  });

  let lastQuestion = '';

  const speaker = (): HTMLElement => el('h2', {
    id: 'companion-speaker-name',
    class: 'companion-speaker',
    text: options.speakerName,
  });

  const renderTurn = (turn: Turn): void => {
    const content: (Node | string)[] = [
      el('h2', {
        id: 'companion-speaker-name',
        class: 'companion-speaker',
        text: options.speakerName,
      }),
      el('p', { class: 'companion-utterance', text: turn.utterance ?? say(turn.utteranceKey) }),
    ];

    replace(root, content);
  };

  /*
   * The answer band.
   *
   * The sentence is the SERVER'S. Every clause was validated against the evidence packet before
   * it left the API: a historical clause carries a citation that resolves, and a digit that no
   * value reference covers is refused outright. Rewriting any of it here would put prose nobody
   * checked inside the one surface whose claim is that its sentences are backed, so this renders
   * the clauses and adds only two things the server did not write: a label for which KIND of
   * silence an abstention is, and a line saying which model answered.
   */
  const renderAnswer = (answer: CompanionAnswer): void => {
    lastQuestion = answer.question;
    const content: (Node | string)[] = [
      speaker(),
      el('p', { class: 'companion-question-echo', text: answer.question }),
    ];

    for (const clause of answer.clauses) {
      const paragraph = el('p', { class: 'companion-utterance', text: clause.text });
      paragraph.dataset['clause'] = clause.type;
      content.push(paragraph);
    }
    if (answer.clauses.length === 0) {
      content.push(el('p', { class: 'companion-utterance', text: say('ask.emptyAnswer') }));
    }

    if (answer.abstained !== null) {
      content.push(el('p', {
        class: 'companion-abstention',
        text: say(`abstention.${answer.abstained}`),
      }));
    }

    content.push(el('p', {
      class: 'companion-provenance',
      text: provenanceSentence(answer.provenance),
    }));

    root.dataset['mode'] = 'answer';
    root.toggleAttribute('data-abstained', answer.abstained !== null);
    replace(root, content);
  };

  return {
    root,
    render(turn) {
      root.dataset['mode'] = 'turn';
      root.removeAttribute('data-abstained');
      renderTurn(turn);
    },
    renderAsking(question) {
      lastQuestion = question;
      root.dataset['mode'] = 'asking';
      root.removeAttribute('data-abstained');
      replace(root, [
        speaker(),
        el('p', { class: 'companion-question-echo', text: question }),
        el('p', { class: 'companion-utterance', text: say('ask.working') }),
      ]);
    },
    renderAnswer,
    reportAskFailure(failure) {
      // The working line is REPLACED rather than appended to. Leaving "Looking through your
      // library" above "the question did not reach the library" would leave a sentence on the
      // screen that is no longer true.
      //
      // The kind, then the server's own detail. Two sentences from two places, and only the
      // first of them is this file's to write.
      root.dataset['mode'] = 'failed';
      root.removeAttribute('data-abstained');
      replace(root, [
        speaker(),
        el('p', { class: 'companion-question-echo', text: lastQuestion }),
        el('p', { class: 'companion-refusal', text: say(`ask.failed.${failure.kind}`) }),
        el('p', { class: 'companion-refusal-detail', text: failure.detail }),
      ]);
    },
    reportRefusal(reasonKey) {
      root.append(el('p', { class: 'companion-refusal', text: say(reasonKey) }));
    },
    noteMemoryFailure(reasonKey, detail) {
      // The kind, then whatever the failing side said, which is the same two-sentence shape
      // `reportAskFailure` uses. An empty detail is the case with no server in it at all: an
      // answer whose citations this session could not resolve was refused here, not there.
      root.append(el('p', { class: 'companion-memory-notice', text: say(reasonKey) }));
      if (detail !== '') {
        root.append(el('p', { class: 'companion-memory-notice-detail', text: detail }));
      }
    },
  };
}

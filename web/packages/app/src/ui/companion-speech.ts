import type { Turn } from '@exulanica/companion-runtime';
import {
  unansweredOf,
  type AnswerProvenance,
  type AskUnavailable,
  type CompanionAnswer,
  type ModelCall,
  type UnansweredAttempts,
} from '../companion-ask-api.js';
import { contentRowFields } from '../companion-content.js';
import type { CompanionNames } from '../companion-names.js';
import { drawSimulated, type DrawnPiece, type SocietyNames } from '../companion-simulated.js';
import { el, replace } from './dom.js';
import { fill, say } from './copy.js';

export interface CompanionSpeechOptions {
  readonly speakerName: string;
  /** Turns each placeholder the Companion's words carry back into the account holder's name. */
  readonly names: CompanionNames;
  /** The society this page shows, for each simulated person and place an answer names. */
  readonly society?: () => SocietyNames | null;
}

export interface CompanionSpeech {
  readonly root: HTMLElement;
  render(turn: Turn): void;
  /** Factual host guidance, visually in the speech band but attributed to no speaker. */
  renderGuidance(title: string, detail: string): void;
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
  switch (provenance.composed) {
    case 'none':
      return say('provenance.none');

    case 'unreadable':
      // Named when a planner call was recorded, unnamed when both attempts raised before any
      // result reached the recorder. Either way it does not mention a search, because there
      // wasn't one.
      return provenance.plannedBy === null
        ? say('provenance.unreadable')
        : fill('provenance.unreadableNamed', { model: provenance.plannedBy, duration: spent });

    case 'search':
      // A model read the question and none wrote the answer. Falling through to
      // `provenance.none` here, which is what this function used to do whenever no composing
      // model was named, printed "No model was asked" over every abstention the interface
      // produced, because the browser sends no plan and the planner therefore always runs.
      return provenance.plannedBy === null
        ? say('provenance.none')
        : fill('provenance.search', { model: provenance.plannedBy, duration: spent });

    case 'undrafted':
      return say('provenance.undrafted');

    case 'proposed':
    case 'refused':
    case 'unshown': {
      // Each names the model that read the request, and none mentions evidence or a search,
      // because a proposal is not an answer and nothing was looked at to make one. A refusal can
      // come after the classifier read the request and before any model drew anything, so it
      // names the classifier; a proposal, shown or not, is only ever credited to the model that
      // drew it.
      const model =
        provenance.servedModel ?? (provenance.composed === 'refused' ? provenance.plannedBy : null);
      return model === null
        ? say('provenance.proposalNone')
        : fill(`provenance.${provenance.composed}`, { model, duration: spent });
    }

    case 'discarded':
      return provenance.servedModel === null
        ? fill('provenance.discardedUnnamed', { duration: spent })
        : fill('provenance.discarded', { model: provenance.servedModel, duration: spent });

    // What became of a proposal: a person or the world decided it, and no model did. There was
    // no search either, so the line says only that.
    case 'outcome':
      return say('provenance.proposalNone');

    // The person's own words. Naming a model over them would credit it with their sentence.
    case 'corrected':
      return say('provenance.corrected');

    case 'model': {
      if (provenance.servedModel === null) return say('provenance.none');
      const values = { model: provenance.servedModel, duration: spent };
      return fill(
        provenance.usedFallback ? 'provenance.modelOnFallback' : 'provenance.model',
        values,
      );
    }
  }
}

/**
 * What the attempts that returned no result add to the line above, or nothing when none did.
 *
 * Said because each may have been billed: a person reading "Answered by X in 12.0 s" should not
 * have to guess that the twelve seconds included a model that timed out first. Whether their cost
 * is known comes from the record, never from the failure's own words.
 */
export function unansweredSentence(unanswered: UnansweredAttempts): string {
  if (unanswered.attempts === 0) return '';
  const count = fill('provenance.unanswered', { count: String(unanswered.attempts) });
  return unanswered.costUnknown ? `${count} ${say('provenance.costUnknown')}` : count;
}

/**
 * The paragraph drawn under an answer: who wrote it, and what its unanswered requests came to.
 *
 * One function for a fresh answer and a remembered one, and what it reads is what each keeps: a
 * fresh answer's calls say what went unanswered, and a remembered one, which executed nothing,
 * carries the count that was kept with it. So the paragraph is drawn again exactly as it was
 * first drawn.
 */
export function provenanceParagraph(answer: CompanionAnswer): string {
  return [
    provenanceSentence(answer.provenance),
    unansweredSentence(answer.unanswered ?? unansweredOf(answer.calls)),
  ]
    .filter((sentence) => sentence !== '')
    .join(' ');
}

/**
 * The line a question that failed shows where an answer's provenance would be, whenever the server
 * sent its record: the attempt that ended it and the model it was for, or, when every model it
 * asked answered and something else stopped it (a budget ceiling, say), the models it asked; and
 * how long the question waited in all.
 */
export function failedSentence(calls: readonly ModelCall[]): string {
  if (calls.length === 0) return '';
  const spent = duration(calls.reduce((total, call) => total + call.latencyMs, 0));
  const ended = [...calls].reverse().find((call) => call.outcome !== 'completed');
  const line = ended === undefined
    ? fill('provenance.failed.afterAnswers', {
      models: [...new Set(calls.map((call) => call.servedModel ?? call.requestedModel))].join(', '),
      duration: spent,
    })
    : fill(
      // Never "was asked" of a request that was never sent.
      ended.costBasis === 'not_sent' ? 'provenance.failed.not_sent' : `provenance.failed.${ended.outcome}`,
      { model: ended.requestedModel, duration: spent },
    );
  return calls.some((call) => call.costBasis === 'unknown')
    ? `${line} ${say('provenance.costUnknown')}`
    : line;
}

/**
 * Structured CONTENT rows already returned by Selection. Shown only when a place-content
 * surface is present (confirmed place, including empty). Ordinary capture answers omit it.
 * Each row is described in words; its identifiers stay on the parsed row, not on the screen.
 */
function renderContentSurface(answer: CompanionAnswer): Node[] {
  const surface = answer.content;
  if (surface === undefined || (!surface.placeConfirmed && surface.rows.length === 0)) {
    return [];
  }
  const nodes: Node[] = [
    el('h3', {
      class: 'companion-content-heading',
      text: 'Place content',
    }),
  ];
  if (surface.rows.length === 0) {
    nodes.push(el('p', {
      class: 'companion-content-empty',
      text: 'Nothing is linked to this place yet.',
    }));
    return nodes;
  }
  const list = el('ul', { class: 'companion-content-list' });
  for (const row of surface.rows) {
    const fields = contentRowFields(row);
    list.append(el('li', {
      class: 'companion-content-item',
      'data-origin': row.originKind,
      'data-availability': row.availability,
      'data-visit-evidence': row.personalVisitEvidence ? 'yes' : 'no',
    }, [
      el('dl', { class: 'companion-content-fields' }, fields.flatMap((field) => [
        el('dt', { text: field.label }),
        el('dd', { text: field.value }),
      ])),
    ]));
  }
  nodes.push(list);
  return nodes;
}

/**
 * Spoken text as nodes: a name the account holder saved, or the words said in its place, is its
 * own element, so a surface and a test can tell a restored name from the sentence around it.
 */
function spoken(pieces: readonly DrawnPiece[]): (Node | string)[] {
  return pieces.map((piece) => {
    if (piece.kind === 'text') return piece.text;
    // A simulated person or place: drawn as simulated, never as somebody from the library.
    if (piece.kind === 'simulated') {
      return el('span', {
        class: 'companion-name companion-simulated',
        'data-placeholder': piece.placeholder,
        'data-simulated': piece.subject,
        'data-subject-id': piece.id ?? undefined,
        'data-unresolved': piece.drawn ? undefined : 'not_shown',
        title: piece.subject === 'inhabitant' ? 'Simulated person, invented for this world' : undefined,
        text: piece.text,
      });
    }
    return el('span', {
      class: 'companion-name',
      'data-placeholder': piece.placeholder,
      'data-entity-id': piece.entityId ?? undefined,
      'data-unresolved': piece.kind === 'unresolved' ? piece.reason : undefined,
      text: piece.text,
    });
  });
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
    root.setAttribute('aria-labelledby', 'companion-speaker-name');
    const content: (Node | string)[] = [
      el('h2', {
        id: 'companion-speaker-name',
        class: 'companion-speaker',
        text: options.speakerName,
      }),
      el('p', { class: 'companion-utterance' }, spoken(
        options.names.restore(turn.utterance ?? say(turn.utteranceKey), undefined),
      )),
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
   * the clauses and adds only three things the server did not write: each name the account
   * holder saved, in place of the placeholder the server sent instead of it; a label for which
   * KIND of silence an abstention is; and a line saying which model answered.
   */
  const renderAnswer = (answer: CompanionAnswer): void => {
    root.setAttribute('aria-labelledby', 'companion-speaker-name');
    lastQuestion = answer.question;
    const content: (Node | string)[] = [
      speaker(),
      el('p', { class: 'companion-question-echo', text: answer.question }),
    ];

    for (const clause of answer.clauses) {
      const paragraph = el(
        'p',
        { class: 'companion-utterance' },
        spoken(drawSimulated(
          options.names.restore(clause.text, answer.names),
          answer,
          options.society?.() ?? null,
        )),
      );
      paragraph.dataset['clause'] = clause.type;
      content.push(paragraph);
    }
    if (answer.clauses.length === 0) {
      content.push(el('p', { class: 'companion-utterance', text: say('ask.emptyAnswer') }));
    }

    content.push(...renderContentSurface(answer));

    // A place with nothing linked to it is not a photograph search that found nothing, so the
    // photograph abstention sentence would be wrong there. The server's clause and the empty
    // place-content line already say what happened.
    if (answer.abstained !== null && answer.content?.placeConfirmed !== true) {
      content.push(el('p', {
        class: 'companion-abstention',
        text: say(`abstention.${answer.abstained}`),
      }));
    }

    content.push(el('p', {
      class: 'companion-provenance',
      text: provenanceParagraph(answer),
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
    renderGuidance(title, detail) {
      root.dataset['mode'] = 'guidance';
      root.removeAttribute('data-abstained');
      root.setAttribute('aria-labelledby', 'companion-starter-title');
      replace(root, [
        el('h2', {
          id: 'companion-starter-title', class: 'companion-starter-title', text: title,
        }),
        el('p', { class: 'companion-starter-copy', text: detail }),
      ]);
    },
    renderAsking(question) {
      root.setAttribute('aria-labelledby', 'companion-speaker-name');
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
      root.setAttribute('aria-labelledby', 'companion-speaker-name');
      // The working line is REPLACED rather than appended to. Leaving "Looking through your
      // library" above "the question did not reach the library" would leave a sentence on the
      // screen that is no longer true.
      //
      // The kind, then the server's own detail. Two sentences from two places, and only the
      // first of them is this file's to write.
      root.dataset['mode'] = 'failed';
      root.removeAttribute('data-abstained');
      // The server's sentence is shown as written, without the transport's `code: ` prefix
      // (`http_503: `), which names a status rather than saying anything to a person.
      const detail = failure.detail.replace(/^[a-z0-9_]+: /, '');
      // What the question paid for before it failed, where an answer's provenance would be.
      const paid = failedSentence(failure.execution?.calls ?? []);
      replace(root, [
        speaker(),
        el('p', { class: 'companion-question-echo', text: lastQuestion }),
        el('p', { class: 'companion-refusal', text: say(`ask.failed.${failure.kind}`) }),
        ...(detail === '' ? [] : [el('p', { class: 'companion-refusal-detail', text: detail })]),
        ...(paid === '' ? [] : [el('p', { class: 'companion-provenance', text: paid })]),
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

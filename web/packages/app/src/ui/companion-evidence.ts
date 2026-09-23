import type { OpenedEvidence } from '../evidence.js';
import { el } from './dom.js';
import { fill, say } from './copy.js';

/**
 * The photograph a citation names, drawn inside the Companion, with the way back to what cited it.
 *
 * Opening a citation used to read the photograph and draw nothing: the bytes arrived and the
 * person was left looking at the sentence that pointed at them. The photograph is drawn here, in
 * the Companion's own surface, so reading an answer and checking what it rests on happen in one
 * place.
 *
 * **The bytes are the masked view.** `EvidenceCache` reads `/evidence/{span}/masked`, which hides
 * every person who has not consented and refuses when a mask is required and missing. A photograph
 * that does not open is said in words, with the reason the server gave, and nothing is drawn in its
 * place: a stand-in picture would be a claim that the evidence exists and looks like that.
 */

/** Which face opened the photograph, and so where `Back` returns. */
export type EvidenceOrigin = 'answer' | 'turn';

export interface ShownEvidence {
  readonly origin: EvidenceOrigin;
  /** Null while the bytes are still being read. */
  readonly opened: OpenedEvidence | null;
  /**
   * When the photograph was taken, as the citation carries it. Null when the citation carries no
   * date, which says nothing about the photograph: a remembered answer keeps no dates at all.
   */
  readonly capturedAt: string | null;
}

export interface CompanionEvidenceView {
  readonly root: HTMLElement;
  /** The way back, handed the keyboard when the photograph opens. */
  readonly back: HTMLButtonElement;
}

/**
 * The server's reason, without the transport's code prefix (`http_409: `), which names a status
 * rather than saying anything to a person. The same trim the answer band gives a failed question.
 */
function reasonText(reason: string): string {
  return reason.replace(/^[a-z0-9_]+: /, '');
}

function body(shown: ShownEvidence): Node[] {
  const opened = shown.opened;
  if (opened === null) {
    return [el('p', { class: 'companion-evidence-status', role: 'status', text: say('evidence.opening') })];
  }
  if (!opened.ok) {
    const detail = reasonText(opened.reason);
    return [
      el('p', { class: 'companion-evidence-unavailable', role: 'status', text: say('evidence.unavailable') }),
      ...(detail === '' ? [] : [el('p', { class: 'companion-evidence-unavailable-detail', text: detail })]),
    ];
  }
  // The date an answer states is the first ten characters of this value, so the caption shows
  // the same ten characters rather than a second rendering of the instant.
  return [
    el('figure', { class: 'companion-evidence-figure' }, [
      el('img', { src: opened.url, alt: say('evidence.alt') }),
      ...(shown.capturedAt === null ? [] : [el('figcaption', {
        class: 'companion-evidence-caption',
        text: fill('evidence.takenOn', { date: shown.capturedAt.slice(0, 10) }),
      })]),
    ]),
  ];
}

export function buildCompanionEvidence(
  shown: ShownEvidence,
  onBack: () => void,
): CompanionEvidenceView {
  const back = el('button', {
    type: 'button',
    class: 'companion-choice companion-evidence-back',
  }, [el('span', {
    class: 'command-action-label',
    text: say(shown.origin === 'answer' ? 'evidence.backToAnswer' : 'answer.backToQuestion'),
  })]);
  back.addEventListener('click', onBack);

  const state = shown.opened === null ? 'opening' : shown.opened.ok ? 'shown' : 'unavailable';
  const root = el('section', {
    class: 'companion-evidence',
    'aria-labelledby': 'companion-evidence-title',
    'data-evidence': state,
  }, [
    el('div', { class: 'companion-evidence-body' }, [
      el('h2', {
        id: 'companion-evidence-title',
        class: 'companion-evidence-title',
        text: say(`evidence.title.${shown.origin}`),
      }),
      ...body(shown),
    ]),
    el('div', { class: 'companion-rail-foot companion-evidence-foot' }, [back]),
  ]);
  return { root, back };
}

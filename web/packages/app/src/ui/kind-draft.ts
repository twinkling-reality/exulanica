/**
 * A new kind of place, drafted from a person's words (`POST /worlds/kinds/drafts`, then
 * `GET /worlds/kinds/drafts/{draft_id}` at the interval each answer names), shown in Create a
 * world's right column when its last card is chosen (`./world-recipes.ts`).
 *
 * The route answers at once and never waits on the model, so the page follows the draft: while it
 * drafts it says so with the time the server counts (`elapsed_seconds`, never the page's own
 * clock), and a person may leave; ready hands the kept kind to the panel, which lists and chooses
 * it; refused says why in two sentences, the check's own sentence inside. A refusal that is not the
 * drafted kind's is said in the server's closed list's words (`drafting.refusals`), and one no
 * check refused (the drafter gave up first) without the drafter's sentence, which only repeats the
 * page's. The words stay in the field after a refusal: the server forgets them once a draft ends.
 */

import { ApiError } from '@exulanica/graph-client';
import type { KindDraft, KindRefusal, WorldKind } from '../world-kinds-api.js';
import { fill, say } from './copy.js';
import { el } from './dom.js';
import { problemSentence } from './words/problems.js';

/** The drafted kind's own refusal; every other code is the closed list's. */
const NOT_DRAFTED = 'kind_not_drafted';
/** Polls that may fail in a row before the page says so and stops following. */
const POLL_FAILURES = 3;

export interface KindDraftPanel {
  readonly root: HTMLElement;
  /** Follow a draft already running, such as one found when the panel opened. */
  follow(draft: KindDraft): void;
  /** Put focus in the field, or on the drafting words while a draft runs. */
  focus(): void;
}

/** A span of seconds in words: "45 seconds", "1 minute", "2 minutes 5 seconds". */
export function elapsedWords(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  const secondWords = seconds === 1 ? say('worldKinds.second') : fill('worldKinds.seconds', { count: String(seconds) });
  if (minutes === 0) return secondWords;
  const minuteWords = minutes === 1 ? say('worldKinds.minute') : fill('worldKinds.minutes', { count: String(minutes) });
  return seconds === 0 ? minuteWords : `${minuteWords} ${secondWords}`;
}

export function buildKindDraft(options: {
  readonly start: (description: string) => Promise<KindDraft>;
  readonly read: (draftId: string) => Promise<KindDraft>;
  /** The server's closed list of draft refusals, each with its meaning. */
  readonly refusals: () => readonly KindRefusal[];
  /** The longest description the server reads. */
  readonly maximumCharacters: number;
  /** A draft became ready: the panel lists its kind and chooses it. */
  readonly onReady: (kind: WorldKind, modelName: string | null) => void;
  /** Whether a draft runs now, so the card can say so. */
  readonly onRunning: (running: boolean) => void;
  /** Escape in the field: focus leaves it, so the next Escape closes the sheet. */
  readonly onLeave: () => void;
  /** Ask again after `ms`; returns a cancel. Tests pass their own. */
  readonly schedule?: (run: () => void, ms: number) => () => void;
}): KindDraftPanel {
  const schedule = options.schedule ?? ((run: () => void, ms: number) => {
    const timer = window.setTimeout(run, ms);
    return () => window.clearTimeout(timer);
  });
  const field = el('textarea', {
    class: 'world-kinds-input', rows: '3', maxlength: String(options.maximumCharacters),
    placeholder: say('worldKinds.placeholder'), 'aria-label': say('worldKinds.field'),
  });
  const draft = el('button', { type: 'button', class: 'world-kinds-draft', text: say('worldKinds.draft'), disabled: true });
  const status = el('p', { class: 'world-kinds-status', role: 'status', 'aria-live': 'polite', tabindex: '-1' });
  const seeIt = el('button', { type: 'button', class: 'world-kinds-see', text: say('worldKinds.seeIt'), hidden: true });
  const root = el('div', { class: 'world-kinds-new' }, [
    el('label', { class: 'world-kinds-label', text: say('worldKinds.field') }),
    field,
    draft,
    status,
    seeIt,
  ]);

  let following: string | null = null;
  let cancel: (() => void) | null = null;
  let failures = 0;

  const meaning = (code: string): string | null =>
    options.refusals().find((refusal) => refusal.code === code)?.meaning ?? null;

  const reflect = (): void => {
    draft.disabled = following !== null || field.value.trim() === '';
    field.readOnly = following !== null;
  };

  const stop = (words: string): void => {
    cancel?.();
    cancel = null;
    following = null;
    status.textContent = words;
    options.onRunning(false);
    reflect();
  };

  const show = (answer: KindDraft): void => {
    if (answer.state === 'drafting') {
      status.textContent = fill('worldKinds.drafting', { elapsed: elapsedWords(answer.elapsedSeconds) });
      return;
    }
    if (answer.state === 'ready' && answer.kind !== null) {
      stop('');
      field.value = '';
      reflect();
      options.onReady(answer.kind, answer.modelName);
      return;
    }
    const refusal = answer.refusal;
    if (refusal === null) {
      stop(fill('worldKinds.stopped', { meaning: meaning('kind_draft_failed') ?? '' }).trim());
    } else if (refusal.code === NOT_DRAFTED) {
      // The check's own sentence says why; where no check refused, the drafter's sentence would
      // only repeat the first, so the page says its two sentences alone.
      stop(refusal.check === null ? say('worldKinds.refused.unchecked') : fill('worldKinds.refused', { sentence: refusal.detail }));
    } else {
      stop(fill('worldKinds.stopped', { meaning: meaning(refusal.code) ?? refusal.detail }));
    }
  };

  const poll = (draftId: string, afterSeconds: number): void => {
    cancel?.();
    cancel = schedule(() => {
      cancel = null;
      // A sheet closed meanwhile stops following; the draft goes on, and a return finds it.
      if (!root.isConnected || following !== draftId) return;
      void options.read(draftId).then((answer) => {
        if (following !== draftId) return;
        failures = 0;
        show(answer);
        if (answer.state === 'drafting') poll(draftId, answer.pollAfterSeconds ?? afterSeconds);
      }, (error: unknown) => {
        if (following !== draftId) return;
        if (error instanceof ApiError && error.status === 404) {
          stop(say('worldKinds.lost'));
          return;
        }
        failures += 1;
        if (failures >= POLL_FAILURES) stop(problemSentence(error));
        else poll(draftId, afterSeconds);
      });
    }, afterSeconds * 1000);
  };

  const follow = (answer: KindDraft): void => {
    seeIt.hidden = true;
    if (answer.state !== 'drafting') {
      show(answer);
      return;
    }
    following = answer.draftId;
    failures = 0;
    if (answer.description !== '') field.value = answer.description;
    options.onRunning(true);
    reflect();
    show(answer);
    poll(answer.draftId, answer.pollAfterSeconds ?? 1);
  };

  let busyDraft: string | null = null;
  seeIt.addEventListener('click', () => {
    if (busyDraft === null) return;
    const id = busyDraft;
    void options.read(id).then(follow, (error: unknown) => {
      status.textContent = error instanceof ApiError && error.status === 404 ? say('worldKinds.lost') : problemSentence(error);
    });
  });

  const send = (): void => {
    const words = field.value.trim();
    if (words === '' || following !== null) return;
    draft.disabled = true;
    seeIt.hidden = true;
    status.textContent = '';
    void options.start(words).then(follow, (error: unknown) => {
      reflect();
      if (!(error instanceof ApiError)) {
        status.textContent = problemSentence(error);
        return;
      }
      if (error.code === 'kind_draft_busy') {
        status.textContent = say('worldKinds.busy');
        const mine = error.extensions['draft_id'];
        busyDraft = typeof mine === 'string' ? mine : null;
        seeIt.hidden = busyDraft === null;
        return;
      }
      if (error.code === 'kind_draft_capacity') {
        status.textContent = say('worldKinds.capacity');
        return;
      }
      status.textContent = meaning(error.code) ?? problemSentence(error);
    });
  };

  field.addEventListener('input', reflect);
  draft.addEventListener('click', send);
  // Enter drafts and Shift with Enter starts a new line; Escape leaves the field first.
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.isComposing) {
      event.preventDefault();
      send();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      options.onLeave();
    }
  });

  return {
    root,
    follow,
    focus() {
      (following === null ? field : status).focus({ preventScroll: true });
    },
  };
}

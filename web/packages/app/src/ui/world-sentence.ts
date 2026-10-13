/**
 * One sentence makes a world (`GET /worlds/drafts`, `POST /worlds/drafts`, then
 * `GET /worlds/drafts/{draft_id}` at the interval each answer names): the one box Create a world
 * shows where the server offers drafting.
 *
 * Before anything is typed the box says, from the server's own offer, what making a world may
 * spend: the most times it asks a model, and how many of this hour's starts are left. The press
 * cannot be reached before that line is shown. Where a start would be refused now (the hour's
 * starts used up, the allowance spent, as many worlds held as may be) the box says so at once,
 * and a draft of the person's own that is still running is picked up where it is. A refusal that
 * passes never leaves the box alone with a dead press: where no draft can be started now, one
 * press goes to the recipes, which ask no model.
 *
 * A person says the world they want and presses once. The route answers at once, so the page
 * follows the draft and says which step it is at with the time the server counts (never the
 * page's own clock): working out how to make it, drafting, making. Ready shows the world's title,
 * what is in it, what was taken from the words for its look and its setting beside the words
 * that chose it, and what the words asked for that is not in it yet, each from the answer, with
 * one press to open it. Refused says why in the server's closed list's words, with the check's
 * own sentence where a check refused, and the words stay in the field: the server keeps none of
 * a refused draft's. No kind, preset or value is shown on the way. One plain line says what
 * happens to the words.
 */

import { ApiError } from '@exulanica/graph-client';
import type { SavedWorldEntry } from '../world-entry-api.js';
import type { WorldDraftOffer, WorldMakingDraft, WorldMakingMemory, WorldMakingStart } from '../world-making-api.js';
import { fill, say } from './copy.js';
import { el, commandAction } from './dom.js';
import { elapsedWords } from './kind-draft.js';
import { problemSentence } from './words/problems.js';

/** Polls that may fail in a row before the page says so and stops following. */
const POLL_FAILURES = 3;

export interface WorldSentencePanel {
  readonly root: HTMLElement;
  /** Put focus in the field, or on the words that say where a running draft has got to. */
  focus(): void;
}

/** The labels of what was made, each once, in the order made: "farmhouse, barn, duck pond". */
export function madeWords(draft: WorldMakingDraft): string {
  return [...new Set(draft.made.map((part) => part.label))].join(', ');
}

const quoted = (words: readonly string[]): string => words.map((phrase) => `\u201c${phrase}\u201d`).join(', ');

/**
 * What the job took from the words for how the world is drawn and where it stands, each beside
 * the person's own words that chose it, and where it is changed; empty where it took nothing.
 */
export function takenWords(draft: WorldMakingDraft): string {
  const said: string[] = [];
  if (draft.look !== null) said.push(fill('worldSentence.taken.look', { look: draft.look.title, words: quoted(draft.look.words) }));
  if (draft.setting !== null) {
    said.push(fill('worldSentence.taken.setting', {
      parts: draft.setting.parts.map((part) => part.title).join(', '), words: quoted(draft.setting.words),
    }));
  }
  return said.length === 0 ? '' : [...said, say('worldSentence.taken.change')].join(' ');
}

/** What a draft may spend, in one line, from the offer's own figures. */
export function spendWords(offer: WorldDraftOffer): string {
  const ceiling = offer.operation === null ? say('worldSentence.spend.legacy')
    : fill('worldSentence.spend.ceiling', { maximum: offer.operation.maximumUsd });
  return `${ceiling} ${fill('worldSentence.spend', {
    calls: String(offer.callsAtMost), left: String(offer.starts.left), anHour: String(offer.starts.anHour),
  })}`;
}

/** Why a start would be refused now, in the page's words where it has them, else the server's. */
export function refusedNowWords(offer: WorldDraftOffer): string {
  if (offer.code === 'kind_draft_limit') {
    const minutes = Math.max(1, Math.ceil((offer.starts.retryAfterSeconds ?? 60) / 60));
    return fill('worldSentence.limit', { minutes: String(minutes) });
  }
  if (offer.code === 'kind_draft_busy') return say('worldSentence.busy.other');
  const meaning = offer.refusals.find((one) => one.code === offer.code)?.meaning ?? offer.detail ?? '';
  return fill('worldSentence.notNow', { meaning }).trim();
}

export function buildWorldSentence(options: {
  /** The offer the sheet was opened on. */
  readonly offer: WorldDraftOffer;
  /** Read the offer again: after a draft ends, the hour's starts have changed. */
  readonly readOffer: () => Promise<WorldDraftOffer>;
  readonly start: (description: string, submission?: WorldMakingStart) => Promise<WorldMakingDraft>;
  readonly memory?: WorldMakingMemory;
  readonly read: (draftId: string) => Promise<WorldMakingDraft>;
  /** Open the world that was made. */
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  /** Show the recipes in place of the box: offered where no draft can be started now. */
  readonly recipes?: () => void;
  /** Workshop commands use modified Enter and keep lifecycle actions at the bottom. */
  readonly workshop?: { readonly onReturn: () => void; readonly configure: () => void };
  /** Ask again after `ms`; returns a cancel. Tests pass their own. */
  readonly schedule?: (run: () => void, ms: number) => () => void;
}): WorldSentencePanel {
  const schedule = options.schedule ?? ((run: () => void, ms: number) => {
    const timer = window.setTimeout(run, ms);
    return () => window.clearTimeout(timer);
  });
  const field = el('textarea', {
    class: 'world-description-input world-sentence-input', rows: '3', maxlength: String(options.offer.descriptionCharacters),
    placeholder: say('worldSentence.placeholder'), 'aria-label': say('worldSentence.field'),
  });
  const spend = el('p', { class: 'world-sentence-spend' });
  const make = el('button', { type: 'button', class: 'world-description-draft world-sentence-make', text: say('worldSentence.make'), disabled: true });
  const status = el('p', { class: 'world-description-status world-sentence-status', role: 'status', 'aria-live': 'polite', tabindex: '-1' });
  const madeLine = el('p', { class: 'world-sentence-made', hidden: true });
  const leftOutLine = el('p', { class: 'world-description-not-supported world-sentence-left-out', hidden: true });
  const takenLine = el('p', { class: 'world-sentence-taken', hidden: true });
  const open = el('button', { type: 'button', class: 'world-description-use world-sentence-open', text: say('worldSentence.open'), hidden: true });
  const follow = el('button', { type: 'button', class: 'world-description-use world-sentence-follow', text: say('worldSentence.follow'), hidden: true });
  const toRecipes = el('button', { type: 'button', class: 'world-description-use world-sentence-recipes', text: say('worldSentence.recipes'), hidden: true });
  // The Describe it panel's own structure and classes, so the box is drawn as that panel is: a
  // heading, the line that says what happens to the words, the field, what a draft may spend, the
  // press, the status and what came of it.
  const root = el('section', { class: 'world-description world-sentence', 'aria-label': say('worldSentence.field') }, [
    el('h3', { text: say('worldSentence.field') }),
    el('p', { class: 'world-sentence-notice', text: say('worldSentence.notice') }),
    field,
    spend,
    make,
    status,
    el('div', { class: 'world-description-result' }, [follow, madeLine, takenLine, leftOutLine, open, toRecipes]),
  ]);

  let configureControl: HTMLButtonElement | null = null;
  if (options.workshop !== undefined) {
    const workshop = options.workshop;
    root.classList.add('world-creation-task');
    make.classList.add('entry-command');
    open.classList.add('entry-command');
    field.removeAttribute('placeholder');
    field.setAttribute('aria-label', 'Describe your world');
    field.rows = 2;
    const resize = (): void => {
      field.style.height = 'auto';
      field.style.height = `${Math.min(240, Math.max(80, field.scrollHeight))}px`;
    };
    field.addEventListener('input', resize);
    const returnButton = el('button', { type: 'button', class: 'entry-command', 'aria-keyshortcuts': 'Escape' }, commandAction('Esc', 'Your worlds'));
    returnButton.addEventListener('click', workshop.onReturn);
    const configure = el('button', { type: 'button', class: 'world-creation-configure entry-command', text: 'AI connection' });
    configure.replaceChildren(...commandAction(/Mac/.test(navigator.platform) ? '⌘ ↵' : 'Ctrl ↵', 'AI connection'));
    configure.addEventListener('click', workshop.configure);
    configure.hidden = options.offer.offered || options.offer.runningDraftId !== null;
    configureControl = configure;
    make.replaceChildren(...commandAction(/Mac/.test(navigator.platform) ? '⌘ ↵' : 'Ctrl ↵', 'Create world'));
    open.replaceChildren(...commandAction('↵', 'Open world'));
    root.replaceChildren(
      el('div', { class: 'world-creation-content' }, [
        el('h1', { text: 'Create a world' }),
        el('label', { for: 'world-creation-description', text: 'Describe your world' }),
        field,
        spend,
        el('details', { class: 'world-creation-disclosure' }, [el('summary', { text: 'Creation details' }), el('p', { text: say('worldSentence.notice') })]),
        status,
        el('div', { class: 'world-creation-result' }, [follow, madeLine, takenLine, leftOutLine]),
      ]),
      el('footer', { class: 'world-creation-commands' }, [returnButton, configure, make, open]),
    );
    field.id = 'world-creation-description';
    resize();
  }

  const memory = options.memory ?? { pending: null };
  let latestOffer = options.offer;
  let following: string | null = null;
  let cancel: (() => void) | null = null;
  let failures = 0;
  let made: SavedWorldEntry | null = null;
  let busyDraft: string | null = null;
  // Whether a start would be taken now, by the last offer read; false until its line is shown.
  let offered = false;
  // A start that was sent and has not answered: Enter or a second press sends no other.
  let sending = false;

  const reflect = (): void => {
    make.disabled = memory.pending !== null || !offered || sending || following !== null || busyDraft !== null || field.value.trim() === '';
    field.readOnly = sending || memory.pending !== null || following !== null || busyDraft !== null;
    follow.disabled = sending;
  };

  const clearResult = (): void => {
    made = null;
    for (const line of [madeLine, takenLine, leftOutLine, open, follow]) line.hidden = true;
  };

  /**
   * Show what a draft may spend; where a start would be refused now, say why before a word: in
   * the status as the sheet opens, and in the line of what is left once a draft has ended, whose
   * own words stay in the status.
   */
  const offer = (answer: WorldDraftOffer, announce: boolean): void => {
    latestOffer = answer;
    // A draft of the person's own still running is offered, since following it is what is next.
    offered = answer.offered || answer.runningDraftId !== null;
    spend.textContent = offered || announce ? spendWords(answer) : `${spendWords(answer)} ${refusedNowWords(answer)}`;
    if (!offered && announce && options.workshop === undefined) status.textContent = refusedNowWords(answer);
    // Where no draft can be started now, the recipes are one press away.
    toRecipes.hidden = offered || options.recipes === undefined;
    if (configureControl !== null) {
      const needsSetup = answer.code === 'provider_credential_absent';
      if (!offered && needsSetup && announce) status.textContent = 'AI creation is not enabled here. You can still open and edit saved worlds.';
      configureControl.hidden = offered || made !== null || !needsSetup;
      if (!offered && !needsSetup && announce) status.textContent = refusedNowWords(answer);
      make.hidden = !offered || made !== null;
      const details = root.querySelector<HTMLElement>('.world-creation-disclosure');
      if (details !== null) details.hidden = !offered;
    }
    reflect();
  };

  const refresh = (): void => {
    // The words of how the draft ended stay; only the line of what is left moves.
    void options.readOffer().then((answer) => {
      if (following === null && memory.pending === null) offer(answer, false);
    }, () => undefined);
  };

  const stop = (words: string): void => {
    cancel?.();
    cancel = null;
    following = null;
    status.textContent = words;
    reflect();
  };

  const show = (answer: WorldMakingDraft): void => {
    const elapsed = { elapsed: elapsedWords(answer.elapsedSeconds) };
    if (answer.state === 'queued' || answer.state === 'choosing' || answer.state === 'drafting' || answer.state === 'making') {
      status.textContent = `${answer.recovered ? `${say('worldSentence.recovered')} ` : ''}${fill(`worldSentence.${answer.state}`, elapsed)}`;
      return;
    }
    memory.pending = null;
    if (answer.state === 'ready' && answer.entry !== null) {
      stop(fill('worldSentence.ready', { title: answer.entry.title }));
      made = answer.entry;
      const parts = madeWords(answer);
      madeLine.textContent = parts === '' ? '' : fill('worldSentence.made', { parts });
      madeLine.hidden = parts === '';
      leftOutLine.textContent = fill('worldSentence.leftOut', { phrases: answer.leftOut.map((phrase) => `“${phrase}”`).join(', ') });
      leftOutLine.hidden = answer.leftOut.length === 0;
      takenLine.textContent = takenWords(answer);
      takenLine.hidden = takenLine.textContent === '';
      open.hidden = false;
      if (options.workshop !== undefined) make.hidden = true;
      field.value = '';
      field.dispatchEvent(new Event('input', { bubbles: true }));
      reflect();
      open.focus({ preventScroll: true });
      refresh();
      return;
    }
    const refusal = answer.refusal;
    const meaning = answer.refusals.find((one) => one.code === refusal?.code)?.meaning ?? '';
    const detail = refusal?.detail ?? '';
    // A check's own sentence says why and is said after the list's; where no check refused, the
    // other sentence only repeats the list's, and is said only where the list has no words.
    stop(meaning !== '' && detail !== '' && detail !== meaning && refusal?.check != null
      ? fill('worldSentence.refused.detail', { meaning, detail })
      : fill('worldSentence.refused', { meaning: meaning === '' ? detail : meaning }).trim());
    refresh();
  };

  const poll = (draftId: string, afterSeconds: number): void => {
    cancel?.();
    cancel = schedule(() => {
      cancel = null;
      // A sheet closed meanwhile stops following; the draft goes on, and the world is saved.
      if (!root.isConnected || following !== draftId) return;
      void options.read(draftId).then((answer) => {
        if (following !== draftId) return;
        checkIdentity(answer, draftId);
        failures = 0;
        show(answer);
        if (answer.pollAfterSeconds !== null) poll(draftId, answer.pollAfterSeconds);
      }).catch((error: unknown) => {
        if (following !== draftId) return;
        if (error instanceof ApiError && error.status === 404) {
          busyDraft = draftId;
          stop(say('worldSentence.lost'));
          follow.textContent = 'Check progress';
          follow.hidden = false;
          return;
        }
        failures += 1;
        if (failures >= POLL_FAILURES) {
          busyDraft = draftId;
          stop(say('worldSentence.progress.interrupted'));
          follow.textContent = 'Check progress';
          follow.hidden = false;
        }
        else poll(draftId, afterSeconds);
      });
    }, afterSeconds * 1000);
  };

  const checkIdentity = (answer: WorldMakingDraft, draftId?: string): void => {
    const pending = memory.pending;
    const expected = pending?.kind === 'sending' ? pending.submission?.idempotencyKey
      : pending?.requestId;
    if ((draftId !== undefined && answer.draftId !== draftId)
      || (expected != null && answer.requestId !== expected)) throw new TypeError('The server returned an invalid world draft identity.');
  };

  const followDraft = (answer: WorldMakingDraft): void => {
    checkIdentity(answer);
    memory.pending = { kind: 'following', draftId: answer.draftId, requestId: answer.requestId };
    if (answer.operation !== null) spend.textContent = spendWords({ ...latestOffer, operation: answer.operation });
    busyDraft = null;
    clearResult();
    if (answer.pollAfterSeconds === null) {
      show(answer);
      return;
    }
    following = answer.draftId;
    failures = 0;
    if (answer.description !== '') field.value = answer.description;
    reflect();
    show(answer);
    poll(answer.draftId, answer.pollAfterSeconds);
  };

  const lost = (error: unknown): string => (
    error instanceof ApiError && error.status === 404 ? say('worldSentence.lost') : problemSentence(error)
  );

  const uncertain = (): void => {
    status.textContent = say(memory.pending?.kind === 'sending' && memory.pending.submission === null
      ? 'worldSentence.request.legacy' : 'worldSentence.request.unknown');
    follow.textContent = say('worldSentence.request.check');
    follow.hidden = false;
    reflect();
  };

  const dispatch = (): void => {
    const attempt = memory.pending;
    if (attempt?.kind !== 'sending' || sending) return;
    sending = true;
    reflect();
    const request = attempt.submission === null ? options.start(attempt.description)
      : options.start(attempt.description, attempt.submission);
    void request.then((answer) => {
      sending = false;
      // Another open panel may already have followed this same request.
      checkIdentity(answer);
      followDraft(answer);
    }).catch((error: unknown) => {
      sending = false;
      // These admission refusals establish that this request did not dispatch.
      const refused = error instanceof ApiError && [
        'world_draft_price_expired', 'world_draft_operation_changed', 'kind_draft_busy',
        'kind_draft_limit', 'kind_draft_capacity',
      ].includes(error.code);
      if (!refused) { uncertain(); return; }
      if (memory.pending === attempt) memory.pending = null;
      if (error instanceof ApiError && error.code === 'kind_draft_busy') {
        const mine = error.extensions['draft_id'];
        busyDraft = typeof mine === 'string' ? mine : null;
        status.textContent = say(busyDraft === null ? 'worldSentence.busy.other' : 'worldSentence.busy');
        follow.hidden = busyDraft === null;
      } else {
        status.textContent = error instanceof ApiError && error.code === 'kind_draft_capacity'
          ? say('worldSentence.capacity') : problemSentence(error);
      }
      reflect();
      refresh();
    });
  };

  const send = (): void => {
    const words = field.value.trim();
    if (words === '' || memory.pending !== null || following !== null || busyDraft !== null || !offered || sending) return;
    const quote = latestOffer.operation;
    if (quote !== null && quote.expiresAt <= Date.now()) {
      sending = true;
      reflect();
      void options.readOffer().then(answer => {
        offer(answer, false);
        status.textContent = say('worldSentence.quote.updated');
      }, error => { status.textContent = problemSentence(error); }).finally(() => { sending = false; reflect(); });
      return;
    }
    clearResult();
    status.textContent = '';
    memory.pending = { kind: 'sending', description: words, submission: quote === null ? null : Object.freeze({
      idempotencyKey: crypto.randomUUID(), operation: quote, maximumUsd: quote.maximumUsd,
    }) };
    dispatch();
  };

  follow.addEventListener('click', () => {
    if (sending) return;
    const pending = memory.pending;
    if (pending?.kind === 'sending') {
      if (pending.submission !== null) { dispatch(); return; }
      // A legacy server cannot deduplicate a POST. Recover through its own running draft only.
      sending = true;
      reflect();
      void options.readOffer().then(async answer => {
        if (answer.runningDraftId === null) { uncertain(); return; }
        const draft = await options.read(answer.runningDraftId);
        checkIdentity(draft, answer.runningDraftId);
        followDraft(draft);
      }).catch(() => uncertain()).finally(() => { sending = false; reflect(); });
      return;
    }
    const id = busyDraft ?? (pending?.kind === 'following' ? pending.draftId : null);
    if (id === null) return;
    void options.read(id).then(answer => { checkIdentity(answer, id); followDraft(answer); }).catch((error: unknown) => {
      status.textContent = lost(error);
      if (error instanceof ApiError && error.isNotFound) {
        busyDraft = id;
        follow.hidden = false;
        // Keep unknown request identity; a missing read is not proof that no work happened.
        reflect();
      }
    });
  });
  open.addEventListener('click', () => {
    if (made === null) return;
    open.disabled = true;
    void options.open(made).catch((error: unknown) => {
      open.disabled = false;
      status.textContent = problemSentence(error);
    });
  });
  toRecipes.addEventListener('click', () => options.recipes?.());
  field.addEventListener('input', reflect);
  make.addEventListener('click', send);
  // Enter makes the world and Shift with Enter starts a new line.
  field.addEventListener('keydown', (event) => {
    const submit = options.workshop === undefined
      ? !event.shiftKey && !event.metaKey && !event.ctrlKey
      : event.metaKey || event.ctrlKey;
    if (event.key === 'Enter' && submit && !event.isComposing) {
      event.preventDefault();
      if (configureControl !== null && !configureControl.hidden) configureControl.click();
      else send();
    }
  });

  offer(options.offer, true);
  // A draft of the person's own that is still running is followed from where it is.
  const pending = memory.pending;
  if (pending?.kind === 'sending') {
    field.value = pending.description;
    if (pending.submission !== null) spend.textContent = spendWords({ ...latestOffer, operation: pending.submission.operation });
    uncertain();
  }
  const running = pending?.kind === 'following' ? pending.draftId
    : pending?.kind === 'sending' ? null : options.offer.runningDraftId;
  if (running !== null) {
    busyDraft = running;
    memory.pending ??= { kind: 'following', draftId: running, requestId: null };
    reflect();
    void options.read(running).then(answer => { checkIdentity(answer, running); followDraft(answer); }).catch((error: unknown) => {
      status.textContent = lost(error);
      if (!(error instanceof ApiError && error.isNotFound) || memory.pending !== null) {
        busyDraft = running;
        follow.textContent = 'Check progress';
        follow.hidden = false;
        reflect();
      }
      refresh();
    });
  }

  return {
    root,
    focus() {
      (following === null ? field : status).focus({ preventScroll: true });
    },
  };
}

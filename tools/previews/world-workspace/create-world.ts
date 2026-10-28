// Create a world (ROOT's composer mock of 27 October, create-linear.html and making-linear.html): one page over the
// front door, in place of the app's old dialog (seams.mjs, 'Your worlds create'). It reads the offer and takes the
// words in the composer, or starts from a ready world in the strip along the foot, whose current card's picture
// stands behind the page. The making view follows a draft by what the server serves, and a refusal comes back to the
// composer with the words kept. Every Enter starts or says why: one that can start shows the making view at once,
// "Waiting to start" timed from the press, before the start answers; one that cannot says why in the price's place,
// and reads the offer again where it is for want of a price. On ready the made world opens through its opening
// (world-opening.ts), and its arrival shows the made note (contextual-world.ts reads the made handoff). The parts draw
// (world-ui-create.ts); words and key fates are create-words.mjs's and create-steps.mjs's. Esc leaves once, the words
// kept; a draft carries on and waits in Your worlds.
// Where web notes are offered, the composer's "Search the web" asks for them, on until it is pressed: Create first
// asks for notes (POST /worlds/references), shows their steps and the notes, then starts the draft with them, or from
// the words alone where none came, saying why; the price and spend count the notes' two model calls.
import { WorldMakingClient, parseWorldDraftOffer, parseWorldMakingDraft, type WorldDraftOffer, type WorldDraftOperation, type WorldMakingStart } from '../../../web/packages/app/src/world-making-api.ts';
import { WorldKindsClient, type WorldKind } from '../../../web/packages/app/src/world-kinds-api.ts';
import { WorldSpecificationClient, type SpecificationPreset } from '../../../web/packages/app/src/world-specification.ts';
import { cardPicture, readCardPictures } from '../../../web/packages/app/src/ui/card-pictures.ts';
import { accessHeaders, type Credentials } from '../../../web/packages/app/src/config.ts';
import type { SavedWorldEntry, WorldEntryClient } from '../../../web/packages/app/src/world-entry-api.ts';
import { ReferencesClient, referenceFinished, referenceHasNotes, type ReferenceRequest } from '../../../web/packages/app/src/references-api.ts';
import {
  composer, createPage, createTitle, fitQuote, makingSteps, quietCommand, webNotes, worldStrip,
  type Composer, type MakingSteps, type StripCard, type WebNotes, type WorldStrip,
} from './world-ui-create.ts';
import type { Step } from './world-ui.ts';
import {
  CREATE_WORDS, REFUSAL_WORDS, STEP_WORDS, budgetShort, ceilingAmount, madeLine, priceUp, priceUpTo, refusalSpent, refusalWords, spentUpTo,
  stepTime, stoppedLine, sumUsd, webNotesLabel, webTip,
} from './create-words.mjs';
import {
  MADE_HANDOFF_KEY, SHORT_CODE, afterRead, createKey, draftSteps, moveChoice, notesNotUsedLine, notesOutcome, notesSteps, offerState,
  pollDelay, spentOf, startCards, withNotesSpent, wrapStop, writeMade,
} from './create-steps.mjs';
import { openMadeWorld } from './front-door.ts';
import { mountUiScale } from './world-ui.ts';

/** What main.ts holds while Create a world is open (its MakeWorldSurface). */
export interface CreateWorldSurface {
  readonly isConnected: boolean;
  remove(): void;
}

/** The title a Blank world is reopened under: the app's own starter (session-and-geometry.ts). */
const BLANK_TITLE = 'My world';
/** The page's title, which names it; and the sentence in the composer's place, which names the strip under it. */
const TITLE_ID = 'wu-create-title';
const SENTENCE_ID = 'wu-create-sentence';

/** The words typed here, kept across leaving and coming back in this page (N6). */
let keptWords = '';
/** Whether the next draft asks the web for notes first, where they are offered: on until it is pressed (the mock). */
let webOn = true;

/** A served draft read, raw: what draftSteps and spentOf read, and the parsed draft for its entry. */
type RawDraft = Readonly<Record<string, unknown>>;

/** A page's own Tab stops in document order: focusable, enabled, in the Tab order and inside nothing hidden. */
export function tabStops(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')]
    .filter((one) => one.tabIndex >= 0 && !(one as HTMLButtonElement).disabled && one.closest('[hidden]') === null);
}

/** A read with the page's own credentials: its bearer on a person's own install, its session's cookie for a guest. */
async function readRaw(access: Credentials, path: string, signal: AbortSignal): Promise<RawDraft> {
  const response = await fetch(access.baseUrl + path, { headers: { ...accessHeaders(access), Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok) throw Object.assign(new Error('read'), { status: response.status });
  return response.json() as Promise<RawDraft>;
}

/** A refusal's served code, from an error the app's transport throws (ApiError) or none. */
const codeOf = (error: unknown): string | null => {
  const code = (error as { readonly code?: unknown } | null)?.code;
  return typeof code === 'string' && code ? code : null;
};

const element = <K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] => {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
};

interface StartCard { readonly key: string; readonly start: () => Promise<SavedWorldEntry> }

/** A start refused for its price: the quote expired, or the operation it was for changed (N32). */
const PRICE_CODES: readonly string[] = ['world_draft_price_expired', 'world_draft_operation_changed', 'world_draft_bound_too_small'];
/** The page's own mark for a refusal whose new price is higher than the one agreed to, said with its figure (N32). */
const PRICE_UP = 'price_up';
/** A price that cannot be read now (N25), said while the offer is read again. */
const PRICE_UNAVAILABLE = 'world_draft_price_unavailable';
/**
 * How old a held operation sheet may be when a start is sent: the server keeps a quote for 60 s (PRICE_SECONDS in
 * exulanica/api/world_draft_offer.py) and refuses an older one (world_draft_price_expired), so a sheet older than this,
 * by this page's own clock, is read again first.
 */
const FRESH_MS = 45_000;

/**
 * A refusal said in the composer's foot until the words change or the offer is read again, with what was spent;
 * `words` where its sentence carries a figure (a higher price, N32; a draft stopped part way, A1b, whose figures the
 * offer read before it no longer holds, so no price is said beside it).
 */
interface Refusal { readonly code: string; readonly spent: string | null; readonly words?: string; readonly stopped?: true }

/** The making view's parts, drawn once for a making. */
interface MakingFrame {
  readonly quote: HTMLElement;
  readonly steps: MakingSteps;
  /** What was spent, under the steps, once a read states it. */
  readonly spent: HTMLElement;
  /** Under the steps: offline, or a price that cannot be read while it is read again. */
  readonly line: HTMLElement;
  readonly web: WebNotes;
  /** Draws the steps after "Waiting to start" (the notes' and the draft's); with no press, the steps as served. */
  after(steps: readonly Step[]): void;
  /** Stops the waiting step's clock. */
  stop(): void;
}

/** What the notes phase hands the draft it starts: its steps, the most the notes may add and the searches they sent. */
interface NotesMade { readonly steps: readonly Step[]; readonly mostUsd: string; readonly searches: number }

/**
 * Opens Create a world over the front door, or returns null where this page has no credentials or
 * saved worlds. `onClose` hears it go (Esc, Your worlds, or a world opened).
 */
export function mountCreateWorld({ root, credentials, entries, onClose }: {
  readonly root: HTMLElement;
  readonly credentials: Credentials | null;
  readonly entries: WorldEntryClient | null;
  readonly onClose: () => void;
}): CreateWorldSurface | null {
  if (credentials === null || entries === null) return null;
  const making = new WorldMakingClient(credentials);
  const lifetime = new AbortController();
  const signal = lifetime.signal;
  const page = createPage({ labelledBy: TITLE_ID });
  // Over the front door and the app's shell, in the workspace's own tokens.
  const host = document.createElement('div');
  host.className = 'wu-root wu-create-host';
  host.append(page.root);
  (root.ownerDocument.body ?? document.body).append(host);
  mountUiScale(host, signal);
  let closed = false;
  const close = (): void => {
    if (closed) return;
    closed = true;
    lifetime.abort();
    host.remove();
    // Left while a draft runs: it carries on, and its card waits in Your worlds (N12).
    if (form === 'creating') void showBeingMade(root, credentials);
    onClose();
  };
  page.corner.append(quietCommand({ onPress: close, place: 'corner' }));

  let offer: WorldDraftOffer | null = null;
  let rawOffer: RawDraft | null = null;
  let offerFailures = 0, offerOffline = false, priceRetries = 0;
  // When the offer held was read, by this page's clock (FRESH_MS).
  let offerAt = 0;
  // An offer read on its way, and the read again waiting its turn: one at a time.
  let reading = false, again = 0;
  let form: 'create' | 'creating' = 'create';
  let busy = false;
  // The submission a press of Create sends; the same one again on a retry of the same words, so a
  // start whose answer was lost is never a second draft (the idempotency key).
  let submission: { readonly words: string; readonly referenceId: string | null; readonly sent: WorldMakingStart } | null = null;
  let refusal: Refusal | null = null;
  // A press of Create that could not start, where the offer's state alone does not say why: the offer not read yet,
  // or no words; said until the words change.
  let asked = false;
  // The reason said last in the composer's foot, so the same reason pressed again is said again.
  let saying: string | null = null;
  // The composer while the page before Create shows one; else the sentence in its place.
  let shown: Composer | null = null;
  let sentence: HTMLElement | null = null;
  let strip: WorldStrip | null = null;
  // The current card, by its key, once a person moved it; until then the first.
  let chosenKey: string | null = null;
  // Blank is there from the start; the served cards join it when they are read.
  let cards: readonly StartCard[] = [{ key: 'blank', start: () => entries.ensureStarter(BLANK_TITLE) }];
  // Made when notes are first asked for, so a page that never asks them builds no client for them.
  let referencesClient: ReferencesClient | null = null;
  const references = (): ReferencesClient => (referencesClient ??= new ReferencesClient(credentials));
  /** The notes this offer prices, where they are offered here: the planner's limit and the most they add. */
  const notesOffered = (): { readonly searches: number; readonly mostUsd: string } | null => {
    const notes = offer?.notes ?? null;
    return notes !== null && notes.offered && notes.maximumUsd !== null ? { searches: notes.searchesAtMost, mostUsd: notes.maximumUsd } : null;
  };
  /** The most a world made now may spend: the draft's, and the notes' where the toggle asks for them (item 2). */
  const mostOf = (operation: WorldDraftOperation): string => {
    const notes = notesOffered();
    return notes !== null && webOn ? sumUsd(operation.maximumUsd, notes.mostUsd) : operation.maximumUsd;
  };

  /** Where words make no world here (N7, N24, N25, N31, N34), the sentence in the composer's place; else null. */
  const sentenceFor = (): string | null => {
    const state = offerState(rawOffer);
    return state.page === 'no-model' ? CREATE_WORDS.noModel : state.page === 'budget' ? CREATE_WORDS.budgetSpent
      : state.page === 'paused' ? CREATE_WORDS.spendingPaused : state.page === 'short' ? budgetShort(state.stepUsd, state.leftUsd)
        : state.page === 'not-offered' ? CREATE_WORDS.notOffered : null;
  };

  /**
   * The composer's foot from what is read so far: the price, and before it why Create cannot start, where it cannot.
   * A refusal of the offer itself stands alone, with no price beside it; a price that cannot be read says so while it
   * is read again (N25).
   */
  const foot = (): void => {
    if (shown === null) return;
    const words = shown.field.value.trim();
    const state = offerState(rawOffer);
    const operation = state.page === 'offered' ? offer?.operation ?? null : null;
    let why: string | null = null, price: string | null = null;
    if (rawOffer === null) why = offerOffline ? CREATE_WORDS.offline : asked ? CREATE_WORDS.loading : null;
    else if (state.page === 'refused') why = refusalWords(state.code);
    else if (operation === null) why = REFUSAL_WORDS.priceUnavailable;
    else {
      if (refusal !== null) why = refusal.words ?? [refusalWords(refusal.code), refusal.spent].filter(Boolean).join(' ');
      else if (asked && !words) why = CREATE_WORDS.describeIt;
      if (!refusal?.stopped) price = priceUpTo(mostOf(operation), offer?.leftUsd ?? null);
    }
    const notes = notesOffered();
    shown.offerWeb(notes === null ? null : { on: webOn, tip: webTip(notes.searches, notes.mostUsd), onChange: (on) => { webOn = on; foot(); } });
    saying = why;
    shown.say(why, price);
    shown.ready(operation !== null && words.length > 0);
    shown.field.maxLength = offer?.descriptionCharacters ?? 1000;
  };

  /** The strip along the foot, the current card kept by its key, the focus kept on it where it was. */
  const drawStrip = (): void => {
    if (form !== 'create') return;
    const offered = startCards([...cardWords.values()], []) as readonly StripCard[];
    const hadFocus = strip?.root.contains(document.activeElement) ?? false;
    let building = true;
    const next = worldStrip(offered, {
      onStart: (key) => { void startFrom(key); },
      // The picture behind follows the current card; a person's move is kept by its key.
      onChoose: (card) => { page.picture(card.picture); if (!building) chosenKey = card.key; },
      ...(sentence === null ? {} : { labelledBy: SENTENCE_ID }),
    });
    const at = chosenKey === null ? 0 : offered.findIndex((card) => card.key === chosenKey);
    next.choose(Math.max(0, at), hadFocus);
    building = false;
    strip = next;
    page.foot.replaceChildren(next.root);
  };

  /** The page before Create, from the offer read so far: the composer, or the sentence where words make no world here. */
  const drawCreate = (): void => {
    const wasCreating = form === 'creating';
    form = 'create';
    page.form('create');
    const words = sentenceFor();
    if (words === null && (shown === null || wasCreating)) {
      sentence = null;
      shown = composer({ onInput: (typed) => {
        keptWords = typed;
        asked = false;
        if (refusal !== null && refusal.code !== 'world_draft_price_expired' && refusal.code !== PRICE_UP && refusal.code !== PRICE_UNAVAILABLE) {
          // After a draft stopped part way the offer read before it is out of date (A1b): read again for what is left.
          const stale = refusal.stopped === true;
          refusal = null;
          if (stale) void readOffer();
        }
        foot();
      }, onCreate: create });
      page.column.replaceChildren(createTitle(CREATE_WORDS.title, TITLE_ID), shown.root);
      // On the page, so the field's height fits the words kept.
      shown.set(keptWords);
    } else if (words !== null && (sentence?.textContent !== words || wasCreating)) {
      shown = null;
      sentence = element('p', 'wu-create-sentence', words);
      sentence.id = SENTENCE_ID;
      page.column.replaceChildren(createTitle(CREATE_WORDS.title, TITLE_ID), sentence);
    }
    foot();
    drawStrip();
  };

  // The cards: the server's presets and kinds as served, one per kind (its first preset), Blank last.
  const cardWords = new Map<string, { readonly key: string; readonly name: string; readonly picture: string | null }>();
  const readCards = async (): Promise<void> => {
    const [presets, kinds, pictures] = await Promise.all([
      new WorldSpecificationClient(credentials).specification().then((spec) => spec.presets, () => [] as readonly SpecificationPreset[]),
      new WorldKindsClient(credentials).library().then((library) => library.kinds, () => [] as readonly WorldKind[]),
      readCardPictures(),
    ]);
    const found: StartCard[] = [];
    for (const preset of presets) {
      const key = `recipe:${preset.key}`;
      cardWords.set(key, { key, name: preset.label, picture: cardPicture(pictures, key, { values: preset.values }) });
      found.push({ key, start: () => entries.makeGenerated(preset.key, preset.label, preset.values) });
    }
    for (const kind of kinds) {
      const first = kind.presets[0];
      if (!first) continue;
      const key = `kind:${kind.kind}`;
      cardWords.set(key, { key, name: kind.label, picture: cardPicture(pictures, key, { version: kind.version, sha256: kind.sha256 }) });
      found.push({ key, start: () => entries.makeOfKind(kind, first.key, kind.label, first.values) });
    }
    cards = [...found, ...cards.filter((card) => card.key === 'blank')];
    if (!signal.aborted) drawStrip();
  };

  /** Reads the offer (raw for its codes, parsed for its sealed quote), quietly again on failure (L14). */
  const readOffer = async (): Promise<void> => {
    if (reading || signal.aborted) return;
    reading = true;
    window.clearTimeout(again);
    try {
      const raw = await readRaw(credentials, '/worlds/drafts', signal);
      offer = parseWorldDraftOffer(raw);
      rawOffer = raw;
      offerAt = Date.now();
      offerFailures = 0; offerOffline = false;
    } catch {
      reading = false;
      if (signal.aborted) return;
      const next = afterRead(offerFailures, false, 0);
      offerFailures = next.failed;
      if (next.offline && !offerOffline) { offerOffline = true; foot(); }
      again = window.setTimeout(() => { void readOffer(); }, next.retryMs);
      return;
    }
    reading = false;
    if (signal.aborted) return;
    const state = offerState(rawOffer);
    if (state.page === 'following') { if (form === 'create') void follow(state.draftId, keptWords, makingFrame(keptWords, null)); return; }
    // A making on show answers by its own reads.
    if (form !== 'create') return;
    drawCreate();
    // A price that cannot be read now: the offer is read again quietly, with L14's backoff (N25).
    if ((state.page === 'refused' && state.code === PRICE_UNAVAILABLE) || (state.page === 'offered' && offer?.operation == null)) {
      const next = afterRead(priceRetries, false, 0);
      priceRetries = next.failed;
      again = window.setTimeout(() => { if (form === 'create') void readOffer(); }, next.retryMs);
    } else priceRetries = 0;
  };

  /**
   * Create: an Enter in the composer or a press of its pill. One that can start shows the making view at once, before
   * the start answers (N2); one that cannot says why in the price's place, the same reason again where it is pressed
   * again, and where it is for want of a price reads the offer again. Never silent.
   */
  const create = (): void => {
    if (busy || form !== 'create' || shown === null) return;
    const words = shown.field.value.trim();
    const state = offerState(rawOffer);
    if (state.page !== 'offered' || offer?.operation == null || !words) {
      const was = saying;
      asked = true;
      foot();
      if (saying !== null && saying === was) shown.again();
      shown.field.focus({ preventScroll: true });
      // With no price to start at, a press reads the offer again at once, and starts the quiet backoff over.
      if (rawOffer !== null && ((state.page === 'offered' && offer?.operation == null) || (state.page === 'refused' && state.code === PRICE_UNAVAILABLE))) {
        priceRetries = 0;
        void readOffer();
      }
      return;
    }
    asked = false;
    refusal = null;
    const agreed = offer.operation.maximumUsd;
    const notes = notesOffered();
    if (notes !== null && webOn) void lookUp(words, notes.mostUsd, agreed);
    else void startDraft(words, makingFrame(words, performance.now()), { agreed });
  };

  /**
   * The making view (the mock's): "Creating your world", the words quoted (or a card's name), the steps, what was
   * spent, and the web notes beside them. With `pressed`, "Waiting to start" leads the steps, timed from the press
   * until the first step after it shows.
   */
  const makingFrame = (words: string, pressed: number | null, heading: string | null = null): MakingFrame => {
    form = 'creating';
    page.form('creating');
    shown = null; sentence = null; strip = null;
    page.foot.replaceChildren();
    const quote = element('p', 'wu-making-quote', heading ?? (words ? `“${words}”` : ''));
    const steps = makingSteps();
    const spent = element('p', 'wu-making-spent'), line = element('p', 'wu-making-spent');
    for (const status of [spent, line]) { status.setAttribute('role', 'status'); status.hidden = true; }
    const web = webNotes();
    const left = element('div');
    left.append(steps.root, spent, line);
    const grid = element('div', 'wu-making');
    grid.append(left, web.root);
    page.column.replaceChildren(createTitle(CREATE_WORDS.creating, TITLE_ID), quote, grid);
    fitQuote(quote);
    page.root.focus({ preventScroll: true });
    let latest: readonly Step[] = [];
    let waited: number | null = null;
    let clock = 0;
    const stop = (): void => window.clearInterval(clock);
    const draw = (): void => {
      if (pressed === null) { steps.set(latest); return; }
      const now = performance.now();
      if (latest.length > 0 && waited === null) { waited = (now - pressed) / 1000; stop(); }
      const waiting: Step = { key: 'queued', words: STEP_WORDS.queued, state: latest.length > 0 ? 'done' : 'now', time: stepTime(waited ?? (now - pressed) / 1000) };
      steps.set([waiting, ...latest]);
    };
    if (pressed !== null) clock = window.setInterval(draw, 1000);
    signal.addEventListener('abort', stop);
    draw();
    return {
      quote, steps, spent, line, web, stop,
      after(next) { latest = pressed === null ? next : next.filter((step) => step.key !== 'queued'); draw(); },
    };
  };

  /** The caret in the composer, where one is drawn. */
  const focusWords = (): void => { shown?.field.focus({ preventScroll: true }); };

  /** Back to the page before Create with the words kept (N9), the refusal said in the composer's foot. */
  const back = (words: string, frame: MakingFrame | null, said: Refusal | null): void => {
    frame?.stop();
    keptWords = words || keptWords;
    refusal = said;
    busy = false;
    drawCreate();
    focusWords();
  };

  /**
   * A start, or a draft, refused: a price refused at the start (the quote expired, or its operation changed) reads the
   * offer again (`requote`) on the making view; less left than one step (A1b) reads the offer again, which says so in
   * the composer's place; anything else goes back to the composer with its sentence and what was spent (N9).
   */
  const refused = (words: string, frame: MakingFrame, code: string, { agreed = null, spent = null, referenceId = null, notes = null }: {
    readonly agreed?: string | null; readonly spent?: string | null; readonly referenceId?: string | null; readonly notes?: NotesMade | null;
  } = {}): void => {
    if (PRICE_CODES.includes(code)) { void requote(words, frame, code, agreed, 0, referenceId, notes); return; }
    if (code === SHORT_CODE) { back(words, frame, null); void readOffer(); return; }
    back(words, frame, { code, spent });
  };

  /**
   * The offer read again after a start refused for its price (N32), the making view kept: where the new most it can
   * spend is no more than `agreed`, the most the person agreed to, it starts again at once with the new quote (and the
   * same notes) and says nothing of a price; where it is higher it goes back and says the new figure, and Create again
   * starts at it; with no start agreed to, it goes back saying the price changed, the new most beside it. Where no new
   * most can be read, it says so under the steps and reads it again with N25's backoff, then the same rule.
   */
  const requote = async (words: string, frame: MakingFrame, code: string, agreed: string | null, failures: number, referenceId: string | null, notes: NotesMade | null): Promise<void> => {
    const fresh = await readSheet();
    const most = fresh?.operation?.maximumUsd ?? null;
    if (signal.aborted || form !== 'creating') return;
    if (most === null) {
      // The offer now says why nothing can start (a limit met, a budget spent): the composer says it.
      const state = offerState(rawOffer);
      if (fresh !== null && state.page !== 'offered' && !(state.page === 'refused' && state.code === PRICE_UNAVAILABLE)) { back(words, frame, null); return; }
      frame.line.textContent = REFUSAL_WORDS.priceUnavailable;
      frame.line.hidden = false;
      const next = afterRead(failures, false, 0);
      window.setTimeout(() => { if (!signal.aborted && form === 'creating') void requote(words, frame, code, agreed, next.failed, referenceId, notes); }, next.retryMs);
      return;
    }
    frame.line.hidden = true;
    if (agreed !== null && Number(most) <= Number(agreed)) { void startDraft(words, frame, { agreed, referenceId, notes, retried: true }); return; }
    back(words, frame, agreed !== null ? { code: PRICE_UP, spent: null, words: priceUp(ceilingAmount(most)) } : { code, spent: null });
  };

  /** Reads the offer for its operation sheet now: the parsed offer, or null where it cannot be read. */
  const readSheet = async (): Promise<WorldDraftOffer | null> => {
    try {
      const raw = await readRaw(credentials, '/worlds/drafts', signal);
      offer = parseWorldDraftOffer(raw);
      rawOffer = raw;
      offerAt = Date.now();
      return offer;
    } catch { return null; }
  };

  /**
   * Starts a draft of the words on its making view (N2) at `agreed`, the most the person saw, with the notes where they
   * came, then follows it. A sheet held through the notes, or read more than FRESH_MS ago, is read again before the
   * start is sent: the offer as it stands then says whether a start can go, and a higher price is said in the
   * composer and waits for Create (N32). `retried` on the one start made again after a refusal for its price, which is
   * not made again from its own.
   */
  const startDraft = async (words: string, frame: MakingFrame, { agreed, referenceId = null, notes = null, retried = false }: {
    readonly agreed: string; readonly referenceId?: string | null; readonly notes?: NotesMade | null; readonly retried?: boolean;
  }): Promise<void> => {
    busy = true;
    if ((notes !== null && !retried) || Date.now() - offerAt > FRESH_MS) {
      const fresh = await readSheet();
      if (signal.aborted) return;
      // Unread, the start goes with the sheet held, and the server says whether it holds.
      if (fresh !== null) {
        if (offerState(rawOffer).page !== 'offered' || fresh.operation === null) { back(words, frame, null); return; }
        if (Number(fresh.operation.maximumUsd) > Number(agreed)) {
          back(words, frame, { code: PRICE_UP, spent: null, words: priceUp(ceilingAmount(fresh.operation.maximumUsd)) });
          return;
        }
      }
    }
    const operation = offer?.operation ?? null;
    if (operation === null) { back(words, frame, { code: PRICE_UNAVAILABLE, spent: null }); return; }
    // The submission a press of Create sends; the same one again on a retry of the same words and sheet, so a start
    // whose answer was lost is never a second draft (the idempotency key).
    if (submission === null || submission.words !== words || submission.referenceId !== referenceId || submission.sent.operation !== operation) {
      submission = { words, referenceId, sent: { idempotencyKey: crypto.randomUUID(), operation, maximumUsd: operation.maximumUsd, ...(referenceId === null ? {} : { referenceId }) } };
    }
    const more = { agreed: retried ? null : agreed, referenceId, notes };
    try {
      const draft = await making.start(words, submission.sent);
      submission = null;
      busy = false;
      if (signal.aborted) return;
      if (draft.state === 'refused') { refused(words, frame, draft.refusal?.code ?? 'world_draft_failed', more); return; }
      void follow(draft.draftId, words, frame, notes);
    } catch (error) {
      busy = false;
      if (signal.aborted) return;
      const code = codeOf(error);
      // A start whose answer never came keeps its key, so Create again is the same start.
      if (code === null) { back(words, frame, { code: 'world_draft_failed', spent: null }); return; }
      submission = null;
      refused(words, frame, code, more);
    }
  };

  /**
   * Web notes first (items 3 and 4), on the making view drawn at the press: the request asked for the words, its steps
   * drawn as they happen with their times (the request states none, so they are this page's reads'), its notes in the
   * second column once kept; then the draft started with them, or from the words alone where none came, the line in
   * their place saying why.
   */
  const lookUp = async (words: string, mostUsd: string, agreed: string): Promise<void> => {
    busy = true;
    const frame = makingFrame(words, performance.now());
    const started: Record<string, number> = {}, seconds: Record<string, number> = {};
    const notesShown = (request: ReferenceRequest | null): Step[] => {
      const now = performance.now();
      for (const step of request?.steps ?? []) {
        if (step.state === 'running' || step.state === 'done' || step.state === 'missed') {
          started[step.step] ??= now;
          if (step.state === 'running' || seconds[step.step] === undefined) seconds[step.step] = (now - started[step.step]!) / 1000;
        }
      }
      return notesSteps(request?.steps ?? [], seconds);
    };
    let request: ReferenceRequest | null = null;
    try {
      request = await references().request({ purpose: 'world_draft', description: words, idempotencyKey: crypto.randomUUID() });
      while (!signal.aborted && !referenceFinished(request)) {
        frame.after(notesShown(request));
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        if (signal.aborted) return;
        request = await references().read(request.referenceId);
      }
    } catch {
      // A request refused or a read that failed: the drafting goes on from the words alone, saying so.
      request = request !== null && referenceFinished(request) ? request : null;
    }
    if (signal.aborted) return;
    const steps = notesShown(request);
    frame.after(steps);
    const searches = request?.searches.length ?? 0;
    const kept = request !== null && referenceHasNotes(request);
    if (kept) frame.web.notes(webNotesLabel(searches), request!.notes);
    else frame.web.instead(webNotesLabel(searches), notesNotUsedLine(request === null ? 'notMade' : notesOutcome(request)));
    busy = false;
    void startDraft(words, frame, { agreed, referenceId: kept ? request!.referenceId : null, notes: { steps, mostUsd, searches } });
  };

  /** The making view: follows draft `draftId` by its served reads until it is ready or refused; after notes, with them. */
  const follow = async (draftId: string, words: string, frame: MakingFrame, notes: NotesMade | null = null): Promise<void> => {
    const reads: RawDraft[] = [];
    const maximum = offer?.operation?.maximumUsd ?? null;
    let failed = 0;
    for (;;) {
      if (signal.aborted) return;
      let raw: RawDraft;
      try {
        raw = await readRaw(credentials, `/worlds/drafts/${encodeURIComponent(draftId)}`, signal);
      } catch {
        if (signal.aborted) return;
        const next = afterRead(failed, false, 0);
        failed = next.failed;
        frame.line.textContent = next.offline ? CREATE_WORDS.offline : '';
        frame.line.hidden = !next.offline;
        await new Promise((resolve) => window.setTimeout(resolve, next.retryMs));
        continue;
      }
      failed = 0; frame.line.hidden = true;
      reads.push(raw);
      if (!frame.quote.textContent && typeof raw['description'] === 'string' && raw['description']) { frame.quote.textContent = `“${raw['description']}”`; fitQuote(frame.quote); }
      // After notes, their steps first, then the draft's.
      frame.after([...(notes?.steps ?? []), ...draftSteps(reads)]);
      const noted = raw['references'] as { state?: unknown; code?: unknown; notes?: unknown; searches?: unknown; spent_usd?: unknown } | null | undefined;
      // A kind of place the notes do not reach says so in their place (item 4).
      if (notes !== null && noted?.state === 'not_used' && noted.code === 'reference_not_for_this_tool') frame.web.instead(webNotesLabel(notes.searches), notesNotUsedLine(null, 'reference_not_for_this_tool'));
      const own = spentOf(raw['accounting']);
      // The spend counts the notes' model calls; where the read states none, their most is not known yet (O1).
      const spent = notes === null ? own : withNotesSpent(own, typeof noted?.spent_usd === 'string' ? noted.spent_usd : null, notes.mostUsd);
      const quoted = typeof (raw['operation'] as { maximum_usd?: unknown } | null)?.maximum_usd === 'string'
        ? (raw['operation'] as { maximum_usd: string }).maximum_usd : maximum;
      // The most this draft may spend: what it was funded with where that is less than the whole (A1b).
      const funded = typeof raw['funded_usd'] === 'string' ? raw['funded_usd'] : null;
      const draftMost = funded !== null && (quoted === null || Number(funded) < Number(quoted)) ? funded : quoted;
      const most = notes === null || draftMost === null ? draftMost : sumUsd(draftMost, notes.mostUsd);
      if (spent !== null && most !== null) { frame.spent.textContent = spentUpTo(spent, most); frame.spent.hidden = false; }
      if (raw['state'] === 'ready') {
        frame.stop();
        const used = noted?.state === 'used' && typeof noted.notes === 'number' && typeof noted.searches === 'number';
        await made(words, frame, raw, spent, used ? noted.notes as number : null);
        return;
      }
      if (raw['state'] === 'refused') {
        const code = typeof (raw['refusal'] as { code?: unknown } | null)?.code === 'string' ? (raw['refusal'] as { code: string }).code : 'world_draft_failed';
        // Stopped part way where its next step could cost more than was left (A1b): said with its figures.
        const stopped = spent === null ? null : stoppedLine((raw['refusal'] as { spending?: unknown } | null)?.spending ?? null, spent);
        if (stopped !== null) back(words, frame, { code, spent: null, words: stopped, stopped: true });
        else refused(words, frame, code, { spent: spent === null ? null : refusalSpent(spent) });
        return;
      }
      const delay = pollDelay(raw);
      await new Promise((resolve) => window.setTimeout(resolve, delay ?? 3000));
    }
  };

  /** Ready: the made note's line handed to the world's arrival, then the world opens (frame 22). */
  const made = async (words: string, frame: MakingFrame, raw: RawDraft, spent: ReturnType<typeof spentOf>, notes: number | null = null): Promise<void> => {
    const draft = parseWorldMakingDraft(raw);
    if (draft.entry === null) { back(words, frame, { code: 'world_draft_failed', spent: null }); return; }
    const line = madeLine({ notes, spent, leftOut: draft.leftOut });
    try { sessionStorage.setItem(MADE_HANDOFF_KEY, writeMade(draft.entry.entryId, line)); } catch { /* The world opens without its note. */ }
    keptWords = '';
    await openMadeWorld(draft.entry);
  };

  /**
   * The making view for a served starter card, drawn the moment it is pressed, since making it takes seconds: the
   * card's name in the quote's place, and its one live step with its time from the press, until the world opens or
   * the start is refused. A card has no draft to read, so its step is the making itself. Returns what stops its clock.
   */
  const makingFrom = (name: string): (() => void) => {
    const frame = makingFrame('', null, name);
    const pressed = performance.now();
    const tick = (): void => frame.steps.set([{ words: STEP_WORDS.making, state: 'now', time: stepTime((performance.now() - pressed) / 1000) }]);
    tick();
    const clock = window.setInterval(tick, 1000);
    const stop = (): void => window.clearInterval(clock);
    signal.addEventListener('abort', stop);
    return stop;
  };

  /** A card: a recipe or a kind starts at once and opens through its opening; Blank opens in build mode (N4). */
  const startFrom = async (key: string): Promise<void> => {
    const card = cards.find((one) => one.key === key);
    if (!card || busy || form !== 'create') return;
    busy = true;
    // The picture behind is the card pressed.
    const at = strip?.cards.findIndex((one) => one.dataset['key'] === key) ?? -1;
    if (strip !== null && at >= 0 && at !== strip.chosen) strip.choose(at);
    // Blank opens at once; a served card is made first, and says so from its press.
    const stop = key === 'blank' ? null : makingFrom(cardWords.get(key)?.name ?? '');
    try {
      const entry = await card.start();
      if (signal.aborted) return;
      if (key === 'blank') {
        try { sessionStorage.setItem(MADE_HANDOFF_KEY, writeMade(entry.entryId, null, { build: true })); } catch { /* Opens without build mode. */ }
      }
      await openMadeWorld(entry);
    } catch (error) {
      stop?.();
      if (!signal.aborted) back(keptWords, null, { code: codeOf(error) ?? 'world_draft_failed', spent: null });
      busy = false;
    } finally {
      stop?.();
    }
  };

  // Keys (createKey): the composer takes its words, Enter creates or starts, arrows move along the cards, Esc leaves
  // once; nothing else reaches the front door or the shell under this page.
  page.root.addEventListener('keydown', (event) => {
    const active = document.activeElement;
    // A word being composed (an input method's Enter) is the field's.
    if (event.isComposing) { event.stopPropagation(); return; }
    // Tab keeps the focus within this page (C6): from its last stop to its first and back, never on to the front door
    // under it; between them the browser moves it.
    if (event.code === 'Tab' && !event.metaKey && !event.ctrlKey && !event.altKey) {
      const next = wrapStop(tabStops(page.root), active, event.shiftKey);
      if (next !== null) { event.preventDefault(); event.stopPropagation(); next.focus(); return; }
    }
    const focus = shown !== null && active === shown.field ? 'field'
      : strip !== null && strip.cards.includes(active as HTMLButtonElement) ? 'card'
        : active instanceof HTMLButtonElement ? 'button' : 'page';
    // Every plain Enter in the composer asks to create: create() starts, or says why it cannot.
    const fate = createKey(event, { page: form, focus, canCreate: true });
    if (fate === 'pass' || fate === 'type' || fate === 'quiet') { event.stopPropagation(); return; }
    event.preventDefault();
    event.stopPropagation();
    if (fate === 'leave') close();
    else if (fate === 'create') create();
    else if (fate === 'start' && strip !== null) void startFrom(strip.cards[strip.chosen]?.dataset['key'] ?? '');
    else if ((fate === 'previous' || fate === 'next') && strip !== null) {
      const at = strip.cards.indexOf(active as HTMLButtonElement);
      strip.choose(moveChoice(at < 0 ? strip.chosen : at, strip.cards.length, fate === 'next' ? 1 : -1), true);
    }
  });
  page.root.tabIndex = -1;

  drawCreate();
  // Focus opens in the composer (N6), the caret in it, so typing starts at once.
  focusWords();
  void readOffer();
  void readCards();
  return {
    get isConnected() { return page.root.isConnected && !closed; },
    remove: close,
  };
}

/**
 * The "Being made…" card on the front door (N12): where this person's draft still runs, a card
 * first in the strip that opens Create a world, which follows it on the making view. Read once, quietly;
 * answers the offer it read, for the front door's other readers of it, or null where it read none.
 */
export async function showBeingMade(root: HTMLElement, credentials: Credentials, signal?: AbortSignal): Promise<RawDraft | null> {
  let raw: RawDraft;
  try { raw = await readRaw(credentials, '/worlds/drafts', signal ?? new AbortController().signal); } catch { return null; }
  if (offerState(raw).page !== 'following' || !root.isConnected) return raw;
  const list = root.querySelector<HTMLElement>('.your-worlds-strip .world-entry-item')?.parentElement;
  if (!list || list.querySelector('.ux-being-made')) return raw;
  // Drawn as Your worlds draws a card (composition/world-entry.ts): a quiet tile, then its words.
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'world-entry-choice your-worlds-card ux-being-made';
  const tile = document.createElement('span');
  tile.className = 'your-worlds-picture'; tile.setAttribute('aria-hidden', 'true');
  const words = document.createElement('span');
  words.className = 'world-entry-choice-title'; words.textContent = CREATE_WORDS.beingMade;
  card.append(tile, words);
  card.addEventListener('click', () => root.querySelector<HTMLElement>('.your-worlds-create')?.click());
  const item = document.createElement('article');
  item.className = 'world-entry-item';
  item.append(card);
  list.prepend(item);
  return raw;
}

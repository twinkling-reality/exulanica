// Create a world (DESIGN's frames 20 and 21, rulings N1 to N21): one light page over the front door,
// in place of the app's old dialog (seams.mjs, 'Your worlds create'). Frame 20 reads the offer and
// takes a sentence, or starts from a card; frame 21 follows a draft by what the server serves, and
// a refusal comes back to frame 20 with the words kept. On ready the made world opens through its
// opening (world-opening.ts), and its arrival shows frame 22 (contextual-world.ts reads the made
// handoff). The parts draw (world-ui-create.ts); words and key fates are create-words.mjs's and
// create-steps.mjs's. Esc leaves once, the words kept; a draft carries on and waits in Your worlds.
import { WorldMakingClient, parseWorldDraftOffer, parseWorldMakingDraft, type WorldDraftOffer, type WorldMakingStart } from '../../../web/packages/app/src/world-making-api.ts';
import { WorldKindsClient, type WorldKind } from '../../../web/packages/app/src/world-kinds-api.ts';
import { WorldSpecificationClient, type SpecificationPreset } from '../../../web/packages/app/src/world-specification.ts';
import type { Credentials } from '../../../web/packages/app/src/config.ts';
import type { SavedWorldEntry, WorldEntryClient } from '../../../web/packages/app/src/world-entry-api.ts';
import {
  createKeyRow, createOrb, filmStrip, lightLabel, lightLine, lightPage, lightSteps, quietCommand, sentenceField, sentenceRow, setOrbReady,
  type FilmStrip, type LightPage, type SentenceField,
} from './world-ui-create.ts';
import { CREATE_WORDS, ceilingAmount, madeSpent, priceLine, priceUp, refusalSpent, refusalWords, setValue, spendLine, startsLeftLine } from './create-words.mjs';
import {
  MADE_HANDOFF_KEY, afterRead, canCreate, createKey, draftSteps, madeColumns, moveChoice, offerState, pollDelay, spentOf, startCards, writeMade,
} from './create-steps.mjs';
import { chosenWorldPicture, openMadeWorld } from './front-door.ts';
import { mountUiScale } from './world-ui.ts';

/** What main.ts holds while Create a world is open (its MakeWorldSurface). */
export interface CreateWorldSurface {
  readonly isConnected: boolean;
  remove(): void;
}

/** The title a Blank world is reopened under: the app's own starter (session-and-geometry.ts). */
const BLANK_TITLE = 'My world';

/** How far under the last line the stepped surface's lower edge stays (N24), in u. */
const SURFACE_BELOW = 64;
/** Frame 21's steps under the stepped surface (520u under a 450u surface), in u. */
const STEPS_BELOW_SURFACE = 70;
/** The least room between frame 20's surface and the cards, in u. */
const CARDS_CLEARANCE = 24;
/** The quote's most lines at 44u, then at 28u (N24). */
const QUOTE_LINES = [3, 5] as const;

/** The words typed here, kept across leaving and coming back in this page (N6). */
let keptWords = '';

/** A served draft read, raw: what draftSteps and spentOf read, and the parsed draft for its entry. */
type RawDraft = Readonly<Record<string, unknown>>;

/** A read through the workspace's own server (GET only), which keeps the token. */
async function readRaw(path: string, signal: AbortSignal): Promise<RawDraft> {
  const response = await fetch('/review-api' + path, { cache: 'no-store', signal });
  if (!response.ok) throw Object.assign(new Error('read'), { status: response.status });
  return response.json() as Promise<RawDraft>;
}

/** A refusal's served code, from an error the app's transport throws (ApiError) or none. */
const codeOf = (error: unknown): string | null => {
  const code = (error as { readonly code?: unknown } | null)?.code;
  return typeof code === 'string' && code ? code : null;
};

interface StartCard { readonly key: string; readonly start: () => Promise<SavedWorldEntry> }

/** A start refused for its price: the quote expired, or the operation it was for changed (N32). */
const PRICE_CODES: readonly string[] = ['world_draft_price_expired', 'world_draft_operation_changed', 'world_draft_bound_too_small'];
/** The page's own mark for a refusal whose new price is higher than the one agreed to, said with its figure (N32). */
const PRICE_UP = 'price_up';
/** A price that cannot be read now (N25), said in the plain ink while the offer is read again. */
const PRICE_UNAVAILABLE = 'world_draft_price_unavailable';

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
  const page: LightPage = lightPage({ form: 'create', picture: chosenWorldPicture(), labelledBy: 'wu-create-title' });
  // Over the front door and the app's shell, in the workspace's own tokens and scale.
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
    if (form === 'creating') void showBeingMade(root);
    onClose();
  };
  page.quiet.append(quietCommand({ onPress: close }));

  let offer: WorldDraftOffer | null = null;
  let rawOffer: RawDraft | null = null;
  let field: SentenceField | null = null;
  let orb: HTMLButtonElement | null = null;
  let strip: FilmStrip | null = null;
  // Blank is there from the start; the served cards join it when they are read.
  let cards: readonly StartCard[] = [{ key: 'blank', start: () => entries.ensureStarter(BLANK_TITLE) }];
  let form: 'create' | 'creating' = 'create';
  let busy = false;
  // The submission a press of Create sends; the same one again on a retry of the same words, so a
  // start whose answer was lost is never a second draft (the idempotency key).
  let submission: { readonly words: string; readonly sent: WorldMakingStart } | null = null;
  // A refusal said under the field, with what was spent, until the words change or the offer is read again;
  // `words` where its sentence carries a figure (a higher price, N32).
  let refusal: { readonly code: string; readonly spent: string | null; readonly words?: string } | null = null;
  let offerFailures = 0, offerOffline = false;
  // The sentence that names the cards where no field is drawn (N24), else null.
  let sentenceId: string | null = null;

  const title = (): HTMLElement => {
    const heading = document.createElement('h1');
    heading.className = 'wu-light-title'; heading.id = 'wu-create-title'; heading.tabIndex = -1;
    heading.textContent = CREATE_WORDS.title;
    return heading;
  };
  // A refusal of the last start leaves Create pressable: "Try again" means these words, or new ones.
  const ready = (): boolean => !busy && canCreate(rawOffer, field?.field.value ?? '');
  const keys = (): void => {
    const onCard = strip !== null && strip.cards.includes(document.activeElement as HTMLButtonElement);
    createKeyRow(page.keys, form === 'create' ? { create: ready(), start: onCard } : { create: false, start: false });
  };

  /** Frame 20, drawn from the offer read so far. */
  const drawCreate = (): void => {
    form = 'create';
    page.form('create');
    const state = offerState(rawOffer);
    const head: Node[] = [title()];
    sentenceId = null;
    if (rawOffer === null) {
      head.push(lightLine(offerOffline ? CREATE_WORDS.offline : CREATE_WORDS.loading, { live: true }));
    } else if (state.page === 'no-model' || state.page === 'budget' || state.page === 'not-offered') {
      // No field and no orb (N7, N24, N25): the sentence, which names the cards under it.
      const sentence = document.createElement('p'); sentence.className = 'wu-light-sentence';
      sentence.id = sentenceId = 'wu-create-sentence';
      sentence.textContent = state.page === 'no-model' ? CREATE_WORDS.noModel : state.page === 'budget' ? CREATE_WORDS.budgetSpent : CREATE_WORDS.notOffered;
      head.push(sentence);
      field = null; orb = null;
    } else {
      const limit = offer?.descriptionCharacters ?? 1000;
      field = sentenceField({ limit, value: keptWords, onInput: (words) => {
        keptWords = words;
        if (refusal !== null && refusal.code !== 'world_draft_price_expired' && refusal.code !== PRICE_UP && refusal.code !== PRICE_UNAVAILABLE) { refusal = null; drawCreate(); field?.field.focus(); return; }
        if (orb) setOrbReady(orb, ready());
        keys();
      } });
      orb = createOrb({ onPress: () => { void create(); }, ready: ready() });
      head.push(sentenceRow(field, orb));
      // Under the field, in order (N24): the count, the refusal and what was spent, the price line,
      // the starts left. A refusal of the offer itself (Create cannot be pressed) stands alone, so no
      // price or starts sit over it (the walk saw "12 of 12 starts left" over one); a price that
      // cannot be read is said in the plain ink while the offer is read again (N25).
      const now = state.page === 'refused' && state.code ? state.code : null;
      if (now === 'world_draft_price_unavailable') head.push(lightLine(refusalWords(now), { live: true }));
      else if (now !== null) head.push(lightLine(refusalWords(now), { tone: 'refused', live: true }));
      else {
        if (refusal !== null) {
          head.push(lightLine(refusal.words ?? refusalWords(refusal.code), refusal.code === PRICE_UNAVAILABLE ? { live: true } : { tone: 'refused', live: true }));
          if (refusal.spent) head.push(lightLine(refusal.spent, { tone: 'refused' }));
        }
        if (offer?.operation) head.push(lightLine(priceLine(offer.operation.maximumUsd)));
        const left = startsLeftLine(offer?.starts.left ?? Number.NaN);
        if (left) head.push(lightLine(left));
      }
    }
    if (sentenceId !== null) page.root.dataset.sentence = 'true'; else delete page.root.dataset.sentence;
    page.head.replaceChildren(...head);
    drawCards();
    keys();
    fit();
  };

  /**
   * The stepped surface holds every line in the head (N24): from its own height, it grows so its
   * lower edge stays `SURFACE_BELOW` under the last line, and never reaches what is under it.
   */
  const fit = (): void => {
    page.surface.style.removeProperty('height');
    page.lower.style.removeProperty('top');
    const unit = page.root.getBoundingClientRect().width / 1920 || 1;
    const top = page.surface.offsetTop, drawn = page.surface.offsetHeight;
    const last = page.head.lastElementChild as HTMLElement | null;
    if (!last || drawn === 0) return;
    const bottom = page.head.offsetTop + last.offsetTop + last.offsetHeight;
    const wanted = bottom + SURFACE_BELOW * unit - top;
    if (form === 'creating') {
      // Frame 21: the surface grows with the quote, and the steps move down with it.
      if (wanted > drawn) {
        page.surface.style.height = `${wanted}px`;
        page.lower.style.top = `${top + wanted + STEPS_BELOW_SURFACE * unit}px`;
      }
      return;
    }
    const ceiling = page.lower.offsetTop - top - CARDS_CLEARANCE * unit;
    if (wanted > drawn) page.surface.style.height = `${Math.min(wanted, ceiling)}px`;
  };

  const drawCards = (): void => {
    const shown = startCards([...cardWords.values()], [], { blankExists });
    strip = filmStrip(shown, (key) => { void startFrom(key); }, sentenceId === null ? {} : { labelledBy: sentenceId });
    strip.cards.forEach((card) => card.removeAttribute('aria-current'));
    strip.root.addEventListener('focusin', keys);
    strip.root.addEventListener('focusout', keys);
    page.lower.replaceChildren(strip.root);
  };

  // The cards: the server's presets and kinds as served, one per kind (its first preset), Blank last.
  const cardWords = new Map<string, { readonly key: string; readonly name: string; readonly picture: string | null }>();
  // Whether the workspace's blank world (its authored starter) is saved already: Blank then reopens it (N27).
  let blankExists = false;
  const readCards = async (): Promise<void> => {
    const [presets, kinds, saved] = await Promise.all([
      new WorldSpecificationClient(credentials).specification().then((spec) => spec.presets, () => [] as readonly SpecificationPreset[]),
      new WorldKindsClient(credentials).library().then((library) => library.kinds, () => [] as readonly WorldKind[]),
      entries.entries().then((list) => list, () => [] as readonly SavedWorldEntry[]),
    ]);
    blankExists = saved.some((entry) => entry.authoredScene?.kind === 'authored-starter');
    const found: StartCard[] = [];
    for (const preset of presets) {
      const key = `recipe:${preset.key}`;
      cardWords.set(key, { key, name: preset.label, picture: null });
      found.push({ key, start: () => entries.makeGenerated(preset.key, preset.label, preset.values) });
    }
    for (const kind of kinds) {
      const first = kind.presets[0];
      if (!first) continue;
      const key = `kind:${kind.kind}`;
      cardWords.set(key, { key, name: kind.label, picture: null });
      found.push({ key, start: () => entries.makeOfKind(kind, first.key, kind.label, first.values) });
    }
    cards = [...found, ...cards.filter((card) => card.key === 'blank')];
    if (!signal.aborted && form === 'create') drawCreate();
  };

  /** Reads the offer (raw for its codes, parsed for its sealed quote), quietly again on failure (L14). */
  const readOffer = async (): Promise<void> => {
    try {
      const raw = await readRaw('/worlds/drafts', signal);
      offer = parseWorldDraftOffer(raw);
      rawOffer = raw;
      offerFailures = 0; offerOffline = false;
    } catch {
      if (signal.aborted) return;
      const next = afterRead(offerFailures, false, 0);
      offerFailures = next.failed;
      if (next.offline && !offerOffline) { offerOffline = true; drawCreate(); }
      window.setTimeout(() => { if (!signal.aborted) void readOffer(); }, next.retryMs);
      return;
    }
    if (signal.aborted) return;
    const state = offerState(rawOffer);
    if (state.page === 'following') { void follow(state.draftId, keptWords); return; }
    const hadFocus = field !== null && document.activeElement === field.field;
    drawCreate();
    if (hadFocus || priceRetries === 0) field?.field.focus({ preventScroll: true });
    // A price that cannot be read now: the offer is read again quietly, with L14's backoff (N25).
    if (state.page === 'refused' && state.code === 'world_draft_price_unavailable') {
      const next = afterRead(priceRetries, false, 0);
      priceRetries = next.failed;
      window.setTimeout(() => { if (!signal.aborted && form === 'create') void readOffer(); }, next.retryMs);
    } else priceRetries = 0;
  };
  let priceRetries = 0;

  /** Create: starts a draft of the words (N2), then follows it on frame 21. `requoted` on the start made at once
   * with a new quote no higher than the one agreed to (N32), which is not made again from its own refusal. */
  const create = async (requoted = false): Promise<void> => {
    const words = field?.field.value.trim() ?? '';
    if (!ready() || offer?.operation == null) return;
    busy = true;
    if (orb) setOrbReady(orb, false);
    if (submission === null || submission.words !== words) {
      const operation = offer.operation;
      submission = { words, sent: { idempotencyKey: crypto.randomUUID(), operation, maximumUsd: operation.maximumUsd } };
    }
    // The most the person agreed to spend: a new quote no higher than it starts at once (N32).
    const agreed = submission.sent.maximumUsd;
    try {
      const draft = await making.start(words, submission.sent);
      submission = null;
      busy = false;
      if (signal.aborted) return;
      if (draft.state === 'refused') { refused(draft.refusal?.code ?? 'world_draft_failed', null, requoted ? null : agreed); return; }
      void follow(draft.draftId, words);
    } catch (error) {
      busy = false;
      if (signal.aborted) return;
      const code = codeOf(error);
      // A start whose answer never came keeps its key, so Create again is the same start.
      if (code === null) { refused('world_draft_failed', null); return; }
      submission = null;
      refused(code, null, requoted ? null : agreed);
    }
  };

  /**
   * Back on frame 20 with the words kept, the refusal said and what was spent (N9). A price refused
   * at the start (the quote expired, or its operation changed) reads the offer again (`requote`).
   */
  const refused = (code: string, spent: string | null, agreed: string | null = null): void => {
    if (PRICE_CODES.includes(code)) { void requote(code, spent, agreed, 0); return; }
    refusal = { code, spent };
    drawCreate();
    field?.field.focus({ preventScroll: true });
  };

  /**
   * The offer read again after a start refused for its price (N32): where the new most it can spend
   * is no more than `agreed`, the most the person agreed to, it starts at once with the new quote and
   * says nothing of a price; where it is higher it stops and says the new figure, and Create again
   * starts at it; with no start agreed to, the new most is shown under "The price changed". Where no
   * new most can be read, it says so in the plain ink and reads it again with N25's backoff, then the
   * same rule (N32 as built).
   */
  const requote = async (code: string, spent: string | null, agreed: string | null, failures: number): Promise<void> => {
    let most: string | null = null;
    try {
      const raw = await readRaw('/worlds/drafts', signal);
      offer = parseWorldDraftOffer(raw);
      rawOffer = raw;
      most = offer.operation?.maximumUsd ?? null;
    } catch { most = null; }
    if (signal.aborted || form !== 'create') return;
    if (most === null) {
      refusal = { code: PRICE_UNAVAILABLE, spent };
      drawCreate();
      const next = afterRead(failures, false, 0);
      window.setTimeout(() => { if (!signal.aborted && form === 'create') void requote(code, spent, agreed, next.failed); }, next.retryMs);
      return;
    }
    if (agreed !== null && Number(most) <= Number(agreed)) { refusal = null; void create(true); return; }
    refusal = agreed !== null ? { code: PRICE_UP, spent, words: priceUp(ceilingAmount(most)) } : { code, spent };
    drawCreate();
    field?.field.focus({ preventScroll: true });
  };

  /** Frame 21: follows draft `draftId` by its served reads until it is ready or refused. */
  const follow = async (draftId: string, words: string): Promise<void> => {
    form = 'creating';
    page.form('creating');
    const quote = document.createElement('p');
    quote.className = 'wu-light-quote'; quote.id = 'wu-create-title';
    quote.textContent = words ? `“${words}”` : '';
    page.head.replaceChildren(lightLabel(CREATE_WORDS.creating), quote);
    const steps = lightSteps();
    const spend = lightLine('', { live: true });
    const offline = lightLine('', { live: true });
    spend.hidden = true; offline.hidden = true;
    page.lower.replaceChildren(steps.root, spend, offline, lightLine(CREATE_WORDS.leave));
    strip = null; field = null; orb = null;
    sizeQuote(quote);
    keys();
    page.root.focus({ preventScroll: true });
    const reads: RawDraft[] = [];
    const maximum = offer?.operation?.maximumUsd ?? null;
    let failed = 0;
    for (;;) {
      if (signal.aborted) return;
      let raw: RawDraft;
      try {
        raw = await readRaw(`/worlds/drafts/${encodeURIComponent(draftId)}`, signal);
      } catch {
        if (signal.aborted) return;
        const next = afterRead(failed, false, 0);
        failed = next.failed;
        offline.textContent = next.offline ? CREATE_WORDS.offline : '';
        offline.hidden = !next.offline;
        await new Promise((resolve) => window.setTimeout(resolve, next.retryMs));
        continue;
      }
      failed = 0; offline.hidden = true;
      reads.push(raw);
      if (!quote.textContent && typeof raw['description'] === 'string' && raw['description']) { quote.textContent = `“${raw['description']}”`; sizeQuote(quote); }
      steps.set(draftSteps(reads));
      const spent = spentOf(raw['accounting']);
      const most = typeof (raw['operation'] as { maximum_usd?: unknown } | null)?.maximum_usd === 'string'
        ? (raw['operation'] as { maximum_usd: string }).maximum_usd : maximum;
      if (spent !== null && most !== null) { spend.textContent = spendLine(spent, most); spend.hidden = false; }
      if (raw['state'] === 'ready') { await made(raw, spent, most); return; }
      if (raw['state'] === 'refused') {
        const code = typeof (raw['refusal'] as { code?: unknown } | null)?.code === 'string' ? (raw['refusal'] as { code: string }).code : 'world_draft_failed';
        keptWords = words || keptWords;
        refused(code, spent === null ? null : refusalSpent(spent));
        return;
      }
      const delay = pollDelay(raw);
      await new Promise((resolve) => window.setTimeout(resolve, delay ?? 3000));
    }
  };

  /** The whole sentence shows (N24): 44u while it fits in three lines, 28u in five, 20u after; the surface follows. */
  const sizeQuote = (quote: HTMLElement): void => {
    delete quote.dataset.size;
    const lines = (): number => {
      const height = parseFloat(getComputedStyle(quote).lineHeight) || 1;
      return Math.round(quote.getBoundingClientRect().height / height);
    };
    if (lines() > QUOTE_LINES[0]) quote.dataset.size = '28';
    if (lines() > QUOTE_LINES[1]) quote.dataset.size = '20';
    fit();
  };

  /** Ready: the made note's columns handed to the world's arrival, then the world opens (frame 22). */
  const made = async (raw: RawDraft, spent: ReturnType<typeof spentOf>, most: string | null): Promise<void> => {
    const draft = parseWorldMakingDraft(raw);
    if (draft.entry === null) { refused('world_draft_failed', null); return; }
    const columns = madeColumns({
      inIt: draft.made.map((part) => part.label).join(', ') || null,
      set: setValue(raw['land'] as Parameters<typeof setValue>[0], raw['setting'] as Parameters<typeof setValue>[1]),
      notInItYet: draft.leftOut.join(', ') || null,
      spent: spent !== null && most !== null ? madeSpent(spent, most) : null,
    });
    try { sessionStorage.setItem(MADE_HANDOFF_KEY, writeMade(draft.entry.entryId, columns)); } catch { /* The world opens without its note. */ }
    keptWords = '';
    await openMadeWorld(draft.entry);
  };

  /** A card: a recipe or a kind starts at once and opens through its opening; Blank opens in build mode (N4). */
  const startFrom = async (key: string): Promise<void> => {
    const card = cards.find((one) => one.key === key);
    if (!card || busy) return;
    busy = true;
    try {
      const entry = await card.start();
      if (signal.aborted) return;
      if (key === 'blank') {
        try { sessionStorage.setItem(MADE_HANDOFF_KEY, writeMade(entry.entryId, [], { build: true })); } catch { /* Opens without build mode. */ }
      }
      await openMadeWorld(entry);
    } catch (error) {
      busy = false;
      if (!signal.aborted) refused(codeOf(error) ?? 'world_draft_failed', null);
    }
  };

  // Keys (createKey): the field takes its words, Enter creates or starts, arrows move along the
  // cards, Esc leaves once; nothing else reaches the front door or the shell under this page.
  page.root.addEventListener('keydown', (event) => {
    const active = document.activeElement;
    const focus = field !== null && active === field.field ? 'field'
      : strip !== null && strip.cards.includes(active as HTMLButtonElement) ? 'card'
        : active instanceof HTMLButtonElement ? 'button' : 'page';
    const fate = createKey(event, { page: form, focus, canCreate: ready() });
    if (fate === 'pass' || fate === 'type' || fate === 'quiet') { event.stopPropagation(); return; }
    event.preventDefault();
    event.stopPropagation();
    if (fate === 'leave') close();
    else if (fate === 'create') void create();
    else if (fate === 'start' && strip !== null) void startFrom(strip.cards[strip.chosen]?.dataset['key'] ?? '');
    else if ((fate === 'previous' || fate === 'next') && strip !== null) {
      const at = strip.cards.indexOf(active as HTMLButtonElement);
      strip.choose(moveChoice(at < 0 ? strip.chosen : at, strip.cards.length, fate === 'next' ? 1 : -1), true);
      keys();
    }
  });
  page.root.tabIndex = -1;

  drawCreate();
  void readOffer();
  void readCards();
  return {
    get isConnected() { return page.root.isConnected && !closed; },
    remove: close,
  };
}

/**
 * The "Being made…" card on the front door (N12): where this person's draft still runs, a card
 * first in the strip that opens Create a world, which follows it on frame 21. Read once, quietly.
 */
export async function showBeingMade(root: HTMLElement, signal?: AbortSignal): Promise<void> {
  let raw: RawDraft;
  try { raw = await readRaw('/worlds/drafts', signal ?? new AbortController().signal); } catch { return; }
  if (offerState(raw).page !== 'following' || !root.isConnected) return;
  const list = root.querySelector<HTMLElement>('.your-worlds-strip .world-entry-item')?.parentElement;
  if (!list || list.querySelector('.ux-being-made')) return;
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
}

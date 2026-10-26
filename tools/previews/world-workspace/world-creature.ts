// Making a creature where it will stand (unit 9, DESIGN's R-CREATURE-BUILD-SHEET.md): opened from build mode's
// "Make a creature" tile. The spot 8 m ahead is marked where the society would take the creature in (the
// stand read, GET .../society/stand), the person's words go in the field, the draft is read every second while
// it is made, and once made the kept kind stands there held by build mode (build-mode.ts's hold), whose own keys
// place it where it was made or put it back. Where the offer offers web notes, a ticked box first asks for notes on
// the words (a reference request, references-api.ts), shows its steps and its notes, and asks the drafter with them;
// where none come, from the words alone. The server's drafter and checks decide what the creature is.
import { CreatureDraftsClient, draftEnded, type CreatureDraft, type CreatureNotesOffer, type CreatureOffer, type SocietyStand } from '../../../web/packages/app/src/creature-drafts-api.ts';
import type { Credentials } from '../../../web/packages/app/src/config.ts';
import { ReferencesClient, referenceFinished, referenceHasNotes, type ReferenceRequest } from '../../../web/packages/app/src/references-api.ts';
import { CREATURE_WORDS, creatureField, leader, madeGroup, makerLine, makingGroup, notesAsk, placeRow, standLabel, standLight, type MakingGroup } from './world-ui-creature.ts';
import { ANCHOR_INSET } from './world-ui-layout.mjs';

/** How far ahead of the eye the stand is looked for (the sheet's 8 m: 3 m falls under the field). */
export const STAND_AHEAD_MM = 8000;
/** The stand's ring on the ground, its radius in metres (the build ring's line and glow; r-creature17t's size). */
export const STAND_RING_M = 1.0;
/** The words one creature may be described with, as the drafter's form states its own. */
const WORDS_MAXIMUM = 400;
/** How long the page follows a notes request before it makes the creature from the words alone and stops the request. */
const NOTES_FOLLOW_MS = 120_000;

/** The sum of two dollar amounts as the server writes them (whole units of a hundred-millionth), with no float. */
export function addUsd(a: string, b: string): string {
  const units = (usd: string): bigint => { const [whole = '0', part = ''] = usd.split('.'); return BigInt(whole) * 100_000_000n + BigInt(part.padEnd(8, '0').slice(0, 8)); };
  const sum = units(a) + units(b);
  return `${sum / 100_000_000n}.${String(sum % 100_000_000n).padStart(8, '0')}`;
}

/**
 * Why a world may not ask, or an ask was refused, in words, by code (M10 and M11); spending paused
 * (the authority held closed until an operator acts) told apart from spent by the served code (N34).
 */
const REFUSED: Readonly<Record<string, string>> = Object.freeze({
  creatures_not_run_here: CREATURE_WORDS.notOffered,
  models_not_configured: CREATURE_WORDS.notOffered,
  budget_exceeded: CREATURE_WORDS.budgetSpent,
  spending_refused: CREATURE_WORDS.budgetSpent,
  spending_suspended: CREATURE_WORDS.spendingPaused,
});

/**
 * Why a draft ended with nothing made, by its failure code (the offer's `codes.failed`), in DESIGN's words of 23
 * October, and whether "[↵] Try again" shows under it: back to the field with the words kept, wherever making is still
 * offered here and changed words may pass. Not where the field cannot help: the budget spent, spending paused, or
 * making not offered here. Any other code reads `wentWrong`, with Try again.
 */
const FAILED: Readonly<Record<string, { readonly words: string; readonly retry: boolean }>> = Object.freeze({
  drafter_unavailable: { words: CREATURE_WORDS.modelSilent, retry: true },
  stranded: { words: CREATURE_WORDS.stoppedPartWay, retry: true },
  expired: { words: CREATURE_WORDS.notStarted, retry: true },
  not_served: { words: CREATURE_WORDS.notOffered, retry: false },
  request_refused: { words: CREATURE_WORDS.notSent, retry: true },
  reference_withdrawn: { words: CREATURE_WORDS.pictureWithdrawn, retry: true },
  spending_refused: { words: CREATURE_WORDS.budgetSpent, retry: false },
  spending_suspended: { words: CREATURE_WORDS.spendingPaused, retry: false },
});

/**
 * The words as the server takes a line: in normal form C, with no control or format character, every run of white
 * space (a line break included) one space, and none at either end, so what a person typed is never refused for what
 * they cannot see.
 */
export function sendableWords(words: string): string {
  return words.normalize('NFC').replace(/\s+/gu, ' ').replace(/[\p{Cc}\p{Cf}]/gu, '').replace(/ {2,}/g, ' ').trim();
}

/** A refusal's served code, from an error the app's transport throws (ApiError), or null. */
const codeOf = (error: unknown): string | null => {
  const code = (error as { readonly code?: unknown } | null)?.code;
  return typeof code === 'string' && code ? code : null;
};

/** How a hold ends, as build mode answers it. */
export type Held = { readonly outcome: 'placed'; readonly thingId: string } | { readonly outcome: 'put-back' } | null;

export interface CreatureScreenDeps {
  readonly root: HTMLElement;
  readonly client: Pick<CreatureDraftsClient, 'offer' | 'drafts' | 'ask' | 'draft' | 'stand'>;
  /** Web notes: a request on the words, read as it goes, stopped where the page gives up on it; absent, none are offered. */
  readonly notes?: Pick<ReferencesClient, 'request' | 'read' | 'cancel'>;
  /** A fresh idempotency key for a notes request. */
  readonly key?: () => string;
  /** The open version and the world it belongs to. */
  readonly version: () => { readonly versionId: string; readonly worldId: string } | null;
  /** The region-frame point on the ground this far ahead of the eye, or null where none is in view. */
  readonly ahead: (millimetres: number) => { readonly xMm: number; readonly zMm: number } | null;
  /** The ring on the ground at the stand, and the screen point the label floats at; hidden with null. */
  readonly mark: (stand: SocietyStand | null) => { readonly x: number; readonly y: number } | null;
  /** Where the held creature's head shows on the screen, for the made card's leader; null where it is not drawn. */
  readonly head?: () => { readonly x: number; readonly y: number } | null;
  /**
   * Build mode's hold: the kept kind held at the stand's point to be placed; `told` hears how its placing stands
   * (placing once Enter lets it go, until the server answers; refused with build mode's own words).
   */
  readonly hold: (
    kind: { readonly source: 'workspace'; readonly sha256: string },
    at: { readonly xMm: number; readonly zMm: number },
    told?: (placing: { readonly placing: boolean; readonly refused: string | null }) => void,
  ) => Promise<Held>;
  /** Back to building; the making, if any, carries on. */
  readonly close: () => void;
  /**
   * Gives the keys back to the world while the step still shows: the made creature is held at the stand, and build
   * mode's own keys place it (Enter) or put it back (Esc).
   */
  readonly release: () => void;
  readonly wait?: (ms: number) => Promise<void>;
}

export interface CreatureScreen {
  /** Act on a key; true when the screen took it. */
  key(event: KeyboardEvent): boolean;
  /** Takes the screen down; a making carries on at the server. */
  destroy(): void;
}

const pause = (ms: number): Promise<void> => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * Opens the describe screen over the world: reads the offer, finds the stand and, where a draft of this person's is
 * still being made, follows it, so a reload loses nothing.
 */
export async function openCreatureScreen(deps: CreatureScreenDeps): Promise<CreatureScreen> {
  const wait = deps.wait ?? pause;
  const layer = document.createElement('div');
  layer.className = 'wu-creature-layer';
  deps.root.append(layer);
  let offer: CreatureOffer | null = null;
  let stand: SocietyStand | null = null;
  let words = '';
  // 'late': the page stopped following a draft the server is still making; it waits in Creatures when done.
  let state: 'describe' | 'making' | 'made' | 'ended' | 'late' = 'describe';
  // Ended with nothing made, whether trying again can help (Try again shows, and Enter does it).
  let retryable = false;
  let ended = false;
  const field = creatureField({ maximum: WORDS_MAXIMUM, onMake: () => { void make(); } });
  // Whether the person ticked the web notes box for this creature (off until ticked, each creature its own choice), and
  // whether a notes request was made for the creature being made (its spend is then part of the making's).
  let withNotes = false, notesAsked = false;
  const label = standLabel(), light = standLight();
  let standAt: { readonly x: number; readonly y: number } | null = null;
  layer.append(field.root);

  /** The web notes the offer offers here, where the page can ask for them and the most they add is served. */
  function notesOffered(): (CreatureNotesOffer & { readonly maximumUsd: string }) | null {
    const notes = offer?.offered ? offer.notes ?? null : null;
    return deps.notes !== undefined && notes !== null && notes.offered && notes.maximumUsd !== null ? notes as CreatureNotesOffer & { readonly maximumUsd: string } : null;
  }
  /** The most the making may cost: the drafter's, and with notes asked for, theirs too; null where it is not served. */
  function mostUsd(): string | null {
    const price = offer?.priceUsdAtMost ?? null, notes = withNotes ? notesOffered() : null;
    return price === null || notes === null ? price : addUsd(price, notes.maximumUsd);
  }
  function lineUnder(): void {
    if (offer !== null && !offer.offered) { field.line(REFUSED[offer.code ?? ''] ?? CREATURE_WORDS.notOffered, true); return; }
    // Ticked, the line gives the whole most; no measured time covers the searches, so it gives no time then.
    field.line(makerLine(mostUsd(), withNotes ? null : offer?.timing.typicalSeconds ?? null, offer?.model?.name ?? null));
  }
  function offerNotes(): void {
    const notes = notesOffered();
    if (notes === null) return;
    const ask = notesAsk({ searchesAtMost: notes.searchesAtMost, maximumUsd: notes.maximumUsd, onChange: (on) => { withNotes = on; lineUnder(); } });
    field.root.append(ask.root);
  }
  function showStand(): void {
    const at = deps.mark(stand);
    standAt = at;
    if (at === null) { label.remove(); return; }
    for (const part of [label, light]) { part.style.left = `${at.x}px`; part.style.top = `${at.y}px`; }
    // "The creature appears here" is describe's label alone: making shows the ring and the light.
    if (state === 'describe' && !label.isConnected) layer.append(label);
  }
  // The label and the light follow the stand on the screen as the window or the view changes, each frame while
  // the stand shows; once the made creature is held there, build mode marks it and the leader follows its head.
  function track(): void {
    if (ended) return;
    if (stand !== null && state !== 'made') showStand();
    if (state === 'made') drawLeader();
    globalThis.requestAnimationFrame?.(track);
  }
  /**
   * Whether a stand's screen point is in view: above the field's top and below the pill, inside the side insets
   * (DESIGN's 13:59 ruling). A bound not laid out yet bounds nothing.
   */
  function inView(at: { readonly x: number; readonly y: number }): boolean {
    const field = deps.root.querySelector('.wu-creature-glass')?.getBoundingClientRect();
    const pill = deps.root.querySelector('.wu-top')?.getBoundingClientRect();
    return at.x >= ANCHOR_INSET && at.x <= innerWidth - ANCHOR_INSET
      && !(field && field.height > 0 && at.y > field.top)
      && !(pill && pill.height > 0 && at.y < pill.bottom);
  }
  async function findStand(): Promise<void> {
    const version = deps.version(), point = deps.ahead(STAND_AHEAD_MM);
    stand = version === null || point === null ? null : await deps.client.stand(version.versionId, version.worldId, point).catch(() => null);
    if (ended) return;
    if (stand === null) { deps.mark(null); return; }
    // A stand out of view, or one the eye does not see (build mode's mark answers none), is no stand: the creature
    // is then placed later from Creatures.
    const at = deps.mark(stand);
    if (at === null || !inView(at)) { stand = null; deps.mark(null); return; }
    showStand();
  }
  const pointer = leader();
  function drawLeader(): void {
    const head = deps.head?.() ?? null, card = layer.querySelector('.wu-creature-made');
    if (head === null || card === null) { pointer.hide(); return; }
    if (!pointer.root.isConnected) layer.prepend(pointer.root);
    const box = card.getBoundingClientRect(), title = card.querySelector('.wu-creature-title')?.getBoundingClientRect();
    // To the card's near edge: its left beside a creature on its left, its right where the card stands on the left.
    pointer.draw(head, { x: box.right <= head.x ? box.right : box.left, y: title ? title.top + title.height / 2 : box.top });
  }
  /**
   * The making group and the made card take the half of the view the stand is not in (DESIGN, 26 October): beside a
   * stand right of the middle they stand on the left, so neither covers the stand or the creature made on it.
   */
  function besideStand(group: HTMLElement): void {
    group.classList.toggle('wu-creature-left', standAt !== null && standAt.x > innerWidth / 2);
  }
  field.input.addEventListener('input', () => { words = field.input.value; field.count(words.length, WORDS_MAXIMUM); });
  field.count(0, WORDS_MAXIMUM);

  /** The making group, its light and the stand's label put away: the field gives way to the steps. */
  function startMaking(): MakingGroup {
    state = 'making';
    field.root.remove();
    const making = makingGroup({ words, priceUsdAtMost: mostUsd() });
    // With web notes asked for, the group grows by the notes: it stands on the field's line and grows upward.
    making.root.classList.toggle('wu-creature-noted', withNotes && notesOffered() !== null);
    besideStand(making.root);
    label.remove();
    layer.append(making.root);
    if (standAt !== null) layer.prepend(light);
    return making;
  }
  const clock = (ms: number): string => { const seconds = Math.floor(ms / 1000); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; };

  /**
   * Web notes on the words before the drafter is asked (Create's frame 21 with "creature"): the request's steps as
   * they pass, each with its time, then its notes; the reference id to draft with, or null where none came, said in
   * place. Esc does not stop it: the page goes on asking, so the creature is still made and waits in Creatures.
   */
  async function followNotes(making: MakingGroup, sent: string): Promise<string | null> {
    let request: ReferenceRequest;
    try {
      request = await deps.notes!.request({ purpose: 'things', description: sent, idempotencyKey: deps.key?.() ?? crypto.randomUUID() });
      notesAsked = true;
    } catch {
      making.alone(CREATURE_WORDS.notesFailed);
      return null;
    }
    const started = Date.now(), deadline = started + NOTES_FOLLOW_MS;
    // When each step was first seen running, and which have been drawn as passed.
    const since = new Map<string, number>([['waiting', started]]), passed = new Set<string>();
    const draw = (now: number): void => {
      const steps = request.steps.filter((step) => CREATURE_WORDS.notesSteps[step.step] !== undefined && step.state !== 'skipped');
      if (request.status !== 'queued' && !passed.has('waiting')) { passed.add('waiting'); making.passed(CREATURE_WORDS.waiting, clock(now - started)); }
      for (const step of steps) {
        if (step.state === 'running' && !since.has(step.step)) since.set(step.step, now);
        if ((step.state === 'done' || step.state === 'missed') && !passed.has(step.step)) {
          passed.add(step.step);
          making.passed(CREATURE_WORDS.notesSteps[step.step]!, clock(now - (since.get(step.step) ?? now)), step.state === 'missed');
        }
      }
      const current = steps.find((step) => step.state === 'running' || step.state === 'waiting');
      const words = request.status === 'queued' || current === undefined ? CREATURE_WORDS.waiting : CREATURE_WORDS.notesSteps[current.step]!;
      making.step(words, false, clock(now - (since.get(current?.step ?? 'waiting') ?? started)));
    };
    while (!referenceFinished(request) && Date.now() < deadline) {
      draw(Date.now());
      await wait(1000);
      request = await deps.notes!.read(request.referenceId).catch(() => request);
    }
    draw(Date.now());
    if (!referenceFinished(request)) {
      // Past the time the page follows it: it is stopped, and the creature is made from the words alone.
      void deps.notes!.cancel(request.referenceId).catch(() => null);
      making.alone(CREATURE_WORDS.notesFailed);
      return null;
    }
    if (referenceHasNotes(request)) {
      making.notes(request.notes, request.searches.length);
      return request.referenceId;
    }
    making.alone(request.status === 'complete' || request.status === 'partial' ? CREATURE_WORDS.notesNone : CREATURE_WORDS.notesFailed);
    return null;
  }

  async function follow(draft: CreatureDraft, making: MakingGroup = startMaking()): Promise<void> {
    const started = Date.now();
    const timeout = offer?.timing.timeoutSeconds ?? 50;
    const deadline = started + (2 * timeout + 10) * 1000;
    let current = draft;
    while (!ended && !draftEnded(current) && Date.now() < deadline) {
      const seconds = Math.floor((Date.now() - started) / 1000);
      making.step(current.status === 'queued' ? CREATURE_WORDS.waiting : CREATURE_WORDS.drafting, false, clock(seconds * 1000));
      await wait(1000);
      if (ended) return;
      current = await deps.client.draft(current.draftId);
    }
    if (ended) return;
    light.remove();
    if (current.status === 'kept' && current.kind !== null) {
      state = 'made';
      making.root.remove();
      const card = madeGroup({
        label: current.label, words, modelName: current.model?.name ?? null, spentUsd: spentOf(current),
        notes: current.references?.state === 'used' ? current.references.notes : 0,
        // Until its made look is made, the creature wears its sketch (M15).
        sketch: current.lookStatus !== 'made', placeable: stand !== null,
      });
      besideStand(card);
      layer.append(card);
      if (stand !== null) {
        // It stands where it was made, held to be placed (B8): build mode draws it there and its own keys place it or
        // put it back; either way this step ends, and a creature put back waits in Creatures.
        label.remove();
        deps.mark(null);
        deps.release();
        const at = { xMm: stand.positionMm[0], zMm: stand.positionMm[1] };
        // Build mode tells how its placing stands, so the card says "Placing…" until the server answers.
        void deps.hold({ source: 'workspace', sha256: current.kind.sha256 }, at, (placing) => { placeRow(card, placing); }).then(() => {
          if (!ended) { destroy(); deps.close(); }
        });
      }
      return;
    }
    if (!draftEnded(current)) {
      // Still being made when the page stops following: it carries on at the server and waits in Creatures.
      state = 'late';
      making.late(CREATURE_WORDS.takingLonger);
      return;
    }
    state = 'ended';
    // A refused draft says its check's own sentence; changed words may pass, so Try again shows under it too.
    const failed = current.refusal !== null ? { words: current.refusal.detail, retry: true } : FAILED[current.failure ?? ''] ?? { words: CREATURE_WORDS.wentWrong, retry: true };
    retryable = failed.retry;
    making.ended(failed.words, retryable ? tryAgain : null, spentOf(current));
  }

  /**
   * What the making spent: the draft's attempts and, where notes were asked for, their request's model calls too.
   * Where the notes' spend is not served (a request that ended without notes keeps no record of its calls here), no
   * figure at all, so the page never says less than was spent.
   */
  function spentOf(draft: CreatureDraft): string | null {
    const own = draft.spentUsd ?? null, notes = draft.references ?? null;
    if (own === null) return null;
    if (notes === null) return notesAsked ? null : own;
    return notes.spentUsd === null ? null : addUsd(own, notes.spentUsd);
  }

  /** Back to the field with the words kept, as Enter does where "[↵] Try again" shows. */
  function tryAgain(): void {
    if (state !== 'ended' || ended) return;
    state = 'describe';
    layer.replaceChildren(field.root);
    lineUnder();
    field.input.focus();
  }

  async function make(): Promise<void> {
    if (state !== 'describe' || offer === null || !offer.offered) return;
    const sent = sendableWords(words);
    if (sent === '') return;
    words = sent;
    notesAsked = false;
    // With the box ticked, the notes first, in the making group, and the drafter asked with them where they came.
    const making = withNotes && notesOffered() !== null ? startMaking() : null;
    const referenceId = making === null ? null : await followNotes(making, sent);
    let asked: CreatureDraft;
    try {
      asked = await deps.client.ask(sent, referenceId);
    } catch (error) {
      const code = codeOf(error);
      // One draft open at a time: the one being made is followed rather than refused (a second page asked it).
      const running = code === 'creature_limit_reached' ? (await deps.client.drafts().catch(() => [])).find((draft) => !draftEnded(draft)) : undefined;
      if (running !== undefined) { await follow(running, making ?? undefined); return; }
      const refused = code === 'creature_limit_reached' ? CREATURE_WORDS.hourLimit : REFUSED[code ?? ''] ?? CREATURE_WORDS.wentWrong;
      if (making === null) { field.line(refused, true); return; }
      // Refused after the notes: the making group says why, and Try again goes back to the field with the words.
      state = 'ended';
      retryable = true;
      making.ended(refused, tryAgain, null);
      return;
    }
    await follow(asked, making ?? undefined);
  }

  function destroy(): void {
    if (ended) return;
    ended = true;
    deps.mark(null);
    layer.remove();
  }

  offer = await deps.client.offer().catch(() => null);
  lineUnder();
  offerNotes();
  await findStand();
  globalThis.requestAnimationFrame?.(track);
  const running = offer?.offered ? (await deps.client.drafts().catch(() => [])).find((draft) => !draftEnded(draft)) : undefined;
  if (running !== undefined) void follow(running);
  else field.input.focus();

  return {
    key(event) {
      if (ended) return false;
      if (event.key === 'Escape') { event.preventDefault(); destroy(); deps.close(); return true; }
      if (event.key === 'Enter' && !event.shiftKey) {
        if (state === 'describe') { event.preventDefault(); void make(); return true; }
        if (state === 'ended' && retryable) { event.preventDefault(); tryAgain(); return true; }
      }
      return false;
    },
    destroy,
  };
}

/** What build mode hands the maker when its tile is picked (build-mode.ts). */
export interface BuildHand {
  readonly hold: CreatureScreenDeps['hold'];
  readonly ahead: CreatureScreenDeps['ahead'];
  /** Where the held creature's head shows on the screen. */
  readonly head: () => { readonly x: number; readonly y: number } | null;
  /** Lays the stand's ring at a region point, or hides it with null; where it shows on the screen. */
  readonly mark: (at: { readonly xMm: number; readonly zMm: number } | null, radiusM: number) => { readonly x: number; readonly y: number } | null;
  /**
   * Told when a creature step shows over the world, with the step's key handler, and when it is gone: the tray hides
   * meanwhile and every key goes to the step first, so nothing else of the world acts on it.
   */
  readonly showing: (now: boolean, key?: (event: KeyboardEvent) => void) => void;
}

/**
 * The maker build mode's "Make a creature" tile opens over the page's open world, or null where the page has no
 * credentials to ask with, so the tray offers no tile. While the screen shows, build mode hands it every key first.
 */
export function creatureMakerFor(state: {
  readonly credentials: Credentials | null;
  readonly activeWorldEntry: { readonly worldId: string; readonly authoredVersionId: string } | null;
}): ((hand: BuildHand) => void) | null {
  if (state.credentials === null) return null;
  const client = new CreatureDraftsClient(state.credentials);
  const notes = new ReferencesClient(state.credentials);
  let open: CreatureScreen | null = null, opening = false;
  return (hand) => {
    if (open !== null || opening) return;
    opening = true;
    const close = (): void => { open = null; hand.showing(false); };
    hand.showing(true, (event) => { open?.key(event); });
    void openCreatureScreen({
      root: document.getElementById('contextual-world') ?? document.body,
      client,
      notes,
      version: () => {
        const entry = state.activeWorldEntry;
        return entry === null ? null : { versionId: entry.authoredVersionId, worldId: entry.worldId };
      },
      ahead: hand.ahead,
      head: hand.head,
      mark: (stand) => hand.mark(stand === null ? null : { xMm: stand.positionMm[0], zMm: stand.positionMm[1] }, STAND_RING_M),
      hold: hand.hold,
      close,
      release: () => { hand.showing(true); },
    }).then((screen) => { open = screen; }, () => { close(); }).finally(() => { opening = false; });
  };
}

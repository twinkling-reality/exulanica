// Making a creature where it will stand (unit 9, DESIGN's R-CREATURE-BUILD-SHEET.md): opened from build mode's
// "Make a creature" tile. The spot 8 m ahead is marked where the society would take the creature in (the
// stand read, GET .../society/stand), or in a world nobody lives in yet at that ground point itself, the person's
// words go in the field, the draft is read every second while
// it is made, and once made the kept kind stands there held by build mode (build-mode.ts's hold), whose own keys
// place it where it was made or put it back. Where the offer offers web notes, a ticked box first asks for notes on
// the words (a reference request, references-api.ts), shows its steps and its notes, and asks the drafter with them;
// where none come, from the words alone. The server's drafter and checks decide what the creature is.
import { CreatureDraftsClient, draftEnded, type CreatureDraft, type CreatureNotesOffer, type CreatureOffer, type SocietyStand } from '../../../web/packages/app/src/creature-drafts-api.ts';
import type { Credentials } from '../../../web/packages/app/src/config.ts';
import { ReferencesClient, referenceFinished, referenceHasNotes, type ReferenceRequest } from '../../../web/packages/app/src/references-api.ts';
import { CREATURE_WORDS, creatureField, leader, madeGroup, makingGroup, placeRow, standLabel, standLight, type MakingGroup } from './world-ui-creature.ts';
import { STEP_WORDS, priceUpTo, stepTime, webTip } from './create-words.mjs';
import { notesSteps, withNotesSpent } from './create-steps.mjs';
import type { Step } from './world-ui.ts';
import { ANCHOR_INSET } from './world-ui-layout.mjs';

/** How far ahead of the eye the stand is looked for (the sheet's 8 m: 3 m falls under the field). */
export const STAND_AHEAD_MM = 8000;
/** The stand's ring on the ground, its radius in metres (the build ring's line and glow; r-creature17t's size). */
export const STAND_RING_M = 1.0;
/** The words one creature may be described with, as the drafter's form states its own. */
const WORDS_MAXIMUM = 400;
/** How long the page follows a notes request before it makes the creature from the words alone and stops the request. */
const NOTES_FOLLOW_MS = 120_000;
/**
 * How long one read of a draft may take before it counts as missed, and how many missed in a row end the making: a
 * read refused, or one that never answers (a request held back by the server), must not leave the page on its step.
 */
const READ_MISSED_MS = 15_000;
const READS_MISSED = 3;

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

/** Where the creature will stand on the region's ground: a society's stand, or a ground point where no society is. */
export type Stand = Pick<SocietyStand, 'positionMm'>;

/**
 * Whether the stand read was refused because the version holds no society (404 `unknown_reference`, as the society's
 * state read is: docs/synthetic-society-contract.md), as in a world nobody lives in yet.
 */
const noSociety = (error: unknown): boolean =>
  (error as { readonly status?: unknown } | null)?.status === 404 && codeOf(error) === 'unknown_reference';

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
  readonly mark: (stand: Stand | null) => { readonly x: number; readonly y: number } | null;
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
  /** Build mode's tray on its Creatures tab with this made creature in focus, where it waits when nothing ahead took it. */
  readonly creatures?: (sha256: string) => void;
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

/** What times a making's steps on its making view. */
export interface MakingClock {
  /** Whether "Waiting to start" is the step under way: nothing after it has shown yet. */
  waiting(): boolean;
  /** The notes request's steps as it serves them now. */
  notes(steps: readonly { readonly step: string; readonly state: string }[]): void;
  /** The drafter is at work: "Making the creature" from now, once. */
  drafting(): void;
  /** The making ended: every time stops, the step under way drawn as not done where `missed`. */
  stop(missed?: boolean): void;
}

/**
 * The making view's steps timed as Create's making view times them (create-world.ts), by this page's clock, since the
 * draft and the notes request state no times: "Waiting to start" from `waitingFrom` (the press) until a step after it
 * shows, once; the notes' steps as their request serves them (create-steps.mjs's notesSteps), each from when this page
 * first saw it; then "Making the creature" from when the drafter was asked, or the read that first found it at work.
 * Each time reads "N s" (create-words.mjs's stepTime), the one under way counting each second while the view shows.
 */
export function makingClock(view: MakingGroup, waitingFrom: number | null): MakingClock {
  let requestSteps: readonly { readonly step: string; readonly state: string }[] = [];
  const noteFrom: Record<string, number> = {}, noteSeconds: Record<string, number> = {};
  let waitingUntil: number | null = null, draftingFrom: number | null = null, stoppedAt: number | null = null, missed = false;
  const draw = (): void => {
    const now = stoppedAt ?? Date.now();
    for (const step of requestSteps) {
      if (step.state !== 'running' && step.state !== 'done' && step.state !== 'missed') continue;
      noteFrom[step.step] ??= now;
      if (step.state === 'running' || noteSeconds[step.step] === undefined) noteSeconds[step.step] = (now - noteFrom[step.step]!) / 1000;
    }
    // A notes step still running when the drafter starts or the making stops was cut off (the page followed it no
    // longer): drawn as not done, so one step at most is under way.
    const notes = (notesSteps(requestSteps, noteSeconds) as Step[])
      .map((step) => step.state === 'now' && (draftingFrom !== null || stoppedAt !== null) ? { ...step, state: 'next' as const } : step);
    const steps: Step[] = [];
    if (waitingFrom !== null) {
      if (waitingUntil === null && (notes.length > 0 || draftingFrom !== null)) waitingUntil = now;
      steps.push({ key: 'queued', words: STEP_WORDS.queued, state: waitingUntil !== null ? 'done' : missed ? 'next' : 'now', time: stepTime(((waitingUntil ?? now) - waitingFrom) / 1000) });
    }
    steps.push(...notes);
    if (draftingFrom !== null) steps.push({ key: 'drafting', words: CREATURE_WORDS.drafting, state: missed ? 'next' : 'now', time: stepTime((now - draftingFrom) / 1000) });
    view.steps(steps);
  };
  // Each second while the view shows; a view taken down (Esc, Try again, made) stops it.
  const tick = setInterval(() => { if (view.root.isConnected) draw(); else clearInterval(tick); }, 1000);
  draw();
  return {
    waiting: () => waitingFrom !== null && waitingUntil === null,
    notes(steps) { if (stoppedAt === null) { requestSteps = steps; draw(); } },
    drafting() { if (stoppedAt === null && draftingFrom === null) { draftingFrom = Date.now(); draw(); } },
    stop(miss = false) {
      if (stoppedAt !== null) return;
      stoppedAt = Date.now();
      missed = miss;
      clearInterval(tick);
      draw();
    },
  };
}

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
  let stand: Stand | null = null;
  let words = '';
  // 'late': the page stopped following a draft the server is still making; it waits in Creatures when done.
  let state: 'describe' | 'making' | 'made' | 'ended' | 'late' = 'describe';
  // Ended with nothing made, whether trying again can help (Try again shows, and Enter does it).
  let retryable = false;
  let ended = false;
  const field = creatureField({ maximum: WORDS_MAXIMUM, onInput: (typed) => { words = typed; foot(); }, onMake: () => { void make(); } });
  // Whether the person ticked the web notes box for this creature (off until ticked, each creature its own choice),
  // whether a notes request was made for the creature being made (its spend is then part of the making's), and whether
  // its making view was drawn for notes.
  let withNotes = false, notesAsked = false, noted = false;
  const label = standLabel(), light = standLight();
  let standAt: { readonly x: number; readonly y: number } | null = null;
  // The made creature that waits in Creatures, nothing ahead having taken it: Back goes there with it in focus.
  let waiting: string | null = null;
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
  /** The composer's foot as Create's: why it cannot make where it cannot, else the most it may cost; Make with words. */
  function foot(): void {
    const refused = offer !== null && !offer.offered ? REFUSED[offer.code ?? ''] ?? CREATURE_WORDS.notOffered : null;
    // With "Search the web" pressed, the price is the whole most, the notes' with the drafter's.
    const most = mostUsd();
    field.composer.say(refused, refused !== null || most === null ? null : priceUpTo(most));
    field.composer.ready(refused === null && offer !== null && sendableWords(words) !== '');
  }
  /** "Search the web" where web notes are offered here, off until pressed (each creature its own choice), its details on hover. */
  function offerNotes(): void {
    const notes = notesOffered();
    field.composer.offerWeb(notes === null ? null : {
      on: withNotes, tip: webTip(notes.searchesAtMost, notes.maximumUsd, 'creature'), onChange: (on) => { withNotes = on; foot(); },
    });
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
    const field = deps.root.querySelector('.wu-creature-field .wu-composer')?.getBoundingClientRect();
    const pill = deps.root.querySelector('.wu-top')?.getBoundingClientRect();
    return at.x >= ANCHOR_INSET && at.x <= innerWidth - ANCHOR_INSET
      && !(field && field.height > 0 && at.y > field.top)
      && !(pill && pill.height > 0 && at.y < pill.bottom);
  }
  /**
   * The stand at the ground point ahead: where the society would take the creature in, or, in a world nobody lives in
   * yet (no society to take it in), that ground point itself, where the tray would place it; then build mode's hold
   * and the server's placing say whether it can stand there, as they do for a thing placed from the tray. None where
   * the read is refused for anything else, or answers that no walking node is open there.
   */
  async function standNear(version: { readonly versionId: string; readonly worldId: string }, point: { readonly xMm: number; readonly zMm: number }): Promise<Stand | null> {
    try {
      return await deps.client.stand(version.versionId, version.worldId, point);
    } catch (error) {
      return noSociety(error) ? { positionMm: [point.xMm, point.zMm] } : null;
    }
  }
  async function findStand(): Promise<void> {
    const version = deps.version(), point = deps.ahead(STAND_AHEAD_MM);
    stand = version === null || point === null ? null : await standNear(version, point);
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

  /** A making on show: its view, and the clock that times its steps. */
  interface Making { readonly view: MakingGroup; readonly clock: MakingClock }

  /**
   * The making view, its light and the stand's label put away: the field gives way to the steps, "Waiting to start"
   * timed from `waitingFrom` (the press) where given.
   */
  function startMaking(waitingFrom: number | null): Making {
    state = 'making';
    field.root.remove();
    const view = makingGroup({ words });
    // With web notes asked for, the view takes the whole width the half leaves from the start, so the notes move
    // nothing when they come; the made card after it keeps that width.
    noted = withNotes && notesOffered() !== null;
    view.root.classList.toggle('wu-creature-noted', noted);
    besideStand(view.root);
    label.remove();
    layer.append(view.root);
    if (standAt !== null) layer.prepend(light);
    return { view, clock: makingClock(view, waitingFrom) };
  }

  /**
   * Web notes on the words before the drafter is asked (Create's frame 21 with "creature"): the request's steps as
   * they pass, each with its time, then its notes; the reference id to draft with, or null where none came, said in
   * place. Esc does not stop it: the page goes on asking, so the creature is still made and waits in Creatures.
   */
  async function followNotes(making: Making, sent: string): Promise<string | null> {
    let request: ReferenceRequest;
    try {
      request = await deps.notes!.request({ purpose: 'things', description: sent, idempotencyKey: deps.key?.() ?? crypto.randomUUID() });
      notesAsked = true;
    } catch {
      making.view.alone(CREATURE_WORDS.notesFailed);
      return null;
    }
    const deadline = Date.now() + NOTES_FOLLOW_MS;
    while (!referenceFinished(request) && Date.now() < deadline) {
      making.clock.notes(request.steps);
      await wait(1000);
      request = await deps.notes!.read(request.referenceId).catch(() => request);
    }
    making.clock.notes(request.steps);
    if (!referenceFinished(request)) {
      // Past the time the page follows it: it is stopped, and the creature is made from the words alone.
      void deps.notes!.cancel(request.referenceId).catch(() => null);
      making.view.alone(CREATURE_WORDS.notesFailed, request.searches.length);
      return null;
    }
    if (referenceHasNotes(request)) {
      making.view.notes(request.notes, request.searches.length);
      return request.referenceId;
    }
    making.view.alone(request.status === 'complete' || request.status === 'partial' ? CREATURE_WORDS.notesNone : CREATURE_WORDS.notesFailed, request.searches.length);
    return null;
  }

  /** One read of the draft, or null where it is refused or has not answered in READ_MISSED_MS. */
  function readDraft(draftId: string): Promise<CreatureDraft | null> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => { resolve(null); }, READ_MISSED_MS);
      deps.client.draft(draftId).then((read) => { clearTimeout(timer); resolve(read); }, () => { clearTimeout(timer); resolve(null); });
    });
  }

  /**
   * Follows `draft` on its making view until it ends: one found on opening gets a view of its own, waiting where it is
   * still queued. "Making the creature" begins at once after the notes' steps, as the draft's own wait is part of it, and
   * otherwise once a read finds the drafter at work.
   */
  async function follow(draft: CreatureDraft, making: Making = startMaking(draft.status === 'queued' ? Date.now() : null)): Promise<void> {
    const started = Date.now();
    const timeout = offer?.timing.timeoutSeconds ?? 50;
    const deadline = started + (2 * timeout + 10) * 1000;
    let current = draft, missed = 0;
    const draw = (read: CreatureDraft): void => { if (read.status !== 'queued' || !making.clock.waiting()) making.clock.drafting(); };
    draw(current);
    showSpent(making.view, current);
    while (!ended && !draftEnded(current) && Date.now() < deadline && missed < READS_MISSED) {
      await wait(1000);
      if (ended) return;
      const read = await readDraft(current.draftId);
      if (ended) return;
      missed = read === null ? missed + 1 : 0;
      if (read !== null) { current = read; draw(current); showSpent(making.view, current); }
    }
    if (ended) return;
    light.remove();
    if (missed >= READS_MISSED) {
      // The draft can no longer be read: how it went is not known here, so the page says so, where a made creature
      // would be, and offers Try again (a draft still being made is then followed rather than asked twice).
      state = 'ended';
      retryable = true;
      making.clock.stop(true);
      making.view.ended(CREATURE_WORDS.cantTell, tryAgain, null);
      return;
    }
    if (current.status === 'kept' && current.kind !== null) {
      state = 'made';
      making.clock.stop();
      making.view.root.remove();
      const card = madeGroup({
        label: current.label, words, modelName: current.model?.name ?? null, spentUsd: spentOf(current),
        notes: current.references?.state === 'used' ? current.references.notes : 0,
        placeable: stand !== null, onBack: back,
      });
      card.classList.toggle('wu-creature-noted', noted);
      besideStand(card);
      layer.append(card);
      if (stand === null) waiting = current.kind.sha256;
      else {
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
      making.clock.stop();
      making.view.late(CREATURE_WORDS.takingLonger);
      return;
    }
    state = 'ended';
    // A refused draft says its check's own sentence; changed words may pass, so Try again shows under it too.
    const failed = current.refusal !== null ? { words: current.refusal.detail, retry: true } : FAILED[current.failure ?? ''] ?? { words: CREATURE_WORDS.wentWrong, retry: true };
    retryable = failed.retry;
    making.clock.stop(true);
    making.view.ended(failed.words, retryable ? tryAgain : null, spentOf(current));
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

  /**
   * Under the steps, what the making has spent so far of the most it may, counted as Create's making view counts it
   * (create-steps.mjs's withNotesSpent): what the draft's attempts settled at, what those under way hold as not known
   * yet, and where web notes were asked for, what their model calls spent, or their most as not known yet where the
   * read states none. Nothing where the draft states no spend or a part has no most to count, so the line never says
   * less than may have been spent.
   */
  function showSpent(making: MakingGroup, draft: CreatureDraft): void {
    const price = offer?.priceUsdAtMost ?? null;
    if (draft.spentUsd === null || draft.spentUsd === undefined || price === null) return;
    const own = { spentUsd: Number(draft.spentUsd), unknownUsd: Number(draft.heldUsd ?? 0) };
    if (!notesAsked && (draft.references ?? null) === null) { making.spent(own, price); return; }
    const notesMost = offer?.notes?.maximumUsd ?? null;
    const spent = notesMost === null ? null : withNotesSpent(own, draft.references?.spentUsd ?? null, notesMost);
    if (notesMost !== null && spent !== null) making.spent(spent, addUsd(price, notesMost));
  }

  /** Back to the field with the words kept, as Enter does where "[↵] Try again" shows. */
  function tryAgain(): void {
    if (state !== 'ended' || ended) return;
    state = 'describe';
    layer.replaceChildren(field.root);
    foot();
    field.composer.field.focus();
  }

  async function make(): Promise<void> {
    if (state !== 'describe' || offer === null || !offer.offered) return;
    const sent = sendableWords(words);
    if (sent === '') return;
    words = sent;
    notesAsked = false;
    // "Waiting to start" is timed from the press, as Create's is.
    const pressed = Date.now();
    // With the box ticked, the notes first, on the making view, and the drafter asked with them where they came.
    const making = withNotes && notesOffered() !== null ? startMaking(pressed) : null;
    const referenceId = making === null ? null : await followNotes(making, sent);
    let asked: CreatureDraft;
    try {
      asked = await deps.client.ask(sent, referenceId);
    } catch (error) {
      const code = codeOf(error);
      // One draft open at a time: the one being made is followed rather than refused (a second page asked it).
      const running = code === 'creature_limit_reached' ? (await deps.client.drafts().catch(() => [])).find((draft) => !draftEnded(draft)) : undefined;
      if (running !== undefined) { await follow(running, making ?? startMaking(pressed)); return; }
      const refused = code === 'creature_limit_reached' ? CREATURE_WORDS.hourLimit : REFUSED[code ?? ''] ?? CREATURE_WORDS.wentWrong;
      if (making === null) { field.composer.say(refused, null); return; }
      // Refused after the notes: the making view says why, and Try again goes back to the field with the words.
      state = 'ended';
      retryable = true;
      making.clock.stop(true);
      making.view.ended(refused, tryAgain, null);
      return;
    }
    await follow(asked, making ?? startMaking(pressed));
  }

  /** Back to building, and where the made creature waits in Creatures, to it there (Esc does the same). */
  function back(): void {
    destroy();
    deps.close();
    if (waiting !== null) deps.creatures?.(waiting);
  }

  function destroy(): void {
    if (ended) return;
    ended = true;
    deps.mark(null);
    layer.remove();
  }

  offer = await deps.client.offer().catch(() => null);
  foot();
  offerNotes();
  await findStand();
  globalThis.requestAnimationFrame?.(track);
  const running = offer?.offered ? (await deps.client.drafts().catch(() => [])).find((draft) => !draftEnded(draft)) : undefined;
  if (running !== undefined) void follow(running);
  else field.composer.field.focus();

  return {
    key(event) {
      if (ended) return false;
      if (event.key === 'Escape') { event.preventDefault(); back(); return true; }
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
  /** Opens the tray on its Creatures tab with that made creature in focus. */
  readonly creatures: (sha256: string) => void;
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
      creatures: hand.creatures,
      close,
      release: () => { hand.showing(true); },
    }).then((screen) => { open = screen; }, () => { close(); }).finally(() => { opening = false; });
  };
}

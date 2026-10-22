// Making a creature where it will stand (unit 9, DESIGN's R-CREATURE-BUILD-SHEET.md): opened from build mode's
// "Make a creature" tile. The spot 8 m ahead is marked where the society would take the creature in (the
// stand read, GET .../society/stand), the person's words go in the field, the draft is read every second while
// it is made, and once made the kept kind stands there held by build mode (build-mode.ts's hold), whose own keys
// place it where it was made or put it back. The server's drafter and checks decide what the creature is.
import { CreatureDraftsClient, draftEnded, type CreatureDraft, type CreatureOffer, type SocietyStand } from '../../../web/packages/app/src/creature-drafts-api.ts';
import type { Credentials } from '../../../web/packages/app/src/config.ts';
import { CREATURE_WORDS, creatureField, leader, madeGroup, makerLine, makingGroup, standLabel, standLight } from './world-ui-creature.ts';
import { ANCHOR_INSET } from './world-ui-layout.mjs';

/** How far ahead of the eye the stand is looked for (the sheet's 8 m: 3 m falls under the field). */
export const STAND_AHEAD_MM = 8000;
/** The stand's ring on the ground, its radius in metres (the build ring's line and glow; r-creature17t's size). */
export const STAND_RING_M = 1.0;
/** The words one creature may be described with, as the drafter's form states its own. */
const WORDS_MAXIMUM = 400;

/** Why a world may not ask, or an ask was refused, in words, by code (M10 and M11). */
const REFUSED: Readonly<Record<string, string>> = Object.freeze({
  creatures_not_run_here: CREATURE_WORDS.notOffered,
  models_not_configured: CREATURE_WORDS.notOffered,
  spending_refused: CREATURE_WORDS.budgetSpent,
});

/** How a hold ends, as build mode answers it. */
export type Held = { readonly outcome: 'placed'; readonly thingId: string } | { readonly outcome: 'put-back' } | null;

export interface CreatureScreenDeps {
  readonly root: HTMLElement;
  readonly client: Pick<CreatureDraftsClient, 'offer' | 'drafts' | 'ask' | 'draft' | 'stand'>;
  /** The open version and the world it belongs to. */
  readonly version: () => { readonly versionId: string; readonly worldId: string } | null;
  /** The region-frame point on the ground this far ahead of the eye, or null where none is in view. */
  readonly ahead: (millimetres: number) => { readonly xMm: number; readonly zMm: number } | null;
  /** The ring on the ground at the stand, and the screen point the label floats at; hidden with null. */
  readonly mark: (stand: SocietyStand | null) => { readonly x: number; readonly y: number } | null;
  /** Where the held creature's head shows on the screen, for the made card's leader; null where it is not drawn. */
  readonly head?: () => { readonly x: number; readonly y: number } | null;
  /** Build mode's hold: the kept kind held at the stand's point to be placed. */
  readonly hold: (kind: { readonly source: 'workspace'; readonly sha256: string }, at: { readonly xMm: number; readonly zMm: number }) => Promise<Held>;
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
  let state: 'describe' | 'making' | 'made' | 'ended' = 'describe';
  let ended = false;
  const field = creatureField({ maximum: WORDS_MAXIMUM, onMake: () => { void make(); } });
  const label = standLabel(), light = standLight();
  let standAt: { readonly x: number; readonly y: number } | null = null;
  layer.append(field.root);

  function lineUnder(): void {
    if (offer !== null && !offer.offered) { field.line(REFUSED[offer.code ?? ''] ?? CREATURE_WORDS.notOffered, true); return; }
    field.line(makerLine(offer?.priceUsdAtMost ?? null, offer?.timing.typicalSeconds ?? null));
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
    pointer.draw(head, { x: box.left, y: title ? title.top + title.height / 2 : box.top });
  }
  field.input.addEventListener('input', () => { words = field.input.value; field.count(words.length, WORDS_MAXIMUM); });
  field.count(0, WORDS_MAXIMUM);

  async function follow(draft: CreatureDraft): Promise<void> {
    state = 'making';
    field.root.remove();
    const making = makingGroup({ words, priceUsdAtMost: offer?.priceUsdAtMost ?? null });
    label.remove();
    layer.append(making.root);
    if (standAt !== null) layer.prepend(light);
    const started = Date.now();
    const timeout = offer?.timing.timeoutSeconds ?? 50;
    const deadline = started + (2 * timeout + 10) * 1000;
    let current = draft;
    while (!ended && !draftEnded(current) && Date.now() < deadline) {
      const seconds = Math.floor((Date.now() - started) / 1000);
      making.step(current.status === 'queued' ? CREATURE_WORDS.waiting : CREATURE_WORDS.drafting, false, `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`);
      await wait(1000);
      if (ended) return;
      current = await deps.client.draft(current.draftId);
    }
    if (ended) return;
    light.remove();
    if (current.status === 'kept' && current.kind !== null) {
      state = 'made';
      making.root.remove();
      layer.append(madeGroup({
        label: current.label, words, modelName: current.model?.name ?? null, spentUsd: current.spentUsd ?? null,
        // Until its made look is made, the creature wears its sketch (M15).
        sketch: current.lookStatus !== 'made', placeable: stand !== null,
      }));
      if (stand !== null) {
        // It stands where it was made, held to be placed (B8): build mode draws it there and its own keys place it or
        // put it back; either way this step ends, and a creature put back waits in Creatures.
        label.remove();
        deps.mark(null);
        deps.release();
        const at = { xMm: stand.positionMm[0], zMm: stand.positionMm[1] };
        void deps.hold({ source: 'workspace', sha256: current.kind.sha256 }, at).then(() => {
          if (!ended) { destroy(); deps.close(); }
        });
      }
      return;
    }
    state = 'ended';
    making.step(current.refusal?.detail ?? REFUSED[current.failure ?? ''] ?? CREATURE_WORDS.notOffered, true);
  }

  async function make(): Promise<void> {
    if (state !== 'describe' || offer === null || !offer.offered || words.trim() === '') return;
    let asked: CreatureDraft;
    try {
      asked = await deps.client.ask(words);
    } catch {
      field.line(CREATURE_WORDS.notOffered, true);
      return;
    }
    await follow(asked);
  }

  function destroy(): void {
    if (ended) return;
    ended = true;
    deps.mark(null);
    layer.remove();
  }

  offer = await deps.client.offer().catch(() => null);
  lineUnder();
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
        if (state === 'ended') { event.preventDefault(); state = 'describe'; layer.replaceChildren(field.root); lineUnder(); field.input.focus(); return true; }
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
  let open: CreatureScreen | null = null, opening = false;
  return (hand) => {
    if (open !== null || opening) return;
    opening = true;
    const close = (): void => { open = null; hand.showing(false); };
    hand.showing(true, (event) => { open?.key(event); });
    void openCreatureScreen({
      root: document.getElementById('contextual-world') ?? document.body,
      client,
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

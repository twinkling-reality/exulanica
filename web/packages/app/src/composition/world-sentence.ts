/**
 * One sentence makes a world, inside Create a world: where the server offers drafting, the sheet
 * shows one box and nothing else (`../ui/world-sentence.ts`), and a world made from it opens as a
 * world made any other way does. A stand-in for the workshop's own first act, wired to the same
 * routes (`GET /worlds/drafts`, `POST /worlds/drafts`, `GET /worlds/drafts/{draft_id}`).
 */

import type { TransportOptions } from '@exulanica/graph-client';
import { buildWorldSentence } from '../ui/world-sentence.js';
import type { SavedWorldEntry } from '../world-entry-api.js';
import { WorldMakingClient, type WorldDraftOffer } from '../world-making-api.js';

/**
 * The codes of the offer (`GET /worlds/drafts`) under which this person never drafts here: a
 * server that makes nothing from words, no right to ask a model, or no model on the server. Any
 * other refusal passes (a draft running, the hour's starts, the allowance, the worlds held), and
 * the box says it before a word is typed.
 */
export const NEVER_DRAFTS: ReadonlySet<string> = new Set([
  'kinds_from_people_not_offered', 'not_authorised', 'provider_credential_absent',
]);

/** Whether Create a world is the one box for this offer, or stays the recipes. */
export function sentenceOffered(offer: WorldDraftOffer): boolean {
  return offer.offered || !NEVER_DRAFTS.has(offer.code ?? '');
}

/** What a draft would meet here now; a server without the route refuses the read. */
export function readWorldDraftOffer(credentials: TransportOptions): Promise<WorldDraftOffer> {
  return new WorldMakingClient(credentials).offer();
}

/** The sheet the box is shown in, by the one hook it offers for it. */
export interface SentenceSheet {
  readonly root: HTMLElement;
  showSentence(box: HTMLElement): void;
  showRecipes(): void;
}

export function attachWorldSentence(sheet: SentenceSheet, options: {
  readonly credentials: TransportOptions;
  /** The offer the sheet was decided by. */
  readonly offer: WorldDraftOffer;
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  /** Called once the recipes are back in the sheet, where no draft can be started now. */
  readonly recipes: () => void;
}): void {
  const client = new WorldMakingClient(options.credentials);
  const box = buildWorldSentence({
    offer: options.offer,
    readOffer: () => client.offer(),
    start: (description) => client.start(description),
    read: (draftId) => client.read(draftId),
    open: options.open,
    recipes: () => {
      sheet.showRecipes();
      options.recipes();
    },
  });
  sheet.showSentence(box.root);
  // The sheet is a dialog the person has just opened: focus goes to the field, the one way in.
  box.focus();
}

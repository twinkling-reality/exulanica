/**
 * The pictures on the cards a world is started from: Create a world's cards and the shell's recipe
 * buttons. Each is the first view of a world made from that card on main, captured when a release
 * is built (`scripts/capture_card_pictures.py`) and shipped in `public/card-pictures/` with its
 * record. Every press of a card makes another world, so the picture is one world made from it, in
 * the same look. A card shows its entry's picture only where the record states what is served for
 * the card now (a recipe's values, or a kind's version and digest); any other card, and every card
 * when the record cannot be read, shows its quiet tile.
 */

export const CARD_PICTURES_PROFILE = 'exulanica.card-pictures/v1';
const RECORD = '/card-pictures/card-pictures.v1.json';
/** A picture is a file beside the record, named by its card: never a path or an address. */
const PICTURE_NAME = /^[a-z0-9_-]+\.jpg$/;

export interface CardPictureEntry {
  readonly card: string;
  readonly reference: Readonly<Record<string, unknown>>;
  readonly picture: string;
}

export type CardPictures = ReadonlyMap<string, CardPictureEntry>;

/** What is served for a card now: a recipe's values, or a kind's version and digest. */
export type ServedCard =
  | { readonly values: Readonly<Record<string, number | string>> }
  | { readonly version: number; readonly sha256: string };

/** The record's entries by card, or null where it cannot be read or states another profile. */
export async function readCardPictures(read: (address: string) => Promise<Response> = fetch): Promise<CardPictures | null> {
  try {
    const answer = await read(RECORD);
    if (!answer.ok) return null;
    const body = (await answer.json()) as { readonly profile?: unknown; readonly entries?: unknown };
    if (body.profile !== CARD_PICTURES_PROFILE || !Array.isArray(body.entries)) return null;
    const entries = new Map<string, CardPictureEntry>();
    for (const raw of body.entries as unknown[]) {
      if (raw === null || typeof raw !== 'object') continue;
      const { card, reference, picture } = raw as Record<string, unknown>;
      if (typeof card !== 'string' || typeof picture !== 'string' || !PICTURE_NAME.test(picture)) continue;
      if (reference === null || typeof reference !== 'object') continue;
      entries.set(card, { card, reference: reference as Record<string, unknown>, picture });
    }
    return entries;
  } catch {
    return null;
  }
}

const sameValues = (recorded: unknown, served: Readonly<Record<string, number | string>>): boolean => {
  if (recorded === null || typeof recorded !== 'object') return false;
  const held = recorded as Record<string, unknown>;
  const keys = Object.keys(served);
  return keys.length === Object.keys(held).length && keys.every((key) => held[key] === served[key]);
};

/** The address of `card`'s picture, or null: its entry must record what is served for it now. */
export function cardPicture(pictures: CardPictures | null, card: string, served: ServedCard): string | null {
  const entry = pictures?.get(card);
  if (!entry) return null;
  const matches = 'values' in served
    ? sameValues(entry.reference['values'], served.values)
    : entry.reference['version'] === served.version && entry.reference['sha256'] === served.sha256;
  return matches ? `/card-pictures/${entry.picture}` : null;
}

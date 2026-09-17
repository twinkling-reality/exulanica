/**
 * The one refusal lettering throws, and the reasons it can carry: the copy of
 * `exulanica.lettering.refusal`. Only the reason is shared between the two languages; the message
 * says what was wrong in words, and the shared cases compare reasons.
 */

/** Why a glyph catalog is refused, in the order the reader checks. */
export const CATALOG_REASONS = [
  'json',
  'shape',
  'promise',
  'characters',
  'kerning',
  'ring',
  'metrics',
] as const;
/** Why a sign layout is refused, in the order the layout rule checks. */
export const LAYOUT_REASONS = [
  'alignment',
  'cap_height',
  'tracking',
  'box',
  'text',
  'character',
  'fit',
  'touch',
] as const;

export type CatalogReason = (typeof CATALOG_REASONS)[number];
export type LayoutReason = (typeof LAYOUT_REASONS)[number];

export class LetteringRefusal extends Error {
  constructor(
    readonly reason: CatalogReason | LayoutReason,
    message: string,
  ) {
    super(`${reason}: ${message}`);
    this.name = 'LetteringRefusal';
  }
}

export function refuse(reason: CatalogReason | LayoutReason, message: string): never {
  throw new LetteringRefusal(reason, message);
}

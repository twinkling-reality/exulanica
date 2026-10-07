/**
 * Where a thing and its look came from, in words, from their origin records alone: one rule per
 * origin class and per licence fact, never per kind, look or source, so a kind drafted or imported
 * tomorrow reads correctly with no code.
 */
import type { OriginRecord } from '../thing-card-api.js';
import { authorWords, licenceWords } from '../ui/look-sheet.js';
import type { CardLink } from '../ui/thing-card.js';

/** The host a source reference names, for its link's words; the reference itself when it is no URL. */
export function sourceName(reference: string): string {
  try {
    const url = new URL(reference);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.host : reference;
  } catch {
    return reference;
  }
}

const httpLink = (reference: string | undefined): string | null => {
  if (reference === undefined) return null;
  try {
    const url = new URL(reference);
    return url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
};

/** Who made a look and its licence, in a line: "By Kay Lousberg. CC0, free to use." */
export function lookLine(origin: OriginRecord): string {
  const who = authorWords(origin.authors) || (origin.by === 'project' ? 'Made for Exulanica' : '');
  const licence = licenceWords({ id: origin.licence.spdx, attribution: null });
  return who === '' ? `${licence}.` : `${who}. ${licence}.`;
}

/** The first source a person can open, or null. */
export function sourceLink(origin: OriginRecord): CardLink | null {
  const href = httpLink(origin.sources[0]);
  return href === null ? null : { text: `From ${sourceName(href)}`, href };
}

/**
 * The credit a licence asks for, whenever it asks: attribution, or share-alike terms. Null for a
 * licence that asks for neither (CC0), so the card shows a credit exactly where one is owed.
 */
export function creditOf(origin: OriginRecord): CardLink | { readonly text: string; readonly href: null } | null {
  const { attribution, shareAlike, spdx, url } = origin.licence;
  if (attribution === null && !shareAlike) return null;
  const who = attribution ?? (origin.authors.length > 0 ? origin.authors.join(', ') : null);
  const terms = shareAlike ? `${spdx}, share alike` : spdx;
  const text = who === null ? `Credit: ${terms}` : `Credit: ${who}, ${terms}`;
  const href = httpLink(url ?? undefined) ?? httpLink(origin.sources[0]);
  return href === null ? { text, href: null } : { text, href };
}

/** Where a kind of thing came from, after "You placed it here." */
export function kindCameWords(label: string, origin: OriginRecord): string {
  const a = `A ${label}`;
  switch (origin.class) {
    case 'authored':
      return origin.by === 'project' ? `${a} is one of Exulanica's own kinds.` : `${a} is a kind made in this workspace.`;
    case 'drafted':
      return `${a} is a kind a model drafted from words.`;
    case 'generated':
      return `${a} is a kind a model generated.`;
    case 'uploaded':
      return `${a} is a kind added in this workspace.`;
    case 'imported': {
      const source = origin.sources[0];
      return source === undefined ? `${a} is an imported kind.` : `${a} is a kind imported from ${sourceName(source)}.`;
    }
    case 'crossed':
      return `${a} came in from outside this world.`;
  }
}

import type { FixtureSeat } from '@exulanica/atlas-react/playcanvas';

let held: { readonly entryId: string; readonly versionId: string; readonly seats: readonly FixtureSeat[] } | null = null;
const listeners = new Set<() => void>();
const changed = (): void => { for (const listener of listeners) listener(); };

/** Contact belongs to one attached saved version. An older disposer cannot withdraw its replacement. */
export function rememberSiteSeats(entryId: string, versionId: string, seats: readonly FixtureSeat[]): () => void {
  const publication = { entryId, versionId, seats };
  held = publication;
  changed();
  return () => {
    if (held !== publication) return;
    held = null;
    changed();
  };
}

export function siteSeats(entryId: string | null | undefined, versionId: string | null | undefined): readonly FixtureSeat[] {
  return held !== null && held.entryId === entryId && held.versionId === versionId ? held.seats : [];
}

export function onSiteSeatsChanged(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

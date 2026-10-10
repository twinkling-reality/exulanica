/**
 * How the page draws what a society records, where the record leaves it open: read from the one
 * data file that states each value with its reason,
 * `assets/catalogs/society-presentation/society-presentation.v1.json`. Presentation only: nothing
 * here changes a recorded position, path or event.
 */
import catalogText from '../../../../assets/catalogs/society-presentation/society-presentation.v1.json?raw';

interface PresentationEntry {
  readonly key: string;
  readonly value: number;
  readonly unit: string;
  readonly reason: string;
}

function readCatalog(text: string): ReadonlyMap<string, PresentationEntry> {
  const document = JSON.parse(text) as { readonly profile?: unknown; readonly entries?: readonly PresentationEntry[] };
  if (document.profile !== 'exulanica.society-presentation/v1' || !Array.isArray(document.entries)) {
    throw new Error('not the society presentation catalog');
  }
  const entries = new Map<string, PresentationEntry>();
  for (const entry of document.entries) {
    if (typeof entry.key !== 'string' || !Number.isFinite(entry.value) || !entry.reason || entries.has(entry.key)) {
      throw new Error(`society presentation entry ${String(entry.key)} is malformed`);
    }
    entries.set(entry.key, entry);
  }
  return entries;
}

const ENTRIES = readCatalog(catalogText);

function millimetres(key: string): number {
  const entry = ENTRIES.get(key);
  if (entry === undefined || entry.unit !== 'millimetre' || entry.value < 0) {
    throw new Error(`the society presentation catalog states no ${key} in millimetres`);
  }
  return entry.value;
}

/** How far apart two people who stand talking are drawn when recorded nearer, in metres. */
export const CONVERSATION_DISTANCE_METRES = millimetres('conversation_distance_mm') / 1000;

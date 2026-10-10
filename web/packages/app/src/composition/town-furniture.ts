/**
 * The street furniture of the generated town that is open, as its own tile records state it.
 *
 * A town's tiles are read where the town is opened (`generated-world.ts`, loaded only when a town
 * is), and its people are drawn elsewhere (`environment-selection.ts`), on every page. This keeps
 * what the first read for the second, by the saved entry it was read for, so the people of a town
 * can be drawn on its benches without the page that draws them loading a town's code. One town is
 * open at a time, so one entry's furniture is kept.
 */
import type { StreetFurniture } from '@exulanica/atlas-react/playcanvas';

let held: { readonly entryId: string; readonly furniture: readonly StreetFurniture[] } | null = null;

/** Keep the furniture read for a saved entry's town, in place of any kept before. */
export function rememberTownFurniture(entryId: string, furniture: readonly StreetFurniture[]): void {
  held = { entryId, furniture };
}

/** The furniture kept for a saved entry's town; none for another entry, or where none was read. */
export function townFurniture(entryId: string | null | undefined): readonly StreetFurniture[] {
  return held !== null && held.entryId === entryId ? held.furniture : [];
}

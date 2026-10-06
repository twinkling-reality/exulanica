import { decodeOwd, facadeFrame, facadeOpenings, faceLayout, type FacadeFields, type MassingFields } from '@exulanica/loom-tess/core';

/**
 * Where a town's windows are: one slot per opening a facade cuts, for whatever dresses it.
 *
 * The tessellator cuts each opening out of its wall and lines it with a reveal; it draws nothing in
 * it. A style pack's window piece fills that hole, so the hole's place, size and facing are read
 * here from the same rules the tessellator cuts by (`facadeFrame`, `faceLayout`, `facadeOpenings`),
 * never derived a second time.
 *
 * A slot is a box in city millimetres: its base centre at the middle of the sill line, set into the
 * wall half the reveal's depth; its width along the face, its depth the reveal's, its height from
 * the sill to the head, or to the springing line of an arched head, where the jambs stop and the
 * arch begins, so a rectangular piece never covers the arch's curve; its front the face's outward
 * side. Its look role is `window.<head treatment>`, so a pack can dress arched and flat heads apart.
 *
 * Only facades the tile owns give slots, so a building at a tile boundary is dressed once.
 */

/** What this reads of a record in a tile's header. */
export interface SlotRecord {
  readonly kind: string;
  readonly fields: Readonly<Record<string, unknown>>;
  readonly membership: string;
}

export interface OpeningSlot {
  /** The facade's identity and the opening's place in its face, storey then bay. */
  readonly identity: string;
  readonly facadeIdentity: string;
  readonly lookRole: string;
  /** City millimetres: east, north, up. */
  readonly positionMm: readonly [number, number, number];
  /** The face's outward direction in plan, a unit vector (east, north). */
  readonly front: readonly [number, number];
  /** Width along the face, depth into it, height. */
  readonly boxMm: readonly [number, number, number];
}

/** Chords of an arched head may sit this far from its circle; the slot reads only its bounds. */
const SLOT_RESOLUTION_MM = 50;

export function openingSlots(records: readonly SlotRecord[]): OpeningSlot[] {
  const massings = new Map<string, MassingFields>();
  for (const record of records) {
    if (record.kind === 'city.massing') massings.set(record.fields['identity'] as string, record.fields as unknown as MassingFields);
  }
  const slots: OpeningSlot[] = [];
  for (const record of records) {
    if (record.kind !== 'city.facade' || record.membership !== 'owned') continue;
    const facade = record.fields as unknown as FacadeFields;
    if (facade.openings.length === 0) continue;
    const where = `city.facade ${facade.identity}`;
    const massing = massings.get(facade.building_identity);
    if (massing === undefined) continue;
    const frame = facadeFrame(facade, massing, where);
    const { region } = faceLayout(facade, frame, where);
    const openings = facadeOpenings(facade, massing, region, SLOT_RESOLUTION_MM, where);
    const dx = (frame.to[0] - frame.from[0]) / frame.run;
    const dy = (frame.to[1] - frame.from[1]) / frame.run;
    // The outward side is the right of the edge's direction, as the tessellator sets faces off it.
    const front: [number, number] = [dy, -dx];
    const head = (facade.openings[0] as unknown as { head_treatment?: unknown }).head_treatment;
    const lookRole = typeof head === 'string' && /^[a-z][a-z0-9_]{0,47}$/.test(head) ? `window.${head}` : 'window.default';
    openings.forEach((opening, index) => {
      const us = opening.outline.map((point) => point[0]);
      const zs = opening.outline.map((point) => point[1]);
      const uLow = Math.min(...us);
      const uHigh = Math.max(...us);
      const zLow = Math.min(...zs);
      // The jambs' tops: the highest points on either side, which for a flat head is the head.
      const zHigh = Math.max(...opening.outline.filter((point) => point[0] - uLow < 1 || uHigh - point[0] < 1).map((point) => point[1]));
      const along = (uLow + uHigh) / 2;
      const inset = opening.revealDepthMm / 2;
      slots.push({
        identity: `${facade.identity}#${index}`,
        facadeIdentity: facade.identity,
        lookRole,
        positionMm: [frame.from[0] + dx * along - front[0] * inset, frame.from[1] + dy * along - front[1] * inset, zLow],
        front,
        boxMm: [uHigh - uLow, opening.revealDepthMm, zHigh - zLow],
      });
    });
  }
  return slots;
}

/** The window slots of the facades each tile container owns, read with the tessellator's own decoder. */
export function containerOpeningSlots(containers: readonly Uint8Array[]): OpeningSlot[] {
  return openingSlots(containers.flatMap((bytes) => decodeOwd(bytes).header.records));
}

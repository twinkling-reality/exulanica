/**
 * The gate each visitor who crossed in came through, for the crowd to draw it stepping out of the
 * gate when it arrives and back into it when it leaves (`AuthoredRegionSociety.setGates`). Its
 * `thing_arrived` event names the gate's placement, which the state's things place: the gate's own
 * position, millimetres in the society's frame. A gate once read is kept while the society is the
 * same one, so a visitor whose arrival has left the events read still goes home through its gate.
 */

import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import type { SocietyEvent } from '../society-api.js';

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

export class VisitorGates {
  #societyId: string | null = null;
  readonly #gates = new Map<string, readonly [number, number]>();

  /** Each visitor's gate read so far, by the visitor's id. */
  get gates(): ReadonlyMap<string, readonly [number, number]> {
    return this.#gates;
  }

  /** Read the arrivals among `events` against `state`; true when a gate was learnt. */
  see(societyId: string, events: readonly SocietyEvent[], state: OwnedSocietyState): boolean {
    if (societyId !== this.#societyId) {
      this.#societyId = societyId;
      this.#gates.clear();
    }
    const placed = new Map<string, readonly [number, number]>();
    for (const thing of state.things ?? []) {
      if (thing.placed_id != null && thing.position_mm != null) placed.set(thing.placed_id, [thing.position_mm[0], thing.position_mm[1]]);
    }
    let learnt = false;
    for (const event of events) {
      if (event.event_kind !== 'thing_arrived' || this.#gates.has(event.subject_id)) continue;
      const thing = record(record(event.document)['thing']);
      const gate = thing['came_by'] === 'crossed' && typeof thing['gate'] === 'string' ? placed.get(thing['gate']) : undefined;
      if (gate === undefined) continue;
      this.#gates.set(event.subject_id, gate);
      learnt = true;
    }
    return learnt;
  }
}

/**
 * THE ROUTE OBSTRUCTION RINGS OF A BAKED TILE, READ FROM THE CONTAINER RATHER THAN DERIVED AGAIN.
 *
 * A consumer that chooses where to walk needs to know what a walk must go round. The tessellator
 * already works that out to carve support, from the grammar's own navigation table: one convex
 * integer plan region per part of a record standing below the capsule height its grammar measures,
 * and the base ring of a record that obstructs with one. This file hands that same answer to
 * anybody holding a decoded container, so there is ONE implementation rather than a second reader
 * that disagrees about a bench and nothing to say which of the two a walk was scored against.
 *
 * IT IS NOT COLLISION AND MUST NOT BE PROMOTED TO IT. These rings drop everything above head height
 * by design, they carry NO HEIGHT at all, and nothing in them stops a body: they say which way a
 * walk can face. A capsule clearance is not a solid, which the nav_envelope contract states in as
 * many words, and `collision_proxy` is the projection for solid occupancy and has no contract yet.
 * A reader that fabricates a top for one of these regions is measuring a shape no record states.
 *
 * WHY THIS IS NOT THE RE-DERIVATION IT LOOKS LIKE, and the one condition that keeps it so. The
 * rings are worked out here from the container's own records and its grammar table, at read time,
 * not carried in the container: no `.owd` holds a ring set. That would be a second reader, except
 * that `decodeOwd` REFUSES a container whose `tessellator_version` is not this source version. So
 * the code computing a ring is necessarily the code that baked the tile it came from, and the two
 * cannot silently diverge. IF THAT PIN EVER LOOSENS THIS BECOMES WRONG: guaranteed identical would
 * become usually agree, and a walk could be scored against obstacles the tile does not have.
 *
 * HALO RECORDS OBSTRUCT TOO. A bench just over the tile boundary turns a walk on this side of it,
 * so the rings come from every record the container carries, owned or halo, exactly as the carve
 * reads them. What a halo record does NOT do is draw, and nothing here draws.
 */
import { tableOf } from './document.js';
import { capsuleOf, obstructionsOf } from './expand.js';
import type { ObstructionRegion } from './expand.js';
import type { OwdHeader } from './owd.js';
import { navigationRowOf } from './record-shapes.js';

/**
 * Every route obstruction ring the records of a baked tile state, in the container's record order,
 * each naming the record it came from. Empty when no kind the tile carries obstructs.
 */
export function routeObstructionRings(header: OwdHeader): ObstructionRegion[] {
  const rings: ObstructionRegion[] = [];
  for (const record of header.records) {
    const grammar = header.grammars[record.grammar];
    if (grammar === undefined) continue;
    const table = tableOf(grammar);
    const row = navigationRowOf(table, record.kind);
    for (const region of obstructionsOf(record.kind, row.obstruction, record.fields, capsuleOf(table), `${record.kind} ${record.identity}`)) {
      rings.push(region);
    }
  }
  return rings;
}

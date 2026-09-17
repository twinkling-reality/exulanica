/**
 * WHAT AN EXPANDER DRAWS: PIECES, EACH WITH ITS OWN VERTICES AND, WHERE THE PROJECTION CARRIES
 * THEM, ONE SURFACE.
 *
 * Its own module, so the rules that build pieces (`streets.ts`) and the table of rules that calls
 * them (`expand.ts`) need not import each other.
 */
import type { SurfaceOrientation } from './triangle-digest.js';

export interface SurfaceExpansion {
  /** The grammar's surface role the piece draws; the material record for (record, role) dresses it. */
  readonly role: string;
  readonly orientation: SurfaceOrientation;
  /** Absolute surface coordinates in millimetres, two per vertex of the piece. */
  readonly coordinates: readonly number[];
}

/**
 * One group of faces an expander draws, with vertices of its own. In a projection that carries
 * surfaces every piece is one surface, and an entry may repeat a role only on another orientation.
 * In any other projection the pieces are joined into one range and carry no surface.
 */
export interface Piece {
  /** Absolute integer vertices in the records' unit, three per vertex. */
  readonly vertices: readonly number[];
  /** Indices into this piece's `vertices`, three per triangle, counter-clockwise seen from outside. */
  readonly triangles: readonly number[];
  /** Present exactly when the projection carries surfaces. */
  readonly surface?: SurfaceExpansion;
}

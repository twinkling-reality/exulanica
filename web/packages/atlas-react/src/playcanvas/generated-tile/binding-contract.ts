import type { NavigationWorld } from '@exulanica/atlas-core';
import type * as pc from 'playcanvas';
import type { CameraState } from '../controls.js';

/**
 * What the Atlas binding needs from a generated tile, and nothing more.
 *
 * A tile arrives already loaded and checked. The binding stands the player on the tile's own
 * support (from its `nav_envelope` projection), starts the camera where the tile says a person
 * stands, and hands the tile the scene to draw into. It never reads the tile's geometry, never
 * derives ground from what is drawn, and never falls back to the owned district's ground.
 *
 * DEVELOPMENT EVALUATION ONLY. A generated tile may not appear in any person's world until a
 * superseding governance ADR is accepted. The app reaches this contract only from the development
 * preview route; see `docs/generated-tile-runtime.md`.
 */
export interface GeneratedTileMount {
  /** Support and collision for the player, from the tile's navigation and collision projections. */
  readonly navigationWorld: NavigationWorld;
  /** Where the session opens: on the tile's support, eye at the navigation world's eye height. */
  readonly start: CameraState;
  attach(host: GeneratedTileHost): GeneratedTileAttachment;
}

export interface GeneratedTileHost {
  readonly app: pc.AppBase;
  /** The parent every environment entity lives under. */
  readonly environmentRoot: pc.Entity;
  readonly camera: pc.Entity;
}

/**
 * What one drawn tile put on the screen. THE TILE IS NAMED BESIDE EVERY FIGURE ON PURPOSE.
 *
 * An attachment draws the tile that was asked for and every neighbour of it whose ground the walk
 * can reach, so one triangle count for an attachment would be a count over a population that
 * changes with how much world came with the request. Each tile counts itself here and a reader adds
 * them up, which is the arrangement where the sum can be checked rather than assumed.
 */
export interface DrawnTileMetrics {
  readonly tileName: string;
  readonly triangles: number;
  readonly drawBatches: number;
  readonly unavailableSurfaces: number;
}

export interface GeneratedTileMetrics {
  readonly tileName: string;
  /** The tile named above and NOT its neighbours, which count themselves in `neighbours`. */
  readonly triangles: number;
  /** Draws for the tile named above. A texture set two tiles draw is uploaded once and drawn twice. */
  readonly drawBatches: number;
  /** The named tile's own container, and every texture set the WORLD cites, fetched once between them. */
  readonly transferredBytes: number;
  readonly decodedTextureBytes: number;
  /** Surfaces of the named tile drawn as unavailable: its own, not the world's. */
  readonly unavailableSurfaces: number;
  /**
   * Every NEIGHBOURING container this attachment also drew, each counting only itself.
   *
   * Empty when no neighbour was given, which is a different fact from neighbours that drew nothing,
   * and the two are told apart by there being no entry rather than by an entry reading zero.
   */
  readonly neighbours: readonly DrawnTileMetrics[];
  readonly lookId: string;
  readonly lookVersion: number;
}

export interface GeneratedTileAttachment {
  readonly metrics: GeneratedTileMetrics;
  /** Removes everything `attach` added and restores the scene it changed. */
  dispose(): void;
}

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

export interface GeneratedTileMetrics {
  readonly tileName: string;
  readonly triangles: number;
  readonly drawBatches: number;
  readonly transferredBytes: number;
  readonly decodedTextureBytes: number;
  readonly unavailableSurfaces: number;
  readonly lookId: string;
  readonly lookVersion: number;
}

export interface GeneratedTileAttachment {
  readonly metrics: GeneratedTileMetrics;
  /** Removes everything `attach` added and restores the scene it changed. */
  dispose(): void;
}

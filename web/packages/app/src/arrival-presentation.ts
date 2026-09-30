/** The saved-world v4 opening policy read by the server and the production page. */

import policyText from '../../../../assets/catalogs/arrival/arrival-presentation.v1.json?raw';
import { adaptSnapshot, type GraphPayload, type ReconstructionSceneRecord } from '@exulanica/graph-client';
import type { ReconstructedGeometry } from './scene.js';
import type { SavedArrivalDescriptor } from './world-entry-api.js';

interface ArrivalPresentationPolicy {
  readonly profile: 'exulanica.arrival-presentation/v1';
  readonly layout_scale_milli: 1000;
  readonly scale_is_metric: false;
  readonly max_drawn_regions: 5;
  readonly position_unit: 'millimetre';
  readonly forward_unit: 'millionth';
  readonly eye_height_mm: 1600;
  readonly fallback_min_distance_mm: 3600;
  readonly fallback_max_distance_mm: 4400;
  readonly fallback_radius_fraction_millionths: 220000;
  readonly fallback_pitch_microradians: -85000;
}

export const ARRIVAL_PRESENTATION = JSON.parse(policyText) as ArrivalPresentationPolicy;

/** Reuse the graph's one scene adapter for an entry-scoped retained build. */
export function retainedSceneRecord(
  payload: GraphPayload['reconstruction_scenes'][number],
  regionId: string,
): ReconstructionSceneRecord {
  const snapshot = adaptSnapshot({
    state_version: 0, review_sources: [], entities: [], occurrences: [], proposals: [],
    scene_groups: [], reconstruction_scenes: [payload], never_same: [], deleted_entity_ids: [],
  }, () => regionId);
  const scene = snapshot.reconstructionScenes?.[0];
  if (scene === undefined || scene.islandId !== regionId) throw new Error('arrival_source_unavailable');
  return scene;
}

/** Quantization is the only permitted difference between a served pose and loaded geometry. */
export function matchesServedLocalPose(
  geometry: ReconstructedGeometry | undefined,
  arrival: SavedArrivalDescriptor,
): boolean {
  const position = geometry?.viewpointLocal;
  const forward = geometry?.viewpointForwardLocal;
  if (position === undefined || forward === undefined) return false;
  const held = [position.x, position.y, position.z];
  const faced = [forward.x, forward.y, forward.z];
  return held.every((value, index) =>
    Math.abs(value * 1000 - arrival.positionLocalMm[index]!) <= 1)
    && faced.every((value, index) =>
      Math.abs(value * 1_000_000 - arrival.forwardLocalMillionths[index]!) <= 2);
}

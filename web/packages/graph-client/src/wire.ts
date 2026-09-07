/**
 * What the API sends, in the API's own words.
 *
 * Snake case, ISO 8601 strings, ids that are plain strings. These are the server's shapes and
 * they are deliberately not the read model's: a reader checking this file against the route that
 * produces it is comparing like with like, and `snapshot.ts` is then the single place where the
 * two vocabularies meet and every difference between them has to be written down.
 *
 * `toMs` lives here because reading one of these timestamps is a wire concern. The server sends a
 * string and every caller wants epoch milliseconds. A string that will not parse becomes null
 * rather than NaN, because NaN travels silently through arithmetic and comes out the far end as a
 * date, whereas a null has to be handled by whoever received it.
 */

export interface AssertionPayload {
  readonly assertion_id: string;
  readonly kind: string;
  readonly predicate_key: string;
  readonly status: string;
  readonly object_value: unknown;
  readonly support_span_ids: readonly string[];
  readonly produced_by: Readonly<Record<string, unknown>>;
  readonly asserted_at: string;
  readonly supersedes: string | null;
}

export interface HistoryPayload {
  readonly event_id: string;
  readonly event_type: string;
  readonly actor: string;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly undoes: string | null;
  readonly created_at: string;
}

export interface ReconstructionScenePayload {
  readonly scene_id: string;
  readonly member_digest: string;
  readonly pose_receipt_sha256: string | null;
  readonly placement_receipt_sha256: string | null;
  readonly gate_digest: string | null;
  readonly recorded_rung: number | null;
  readonly recorded_reasons: readonly string[];
  readonly displayed_rung: 1 | 2 | 3 | 4;
  readonly display_reasons: readonly string[];
  readonly member_count: number;
  readonly registered_member_count: number;
  readonly receipt_state: 'available' | 'missing' | 'invalid';
  readonly placement_state: 'available' | 'partial' | 'bytes_missing' | 'unavailable' | 'invalid';
  readonly rendering_substrate: 'posed_point_maps' | 'gaussian_splats' | 'source_photographs';
  /**
   * How many people in this scene are not being drawn, counted by the server.
   *
   * Server-side on purpose: a client that failed to load the region rows would otherwise compute
   * zero and tell the viewer that nobody is hidden.
   */
  readonly hidden_person_count: number;
  readonly masked_member_count: number;
  readonly trained_geometry?: {
    readonly artifact_id: string;
    readonly content_sha256: string;
    readonly container: 'sog/1';
    readonly scene_from_asset_row_major: readonly number[];
    readonly bounds: { readonly min: readonly number[]; readonly max: readonly number[] };
    readonly state: 'available' | 'bytes_missing' | 'invalid';
    readonly reference: {
      readonly href: string;
      readonly authorization: 'workspace-bearer';
      readonly content_sha256: string;
      readonly byte_size: number;
    } | null;
    /** The trainer's measured held-out appearance and accounting; absent from older payloads. */
    readonly quality?: {
      readonly heldout_views: number;
      readonly psnr: number;
      readonly ssim: number;
      readonly lpips: number;
      readonly coverage_fraction: number;
      readonly floaters_fraction: number;
      readonly iterations_completed: number;
      readonly duration_seconds: number;
      readonly usd_cost: number;
      readonly gpu: string;
    };
  } | null;
  readonly members: readonly {
    readonly capture_id: string;
    readonly ordinal: number;
    readonly registered: boolean;
    /**
     * The people in this photograph: an outline and a state, never pixels.
     *
     * A masked region's bytes were replaced with neutral fill before reconstruction read them,
     * so there is nothing here a rendering bug could turn back into somebody's face.
     */
    readonly person_regions: readonly {
      readonly region_id: string;
      readonly state: 'unknown' | 'present' | 'shown' | 'hidden' | 'withdrawn';
      readonly silhouette_ppm: readonly (readonly number[])[];
      readonly display_name: string | null;
      readonly subject_id: string | null;
    }[];
    /**
     * Whether anybody has screened this photograph for people at all.
     *
     * `unscreened` is not the same fact as an empty `person_regions`, and the difference is the
     * whole point: one means there is nobody to hide, the other means nobody has looked. Treat an
     * absent or unrecognised value as `unscreened` and draw no pixels.
     */
    readonly person_review_state: 'unscreened' | 'screened' | 'stale';
    readonly recovered_camera?: {
      readonly scene_from_camera_row_major: readonly number[];
      readonly calibration: {
        readonly model: string; readonly width: number; readonly height: number;
        readonly fx: number; readonly fy: number; readonly cx: number; readonly cy: number;
        readonly parameters: readonly number[];
      };
      readonly projection: 'pinhole' | 'pinhole-approximation';
    } | null;
    readonly exclusion_reason: string | null;
    readonly placement: {
      readonly artifact_id: string;
      readonly content_sha256: string;
      readonly container: string | null;
      readonly scene_from_opm_row_major: readonly number[];
      readonly local_units_to_scene_units: number;
      readonly scale_status: 'colmap-correspondence-fit';
      readonly state: 'available' | 'bytes_missing';
      readonly reference: {
        readonly href: string;
        readonly authorization: 'workspace-bearer';
        readonly content_sha256: string;
        readonly byte_size: number;
      } | null;
    } | null;
  }[];
  /**
   * Content a world model imagined for this scene, in its own tier below every recorded rung.
   *
   * A separate field from `trained_geometry` rather than a flag on it, and that is the whole
   * design: to draw one of these a client has to read a field whose name says what it is. A
   * client that ignores this field sees exactly the world that was photographed, which is the
   * correct default for every consumer that has not thought about the distinction.
   *
   * An empty array means nothing was generated. An entry with `state: 'invalid'` means a
   * generation exists whose receipt did not verify, which is a different fact and is never
   * silently dropped: a dropped generation is indistinguishable from no generation.
   *
   * Absent from older payloads. Treat an absent field as unknown rather than as empty, and draw
   * nothing either way.
   */
  readonly generated_geometry?: readonly {
    readonly artifact_id: string;
    readonly receipt_sha256: string | null;
    readonly tier: 'generated';
    readonly state: 'available' | 'invalid';
    readonly state_reason: string | null;
    readonly model: {
      readonly provider: string;
      readonly model_id: string;
      readonly model_version: string;
    } | null;
    readonly prompt_sha256: string | null;
    /** Exactly what the model was shown, digest by digest. */
    readonly conditioning: readonly { readonly role: string; readonly sha256: string }[];
    readonly world_read_bundle_sha256: string | null;
    readonly container: string | null;
    readonly content_sha256: string | null;
    readonly byte_size: number | null;
    /** Where the record stops, in words. Shown to the viewer; never omitted from a valid entry. */
    readonly seam: string | null;
  }[];
}

/** What the API's `GET /graph` answers with. Server terms, not read-model terms. */
export interface GraphPayload {
  readonly state_version: number;
  readonly entities: readonly {
    readonly entity_id: string;
    readonly entity_class: string;
    readonly display_name: string | null;
    readonly merged_into: string | null;
    readonly occurrence_count: number;
    readonly capture_ids: readonly string[];
    readonly first_seen: string | null;
    readonly last_seen: string | null;
    readonly open_question_count: number;
    readonly assertions: readonly AssertionPayload[];
    readonly history: readonly HistoryPayload[];
    readonly contradictions: readonly Readonly<Record<string, unknown>>[];
  }[];
  readonly occurrences: readonly {
    readonly occurrence_id: string;
    readonly capture_id: string;
    readonly occurrence_class: string;
    readonly primary_span_id: string;
    readonly entity_id: string | null;
    readonly link_state: string | null;
    readonly captured_at: string | null;
  }[];
  readonly proposals: readonly {
    readonly proposal_id: string;
    readonly occurrence_id: string;
    readonly entity_id: string;
    readonly rank: number;
    readonly outcome: string;
    readonly basis: Readonly<Record<string, unknown>>;
    /** The modality this proposal carries that the user has not already refused for the pair. */
    readonly new_modality: string | null;
    readonly suppressed_by_rejection: boolean;
    readonly support_span_ids: readonly string[];
  }[];
  readonly scene_groups: readonly {
    readonly group_id: string;
    readonly ordinal: number;
    readonly capture_ids: readonly string[];
    readonly first_utc: string | null;
    readonly last_utc: string | null;
    readonly member_count: number;
    readonly positioned_member_count: number;
    readonly radius_m: number | null;
    readonly centroid_lat_e7: number | null;
    readonly centroid_lon_e7: number | null;
    readonly rung: number | null;
    readonly rung_capture_count: number;
  }[];
  readonly reconstruction_scenes: readonly ReconstructionScenePayload[];
  readonly never_same: readonly (readonly [string, string])[];
  readonly deleted_entity_ids: readonly string[];
}

/** An ISO 8601 instant as epoch milliseconds, or null when it cannot be read. Never NaN. */
export function toMs(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

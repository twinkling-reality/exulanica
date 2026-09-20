import type * as pc from 'playcanvas';
import type { CharacterSubject, ResolvedCharacterRepresentation } from '@exulanica/atlas-core';

export type SocietyProfile =
  | 'exulanica-society/v1'
  | 'exulanica-society/v2'
  | 'exulanica-society/v4';

/** The v2 goal: one reviewed affordance at one target. */
export interface PurposefulGoal {
  readonly kind: 'visit' | 'rest';
  readonly target_id: string;
  readonly reason: string;
}

/** The v4 goal: a catalogued activity, where it happens, and why it was the most pressing. */
export interface RoutineGoal {
  readonly activity: string;
  readonly destination_id: string | null;
  readonly because: string;
}

export interface SocietyInhabitantSnapshot {
  readonly id: string;
  readonly synthetic: true;
  readonly display_name?: string;
  /** v1 and v2 carry a label; v4 carries a role only where the place's premises supply one. */
  readonly role?: string | null;
  readonly role_reason?: string;
  readonly position_mm: readonly [number, number];
  readonly goal?: null | PurposefulGoal | RoutineGoal;
  readonly action?: {
    readonly kind: string;
    readonly status: 'active' | 'completed' | 'blocked';
    readonly target_id?: string | null;
    readonly destination_id?: string | null;
    readonly remaining_ticks?: number;
    readonly reason: string;
  };
  readonly route?: null | {
    readonly node_ids: readonly string[];
    readonly edge_index: number;
    readonly edge_progress_mm: number;
    readonly destination_node_id: string;
    readonly input_sha256: string;
  };
  readonly motion_path_mm?: readonly (readonly [number, number])[];
  /** v4: inside premises. Interiors are not drawn; the person is counted, not placed. */
  readonly indoors?: boolean;
  /** v4: this inhabitant's own walking budget per simulated minute. */
  readonly walk_speed_mm_per_tick?: number;
  /**
   * The height of the surface this person stands on, millimetres against their place's datum, for
   * a state whose place states one (`exulanica.society-place/v2`). Absent means the place states
   * no height, not that the height is zero: the crowd draws every walker on the ground plane, so
   * it refuses a person who states one rather than drawing them below the surface they stand on.
   */
  readonly support_z_mm?: number | null;
  readonly needs?: Readonly<Record<string, number>>;
  readonly explanation?: { readonly summary: string; readonly event_ids: readonly string[] };
}

/** The exact versioned routine catalogs and digest recorded by a v4 society state. */
export interface SocietyRoutineBinding {
  readonly catalog_versions: Readonly<Record<string, number>>;
  readonly sha256: string;
}

export interface OwnedSocietyState {
  readonly profile?: SocietyProfile;
  readonly society_id?: string;
  readonly branch_id?: string;
  readonly input_seq?: number;
  readonly input_sha256?: string;
  readonly routine?: SocietyRoutineBinding;
  readonly tick: number;
  /** V4 simulated duration of one tick. Absent profiles do not imply zero. */
  readonly tick_seconds?: number;
  readonly start_minute_of_day?: number;
  readonly minute_of_day?: number;
  readonly day?: number;
  readonly inhabitants: readonly SocietyInhabitantSnapshot[];
}

export type CrowdDetail = 'near' | 'far';

export interface InhabitantIdentity {
  readonly societyId: string;
  readonly branchId: string;
  readonly inhabitantId: string;
}

export interface CrowdPose {
  /** Ground contact, world metres. */
  readonly position: readonly [number, number, number];
  readonly deltaSeconds: number;
  readonly reducedMotion?: boolean;
  readonly discontinuity?: boolean;
}

/**
 * What the crowd needs of anything that draws one person. Two kinds satisfy it: the abstract
 * character in this folder, and the character lane's `inhabitantRenderable`, whose people are
 * composed from shared catalog containers. What the two do not share is optional here, and absence
 * means something in every case, stated per member: a reader must never read a missing member as
 * zero or as nothing.
 */
export interface CrowdRenderable {
  readonly root: pc.Entity;
  readonly subject: CharacterSubject;
  /**
   * Optional: the resolved representation, for a renderable that draws one. A catalog person is
   * described by its look and that look's digest instead and omits this; the crowd then reports no
   * representation for that inhabitant rather than an empty one.
   */
  readonly representation?: ResolvedCharacterRepresentation;
  readonly standingHeight: number;
  readonly facing: number;
  /**
   * Optional: bytes this renderable owns outright, for a renderable that holds its own geometry and
   * textures. A renderable drawn from shared containers omits both, because its bytes belong to the
   * shared host and counting them here would count one container once per person. The crowd's total
   * is therefore what is reported here plus what the shared host holds, never one instead of the
   * other.
   */
  readonly residentBytes?: number;
  readonly textureResidentBytes?: number;
  pose(pose: CrowdPose): void;
  /**
   * Optional: carry the last pose to a new ground contact without solving a new one. A renderable
   * that offers it may be posed on fewer frames than it is drawn, and is handed the time skipped at
   * its next pose; one without it is posed every frame.
   */
  follow?(position: readonly [number, number, number]): void;
  setVisible(visible: boolean): void;
  destroy(): void;
}

export type CrowdRenderableFactory = (
  device: pc.GraphicsDevice,
  parent: pc.Entity,
  identity: InhabitantIdentity,
  detail: 'near',
) => CrowdRenderable;

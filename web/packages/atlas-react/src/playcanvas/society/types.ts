import type * as pc from 'playcanvas';
import type { CharacterSubject, ResolvedCharacterRepresentation } from '@exulanica/atlas-core';

export type SocietyProfile =
  | 'exulanica-society/v1'
  | 'exulanica-society/v2'
  | 'exulanica-society/v3'
  | 'exulanica-society/v4';

/** The v2 goal: one reviewed affordance at one target, or a walk that makes room at a busy destination, which names no target. */
export interface PurposefulGoal {
  readonly kind: 'visit' | 'rest' | 'make_room';
  readonly target_id: string | null;
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
  /**
   * v2: how far anybody may walk in one tick, in millimetres, as the state recorded it at creation
   * (`movement_budget_mm_per_tick`). Absent means the state records no pace, not that nobody walks.
   */
  readonly movement_budget_mm_per_tick?: number;
  /** V4 simulated duration of one tick. Absent profiles do not imply zero. */
  readonly tick_seconds?: number;
  readonly start_minute_of_day?: number;
  readonly minute_of_day?: number;
  readonly day?: number;
  readonly inhabitants: readonly SocietyInhabitantSnapshot[];
}

export type CrowdDetail = 'near' | 'far';

/**
 * Why a person was drawn somewhere without walking there. Every such move is named, never silent:
 * - `minutes-not-read`: simulated minutes passed that this view never read, and the path recorded
 *   for the latest one does not start where the person was drawn;
 * - `path-starts-elsewhere`: the next minute's recorded path starts somewhere other than where the
 *   previous one ended, as when people are brought back at new starting places;
 * - `too-far-behind`: more recorded walking is waiting than can be caught up, so the person is
 *   carried forward along their own recorded path;
 * - `no-recorded-path`: the state records where the person is and no path for how they got there;
 * - `not-newer`: the state is not later than the one drawn, so the person is drawn where it says.
 */
export type CrowdJumpReason =
  | 'minutes-not-read'
  | 'path-starts-elsewhere'
  | 'too-far-behind'
  | 'no-recorded-path'
  | 'not-newer';

export interface CrowdJump {
  readonly inhabitantId: string;
  readonly reason: CrowdJumpReason;
  /** The tick of the state that caused the jump. */
  readonly tick: number;
  /** Ticks between the last state drawn and this one, less the one being drawn (0 when none). */
  readonly unreadTicks: number;
  /** How far the drawn person moved without walking, in metres. */
  readonly metres: number;
}

/** How one snapshot is presented over time. */
export interface CrowdTiming {
  /** Real milliseconds one simulated tick takes to present: the host's effective interval. */
  readonly intervalMs?: number;
  readonly nowMs?: number;
  /**
   * How long a standing person waits before starting a newly recorded walk, in real milliseconds.
   * A caller that learns of each tick some time after it happens passes that delay, so the next
   * tick's path has arrived before this one is walked to its end and nobody stops between minutes.
   */
  readonly startLagMs?: number;
}

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
  /**
   * What the person is doing where they stand, as the state says: the kind of an action under way,
   * such as `rest`, or null. A renderable that draws postures draws the one its catalog declares for
   * it; one that draws none, like the abstract figure, stands.
   */
  readonly activity?: string | null;
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

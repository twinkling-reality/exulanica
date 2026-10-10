import type * as pc from 'playcanvas';
import type { CharacterSubject, ResolvedCharacterRepresentation } from '@exulanica/atlas-core';

export type SocietyProfile =
  | 'exulanica-society/v1'
  | 'exulanica-society/v2'
  | 'exulanica-society/v3'
  | 'exulanica-society/v4'
  | 'exulanica-society/v5'
  | 'exulanica-society/v7';

/** A shipped thing kind by key, version and digest, as a society of things names it: never a look. */
export interface ShippedThingKindReference {
  readonly kind: string;
  readonly version: number;
  readonly sha256: string;
  readonly source?: undefined;
}

/**
 * A kind its workspace keeps (a creature drafted from a person's words), as a society of things
 * names it: by its document's digest alone, never by a key its maker's words made. What the
 * society runs of it is its run form, which the state carries under `kinds`; what it is called
 * and drawn as is asked of the workspace's store by this digest.
 */
export interface MadeThingKindReference {
  readonly source: 'workspace';
  readonly sha256: string;
  /** Never stated: a kept kind's key and version are its workspace's, made from a person's words. */
  readonly kind?: undefined;
  readonly version?: undefined;
}

/** How a society of things names a kind: a shipped one, or one its workspace keeps. */
export type ThingKindReference = ShippedThingKindReference | MadeThingKindReference;

/** Whether a society names this kind as its workspace's own, by digest alone. */
export const isMadeKind = (kind: ThingKindReference): kind is MadeThingKindReference =>
  'source' in kind && kind.source === 'workspace';

/**
 * One of a society of things' things (v7): an object its author placed, standing where the version
 * puts it, or one a visitor carried in, held by it. How it is drawn is a look chosen for it.
 */
export interface SocietyThingSnapshot {
  readonly id: string;
  readonly placed_id: string | null;
  readonly kind: ThingKindReference;
  readonly position_mm: readonly [number, number] | null;
  readonly yaw_microradians: number | null;
  readonly held_by: string | null;
  /** Only for a thing that does not rest on the ground: millimetres above its elevation. */
  readonly height_mm?: number;
  /** Where its author placed it, in a society whose beings have hands (`exulanica-ability/hands/v1`). */
  readonly placed_at_mm?: readonly [number, number];
  /** While held there: the holder's socket it is in, such as `hand.right`; absent (or null) otherwise. */
  readonly socket?: string | null;
  /** In a society whose beings have hands: the visitor that carried it in, which it goes home with. */
  readonly brought_by?: string;
}

/**
 * The v2 goal: one reviewed affordance at one target, a walk that makes room at a busy
 * destination, standing a while at an open spot, or talking with one other person. Only the first
 * names a target.
 */
export interface PurposefulGoal {
  readonly kind: 'visit' | 'rest' | 'make_room' | 'stand' | 'talk';
  readonly target_id: string | null;
  readonly reason: string;
  /** Talking: the other person, and the minutes the two talk once both are there. */
  readonly partner_id?: string;
  readonly duration_ticks?: number;
}

/** The v4 goal: a catalogued activity, where it happens, and why it was the most pressing. */
export interface RoutineGoal {
  readonly activity: string;
  readonly destination_id: string | null;
  readonly because: string;
  readonly reason?: string;
}

/** A line a being of a society of things heard: when, who said it (by kind and number), to whom. */
export interface SocietyHeardLine {
  readonly tick: number;
  readonly from: string;
  readonly from_kind: ThingKindReference;
  readonly from_number: number;
  /** The one it was said to, or null for everyone near. */
  readonly to: string | null;
  readonly line: string;
  /** The model that wrote the line, where a model decided it; absent for an outside program's. */
  readonly model?: { readonly provider: string; readonly model_id: string };
}

export interface SocietyInhabitantSnapshot {
  readonly id: string;
  readonly synthetic: true;
  readonly display_name?: string;
  /** v1 and v2 carry a label; v4 carries a role only where the place's premises supply one. */
  readonly role?: string | null;
  readonly role_reason?: string;
  readonly has_home?: boolean;
  readonly has_work?: boolean;
  readonly position_mm: readonly [number, number];
  readonly goal?: null | PurposefulGoal | RoutineGoal;
  readonly action?: {
    readonly kind: string;
    readonly status: 'active' | 'completed' | 'blocked';
    readonly target_id?: string | null;
    readonly destination_id?: string | null;
    readonly remaining_ticks?: number;
    readonly reason: string;
    /** What finishing a stay relieves, carried by a stay begun under a routine an input records. */
    readonly relief_milli?: number;
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
  /** v7: the person is a thing of this kind, and came by population, placement or crossing. */
  readonly kind?: ThingKindReference;
  readonly came_by?: 'populated' | 'placed' | 'crossed';
  readonly placed_id?: string | null;
  readonly crossing?: {
    readonly arrival_id: string;
    readonly bridge: string;
    readonly grant_id: string;
    /** Who decides for the visitor here, as its arrival said; absent means its program does. */
    readonly decided_by?: 'program' | 'world';
  } | null;
  /** v7, only where they apply: a mode other than walking, height and velocity in flight, a size class. */
  readonly mode?: 'walking' | 'flight';
  readonly height_mm?: number;
  /** mm/s: x and y along the ground (position_mm's two axes), z up (the rate of height_mm). */
  readonly velocity_mm_s?: readonly [number, number, number];
  readonly size_class_mm?: number;
  /** v7: the lines the being heard, oldest first; stated only once it heard one. */
  readonly heard?: readonly SocietyHeardLine[];
  /** v7: the minutes in a row a visitor's program has been quiet; stated only while it is. */
  readonly quiet_minutes?: number;
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
  /** v7: the society's things. */
  readonly things?: readonly SocietyThingSnapshot[];
  /** v7: the ability modules its first input recorded, such as `exulanica-ability/hands/v1`. */
  readonly modules?: readonly string[];
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
  /**
   * How far apart two people who stand talking with each other are drawn, centre to centre, in
   * metres, when their recorded standing points are nearer than that: each is drawn half the
   * shortfall back from the other, a step taken at their own pace. Presentation only: no recorded
   * position changes. Absent or zero, everyone is drawn at their recorded point, as before.
   */
  readonly conversationMetres?: number;
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
  /** Whether the activity is performed on a seat (`CharacterPose.seated`); absent means no seat. */
  readonly seated?: boolean;
  /** The ground's height under a person drawn above it (`CharacterPose.groundY`). */
  readonly groundY?: number;
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
   * Optional: how fast this renderable walks at its walk's own cadence, metres a second at the size
   * it is drawn, for one whose look declares it, as a rigged thing's does. Absent or null means it
   * declares none, and the crowd then walks the person at the catalog person's pace for their id; a
   * catalog person omits it for that reason.
   */
  readonly walkSpeed?: number | null;
  /**
   * Optional: whether this renderable draws an activity on a seat in a seat posture. The catalog
   * person does; one that omits it, like the abstract figure, draws every activity standing, and the
   * crowd then keeps it standing at its place rather than lifting it onto a seat it would hover over.
   */
  readonly drawsSeats?: boolean;
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

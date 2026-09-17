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
  /** v1 and v2 carry a legacy label; v4 carries a role only where the place's premises supply one. */
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
  readonly needs?: Readonly<Record<string, number>>;
  readonly explanation?: { readonly summary: string; readonly event_ids: readonly string[] };
}

export interface OwnedSocietyState {
  readonly profile?: SocietyProfile;
  readonly society_id?: string;
  readonly branch_id?: string;
  readonly input_seq?: number;
  readonly input_sha256?: string;
  readonly tick: number;
  readonly minute_of_day?: number;
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
 * The seam to the character lane's public renderable. It carries only what the crowd uses, so
 * the character lane's `inhabitantRenderable` satisfies it unchanged when it lands.
 */
export interface CrowdRenderable {
  readonly root: pc.Entity;
  readonly subject: CharacterSubject;
  readonly representation: ResolvedCharacterRepresentation;
  readonly standingHeight: number;
  readonly facing: number;
  readonly residentBytes: number;
  readonly textureResidentBytes: number;
  pose(pose: CrowdPose): void;
  /**
   * Optional: carry the last pose to a new ground contact without solving a new one. A renderable
   * that offers it may be posed on fewer frames than it is drawn; one without it is posed every
   * frame.
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

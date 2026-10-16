/**
 * The authored-objects surface's public contract: what `mountObjects` is given, what it returns,
 * and the regions an object stands in.
 *
 * A leaf that `objects.ts` and `objects-regions.ts` both import, so neither imports the other.
 * `objects.ts` re-exports the names its importers use.
 */

import type { AtlasScene, Island, IslandId } from '@exulanica/atlas-core';
import type { AuthoredGround } from '@exulanica/atlas-react/playcanvas';

import type { GatedConfirmPanel } from '../ui/confirm.js';
import type { ObjectOperationGate, ObjectPlacementPanel } from '../ui/object-placement.js';
import type { ObjectRole, ReviewedAsset, WorldObjectsClient } from '../world-objects-api.js';
import type { DeclaredFloor } from '../world-entry-api.js';
import type { Credentials } from '../config.js';
import type { GeneratedObjectGround } from './generated-object-ground.js';
import type { AppEnvironment, SessionState } from './session-state.js';

export interface DistrictObjectPlacement {
  readonly versionId: string;
  readonly regionId: string;
  readonly translationMm: readonly [number, number, number];
  readonly boundsMm: readonly [number, number, number, number];
}

/**
 * The authored region this world places objects on, and the ground it states.
 *
 * The ground is passed through from the descriptor rather than reduced to numbers here, because a
 * ground that states it has no extent has no numbers to reduce to and the difference is the whole
 * question this surface has to answer.
 */
export type AuthoredObjectRegion = { readonly regionId: string } & AuthoredGround;

export interface ObjectRegion {
  readonly regionId: IslandId;
  readonly placement: Island['placement'];
  readonly footprintRadiusLocal: number;
  readonly sceneId: string;
}

export interface ObjectsDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly credentials: Credentials;
  /** The scene this mount is drawn from, for the regions an object may stand in. */
  readonly scene: AtlasScene;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
  /** True while the world itself is the primary surface, so the key does not fight a dialog. */
  readonly isWorldPrimary: () => boolean;
  readonly onOpen?: () => void;
  /** Refresh dependent views after an accepted write; it cannot undo that write. */
  readonly onAuthoredEdit?: (versionId: string) => Promise<void>;
  /** Current, byte-verified authored district binding. Never a reconstructed memory frame. */
  readonly districtPlacement?: () => DistrictObjectPlacement | null;
  /** Exact source-independent region pinned by an authored starter entry. */
  readonly authoredRegion?: AuthoredObjectRegion;
  /** Late read of the active saved generated region and its authoritative navigation surface. */
  readonly generatedGround?: () => GeneratedObjectGround | null;
  /**
   * The floor every region of a world that states no ground has (a world made from photographs),
   * as its saved entry serves it: objects stand on it, in any region, reconstructed or not.
   */
  readonly declaredFloor?: DeclaredFloor;
  /** The write path's confirmation panel, hidden before this surface shows its own. */
  readonly hideWritePathConfirm: () => void;
  /** Injectable for tests. Production builds the real authority client. */
  readonly client?: WorldObjectsClient;
  /** Injectable for tests. Production fetches the verified container bytes. */
  readonly loadBytes?: (asset: ReviewedAsset, islandId: IslandId) => Promise<ArrayBuffer>;
}

/** The page's own part of a Companion plan request, in the wire's names. */
export interface CompanionSelectionContext {
  readonly placement: {
    readonly region_id: string;
    readonly transform: {
      readonly x_mm: number; readonly y_mm: number; readonly z_mm: number;
      readonly yaw_microradians: number; readonly scale_milli: number;
    };
  } | null;
  readonly viewer: {
    readonly x_mm: number; readonly z_mm: number; readonly yaw_microradians: number; readonly region_id?: string;
  } | null;
  readonly selected_object_id: string | null;
}

export interface MountedObjects {
  readonly panel: ObjectPlacementPanel;
  readonly confirm: GatedConfirmPanel;
  toggle(): void;
  /** Inspect a resident object from this selected saved version, using the same controls as its list. */
  inspect(objectId: string): boolean;
  close(): void;
  /** Where the Create panel offers a small square: a saved world with an authored ground. */
  smallSquareOffered(): boolean;
  /** The Create panel's own small square, asked for from elsewhere with the role the person chose. */
  arrangeSmallSquare(role: ObjectRole): void;
  /** Stage taking back the last change, through the same confirmation as the panel's own control. */
  undo(): void;
  /** Whether this world holds a change that can still be taken back. */
  undoable(): boolean;
  /** What the world's capability descriptors allow; see `ObjectPlacementPanel.setOperationGate`. */
  setOperationGate(gate: ObjectOperationGate): void;
  /**
   * Where the person points and stands, and what is selected, as a Companion plan request's
   * `context` takes it (`ActionContextBody`): the ground ahead of them in the region they stand
   * in, the place they stand for an arrangement, and the selected object. It engages nothing.
   */
  selectionContext(): CompanionSelectionContext;
  /** A reviewed object's title by its asset key, or a placed object's by its id; null if unknown. */
  titleOf(key: { readonly assetKey?: string | null; readonly objectId?: string | null }): string | null;
  /** Read the authority and draw what it holds. Awaited by tests; fire and forget in the app. */
  begin(versionId?: string): Promise<void>;
  dispose(): void;
}

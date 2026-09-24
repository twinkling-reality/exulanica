/**
 * Authored objects: the surface that places one, moves it, runs it, takes it away, and undoes it.
 *
 * This is product-direction.md's first milestone rows 3 and 4 assembled out of parts that each
 * refuse to do the others' job. The panel in `ui/object-placement.ts` builds elements and holds no
 * client. `world-objects-api.ts` speaks to the `/world/versions` plane and knows nothing about a
 * renderer. `atlas-react`'s `SceneObjectRuntime` draws and animates and cannot write. This module
 * is the one place that knows all three exist, which is the shape every other surface in
 * `composition/` has.
 *
 * **Every write goes through the confirmation surface.** Placing, moving, removing and undoing all
 * stop at `confirm.show(...)` and are sent only from the panel's own confirm handler. That is the
 * invariant `write-path.ts` states for the graph, held here for a different authority.
 *
 * **Adding is asked before it is confirmed.** A placement is a composition: the confirmation shows
 * the landing mark and the server's own preview verdict for that exact pose and base, and Confirm
 * stays held until the verdict is ready. Apply sends the same request, so the server resolves the
 * same thing again and writes it, or refuses by code and the world is unchanged. Nothing on this
 * side asserts that a source is permitted, stored or current; the server says so or it is not so.
 *
 * **This surface builds its OWN confirmation panel, and that is deliberate.** `write-path.ts`
 * binds its panel's `onConfirm` to `session.commit`, the graph's mutation gate; an object write is
 * not a graph proposal and routing it through that panel would call the wrong authority with an id
 * it never staged. `buildConfirm` is a factory and the confirmation surface is specified as ONE
 * COMPONENT WITH TWO MOUNT POINTS (interaction-model.md 5.2), so a second instance of the same
 * component is the mechanically honest reading of "through the existing confirmation surface". The
 * two are never open at once: this one hides the write path's before showing itself, so exactly
 * one `#confirm-title` is ever in the document.
 *
 * **Removal is reversible, and the panel says so, because the contract made it so.** A removal is
 * stored rather than executed: the row survives with `removed: true`, and undo "restores it rather
 * than resurrecting a new identity". A sentence that said a removal could not be undone would be
 * a false reversibility claim in the one place `confirm.ts` says it is least acceptable to be
 * wrong.
 *
 * **A nudge is not a write until it is saved.** The arrow keys move the object in the world
 * immediately, because a move nobody can see is a move nobody can judge, and they send nothing.
 * The accumulated pose goes through the confirmation surface once, on a control that says so.
 * Confirming each keystroke would either make the interaction unusable or make the confirmation
 * meaningless, and the second failure is the worse one.
 *
 * **Trigger, stop and reset write nothing at all.** The contract is explicit that they are "the
 * runtime's contract, not a stored parameter", so an object reopens at the transform its author
 * placed, at rest.
 *
 * **Giving, changing or taking away a motion is its own confirmed edit.** It keeps the object's
 * identity and place, so undo takes back the motion alone. The parameters go to the server as
 * chosen and its registry decides; a refusal is shown in the server's words and nothing is saved.
 *
 * **Preview draws but never sends.** `?preview=1` has no authority behind it, so the surface uses
 * a small built-in catalogue and says, every time, that what it drew was not saved.
 */

import {
  BEHAVIOUR_REGISTRY,
  BOUNDED_PATH_KEY,
  BOUNDED_PATH_VERSION,
  DISPLAY_EYE_HEIGHT,
  identityDisplayFrame,
  atlasVec3,
  type AtlasScene,
  type Island,
  type IslandId,
  type SceneDisplayFrame,
} from '@exulanica/atlas-core';
import { tierPolicy } from '@exulanica/companion-runtime';
import type { ConfirmationBand, ConfirmationSummary } from '@exulanica/companion-runtime';
import {
  AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M,
  DEFAULT_PLACEMENT_DISTANCE_MM,
  MM_PER_METRE,
  fetchVerifiedObjectAsset,
  nudgedPose,
  placementLandingPose,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  regionPointFromAtlas,
  type AuthoredGround,
  type PlacedAuthoredObject,
  type RegionPose,
} from '@exulanica/atlas-react/playcanvas';

import {
  SMALL_SQUARE,
  applyArrangement,
  previewArrangement,
  type ArrangementPreview,
  type ArrangementRequest,
  type ArrangementViewer,
  type ArrangementWriteResult,
} from '../arrangement-api.js';
import {
  applyComposition,
  previewComposition,
  type CompositionApplyRequest,
  type CompositionPreview,
} from '../composition-preview-api.js';
import {
  RECHECKABLE_ARRANGEMENT_REFUSALS,
  explainArrangementFailure,
  explainArrangementRefusal,
} from '../ui/arrangement-refusals.js';
import {
  buildCompositionVerdict,
  compositionDetails,
  describeReady,
  explainBlockedReason,
  explainCompositionFailure,
  explainPreview,
  type CompositionExplanation,
  type CompositionVerdictView,
} from '../ui/composition-preview.js';
import { buildConfirm, type GatedConfirmPanel } from '../ui/confirm.js';
import {
  buildObjectPlacement,
  type BehaviourControlKey,
  type MotionAxisKey,
  type MotionDraft,
  type ObjectPlacementDraft,
  type ObjectPlacementPanel,
  type PlacedObjectRow,
} from '../ui/object-placement.js';
import {
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  isObjectRole,
  objectWriteFailure,
  type AlternateVersion,
  type AuthoredObject,
  type ObjectBehaviour,
  type ObjectRole,
  type ObjectWriteResult,
  type ReviewedAsset,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';
import type { Credentials } from '../config.js';

/** How far one arrow key moves an object, in millimetres. A quarter of a step. */
const NUDGE_STEP_MM = 250;
/** How far one bracket key turns it, in radians. */
const TURN_STEP = Math.PI / 12;

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

interface ObjectRegion {
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
  /** The write path's confirmation panel, hidden before this surface shows its own. */
  readonly hideWritePathConfirm: () => void;
  /** Injectable for tests. Production builds the real authority client. */
  readonly client?: WorldObjectsClient;
  /** Injectable for tests. Production fetches the verified container bytes. */
  readonly loadBytes?: (asset: ReviewedAsset, islandId: IslandId) => Promise<ArrayBuffer>;
}

export interface MountedObjects {
  readonly panel: ObjectPlacementPanel;
  readonly confirm: GatedConfirmPanel;
  toggle(): void;
  close(): void;
  /** Read the authority and draw what it holds. Awaited by tests; fire and forget in the app. */
  begin(versionId?: string): Promise<void>;
  dispose(): void;
}

interface Pending {
  readonly kind: 'place' | 'arrange' | 'move' | 'remove' | 'behaviour' | 'undo' | 'bootstrap';
  readonly describe: string;
  readonly reversible: boolean;
  /** The server's verdict on a placement. Confirm is held until it is ready. */
  readonly verdict?: CompositionVerdictView;
  /** `reported` when the run has already put its outcome in the confirmation surface. */
  run(): Promise<void | 'reported'>;
  /** How a thrown failure is said, when the default words are not the right ones. */
  failed?(error: unknown): void;
}

/** One placement as the person chose it, kept so it can be checked again against a newer base. */
interface PlacementPlan {
  readonly asset: ReviewedAsset;
  readonly role: ObjectRole;
  readonly region: ObjectRegion;
  readonly pose: RegionPose;
  readonly behaviour: ObjectBehaviour | null;
  readonly district: DistrictObjectPlacement | null;
  readonly describe: string;
}

/** A small square as the person asked for it, kept so it can be checked again against a newer base. */
interface ArrangementPlan {
  readonly role: ObjectRole;
  readonly viewer: ArrangementViewer;
}

/** Refusals a fresh check can clear: a newer base, or a new identity for the addition. */
const RECHECKABLE: ReadonlySet<string> = new Set(['stale_base', 'subject_already_present']);

/** Said when a write is confirmed with no saved version to write to. */
const NO_AUTHORITY = 'No saved world version is connected, so nothing was changed.';

export function mountObjects(deps: ObjectsDependencies): MountedObjects {
  const { env, state } = deps;
  const listeners = new AbortController();
  let disposed = false;
  const definition = BEHAVIOUR_REGISTRY.resolve(BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION);

  // A client exists only for a world that is open; without one nothing can be written.
  const client = deps.client ?? null;

  let assets: readonly ReviewedAsset[] = Object.freeze([]);
  let version: AlternateVersion | null = null;
  let selectedId: string | null = null;
  let drawGeneration = 0;
  let selectionRevision = 0;
  let releaseRepresentationSelection: (() => void) | null = null;
  let publishingObjectSelection = false;
  let clearingRepresentationsForRedraw = false;
  /** Where the selected object is right now, uncommitted. Null when it is where it is saved. */
  let nudged: RegionPose | null = null;
  let pending: Pending | null = null;
  let issued = 0;
  /** Which placement check is current; a verdict for any other is ignored. */
  let placementCheck = 0;
  /** True only while the pending placement holds a ready verdict for its exact request. */
  let placementReady = false;
  /** Refusals and clamps the runtime reported, by object, so a row can keep showing them. */
  const notices = new Map<string, string>();
  /** Objects the preview drew for this session only. Never sent anywhere. */

  const confirm = buildConfirm({
    onConfirm: () => void commit(),
    onCancel: () => {
      pending = null;
      placementReady = false;
      placementCheck += 1;
      clearPlacementLandingMark();
      confirm.hide();
    },
  });

  const integerParameter = (name: string): { min: number; max: number; fallback: number } => {
    const descriptor = definition.ok ? definition.definition.parameters[name] : undefined;
    return descriptor !== undefined && descriptor.kind === 'integer'
      ? { min: descriptor.minimum, max: descriptor.maximum, fallback: descriptor.default }
      : { min: 0, max: 1, fallback: 0 };
  };
  const choiceParameter = (name: string): { choices: readonly string[]; fallback: string } => {
    const descriptor = definition.ok ? definition.definition.parameters[name] : undefined;
    return descriptor !== undefined && descriptor.kind === 'choice'
      ? { choices: descriptor.choices, fallback: descriptor.default }
      : { choices: [], fallback: '' };
  };

  const panel = buildObjectPlacement({
    onPlace: (draft) => proposePlacement(draft),
    onArrange: (role) => proposeArrangement(role),
    onSelect: (objectId) => select(objectId),
    onControl: (objectId, action) => control(objectId, action),
    onSetMotion: (objectId, motion) => proposeMotion(objectId, motion),
    onClearMotion: (objectId) => proposeClearMotion(objectId),
    onRemove: (objectId) => proposeRemoval(objectId),
    onUndo: () => proposeUndo(),
    onSaveMove: () => proposeMove(),
    onDiscardMove: () => discardMove(),
    onClose: () => setPanelVisible(false),
  }, {
    axes: choiceParameter('axis').choices as readonly MotionAxisKey[],
    axisFallback: choiceParameter('axis').fallback as MotionAxisKey,
    easings: choiceParameter('easing').choices,
    easingFallback: choiceParameter('easing').fallback,
    travelMm: integerParameter('travel_mm'),
    periodMilliseconds: integerParameter('period_milliseconds'),
  });

  function setPanelVisible(visible: boolean): void {
    // The browser owns traversal mode. Let its pointerlockchange event update the shell before
    // the visitor clicks the object controls; displaying a panel alone leaves the mouse locked.
    if (visible && document.pointerLockElement != null) document.exitPointerLock();
    if (visible) deps.onOpen?.();
    panel.setVisible(visible);
  }

  // -- reading -----------------------------------------------------------------------------------

  async function begin(versionId?: string): Promise<void> {
    if (disposed) return;
    const generation = ++drawGeneration;
    if (client === null) {
      // The preview has no reviewed object registry and no saved version. It offers nothing
      // rather than a stand-in whose digests no bytes were ever hashed to.
      assets = Object.freeze([]);
      version = null;
      refresh();
      panel.report(
        'This is the development preview. It has no reviewed objects and no saved world, so there '
        + 'is nothing to place here, and nothing is sent.',
      );
      return;
    }
    try {
      const connected = await client.connect(versionId);
      if (disposed || generation !== drawGeneration) return;
      const versionChanged = version !== null
        && connected.version?.versionId !== version.versionId;
      assets = connected.assets;
      version = connected.version;
      if (versionChanged && selectedId !== null) {
        selectedId = null;
        selectionRevision += 1;
      }
      refresh();
      await redrawAll(generation);
      if (disposed || generation !== drawGeneration) return;
      if (version === null) {
        panel.report(
          'Choose an object and select “Place before me” to open an alternate version first.',
        );
        return;
      }
      // The hint is for a world with nothing added yet, and that is the version's to say: a world
      // that already holds an object never shows it again, on this device or any other.
      if (visibleObjects().length === 0) {
        deps.showTravelStatus('Press P to add an object to this world.');
      }
    } catch (error) {
      if (disposed || generation !== drawGeneration) return;
      clearingRepresentationsForRedraw = true;
      try {
        state.atlas?.binding.objects.clear();
      } finally {
        clearingRepresentationsForRedraw = false;
      }
      notices.clear();
      assets = Object.freeze([]);
      version = null;
      nudged = null;
      panel.setPendingMove(null);
      refresh();
      panel.report(`No objects could be read: ${objectWriteFailure(error)}`, 'failure');
    }
  }

  /** Every object the authority holds, verified and drawn. A failure is per object, not per world. */
  async function drawEvery(generation = drawGeneration): Promise<void> {
    const runtime = state.atlas?.binding.objects;
    if (disposed || runtime === undefined || version === null) return;
    const versionId = version.versionId;
    for (const record of visibleObjects()) {
      if (generation !== drawGeneration || version?.versionId !== versionId) return;
      const failure = await draw(record, generation, versionId);
      if (generation !== drawGeneration || version?.versionId !== versionId) return;
      if (failure !== null) {
        notices.set(record.objectId, failure);
        deps.showTravelStatus(failure, 'failure');
      }
    }
    refresh();
  }

  /** Load one object's verified bytes and place it. Returns the reason it could not be drawn. */
  async function draw(
    record: AuthoredObject,
    generation = drawGeneration,
    versionId = version?.versionId ?? null,
  ): Promise<string | null> {
    const runtime = state.atlas?.binding.objects;
    if (disposed || runtime === undefined) return 'The world is not drawn yet.';
    // The contract embeds the whole registry row on the object, so availability is already here.
    if (record.asset.availability !== 'available') {
      return `The reviewed bytes for “${record.asset.title}” are not in storage `
        + `(${record.asset.availability}), so it cannot be drawn.`;
    }
    const region = regionOf(record.regionId);
    if (region === null) return 'That object names a region this world does not draw.';
    if (region.sceneId === 'authored-starter' &&
        !authoredContains(record.transform.xMm, record.transform.zMm)) {
      return 'That object is saved outside this world’s authored ground and was not drawn.';
    }
    const frameKey = JSON.stringify(currentDistrict());
    try {
      const bytes = await loadBytes(record.asset, region.regionId);
      if (listeners.signal.aborted || generation !== drawGeneration || version?.versionId !== versionId) {
        return null;
      }
      if (frameKey !== JSON.stringify(currentDistrict()) || regionOf(record.regionId) === null) {
        return "The object’s display frame is no longer available.";
      }
      const placed: PlacedAuthoredObject = {
        objectId: record.objectId,
        islandId: region.regionId,
        asset: {
          assetKey: record.asset.assetKey,
          mediaType: record.asset.mediaType,
          contentSha256: record.asset.contentSha256,
          byteSize: record.asset.byteSize,
        },
        transform: poseOf(record),
        behaviour: record.behaviour === null ? null : {
          behaviourKey: record.behaviour.behaviourKey,
          behaviourVersion: record.behaviour.behaviourVersion,
          parameters: record.behaviour.parameters,
        },
      };
      const outcome = await runtime.place(placed, bytes);
      if (disposed || generation !== drawGeneration || version?.versionId !== versionId) return null;
      // A behaviour this client cannot run and a clamped parameter are both refusals the visitor is
      // owed. They stay on the object rather than only being announced, because the status line
      // moves on and the object stays.
      if (outcome.notices.length > 0) {
        const said = outcome.notices.join(' ');
        notices.set(record.objectId, said);
        deps.showTravelStatus(said, 'failure');
      } else {
        notices.delete(record.objectId);
      }
      return null;
    } catch (error) {
      if (disposed || generation !== drawGeneration || version?.versionId !== versionId) return null;
      return error instanceof Error ? error.message : 'the object could not be drawn';
    }
  }

  function loadBytes(asset: ReviewedAsset, islandId: IslandId): Promise<ArrayBuffer> {
    if (deps.loadBytes !== undefined) return deps.loadBytes(asset, islandId);
    return fetchVerifiedObjectAsset(
      islandId,
      {
        assetKey: asset.assetKey,
        mediaType: asset.mediaType,
        contentSha256: asset.contentSha256,
        byteSize: asset.byteSize,
      },
      listeners.signal,
      { baseUrl: deps.credentials.baseUrl, token: deps.credentials.token },
    );
  }

  const poseOf = (record: AuthoredObject): RegionPose => Object.freeze({
    xMm: record.transform.xMm,
    yMm: record.transform.yMm,
    zMm: record.transform.zMm,
    yawMicroradians: record.transform.yawMicroradians,
    scaleMilli: record.transform.scaleMilli,
  });

  // -- where an object goes ------------------------------------------------------------------------

  /**
   * The region an object is placed in: the one the visitor is STANDING IN, or none.
   *
   * Nearest by ground-plane distance among the regions that actually draw reconstructed geometry,
   * because an object placed in a region with nothing in it would stand on an absent floor.
   *
   * NEAREST IS NOT ENOUGH, and the browser check is what proved it. A visitor standing in a region
   * with no reconstruction still has a nearest reconstructed region, on the other side of the
   * world. Placing there converts their position into that region's frame and drops the object
   * onto THAT region's ground, so it lands at a height they are not standing at and disappears the
   * moment the distant region falls back to a stub. The person sees nothing and is told the
   * placement succeeded, which is the worst of the available outcomes.
   */
  function placementRegion(): ObjectRegion | null {
    const authored = authoredObjectRegion();
    const authoredPose = state.atlas?.binding.playerPose();
    if (authored !== null && authoredPose !== undefined && authoredContains(
      authoredPose.position.x * MM_PER_METRE,
      authoredPose.position.z * MM_PER_METRE,
    )) return authored;
    const district = currentDistrict();
    const visitor = state.atlas?.binding.playerPose();
    if (district !== null && visitor !== undefined && districtContains(district, visitor.position.x * MM_PER_METRE, visitor.position.z * MM_PER_METRE)) {
      const island = regionOf(district.regionId);
      if (island !== null) return { ...island, sceneId: 'authored-district' };
    }
    const drawn = drawnRegions();
    if (drawn.length === 0) return null;
    const pose = state.atlas?.binding.playerPose();
    if (pose === undefined) return drawn[0]!;
    let best: ObjectRegion | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of drawn) {
      const distance = Math.hypot(
        candidate.placement.position.x - pose.position.x,
        candidate.placement.position.z - pose.position.z,
      );
      const reach = candidate.footprintRadiusLocal * candidate.placement.scale * 1.5;
      if (distance < bestDistance && distance <= reach) {
        bestDistance = distance;
        best = candidate;
      }
    }
    return best;
  }

  function drawnRegions(): readonly ObjectRegion[] {
    const scenes = new Map<IslandId, string>();
    for (const placed of state.placedPointMaps ?? []) scenes.set(placed.islandId, placed.sceneId);
    for (const trained of state.trainedGeometry) scenes.set(trained.islandId, trained.sceneId);
    for (const islandId of state.pointMaps?.keys() ?? []) {
      if (!scenes.has(islandId)) scenes.set(islandId, `legacy:${islandId}`);
    }
    const reconstructed = deps.scene.islands.flatMap((island) => {
      const sceneId = scenes.get(island.islandId);
      return sceneId === undefined ? [] : [{
        regionId: island.islandId,
        placement: island.placement,
        footprintRadiusLocal: island.footprintRadiusLocal,
        sceneId,
      }];
    });
    const authored = authoredObjectRegion();
    return authored === null ? reconstructed : [authored, ...reconstructed];
  }

  function regionOf(regionId: string): ObjectRegion | null {
    const authored = authoredObjectRegion();
    if (authored !== null && String(authored.regionId) === regionId) return authored;
    const island = deps.scene.islands.find((item) => String(item.islandId) === regionId);
    if (island === undefined) return null;
    const district = currentDistrict();
    if (district?.regionId === regionId) {
      const [x, y, z] = district.translationMm;
      return {
        regionId: island.islandId,
        placement: { position: atlasVec3(x / MM_PER_METRE, y / MM_PER_METRE, z / MM_PER_METRE), yaw: 0, scale: 1 },
        footprintRadiusLocal: island.footprintRadiusLocal,
        sceneId: 'authored-district',
      };
    }
    // A live district without its authorized binding cannot fall back to an arbitrary memory root.
    if (deps.districtPlacement !== undefined && !env.preview && !drawnRegions().some(item => String(item.regionId) === regionId)) return null;
    return {
      regionId: island.islandId,
      placement: island.placement,
      footprintRadiusLocal: island.footprintRadiusLocal,
      sceneId: drawnRegions().find((item) => item.regionId === island.islandId)?.sceneId ?? 'unavailable',
    };
  }

  function authoredObjectRegion(): ObjectRegion | null {
    const region = deps.authoredRegion;
    if (region === undefined) return null;
    return {
      regionId: region.regionId as IslandId,
      placement: {
        position: atlasVec3(0, region.elevationMm / MM_PER_METRE, 0), yaw: 0, scale: 1,
      },
      /*
       * How far from the region origin somebody still counts as standing at this region.
       *
       * For a bounded ground that is the inscribed circle of its rectangle. For a ground with no
       * extent it is the distance the renderer supports, because there is no nearer place the
       * region stops being under your feet. The value stays finite either way: it is compared
       * against real distances, and an infinity would be a number no refusal could read back.
       */
      footprintRadiusLocal: region.kind === 'endless'
        ? AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M
        : Math.min(region.halfWidthMm, region.halfDepthMm) / MM_PER_METRE,
      sceneId: 'authored-starter',
    };
  }

  /**
   * Whether this world will draw and save an object at that spot on its authored ground.
   *
   * A bounded ground answers with its own declared rectangle: outside it there is no described
   * surface. An endless ground has no rectangle, so the only honest limit left is how far this
   * renderer can still draw a position, which is what
   * `AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M` states and what the walking surface uses too.
   * Both remain a browser constraint. `docs/saved-world-entry.md` says so: the general authored
   * object API validates region ownership and transforms and enforces neither bound.
   */
  function authoredContains(xMm: number, zMm: number): boolean {
    const region = deps.authoredRegion;
    if (region === undefined) return false;
    if (region.kind === 'endless') {
      return Math.hypot(xMm, zMm) <= AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M * MM_PER_METRE;
    }
    return Math.abs(xMm) <= region.halfWidthMm && Math.abs(zMm) <= region.halfDepthMm;
  }

  function currentDistrict(): DistrictObjectPlacement | null {
    const district = deps.districtPlacement?.() ?? null;
    return district !== null && district.versionId === version?.versionId && !version.sourceInvalidated
      && deps.scene.islands.some(island => String(island.islandId) === district.regionId)
      ? district : null;
  }

  function districtContains(district: DistrictObjectPlacement, xMm: number, zMm: number): boolean {
    const [west, north, east, south] = district.boundsMm;
    return xMm >= west && xMm <= east && zMm >= north && zMm <= south;
  }

  /**
   * A region's display frame, or the identity when it has none.
   *
   * The frame is not part of an object's transform: the contract poses objects region-local and
   * the renderer draws them there directly. It is still read HERE, for one question only, which
   * is whether `y = 0` in that region is a measured ground or an arbitrary origin.
   */
  function frameFor(sceneId: string): SceneDisplayFrame {
    return state.displayFrames.get(sceneId) ?? identityDisplayFrame();
  }

  /** True when this region's ground was estimated from recovered cameras rather than assumed. */
  function groundIsMeasured(sceneId: string): boolean {
    return frameFor(sceneId).cameraCount > 0;
  }

  /**
   * What counts as the ground in a region, in region-local millimetres.
   *
   * A display frame derived from recovered cameras puts the estimated ground at `y = 0`, so an
   * object placed there stands on the same surface the geometry does. A region with no recovered
   * cameras has the IDENTITY frame, whose origin is the scene's own arbitrary one, and placing at
   * `y = 0` there drops the object under the floor the visitor is walking on. In that case the
   * ground is taken to be the visitor's own feet, which is an approximation and is said to be one
   * on the confirmation the person reads.
   */
  function groundMmIn(
    region: ObjectRegion,
    sceneId: string,
    pose: { readonly position: { readonly x: number; readonly y: number; readonly z: number } },
  ): number {
    if (sceneId === 'authored-starter') return 0;
    if (sceneId === 'authored-district') return -(currentDistrict()?.translationMm[1] ?? 0);
    if (groundIsMeasured(sceneId)) return 0;
    return regionPointFromAtlas(
      region.placement,
      [pose.position.x, pose.position.y - DISPLAY_EYE_HEIGHT, pose.position.z],
    )[1];
  }

  /**
   * Where a new object lands: on an engaged anchor, or a step in front of the visitor.
   *
   * The focused anchor is what "the focused point" means in this application: there is no picked
   * world point, and `engageFocusedAnchor` is the one public read of what the reticle has settled
   * on. When nothing is engaged, the object goes on the ground ahead, facing the person.
   */
  function placementPose(region: ObjectRegion, sceneId: string): RegionPose | null {
    const binding = state.atlas?.binding;
    if (binding === undefined) return null;
    const pose = binding.playerPose();
    const ground = groundMmIn(region, sceneId, pose);
    const index = sceneId === 'authored-district' || sceneId === 'authored-starter'
      ? null : binding.engageFocusedAnchor();
    if (index !== null) {
      const at = index * 3;
      const positions = binding.table.atlasPositions;
      if (at + 2 < positions.length) {
        return placementPoseAtAtlasPoint(
          region.placement,
          [positions[at]!, positions[at + 1]!, positions[at + 2]!],
          pose,
          ground,
        );
      }
    }
    return placementPoseBeforeVisitor(region.placement, pose, DEFAULT_PLACEMENT_DISTANCE_MM, ground);
  }

  /**
   * Draw the pose held for confirmation on the ground: the same `RegionPose` preview and apply
   * send. The field mark is the world field's placement landing, not the Map visitor triangle.
   */
  function showPlacementLandingMark(region: ObjectRegion, pose: RegionPose): void {
    state.atlas?.binding.field.setPlacementLandingPose(placementLandingPose(region.placement, pose));
  }

  function clearPlacementLandingMark(): void {
    state.atlas?.binding.field.setPlacementLandingPose(null);
  }

  // -- proposing -----------------------------------------------------------------------------------

  async function proposeBootstrap(): Promise<void> {
    if (client === null) return;
    try {
      const baseTopologyDigest = await client.bootstrapBase();
      stage({
        kind: 'bootstrap',
        describe: 'Open an alternate version of this world so you can add objects, keeping every source photograph.',
        reversible: false,
        run: async () => {
          const versionId = await client.bootstrapVersion(baseTopologyDigest);
          await begin(versionId);
          if (version?.versionId !== versionId) {
            panel.report('The alternate version opened, but could not be read. Reload to try again.', 'failure');
            return;
          }
          panel.report('Alternate version opened. Choose “Place before me” again to place your object.', 'settled');
        },
      });
    } catch (error) {
      panel.report(objectWriteFailure(error), 'failure');
    }
  }

  function proposePlacement(draft: ObjectPlacementDraft): void {
    // A role is the person's answer about their own material. Nothing here answers for them.
    if (!isObjectRole(draft.role)) {
      panel.report('Choose what this object is to you before placing it.', 'failure');
      return;
    }
    const role: ObjectRole = draft.role;
    const asset = assets.find((candidate) => candidate.assetKey === draft.assetKey);
    if (asset === undefined) {
      panel.report('That object is not in the reviewed registry.', 'failure');
      return;
    }
    if (asset.availability !== 'available') {
      panel.report(
        `The reviewed bytes for “${asset.title}” are not in storage, so it cannot be placed.`,
        'failure',
      );
      return;
    }
    if (version === null) {
      void proposeBootstrap();
      return;
    }
    if (version.sourceInvalidated) {
      panel.report(
        'The place this version was built on was deleted, so nothing more can be added to it.',
        'failure',
      );
      return;
    }
    const region = placementRegion();
    if (region === null) {
      panel.report(
        drawnRegions().length === 0
          ? 'No authorized district or reconstructed ground is available to stand an '
            + 'object on.'
          : 'You are not standing in a region with reconstructed ground. Walk into one, then '
            + 'place the object there.',
        'failure',
      );
      return;
    }
    const pose = placementPose(region, region.sceneId);
    if (pose === null) {
      panel.report('The world is still forming. Try again in a moment.', 'failure');
      return;
    }
    if (region.sceneId === 'authored-starter' && !authoredContains(pose.xMm, pose.zMm)) {
      panel.report('That spot is outside this world’s authored ground. Face inward and try again.', 'failure');
      return;
    }
    const districtAtPlacement = region.sceneId === 'authored-district' ? currentDistrict() : null;
    if (districtAtPlacement !== null && !districtContains(districtAtPlacement,
      pose.xMm + districtAtPlacement.translationMm[0], pose.zMm + districtAtPlacement.translationMm[2])) {
      panel.report('That spot is outside the district. Face toward its ground and try again.', 'failure');
      return;
    }
    const behaviour: ObjectBehaviour | null = draft.motion ? boundedPath(draft) : null;
    stagePlacement({
      asset,
      role,
      region,
      pose,
      behaviour,
      district: districtAtPlacement,
      describe:
        `Add “${asset.title}” where the mark shows, `
        + (districtAtPlacement !== null
          ? 'standing on this district’s authored ground'
          : region.sceneId === 'authored-starter'
          ? 'standing on this world’s authored ground'
          : groundIsMeasured(region.sceneId)
          ? 'standing on the ground its cameras recovered'
          : 'standing at your feet, because this place has no recovered cameras to place a '
            + 'ground from')
        + `${behaviour === null ? '' : `, travelling ${axisWords(draft.axis)}`}.`,
    });
  }

  /**
   * Show a placement for confirmation and ask the server about it, against the version held now.
   *
   * The object id is chosen here, stable within the version: a monotonic counter beside the edit
   * sequence keeps it unique without a clock or a random source. The request built here is the one
   * previewed and the one applied, so the verdict a person reads is about exactly what is sent.
   */
  function stagePlacement(plan: PlacementPlan): void {
    if (client === null || version === null) {
      panel.report(NO_AUTHORITY, 'failure');
      return;
    }
    const base = version;
    const request: CompositionApplyRequest = Object.freeze({
      source: Object.freeze({ kind: 'reviewed_asset' as const, assetKey: plan.asset.assetKey }),
      placement: Object.freeze({
        subjectId: `object-${base.editSeq + 1}-${(issued += 1)}`,
        regionId: String(plan.region.regionId),
        transform: plan.pose,
        originRole: plan.role,
        behaviour: plan.behaviour,
      }),
    });
    const districtKey = JSON.stringify(plan.district);
    const verdict = buildCompositionVerdict();
    verdict.checking();
    showPlacementLandingMark(plan.region, plan.pose);
    stage({
      kind: 'place',
      describe: plan.describe,
      reversible: true,
      verdict,
      run: async () => {
        if (client === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        if (plan.district !== null && JSON.stringify(currentDistrict()) !== districtKey) {
          throw new Error('The district binding changed. Choose the placement again.');
        }
        return settlePlacement(await applyComposition(client, base, request), plan);
      },
      failed: (error) => reportPlacementFailure(explainCompositionFailure(error, 'apply'), plan),
    });
    const check = placementCheck;
    void checkPlacement(check, base, request, plan, verdict);
  }

  function placementIsCurrent(check: number): boolean {
    return !disposed && check === placementCheck && pending?.kind === 'place';
  }

  /** The server's preview for one staged placement, put in the confirmation surface. */
  async function checkPlacement(
    check: number,
    base: AlternateVersion,
    request: CompositionApplyRequest,
    plan: PlacementPlan,
    verdict: CompositionVerdictView,
  ): Promise<void> {
    if (client === null) return;
    const again = { label: 'Check again', run: () => stagePlacement(plan) };
    let preview: CompositionPreview;
    try {
      preview = await previewComposition(client, base, request);
    } catch (error) {
      if (placementIsCurrent(check)) verdict.refused(explainCompositionFailure(error, 'preview'), again);
      return;
    }
    if (!placementIsCurrent(check)) return;
    const refused = explainPreview(preview);
    if (refused !== null) {
      if (preview.blockedReason === 'stale_base') {
        // Read the world as it is now, so what is drawn is current before anything is retried.
        await rereadVersion(base.versionId);
        if (!placementIsCurrent(check)) return;
      }
      verdict.refused(
        refused,
        RECHECKABLE.has(preview.blockedReason ?? '') ? again : undefined,
      );
      return;
    }
    if (!answersThisPlacement(preview, base, request)) {
      verdict.refused(Object.freeze({
        happened: 'The world answered about a different change than the one shown here.',
        next: 'Nothing was changed. Check again.',
        code: null,
        detail: `Answered for version ${preview.version.authoredVersionId} `
          + `at ${preview.version.stateSha256} and subject ${preview.wouldChange.subjectId ?? 'none'}.`,
        outcome: 'unchanged',
      }), again);
      return;
    }
    placementReady = true;
    verdict.ready(
      `${describeReady(preview, plan.asset.title)} Confirm to add it, or Cancel to leave the world `
      + 'as it is.',
    );
    confirm.setConfirmable(true);
  }

  /** A ready verdict counts only for the version, base and subject this surface sent. */
  function answersThisPlacement(
    preview: CompositionPreview,
    base: AlternateVersion,
    request: CompositionApplyRequest,
  ): boolean {
    return preview.version.authoredVersionId === base.versionId
      && preview.version.worldId === base.worldId
      && preview.version.stateSha256 === base.stateSha256
      && preview.wouldChange.kind === 'add_object'
      && preview.wouldChange.subjectId === request.placement.subjectId;
  }

  async function rereadVersion(versionId: string): Promise<void> {
    if (client === null) return;
    try {
      version = await client.readVersion(versionId);
    } catch {
      return;
    }
    await redrawAll();
  }

  /** An applied placement, or the stale base it met, which is read again and offered back. */
  async function settlePlacement(
    result: ObjectWriteResult,
    plan: PlacementPlan,
  ): Promise<void | 'reported'> {
    if (result.kind === 'recorded') {
      await settle(result, 'Added. “Take back the last change” removes it again.');
      return;
    }
    if (disposed) return 'reported';
    version = result.current;
    await redrawAll();
    reportPlacementFailure(explainBlockedReason('stale_base'), plan);
    return 'reported';
  }

  function reportPlacementFailure(explanation: CompositionExplanation, plan: PlacementPlan): void {
    const recheck = explanation.outcome === 'unchanged'
      && explanation.code !== null
      && RECHECKABLE.has(explanation.code);
    confirm.reportFailure(explanation.happened, {
      ...(explanation.outcome === 'unknown' ? { title: 'Not confirmed' } : {}),
      next: explanation.next,
      details: compositionDetails(explanation),
      ...(recheck ? { retry: { label: 'Check again', run: () => stagePlacement(plan) } } : {}),
    });
    panel.report(`${explanation.happened} ${explanation.next}`, 'failure');
  }

  // -- a small square ------------------------------------------------------------------------------

  /**
   * Ask for the square in front of the person, facing them, with the role they chose for it.
   *
   * Only where they stand and which way they face is sent: where each object goes is the server's
   * to work out from the world's own ground, and it refuses by name when the square would not fit.
   */
  function proposeArrangement(role: string): void {
    if (!isObjectRole(role)) {
      panel.report('Choose what these objects are to you before placing the square.', 'failure');
      return;
    }
    if (version === null) {
      void proposeBootstrap();
      return;
    }
    if (version.sourceInvalidated) {
      panel.report(
        'The place this version was built on was deleted, so nothing more can be added to it.',
        'failure',
      );
      return;
    }
    const region = placementRegion();
    const binding = state.atlas?.binding;
    if (region === null || binding === undefined) {
      panel.report('The world is still forming. Try again in a moment.', 'failure');
      return;
    }
    const pose = binding.playerPose();
    // Where the person stands and faces, as a pose placed no distance ahead of them.
    const standing = placementPoseBeforeVisitor(
      region.placement, pose, 0, groundMmIn(region, region.sceneId, pose),
    );
    stageArrangement({
      role,
      viewer: Object.freeze({
        xMm: standing.xMm,
        zMm: standing.zMm,
        yawMicroradians: standing.yawMicroradians,
      }),
    });
  }

  function stageArrangement(plan: ArrangementPlan): void {
    if (client === null || version === null) {
      panel.report(NO_AUTHORITY, 'failure');
      return;
    }
    const base = version;
    const request: ArrangementRequest = Object.freeze({
      key: SMALL_SQUARE.key,
      version: SMALL_SQUARE.version,
      viewer: plan.viewer,
      originRole: plan.role,
    });
    const verdict = buildCompositionVerdict();
    verdict.checking();
    stage({
      kind: 'arrange',
      describe: 'Place a small square in front of you, facing you, each of its objects its own change.',
      reversible: true,
      verdict,
      run: async () => {
        if (client === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        return settleArrangement(await applyArrangement(client, base, request), plan);
      },
      failed: (error) => reportArrangementFailure(explainArrangementFailure(error, 'apply'), plan),
    });
    const check = placementCheck;
    void checkArrangement(check, base, request, plan, verdict);
  }

  function arrangementIsCurrent(check: number): boolean {
    return !disposed && check === placementCheck && pending?.kind === 'arrange';
  }

  /** The server's preview of the square, put in the confirmation surface. */
  async function checkArrangement(
    check: number,
    base: AlternateVersion,
    request: ArrangementRequest,
    plan: ArrangementPlan,
    verdict: CompositionVerdictView,
  ): Promise<void> {
    if (client === null) return;
    const again = { label: 'Check again', run: () => stageArrangement(plan) };
    let preview: ArrangementPreview;
    try {
      preview = await previewArrangement(client, base, request);
    } catch (error) {
      if (arrangementIsCurrent(check)) verdict.refused(explainArrangementFailure(error, 'preview'), again);
      return;
    }
    if (!arrangementIsCurrent(check)) return;
    if (preview.blockedReason !== null) {
      if (preview.blockedReason === 'stale_base') {
        await rereadVersion(base.versionId);
        if (!arrangementIsCurrent(check)) return;
      }
      verdict.refused(
        explainArrangementRefusal(preview.blockedReason, preview.blockedDetail),
        RECHECKABLE_ARRANGEMENT_REFUSALS.has(preview.blockedReason) ? again : undefined,
      );
      return;
    }
    if (preview.arrangement === null
      || preview.version.authoredVersionId !== base.versionId
      || preview.version.worldId !== base.worldId
      || preview.version.stateSha256 !== base.stateSha256) {
      verdict.refused(Object.freeze({
        happened: 'The world answered about a different change than the one shown here.',
        next: 'Nothing was changed. Check again.',
        code: null,
        detail: `Answered for version ${preview.version.authoredVersionId} at ${preview.version.stateSha256}.`,
        outcome: 'unchanged' as const,
      }), again);
      return;
    }
    placementReady = true;
    verdict.ready(
      `${preview.arrangement.title}: ${preview.arrangement.summary} It adds `
      + `${objectCount(preview.wouldAdd.length)} in front of you, facing you, each its own change, so `
      + '“Take back the last change” removes them one at a time, newest first. Confirm to place '
      + 'it, or Cancel to leave the world as it is.',
    );
    confirm.setConfirmable(true);
  }

  /** An applied square, or the stale base it met, which is read again and offered back. */
  async function settleArrangement(
    result: ArrangementWriteResult,
    plan: ArrangementPlan,
  ): Promise<void | 'reported'> {
    if (result.kind === 'recorded') {
      const { arrangement, addedObjectIds } = result.applied;
      await settle(
        { kind: 'recorded', version: result.version },
        `Placed “${arrangement.title}”: ${objectCount(addedObjectIds.length)}, each its own change. `
          + '“Take back the last change” removes them one at a time, newest first.',
      );
      return;
    }
    if (disposed) return 'reported';
    version = result.current;
    await redrawAll();
    reportArrangementFailure(explainArrangementRefusal('stale_base'), plan);
    return 'reported';
  }

  function objectCount(count: number): string {
    return count === 1 ? 'one object' : `${count} objects`;
  }

  function reportArrangementFailure(explanation: CompositionExplanation, plan: ArrangementPlan): void {
    const recheck = explanation.outcome === 'unchanged'
      && explanation.code !== null
      && RECHECKABLE_ARRANGEMENT_REFUSALS.has(explanation.code);
    confirm.reportFailure(explanation.happened, {
      ...(explanation.outcome === 'unknown' ? { title: 'Not confirmed' } : {}),
      next: explanation.next,
      details: compositionDetails(explanation),
      ...(recheck ? { retry: { label: 'Check again', run: () => stageArrangement(plan) } } : {}),
    });
    panel.report(`${explanation.happened} ${explanation.next}`, 'failure');
  }

  function proposeMove(): void {
    const object = selectedRecord();
    if (object === null || nudged === null || version === null) return;
    const target = nudged;
    if (isAuthoredRegionId(object.regionId) && !authoredContains(target.xMm, target.zMm)) {
      panel.report('That move is outside this world’s authored ground and was not saved.', 'failure');
      return;
    }
    stage({
      kind: 'move',
      describe: `Move “${object.asset.title}” to where you have just put it${offsetWords(object, target)}.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        const result = await client.move(version, object.objectId, target);
        nudged = null;
        panel.setPendingMove(null);
        await settle(result, 'Moved.');
      },
    });
  }

  function proposeRemoval(objectId: string): void {
    const object = recordOf(objectId);
    if (object === null) return;
    stage({
      kind: 'remove',
      describe: `Take “${object.asset.title}” out of this world.`,
      // The contract stores a removal rather than executing it: "the row survives with
      // removed = true, so the object id stays stable and undo restores it rather than
      // resurrecting a new identity." So this genuinely is reversible, and saying otherwise would
      // be the false reversibility claim `confirm.ts` calls the worst sentence to get wrong.
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        const result = await client.remove(version, objectId);
        await settle(result, 'Removed. You can take that back.');
      },
    });
  }

  /**
   * Give a placed object a bounded motion, or replace the one it carries, as its own edit.
   *
   * The parameters are sent exactly as chosen and nothing here decides whether they are allowed:
   * the server's reviewed registry does, and a refusal reaches the confirmation surface and the
   * status line in its words, with nothing saved. The controls stay open after a refusal so the
   * person can correct what they chose rather than choose it all again.
   */
  function proposeMotion(objectId: string, motion: MotionDraft): void {
    const object = recordOf(objectId);
    if (object === null) return;
    const stored = storedMotionOf(object);
    if (stored !== null && stored.axis === motion.axis && stored.easing === motion.easing
      && stored.travelMm === motion.travelMm
      && stored.periodMilliseconds === motion.periodMilliseconds) {
      panel.report('That is the motion it already has, so there is nothing to save.');
      return;
    }
    const behaviour = boundedPath(motion);
    stage({
      kind: 'behaviour',
      describe: (object.behaviour === null
        ? `Give “${object.asset.title}” a motion: `
        : `Change the motion of “${object.asset.title}” to this: `)
        + `${motionWords(motion)}. It stays where it was placed, at rest until you start it.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        const result = await client.setBehaviour(version, objectId, behaviour);
        await settle(result, 'Motion saved. Start runs it, and “Take back the last change” removes it.');
        if (result.kind === 'recorded') panel.closeMotionEditor();
      },
    });
  }

  /** Take a placed object's motion away. The object stays, still, where it was placed. */
  function proposeClearMotion(objectId: string): void {
    const object = recordOf(objectId);
    if (object === null || object.behaviour === null) return;
    stage({
      kind: 'behaviour',
      describe: `Take the motion away from “${object.asset.title}”. It stays where it was placed.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        const result = await client.setBehaviour(version, objectId, null);
        await settle(result, 'Motion taken away. You can take that back.');
        if (result.kind === 'recorded') panel.closeMotionEditor();
      },
    });
  }

  /**
   * Undo, which the contract owns rather than this surface.
   *
   * It reverses "the newest edit that no undo already names", from the document that edit stored,
   * so three edits can be taken back one at a time. This surface therefore does not track what to
   * undo and must not: a client's memory of an edit is exactly what `before_document` exists to
   * replace.
   */
  function proposeUndo(): void {
    if (version === null) return;
    const last = [...version.edits].reverse()
      .find((edit) => edit.kind !== 'undo'
        && !version!.edits.some((other) => other.undoneEditId === edit.editId));
    if (last === undefined) {
      panel.report('There is nothing left to take back in this world.', 'failure');
      return;
    }
    stage({
      kind: 'undo',
      describe: `Take back the last change to this world: ${editWords(last.kind)}.`,
      reversible: false,
      run: async () => {
        if (client === null || version === null) {
          panel.report(NO_AUTHORITY, 'failure');
          return;
        }
        await settle(await client.undo(version), 'Taken back.');
      },
    });
  }

  /** Stage a write and render it for reading. Nothing is sent until the panel's confirm. */
  function stage(next: Pending): void {
    pending = next;
    placementReady = false;
    placementCheck += 1;
    issued += 1;
    deps.hideWritePathConfirm();
    if (next.kind !== 'place') clearPlacementLandingMark();
    confirm.show(`world-object-${issued}`, summaryFor(next), next.describe, {
      undoControlAvailable: client !== null && next.reversible
        && (next.kind === 'place' || next.kind === 'arrange' || next.kind === 'move'
          || next.kind === 'remove' || next.kind === 'behaviour'),
      ...(next.verdict === undefined ? {} : { verdict: next.verdict.root, confirmable: false }),
    });
  }

  async function commit(): Promise<void> {
    const running = pending;
    if (running === null) return;
    // A placement, or a square, is confirmable only on the server's ready verdict for exactly
    // this request.
    if ((running.kind === 'place' || running.kind === 'arrange') && !placementReady) return;
    pending = null;
    placementReady = false;
    placementCheck += 1;
    clearPlacementLandingMark();
    panel.setBusy(true);
    try {
      if (await running.run() !== 'reported') confirm.hide();
    } catch (error) {
      if (running.failed !== undefined) {
        running.failed(error);
      } else {
        confirm.reportFailure(objectWriteFailure(error));
        panel.report(objectWriteFailure(error), 'failure');
      }
    } finally {
      panel.setBusy(false);
    }
  }

  /**
   * What came back: the whole version, or the same thing plus a refusal.
   *
   * Every mutation answers with `AlternateVersionView`, so a write is also the re-read and there
   * is no second request to get out of step with.
   */
  async function settle(result: ObjectWriteResult, said: string): Promise<void> {
    if (disposed) return;
    const next = result.kind === 'stale' ? result.current : result.version;
    version = next;
    await redrawAll();
    if (result.kind === 'stale') {
      panel.report(
        'This world changed while you were deciding, so nothing was written. '
        + 'What is shown is current; choose again.',
        'failure',
      );
      return;
    }
    panel.report(said, 'settled');
    if (next !== undefined && deps.onAuthoredEdit) {
      try {
        await deps.onAuthoredEdit(next.versionId);
      } catch {
        deps.showTravelStatus('Your change was saved. Society updates are temporarily unavailable.', 'failure');
      }
    }
  }

  async function redrawAll(generation = ++drawGeneration): Promise<void> {
    const runtime = state.atlas?.binding.objects;
    const retainedSelection = selectedId;
    const retainedSelectionRevision = selectionRevision;
    clearingRepresentationsForRedraw = true;
    try {
      runtime?.clear();
    } finally {
      clearingRepresentationsForRedraw = false;
    }
    notices.clear();
    if (selectedId !== null) {
      const selected = recordOf(selectedId);
      if (selected === null || selected.asset.availability !== 'available') {
        selectedId = null;
        selectionRevision += 1;
      }
    }
    nudged = null;
    panel.setPendingMove(null);
    await drawEvery(generation);
    if (disposed || generation !== drawGeneration
      || selectionRevision !== retainedSelectionRevision
      || selectedId !== retainedSelection) return;
    reflectObjectSelectionInDataView(retainedSelection);
  }

  // -- moving, running and selecting -----------------------------------------------------------------

  function select(objectId: string | null): void {
    if (nudged !== null) discardMove();
    selectedId = objectId;
    selectionRevision += 1;
    reflectObjectSelectionInDataView(objectId);
    refresh();
  }

  function reflectObjectSelectionInDataView(objectId: string | null): void {
    const binding = state.atlas?.binding;
    if (binding?.setRepresentationSelection === undefined) return;
    const available = objectId !== null && binding.representationReport.subjects.some(entry =>
      entry.subject.subjectId === objectId && entry.subject.availability === 'available');
    // Unsupported geometry remains selectable here, but another data subject must not stay
    // highlighted as though it were the chosen object.
    const target = available ? objectId : null;
    if (binding.representationReport.selection === target) return;
    try {
      publishingObjectSelection = true;
      binding.setRepresentationSelection(target);
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      if (binding.representationReport.selection !== null) binding.setRepresentationSelection(null);
    } finally {
      publishingObjectSelection = false;
    }
  }

  function reflectDataViewSelection(
    subjectId: string | null,
    reason: 'explicit' | 'unavailable' | 'unregistered',
  ): void {
    if (publishingObjectSelection) return;
    if (clearingRepresentationsForRedraw && subjectId === null && reason === 'unregistered') return;
    const next = subjectId !== null && recordOf(subjectId) !== null ? subjectId : null;
    if (next === selectedId) { refresh(); return; }
    if (nudged !== null) discardMove();
    selectedId = next;
    selectionRevision += 1;
    refresh();
  }

  function nudge(delta: { xMm?: number; yMm?: number; zMm?: number; yaw?: number }): void {
    const object = selectedRecord();
    const runtime = state.atlas?.binding.objects;
    if (object === null || runtime === undefined) return;
    const next = nudgedPose(nudged ?? poseOf(object), delta);
    if (isAuthoredRegionId(object.regionId) && !authoredContains(next.xMm, next.zMm)) {
      panel.report('The authored ground ends here. This move was not applied.', 'failure');
      return;
    }
    nudged = next;
    runtime.setTransform(object.objectId, next);
    panel.setPendingMove(`Not saved yet: “${object.asset.title}”${offsetWords(object, next)}.`);
    refresh();
  }

  function isAuthoredRegionId(regionId: string): boolean {
    return deps.authoredRegion?.regionId === regionId;
  }

  function discardMove(): void {
    const object = selectedRecord();
    nudged = null;
    panel.setPendingMove(null);
    if (object === null) return;
    state.atlas?.binding.objects.setTransform(object.objectId, poseOf(object));
    refresh();
  }

  function control(objectId: string, action: BehaviourControlKey): void {
    const runtime = state.atlas?.binding.objects;
    if (runtime === undefined) {
      panel.report('The world is not drawn yet.', 'failure');
      return;
    }
    const result = runtime.control(objectId, action);
    if (!result.ok) {
      panel.report(result.reason, 'failure');
      deps.showTravelStatus(result.reason, 'failure');
      refresh();
      return;
    }
    panel.report({
      trigger: 'Travelling.',
      stop: 'Stopped where it is.',
      reset: 'Back exactly where it was placed.',
    }[action], 'settled');
    refresh();
  }

  // -- rendering the panel ---------------------------------------------------------------------------

  /** Removed objects are kept by the authority and are not drawn. Undo brings them back. */
  function visibleObjects(): readonly AuthoredObject[] {
    return everyRecord().filter((record) => !record.removed);
  }

  function everyRecord(): readonly AuthoredObject[] {
    return version?.objects ?? [];
  }

  function recordOf(objectId: string): AuthoredObject | null {
    return visibleObjects().find((row) => row.objectId === objectId) ?? null;
  }

  function selectedRecord(): AuthoredObject | null {
    return selectedId === null ? null : recordOf(selectedId);
  }

  function axisWords(axis: MotionAxisKey): string {
    return { x: 'side to side', y: 'up and down', z: 'forward and back' }[axis] ?? String(axis);
  }

  /** The reviewed behaviour a motion draft names, in the registry's own parameter names. */
  function boundedPath(motion: MotionDraft): ObjectBehaviour {
    return {
      behaviourKey: BOUNDED_PATH_KEY,
      behaviourVersion: BOUNDED_PATH_VERSION,
      parameters: {
        axis: motion.axis,
        easing: motion.easing,
        travel_mm: motion.travelMm,
        period_milliseconds: motion.periodMilliseconds,
      },
    };
  }

  function motionWords(motion: MotionDraft): string {
    return `${axisWords(motion.axis)}, ${(motion.travelMm / MM_PER_METRE).toFixed(2)} m out and `
      + `back every ${(motion.periodMilliseconds / 1000).toFixed(1)} s, `
      + (motion.easing === 'linear' ? 'at an even pace' : 'easing in and out');
  }

  /** The stored motion in the panel's own controls, or null when they cannot show it exactly. */
  function storedMotionOf(record: AuthoredObject): MotionDraft | null {
    const behaviour = record.behaviour;
    if (behaviour === null || behaviour.behaviourKey !== BOUNDED_PATH_KEY
      || behaviour.behaviourVersion !== BOUNDED_PATH_VERSION) return null;
    const read = BEHAVIOUR_REGISTRY.readParameters(
      behaviour.behaviourKey, behaviour.behaviourVersion, behaviour.parameters,
    );
    if (!read.ok || read.clamped.length > 0) return null;
    return Object.freeze({
      axis: String(read.parameters['axis']),
      easing: String(read.parameters['easing']),
      travelMm: Number(read.parameters['travel_mm']),
      periodMilliseconds: Number(read.parameters['period_milliseconds']),
    });
  }

  function editWords(kind: string): string {
    return {
      add_object: 'an object you added',
      move_object: 'a move',
      remove_object: 'a removal',
      set_object_behaviour: 'a change to an object’s motion',
    }[kind] ?? kind.replace(/_/g, ' ');
  }

  function offsetWords(record: AuthoredObject, pose: RegionPose): string {
    const saved = poseOf(record);
    const moved = Math.hypot(pose.xMm - saved.xMm, pose.yMm - saved.yMm, pose.zMm - saved.zMm);
    return moved === 0 ? '' : `, about ${(moved / MM_PER_METRE).toFixed(2)} of a step from where it is saved`;
  }

  function motionOf(record: AuthoredObject): PlacedObjectRow['motion'] {
    if (record.behaviour === null) return 'none';
    const held = state.atlas?.binding.objects.motionStateOf(record.objectId) ?? null;
    if (held === null || held === 'none') return 'unsupported';
    return held as PlacedObjectRow['motion'];
  }

  function refresh(): void {
    panel.showAssets(
      assets.map((asset) => ({
        assetKey: asset.assetKey,
        label: asset.title,
        summary: asset.summary,
        available: asset.availability === 'available',
        unavailableReason: asset.availability === 'available' ? null : asset.availability,
        licenceId: asset.licenceId,
      })),
      Object.entries(OBJECT_ROLE_LABELS).map(([key, label]) => ({ key, label })),
    );
    panel.showObjects(
      visibleObjects().map((record) => ({
        objectId: record.objectId,
        label: record.asset.title,
        motion: motionOf(record),
        storedMotion: storedMotionOf(record),
        note: notices.get(record.objectId) ?? null,
      })),
      selectedId,
    );
    panel.setUndoable(
      version !== null
      && version.edits.some((edit) => edit.kind !== 'undo'
        && !version!.edits.some((other) => other.undoneEditId === edit.editId)),
    );
  }

  /**
   * The confirmation summary for an object write.
   *
   * Band 1 is "what you told me", rendered VERBATIM, and that is exactly what a placement is: the
   * person chose an object, a role and a place, and the sentence is their statement rather than a
   * system inference. Putting it there is what makes `confirm.ts`'s effect sentence read as
   * something true; its label table is a closed list of graph predicates and a row with no
   * verbatim text would render as "this proposed change", which describes nothing.
   *
   * Bands 2 and 3 are empty and band 4 is never omitted, both by specification: an authored object
   * is supported by no captures and inferred by nothing.
   */
  function summaryFor(next: Pending): ConfirmationSummary {
    const band = (
      id: ConfirmationBand['band'],
      toneKey: ConfirmationBand['toneKey'],
      rows: ConfirmationBand['rows'],
    ): ConfirmationBand => Object.freeze({ band: id, toneKey, rows, omitted: false as const });
    // Opening an alternate and undo have no inverse on this surface.
    const tier = next.reversible ? 1 : 2;
    return Object.freeze({
      draftId: `world-object-${issued}`,
      tier,
      policy: tierPolicy(tier),
      bands: Object.freeze([
        band('told', 'warm', Object.freeze([Object.freeze({
          rowKey: `world-object:${next.kind}`,
          verbatim: next.describe,
          labelKey: 'row.note',
          value: null,
          evidence: Object.freeze([]),
          methodKey: null,
          confidence: null,
          editable: false,
          removable: false,
          rejectable: false,
          pending: true,
        })])),
        band('captures', 'neutral', Object.freeze([])),
        band('inferred', 'cool', Object.freeze([])),
        band('unknown', 'plain', Object.freeze([])),
      ]) as ConfirmationSummary['bands'],
      external: null,
      // An authored object touches no evidence points and no memory regions, so a radius in
      // counts would be two zeroes dressed as a warning.
      blastRadius: null,
      reversible: next.reversible,
      permittedHere: true,
    });
  }

  // -- keys ------------------------------------------------------------------------------------------

  /**
   * P opens the surface, the arrow keys move what is selected, and nothing the rest of the
   * application already owns is touched.
   *
   * `input-modes.ts` holds the one window keydown listener and is not extensible from outside it,
   * so this registers its own with its own controller rather than borrowing `state.mountListeners`,
   * which that module resets after this surface is mounted. Two listeners are only safe because
   * the keys are disjoint: movement is WASD and Shift, the shell owns I, M, O, Backspace and ?,
   * and the controls own E, Space, Enter, X and Escape. P, the arrows, the page keys and the
   * brackets are claimed by nothing.
   */
  window.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
    if (!deps.isWorldPrimary()) return;
    const target = event.target;
    if (target instanceof HTMLElement
      && (target.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName))) {
      return;
    }
    if (event.code === 'Escape' && document.pointerLockElement == null && panel.visible() && confirm.root.hidden) {
      event.preventDefault();
      setPanelVisible(false);
      return;
    }
    if (event.code === 'KeyP') {
      event.preventDefault();
      setPanelVisible(!panel.visible());
      return;
    }
    if (!panel.visible()) return;
    const move: Readonly<Record<string, Parameters<typeof nudge>[0]>> = {
      ArrowUp: { zMm: -NUDGE_STEP_MM },
      ArrowDown: { zMm: NUDGE_STEP_MM },
      ArrowLeft: { xMm: -NUDGE_STEP_MM },
      ArrowRight: { xMm: NUDGE_STEP_MM },
      PageUp: { yMm: NUDGE_STEP_MM },
      PageDown: { yMm: -NUDGE_STEP_MM },
      BracketLeft: { yaw: -TURN_STEP },
      BracketRight: { yaw: TURN_STEP },
    };
    const delta = move[event.code];
    if (delta === undefined) return;
    if (selectedRecord() === null) {
      panel.report('Choose an object in the list first, then the arrow keys move it.');
      return;
    }
    event.preventDefault();
    nudge(delta);
  }, { signal: listeners.signal });

  const representationBinding = state.atlas?.binding;
  releaseRepresentationSelection = representationBinding?.observeRepresentationSelection?.(
    (subjectId, reason) => reflectDataViewSelection(subjectId, reason),
  ) ?? null;
  const initialRepresentationSelection = representationBinding?.representationReport?.selection;
  if (initialRepresentationSelection !== undefined) {
    reflectDataViewSelection(initialRepresentationSelection, 'explicit');
  }
  refresh();

  return {
    panel,
    confirm,
    close() { setPanelVisible(false); },
    toggle() {
      setPanelVisible(!panel.visible());
    },
    begin,
    dispose() {
      if (disposed) return;
      disposed = true;
      drawGeneration += 1;
      listeners.abort();
      releaseRepresentationSelection?.();
      releaseRepresentationSelection = null;
      clearPlacementLandingMark();
      state.atlas?.binding.objects.cancelPending();
      pending = null;
      placementReady = false;
      placementCheck += 1;
    },
  };
}

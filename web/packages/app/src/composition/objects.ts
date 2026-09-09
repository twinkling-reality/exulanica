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
 * than resurrecting a new identity". An earlier draft of this file told people a removal could not
 * be undone, which was written against a guessed contract and would now be a false reversibility
 * claim in the one place `confirm.ts` says it is least acceptable to be wrong.
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
 * **Preview draws but never sends.** `?preview=1` has no authority behind it, so the surface uses
 * a small built-in catalogue and says, every time, that what it drew was not saved.
 */

import {
  BEHAVIOUR_REGISTRY,
  BOUNDED_PATH_KEY,
  BOUNDED_PATH_VERSION,
  DISPLAY_EYE_HEIGHT,
  identityDisplayFrame,
  type AtlasScene,
  type Island,
  type IslandId,
  type SceneDisplayFrame,
} from '@exulanica/atlas-core';
import { tierPolicy } from '@exulanica/companion-runtime';
import type { ConfirmationBand, ConfirmationSummary } from '@exulanica/companion-runtime';
import {
  AUTHORED_OBJECT_MEDIA_TYPE,
  DEFAULT_PLACEMENT_DISTANCE_MM,
  MM_PER_METRE,
  fetchVerifiedObjectAsset,
  nudgedPose,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  regionPointFromAtlas,
  type PlacedAuthoredObject,
  type RegionPose,
} from '@exulanica/atlas-react/playcanvas';

import { buildConfirm, type ConfirmPanel } from '../ui/confirm.js';
import {
  buildObjectPlacement,
  type BehaviourControlKey,
  type MotionAxisKey,
  type ObjectPlacementDraft,
  type ObjectPlacementPanel,
  type PlacedObjectRow,
} from '../ui/object-placement.js';
import {
  OBJECT_ROLES,
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  objectWriteFailure,
  type AlternateVersion,
  type AuthoredObject,
  type ObjectRole,
  type ReviewedAsset,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';

/** How far one arrow key moves an object, in millimetres. A quarter of a step. */
const NUDGE_STEP_MM = 250;
/** How far one bracket key turns it, in radians. */
const TURN_STEP = Math.PI / 12;

export interface ObjectsDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly credentials: { readonly baseUrl: string; readonly token: string };
  /** The scene this mount is drawn from, for the regions an object may stand in. */
  readonly scene: AtlasScene;
  readonly showTravelStatus: (message: string, kind?: 'progress' | 'failure') => void;
  /** True while the world itself is the primary surface, so the key does not fight a dialog. */
  readonly isWorldPrimary: () => boolean;
  /** The write path's confirmation panel, hidden before this surface shows its own. */
  readonly hideWritePathConfirm: () => void;
  /** Injectable for tests. Production builds the real authority client. */
  readonly client?: WorldObjectsClient;
  /** Injectable for tests. Production fetches the verified container bytes. */
  readonly loadBytes?: (asset: ReviewedAsset, islandId: IslandId) => Promise<ArrayBuffer>;
}

export interface MountedObjects {
  readonly panel: ObjectPlacementPanel;
  readonly confirm: ConfirmPanel;
  toggle(): void;
  /** Read the authority and draw what it holds. Awaited by tests; fire and forget in the app. */
  begin(): Promise<void>;
  dispose(): void;
}

interface Pending {
  readonly kind: 'place' | 'move' | 'remove' | 'undo';
  readonly describe: string;
  readonly reversible: boolean;
  run(): Promise<void>;
}

export function mountObjects(deps: ObjectsDependencies): MountedObjects {
  const { env, state } = deps;
  const listeners = new AbortController();
  const definition = BEHAVIOUR_REGISTRY.resolve(BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION);

  const client = deps.client ?? (env.preview ? null : new WorldObjectsClient(deps.credentials));

  let assets: readonly ReviewedAsset[] = Object.freeze([]);
  let version: AlternateVersion | null = null;
  let selectedId: string | null = null;
  /** Where the selected object is right now, uncommitted. Null when it is where it is saved. */
  let nudged: RegionPose | null = null;
  let pending: Pending | null = null;
  let issued = 0;
  /** Refusals and clamps the runtime reported, by object, so a row can keep showing them. */
  const notices = new Map<string, string>();
  /** Objects the preview drew for this session only. Never sent anywhere. */
  const drawnInPreview: AuthoredObject[] = [];

  const confirm = buildConfirm({
    onConfirm: () => void commit(),
    onCancel: () => { pending = null; confirm.hide(); },
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
    onSelect: (objectId) => select(objectId),
    onControl: (objectId, action) => control(objectId, action),
    onRemove: (objectId) => proposeRemoval(objectId),
    onUndo: () => proposeUndo(),
    onSaveMove: () => proposeMove(),
    onDiscardMove: () => discardMove(),
    onClose: () => panel.setVisible(false),
  }, {
    axes: choiceParameter('axis').choices as readonly MotionAxisKey[],
    axisFallback: choiceParameter('axis').fallback as MotionAxisKey,
    easings: choiceParameter('easing').choices,
    easingFallback: choiceParameter('easing').fallback,
    travelMm: integerParameter('travel_mm'),
    periodMilliseconds: integerParameter('period_milliseconds'),
  });

  // -- reading -----------------------------------------------------------------------------------

  async function begin(): Promise<void> {
    if (client === null) {
      assets = PREVIEW_ASSETS;
      version = PREVIEW_VERSION;
      refresh();
      panel.report(
        'This is the development preview. Objects placed here are drawn for this session and are '
        + 'not saved.',
      );
      return;
    }
    try {
      const connected = await client.connect();
      assets = connected.assets;
      version = connected.version;
      refresh();
      if (version === null) {
        panel.report(
          'This world has no alternate version yet, so there is nowhere to add an object. '
          + 'Create one first.',
          'failure',
        );
        return;
      }
      await drawEvery();
      deps.showTravelStatus('Press P to add an object to this world.');
    } catch (error) {
      assets = Object.freeze([]);
      version = null;
      refresh();
      panel.report(`No objects could be read: ${objectWriteFailure(error)}`, 'failure');
    }
  }

  /** Every object the authority holds, verified and drawn. A failure is per object, not per world. */
  async function drawEvery(): Promise<void> {
    const runtime = state.atlas?.binding.objects;
    if (runtime === undefined || version === null) return;
    for (const record of visibleObjects()) {
      const failure = await draw(record);
      if (failure !== null) {
        notices.set(record.objectId, failure);
        deps.showTravelStatus(failure, 'failure');
      }
    }
    refresh();
  }

  /** Load one object's verified bytes and place it. Returns the reason it could not be drawn. */
  async function draw(record: AuthoredObject): Promise<string | null> {
    const runtime = state.atlas?.binding.objects;
    if (runtime === undefined) return 'The world is not drawn yet.';
    // The contract embeds the whole registry row on the object, so availability is already here.
    if (record.asset.availability !== 'available' && !env.preview) {
      return `The reviewed bytes for “${record.asset.title}” are not in storage `
        + `(${record.asset.availability}), so it cannot be drawn.`;
    }
    const island = regionOf(record.regionId);
    if (island === null) return 'That object names a region this world does not draw.';
    try {
      const bytes = await loadBytes(record.asset, island.islandId);
      const placed: PlacedAuthoredObject = {
        objectId: record.objectId,
        islandId: island.islandId,
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
      // A behaviour this build cannot run and a clamped parameter are both refusals the visitor is
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
      return error instanceof Error ? error.message : 'the object could not be drawn';
    }
  }

  function loadBytes(asset: ReviewedAsset, islandId: IslandId): Promise<ArrayBuffer> {
    if (deps.loadBytes !== undefined) return deps.loadBytes(asset, islandId);
    if (env.preview) return Promise.resolve(previewContainer());
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
  function placementRegion(): { readonly island: Island; readonly sceneId: string } | null {
    const drawn = drawnRegions();
    if (drawn.length === 0) return null;
    const pose = state.atlas?.binding.cameraPose();
    if (pose === undefined) return drawn[0]!;
    let best: { readonly island: Island; readonly sceneId: string } | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of drawn) {
      const distance = Math.hypot(
        candidate.island.placement.position.x - pose.position.x,
        candidate.island.placement.position.z - pose.position.z,
      );
      const reach = candidate.island.footprintRadiusLocal * candidate.island.placement.scale * 1.5;
      if (distance < bestDistance && distance <= reach) {
        bestDistance = distance;
        best = candidate;
      }
    }
    return best;
  }

  function drawnRegions(): readonly { readonly island: Island; readonly sceneId: string }[] {
    const scenes = new Map<IslandId, string>();
    for (const placed of state.placedPointMaps ?? []) scenes.set(placed.islandId, placed.sceneId);
    for (const trained of state.trainedGeometry) scenes.set(trained.islandId, trained.sceneId);
    for (const islandId of state.pointMaps?.keys() ?? []) {
      if (!scenes.has(islandId)) scenes.set(islandId, `legacy:${islandId}`);
    }
    return deps.scene.islands.flatMap((island) => {
      const sceneId = scenes.get(island.islandId);
      return sceneId === undefined ? [] : [{ island, sceneId }];
    });
  }

  function regionOf(regionId: string): Island | null {
    return deps.scene.islands.find((island) => String(island.islandId) === regionId) ?? null;
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
    island: Island,
    sceneId: string,
    pose: { readonly position: { readonly x: number; readonly y: number; readonly z: number } },
  ): number {
    if (groundIsMeasured(sceneId)) return 0;
    return regionPointFromAtlas(
      island.placement,
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
  function placementPose(island: Island, sceneId: string): RegionPose | null {
    const binding = state.atlas?.binding;
    if (binding === undefined) return null;
    const pose = binding.cameraPose();
    const ground = groundMmIn(island, sceneId, pose);
    const index = binding.engageFocusedAnchor();
    if (index !== null) {
      const at = index * 3;
      const positions = binding.table.atlasPositions;
      if (at + 2 < positions.length) {
        return placementPoseAtAtlasPoint(
          island.placement,
          [positions[at]!, positions[at + 1]!, positions[at + 2]!],
          pose,
          ground,
        );
      }
    }
    return placementPoseBeforeVisitor(island.placement, pose, DEFAULT_PLACEMENT_DISTANCE_MM, ground);
  }

  // -- proposing -----------------------------------------------------------------------------------

  function proposePlacement(draft: ObjectPlacementDraft): void {
    const asset = assets.find((candidate) => candidate.assetKey === draft.assetKey);
    if (asset === undefined) {
      panel.report('That object is not in the reviewed registry.', 'failure');
      return;
    }
    if (asset.availability !== 'available' && !env.preview) {
      panel.report(
        `The reviewed bytes for “${asset.title}” are not in storage, so it cannot be placed.`,
        'failure',
      );
      return;
    }
    if (version === null) {
      panel.report('There is no alternate world version to add this to.', 'failure');
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
          ? 'No region in this world draws a reconstruction, so there is no ground to stand an '
            + 'object on.'
          : 'You are not standing in a region with reconstructed ground. Walk into one, then '
            + 'place the object there.',
        'failure',
      );
      return;
    }
    const pose = placementPose(region.island, region.sceneId);
    if (pose === null) {
      panel.report('The world is still forming. Try again in a moment.', 'failure');
      return;
    }
    const role: ObjectRole = OBJECT_ROLES.includes(draft.role as ObjectRole)
      ? (draft.role as ObjectRole)
      : 'fictional';
    const behaviour = draft.motion
      ? {
          behaviourKey: BOUNDED_PATH_KEY,
          behaviourVersion: BOUNDED_PATH_VERSION,
          parameters: {
            axis: draft.axis,
            easing: draft.easing,
            travel_mm: draft.travelMm,
            period_milliseconds: draft.periodMilliseconds,
          },
        }
      : null;
    // The caller chooses the object id, and it is stable within the version. A monotonic counter
    // beside the edit sequence keeps it unique without a clock or a random source.
    const objectId = `object-${version.editSeq + 1}-${(issued += 1)}`;

    stage({
      kind: 'place',
      describe:
        `Add “${asset.title}” to ${regionLabel(region.island.islandId)}, `
        + (groundIsMeasured(region.sceneId)
          ? 'standing on the ground its cameras recovered'
          : 'standing at your feet, because this region has no recovered cameras to place a '
            + 'ground from')
        + `${behaviour === null ? '' : `, travelling ${axisWords(draft.axis)}`}.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          drawnInPreview.push(previewObject(objectId, asset, region.island, pose, behaviour, role));
          const failure = await draw(drawnInPreview.at(-1)!);
          refresh();
          panel.report(
            failure ?? 'Placed for this session only. The preview is read-only and nothing was saved.',
            failure === null ? 'settled' : 'failure',
          );
          return;
        }
        const result = await client.place(version, {
          objectId,
          assetSha256: asset.contentSha256,
          regionId: String(region.island.islandId),
          transform: pose,
          originRole: role,
          behaviour,
        });
        await settle(result, 'Added.');
      },
    });
  }

  function proposeMove(): void {
    const object = selectedRecord();
    if (object === null || nudged === null || version === null) return;
    const target = nudged;
    stage({
      kind: 'move',
      describe: `Move “${object.asset.title}” to where you have just put it${offsetWords(object, target)}.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          nudged = null;
          panel.setPendingMove(null);
          panel.report('The preview is read-only, so this position was not saved.', 'failure');
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
          const at = drawnInPreview.findIndex((row) => row.objectId === objectId);
          if (at !== -1) drawnInPreview.splice(at, 1);
          state.atlas?.binding.objects.remove(objectId);
          if (selectedId === objectId) select(null);
          refresh();
          panel.report('Taken out of this session. The preview is read-only.', 'failure');
          return;
        }
        const result = await client.remove(version, objectId);
        await settle(result, 'Removed. You can take that back.');
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
          panel.report('The preview is read-only, so there is nothing recorded to take back.', 'failure');
          return;
        }
        await settle(await client.undo(version), 'Taken back.');
      },
    });
  }

  /** Stage a write and render it for reading. Nothing is sent until the panel's confirm. */
  function stage(next: Pending): void {
    pending = next;
    issued += 1;
    deps.hideWritePathConfirm();
    confirm.show(`world-object-${issued}`, summaryFor(next), next.describe);
  }

  async function commit(): Promise<void> {
    const running = pending;
    if (running === null) return;
    pending = null;
    if (env.preview) {
      confirm.hide();
      panel.setBusy(true);
      try { await running.run(); } finally { panel.setBusy(false); }
      return;
    }
    panel.setBusy(true);
    try {
      await running.run();
      confirm.hide();
    } catch (error) {
      confirm.reportFailure(objectWriteFailure(error));
      panel.report(objectWriteFailure(error), 'failure');
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
  async function settle(
    result: { readonly kind: 'recorded' | 'stale'; readonly version?: AlternateVersion; readonly current?: AlternateVersion },
    said: string,
  ): Promise<void> {
    const next = result.kind === 'stale' ? result.current : result.version;
    if (next !== undefined) version = next;
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
  }

  async function redrawAll(): Promise<void> {
    const runtime = state.atlas?.binding.objects;
    if (runtime !== undefined) for (const objectId of runtime.objectIds) runtime.remove(objectId);
    notices.clear();
    if (selectedId !== null && recordOf(selectedId) === null) selectedId = null;
    nudged = null;
    panel.setPendingMove(null);
    await drawEvery();
  }

  // -- moving, running and selecting -----------------------------------------------------------------

  function select(objectId: string | null): void {
    if (nudged !== null) discardMove();
    selectedId = objectId;
    refresh();
  }

  function nudge(delta: { xMm?: number; yMm?: number; zMm?: number; yaw?: number }): void {
    const object = selectedRecord();
    const runtime = state.atlas?.binding.objects;
    if (object === null || runtime === undefined) return;
    const next = nudgedPose(nudged ?? poseOf(object), delta);
    nudged = next;
    runtime.setTransform(object.objectId, next);
    panel.setPendingMove(`Not saved yet: “${object.asset.title}”${offsetWords(object, next)}.`);
    refresh();
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
    return client === null ? drawnInPreview : version?.objects ?? [];
  }

  function recordOf(objectId: string): AuthoredObject | null {
    return visibleObjects().find((row) => row.objectId === objectId) ?? null;
  }

  function selectedRecord(): AuthoredObject | null {
    return selectedId === null ? null : recordOf(selectedId);
  }

  function regionLabel(islandId: IslandId): string {
    return `region ${String(islandId).slice(0, 8)}`;
  }

  function axisWords(axis: MotionAxisKey): string {
    return { x: 'side to side', y: 'up and down', z: 'forward and back' }[axis] ?? String(axis);
  }

  function editWords(kind: string): string {
    return {
      add_object: 'an object you added',
      move_object: 'a move',
      remove_object: 'a removal',
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
        available: asset.availability === 'available' || env.preview,
        unavailableReason: asset.availability === 'available' ? null : asset.availability,
        licenceId: asset.licenceId,
      })),
      OBJECT_ROLES.map((key) => ({ key, label: OBJECT_ROLE_LABELS[key] })),
    );
    panel.showObjects(
      visibleObjects().map((record) => ({
        objectId: record.objectId,
        label: record.asset.title,
        regionLabel: regionLabel(record.regionId as IslandId),
        motion: motionOf(record),
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
    // Tier 2 for undo, which is the one operation here that cannot itself be taken back: an undo
    // edit is never a candidate for another undo.
    const tier = next.kind === 'undo' ? 2 : 1;
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
    if (event.code === 'KeyP') {
      event.preventDefault();
      panel.setVisible(!panel.visible());
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

  refresh();

  return {
    panel,
    confirm,
    toggle() {
      panel.setVisible(!panel.visible());
    },
    begin,
    dispose() {
      listeners.abort();
      pending = null;
    },
  };
}

// -- the preview catalogue ---------------------------------------------------------------------------

/**
 * What `?preview=1` offers, and the container it draws.
 *
 * Built here rather than read from `graph-client/test/fixtures/world-objects.json`, which is a
 * real `GET /world/versions/{id}` body the CLIENT's tests parse and which carries no bytes. A
 * preview needs something to draw. This is a box, it is obviously a box, and the surface says
 * every time that nothing placed in the preview was saved.
 */
const PREVIEW_ASSETS: readonly ReviewedAsset[] = Object.freeze([
  Object.freeze({
    assetKey: 'preview.marker',
    title: 'Preview marker',
    summary: 'A half-metre box, drawn by the development preview only.',
    mediaType: AUTHORED_OBJECT_MEDIA_TYPE,
    contentSha256: '0'.repeat(64),
    byteSize: 0,
    licenceId: 'CC0-1.0',
    licenceSha256: '0'.repeat(64),
    availability: 'available',
  }),
]);

const PREVIEW_VERSION: AlternateVersion = Object.freeze({
  schemaVersion: 1,
  versionId: 'preview',
  worldId: 'preview',
  sourceSnapshotId: 'preview',
  parentVersionId: null,
  title: 'Development preview',
  origin: 'authored',
  styleVersionId: null,
  stateSha256: '0'.repeat(64),
  editSeq: 0,
  sourceInvalidated: false,
  createdBy: 'preview',
  createdAt: '1970-01-01T00:00:00+00:00',
  objects: Object.freeze([]),
  elementOverrides: Object.freeze([]),
  edits: Object.freeze([]),
});

function previewObject(
  objectId: string,
  asset: ReviewedAsset,
  island: Island,
  pose: RegionPose,
  behaviour: {
    readonly behaviourKey: string;
    readonly behaviourVersion: number;
    readonly parameters: Readonly<Record<string, unknown>>;
  } | null,
  role: ObjectRole,
): AuthoredObject {
  return Object.freeze({
    objectId,
    asset,
    regionId: String(island.islandId),
    transform: Object.freeze({
      coordinateSpace: 'region_local',
      coordinateUnit: 'millimetre',
      ...pose,
    }),
    origin: Object.freeze({ kind: 'authored', role }),
    behaviour,
    removed: false,
  });
}

/** A self-contained GLB holding one half-metre box, built rather than shipped. */
function previewContainer(): ArrayBuffer {
  const h = 0.25;
  const positions = new Float32Array([
    -h, 0, -h, h, 0, -h, h, 2 * h, -h, -h, 2 * h, -h,
    -h, 0, h, h, 0, h, h, 2 * h, h, -h, 2 * h, h,
  ]);
  const indices = new Uint16Array([
    0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
    3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5,
  ]);
  const indexBytes = new Uint8Array(indices.buffer);
  const positionBytes = new Uint8Array(positions.buffer);
  const indexPadding = (4 - (indexBytes.length % 4)) % 4;
  const binary = new Uint8Array(positionBytes.length + indexBytes.length + indexPadding);
  binary.set(positionBytes, 0);
  binary.set(indexBytes, positionBytes.length);

  const gltf = {
    asset: { version: '2.0', generator: 'exulanica-preview' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, name: 'preview-marker' }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, material: 0 }] }],
    materials: [{
      name: 'preview',
      pbrMetallicRoughness: {
        baseColorFactor: [0.82, 0.55, 0.28, 1], metallicFactor: 0, roughnessFactor: 0.7,
      },
    }],
    accessors: [
      {
        bufferView: 0, componentType: 5126, count: 8, type: 'VEC3',
        min: [-h, 0, -h], max: [h, 2 * h, h],
      },
      { bufferView: 1, componentType: 5123, count: indices.length, type: 'SCALAR' },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: positionBytes.length, target: 34962 },
      {
        buffer: 0, byteOffset: positionBytes.length, byteLength: indexBytes.length, target: 34963,
      },
    ],
    buffers: [{ byteLength: binary.length }],
  };

  const json = new TextEncoder().encode(JSON.stringify(gltf));
  const jsonChunk = new Uint8Array(Math.ceil(json.length / 4) * 4).fill(0x20);
  jsonChunk.set(json);
  const total = 12 + 8 + jsonChunk.length + 8 + binary.length;
  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, total, true);
  view.setUint32(12, jsonChunk.length, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.set(jsonChunk, 20);
  view.setUint32(20 + jsonChunk.length, binary.length, true);
  view.setUint32(24 + jsonChunk.length, 0x004e4942, true);
  bytes.set(binary, 28 + jsonChunk.length);
  return bytes.buffer;
}

/**
 * Authored objects: the surface that places one, moves it, runs it, and takes it away again.
 *
 * This is product-direction.md's first milestone rows 3 and 4 assembled out of parts that each
 * refuse to do the others' job. The panel in `ui/object-placement.ts` builds elements and holds
 * no client. `world-objects-api.ts` speaks to the authority and knows nothing about a renderer.
 * `atlas-react`'s `SceneObjectRuntime` draws and animates and cannot write. This module is the
 * one place that knows all three exist, which is the same shape every other surface in
 * `composition/` has.
 *
 * **Every write goes through the confirmation surface.** Placing, moving and removing all stop at
 * `confirm.show(...)` and are sent only from the panel's own confirm handler. That is the
 * invariant `write-path.ts` states for the graph, held here for a different authority.
 *
 * **This surface builds its OWN confirmation panel, and that is deliberate.** `write-path.ts`
 * binds its panel's `onConfirm` to `session.commit`, which is the graph's mutation gate; an object
 * write is not a graph proposal and routing it through that panel would call the wrong authority
 * with an id it never staged. `buildConfirm` is a factory and the confirmation surface is
 * specified as ONE COMPONENT WITH TWO MOUNT POINTS (interaction-model.md 5.2), so a second
 * instance of the same component is the mechanically honest reading of "through the existing
 * confirmation surface". The two are never open at once: this one hides the write path's before
 * showing itself, so exactly one `#confirm-title` is ever in the document.
 *
 * **A nudge is not a write until it is saved.** The arrow keys move the object in the world
 * immediately, because a move nobody can see is a move nobody can judge, and they send nothing.
 * The accumulated position goes through the confirmation surface once, on a control that says so.
 * Confirming each keystroke would either make the interaction unusable or make the confirmation
 * meaningless, and the second failure is the worse one.
 *
 * **Trigger, stop and reset write nothing at all.** They are runtime state, and running is not a
 * property of a world. `docs/world-objects-contract.md` says so explicitly, and the object reopens
 * at the transform its author placed, at rest.
 *
 * **Preview draws but never sends.** `?preview=1` has no authority behind it, so the surface uses
 * a small built-in catalogue and says, every time, that what it drew was not saved. The
 * alternative was to disable the surface in preview, which would have made the one path available
 * for looking at this work the one path that cannot show it.
 */

import {
  BEHAVIOUR_REGISTRY,
  BOUNDED_MOTION_ID,
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
  AUTHORED_OBJECT_CONTAINER,
  DEFAULT_PLACEMENT_DISTANCE,
  displayPointFromAtlas,
  displayPoseOfObject,
  fetchVerifiedObjectAsset,
  objectTransformForDisplayPose,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  type DisplayPose,
  type PlacedAuthoredObject,
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
  OBJECT_ORIGINS,
  OBJECT_ORIGIN_LABELS,
  WorldObjectsClient,
  objectWriteFailure,
  type AuthoredObjectRecord,
  type AuthoredWorldVersion,
  type ObjectOrigin,
  type ReviewedObjectAsset,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';

/**
 * The world version an edit is made against, when nothing else names one.
 *
 * `docs/world-objects-contract.md` reserves `current` as the alias for the workspace's current
 * authored version. There is no version picker in this build and inventing one would be a second
 * milestone; naming the alias in one constant means the picker, when it arrives, is one edit.
 */
export const CURRENT_WORLD_VERSION = 'current';

/** How far one arrow key moves an object, in region display units. */
const NUDGE_STEP = 0.25;
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
  readonly loadBytes?: (asset: ReviewedObjectAsset, islandId: IslandId) => Promise<ArrayBuffer>;
}

export interface MountedObjects {
  readonly panel: ObjectPlacementPanel;
  readonly confirm: ConfirmPanel;
  /** Open or close the surface. Bound to a key in `main.ts`. */
  toggle(): void;
  /** Read the authority and draw what it holds. Awaited by tests; fire and forget in the app. */
  begin(): Promise<void>;
  dispose(): void;
}

interface Pending {
  readonly kind: 'place' | 'move' | 'remove';
  readonly describe: string;
  readonly reversible: boolean;
  run(): Promise<void>;
}

export function mountObjects(deps: ObjectsDependencies): MountedObjects {
  const { env, state } = deps;
  const listeners = new AbortController();
  const definition = BEHAVIOUR_REGISTRY.resolve(BOUNDED_MOTION_ID);

  const client = deps.client
    ?? (env.preview ? null : new WorldObjectsClient(deps.credentials));

  let assets: readonly ReviewedObjectAsset[] = Object.freeze([]);
  let version: AuthoredWorldVersion | null = null;
  let selectedId: string | null = null;
  /** Where the selected object is right now, uncommitted. Null when it is where it is saved. */
  let nudged: DisplayPose | null = null;
  let pending: Pending | null = null;
  let issued = 0;
  /** Refusals and clamps the runtime reported, by object, so a row can keep showing them. */
  const notices = new Map<string, string>();
  /** Objects the preview drew for this session only. Never sent anywhere. */
  const drawnInPreview: AuthoredObjectRecord[] = [];

  const confirm = buildConfirm({
    onConfirm: () => void commit(),
    onCancel: () => { pending = null; confirm.hide(); },
  });

  const panel = buildObjectPlacement({
    onPlace: (draft) => proposePlacement(draft),
    onSelect: (objectId) => select(objectId),
    onControl: (objectId, action) => control(objectId, action),
    onRemove: (objectId) => proposeRemoval(objectId),
    onSaveMove: () => proposeMove(),
    onDiscardMove: () => discardMove(),
    onClose: () => panel.setVisible(false),
  }, {
    axes: definition.ok ? [...definition.definition.axes] as MotionAxisKey[] : ['y'],
    amplitude: definition.ok ? definition.definition.ranges.amplitude : { min: 0, max: 1, fallback: 0.35 },
    period: definition.ok ? definition.definition.ranges.period : { min: 0.5, max: 20, fallback: 4 },
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
      const connected = await client.connect(CURRENT_WORLD_VERSION);
      assets = connected.registry.assets;
      version = connected.version;
      refresh();
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
    for (const record of version.objects) {
      const failure = await draw(record);
      if (failure !== null) {
        notices.set(record.objectId, failure);
        deps.showTravelStatus(failure, 'failure');
      }
    }
    refresh();
  }

  /** Load one object's verified bytes and place it. Returns the reason it could not be drawn. */
  async function draw(record: AuthoredObjectRecord): Promise<string | null> {
    const runtime = state.atlas?.binding.objects;
    if (runtime === undefined) return 'The world is not drawn yet.';
    const asset = assets.find((candidate) => candidate.assetId === record.assetId);
    if (asset === undefined) return `“${record.assetId}” is not in the reviewed registry.`;
    // The preview has no authority and therefore no stored bytes; it draws its own container.
    // Everywhere else a null reference is exactly what an unavailable asset looks like.
    if (asset.reference === null && !env.preview) {
      return `The file for “${asset.label}” is not in storage, so it cannot be drawn.`;
    }
    const island = regionOf(record.regionId);
    if (island === null) return 'That object names a region this world does not draw.';
    try {
      const bytes = await loadBytes(asset, island.islandId);
      const placed: PlacedAuthoredObject = {
        objectId: record.objectId,
        islandId: island.islandId,
        sceneId: record.sceneId,
        asset: {
          assetId: asset.assetId,
          container: AUTHORED_OBJECT_CONTAINER,
          path: asset.reference?.href ?? `/world-objects/assets/${asset.assetId}/bytes`,
          contentSha256: asset.reference?.contentSha256 ?? '0'.repeat(64),
          byteSize: asset.reference?.byteSize ?? 0,
        },
        sceneFromObjectRowMajor: record.sceneFromObject,
        behaviour: record.behaviour === null ? null : {
          behaviourId: record.behaviour.behaviourId,
          parameters: record.behaviour.parameters,
        },
      };
      const outcome = await runtime.place(placed, bytes, frameFor(record.sceneId));
      // An unsupported behaviour and a clamped parameter are both refusals the visitor is owed.
      // They are kept on the object rather than only announced, because the status line moves on.
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

  function loadBytes(asset: ReviewedObjectAsset, islandId: IslandId): Promise<ArrayBuffer> {
    if (deps.loadBytes !== undefined) return deps.loadBytes(asset, islandId);
    if (env.preview) return Promise.resolve(previewContainer());
    if (asset.reference === null) {
      return Promise.reject(new TypeError('That asset has no bytes in storage.'));
    }
    return fetchVerifiedObjectAsset(
      islandId,
      {
        assetId: asset.assetId,
        container: AUTHORED_OBJECT_CONTAINER,
        path: asset.reference.href,
        contentSha256: asset.reference.contentSha256,
        byteSize: asset.reference.byteSize,
      },
      listeners.signal,
      { baseUrl: deps.credentials.baseUrl, token: deps.credentials.token },
    );
  }

  // -- where an object goes ------------------------------------------------------------------------

  /**
   * The region an object is placed in: the one the visitor is STANDING IN, or none.
   *
   * Nearest by ground-plane distance among the regions that actually draw reconstructed geometry,
   * because an object placed in a region with nothing in it would stand on an absent floor. This
   * reads an atlas position as a position, which is only legitimate inside a presentation
   * decision; it decides where a made thing is DRAWN and answers nothing about the captured world.
   *
   * NEAREST IS NOT ENOUGH, and the browser check is what proved it. A visitor standing in a
   * region with no reconstruction still has a nearest reconstructed region, on the other side of
   * the world. Placing there converts their position into that region's frame and drops the
   * object onto THAT region's ground, so it lands at a height they are not standing at and
   * disappears the moment the distant region falls back to a stub. The person sees nothing and is
   * told the placement succeeded, which is the worst of the available outcomes. So a placement
   * outside the region's own footprint is refused, and the refusal says what to do instead.
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
      // The region's own extent, in atlas units, with room to stand at its edge and place inward.
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
    // The legacy unposed path synthesises the same scene id the binding does.
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
   * A scene with no recovered cameras gets the identity frame from `display-frame.ts` itself, so
   * falling back to it here is the same answer rather than a substitute for one. The preview,
   * which loads geometry from disk and computes no frames at all, lands here too.
   */
  function frameFor(sceneId: string): SceneDisplayFrame {
    return state.displayFrames.get(sceneId) ?? identityDisplayFrame();
  }

  /**
   * Where a new object lands: on an engaged anchor, or a step in front of the visitor.
   *
   * The focused anchor is what "the focused point" means in this application: there is no picked
   * world point, and `engageFocusedAnchor` is the one public read of what the reticle has settled
   * on. When nothing is engaged, the object goes on the ground ahead, facing the person.
   */
  function placementPose(island: Island, frame: SceneDisplayFrame): DisplayPose | null {
    const binding = state.atlas?.binding;
    if (binding === undefined) return null;
    const pose = binding.cameraPose();
    const ground = groundHeightIn(island, frame, pose);
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
    return placementPoseBeforeVisitor(island.placement, pose, DEFAULT_PLACEMENT_DISTANCE, ground);
  }

  /**
   * What counts as the ground in a region, and whether that is a measurement.
   *
   * A display frame derived from recovered cameras puts the estimated ground at `y = 0`, so an
   * object placed there stands on the same surface the geometry does. A region with no recovered
   * cameras has the IDENTITY frame, whose origin is the scene's own arbitrary one, and placing at
   * `y = 0` there drops the object under the floor the visitor is walking on. In that case the
   * ground is taken to be the visitor's own feet, which is an approximation and is said to be one
   * on the confirmation the person reads.
   */
  function groundHeightIn(
    island: Island,
    frame: SceneDisplayFrame,
    pose: { readonly position: { readonly x: number; readonly y: number; readonly z: number } },
  ): number {
    if (frame.cameraCount > 0) return 0;
    return displayPointFromAtlas(
      island.placement,
      [pose.position.x, pose.position.y - DISPLAY_EYE_HEIGHT, pose.position.z],
    )[1];
  }

  /** True when this region's ground was estimated from recovered cameras rather than assumed. */
  function groundIsMeasured(sceneId: string): boolean {
    return frameFor(sceneId).cameraCount > 0;
  }

  // -- proposing -----------------------------------------------------------------------------------

  function proposePlacement(draft: ObjectPlacementDraft): void {
    const asset = assets.find((candidate) => candidate.assetId === draft.assetId);
    if (asset === undefined) {
      panel.report('That object is not in the reviewed registry.', 'failure');
      return;
    }
    if (asset.reference === null && !env.preview) {
      panel.report(`The file for “${asset.label}” is not in storage.`, 'failure');
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
    const frame = frameFor(region.sceneId);
    const pose = placementPose(region.island, frame);
    if (pose === null) {
      panel.report('The world is still forming. Try again in a moment.', 'failure');
      return;
    }
    const sceneFromObject = objectTransformForDisplayPose(frame, pose);
    const behaviour = draft.motion
      ? {
          behaviourId: BOUNDED_MOTION_ID,
          parameters: { axis: draft.axis, amplitude: draft.amplitude, period: draft.period },
        }
      : null;
    const origin = OBJECT_ORIGINS.includes(draft.origin as ObjectOrigin)
      ? (draft.origin as ObjectOrigin)
      : 'fictional-source';

    stage({
      kind: 'place',
      describe:
        `Add “${asset.label}” to ${regionLabel(region.island.islandId)}, `
        + (groundIsMeasured(region.sceneId)
          ? 'standing on the ground its cameras recovered'
          : 'standing at your feet, because this region has no recovered cameras to place a '
            + 'ground from')
        + `${behaviour === null ? '' : `, moving ${axisWords(draft.axis)}`}.`,
      reversible: true,
      run: async () => {
        const record: AuthoredObjectRecord = {
          objectId: `preview-object-${(issued += 1)}`,
          assetId: asset.assetId,
          regionId: String(region.island.islandId),
          sceneId: region.sceneId,
          sceneFromObject,
          origin,
          behaviour,
          basedOnWorldVersionId: version?.worldVersionId ?? null,
          recordedSha256: '0'.repeat(64),
        };
        if (client === null || version === null) {
          drawnInPreview.push(record);
          const failure = await draw(record);
          refresh();
          panel.report(
            failure ?? 'Placed for this session only. The preview is read-only and nothing was saved.',
            failure === null ? 'settled' : 'failure',
          );
          return;
        }
        const result = await client.place(version, {
          assetId: asset.assetId,
          regionId: String(region.island.islandId),
          sceneId: region.sceneId,
          sceneFromObject,
          origin,
          behaviour,
        });
        await settle(result, 'Added.');
      },
    });
  }

  function proposeMove(): void {
    const object = selectedRecord();
    if (object === null || nudged === null) return;
    const moved = objectTransformForDisplayPose(frameFor(object.sceneId), nudged);
    const target = nudged;
    stage({
      kind: 'move',
      describe: `Move “${labelOf(object)}” to where you have just put it${offsetWords(object, target)}.`,
      reversible: true,
      run: async () => {
        if (client === null || version === null) {
          nudged = null;
          panel.setPendingMove(null);
          panel.report('The preview is read-only, so this position was not saved.', 'failure');
          return;
        }
        const result = await client.move(version, object.objectId, moved);
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
      describe: `Take “${labelOf(object)}” out of this world.`,
      // Re-adding produces a new object with a new identity. That is not the same thing as an
      // undo, and the confirmation surface is required to be true about which it is.
      reversible: false,
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
        state.atlas?.binding.objects.remove(objectId);
        if (selectedId === objectId) select(null);
        await settle(result, 'Removed.');
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
      // The same guard `write-path.ts` states, for the same reason: the preview has no authority
      // behind it. It still draws, and it still says the drawing was not saved.
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

  /** What came back from the authority: recorded, or refused because the base moved. */
  async function settle(
    result: { readonly kind: 'recorded' | 'stale'; readonly current?: AuthoredWorldVersion },
    said: string,
  ): Promise<void> {
    if (result.kind === 'stale' && result.current !== undefined) {
      version = result.current;
      await redrawAll();
      panel.report(
        'This world changed while you were deciding, so nothing was written. '
        + 'What is shown is current; choose again.',
        'failure',
      );
      return;
    }
    if (client !== null) version = await client.refreshObjects(CURRENT_WORLD_VERSION);
    await redrawAll();
    panel.report(said, 'settled');
  }

  async function redrawAll(): Promise<void> {
    const runtime = state.atlas?.binding.objects;
    if (runtime !== undefined) for (const objectId of runtime.objectIds) runtime.remove(objectId);
    notices.clear();
    await drawEvery();
  }

  // -- moving, running and selecting -----------------------------------------------------------------

  function select(objectId: string | null): void {
    if (nudged !== null) discardMove();
    selectedId = objectId;
    refresh();
  }

  function nudge(delta: { x?: number; y?: number; z?: number; yaw?: number }): void {
    const object = selectedRecord();
    const runtime = state.atlas?.binding.objects;
    if (object === null || runtime === undefined) return;
    const frame = frameFor(object.sceneId);
    const from = nudged ?? displayPoseOfObject(frame, object.sceneFromObject);
    const next: DisplayPose = Object.freeze({
      x: from.x + (delta.x ?? 0),
      y: Math.max(0, from.y + (delta.y ?? 0)),
      z: from.z + (delta.z ?? 0),
      yaw: from.yaw + (delta.yaw ?? 0),
    });
    nudged = next;
    runtime.setTransform(object.objectId, objectTransformForDisplayPose(frame, next), frame);
    panel.setPendingMove(`Not saved yet: “${labelOf(object)}”${offsetWords(object, next)}.`);
    refresh();
  }

  function discardMove(): void {
    const object = selectedRecord();
    nudged = null;
    panel.setPendingMove(null);
    if (object === null) return;
    const frame = frameFor(object.sceneId);
    state.atlas?.binding.objects.setTransform(object.objectId, object.sceneFromObject, frame);
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
      // The milestone requires an unsupported behaviour to fail visibly. It fails here as well as
      // at placement, because this is where a person actually pressed something.
      panel.report(result.reason, 'failure');
      deps.showTravelStatus(result.reason, 'failure');
      refresh();
      return;
    }
    panel.report({
      trigger: 'Moving.',
      stop: 'Stopped where it is.',
      reset: 'Back exactly where it was placed.',
    }[action], 'settled');
    refresh();
  }

  // -- rendering the panel ---------------------------------------------------------------------------

  function everyRecord(): readonly AuthoredObjectRecord[] {
    return client === null ? drawnInPreview : version?.objects ?? [];
  }

  function recordOf(objectId: string): AuthoredObjectRecord | null {
    return everyRecord().find((row) => row.objectId === objectId) ?? null;
  }

  function selectedRecord(): AuthoredObjectRecord | null {
    return selectedId === null ? null : recordOf(selectedId);
  }

  function labelOf(record: AuthoredObjectRecord): string {
    return assets.find((asset) => asset.assetId === record.assetId)?.label ?? record.assetId;
  }

  function regionLabel(islandId: IslandId): string {
    return `region ${String(islandId).slice(0, 8)}`;
  }

  function axisWords(axis: MotionAxisKey): string {
    return { x: 'side to side', y: 'up and down', z: 'forward and back' }[axis];
  }

  function offsetWords(record: AuthoredObjectRecord, pose: DisplayPose): string {
    const saved = displayPoseOfObject(frameFor(record.sceneId), record.sceneFromObject);
    const moved = Math.hypot(pose.x - saved.x, pose.y - saved.y, pose.z - saved.z);
    return moved < 1e-6 ? '' : `, about ${moved.toFixed(2)} of a step from where it is saved`;
  }

  function motionOf(record: AuthoredObjectRecord): PlacedObjectRow['motion'] {
    if (record.behaviour === null) return 'none';
    const runtime = state.atlas?.binding.objects;
    const held = runtime?.motionStateOf(record.objectId) ?? null;
    if (held === null || held === 'none') return 'unsupported';
    return held as PlacedObjectRow['motion'];
  }

  function refresh(): void {
    panel.showAssets(
      assets.map((asset) => ({
        assetId: asset.assetId,
        label: asset.label,
        available: asset.reference !== null || env.preview,
        supportsMotion: asset.supportedBehaviours.includes(BOUNDED_MOTION_ID),
      })),
      OBJECT_ORIGINS.map((key) => ({ key, label: OBJECT_ORIGIN_LABELS[key] })),
    );
    panel.showObjects(
      everyRecord().map((record) => ({
        objectId: record.objectId,
        label: labelOf(record),
        regionLabel: regionLabel(record.regionId as IslandId),
        motion: motionOf(record),
        note: notices.get(record.objectId) ?? null,
      })),
      selectedId,
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
    // Tier 2 for a removal: it states its own blast radius as nothing, and it earns the second
    // control because it is the one operation here that cannot be undone.
    const tier = next.kind === 'remove' ? 2 : 1;
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
      ArrowUp: { z: -NUDGE_STEP },
      ArrowDown: { z: NUDGE_STEP },
      ArrowLeft: { x: -NUDGE_STEP },
      ArrowRight: { x: NUDGE_STEP },
      PageUp: { y: NUDGE_STEP },
      PageDown: { y: -NUDGE_STEP },
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
 * Built here rather than read from `graph-client/test/fixtures/world-objects.json`, which is the
 * fixture the CLIENT's tests read: that file describes wire responses and carries no bytes, and a
 * preview needs something to draw. This is a box, it is obviously a box, and the surface says
 * every time that nothing placed in the preview was saved.
 */
const PREVIEW_ASSETS: readonly ReviewedObjectAsset[] = Object.freeze([
  Object.freeze({
    assetId: 'preview-marker',
    label: 'Preview marker',
    container: AUTHORED_OBJECT_CONTAINER,
    reference: null,
    origin: 'fictional-source' as const,
    footprint: Object.freeze({ radius: 0.25, height: 0.5 }),
    supportedBehaviours: Object.freeze([BOUNDED_MOTION_ID]),
  }),
]);

const PREVIEW_VERSION: AuthoredWorldVersion = Object.freeze({
  worldVersionId: CURRENT_WORLD_VERSION,
  basedOnWorldVersionId: null,
  recordedSha256: '0'.repeat(64),
  objects: Object.freeze([]),
});

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

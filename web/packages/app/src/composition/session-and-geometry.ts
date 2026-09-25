/**
 * Opening a session, and reading the geometry the world is about to draw.
 *
 * Two jobs in one module because they are one sequence: a session is what a geometry read is
 * authorized by, and the snapshot the session opened with is what resolves a reconstruction to a
 * region. Nothing here builds a surface. It fills in `SessionState` and hands the composition
 * root a world to mount.
 */

import { localVec3, type IslandId, type SceneDisplayFrame } from '@exulanica/atlas-core';
import type {
  GraphSnapshot,
  ReconstructionSceneRecord,
  RenderingSubstrate,
} from '@exulanica/graph-client';
import { ApiError } from '@exulanica/graph-client';
import type { PlacedScenePointMap, PointMap } from '@exulanica/atlas-react/playcanvas';
import {
  footprintRadiusOf,
  scenePointMapFootprint,
  scenePointMapForward,
  scenePointMapViewpoint,
  trainedSceneFootprint,
} from '@exulanica/atlas-react/playcanvas';
import { worldArtProfile } from '@exulanica/presentation';

import { credentials, previewCredentials } from '../config.js';
import { EvidenceCache } from '../evidence.js';
import {
  GeometryClient,
  displayFrameSentence,
  regionsByCapture,
  standpointArrangementSentence,
  unposedArrangementSentence,
  type GeometryIssue,
  type GeometryIssueState,
  type PlacedEstimateReference,
} from '../geometry-api.js';
import {
  WorldObjectsClient,
  drawablePointMaps,
  type AlternateVersion,
  type PointMapInstance,
} from '../world-objects-api.js';
import {
  InteractionPolicyClient,
  preferencesFromInteractionPolicy,
} from '../interaction-policy.js';
import { writePreferences } from '../preferences.js';
import type { ReconstructedGeometry } from '../scene.js';
import { openSession } from '../session.js';
import { SourceMediaClient } from '../source-media-api.js';
import { el } from '../ui/dom.js';
import type { ReconstructionRungDisclosure } from '../ui/status.js';
import { WorldStyleClient } from '../world-style-api.js';
import {
  WorldEntryClient,
  automaticWorldEntry,
  type SavedWorldEntry,
} from '../world-entry-api.js';
import { describeWorldStyleFailure, preferencesForWorldVersion } from './appearance.js';
import type { AppEnvironment, SessionState } from './session-state.js';
import type { Credentials } from '../config.js';

export class StarterWorldOpeningError extends Error {
  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : 'The starter world request failed.');
    this.name = 'StarterWorldOpeningError';
  }
}

/**
 * Open the session and everything it authorizes, up to but not including a mount.
 *
 * The preview exception is first and is the only place a fixture may enter: it loads a
 * reconstruction from disk into the same field production fills from the API, so nothing
 * downstream branches on which side it came from.
 */
export async function openAppSession(
  env: AppEnvironment,
  state: SessionState,
  token: string,
  csrfToken?: string,
): Promise<void> {
  if (env.preview) {
    state.previewSourceMedia = (await import('../dev/preview-media.js')).PREVIEW_SOURCE_MEDIA;
    state.pointMaps = await (await import('../dev/preview-point-maps.js')).previewPointMaps();
  }
  state.credentials = env.preview
    ? previewCredentials(window.location.origin)
    : credentials(token, csrfToken);
  // The graph puts every photograph the open world holds in that world's region. The regions come
  // with the world's source media, which is read when a world opens, after this first read.
  const opened = await openSession({
    ...state.credentials, worldRegions: () => state.sourceMediaSession?.worldRegions,
  });
  state.session = opened.session;
  state.snapshot = opened.initial;
  state.evidence = new EvidenceCache(opened.session.client);
  state.companionEngine = opened.companion;
  if (env.preview) return;

  state.worldEntries = new WorldEntryClient(state.credentials);
  state.savedWorldEntries = await state.worldEntries.entries();
  if (state.savedWorldEntries.length === 0) {
    try {
      const starter = await state.worldEntries.ensureStarter('My world');
      state.savedWorldEntries = Object.freeze([starter]);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) {
        throw new StarterWorldOpeningError(error);
      }
      // A concurrent tab may have created a non-starter entry after the empty read. Re-read and
      // let the ordinary saved-world chooser present that state instead of creating over it.
      state.savedWorldEntries = await state.worldEntries.entries();
    }
  }
  state.activeWorldEntry = automaticWorldEntry(state.savedWorldEntries);
  if (state.activeWorldEntry !== null) {
    try {
      await openWorldEntryContext(state, state.activeWorldEntry);
    } catch (error) {
      // KEEP WHY, AND KEEP THE ERROR. A lone available world is opened here, so this failure is
      // the only reason a person with exactly one world sees anything but their world. Discarding
      // it put them in front of a list of one with nothing said. The error is retained rather
      // than a sentence made from it, because what a person should be told is a decision for the
      // surface that has to fit it on a screen, not for the code that caught it.
      state.activeWorldEntry = null;
      state.worldEntryError = error;
    }
  }

}

/**
 * Read the interaction settings the open world holds, and keep a client for writing them.
 *
 * Interaction policy belongs to a world, like its appearance, so it is read when a world opens
 * rather than once at start-up: a world chosen later from the list gets its own settings, and no
 * request is made for a world nobody opened. A failure keeps the device's own copy and says so.
 */
async function connectInteractionPolicy(
  state: SessionState,
  credentials: Credentials,
  worldId: string,
): Promise<string[]> {
  state.interactionPolicies = new InteractionPolicyClient({ ...credentials, worldId });
  try {
    const interactionState = await new InteractionPolicyClient({
      ...credentials, worldId, signal: AbortSignal.timeout(15_000),
    }).current();
    if (interactionState.current !== null) {
      state.preferences = preferencesFromInteractionPolicy(
        state.preferences, interactionState.parameters,
      );
      try {
        writePreferences(window.localStorage, state.preferences);
      } catch {
        // The durable server copy is authoritative; private browsing may reject its local cache.
      }
    }
    return [];
  } catch (error) {
    state.interactionPolicies = null;
    return [`Saved interaction settings unavailable: ${error instanceof Error ? error.message : 'the request failed'}`];
  }
}

/** Connect the exact world and appearance versions named by a chosen durable entry. */
export async function openWorldEntryContext(
  state: SessionState,
  entry: SavedWorldEntry,
): Promise<void> {
  if (state.credentials === null) throw new Error('The authenticated session is not open.');
  if (entry.availability !== 'available') {
    throw new Error(entry.unavailableReason === 'source_deleted'
      ? 'This saved world is unavailable because its source material was deleted.'
      : entry.unavailableReason === 'authored_version_changed'
        ? 'This saved world changed elsewhere and must be reconciled before it can open.'
        : 'This saved world is unavailable. Review its source material before opening it.');
  }
  state.activeWorldEntry = entry;

  state.worldStyles = new WorldStyleClient({
    ...state.credentials,
    worldId: entry.worldId,
    savedEntry: () => {
      const active = state.activeWorldEntry;
      if (active === null) throw new Error('The saved world entry is no longer active.');
      return {
        entryId: active.entryId,
        revision: active.revision,
        authoredStateSha256: active.authoredStateSha256,
        authoredEditSeq: active.authoredEditSeq,
        styleVersionId: active.styleVersionId,
      };
    },
    onSavedEntryAdvanced: (version, base) => {
      const active = state.activeWorldEntry;
      if (active === null || active.entryId !== base.entryId || active.revision !== base.revision) {
        state.sourceMediaNotices = Object.freeze([
          'The appearance and resume point were saved, but this page must reload before another change.',
          ...state.sourceMediaNotices,
        ]);
        return;
      }
      const updated = Object.freeze({
        ...active,
        styleVersionId: version.versionId,
        revision: active.revision + 1,
        updatedAt: new Date().toISOString(),
      });
      state.activeWorldEntry = updated;
      state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((candidate) =>
        candidate.entryId === updated.entryId ? updated : candidate));
    },
  });
  try {
    state.worldStyleConnection = await state.worldStyles.connect(entry.styleVersionId);
    state.preferences = preferencesForWorldVersion(
      state.preferences,
      state.worldStyleConnection.state.current,
    );
    state.worldStyleFailure = null;
  } catch (error) {
    state.worldStyleFailure = describeWorldStyleFailure(error);
    state.worldStyleConnection = null;
    state.worldStyles = null;
    state.activeWorldEntry = null;
    // `cause` so a caller can still see what actually failed. Without it the only thing left is
    // this sentence, and a full-page screen cannot tell a dropped connection from a refusal.
    throw new Error(
      `The saved appearance version could not be opened: ${state.worldStyleFailure}`,
      { cause: error },
    );
  }
  const regionsBefore = state.sourceMediaSession?.worldRegions;
  state.sourceMediaSession?.dispose();
  state.sourceMediaSession = null;
  const settingsNotices = await connectInteractionPolicy(state, state.credentials, entry.worldId);
  await connectEntrySourceMedia(state, state.credentials, entry, settingsNotices);
  await readGraphForWorldRegions(state, regionsBefore);
}

/**
 * Read the graph again when the opened world holds its photographs in other regions.
 *
 * The session's client asks for the open world's regions at each graph read, and the regions
 * arrive with the world's source media, after the graph the page holds was read. Without this
 * read, an object placed in a region of the world names a region nothing draws until the next
 * write happens to read the graph. Opening an authored world, or the same world again, reads
 * nothing more.
 */
async function readGraphForWorldRegions(
  state: SessionState,
  before: ReadonlyMap<string, string> | undefined,
): Promise<void> {
  const after = state.sourceMediaSession?.worldRegions;
  if (state.session === null || sameRegions(before, after)) return;
  state.snapshot = await state.session.snapshot();
}

function sameRegions(
  left: ReadonlyMap<string, string> | undefined,
  right: ReadonlyMap<string, string> | undefined,
): boolean {
  const a = left ?? new Map<string, string>();
  const b = right ?? new Map<string, string>();
  return a.size === b.size && [...a].every(([captureId, regionId]) => b.get(captureId) === regionId);
}

/** The chosen world's source media and the notices opening it leaves, or none for an authored world. */
async function connectEntrySourceMedia(
  state: SessionState,
  credentials: Credentials,
  entry: SavedWorldEntry,
  settingsNotices: readonly string[],
): Promise<void> {
  if (entry.sourceKind === 'authored') {
    state.previewSourceMedia = new Map();
    state.sourceMediaNotices = Object.freeze(settingsNotices);
    return;
  }
  try {
    const profile = worldArtProfile(
      state.preferences.worldArtProfile,
      state.preferences.worldArtProfileVersion,
      state.preferences.worldStyleParameters,
    );
    state.sourceMediaSession = await new SourceMediaClient({
      ...credentials,
      worldId: entry.worldId,
      sourceSnapshotId: entry.sourceSnapshotId,
    }).load(
      profile.palette.stoneShadow,
    );
    state.previewSourceMedia = state.sourceMediaSession.catalog;
    state.sourceMediaNotices = Object.freeze([
      ...settingsNotices,
      'Your saved changes and appearance reopen exactly. The surrounding memory layout reflects '
        + 'the latest source material you are allowed to view.',
      ...state.sourceMediaSession.issues.map((issue) => {
      const issueState = issue.state === 'missing_evidence'
        ? 'Missing source evidence'
        : issue.state === 'unavailable_asset'
          ? 'Source asset unavailable'
          : issue.state === 'unauthorized'
            ? 'Source not authorized'
            : 'Source loading error';
      return `${issueState}: ${issue.reason}`;
      }),
    ]);
  } catch (error) {
    state.previewSourceMedia = new Map();
    state.sourceMediaNotices = Object.freeze([
      ...settingsNotices,
      `Source media unavailable: ${error instanceof Error ? error.message : 'the request failed'}`,
    ]);
  }
}

/**
 * The geometry re-read that opens every mount, with the notice it shows while it runs.
 *
 * The preview fills the same slot from disk and must not be overwritten by a route it does not
 * serve, so production is the only side that reads. The returned dispose is a no-op: the loading
 * notice is removed in a `finally` before this resolves, so there is nothing left to stop.
 */
export async function mountSessionGeometry(deps: {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly credentials: Credentials;
  readonly snapshot: GraphSnapshot;
}): Promise<{ dispose: () => void }> {
  const { env, state } = deps;
  if (!env.preview) {
    const loading = el('p', {
      class: 'reconstruction-loading', role: 'status',
      text: 'Loading and verifying reconstruction… Source photographs remain available if geometry cannot load.',
    });
    env.shell.setAttribute('aria-busy', 'true');
    env.shell.append(loading);
    try {
      await loadGeometry(env, state, deps.credentials, deps.snapshot);
      // After the region geometry and before the mount: what a person placed in their own world
      // is read from that world's version, not from the workspace's list of every estimate.
      await loadAuthoredPointMaps(state, deps.credentials);
    }
    finally { loading.remove(); env.shell.removeAttribute('aria-busy'); }
  }
  return { dispose: () => undefined };
}

/**
 * The production reconstruction load. ADR-0009 D10, from the client's side.
 *
 * **Regions are resolved from the snapshot the world is drawn from**, not from a second read.
 * The server ships capture ids and no island id, because ADR-0005 leaves what an island is to
 * the client; `regionsByCapture` puts them through the islands this snapshot already resolved,
 * so a shell lands in the region its own anchors did.
 *
 * **It runs on every mount, and that is what makes a deletion reach the renderer.** Called once
 * at start-up it would not: `mount()` re-reads the same decoded maps after every committed
 * write, so a photograph deleted in this session would keep its reconstruction on screen at full
 * fidelity for the life of the tab, and the 410 the delivery route so carefully produces would be
 * observable only during boot. The list is re-read each time and the bytes are not: a map already
 * decoded is handed back through `byArtifact`, so the recurring cost is a few hundred bytes of
 * JSON and the recurring benefit is that a region whose descriptor has gone loses its geometry.
 *
 * **A failure here is never a failure of the world.** A region with no geometry is rung 4, which
 * is a real rung with a real experience, and the whole thesis is that reconstruction quality
 * never participates in the truth guarantee. So every failure becomes a notice on the status bar
 * and the Atlas mounts either way, exactly as the development preview already behaves when a
 * fixture is missing. What previously could still take the world down was a request that never
 * settled; every one of them now carries a deadline.
 */
/**
 * The depth estimates the account holder placed in the world they have open, ready to draw, and
 * the region of every placement in that version, which decides where the world opens.
 *
 * Read from the authored version rather than from the ``/geometry`` list. The list is every
 * estimate this workspace holds; what a world draws is what somebody PUT in it, which is the
 * placement rows, and each of those pins the exact bytes it was made against.
 *
 * Returns an empty list rather than throwing on anything: a world whose estimates cannot be
 * loaded is a world that opens without them, not a world that fails to open. Every reason lands
 * in ``state.geometryIssues`` beside the rest.
 */
export async function loadAuthoredPointMaps(
  state: SessionState,
  where: { baseUrl: string; token: string },
): Promise<void> {
  const entry = state.activeWorldEntry;
  // A version that cannot be read names no placement, and the world opens in its first region.
  state.placementRegionIds = undefined;
  if (entry?.authoredVersionId === undefined || entry.authoredVersionId === null) {
    state.authoredPointMaps = undefined;
    return;
  }
  try {
    const version = await new WorldObjectsClient({
      ...where, worldId: entry.worldId,
    }).readVersion(entry.authoredVersionId);
    state.placementRegionIds = placementRegionIds(version);
    const drawable = drawablePointMaps(version);
    if (drawable.length === 0) {
      state.authoredPointMaps = Object.freeze([]);
      return;
    }
    const session = await new GeometryClient(where).loadPlacedEstimates(
      drawable.map((instance) => placedEstimateReference(instance)),
    );
    state.authoredPointMaps = Object.freeze(
      drawable.flatMap((instance) => {
        const map = session.maps.get(instance.instanceId);
        // Absent means the bytes failed their check or did not arrive. Nothing is drawn for it.
        return map === undefined
          ? []
          : [{
              instanceId: instance.instanceId,
              map,
              transform: {
                xMm: instance.transform.xMm,
                yMm: instance.transform.yMm,
                zMm: instance.transform.zMm,
                yawMicroradians: instance.transform.yawMicroradians,
                scaleMilli: instance.transform.scaleMilli,
              },
            }];
      }),
    );
    if (session.issues.length > 0) {
      state.geometryIssues = Object.freeze([...state.geometryIssues ?? [], ...session.issues]);
    }
  } catch {
    // A world opens without its estimates rather than not at all.
    state.authoredPointMaps = Object.freeze([]);
  }
}

/**
 * The region of every placement the person made in a version and has not removed: objects,
 * environment pieces and depth estimates. Every placement is the person's own (the server admits
 * only authored origins), and photographs are not placements.
 */
export function placementRegionIds(version: AlternateVersion): readonly string[] {
  return Object.freeze([
    ...version.objects,
    ...version.environmentInstances ?? [],
    ...version.pointMapInstances ?? [],
  ].filter((placement) => !placement.removed).map((placement) => placement.regionId));
}

/** What the client needs to fetch and check one placed estimate, read from the placement itself. */
function placedEstimateReference(instance: PointMapInstance): PlacedEstimateReference {
  const source = instance.source as Record<string, Record<string, unknown> | string>;
  const artifact = (source['artifact'] ?? {}) as Record<string, unknown>;
  return {
    instanceId: instance.instanceId,
    captureId: String(source['capture_id'] ?? ''),
    artifactId: String(artifact['artifact_id'] ?? ''),
    contentSha256: String(artifact['content_sha256'] ?? ''),
    byteSize: Number(artifact['byte_size'] ?? 0),
    container: String(artifact['container'] ?? ''),
  };
}

export async function loadGeometry(
  env: AppEnvironment,
  state: SessionState,
  where: { baseUrl: string; token: string },
  from: GraphSnapshot,
): Promise<void> {
  env.browserMeasurement?.beginGeometryLoad();
  try {
    const client = new GeometryClient(where, (measurement) => {
      env.browserMeasurement?.recordGeometry(measurement);
    });
    const regions = regionsByCapture(from.islands);
    const scenes = from.reconstructionScenes ?? [];
    // Regions already chose one scene each; the loader draws those and reports the rest.
    const displayed = new Set(from.islands.flatMap((island) =>
      island.reconstructionSceneId == null ? [] : [island.reconstructionSceneId]));
    const sceneGeometry = await client.loadScenes(scenes, regions, state.heldPointMaps, displayed);
    state.notDrawnScenes = new Set(sceneGeometry.issues
      .filter((issue) => issue.state === 'not_displayed' && issue.sceneId !== undefined)
      .map((issue) => issue.sceneId!));
    const sceneCaptures = new Set(
      scenes.flatMap((scene) => scene.members.map((member) => member.captureId)),
    );
    const held = new Map([...(state.heldPointMaps ?? []), ...sceneGeometry.byArtifact]);
    const legacyGeometry = await client.load(regions, held, sceneCaptures);
    state.pointMaps = new Map([...legacyGeometry.pointMaps, ...sceneGeometry.pointMaps]);
    state.placedPointMaps = sceneGeometry.placedPointMaps;
    state.trainedGeometry = sceneGeometry.trainedGeometry;
    state.recoveredCameras = sceneGeometry.recoveredCameras;
    state.heldPointMaps = new Map([...legacyGeometry.byArtifact, ...sceneGeometry.byArtifact]);
    state.geometryNotices = geometryNoticesFor([
      ...sceneGeometry.issues,
      ...legacyGeometry.issues,
    ]);
    state.geometryIssues = Object.freeze([
      ...sceneGeometry.issues,
      ...legacyGeometry.issues,
    ]);
    env.browserMeasurement?.endGeometryLoad(state.geometryIssues);
    state.displayFrames = sceneGeometry.displayFrames;
    state.reconstructionRungs = reconstructionRungsFor(
      scenes, sceneGeometry.renderingByScene, state.notDrawnScenes, state.displayFrames,
    );
  } catch (error) {
    state.pointMaps = undefined;
    state.placedPointMaps = undefined;
    state.trainedGeometry = Object.freeze([]);
    state.recoveredCameras = Object.freeze([]);
    state.heldPointMaps = undefined;
    state.geometryNotices = Object.freeze([
      `Reconstructions unavailable: ${error instanceof Error ? error.message : 'the request failed'}`,
    ]);
    state.geometryIssues = Object.freeze([]);
    env.browserMeasurement?.endGeometryLoad(state.geometryIssues);
    state.reconstructionRungs = reconstructionRungsFor(
      from.reconstructionScenes ?? [],
      new Map(),
    );
  }
}

export function reconstructionRungsFor(
  scenes: readonly ReconstructionSceneRecord[],
  actual: ReadonlyMap<string, RenderingSubstrate>,
  notDrawn: ReadonlySet<string> = new Set(),
  displayFrames: ReadonlyMap<string, SceneDisplayFrame> = new Map(),
): readonly ReconstructionRungDisclosure[] {
  return Object.freeze(scenes.map((scene) => {
    const substrate = actual.get(scene.sceneId) ?? 'source_photographs';
    // Unposed depth is rung 3 whatever the pose recorded: the specification's rung 3 needs no pose.
    const displayedRung = substrate === 'source_photographs' ? 4
      : substrate === 'unposed_point_maps' ? 3 : Math.max(scene.recordedRung ?? 3, 3);
    const reasons = [...scene.displayReasons];
    // Drawn from the server's standpoint record only when it joined these photographs; the geometry
    // loader places them from it exactly then, so the two cannot disagree about which was drawn.
    const measuredArrangement = substrate === 'unposed_point_maps' && scene.standpoint?.state === 'joined';
    const frame = displayFrames.get(scene.sceneId);
    if (frame !== undefined && substrate !== 'source_photographs') {
      // The presentation frame is a layout decision and is said out loud beside the rung.
      reasons.push(
        substrate !== 'unposed_point_maps' ? displayFrameSentence(frame)
          : measuredArrangement ? standpointArrangementSentence(frame) : unposedArrangementSentence(frame),
      );
    }
    if (notDrawn.has(scene.sceneId)) {
      reasons.push('Not drawn: its region displays a more complete reconstruction of the same photographs.');
    } else if (substrate !== scene.renderingSubstrate) {
      reasons.push(
        substrate === 'source_photographs'
          ? 'This browser has no loaded reconstruction; the original source photographs remain available.'
          : 'This browser is showing verified reconstruction geometry; its recorded quality gate is unchanged.',
      );
    }
    return Object.freeze({
      sceneId: scene.sceneId,
      recordedRung: scene.recordedRung,
      displayedRung: displayedRung as 1 | 2 | 3 | 4,
      registeredMemberCount: scene.registeredMemberCount,
      memberCount: scene.memberCount,
      renderingSubstrate: substrate,
      measuredArrangement,
      reasons: Object.freeze(reasons),
      // What the proof lens reads. `drawn` is already decided above, and passing it rather than
      // letting the panel infer it from the substrate is the point: a scene can have trained
      // geometry and still be showing the visitor nothing, because its region draws another one.
      drawn: !notDrawn.has(scene.sceneId),
      // FALSE UNTIL SOMETHING DRAWS A GENERATION, and this is not a placeholder.
      //
      // The first version set this whenever a verified generation existed for the scene, which
      // made the panel tell a visitor "A model produced this. No camera observed it" about a
      // region drawing recorded point maps. Nothing in this renderer draws generated geometry at
      // all, so the honest answer to "is a model surface on screen" is no. Filing a generation
      // must not change what the world says it is showing.
      //
      // When a loader draws one, this becomes a fact about that region's drawn content, not about
      // the existence of a row.
      showingGenerated: false,
      ...(scene.trainedGeometry?.quality === undefined ? {} : { trainingQuality: scene.trainedGeometry.quality }),
    });
  }));
}

/**
 * One line per kind of failure, with a count, rather than one line per photograph.
 *
 * `unplaced` is the ordinary state of a photograph in a multi-photograph region rather than an
 * anomaly, so a corpus of eighty photographs across five regions produces seventy-five identical
 * sentences. Rendered one per line they become the page. Counting them keeps the disclosure and
 * loses none of it: the count is the honest number and the first reason says what the kind means.
 */
export function geometryNoticesFor(issues: readonly GeometryIssue[]): readonly string[] {
  const byState = new Map<GeometryIssueState, GeometryIssue[]>();
  for (const issue of issues) {
    const held = byState.get(issue.state);
    if (held === undefined) byState.set(issue.state, [issue]);
    else held.push(issue);
  }
  return Object.freeze(
    [...byState].map(([issueState, group]) => {
      const label = GEOMETRY_NOTICE[issueState];
      const first = group[0]!.reason;
      return group.length === 1
        ? `${label}: ${first}`
        : `${label}: ${group.length} reconstructions. ${first}`;
    }),
  );
}

/** What each geometry failure is called on screen. One phrase per state, and no state hidden. */
const GEOMETRY_NOTICE: Record<GeometryIssueState, string> = {
  bytes_missing: 'Reconstruction bytes unavailable',
  unavailable: 'Reconstruction withheld by current policy',
  unsupported_container: 'Reconstruction container unsupported',
  verification_failed: 'Reconstruction failed its digest check',
  unverifiable: 'Reconstruction could not be verified',
  undecodable: 'Reconstruction could not be read',
  unplaced: 'Reconstruction not placed',
  no_region: 'Reconstruction has no region',
  not_displayed: 'Reconstruction not drawn',
  unauthorized: 'Reconstruction not authorized',
  timed_out: 'Reconstruction timed out',
  photograph_unavailable: 'Photograph not used for detail',
  error: 'Reconstruction loading error',
};

/**
 * What each decoded point map says about its region, for the scene graph.
 *
 * The rung and the viewpoint are read off the container rather than assumed: `rung` is fixed at
 * 3 by the format, and `viewpoint.position` is the camera the reconstruction was recovered from.
 * Reading them here keeps `scene.ts` free of the container format while still letting the scene
 * graph describe a region by the geometry it is actually holding.
 */
export function reconstructionsOf(
  state: SessionState,
  maps: ReadonlyMap<IslandId, PointMap> | undefined,
  placedMaps: readonly PlacedScenePointMap[] | undefined,
): ReadonlyMap<IslandId, ReconstructedGeometry> {
  const out = new Map<IslandId, ReconstructedGeometry>();
  const placedByIsland = new Map<IslandId, PlacedScenePointMap[]>();
  for (const placed of placedMaps ?? []) {
    const held = placedByIsland.get(placed.islandId);
    if (held === undefined) placedByIsland.set(placed.islandId, [placed]);
    else held.push(placed);
  }
  for (const [islandId, values] of placedByIsland) {
    const viewpoint = scenePointMapViewpoint(values[0]!);
    const forward = scenePointMapForward(values[0]!);
    out.set(islandId, {
      rung: 3,
      viewpointLocal: localVec3(viewpoint[0], viewpoint[1], viewpoint[2]),
      viewpointForwardLocal: localVec3(forward[0], forward[1], forward[2]),
      footprintRadiusLocal: Math.max(scenePointMapFootprint(values), ...state.trainedGeometry
        .filter((geometry) => geometry.islandId === islandId).map(trainedSceneFootprint)),
    });
  }
  for (const trained of state.trainedGeometry) {
    if (out.has(trained.islandId)) continue;
    const camera = state.recoveredCameras.find((candidate) => candidate.sceneId === trained.sceneId && candidate.islandId === trained.islandId);
    if (camera === undefined) continue;
    const m = camera.sceneFromCameraRowMajor;
    // COLMAP cameras look along their local +Z axis, the third column of the rotation.
    out.set(trained.islandId, { rung: 3, viewpointLocal: localVec3(m[3]!, m[7]!, m[11]!),
      viewpointForwardLocal: localVec3(m[2]!, m[6]!, m[10]!),
      footprintRadiusLocal: trainedSceneFootprint(trained) });
  }
  for (const [islandId, map] of maps ?? []) {
    if (out.has(islandId)) continue;
    const [x, y, z] = map.header.viewpoint.position;
    out.set(islandId, {
      rung: map.header.rung,
      viewpointLocal: localVec3(x, y, z),
      // The renderer's own function, so the region's stated size and the radius its cloud
      // dissolves at cannot drift apart.
      footprintRadiusLocal: footprintRadiusOf(map.header),
    });
  }
  return out;
}

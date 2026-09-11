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
  unposedArrangementSentence,
  type GeometryIssue,
  type GeometryIssueState,
} from '../geometry-api.js';
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
import { describeWorldStyleFailure, preferencesForWorldVersion } from './appearance.js';
import type { AppEnvironment, SessionState } from './session-state.js';

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
): Promise<void> {
  if (env.preview) {
    state.previewSourceMedia = (await import('../dev/preview-media.js')).PREVIEW_SOURCE_MEDIA;
    state.pointMaps = await (await import('../dev/preview-point-maps.js')).previewPointMaps();
  }
  state.credentials = env.preview
    ? previewCredentials(window.location.origin)
    : credentials(token);
  const opened = await openSession(state.credentials);
  state.session = opened.session;
  state.snapshot = opened.initial;
  state.evidence = new EvidenceCache(opened.session.client);
  state.companionEngine = opened.companion;
  if (env.preview) return;

  state.worldStyles = new WorldStyleClient(state.credentials);
  try {
    state.worldStyleConnection = await state.worldStyles.connect();
    state.preferences = preferencesForWorldVersion(
      state.preferences,
      state.worldStyleConnection.state.current,
    );
    state.worldStyleFailure = null;
  } catch (error) {
    state.worldStyleFailure = describeWorldStyleFailure(error);
    state.worldStyleConnection = null;
    state.worldStyles = null;
  }
  state.interactionPolicies = new InteractionPolicyClient(state.credentials);
  const startupNotices: string[] = [];
  try {
    const interactionState = await new InteractionPolicyClient({
      ...state.credentials, signal: AbortSignal.timeout(15_000),
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
  } catch (error) {
    state.interactionPolicies = null;
    startupNotices.push(`Saved interaction settings unavailable: ${error instanceof Error ? error.message : 'the request failed'}`);
  }
  state.sourceMediaSession?.dispose();
  state.sourceMediaSession = null;
  try {
    const profile = worldArtProfile(
      state.preferences.worldArtProfile,
      state.preferences.worldArtProfileVersion,
      state.preferences.worldStyleParameters,
    );
    state.sourceMediaSession = await new SourceMediaClient(state.credentials).load(
      profile.palette.stoneShadow,
    );
    state.previewSourceMedia = state.sourceMediaSession.catalog;
    state.sourceMediaNotices = Object.freeze([...startupNotices, ...state.sourceMediaSession.issues.map((issue) => {
      const issueState = issue.state === 'missing_evidence'
        ? 'Missing source evidence'
        : issue.state === 'unavailable_asset'
          ? 'Source asset unavailable'
          : issue.state === 'unauthorized'
            ? 'Source not authorized'
            : 'Source loading error';
      return `${issueState}: ${issue.reason}`;
    })]);
  } catch (error) {
    state.previewSourceMedia = new Map();
    state.sourceMediaNotices = Object.freeze([
      ...startupNotices,
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
  readonly credentials: { baseUrl: string; token: string };
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
    try { await loadGeometry(env, state, deps.credentials, deps.snapshot); }
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
    const frame = displayFrames.get(scene.sceneId);
    if (frame !== undefined && substrate !== 'source_photographs') {
      // The presentation frame is a layout decision and is said out loud beside the rung.
      reasons.push(
        substrate === 'unposed_point_maps' ? unposedArrangementSentence(frame) : displayFrameSentence(frame),
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
  unsupported_container: 'Reconstruction container unsupported',
  verification_failed: 'Reconstruction failed its digest check',
  unverifiable: 'Reconstruction could not be verified',
  undecodable: 'Reconstruction could not be read',
  unplaced: 'Reconstruction not placed',
  no_region: 'Reconstruction has no region',
  not_displayed: 'Reconstruction not drawn',
  unauthorized: 'Reconstruction not authorized',
  timed_out: 'Reconstruction timed out',
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

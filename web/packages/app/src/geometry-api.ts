/**
 * Authenticated, digest-verified reconstruction geometry for the renderer.
 *
 * This is the production half of ADR-0009 D10. Until it existed, "no route serves artifact bytes,
 * and the only loader in the workspace is a development preview, while the app's own comment
 * claiming that production reads point maps from an API describes an implementation that does not
 * exist". The comment in `atlas.ts` is now true, and this file is what makes it true.
 *
 * The record names three requirements and each one is a line of code here.
 *
 * **Bytes in hand.** Not a URL handed to the renderer, and not a blob URL either. A point map is
 * decoded from an `ArrayBuffer` this module fetched and checked; nothing downstream is given a
 * string it could load something else from.
 *
 * **A bearer in the header.** Through the same `Transport` every other authenticated read uses,
 * which holds the token in a private field and puts it in an `authorization` header. There is no
 * variant of this that works with a plain URL: the token would have to go in a query string,
 * where it lands in a proxy log holding the keys to somebody's photograph library.
 *
 * **The content hash verified against the descriptor that named it.** The list route says what
 * each artifact's SHA-256 is; the byte route returns the bytes. The digest is computed here and
 * compared **against the descriptor**, never against the response's own `ETag`, which would be
 * checking the response against itself. A mismatch means the region gets no geometry and the
 * failure is reported: bytes that failed their check never reach `decodeOpm`.
 *
 * **Without `crypto.subtle` there is no geometry at all.** A page served over a non-secure
 * context has no `SubtleCrypto`, so the third requirement cannot be met, so the loader refuses
 * every region and says why once. Decoding unverified bytes because the environment made checking
 * inconvenient would be the exact trade this design exists to refuse.
 *
 * **A validated scene loads every placed member.** The graph record binds each point map to the
 * pose and placement receipt that puts it in a shared frame, so those maps may be drawn together.
 * The older descriptor-list method remains for single-photograph regions with no scene record and
 * still attempts one unposed map per region.
 */

import type { IslandId, SceneDisplayFrame } from '@exulanica/atlas-core';
import {
  colmapCameraSample, composeDisplayFrame, displayCameraTransform, opmCameraSample, sceneDisplayFrame,
  transformedBoxCorners, unmeasuredFan,
} from '@exulanica/atlas-core';
import type { PlacedScenePointMap, PointMap, TrainedSceneGeometry, RecoveredSceneCamera } from '@exulanica/atlas-react/playcanvas';
import { decodeOpm, validateScenePointMapPlacement, validateSogBundle, validateTrainedSceneGeometry, validateRecoveredSceneCamera } from '@exulanica/atlas-react/playcanvas';
import {
  ApiError,
  Transport,
  type ReconstructionSceneRecord,
  type RenderingSubstrate,
  type TransportOptions,
  type UnposedPointMapRecord,
} from '@exulanica/graph-client';

export type GeometryIssueState =
  | 'bytes_missing'
  | 'unsupported_container'
  | 'verification_failed'
  | 'unverifiable'
  | 'undecodable'
  | 'unplaced'
  | 'no_region'
  | 'not_displayed'
  | 'unauthorized'
  | 'timed_out'
  | 'photograph_unavailable'
  | 'error';

export interface GeometryIssue {
  readonly captureId: string;
  readonly islandId: string | null;
  readonly sceneId?: string;
  readonly state: GeometryIssueState;
  readonly reason: string;
}

export interface GeometrySession {
  /** One decoded, verified point map per region. Regions absent from it are drawn as anchors. */
  readonly pointMaps: ReadonlyMap<IslandId, PointMap>;
  /** Every successfully verified map with its receipt-validated scene placement. */
  readonly placedPointMaps: readonly PlacedScenePointMap[];
  /**
   * The same maps by artifact id, to be handed back to the next `load`.
   *
   * Keyed by artifact rather than by region because an artifact id names one content hash for
   * ever, while which region a capture belongs to is a client decision that a regrouping can
   * change. A map carried forward under a region key could end up drawn in a region it was never
   * verified for.
   */
  readonly byArtifact: ReadonlyMap<string, PointMap>;
  readonly issues: readonly GeometryIssue[];
  /** What this browser can draw now, after transport, digest and decode checks. */
  readonly renderingByScene: ReadonlyMap<string, RenderingSubstrate>;
  /** Verified SOG bytes; GPU decode availability is settled separately by the renderer. */
  readonly trainedGeometry: readonly TrainedSceneGeometry[];
  readonly recoveredCameras: readonly RecoveredSceneCamera[];
  /**
   * The presentation similarity applied to each drawn scene's maps, trained asset and cameras.
   *
   * Derived from the recovered cameras alone so the scene stands upright, centred and at walking
   * scale in its region. It is a layout decision like the region's placement: no receipt changes,
   * no physical claim follows, and the status line discloses it.
   */
  readonly displayFrames: ReadonlyMap<string, SceneDisplayFrame>;
}

/** One successfully placed geometry input, measured at the authenticated byte boundary. */
export interface GeometryLoadMeasurement {
  readonly sceneId: string;
  readonly captureId: string;
  readonly artifactId: string;
  readonly expectedBytes: number;
  readonly receivedBytes: number;
  readonly fetchMs: number;
  readonly verifyMs: number;
  readonly decodeMs: number;
  readonly reused: boolean;
}

export type GeometryLoadObserver = (measurement: GeometryLoadMeasurement) => void;

/** What a previous session decoded, by artifact id. See `GeometryClient.load`. */
export type HeldPointMaps = ReadonlyMap<string, PointMap>;

/**
 * The one sentence the status shows for a scene's presentation frame, beside its rung.
 *
 * A frame is a layout decision, so it is said out loud with its scale. When the cameras agreed on
 * an up direction the scene stands upright with the cameras at eye height. When they did not
 * (MEASURED 2026-09-05: a rock photographed from all around and turned over between series has
 * no gravity axis in its recovered frame) the scene axes stand and the sentence says no upright
 * is claimed, so a tilted exhibit reads as a fact about the photographs rather than a bug.
 */
/**
 * The sentence beside unposed depth. Not `displayFrameSentence`: that one speaks of recovered
 * cameras, and here there are none. The standpoint and the headings are this client's arrangement.
 */
export function unposedArrangementSentence(frame: SceneDisplayFrame): string {
  return `Arranged by this browser around one standpoint at ${frame.scale.toPrecision(3)}\u00d7 exhibit scale, `
    + 'each photograph turned to its own heading; no photograph\u2019s position was recovered.';
}

export function displayFrameSentence(frame: SceneDisplayFrame): string {
  const scale = `${frame.scale.toPrecision(3)}× nonmetric exhibit scale`;
  if (frame.upMethod !== 'scene-axes') {
    return `Displayed upright at ${scale}, with the recovered cameras at eye height.`;
  }
  return frame.cameraCount > 0
    ? `Displayed on its recovered axes at ${scale}; its recovered cameras do not agree on an up direction, so no upright is claimed.`
    : `Displayed on its recovered axes at ${scale}.`;
}

/**
 * How long one request may take before it is abandoned.
 *
 * Two numbers because the two requests are not alike: the list is a few hundred bytes of JSON
 * and a slow one means the server is in trouble, while a point map is a few megabytes and a
 * minute is an ordinary time for one on a poor connection. Both are deadlines rather than
 * budgets: exceeding one costs that region and no other.
 */
const LIST_TIMEOUT_MS = 15_000;
const BYTES_TIMEOUT_MS = 60_000;

/**
 * Which region each capture belongs to, built from the snapshot the world was drawn from.
 *
 * A map rather than a function, because the mapping is not total and pretending otherwise would
 * hide the interesting case. `buildIslands` creates a region for every capture some entity,
 * scene group or occurrence names; a photograph that produced geometry and none of those has no
 * region in this world, and inventing one here would be adding a region the layout never solved.
 * A capture absent from this map is reported rather than placed.
 */
export type RegionOfCapture = ReadonlyMap<string, IslandId>;

/** The mapping above, from the islands the snapshot already resolved. */
export function regionsByCapture(
  islands: readonly { readonly islandId: string; readonly captureIds: readonly string[] }[],
): RegionOfCapture {
  const byCapture = new Map<string, IslandId>();
  for (const island of islands) {
    for (const captureId of island.captureIds) byCapture.set(captureId, island.islandId as IslandId);
  }
  return byCapture;
}

/**
 * The container this build can decode.
 *
 * `decodeOpm` refuses anything but version 2 by name, and ADR-0010 D9 is refuse and regenerate
 * with no upgrade on read. This constant and that decoder move together or a region silently
 * shows nothing: it was `opm/1` until ADR-0010 was built, and the CORRECTED paragraph in that
 * record names this loader as the third writer its migration had to reach.
 *
 * A descriptor with a null container is attempted rather than refused: null means no stage
 * definition was recorded for that artifact's parameter digest, which is a fact about an older
 * corpus rather than a statement that the bytes are unreadable, and the decoder is then the
 * check. **A descriptor that says `opm/1` is refused here rather than at the decoder**, which
 * costs one region a fetch of several megabytes it could not have read, and the message names
 * the version rather than the file.
 */
const SUPPORTED_CONTAINER = 'opm/2';

interface GeometryWire {
  readonly captureId: string;
  readonly artifactId: string;
  readonly kind: string;
  readonly container: string | null;
  /**
   * Open, not a union of the two states this build knows.
   *
   * A closed union here would be validated in `parseGeometryList`, which throws for the whole
   * list, so one state added by a later server (D6's placement, D8's corridor) would take every
   * region's geometry away from every older client rather than the one descriptor carrying it.
   * The loader decides what to do with a state it does not recognise, per descriptor.
   */
  readonly state: string;
  readonly reason: string | null;
  readonly needsRepair: boolean;
  readonly reference: {
    readonly href: string;
    readonly authorization: 'workspace-bearer';
    readonly contentSha256: string;
    readonly byteSize: number;
  } | null;
}

export class GeometryClient {
  readonly #options: TransportOptions;
  readonly #observer: GeometryLoadObserver | undefined;
  readonly #decodePhotograph: PhotographDecoder;

  constructor(options: TransportOptions, observer?: GeometryLoadObserver, decodePhotograph?: PhotographDecoder) {
    this.#options = options;
    this.#decodePhotograph = decodePhotograph ?? decodePhotographInBrowser;
    this.#observer = observer;
  }

  /**
   * Load every region's geometry, in the order the server returned it.
   *
   * **Every request is bounded.** `fetch` has no timeout of its own, and nothing else on this
   * path had one: a half-open connection or a captive portal would leave the promise unsettled
   * for ever, and because `mount()` waits for this the page would stay blank with no error, no
   * notice and no retry. Each request therefore carries its own `AbortSignal.timeout`, so a
   * stall costs one region rather than the world, and any signal the caller supplied is honoured
   * alongside it.
   *
   * **At most one attempt per region.** The region is marked before the fetch, not after the
   * decode. Marking it after would mean a region whose first reconstruction fails its digest
   * falls through to the next candidate and the next: measured on the shape this corpus has, a
   * region of sixteen photographs behind a mangling proxy would fetch fifty-four megabytes to
   * draw nothing. One attempt makes the byte cost of a load at most one point map per region,
   * whatever goes wrong.
   *
   * **A map already decoded is not fetched again.** `held` is the previous session's maps by
   * artifact id. The list itself is re-read on every mount, which is what makes a deletion
   * reach the renderer: a region whose descriptor has gone loses its geometry on the next
   * mount rather than keeping it for the life of the tab. Re-reading a few hundred bytes of
   * JSON is what that costs.
   *
   * Sequential rather than concurrent, and **`mount()` awaits the whole of it**, which is the
   * shape `SourceMediaClient.load` already has. The consequence is stated rather than left to be
   * discovered: the world's first paint waits for every region's bytes. Sequential keeps peak
   * memory at one point map and keeps a slow link from carrying five requests at once; it does
   * not shorten the wait. What would shorten it is drawing the world first and re-mounting when
   * geometry arrives, which is a change to `mount()` rather than to the fetch order, and it is
   * left undone rather than done unmeasured.
   */
  async load(
    regionOf: RegionOfCapture,
    held?: HeldPointMaps,
    excludedCaptureIds: ReadonlySet<string> = new Set(),
  ): Promise<GeometrySession> {
    const descriptors = parseGeometryList(
      await this.#transport(LIST_TIMEOUT_MS).getJson<unknown>('/geometry'),
    );
    const pointMaps = new Map<IslandId, PointMap>();
    const byArtifact = new Map<string, PointMap>();
    const attempted = new Set<IslandId>();
    const issues: GeometryIssue[] = [];
    const digest = globalThis.crypto?.subtle;

    for (const descriptor of descriptors) {
      if (excludedCaptureIds.has(descriptor.captureId)) continue;
      const islandId = regionOf.get(descriptor.captureId) ?? null;
      const report = (state: GeometryIssueState, reason: string): void => {
        issues.push(Object.freeze({ captureId: descriptor.captureId, islandId, state, reason }));
      };

      if (islandId === null) {
        report(
          'no_region',
          'This photograph has a reconstruction and no region in this world to draw it in.',
        );
        continue;
      }
      if (attempted.has(islandId)) {
        // See the module comment. Not a failure and not hidden: a region holding several
        // unposed shells is what a scene group of photographs looks like before ADR-0009 D6.
        report(
          'unplaced',
          'This region already carries another photograph’s reconstruction. Placing a second '
            + 'one needs the recovered poses that no placement record carries yet.',
        );
        continue;
      }
      if (descriptor.state === 'bytes_missing') {
        report(
          'bytes_missing',
          descriptor.reason ?? 'The reconstruction was recorded and its bytes are not stored.',
        );
        continue;
      }
      if (descriptor.state !== 'available') {
        // A state this build has never heard of, checked BEFORE the reference so that an
        // unfamiliar state carrying no bytes is not mislabelled as missing ones. Reported for
        // this one descriptor and not thrown, because the wire will gain states as ADR-0009 D6
        // and D8 land, and a client that refused the whole list would lose every region's
        // geometry to one unknown word.
        report('error', `This build does not understand the state ‘${descriptor.state}’.`);
        continue;
      }
      if (descriptor.reference === null) {
        // Available and nameless. The server says a reference is null exactly when the state is
        // not available, so this is a malformed response rather than a missing artifact, and
        // calling it `bytes_missing` would report a server defect as a storage one.
        report('error', 'The server said a reconstruction was available and named no bytes.');
        continue;
      }
      if (descriptor.container !== null && descriptor.container !== SUPPORTED_CONTAINER) {
        report(
          'unsupported_container',
          `This build reads ${SUPPORTED_CONTAINER} and the reconstruction is ${descriptor.container}.`,
        );
        continue;
      }
      const reference = descriptor.reference;
      if (reference.authorization !== 'workspace-bearer' || !safeGeometryPath(reference.href)) {
        report('error', 'The geometry reference failed its provenance check.');
        continue;
      }

      const already = held?.get(descriptor.artifactId);
      if (already !== undefined) {
        // Verified when it was fetched, and an artifact id names one content hash for ever, so
        // there is nothing a re-fetch could establish that this does not already carry.
        attempted.add(islandId);
        pointMaps.set(islandId, already);
        byArtifact.set(descriptor.artifactId, already);
        continue;
      }
      if (digest === undefined) {
        report(
          'unverifiable',
          'This page has no SubtleCrypto, so the bytes cannot be checked against the digest that '
            + 'named them. Geometry is not loaded rather than loaded unchecked.',
        );
        continue;
      }

      // Marked here, before the fetch. See the module comment: one attempt per region.
      attempted.add(islandId);
      try {
        const response = await this.#transport(BYTES_TIMEOUT_MS).getBytes(reference.href);
        const bytes = await response.arrayBuffer();
        const failure = await verify(digest, bytes, reference.contentSha256, reference.byteSize);
        if (failure !== null) {
          report('verification_failed', failure);
          continue;
        }
        const map = decodeOpm(bytes);
        pointMaps.set(islandId, map);
        byArtifact.set(descriptor.artifactId, map);
      } catch (error) {
        if (error instanceof ApiError) {
          report(
            error.isUnauthenticated ? 'unauthorized' : 'error',
            geometryFailure(error),
          );
          continue;
        }
        if (error instanceof DOMException && error.name === 'TimeoutError') {
          report('timed_out', 'The reconstruction did not arrive in time.');
          continue;
        }
        // Everything the decoder throws lands here, and it is reported as a decode failure
        // rather than as a transport one: the bytes arrived and hashed correctly, so what
        // failed is this build's ability to read them.
        report('undecodable', error instanceof Error ? error.message : 'The container did not decode.');
      }
    }

    return Object.freeze({
      pointMaps,
      placedPointMaps: Object.freeze([]),
      displayFrames: new Map<string, SceneDisplayFrame>(),
      byArtifact,
      issues: Object.freeze(issues),
      renderingByScene: new Map(),
      trainedGeometry: Object.freeze([]),
      recoveredCameras: Object.freeze([]),
    });
  }

  /**
   * Load every placed map named by validated reconstruction-scene records.
   *
   * `displayed` names the scenes the resolved regions chose to show, one per region. A current
   * scene the regions did not choose, such as an automatic group scene beside an operator's fuller
   * exact set over the same photographs, is reported as `not_displayed` and fetches nothing, so
   * the same photographs' geometry is never stacked twice. Without the set every scene loads.
   */
  async loadScenes(
    scenes: readonly ReconstructionSceneRecord[],
    regionOf: RegionOfCapture,
    held?: HeldPointMaps,
    displayed?: ReadonlySet<string>,
  ): Promise<GeometrySession> {
    const pointMaps = new Map<IslandId, PointMap>();
    const placedPointMaps: PlacedScenePointMap[] = [];
    const byArtifact = new Map<string, PointMap>();
    const renderingByScene = new Map<string, RenderingSubstrate>();
    const issues: GeometryIssue[] = [];
    const digest = globalThis.crypto?.subtle;
    const trainedGeometry: TrainedSceneGeometry[] = [];
    const recoveredCameras: RecoveredSceneCamera[] = [];
    const displayFrames = new Map<string, SceneDisplayFrame>();

    /**
     * Held, or fetched, digest-verified and decoded: the one path every scene point map takes,
     * placed or not. Reports its own failure and answers null, so no caller can draw bytes that
     * failed their check.
     */
    const obtain = async (
      sceneId: string,
      captureId: string,
      artifactId: string,
      reference: { readonly href: string; readonly contentSha256: string; readonly byteSize: number },
      report: (state: GeometryIssueState, reason: string) => void,
    ): Promise<{ map: PointMap; measurement: GeometryLoadMeasurement | null } | null> => {
      const kept = held?.get(artifactId);
      if (kept !== undefined) return { map: kept, measurement: null };
      if (digest === undefined) {
        report('unverifiable', 'This page has no SubtleCrypto, so scene geometry is not loaded unchecked.');
        return null;
      }
      try {
        const fetchStarted = monotonicNow();
        const response = await this.#transport(BYTES_TIMEOUT_MS).getBytes(reference.href);
        const bytes = await response.arrayBuffer();
        const fetchMs = monotonicNow() - fetchStarted;
        const verifyStarted = monotonicNow();
        const failure = await verify(digest, bytes, reference.contentSha256, reference.byteSize);
        const verifyMs = monotonicNow() - verifyStarted;
        if (failure !== null) {
          report('verification_failed', failure);
          return null;
        }
        const decodeStarted = monotonicNow();
        const map = decodeOpm(bytes);
        return {
          map,
          measurement: Object.freeze({
            sceneId,
            captureId,
            artifactId,
            expectedBytes: reference.byteSize,
            receivedBytes: bytes.byteLength,
            fetchMs,
            verifyMs,
            decodeMs: monotonicNow() - decodeStarted,
            reused: false,
          }),
        };
      } catch (error) {
        if (error instanceof ApiError) {
          report(error.isUnauthenticated ? 'unauthorized' : 'error', geometryFailure(error));
        } else if (error instanceof DOMException && error.name === 'TimeoutError') {
          report('timed_out', 'The reconstruction did not arrive in time.');
        } else {
          report('undecodable', error instanceof Error ? error.message : 'The container did not decode.');
        }
        return null;
      }
    };

    for (const scene of scenes) {
      let loadedForScene = 0;
      const sceneCameras: RecoveredSceneCamera[] = [];
      const scenePlaced: PlacedScenePointMap[] = [];
      const sceneTrained: TrainedSceneGeometry[] = [];
      const resolvedIslands = new Set(
        scene.members.map((member) => regionOf.get(member.captureId)).filter(
          (value): value is IslandId => value !== undefined,
        ),
      );
      const islandId = resolvedIslands.size === 1 && scene.members.every(
        (member) => regionOf.has(member.captureId),
      ) ? [...resolvedIslands][0]! : null;
      if (displayed !== undefined && !displayed.has(scene.sceneId)) {
        issues.push({
          sceneId: scene.sceneId, captureId: scene.members[0]?.captureId ?? '', islandId,
          state: 'not_displayed',
          reason: 'Its region displays a more complete reconstruction of the same photographs; '
            + 'this scene remains recorded and is not drawn.',
        });
        renderingByScene.set(scene.sceneId, 'source_photographs');
        continue;
      }

      for (const member of scene.members) {
        if (member.recoveredCamera != null && member.registered && scene.receiptState === 'available'
          && scene.poseReceiptSha256 !== null && islandId !== null && scene.islandId === islandId) {
          try {
            const camera: RecoveredSceneCamera = { ...member.recoveredCamera, sceneId: scene.sceneId,
              captureId: member.captureId, ordinal: member.ordinal, islandId,
              poseReceiptSha256: scene.poseReceiptSha256 };
            validateRecoveredSceneCamera(camera);
            sceneCameras.push(camera);
          } catch (error) {
            issues.push({ sceneId: scene.sceneId, captureId: member.captureId, islandId, state: 'undecodable',
              reason: error instanceof Error ? error.message : 'The recovered camera is invalid.' });
          }
        }
        const placement = member.placement;
        if (placement === null) continue;
        const report = (state: GeometryIssueState, reason: string): void => {
          issues.push(Object.freeze({
            sceneId: scene.sceneId,
            captureId: member.captureId,
            islandId,
            state,
            reason,
          }));
        };
        if (islandId === null || scene.islandId !== islandId) {
          report(
            'no_region',
            'The reconstruction scene no longer resolves to one complete region in this graph.',
          );
          continue;
        }
        if (placement.scaleStatus !== 'colmap-correspondence-fit') {
          report('unplaced', 'This reconstruction has no validated alignment to the recovered cameras.');
          continue;
        }
        if (placement.state !== 'available' || placement.reference === null) {
          report('bytes_missing', 'The placed point map is recorded and its bytes are unavailable.');
          continue;
        }
        if (placement.container !== null && placement.container !== SUPPORTED_CONTAINER) {
          report(
            'unsupported_container',
            `This build reads ${SUPPORTED_CONTAINER} and the reconstruction is ${placement.container}.`,
          );
          continue;
        }
        const reference = placement.reference;
        if (
          reference.authorization !== 'workspace-bearer'
          || reference.href !== `/geometry/${placement.artifactId}`
          || !safeGeometryPath(reference.href)
          || reference.contentSha256 !== placement.contentSha256
        ) {
          report('error', 'The scene geometry reference failed its provenance check.');
          continue;
        }

        const obtained = await obtain(scene.sceneId, member.captureId, placement.artifactId, reference, report);
        if (obtained === null) continue;
        const { map, measurement } = obtained;
        const placed: PlacedScenePointMap = {
          sceneId: scene.sceneId,
          artifactId: placement.artifactId,
          captureId: member.captureId,
          islandId,
          map,
          sceneFromOpmRowMajor: placement.sceneFromOpmRowMajor,
          localUnitsToSceneUnits: placement.localUnitsToSceneUnits,
        };
        try {
          validateScenePointMapPlacement(placed);
        } catch (error) {
          report('error', error instanceof Error ? error.message : 'The placement is invalid.');
          continue;
        }
        this.#observer?.(measurement ?? Object.freeze({
          sceneId: scene.sceneId,
          captureId: member.captureId,
          artifactId: placement.artifactId,
          expectedBytes: reference.byteSize,
          receivedBytes: 0,
          fetchMs: 0,
          verifyMs: 0,
          decodeMs: 0,
          reused: true,
        }));
        scenePlaced.push(placed);
        byArtifact.set(placement.artifactId, map);
        if (!pointMaps.has(islandId)) pointMaps.set(islandId, map);
        loadedForScene += 1;
      }
      // Rung 3 with no pose: each photograph's own depth, in an arrangement this client derives
      // and labels as unmeasured. Only when the scene placed nothing, which is the only time the
      // server sends these; a scene that placed anything keeps its excluded members as photographs.
      let loadedUnposed = 0;
      const unposedMembers = scene.members.every((member) => member.placement === null)
        ? [...scene.members].sort((a, b) => a.ordinal - b.ordinal)
          .filter((member) => member.unposedPointMap != null)
        : [];
      const unposedLoaded: { captureId: string; artifactId: string; map: PointMap;
        measurement: GeometryLoadMeasurement | null; byteSize: number;
        report: (state: GeometryIssueState, reason: string) => void;
        photograph: ImageBitmap | null }[] = [];
      for (const member of unposedMembers) {
        const unposed = member.unposedPointMap!;
        const report = (state: GeometryIssueState, reason: string): void => {
          issues.push(Object.freeze({ sceneId: scene.sceneId, captureId: member.captureId, islandId, state, reason }));
        };
        if (islandId === null || scene.islandId !== islandId) {
          report('no_region', 'The reconstruction scene no longer resolves to one complete region in this graph.');
          continue;
        }
        if (unposed.state !== 'available' || unposed.reference === null) {
          report('bytes_missing', 'This photograph\u2019s depth is recorded and its bytes are unavailable.');
          continue;
        }
        if (unposed.container !== null && unposed.container !== SUPPORTED_CONTAINER) {
          report('unsupported_container', `This build reads ${SUPPORTED_CONTAINER} and the reconstruction is ${unposed.container}.`);
          continue;
        }
        const reference = unposed.reference;
        if (
          reference.authorization !== 'workspace-bearer'
          || reference.href !== `/geometry/${unposed.artifactId}`
          || !safeGeometryPath(reference.href)
          || reference.contentSha256 !== unposed.contentSha256
        ) {
          report('error', 'The scene geometry reference failed its provenance check.');
          continue;
        }
        const obtained = await obtain(scene.sceneId, member.captureId, unposed.artifactId, reference, report);
        if (obtained === null) continue;
        const photograph = await this.#photograph(unposed.photograph ?? null, obtained.map, digest, report);
        unposedLoaded.push({ captureId: member.captureId, artifactId: unposed.artifactId, ...obtained,
          byteSize: reference.byteSize, report, photograph });
      }
      const fan = unmeasuredFan(unposedLoaded.map(({ map }) => ({
        position: map.header.viewpoint.position,
        fovYDeg: map.header.viewpoint.fovYDeg,
        aspect: map.header.viewpoint.aspect,
      })));
      unposedLoaded.forEach((loaded, index) => {
        const sceneFromOpm = fan[index] ?? null;
        if (sceneFromOpm === null || islandId === null) {
          loaded.report('unplaced', 'More photographs than one unmeasured arrangement holds; this one opens as a photograph.');
          return;
        }
        const placed: PlacedScenePointMap = {
          sceneId: scene.sceneId,
          artifactId: loaded.artifactId,
          captureId: loaded.captureId,
          islandId,
          map: loaded.map,
          sceneFromOpmRowMajor: sceneFromOpm,
          localUnitsToSceneUnits: 1,
          arrangement: 'unmeasured-fan',
          ...(loaded.photograph === null ? {} : { photograph: loaded.photograph }),
        };
        try {
          validateScenePointMapPlacement(placed);
        } catch (error) {
          loaded.report('error', error instanceof Error ? error.message : 'The arrangement is invalid.');
          return;
        }
        this.#observer?.(loaded.measurement ?? Object.freeze({
          sceneId: scene.sceneId, captureId: loaded.captureId, artifactId: loaded.artifactId,
          expectedBytes: loaded.byteSize, receivedBytes: 0, fetchMs: 0, verifyMs: 0, decodeMs: 0, reused: true,
        }));
        scenePlaced.push(placed);
        byArtifact.set(loaded.artifactId, loaded.map);
        if (!pointMaps.has(islandId)) pointMaps.set(islandId, loaded.map);
        loadedUnposed += 1;
      });
      renderingByScene.set(
        scene.sceneId,
        loadedForScene > 0 ? 'posed_point_maps' : loadedUnposed > 0 ? 'unposed_point_maps' : 'source_photographs',
      );
      const trained = scene.trainedGeometry;
      if (trained != null) {
        const report = (state: GeometryIssueState, reason: string): void => {
          issues.push({ sceneId: scene.sceneId, captureId: scene.members[0]?.captureId ?? '', islandId, state, reason });
        };
        const reference = trained.reference;
        if (islandId === null || scene.islandId !== islandId) {
          report('no_region', 'The trained scene does not resolve to one complete region.');
        } else if (trained.state !== 'available' || reference === null) {
          report('bytes_missing', 'The trained scene is recorded but its verified bytes are unavailable.');
        } else if (trained.container !== 'sog/1') {
          report('unsupported_container', 'This build reads trained scene bundles in sog/1.');
        } else if (reference.authorization !== 'workspace-bearer'
          || reference.href !== `/scene-geometry/${trained.artifactId}`
          || !/^\/scene-geometry\/[0-9a-f-]{36}$/u.test(reference.href)
          || reference.contentSha256 !== trained.contentSha256) {
          report('error', 'The trained scene reference failed its provenance check.');
        } else if (digest === undefined) {
          report('unverifiable', 'This page cannot verify trained scene bytes; source evidence remains available.');
        } else {
          try {
            const started = monotonicNow();
            const response = await this.#transport(BYTES_TIMEOUT_MS).getBytes(reference.href);
            const bytes = await response.arrayBuffer();
            const fetched = monotonicNow();
            const failure = await verify(digest, bytes, reference.contentSha256, reference.byteSize);
            const verified = monotonicNow();
            if (failure !== null) report('verification_failed', failure);
            else {
              const { pointCount } = validateSogBundle(bytes);
              const value: TrainedSceneGeometry = {
                sceneId: scene.sceneId, islandId, artifactId: trained.artifactId,
                bytes, pointCount, bounds: trained.bounds,
                sceneFromAssetRowMajor: trained.sceneFromAssetRowMajor,
              };
              validateTrainedSceneGeometry(value);
              sceneTrained.push(value);
              this.#observer?.(Object.freeze({
                sceneId: scene.sceneId, captureId: scene.members[0]?.captureId ?? '',
                artifactId: trained.artifactId, expectedBytes: reference.byteSize, receivedBytes: bytes.byteLength,
                fetchMs: fetched - started, verifyMs: verified - fetched, decodeMs: monotonicNow() - verified, reused: false,
              }));
            }
          } catch (error) {
            report(error instanceof ApiError && error.isUnauthenticated ? 'unauthorized' : 'undecodable',
              error instanceof Error ? error.message : 'The trained scene could not load.');
          }
        }
      }

      // Presentation: one similarity per scene, from its recovered cameras, so the scene stands
      // upright, centred and at walking scale in its region. Receipts and identities are untouched.
      const samples = sceneCameras.length > 0
        ? sceneCameras.map((camera) => colmapCameraSample(camera.sceneFromCameraRowMajor))
        : scenePlaced.map((placed) => opmCameraSample(placed.sceneFromOpmRowMajor, placed.map.header.viewpoint.position));
      const corners = [
        ...scenePlaced.flatMap((placed) => transformedBoxCorners(placed.map.header.bounds, placed.sceneFromOpmRowMajor)),
        ...sceneTrained.flatMap((trained) => transformedBoxCorners(trained.bounds, trained.sceneFromAssetRowMajor)),
      ];
      const frame = sceneDisplayFrame(samples, corners);
      if (sceneCameras.length + scenePlaced.length + sceneTrained.length > 0) displayFrames.set(scene.sceneId, frame);
      const reportDisplayed = (captureId: string, error: unknown): void => {
        issues.push({ sceneId: scene.sceneId, captureId, islandId, state: 'undecodable',
          reason: error instanceof Error ? error.message : 'The displayed transform is invalid.' });
      };
      for (const camera of sceneCameras) {
        const value = { ...camera, sceneFromCameraRowMajor: displayCameraTransform(frame, camera.sceneFromCameraRowMajor) };
        try { validateRecoveredSceneCamera(value); recoveredCameras.push(Object.freeze(value)); }
        catch (error) { reportDisplayed(camera.captureId, error); }
      }
      for (const placed of scenePlaced) {
        const value = { ...placed, sceneFromOpmRowMajor: composeDisplayFrame(frame, placed.sceneFromOpmRowMajor),
          localUnitsToSceneUnits: frame.scale * placed.localUnitsToSceneUnits };
        try { validateScenePointMapPlacement(value); placedPointMaps.push(Object.freeze(value)); }
        catch (error) { reportDisplayed(placed.captureId ?? '', error); }
      }
      for (const trained of sceneTrained) {
        const value = { ...trained, sceneFromAssetRowMajor: composeDisplayFrame(frame, trained.sceneFromAssetRowMajor) };
        try { validateTrainedSceneGeometry(value); trainedGeometry.push(Object.freeze(value)); }
        catch (error) { reportDisplayed(scene.members[0]?.captureId ?? '', error); }
      }
    }

    return Object.freeze({
      pointMaps,
      placedPointMaps: Object.freeze(placedPointMaps),
      byArtifact,
      issues: Object.freeze(issues),
      renderingByScene,
      trainedGeometry: Object.freeze(trainedGeometry),
      recoveredCameras: Object.freeze(recoveredCameras),
      displayFrames,
    });
  }

  /**
   * The viewer's image of one photograph, for texturing its unplaced depth, or null with the
   * reason reported. Fetched from the viewer route the graph named, refused unless its bytes hash
   * to the digest the graph named, and decoded upright at the photograph's own proportions. A
   * failure costs detail and nothing else: the depth is still drawn, in its own colours.
   */
  async #photograph(
    reference: NonNullable<UnposedPointMapRecord['photograph']> | null,
    map: PointMap,
    digest: SubtleCrypto | undefined,
    report: (state: GeometryIssueState, reason: string) => void,
  ): Promise<ImageBitmap | null> {
    if (reference === null) return null;
    if (reference.authorization !== 'workspace-bearer' || !PHOTOGRAPH_PATH.test(reference.href)) {
      report('photograph_unavailable', 'The photograph reference failed its provenance check; its depth keeps its own colours.');
      return null;
    }
    if (digest === undefined) {
      report('photograph_unavailable', 'This page cannot verify the photograph, so its depth keeps its own colours.');
      return null;
    }
    try {
      const response = await this.#transport(BYTES_TIMEOUT_MS).getBytes(reference.href);
      const bytes = await response.arrayBuffer();
      const failure = await verify(digest, bytes, reference.contentSha256, reference.byteSize);
      if (failure !== null) {
        report('photograph_unavailable', `${failure} Its depth keeps its own colours.`);
        return null;
      }
      const decoded = await this.#decodePhotograph(bytes, map.header.sourceImage);
      if (decoded === null) {
        report('photograph_unavailable', 'The photograph did not decode at its recorded proportions; its depth keeps its own colours.');
      }
      return decoded;
    } catch (error) {
      report('photograph_unavailable', error instanceof ApiError
        ? `${geometryFailure(error)} Its depth keeps its own colours.`
        : 'The photograph could not be loaded; its depth keeps its own colours.');
      return null;
    }
  }

  /** A transport for one request, carrying its own deadline. See `load`. */
  #transport(timeoutMs: number): Transport {
    const deadline = AbortSignal.timeout(timeoutMs);
    const supplied = this.#options.signal;
    return new Transport({
      ...this.#options,
      signal: supplied === undefined ? deadline : AbortSignal.any([supplied, deadline]),
    });
  }
}

function monotonicNow(): number {
  return globalThis.performance?.now() ?? Date.now();
}

/**
 * The digest check, and the length check that comes before it.
 *
 * Length first because it is free and because a body of the wrong size is a different fact from
 * one with the wrong content: a truncated transfer and a substituted artifact both fail the
 * hash, and only one of them is worth retrying. Returns the reason it failed, or null.
 */
async function verify(
  subtle: SubtleCrypto,
  bytes: ArrayBuffer,
  expected: string,
  byteSize: number,
): Promise<string | null> {
  if (bytes.byteLength !== byteSize) {
    return `The reconstruction is ${byteSize} bytes and ${bytes.byteLength} arrived.`;
  }
  const actual = hex(await subtle.digest('SHA-256', bytes));
  if (actual !== expected) {
    return `The bytes hash to ${actual.slice(0, 12)}… and the descriptor named ${expected.slice(0, 12)}….`;
  }
  return null;
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** The same shape `source-media-api.ts` requires of an evidence path, for the same reason. */
/** Decode a verified photograph upright, or null when it is not at the recorded proportions. */
export type PhotographDecoder = (
  bytes: ArrayBuffer,
  source: { readonly width: number; readonly height: number },
) => Promise<ImageBitmap | null>;

/** The viewer route and nothing else: a span id and the masked suffix. */
const PHOTOGRAPH_PATH = /^\/evidence\/[0-9a-f-]{36}\/masked$/u;
/** Longest side a photograph is uploaded at. Detail beyond this is not visible at walking distance. */
export const PHOTOGRAPH_MAX_SIDE = 4096;

/**
 * The browser's own decoder, EXIF orientation applied, scaled to at most `PHOTOGRAPH_MAX_SIDE`.
 * The result must have the photograph's recorded proportions, which is what proves it is upright
 * the same way the depth grid is: a sideways decode of a portrait photograph would be refused here
 * rather than drawn across the surface rotated.
 */
async function decodePhotographInBrowser(
  bytes: ArrayBuffer,
  source: { readonly width: number; readonly height: number },
): Promise<ImageBitmap | null> {
  if (typeof createImageBitmap !== 'function') return null;
  const full = await createImageBitmap(new Blob([bytes]), { imageOrientation: 'from-image' });
  if (Math.abs(full.width * source.height - full.height * source.width) > Math.max(full.width, full.height)) {
    full.close();
    return null;
  }
  const scale = Math.min(1, PHOTOGRAPH_MAX_SIDE / Math.max(full.width, full.height));
  if (scale === 1) return full;
  const scaled = await createImageBitmap(full, {
    resizeWidth: Math.round(full.width * scale),
    resizeHeight: Math.round(full.height * scale),
    resizeQuality: 'high',
  });
  full.close();
  return scaled;
}

function safeGeometryPath(value: string): boolean {
  return value.startsWith('/geometry/')
    && !value.includes('://')
    && !value.includes('?')
    && !value.includes('#');
}

function geometryFailure(error: ApiError): string {
  if (error.isUnauthenticated) return 'This session is not authorized to load the reconstruction.';
  if (error.status === 410) return 'This reconstruction was deleted.';
  if (error.code === 'unavailable_asset') return 'The reconstruction bytes are not in storage.';
  return `${error.code}: ${error.message.replace(`${error.code}: `, '')}`;
}

function parseGeometryList(value: unknown): readonly GeometryWire[] {
  if (!Array.isArray(value)) throw new TypeError('The server returned an invalid geometry list.');
  return Object.freeze(value.map((item) => {
    const row = asRecord(item, 'geometry item');
    // Required to be a non-empty string and nothing more. Which states exist is the server's to
    // extend; which ones this build can act on is the loader's to decide. See `GeometryWire`.
    const state = requiredText(row['state'], 'geometry state');
    const raw = row['reference'];
    let reference: GeometryWire['reference'] = null;
    if (raw !== null && raw !== undefined) {
      const value_ = asRecord(raw, 'geometry reference');
      if (value_['authorization'] !== 'workspace-bearer') {
        throw new TypeError('The server returned an unknown geometry authorization mode.');
      }
      reference = Object.freeze({
        href: requiredText(value_['href'], 'geometry href'),
        authorization: 'workspace-bearer',
        contentSha256: requiredDigest(value_['content_sha256']),
        byteSize: requiredCount(value_['byte_size'], 'geometry byte size'),
      });
    }
    return Object.freeze({
      captureId: requiredText(row['capture_id'], 'capture ID'),
      artifactId: requiredText(row['artifact_id'], 'artifact ID'),
      kind: requiredText(row['kind'], 'geometry kind'),
      container: optionalText(row['container'], 'container'),
      state,
      reason: optionalText(row['reason'], 'geometry reason'),
      needsRepair: row['needs_repair'] === true,
      reference,
    });
  }));
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${label}.`);
  }
  return value as Record<string, unknown>;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid ${label}.`);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  return value === null || value === undefined ? null : requiredText(value, label);
}

function requiredCount(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`Invalid ${label}.`);
  }
  return value;
}

/**
 * Refused at the boundary rather than at the comparison.
 *
 * A digest that is not 64 lowercase hex characters can never equal one this module computes, so
 * accepting it would turn a malformed response into a per-region verification failure that reads
 * like a corrupted artifact. It is the response that is wrong, and it says so once.
 */
function requiredDigest(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError('The server returned a content hash that is not a SHA-256.');
  }
  return value;
}

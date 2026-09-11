/**
 * The two things every surface module is handed: what the document gave us, and what the session
 * is currently holding.
 *
 * `main.ts` used to be one file because these values were module-level `let` bindings and every
 * surface reached them by name. Splitting the file without splitting that state would have turned
 * the bindings into cross-module globals, which is the same coupling wearing an import statement.
 *
 * So there is exactly one mutable object. A surface module receives it, reads it and writes it,
 * and no surface module owns a `let` of its own that another surface can see. The rule is
 * checkable by reading the top of each module in `composition/`: a module-level `let` there is a
 * bug, and everything mutable that must survive a re-mount is a field below.
 *
 * `AppEnvironment` is the other half and is frozen on purpose. It is what the document and the
 * URL decided before any session existed, and nothing in a mount may change it.
 */

import type { IslandId, SceneDisplayFrame } from '@exulanica/atlas-core';
import type { GraphSnapshot } from '@exulanica/graph-client';
import type {
  PlacedScenePointMap,
  PointMap,
  RecoveredSceneCamera,
  SourceMediaCatalog,
  TrainedSceneGeometry,
} from '@exulanica/atlas-react/playcanvas';
import type { CompanionSession } from '@exulanica/companion-runtime';
import type { WorldArtProfile } from '@exulanica/presentation';
import { worldArtProfile } from '@exulanica/presentation';
import type { IndexFacets } from '@exulanica/world-index';
import { decodeFacets } from '@exulanica/world-index';

import type { MountedAtlas } from '../atlas.js';
import { browserValidation } from '../browser-validation.js';
import { isAtlasPreview } from '../config.js';
import type { EvidenceCache } from '../evidence.js';
import type { GeometryIssue, HeldPointMaps } from '../geometry-api.js';
import type { InteractionPolicyClient } from '../interaction-policy.js';
import type { ObservationSummary } from '../observations-api.js';
import { readPreferences, type AtlasPreferences } from '../preferences.js';
import type { Session } from '../session.js';
import type { SourceMediaSession } from '../source-media-api.js';
import type { CompanionStage } from '../ui/companion-stage.js';
import type { ReconstructionRungDisclosure } from '../ui/status.js';
import type { WorldStyleClient, WorldStyleConnection } from '../world-style-api.js';

/** What the document and the URL settled before a session existed. Never written by a mount. */
export interface AppEnvironment {
  readonly shell: HTMLElement;
  readonly canvas: HTMLCanvasElement;
  /** The opt-in `validation=1` recorder, or null. Null is the ordinary case. */
  readonly browserMeasurement: ReturnType<typeof browserValidation>;
  readonly systemAppearance: MediaQueryList;
  readonly systemReducedMotion: MediaQueryList;
  /** The development `?preview=1` exception. False in every production build. */
  readonly preview: boolean;
  /** A world style named in the preview URL, which outranks the stored preference while set. */
  readonly previewArtProfile: WorldArtProfile | undefined;
}

/**
 * Everything a mount may change, and everything that has to outlive one.
 *
 * `mount()` runs again after every committed write. A field here is a field whose value must
 * survive that, either because re-reading it would cost bytes (`heldPointMaps`), because it is
 * what the visitor is currently looking through (`proofLensEnabled`), or because it is the handle
 * that stops the previous mount's owner (`atlas`, `mountListeners`, `stopWatching`).
 *
 * Values that do NOT survive a mount are deliberately absent: they are locals in the module that
 * builds them, which is what makes "this surface is rebuilt each mount" true by construction.
 */
export interface SessionState {
  credentials: { baseUrl: string; token: string } | null;
  session: Session | null;
  snapshot: GraphSnapshot | null;
  evidence: EvidenceCache | null;
  companionEngine: CompanionSession | null;

  // -- the handles that stop a previous mount -------------------------------------------------
  atlas: MountedAtlas | null;
  mountedCompanionStage: CompanionStage | null;
  mountListeners: AbortController | null;
  stopWatching: (() => void) | null;
  stopWorldStyleProposalInbox: (() => void) | null;
  settingsStylePreviewId: string | null;

  // -- what the world is currently drawing ----------------------------------------------------
  /**
   * The geometry the world is currently drawing, whichever side it came from.
   *
   * One field rather than two, because a mount must not know: production reads it from the API
   * through `geometry-api.ts` and the preview loads a reconstruction from disk, and a mount that
   * branched on which would be a second place for the two to diverge.
   */
  pointMaps: ReadonlyMap<IslandId, PointMap> | undefined;
  /** All maps with their shared-scene transforms. Undefined for the legacy preview path. */
  placedPointMaps: readonly PlacedScenePointMap[] | undefined;
  trainedGeometry: readonly TrainedSceneGeometry[];
  recoveredCameras: readonly RecoveredSceneCamera[];
  notDrawnScenes: ReadonlySet<string>;
  displayFrames: ReadonlyMap<string, SceneDisplayFrame>;
  /** What the last production load decoded, by artifact id, so a re-mount re-fetches no bytes. */
  heldPointMaps: HeldPointMaps | undefined;

  // -- what the status bar is currently saying ------------------------------------------------
  sourceMediaNotices: readonly string[];
  geometryNotices: readonly string[];
  geometryIssues: readonly GeometryIssue[];
  reconstructionRungs: readonly ReconstructionRungDisclosure[];

  /**
   * Whether the proof lens is switched on, for this session only.
   *
   * Not a preference and not persisted. The lens is a way of looking at what is already on screen,
   * and a stored one would change what a visitor sees on arrival on the strength of something they
   * did once. It is also the reason this is a plain field rather than renderer state: switching it
   * writes one uniform per region and nothing else.
   */
  proofLensEnabled: boolean;

  /**
   * Which photograph the review panel is currently about, so a late answer cannot land on another.
   *
   * Not cached, unlike the observation summary below. An accepted pose receipt is immutable and
   * re-reading it says nothing new; a review is the opposite, since every button in it writes a
   * receipt that changes what the next read returns.
   */
  reviewCaptureId: string | null;

  /**
   * One scene's recorded observation counts, cached for the session. See `observations-api.ts`.
   * Clicks are not cached: each is resolved by the server, and holds nothing here once shown.
   */
  observationSummary: ObservationSummary | null;
  observationSummarySceneId: string | null;
  observationSummaryLoad: Promise<void> | null;

  // -- the authorities a session connected to -------------------------------------------------
  worldStyles: WorldStyleClient | null;
  worldStyleConnection: WorldStyleConnection | null;
  worldStyleFailure: string | null;
  interactionPolicies: InteractionPolicyClient | null;
  sourceMediaSession: SourceMediaSession | null;
  previewSourceMedia: SourceMediaCatalog | undefined;

  // -- what the visitor has chosen ------------------------------------------------------------
  preferences: AtlasPreferences;
  indexFacets: IndexFacets;
  selected: string | null;
  /** Monotonic, so two proposals in one session never share an id. Not a clock and not random. */
  issued: number;
}

/**
 * Read the document, the URL and stored preferences once.
 *
 * The throw is the same one the single-file version made at module evaluation: an application
 * with no canvas and no shell has nothing to compose, and failing here is better than failing
 * later inside a surface that assumed both.
 */
export function createAppEnvironment(): AppEnvironment {
  const shell = document.getElementById('shell');
  const canvas = document.getElementById('atlas');
  if (!(canvas instanceof HTMLCanvasElement) || shell === null) {
    throw new Error('app: expected #atlas and #shell in the document');
  }
  const preview = isAtlasPreview(window.location.search, import.meta.env.DEV);
  const previewArtProfileId = preview
    ? new URLSearchParams(window.location.search).get('world-style')
    : null;
  return Object.freeze({
    shell,
    canvas,
    browserMeasurement: browserValidation(window.location.search),
    systemAppearance: window.matchMedia('(prefers-color-scheme: dark)'),
    systemReducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)'),
    preview,
    previewArtProfile: previewArtProfileId === null
      ? undefined
      : worldArtProfile(previewArtProfileId),
  });
}

/** The empty session. Every field starts at the value the single-file version initialised it to. */
export function createSessionState(): SessionState {
  return {
    credentials: null,
    session: null,
    snapshot: null,
    evidence: null,
    companionEngine: null,

    atlas: null,
    mountedCompanionStage: null,
    mountListeners: null,
    stopWatching: null,
    stopWorldStyleProposalInbox: null,
    settingsStylePreviewId: null,

    pointMaps: undefined,
    placedPointMaps: undefined,
    trainedGeometry: Object.freeze([]),
    recoveredCameras: Object.freeze([]),
    notDrawnScenes: new Set(),
    displayFrames: new Map(),
    heldPointMaps: undefined,

    sourceMediaNotices: Object.freeze([]),
    geometryNotices: Object.freeze([]),
    geometryIssues: Object.freeze([]),
    reconstructionRungs: Object.freeze([]),

    proofLensEnabled: false,
    reviewCaptureId: null,
    observationSummary: null,
    observationSummarySceneId: null,
    observationSummaryLoad: null,

    worldStyles: null,
    worldStyleConnection: null,
    worldStyleFailure: null,
    interactionPolicies: null,
    sourceMediaSession: null,
    previewSourceMedia: undefined,

    preferences: readPreferences(window.localStorage),
    indexFacets: decodeFacets(window.location.search),
    selected: null,
    issued: 0,
  };
}

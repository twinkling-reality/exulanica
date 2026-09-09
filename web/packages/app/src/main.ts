/**
 * Boot: one session, one snapshot, one scene, and one write path.
 *
 * The shape of this file is the argument. It builds a session, reads the graph once, adapts it
 * into a scene, mounts the renderer, and wires three surfaces to that one snapshot. In a normal
 * build there is no second source of truth and no fixture: everything on the screen came from
 * `GET /graph`, `GET /evidence/{span}` or a write that went through the gate. The Vite development
 * server has one explicit `?preview=1` exception for UI work while the API is unavailable. It is
 * synthetic, identified in the document title and contextual surfaces, and read-only; production
 * builds cannot enter it.
 *
 * **Every write goes through the confirmation surface**, and the confirmation surface is the only
 * caller of `session.commit`. The chain is: the user types a name, a draft is built by
 * `world-index`, translated into an update proposal, staged on the gate, rendered for reading,
 * and committed only when the user presses confirm. Skipping any link is not possible from here,
 * because `session` exposes `stage` and `commit` separately and the panel is what sits between.
 *
 * **The snapshot is re-read after a write rather than patched.** A local patch would be a second
 * model of the graph maintained by hand, and the first time it disagreed with the server the
 * interface would be confidently wrong. Re-reading costs one request and cannot drift.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';
import './appearance.css';
import './unified-interface.css';

import type { OccurrenceRecord, RenderingSubstrate } from '@exulanica/graph-client';
import { ApiError } from '@exulanica/graph-client';
import {
  anchorId as toAnchorId,
  islandId as toIslandId,
  type IslandId,
} from '@exulanica/atlas-core';
// A second atlas-core import, deliberately its own statement. Click-to-evidence's geometry is a
// self-contained group, and keeping it apart from the block above leaves that block byte-identical
// to the one the person-consent branch also edits.
import {
  canvasToSourcePixel,
  observationSentence,
  pickObservedPoint,
  type PickCamera,
} from '@exulanica/atlas-core';
import {
  FACET_KEYS,
  confirmationFor,
  decodeFacets,
  draftEdit,
  encodeFacets,
  type IndexFacets,
} from '@exulanica/world-index';
import { mountAtlas, type MountedAtlas } from './atlas.js';
import { applicationTitle, developmentToken, sourcePresentation } from './config.js';
import { listBatches, watchBatch, type BatchSummary } from './formation.js';
import { toUpdateProposal } from './proposal.js';
import { buildScene } from './scene.js';
import { buildConfirm } from './ui/confirm.js';
import { buildCompanionEncounter } from './ui/companion-encounter.js';
import { resolveCompanionPlacement } from './ui/companion-placement.js';
import { buildAtlasCommands, type AtlasCommand } from './ui/atlas-commands.js';
import { buildControlsGuide } from './ui/controls-guide.js';
import { buildOptions } from './ui/options.js';
import { buildWorldChrome } from './ui/world-chrome.js';
import { buildCompanionStage, type CompanionStage } from './ui/companion-stage.js';
import { createCompanionController } from './companion.js';
import { CompanionAskClient } from './companion-ask-api.js';
import type { Turn } from '@exulanica/companion-runtime';
import { buildDetail } from './ui/detail.js';
import { buildFormation } from './ui/formation.js';
import { buildEmptyWorld } from './ui/empty-world.js';
import { buildPersonReview } from './ui/person-review.js';
import { PersonRegionDrafts } from './ui/person-region-editor.js';
import { buildReconstructionInspector } from './ui/reconstruction-inspector.js';
import { buildStartupState } from './ui/startup-state.js';
import { el, replace } from './ui/dom.js';
import { createFirstUseGuidance, type FirstUseMode } from './ui/first-use-guidance.js';
import { buildWorldIndex } from './ui/world-index.js';
import { MapPeek } from './ui/map-peek.js';
import { buildRegionPlan } from './ui/region-plan.js';
import { buildStatus, MAP_ORIENTATION_CAPTION } from './ui/status.js';
// Below the status import rather than beside it: the person-consent branch adds its own imports
// at the top of this block, and two branches inserting into one sorted list conflict over nothing.
import { proofLensIslandColors } from './ui/proof-lens.js';
import {
  ObservationsClient,
  ObservationsUnavailable,
  consentSentence,
  type ObservationGraph,
} from './observations-api.js';
import { PersonReviewApi, ReviewUnavailable } from './person-review-api.js';
import { writePreferences, type AtlasPreferences } from './preferences.js';
import type { ActiveWorldStylePreview } from './world-style-api.js';
import { worldStyleProposalInbox } from './world-style-proposals.js';
import {
  applyDocumentAppearance,
  applyDocumentWorldStyle,
  themeForPreferences,
} from './theme.js';
import {
  companionAppearanceConfiguration,
  readSourceLight,
  sourceLightParameters,
  worldArtProfile,
} from '@exulanica/presentation';
import {
  commandForKeystroke,
  initialWorldShell,
  updateWorldShell,
  type WorldShellEvent,
} from './world-shell.js';
import {
  describeWorldStyleFailure,
  preferencesForWorldReference,
  preferencesForWorldVersion,
  presentWorldStyleAuthority,
  syncWorldStyleConnection,
  worldStylePreviewMatches,
} from './composition/appearance.js';
import {
  mountSessionGeometry,
  openAppSession,
  reconstructionRungsFor,
  reconstructionsOf,
} from './composition/session-and-geometry.js';
import { createAppEnvironment, createSessionState } from './composition/session-state.js';

const env = createAppEnvironment();
const state = createSessionState();
const {
  shell,
  canvas,
  browserMeasurement,
  systemAppearance,
  systemReducedMotion,
  preview,
  previewArtProfile,
} = env;

let atlas: MountedAtlas | null = null;
let stopWatching: (() => void) | null = null;
let mountedCompanionStage: CompanionStage | null = null;
let settingsStylePreviewId: string | null = null;

/**
 * Whether the proof lens is switched on, for this session only.
 *
 * Not a preference and not persisted. The lens is a way of looking at what is already on screen,
 * and a stored one would change what a visitor sees on arrival on the strength of something they
 * did once. It is also the reason this is a plain variable rather than renderer state: switching
 * it writes one uniform per region and nothing else.
 */
let proofLensEnabled = false;
/**
 * Which photograph the review panel is currently about, so a late answer cannot land on another.
 *
 * Not cached, unlike the observation graph below. An accepted pose receipt is immutable and
 * re-reading it says nothing new; a review is the opposite, since every button in it writes a
 * receipt that changes what the next read returns.
 */
let reviewCaptureId_: string | null = null;

/** One scene's recorded observation graph, cached for the session. See `observations-api.ts`. */
let observationGraph_: ObservationGraph | null = null;
let observationGraphSceneId_: string | null = null;
let observationLoad_: Promise<void> | null = null;

let stopWorldStyleProposalInbox: (() => void) | null = null;

window.addEventListener('pagehide', () => state.sourceMediaSession?.dispose(), { once: true });
systemReducedMotion.addEventListener('change', (event) => {
  atlas?.binding.setReducedMotion(event.matches);
});
applyDocumentAppearance(state.preferences, systemAppearance.matches);
/**
 * Window listeners belonging to the current mount.
 *
 * `mount` runs again after every committed write and again on a hot reload, and a listener added
 * without one of these survives the mount that added it. Two of them turn one key press into two
 * toggles, which is a summon immediately undone by a dismiss and looks exactly like a key that
 * does nothing.
 */
let mountListeners: AbortController | null = null;
let indexFacets: IndexFacets = decodeFacets(window.location.search);
let selected: string | null = null;
/** Monotonic, so two proposals in one session never share an id. Not a clock and not random. */
let issued = 0;
document.title = applicationTitle(preview);
applyDocumentWorldStyle(previewArtProfile ?? worldArtProfile(
  state.preferences.worldArtProfile,
  state.preferences.worldArtProfileVersion,
  state.preferences.worldStyleParameters,
));

void boot().catch((error: unknown) => {
  canvas.hidden = true;
  shell.setAttribute('data-world-state', 'error');
  replace(shell, [buildStartupState(error)]);
});

async function boot(): Promise<void> {
  replace(shell, [buildStartupState()]);
  if (preview) {
    await start('');
    return;
  }
  const token = developmentToken();
  if (token === null) {
    askForToken();
    return;
  }
  await start(token);
}

/**
 * The credential prompt.
 *
 * There is no account system to sign in to. `exulanica/api/authorisation.py` says so plainly, and
 * this asks for the bearer token the operator configured rather than inventing a registration
 * flow a config module has no business deciding. Nothing is stored: the value goes to the
 * transport and is not written to storage, a cookie or the URL.
 */
function askForToken(): void {
  const form = el('form', { class: 'gate' });
  const input = el('input', {
    type: 'password',
    autocomplete: 'off',
    'aria-label': 'Access token',
    placeholder: 'Access token',
  });
  const failure = el('p', { class: 'gate-failure' });
  failure.hidden = true;

  form.append(
    el('h1', { text: 'Exulanica' }),
    el('p', { class: 'gate-note' }, [
      'This instance authenticates with a bearer token the operator configures. There is no ' +
        'account system, no registration and no password reset. The token is held for this tab ' +
        'only and is never stored.',
    ]),
    input,
    el('button', { type: 'submit', class: 'primary', text: 'Open the library' }),
    failure,
  );
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    failure.hidden = true;
    void start(input.value.trim()).catch((error: unknown) => {
      failure.hidden = false;
      failure.textContent =
        error instanceof ApiError && error.isUnauthenticated
          ? 'That token is not configured on this instance.'
          : error instanceof Error
            ? error.message
            : 'the request failed';
    });
  });
  replace(shell, [form]);
  input.focus();
}

async function start(token: string): Promise<void> {
  await openAppSession(env, state, token);
  await mount();
}
async function mount(): Promise<void> {
  const current = state.snapshot;
  const currentSession = state.session;
  const currentEvidence = state.evidence;
  const currentCredentials = state.credentials;
  const currentCompanion = state.companionEngine;
  if (
    current === null ||
    currentSession === null ||
    currentEvidence === null ||
    currentCredentials === null ||
    currentCompanion === null
  ) {
    return;
  }

  // Geometry, re-read here rather than once at start-up. See `loadGeometry`: the list is what
  // carries a deletion to the renderer, and the bytes are not re-fetched. The preview fills the
  // same slot from disk and must not be overwritten by a route it does not serve.
  await mountSessionGeometry({
    env, state, credentials: currentCredentials, snapshot: current,
  });

  // The turn engine outlives a re-mount, so it is told about the new graph rather than rebuilt.
  // Rebuilding it would discard the memory of what has already been asked, and the Companion
  // would open every refresh by asking the question the user just answered.
  currentCompanion.observeSnapshot(current);

  const emptyWorld = buildEmptyWorld(current);
  if (emptyWorld !== null) {
    // An in-session withdrawal can arrive after a populated world was mounted. Stop every owner
    // of that field before replacing its DOM so neither geometry nor input remains live offscreen.
    mountedCompanionStage?.dispose();
    mountedCompanionStage = null;
    stopWatching?.();
    stopWatching = null;
    mountListeners?.abort();
    mountListeners = null;
    atlas?.dispose();
    atlas = null;
    settingsStylePreviewId = null;
    canvas.hidden = true;
    shell.setAttribute('data-world-state', 'empty');
    replace(shell, [emptyWorld]);
    return;
  }
  canvas.hidden = false;
  shell.removeAttribute('data-world-state');

  const built = buildScene(
    current,
    1,
    new Map(),
    new Map(),
    reconstructionsOf(state, state.pointMaps, state.placedPointMaps),
  );
  // A graph write remounts every surface. Stop the previous field before replacing its node, or
  // its frame loop and observers would survive invisibly for the rest of the session.
  mountedCompanionStage?.dispose();
  const stage = el('div', { class: 'stage' });
  const companionStage = buildCompanionStage({ parent: stage });
  const companionAppearance = (): ReturnType<typeof companionAppearanceConfiguration> =>
    companionAppearanceConfiguration({
      body: state.preferences.companionBody,
      color: state.preferences.companionColor,
      face: state.preferences.companionFace,
    });
  companionStage.setAppearance(companionAppearance());
  mountedCompanionStage = companionStage;
  const firstUse = createFirstUseGuidance(window.localStorage);
  let inputMode: FirstUseMode = 'converse';
  let reflectFirstUse = (): void => undefined;
  const finishFirstUse = (): void => {
    if (firstUse.complete()) reflectFirstUse();
  };

  function reflectTurnState(turn: Turn | null): void {
    if (turn === null || turn.intent === 'acknowledge') {
      companionStage.setState('resting');
      return;
    }
    if (turn.intent === 'enrich_relation') {
      companionStage.setState('attending');
      return;
    }
    // Identity, continuity, and contradiction turns all exist because the graph is unresolved.
    companionStage.setState('uncertain');
  }

  const confirm = buildConfirm({
    onConfirm: (proposalId) => void commit(proposalId),
    onCancel: (proposalId) => {
      currentSession.discard(proposalId);
      confirm.hide();
    },
    onVisibilityChange: (visible) => companionPanel.setConfirming(visible),
  });

  // The Companion. The controller holds the turn, the panel renders it, and the confirmation
  // surface built above is the only thing either of them can reach that writes.
  //
  // `askQuestion` is the read half: free text the parser cannot turn into a change is a question
  // about the library, and this is the only place holding the credential it takes to ask one.
  const companionAsk = new CompanionAskClient(currentCredentials);
  const companionController = createCompanionController({
    companion: currentCompanion,
    askQuestion: (question) => companionAsk.ask(question),
    onWorking: (working) => companionStage.setState(working ? 'working' : 'attending'),
    onAwaitingConfirmation: (proposalId, summary, utterance) => {
      // A staged proposal is still unconfirmed. It may not borrow the settled presentation.
      companionStage.setState('uncertain');
      confirm.show(proposalId, summary, utterance);
    },
  });
  function dismissCompanion(): void {
    companionController.dismiss();
    companionStage.setState('resting');
    companionStage.hide();
    reflectShell();
  }
  const companionPanel = buildCompanionEncounter({
    onSelect: (optionId) => {
      companionController.select(optionId);
      reflectTurnState(companionController.current());
      finishFirstUse();
    },
    onSubmit: (optionIds) => {
      companionController.submit(optionIds);
      reflectTurnState(companionController.current());
      finishFirstUse();
    },
    onEvidence: (index) => {
      const handle = companionController.evidenceAt(index);
      if (handle !== null) void currentEvidence.open(handle);
    },
    onSay: (text) => {
      companionController.say(text);
      reflectTurnState(companionController.current());
      finishFirstUse();
    },
  });
  companionController.attach(companionPanel);

  let shellState = initialWorldShell();
  const returnFocus: Array<HTMLElement | null> = [];
  let reflectShell = (): void => undefined;
  const dispatchShell = (event: WorldShellEvent): void => {
    const priorDepth = shellState.returnStack.length;
    const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const next = updateWorldShell(shellState, event);
    const nextDepth = next.returnStack.length;

    if (nextDepth > priorDepth) {
      returnFocus.push(active);
    }

    let restore: HTMLElement | null = null;
    while (returnFocus.length > nextDepth) restore = returnFocus.pop() ?? null;

    shellState = next;
    reflectShell();

    if (restore !== null) {
      window.setTimeout(() => {
        if (
          restore?.isConnected === true &&
          restore.closest('[inert]') === null &&
          restore.getClientRects().length > 0
        ) {
          restore.focus({ preventScroll: true });
        }
      });
    }
  };

  const travelStatus = el('p', {
    class: 'travel-status',
    role: 'status',
    'aria-live': 'polite',
  });
  travelStatus.hidden = true;
  let travelStatusTimer: number | null = null;
  const showTravelStatus = (message: string, kind: 'progress' | 'failure' = 'progress'): void => {
    if (travelStatusTimer !== null) window.clearTimeout(travelStatusTimer);
    travelStatus.textContent = message;
    travelStatus.dataset['kind'] = kind;
    travelStatus.hidden = false;
    travelStatusTimer = window.setTimeout(() => {
      travelStatus.hidden = true;
      travelStatusTimer = null;
    }, kind === 'failure' ? 5200 : 3200);
  };
  const travelUsesReducedMotion = (): boolean =>
    state.preferences.transition === 'fade' ||
    (state.preferences.transition === 'system' && systemReducedMotion.matches);

  const detail = buildDetail(currentEvidence, {
    onClose: () => dispatchShell({ type: 'close-detail' }),
    onName: (occurrence) => propose(occurrence, confirm),
    onEvidenceOpened: (anchorId) => {
      // 5.2: the written claim and the spatial world point at the same evidence at the same
      // moment. Focusing the anchor is the spatial half of that one gesture.
      if (anchorId === null || atlas === null) return;
      const index = atlas.binding.table.indexOf.get(anchorId as never);
      if (index !== undefined) atlas.binding.focusAnchor(index);
    },
    onLocate: (targetAnchorId, targetIslandId) => {
      const binding = atlas?.binding;
      if (binding === undefined) {
        showTravelStatus('The Atlas is still forming. Try again in a moment.', 'failure');
        return;
      }
      const resolution = targetAnchorId === null
        ? binding.navigateToIsland(toIslandId(targetIslandId), travelUsesReducedMotion())
        : binding.navigateToAnchor(toAnchorId(targetAnchorId), travelUsesReducedMotion());
      if (!resolution.ok) {
        const message = {
          'unknown-target': 'That source is not in this Atlas.',
          'outside-resident-field': 'That region is outside the resident field.',
          'no-safe-surface': 'No safe arrival point is available near that source. Open Map to approach its region.',
          occluded: 'That source is present, but no clear arrival point is available.',
        }[resolution.reason];
        showTravelStatus(message, 'failure');
        return;
      }
      dispatchShell({ type: 'show-world' });
      showTravelStatus(travelUsesReducedMotion() ? 'Located the source.' : 'Moving to the source…');
    },
  }, {
    preview,
    ...(state.previewSourceMedia === undefined ? {} : { sourceMedia: state.previewSourceMedia }),
  });

  const regionPoints = built.scene.islands.map((island) => ({
    islandId: island.islandId,
    x: island.placement.position.x,
    z: island.placement.position.z,
  }));
  const minimap = buildRegionPlan(regionPoints, { viewer: true, className: 'region-minimap' });
  minimap.render(new Set(), null);
  const worldIndex = buildWorldIndex({
    onEntity: (entityId, activation) => {
      selected = entityId;
      const entity = current.entities.find((e) => e.entityId === entityId);
      if (entity !== undefined) {
        detail.showEntity(current, entity);
        dispatchShell({ type: 'show-detail', id: entityId });
      }
      worldIndex.render(current, indexFacets, selected);
      if (activation === 'keyboard') {
        window.setTimeout(() => detail.root.querySelector<HTMLElement>('button')?.focus(), 0);
      }
    },
    onOccurrence: (occurrenceId, activation) => {
      selected = occurrenceId;
      const occurrence = current.occurrences.find((o) => o.occurrenceId === occurrenceId);
      if (occurrence !== undefined) {
        detail.showOccurrence(occurrence);
        dispatchShell({ type: 'show-detail', id: occurrenceId });
      }
      worldIndex.render(current, indexFacets, selected);
      if (activation === 'keyboard') {
        window.setTimeout(() => detail.root.querySelector<HTMLElement>('button')?.focus(), 0);
      }
    },
    onSearch: (text) => {
      indexFacets = Object.freeze({ ...indexFacets, text });
      worldIndex.render(current, indexFacets, selected);
    },
    onFacets: (next) => {
      indexFacets = next;
      syncIndexRoute(next);
      worldIndex.render(current, indexFacets, selected);
    },
    onClose: () => dispatchShell({ type: 'toggle-index' }),
  }, {
    preview,
    // Placements come from the scene, not the graph: the index reads where the world already put
    // these regions rather than deciding it a second time.
    regions: regionPoints,
  });

  // The canvas stays where the document put it: fixed, behind everything, outside the shell.
  // Moving it into the shell would put it in the shell's stacking context, where it paints over
  // the rail. The stage is the hole it shows through and the parent the anchor overlay writes
  // its nodes into, which is a different job from being the canvas.
  const forming = buildFormation();
  const chrome = buildWorldChrome(shell);
  const handleAtlasCommand = (command: AtlasCommand): void => {
    if (companionPanel.state() === 'open') dismissCompanion();
    if (command === 'index') dispatchShell({ type: 'toggle-index' });
    else if (command === 'map') dispatchShell({ type: 'toggle-map' });
    else if (command === 'options') dispatchShell({ type: 'toggle-options' });
    else dispatchShell({ type: 'toggle-controls' });
  };
  const commandBar = buildAtlasCommands(handleAtlasCommand);
  const mapPeek = new MapPeek({
    isMapActive: () => shellState.camera === 'map',
    enterMap: () => dispatchShell({ type: 'toggle-map' }),
    leaveMap: () => dispatchShell({ type: 'toggle-map' }),
    toggleMap: () => handleAtlasCommand('map'),
    schedule: (run, ms) => window.setTimeout(run, ms),
    cancel: (handle) => window.clearTimeout(handle),
  });
  reflectFirstUse = (): void => {
    companionPanel.setFirstUsePrompt(firstUse.prompt(inputMode));
    shell.dataset['firstUse'] = firstUse.phase();
  };
  reflectFirstUse();
  const mapReturn = el('button', { type: 'button', text: 'Return  M' });
  mapReturn.addEventListener('click', () => handleAtlasCommand('map'));
  const mapCaption = el('section', {
    class: 'map-caption',
    'aria-label': 'Atlas Map orientation',
  }, [
    el('strong', { text: 'Atlas Map' }),
    el('span', { text: MAP_ORIENTATION_CAPTION }),
    mapReturn,
  ]);
  mapCaption.hidden = true;
  const viewportBoundary = el('aside', {
    class: 'viewport-boundary',
    'aria-labelledby': 'viewport-boundary-title',
  }, [
    el('p', { class: 'overlay-kicker', text: 'Atlas boundary' }),
    el('h1', { id: 'viewport-boundary-title', text: 'A wider view is required' }),
    el('p', {
      text:
        'This Atlas prototype is designed for laptop and desktop windows. ' +
        'Widen this window to at least 60rem to continue.',
    }),
  ]);
  let optionsView: ReturnType<typeof buildOptions>;
  let serverPreviewTimer: number | null = null;
  let previewSequence = 0;

  const reflectLocalWorldPreview = (
    candidate: AtlasPreferences,
    origin: 'settings' | 'companion' = 'settings',
  ): boolean => {
    if (atlas === null) return false;
    const styleChanged = candidate.worldArtProfile !== state.preferences.worldArtProfile ||
      candidate.worldArtProfileVersion !== state.preferences.worldArtProfileVersion ||
      JSON.stringify(candidate.worldStyleParameters) !==
        JSON.stringify(state.preferences.worldStyleParameters);
    if (!styleChanged) return false;
    if (settingsStylePreviewId !== null) {
      atlas.binding.discardArtProfilePreview(settingsStylePreviewId);
      settingsStylePreviewId = null;
    }
    const candidateProfile = worldArtProfile(
      candidate.worldArtProfile,
      candidate.worldArtProfileVersion,
      candidate.worldStyleParameters,
    );
    const previewSession = atlas.binding.previewArtProfile(
      candidateProfile,
      origin,
      candidate.worldStyleParameters,
    );
    if (!previewSession.validation.ok) return false;
    settingsStylePreviewId = previewSession.sessionId;
    applyDocumentWorldStyle(candidateProfile);
    return true;
  };

  const previewOnServer = async (candidate: AtlasPreferences): Promise<ActiveWorldStylePreview | null> => {
    const client = state.worldStyles;
    if (client === null) {
      optionsView.reportWorldLifecycle(
        'failed',
        state.worldStyleFailure ?? 'World style authority is unavailable. This preview cannot be saved.',
      );
      return null;
    }
    const sequence = ++previewSequence;
    optionsView.reportWorldLifecycle('checking');
    try {
      const active = await client.previewSettings({
        profileId: candidate.worldArtProfile,
        profileVersion: candidate.worldArtProfileVersion,
        parameters: candidate.worldStyleParameters,
      });
      if (sequence === previewSequence) {
        syncWorldStyleConnection(state, client);
        presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, active);
        optionsView.reportWorldLifecycle(
          active.recoveredFromStale ? 'stale' : 'ready',
        );
      }
      return active;
    } catch (error) {
      if (sequence === previewSequence) {
        optionsView.reportWorldLifecycle('failed', describeWorldStyleFailure(error));
      }
      return null;
    }
  };

  const queueServerPreview = (candidate: AtlasPreferences): void => {
    if (serverPreviewTimer !== null) window.clearTimeout(serverPreviewTimer);
    serverPreviewTimer = window.setTimeout(() => {
      serverPreviewTimer = null;
      void previewOnServer(candidate);
    }, 220);
  };

  optionsView = buildOptions({
    preferences: state.preferences,
    onChange: applyPreferences,
    /*
     * The person's own photographs, read as four control positions.
     *
     * It samples the blob URLs the renderer already holds rather than fetching again, so no extra
     * authorized request is made for a colour, and it returns values rather than applying them:
     * the existing preview and Apply own the change exactly as they do for a slider.
     */
    onReadSourceLight: async () => {
      const catalog = state.previewSourceMedia;
      if (catalog === undefined) return null;
      const sources = [...catalog.values()]
        .filter((entry) => entry.available && entry.url !== null)
        .map((entry) => ({ url: entry.url as string, available: true }));
      if (sources.length === 0) return null;
      const { sampleSources } = await import('./media-sampler.js');
      const reading = readSourceLight(await sampleSources(sources));
      if (reading.sampled === 0) return null;
      return sourceLightParameters(reading, state.preferences.worldStyleParameters);
    },
    onPreview: (candidate) => {
      shell.setAttribute('data-vignette', candidate.vignette);
      atlas?.binding.setFieldOfView(candidate.fieldOfView);
      atlas?.binding.setSensitivityMultiplier(candidate.mouseSensitivity);
      if (reflectLocalWorldPreview(candidate)) queueServerPreview(candidate);
    },
    onWorldDiscard: (restored) => {
      if (serverPreviewTimer !== null) {
        window.clearTimeout(serverPreviewTimer);
        serverPreviewTimer = null;
      }
      previewSequence += 1;
      if (settingsStylePreviewId !== null && atlas !== null) {
        atlas.binding.discardArtProfilePreview(settingsStylePreviewId);
        settingsStylePreviewId = null;
      }
      applyDocumentWorldStyle(previewArtProfile ?? worldArtProfile(
        restored.worldArtProfile,
        restored.worldArtProfileVersion,
        restored.worldStyleParameters,
      ));
      const client = state.worldStyles;
      if (client !== null) {
        void client.discardActive().then(() => {
          syncWorldStyleConnection(state, client);
          presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, null);
          optionsView.reportWorldLifecycle('idle');
        }).catch((error) => optionsView.reportWorldLifecycle(
          'failed', describeWorldStyleFailure(error),
        ));
      }
    },
    onWorldApply: async (candidate) => {
      if (serverPreviewTimer !== null) {
        window.clearTimeout(serverPreviewTimer);
        serverPreviewTimer = null;
      }
      const client = state.worldStyles;
      if (client === null) {
        optionsView.reportWorldLifecycle(
          'failed',
          state.worldStyleFailure ?? 'World style authority is unavailable. No durable change was made.',
        );
        return false;
      }
      const existing = client.activePreview();
      const active = existing !== null && worldStylePreviewMatches(existing, candidate)
        ? existing
        : await previewOnServer(candidate);
      if (active === null) return false;
      optionsView.reportWorldLifecycle('checking', 'Applying the reviewed preview…');
      try {
        const result = await client.applyActive();
        syncWorldStyleConnection(state, client);
        if (result.kind === 'stale-recovered') {
          presentWorldStyleAuthority(
            optionsView, state.worldStyleConnection, state.worldStyleFailure, result.preview,
          );
          optionsView.reportWorldLifecycle('stale');
          return false;
        }
        presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, null);
        optionsView.reportWorldLifecycle('saved');
        return true;
      } catch (error) {
        optionsView.reportWorldLifecycle('failed', describeWorldStyleFailure(error));
        return false;
      }
    },
    onWorldRollback: async (targetVersionId) => {
      const client = state.worldStyles;
      if (client === null) {
        optionsView.reportWorldLifecycle(
          'failed', state.worldStyleFailure ?? 'World style authority is unavailable.',
        );
        return null;
      }
      optionsView.reportWorldLifecycle('checking', 'Restoring the selected saved design…');
      try {
        const result = await client.rollback(targetVersionId);
        syncWorldStyleConnection(state, client);
        presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, null);
        if (result.kind === 'stale') {
          const latest = preferencesForWorldVersion(state.preferences, result.state.current);
          applyPreferences(latest);
          optionsView.reportWorldLifecycle(
            'stale',
            'The saved world changed elsewhere. The latest version is shown; choose the restore target again.',
          );
          return null;
        }
        optionsView.reportWorldLifecycle('saved', `Restored as revision ${result.version.revision}.`);
        return preferencesForWorldVersion(state.preferences, result.version);
      } catch (error) {
        optionsView.reportWorldLifecycle('failed', describeWorldStyleFailure(error));
        return null;
      }
    },
    onClose: () => dispatchShell({ type: 'toggle-options' }),
    onShowControls: () => dispatchShell({ type: 'toggle-controls' }),
  });
  presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, null);
  stopWorldStyleProposalInbox?.();
  stopWorldStyleProposalInbox = worldStyleProposalInbox.subscribe(async (proposal) => {
    const client = state.worldStyles;
    if (client === null) {
      optionsView.reportWorldLifecycle(
        'failed',
        state.worldStyleFailure ?? 'World style authority is unavailable. The proposal was not previewed.',
      );
      return;
    }
    if (proposal.scope?.kind === 'region') {
      optionsView.reportWorldLifecycle(
        'failed',
        'Regional style proposals require a regional renderer preview and are not shown as a global change.',
      );
      return;
    }
    try {
      optionsView.reportWorldLifecycle('checking', 'Validating the upstream proposal…');
      const active = await client.previewUpstream(proposal);
      const candidate = preferencesForWorldReference(
        state.preferences,
        active.preview.candidate.globalStyle,
      );
      optionsView.setPreferences(candidate);
      reflectLocalWorldPreview(
        candidate,
        proposal.origin === 'companion' ? 'companion' : 'settings',
      );
      syncWorldStyleConnection(state, client);
      presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, active);
      optionsView.reportWorldLifecycle(active.recoveredFromStale ? 'stale' : 'ready');
    } catch (error) {
      optionsView.reportWorldLifecycle('failed', describeWorldStyleFailure(error));
    }
  });
  const settingsView = buildControlsGuide({
    preferences: state.preferences,
    onChange: applyPreferences,
    onClose: () => dispatchShell({ type: 'toggle-controls' }),
    onShowCustomize: () => dispatchShell({ type: 'toggle-options' }),
  });

  let latestSettingsSave = 0;
  function applyPreferences(next: AtlasPreferences): void {
    const previous = state.preferences;
    state.preferences = next;
    if (settingsStylePreviewId !== null && atlas !== null) {
      atlas.binding.discardArtProfilePreview(settingsStylePreviewId);
      settingsStylePreviewId = null;
    }
    try {
      writePreferences(window.localStorage, state.preferences);
    } catch {
      // Private browsing may refuse storage. The live setting still applies for this session.
    }
    const theme = applyDocumentAppearance(state.preferences, systemAppearance.matches);
    const profile = previewArtProfile ?? worldArtProfile(
      state.preferences.worldArtProfile,
      state.preferences.worldArtProfileVersion,
      state.preferences.worldStyleParameters,
    );
    applyDocumentWorldStyle(profile);
    optionsView.setPreferences(state.preferences);
    settingsView.setPreferences(state.preferences);
    companionStage.setAppearance(companionAppearance());
    shell.setAttribute('data-vignette', state.preferences.vignette);
    atlas?.binding.setTheme(theme);
    // A new theme is a new palette, so a lit lens has to be re-resolved from it. Off stays off.
    applyProofLens();
    atlas?.binding.setArtProfile(
      profile,
      'settings',
      state.preferences.worldStyleParameters,
    );
    atlas?.binding.setFieldOfView(state.preferences.fieldOfView);
    atlas?.binding.setSensitivityMultiplier(state.preferences.mouseSensitivity);
    if (state.interactionPolicies !== null) {
      latestSettingsSave += 1;
      const save = latestSettingsSave;
      optionsView.reportPersistence('saving');
      void state.interactionPolicies
        .syncSettings(previous, state.preferences, systemReducedMotion.matches)
        .then(() => {
          if (save === latestSettingsSave) optionsView.reportPersistence('saved');
        })
        .catch(() => {
          if (save === latestSettingsSave) optionsView.reportPersistence('failed');
        });
    }
  }

  /*
   * THE PROOF LENS AND CLICK-TO-EVIDENCE.
   *
   * Both live here, between the settings block and the inspector, because both need the graph,
   * the theme and the binding at once and this is the only scope that holds all three. The
   * person-consent branch edits neither of the two functions above or below, so this whole region
   * is textually its own.
   */

  /** Which region draws which scene, as the regions themselves already decided. */
  const islandOfScene = (sceneId: string): IslandId | undefined => {
    const region = current.islands.find((island) => island.reconstructionSceneId === sceneId);
    return region === undefined ? undefined : toIslandId(region.islandId);
  };

  /**
   * Push the lens state at the renderer, and push nothing else.
   *
   * Every argument is read fresh: the disclosures the status panel is already showing, the region
   * each scene resolved to, and the current theme. Nothing is stored, no scene is rebuilt, and the
   * one call this makes writes four floats per region.
   */
  const applyProofLens = (): void => {
    atlas?.binding.setProofLens(
      proofLensEnabled
        ? proofLensIslandColors(
            state.reconstructionRungs,
            islandOfScene,
            themeForPreferences(state.preferences, systemAppearance.matches),
          )
        : null,
    );
  };

  /**
   * How far from the cursor, in screen pixels, a recorded point may be and still count as clicked.
   *
   * Expressed in screen pixels and converted to the photograph's own pixels per click, because the
   * two are not the same scale: the inspector fits a 4080-pixel-tall original into a canvas around
   * 700 pixels tall, so eight screen pixels is about forty-five source pixels. A tolerance typed
   * in source pixels would be a different gesture on every display.
   */
  const PICK_TOLERANCE_CANVAS_PX = 8;
  const PICK_OCCLUSION_BAND_CANVAS_PX = 2;

  /** The raw recovered camera for one capture: the frame the observation graph is recorded in. */
  const pickCameraFor = (sceneId: string, captureId: string): PickCamera | null => {
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const camera = record?.members.find((member) => member.captureId === captureId)?.recoveredCamera;
    if (camera == null) return null;
    /*
     * THE RAW TRANSFORM, NOT THE DISPLAYED ONE, and the difference is the whole correctness of
     * this gesture. `geometry-api.ts` composes each scene's display frame into the cameras it
     * hands the renderer, so the scene stands upright and at walking scale; the observation
     * graph's world coordinates are the recovered COLMAP frame and are not composed with
     * anything. Projecting one through the other would be a silent, plausible-looking error.
     *
     * Either pair would in fact agree, because a similarity applied to both a camera and a point
     * cancels in the projection. Using the recorded pair is still the right choice: it is the one
     * that stays correct if the display frame ever stops being a similarity, and it is the pair
     * whose agreement was measured. Against this scene on 2026-09-06, reprojecting every retained
     * observation of the first photograph through this transform reproduced COLMAP's own recorded
     * pixel to a median of 2.8 px and a maximum of 9.9 px on a 3060x4080 original, which is the
     * SIMPLE_RADIAL distortion that `pinhole-approximation` says it is dropping.
     */
    return {
      sceneFromCameraRowMajor: camera.sceneFromCameraRowMajor,
      calibration: camera.calibration,
      projection: camera.projection,
    };
  };

  /**
   * Load the scene's recorded observation graph once, when the inspector opens on it.
   *
   * Started on open rather than on the first click so the answer is ready when a visitor asks:
   * the real bowl scene's graph is about 53 MB of JSON. Cached by scene id for the session,
   * because an accepted pose receipt is immutable and re-reading it could not say anything new.
   */
  const loadObservations = (sceneId: string): void => {
    if (observationGraphSceneId_ === sceneId && (observationGraph_ !== null || observationLoad_ !== null)) return;
    const where = state.credentials;
    if (where === null) {
      reconstructionInspector.showEvidence({
        kind: 'failed', reason: 'This session has no credentials to read the observation graph with.',
      });
      return;
    }
    observationGraphSceneId_ = sceneId;
    observationGraph_ = null;
    reconstructionInspector.showEvidence({ kind: 'loading' });
    observationLoad_ = new ObservationsClient(where).load(sceneId).then((graph) => {
      if (observationGraphSceneId_ !== sceneId) return;
      observationGraph_ = graph;
      reconstructionInspector.showEvidence({
        kind: 'ready', pointCount: graph.points.length, retainedPerImage: graph.retainedPerImage,
      });
    }).catch((error: unknown) => {
      if (observationGraphSceneId_ !== sceneId) return;
      reconstructionInspector.showEvidence({
        kind: 'failed',
        reason: error instanceof ObservationsUnavailable
          ? error.message
          : 'The recorded observation graph could not be read.',
      });
    }).finally(() => {
      if (observationGraphSceneId_ === sceneId) observationLoad_ = null;
    });
  };

  /** What one capture's original looks like in this session, through its own evidence handles. */
  /**
   * Load who is in the photograph this view stands on, and let a reviewer answer.
   *
   * Called on every view change, including with null, because the panel is about ONE photograph
   * and leaving the previous one on screen would offer buttons that write receipts against a
   * capture the visitor has already left. `reviewCaptureId_` is the guard: a slow answer for the
   * previous photograph is dropped rather than rendered.
   *
   * Every action refetches instead of patching the panel in place. One receipt can move more than
   * the row it was written against, because a subject can be bound to several regions and the
   * resolved state is a fold over all of that subject's receipts; a client that edited one row
   * would be a second implementation of a rule the server already owns.
   */
  const manualDrafts = new PersonRegionDrafts();
  let reviewGeneration = 0;
  const loadPersonReview = (captureId: string | null): void => {
    const generation = ++reviewGeneration;
    reconstructionInspector.showReview(null);
    reviewCaptureId_ = captureId;
    if (captureId === null) {
      reconstructionInspector.showReview(null);
      return;
    }
    const where = state.credentials;
    if (where === null) {
      reconstructionInspector.showReview(
        el('p', { text: 'This session has no credentials to read who is in this photograph.' }),
      );
      return;
    }
    const api = new PersonReviewApi(where);
    const act = (run: () => Promise<unknown>): void => {
      void run()
        .then(() => { if (reviewCaptureId_ === captureId && generation === reviewGeneration) loadPersonReview(captureId); })
        .catch((error: unknown) => {
          if (reviewCaptureId_ !== captureId || generation !== reviewGeneration) return;
          reconstructionInspector.showReview(el('p', {
            class: 'person-review-failed',
            text: error instanceof ReviewUnavailable
              ? error.message
              : 'That review edit was not recorded.',
          }));
        });
    };
    void api.load(captureId).then((review) => {
      // Dropped rather than drawn: the visitor has moved to another photograph since this asked.
      if (reviewCaptureId_ !== captureId || generation !== reviewGeneration) return;
      reconstructionInspector.showReview(buildPersonReview({
        captureId: review.captureId,
        reviewState: review.reviewState,
        regions: review.regions,
        onReload: () => loadPersonReview(captureId),
        editor: {
          captureId, source: sourceForCapture(captureId), drafts: manualDrafts,
          isCurrent: () => reviewCaptureId_ === captureId && generation === reviewGeneration
            && reconstructionInspector.selected?.captureId === captureId,
          onAdd: async (region) => {
            // Reconcile an uncertain previous response before writing another receipt.
            const latest = await api.load(captureId);
            if (!latest.regions.some((item) => item.regionKey === region.region_key)) {
              await api.add(captureId, region);
            }
          },
        },
        onConfirm: (regionKey) => act(() =>
          api.edit(captureId, { region_key: regionKey, action: 'confirm' })),
        onDelete: (regionKey) => act(() =>
          api.edit(captureId, { region_key: regionKey, action: 'delete' })),
        onConsent: (regionKey, scope, decision) => {
          const region = review.regions.find((item) => item.regionKey === regionKey);
          if (region === undefined) return;
          act(() => api.consent(captureId, region, scope, decision));
        },
      }));
    }).catch((error: unknown) => {
      if (reviewCaptureId_ !== captureId || generation !== reviewGeneration) return;
      reconstructionInspector.showReview(el('p', {
        class: 'person-review-failed',
        text: error instanceof ReviewUnavailable
          ? error.message
          : 'Who is in this photograph could not be read.',
      }));
    });
  };

  const sourceForCapture = (captureId: string) =>
    [...(state.previewSourceMedia?.values() ?? [])].find((descriptor) =>
      descriptor.captureIds?.includes(captureId))
    ?? current.occurrences
      .filter((occurrence) => occurrence.captureId === captureId)
      .flatMap((occurrence) => occurrence.evidence)
      .map((handle) => state.previewSourceMedia?.get(handle))
      .find((descriptor) => descriptor !== undefined) ?? null;

  /**
   * One click in the inspector, resolved to the photographs that observed that piece of the world.
   *
   * The answer is recorded provenance and nothing else: the point is one COLMAP actually stored,
   * and the photographs listed are the ones whose observations of it were retained. Nothing here
   * reprojects the point into other cameras to ask which of them could have seen it, because that
   * is a geometric guess about visibility rather than a record of an observation.
   */
  const resolveEvidenceAt = (clientX: number, clientY: number): void => {
    const view = atlas?.binding.inspectionView ?? null;
    if (view === null) return;
    const captureId = view.captureIds[0];
    if (view.kind !== 'source-camera' || view.calibration === null || captureId === undefined) {
      reconstructionInspector.showEvidence({
        kind: 'unsupported',
        reason: view.kind === 'between-cameras'
          ? 'This is a midpoint between two photographs, not a photograph. No camera stood here, '
            + 'so there is no calibrated projection to invert. Choose either adjacent source camera.'
          : 'This view has no accepted calibration, so a click cannot be inverted exactly.',
      });
      return;
    }
    const graph = observationGraph_;
    if (graph === null) {
      if (observationLoad_ === null) loadObservations(view.sceneId);
      return;
    }
    const camera = pickCameraFor(view.sceneId, captureId);
    if (camera === null) {
      reconstructionInspector.showEvidence({
        kind: 'unsupported',
        reason: 'This session holds no recovered camera for that photograph.',
      });
      return;
    }
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const cursor = canvasToSourcePixel(
      camera.calibration,
      { width: rect.width, height: rect.height },
      { x: clientX - rect.left, y: clientY - rect.top },
    );
    const sourcePxPerCanvasPx = camera.calibration.height / rect.height;
    const tolerancePx = PICK_TOLERANCE_CANVAS_PX * sourcePxPerCanvasPx;
    const result = pickObservedPoint(camera, graph.points, cursor, {
      tolerancePx,
      occlusionBandPx: PICK_OCCLUSION_BAND_CANVAS_PX * sourcePxPerCanvasPx,
    });
    if (result === null) {
      reconstructionInspector.showEvidence({
        kind: 'miss', toleranceSourcePx: tolerancePx, canvasPx: PICK_TOLERANCE_CANVAS_PX,
      });
      return;
    }
    const observedBy = graph.observedBy.get(result.point.pointId) ?? [];
    reconstructionInspector.showEvidence({
      kind: 'hit',
      // Verbatim from atlas-core. It is the sentence that must state both the full track length
      // and the retained count whenever they differ, and rewording it here is how they diverge.
      sentence: observationSentence(result),
      pointId: result.point.pointId,
      pixelDistance: result.pixelDistance,
      // The POINT's mean residual over its whole track, which is what the receipt records: the
      // pose stage copies `points3D.txt` field 7 onto every row of a track, so all of these are
      // the same number and it belongs to the point, not to any one photograph.
      meanReprojectionErrorPx: observedBy[0]?.reprojectionErrorPx ?? 0,
      projection: result.projection,
      photographs: observedBy.map((observation, index) => {
        const source = sourceForCapture(observation.captureId);
        return {
          captureId: observation.captureId,
          title: source?.title ?? null,
          label: `Photograph ${String(index + 1)}`,
          url: source?.url ?? null,
          alt: source?.alt ?? 'An authorized original photograph.',
          available: source?.available === true && source.url !== null,
          x: observation.x,
          y: observation.y,
          consentSentence: consentSentence(observation.consent),
        };
      }),
    });
  };

  const reconstructionInspector = buildReconstructionInspector({
    onView: (sceneId, viewId) => atlas?.binding.inspectSceneView(sceneId, viewId) ?? false,
    onReturn: () => { loadPersonReview(null); atlas?.binding.endSceneInspection(); },
    // The world canvas is aria-hidden, so the click has to have a real button beside it or the
    // gesture exists only for sighted mouse users.
    onResolveCentre: () => {
      const rect = canvas.getBoundingClientRect();
      resolveEvidenceAt(rect.left + rect.width / 2, rect.top + rect.height / 2);
    },
    onViewShown: (sceneId, view) => {
      // A new view is a new projection, so the previous pick no longer describes what is on
      // screen. The panel goes back to saying what a click could resolve rather than keeping an
      // answer about a camera the visitor has left.
      // The review is about a photograph, so it follows the view that stands on one and is
      // cleared by every view that does not. Called before the early return below for exactly
      // that reason: a midpoint between two cameras must not keep the previous photograph's
      // people on screen with buttons that write receipts against it.
      loadPersonReview(view.captureId ?? null);
      if (view.kind !== 'source-camera' || view.projection === 'opm-estimate') {
        reconstructionInspector.showEvidence({
          kind: 'unsupported',
          reason: view.kind === 'between-cameras'
            ? 'This is a midpoint between two photographs. No camera stood here, so there is no '
              + 'calibrated projection to invert. Choose either adjacent source camera.'
            : 'This view has no accepted calibration, so a click cannot be inverted exactly.',
        });
        return;
      }
      loadObservations(sceneId);
      const graph = observationGraph_;
      if (graph !== null && observationGraphSceneId_ === sceneId) {
        reconstructionInspector.showEvidence({
          kind: 'ready', pointCount: graph.points.length, retainedPerImage: graph.retainedPerImage,
        });
      }
    },
  });
  const inspectReconstruction = (sceneId: string): void => {
    dispatchShell({ type: 'show-world' });
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const views = atlas?.binding.inspectionViews(sceneId) ?? [];
    let cameraNumber = 0;
    const choices = views.map((view) => {
      const member = view.kind === 'source-camera'
        ? record?.members.find((candidate) => candidate.captureId === view.captureIds[0]
          || (view.captureIds.length === 0 && candidate.placement?.artifactId === view.artifactIds[0]))
        : undefined;
      if (view.kind === 'source-camera') cameraNumber += 1;
      // World source IDs name topology slots, not captures. Join through the actual evidence
      // handles of this capture; matching a generated source ID to a capture ID loses every source.
      const source = member === undefined ? null :
        [...(state.previewSourceMedia?.values() ?? [])].find((descriptor) =>
          descriptor.captureIds?.includes(member.captureId))
        ?? current.occurrences
          .filter((occurrence) => occurrence.captureId === member.captureId)
          .flatMap((occurrence) => occurrence.evidence)
          .map((handle) => state.previewSourceMedia?.get(handle))
          .find((descriptor) => descriptor !== undefined) ?? null;
      return {
        id: view.id, kind: view.kind, projection: view.projection,
        label: view.kind === 'source-camera'
          ? `Source camera ${cameraNumber}` : `Between cameras ${cameraNumber} and ${cameraNumber + 1}`,
        source,
        // Taken from the member already resolved above rather than from `view.captureIds`, which
        // names topology slots on a source-only view. Null for a midpoint, where no single
        // photograph is being looked at and so no review is about anything.
        captureId: member?.captureId ?? null,
      };
    });
    if (!reconstructionInspector.open(sceneId, choices)) {
      showTravelStatus('No verified reconstruction cameras are available. The original sources remain in Index.', 'failure');
    }
  };
  // Both the availability panel and inspector count the same authorized, deduplicated set.
  const sourcesForScene = (sceneId: string) => {
    const record = current.reconstructionScenes?.find((scene) => scene.sceneId === sceneId);
    const region = current.islands.find((island) => island.islandId === (record?.islandId ?? sceneId));
    const captures = new Set(record?.members.map((member) => member.captureId) ?? region?.captureIds ?? []);
    const regionId = record?.islandId ?? region?.islandId;
    const seen = new Set<string>();
    return [...(state.previewSourceMedia?.values() ?? [])].filter((source) => {
      if (seen.has(source.evidenceRef)) return false;
      if ((regionId === undefined || source.regionId !== regionId)
        && !source.captureIds?.some((id) => captures.has(id))) return false;
      seen.add(source.evidenceRef);
      return true;
    });
  };
  const inspectSceneSources = (sceneId: string): void => {
    atlas?.binding.endSceneInspection();
    dispatchShell({ type: 'show-world' });
    const sources = sourcesForScene(sceneId);
    const choices = sources.map((source, index) => ({
      id: `source:${source.evidenceRef}`, kind: 'source-only' as const,
      label: `Photograph ${index + 1}`, source,
      captureId: source.captureIds?.length === 1 ? source.captureIds[0] ?? null : null,
    }));
    if (!reconstructionInspector.open(sceneId, choices)) {
      showTravelStatus('No authorized source photographs are available in this session.', 'failure');
    }
  };
  const renderedPreviewRegions = new Set<string>();
  const renderReconstructionStatus = (): HTMLElement => buildStatus({
    omittedRegionCount: built.omitted.length, undrawable: built.undrawable,
    notices: [...state.sourceMediaNotices, ...state.geometryNotices], reconstructionScenes: state.reconstructionRungs,
    sourceRegions: current.islands
      .filter((island) => !renderedPreviewRegions.has(island.islandId)
        && !current.reconstructionScenes?.some((scene) => scene.islandId === island.islandId))
      .map((island) => ({ regionId: island.islandId, captureCount: island.captureIds.length })),
    onInspectScene: inspectReconstruction, onInspectSources: inspectSceneSources,
    // The lens switch, last in the input as it is last in the panel. Toggling it calls
    // `applyProofLens` and nothing else: no scene is rebuilt and this panel is not re-rendered,
    // which is what makes "toggling the lens changes no scene, no rung and no receipt" checkable
    // rather than merely asserted.
    proofLens: {
      enabled: proofLensEnabled,
      theme: themeForPreferences(state.preferences, systemAppearance.matches),
      onToggle: (enabled) => {
        proofLensEnabled = enabled;
        applyProofLens();
      },
    },
    ...(sourcePresentation() === 'inspection' ? {
      reconstructionFocus: {
        collections: current.islands.map((island) => {
          const sceneId = current.reconstructionScenes?.find((scene) => scene.islandId === island.islandId)?.sceneId
            ?? island.islandId;
          return { sceneId, sourceCount: sourcesForScene(sceneId).length };
        }),
      },
    } : {}),
  });
  let reconstructionStatus = renderReconstructionStatus();
  replace(shell, [
    stage,
    chrome.reticle,
    worldIndex.root,
    detail.root,
    forming.root,
    companionPanel.root,
    confirm.root,
    commandBar.root,
    mapCaption,
    travelStatus,
    minimap.root,
    optionsView.root,
    settingsView.root,
    viewportBoundary,
    reconstructionInspector.root,
    reconstructionStatus,
  ]);

  reflectShell = (): void => {
    if (shellState.primary !== 'world') {
      atlas?.binding.endSceneInspection();
      reconstructionInspector.hide();
    }
    shell.setAttribute('data-primary', shellState.primary);
    shell.setAttribute('data-camera', shellState.camera);
    chrome.setIndexOpen(shellState.primary === 'index');
    worldIndex.root.inert = shellState.primary !== 'index';
    worldIndex.root.setAttribute('aria-hidden', shellState.primary === 'index' ? 'false' : 'true');
    optionsView.setVisible(shellState.primary === 'options');
    settingsView.setVisible(shellState.primary === 'controls');
    const systemSurfaceOpen = shellState.primary === 'options' || shellState.primary === 'controls';
    const modalBackground = [
      stage,
      worldIndex.root,
      detail.root,
      forming.root,
      companionPanel.root,
      confirm.root,
      mapCaption,
      travelStatus,
    ];
    // On close, release the command bar before the dialog restores focus to its trigger. On open,
    // move focus into the dialog before making that same trigger inert.
    if (!systemSurfaceOpen) for (const surface of modalBackground) surface.inert = false;
    optionsView.setVisible(shellState.primary === 'options');
    settingsView.setVisible(shellState.primary === 'controls');
    if (systemSurfaceOpen) for (const surface of modalBackground) surface.inert = true;
    commandBar.reflect(shellState.primary, shellState.camera);
    mapCaption.hidden = shellState.camera !== 'map';
    // Only while traversing the ground: the Map is already the whole answer, and a plate has the
    // world behind it rather than under it.
    minimap.root.hidden =
      !state.preferences.regionMinimap ||
      shellState.primary !== 'world' ||
      shellState.camera !== 'ground';
    detail.root.hidden = shellState.primary !== 'index' || shellState.detailId === null;
    atlas?.binding.setMapMode(shellState.camera === 'map');
    /*
     * A plate stands in front of the world; it does not replace it. Movement therefore tracks the
     * CAMERA MODE and nothing else: Map and direct travel own the camera, so they stop you, but
     * opening a panel never does. Disabling controls for the system surfaces parked you in place
     * the moment you opened Customize, which is the one surface where walking around while you
     * change the world's appearance is the entire point.
     *
     * Summon keeps its own guard below, so a system surface still cannot call the Companion out
     * from behind itself.
     */
    atlas?.binding.setControlsEnabled(shellState.camera === 'ground');
    // Every surface here takes the cursor. None of them should take your feet with it.
    atlas?.binding.setFreeCursorActive(
      companionPanel.state() === 'open' || shellState.primary !== 'world',
    );
    if (
      (shellState.primary !== 'world' || shellState.camera === 'map') &&
      document.pointerLockElement !== null
    ) {
      document.exitPointerLock();
    }
  };
  shell.setAttribute('data-vignette', state.preferences.vignette);
  reflectShell();

  worldIndex.render(current, indexFacets, selected);
  forming.render(null, null);

  // What there is to watch. There is no upload endpoint yet, so an intake starts from the command
  // line and this asks the API rather than assuming: an empty list renders as nothing forming,
  // which is a true statement, and a fabricated batch would not be.
  stopWatching?.();
  stopWatching = null;
  void listBatches(currentCredentials!).then((batches) => {
    const watching = mostRecentlyStarted(batches);
    if (watching === undefined) return;
    stopWatching = watchBatch(currentCredentials!, watching.batchId, (state) => {
      forming.render(state, watching.label);
    });
  });

  atlas?.dispose();
  settingsStylePreviewId = null;
  const activeTheme = themeForPreferences(state.preferences, systemAppearance.matches);
  let lastMoving: boolean | null = null;
  let lastAnchorFocus: boolean | null = null;
  const rendererLoading = el('p', { class: 'reconstruction-loading', role: 'status',
    text: 'Opening the Atlas and decoding its available reconstruction…' });
  shell.append(rendererLoading);
  shell.setAttribute('aria-busy', 'true');
  try {
    atlas = await mountAtlas(canvas, stage, built.scene, (report) => {
    if (lastMoving !== report.moving) {
      lastMoving = report.moving;
      shell.setAttribute('data-moving', report.moving ? 'true' : 'false');
    }
    if (report.moving && firstUse.observeMovement()) reflectFirstUse();
    if (!minimap.root.hidden) {
      const camera = atlas?.binding.controls.state;
      minimap.setViewer(
        camera === undefined ? null : { x: camera.x, z: camera.z, yaw: camera.yaw },
      );
    }
    const anchorFocused = report.mode === 'traverse' && report.focusedIndex !== null;
    if (lastAnchorFocus !== anchorFocused) {
      lastAnchorFocus = anchorFocused;
      shell.toggleAttribute('data-anchor-focus', anchorFocused);
    }
    shell.setAttribute('data-spatial', report.spatial.phase);
    if (report.recoveryReason !== null) {
      showTravelStatus(
        report.recoveryReason === 'outside-field'
          ? 'Returned to the nearest safe place; the resident field ended here.'
          : report.recoveryReason === 'no-surface'
            ? 'Returned to the nearest safe place; there is no walkable surface here.'
            : 'Returned to the nearest safe place; the surface ahead is too steep or discontinuous.',
        'failure',
      );
    }
  }, {
    theme: activeTheme,
    fieldOfView: state.preferences.fieldOfView,
    mouseSensitivity: state.preferences.mouseSensitivity,
    artProfile: previewArtProfile ?? worldArtProfile(
      state.preferences.worldArtProfile,
      state.preferences.worldArtProfileVersion,
      state.preferences.worldStyleParameters,
    ),
    ...(previewArtProfile === undefined
      ? { artProfileParameters: state.preferences.worldStyleParameters }
      : {}),
    ...(state.previewSourceMedia === undefined ? {} : { sourceMedia: state.previewSourceMedia }),
    ...(state.pointMaps === undefined ? {} : { pointMaps: state.pointMaps }),
    ...(state.placedPointMaps === undefined ? {} : { placedPointMaps: state.placedPointMaps }),
    trainedGeometry: state.trainedGeometry,
    sourcePresentation: sourcePresentation(),
    recoveredCameras: state.recoveredCameras,
    reducedMotion: systemReducedMotion.matches,
  }, browserMeasurement === null ? undefined : (binding) => {
    browserMeasurement.observeBinding(binding, {
      scenes: current.reconstructionScenes ?? [],
      placedPointMapCount: state.placedPointMaps?.length ?? 0,
      placementMaxErrors: binding.verifyPlacements().map((check) => check.maxErrorMetres),
    });
    });
  } finally { rendererLoading.remove(); shell.removeAttribute('aria-busy'); }
  // Only renderer-accepted legacy preview maps suppress the source-only region notice.
  if (preview) {
    for (const visual of atlas.binding.islands) {
      if (state.pointMaps?.has(visual.island.islandId)) renderedPreviewRegions.add(visual.island.islandId);
    }
  }
  const actualRendering = new Map<string, RenderingSubstrate>();
  for (const visual of atlas.binding.islands) actualRendering.set(visual.pointMap.sceneId, 'posed_point_maps');
  for (const visual of atlas.binding.trainedScenes) actualRendering.set(visual.geometry.sceneId, 'gaussian_splats');
  state.reconstructionRungs = reconstructionRungsFor(current.reconstructionScenes ?? [], actualRendering, state.notDrawnScenes, state.displayFrames);
  state.geometryNotices = Object.freeze([...state.geometryNotices, ...atlas.binding.trainedSceneFailures
    .map((failure) => `Trained reconstruction unavailable: ${failure.reason}`)]);
  const refreshedStatus = renderReconstructionStatus();
  reconstructionStatus.replaceWith(refreshedStatus);
  reconstructionStatus = refreshedStatus;
  // The lens survives a remount. It is session state, not renderer state, so a world that has just
  // been rebuilt has to be told what the visitor is currently looking through.
  applyProofLens();
  canvas.dataset.companionRenderer = 'svg';
  reflectShell();

  // -- the two input modes, and the one key that calls the Companion ----------------------
  //
  // The mode follows the browser's pointer lock state and is never guessed at: the browser drops
  // the lock on Escape and on focus loss without telling the application first, so a mode the
  // application tracked itself would be wrong within seconds of the user tabbing away.
  const mounted = atlas;
  mounted.binding.onInspectionChange = (view) => {
    if (view === null) reconstructionInspector.hide();
  };
  mounted.binding.mapOverlay?.setActive(shellState.camera === 'map');
  mounted.binding.onMapTarget = (islandId) => {
    const resolution = mounted.binding.navigateToIsland(islandId, travelUsesReducedMotion());
    if (!resolution.ok) {
      showTravelStatus('No safe arrival point is available in that region.', 'failure');
      return;
    }
    dispatchShell({ type: 'show-world' });
    showTravelStatus(travelUsesReducedMotion() ? 'Located the region.' : 'Moving to the region…');
  };
  mounted.binding.onNavigationArrive = (target) => {
    if (target.kind === 'anchor') {
      const index = mounted.binding.table.indexOf.get(target.anchorId);
      if (index !== undefined) mounted.binding.focusAnchor(index);
    }
    showTravelStatus(target.kind === 'anchor' ? 'Located the source.' : 'The memory is in focus.');
  };
  function reflectMode(next: 'traverse' | 'converse'): void {
    inputMode = next;
    chrome.setMode(next);
    if (next === 'traverse') mounted.binding.releaseFocusedAnchor();
    if (next === 'traverse' && (shellState.primary !== 'world' || shellState.camera !== 'ground')) {
      dispatchShell({ type: 'show-world' });
    }
    // The prompt says what is true right now. With the mouse free the useful instruction is how
    // to get into the world; once inside it is how to call the Companion. An open conversation
    // outranks both and is left alone.
    if (companionPanel.state() === 'open') return;
    companionPanel.setState(next === 'traverse' ? 'summon' : 'enter');
    firstUse.observeMode(next);
    reflectFirstUse();
  }
  mounted.binding.controls.onModeChange = reflectMode;
  reflectMode(mounted.binding.controls.mode);

  /** Open the fixed visual-novel composition over the current memory backdrop. */
  // X and right click reach this through the renderer controls, so the verb observes the same
  // enabled/disabled boundary as movement and interaction instead of bypassing system surfaces.
  function summonCompanion(): void {
    // Pointer Lock freezes clientX/clientY by specification. The SVG Companion follows the free
    // page pointer, so summoning releases the real browser lock instead of fabricating a cursor.
    if (document.pointerLockElement !== null) document.exitPointerLock();
    const placement = resolveCompanionPlacement({
      viewport: { width: window.innerWidth, height: window.innerHeight },
      // The reference deliberately treats the memory as backdrop, so it does not mirror the
      // reading order around a projected source rectangle.
      memoryBounds: null,
      preferredSide: state.preferences.companionSide,
    });
    companionPanel.setPlacement(placement);
    companionController.summon(Date.now());
    reflectTurnState(companionController.current());
    companionStage.show();
    reflectShell();
  }

  function toggleCompanion(): void {
    // A system surface must not summon the Companion out from behind itself. This used to fall
    // out of disabling the controls wholesale; it is now stated where the policy actually lives.
    if (shellState.primary === 'options' || shellState.primary === 'controls') return;
    if (companionPanel.state() === 'open') {
      dismissCompanion();
      return;
    }
    summonCompanion();
  }

  mounted.binding.controls.onSummon = toggleCompanion;
  mounted.binding.controls.onInteract = () => {
    const index = mounted.binding.engageFocusedAnchor();
    if (index === null) return;
    const anchor = mounted.binding.table.anchors[index];
    const occurrence = anchor === undefined
      ? undefined
      : current.occurrences.find((value) => value.occurrenceId === anchor.occurrenceId);
    if (occurrence === undefined) {
      mounted.binding.releaseFocusedAnchor();
      showTravelStatus('This memory reference is unavailable.', 'failure');
      return;
    }
    selected = occurrence.occurrenceId;
    detail.showOccurrence(occurrence);
    worldIndex.render(current, indexFacets, selected);
    if (shellState.primary !== 'index') dispatchShell({ type: 'toggle-index' });
    dispatchShell({ type: 'show-detail', id: occurrence.occurrenceId });
  };

  mountListeners?.abort();
  mountListeners = new AbortController();
  /*
   * CLICK-TO-EVIDENCE, bound here and not beside the function that resolves it.
   *
   * The listener is on the shared world canvas, which the inspector does not own, so it has to
   * hang off `mountListeners` like every other listener outside a mounted element: the inspector
   * is rebuilt on each mount and the old one is simply discarded, so a listener registered beside
   * it would survive the mount that created it. This file already records that failure mode.
   *
   * Guarded on the inspector being open, so traverse is untouched: while traversing,
   * `inspectionView` is null and `resolveEvidenceAt` returns before reading anything.
   * `pointerup` rather than `pointerdown`, so a drag that happens to end over the canvas is not
   * taken as a click on a surface the visitor never pointed at.
   */
  canvas.addEventListener(
    'pointerup',
    (event) => {
      if (event.button !== 0 || reconstructionInspector.root.hidden) return;
      resolveEvidenceAt(event.clientX, event.clientY);
    },
    { signal: mountListeners.signal },
  );
  canvas.addEventListener(
    'webglcontextlost',
    (event) => {
      event.preventDefault();
      dispatchShell({ type: 'show-index' });
      showTravelStatus(
        'The 3D renderer became unavailable. The complete World Index remains available.',
        'failure',
      );
    },
    { signal: mountListeners.signal },
  );
  window.addEventListener(
    'keydown',
    (event) => {
      const target = event.target;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable);
      /*
       * Escape steps back by exactly one, and only once the browser has finished with it.
       *
       * While the pointer is locked Escape belongs to the user agent: it releases the mouse and
       * we neither see nor want it, which is the rule the renderer controls are built around.
       * Released, it has no browser job left, and the key everyone already tries for "out of
       * this" becomes the way out. One press, one level: the exchange, then the entry, then the
       * plate. Backspace keeps its meaning for people who learned it, but nobody guesses it.
       */
      if (event.code === 'Escape' && document.pointerLockElement === null) {
        // Search is the innermost thing open, so it is the first thing Escape takes back.
        if (shellState.primary === 'index' && worldIndex.closeSearch()) {
          event.preventDefault();
          return;
        }
        if (companionPanel.state() === 'open') {
          event.preventDefault();
          dismissCompanion();
          return;
        }
        if (shellState.detailId !== null) {
          event.preventDefault();
          dispatchShell({ type: 'close-detail' });
          return;
        }
        if (shellState.primary !== 'world') {
          event.preventDefault();
          dispatchShell({ type: 'show-world' });
          return;
        }
      }
      const command = commandForKeystroke({
        code: event.code,
        key: event.key,
        modified: event.altKey || event.ctrlKey || event.metaKey,
        typing,
      });
      if (
        !typing && companionPanel.state() === 'open' &&
        !event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyE'
      ) {
        if (companionPanel.openEvidence()) {
          event.preventDefault();
          return;
        }
      }
      if (
        !typing && shellState.primary === 'index' &&
        !event.altKey && !event.ctrlKey && !event.metaKey && event.code === 'KeyS'
      ) {
        event.preventDefault();
        worldIndex.focusSearch();
        return;
      }
      if (command === 'toggle-index') {
        event.preventDefault();
        handleAtlasCommand('index');
        return;
      }
      if (command === 'toggle-map') {
        event.preventDefault();
        // Tap or hold is decided on the way back up, so the key does nothing yet.
        mapPeek.press();
        return;
      }
      if (command === 'toggle-options') {
        event.preventDefault();
        handleAtlasCommand('options');
        return;
      }
      if (command === 'toggle-controls') {
        event.preventDefault();
        handleAtlasCommand('controls');
        return;
      }
      if (command === 'selection-back' && shellState.detailId !== null) {
        event.preventDefault();
        dispatchShell({ type: 'close-detail' });
        return;
      }
      // Not while the user is typing an answer into the Companion or a name into the index.
      if (typing) return;
      // Answering by number, which is the only way to answer while the pointer is locked: there
      // is no cursor to click with, and releasing the lock to reply would mean leaving the world
      // for every question. Unavailable options return null and the key does nothing, rather than
      // selecting the next one along and committing something nobody chose.
      if (/^Digit[1-9]$/.test(event.code)) {
        if (companionPanel.pressNumber(Number(event.code.slice(5)))) event.preventDefault();
        return;
      }
    },
    { signal: mountListeners.signal },
  );
  window.addEventListener(
    'keyup',
    (event: KeyboardEvent) => {
      if (event.code === 'KeyM') mapPeek.release();
    },
    { signal: mountListeners.signal },
  );
  // A hold that loses the window never receives its keyup, and a look must not become a journey.
  window.addEventListener('blur', () => mapPeek.abort(), { signal: mountListeners.signal });
  window.addEventListener(
    'popstate',
    () => {
      indexFacets = decodeFacets(window.location.search);
      worldIndex.render(current, indexFacets, selected);
    },
    { signal: mountListeners.signal },
  );
  systemAppearance.addEventListener(
    'change',
    () => applyPreferences(state.preferences),
    { signal: mountListeners.signal },
  );

  // Nothing is asked unprompted. The Companion arrives when it is called, and until then the
  // world is the whole of what is on screen.

  // Reported rather than trusted. A placement that does not reproduce atlas-core's own transform
  // is a region turned the wrong way, which is invisible until somebody walks behind it.
  const worst = Math.max(0, ...atlas.placements.map((check) => check.maxErrorMetres));
  if (worst > 1e-3) {
    console.warn(`atlas placement disagrees with atlas-core by ${worst} atlas units`);
  }

  // -- the write path, in full -----------------------------------------------------------
  function propose(occurrence: OccurrenceRecord, panel: typeof confirm): void {
    const form = detail.root.querySelector<HTMLFormElement>('.name-offer');
    const input = form?.querySelector<HTMLInputElement>('input');
    const displayName = input?.value.trim() ?? '';
    if (displayName.length === 0) return;

    issued += 1;
    const proposalId = `proposal-${issued}`;
    // Drafted by world-index, not here. The tier, the reversibility and the four bands all come
    // from the one policy table both surfaces obey.
    const draft = draftEdit(
      current!,
      syntheticEntityFor(occurrence),
      displayName,
      (kind) => `${kind}-${issued}`,
    );
    const translated = toUpdateProposal(draft, {
      proposalId,
      turnId: `turn-${issued}`,
      stateVersion: currentSession!.stateVersion(),
      occurrenceId: occurrence.occurrenceId,
    });
    if (!translated.ok) {
      panel.reportFailure(translated.reason);
      return;
    }
    currentSession!.stage(translated.proposal);
    panel.show(proposalId, confirmationFor(draft, syntheticEntityFor(occurrence)), displayName);
  }

  async function commit(proposalId: string): Promise<void> {
    if (preview) {
      companionStage.setState('uncertain');
      confirm.reportFailure('Preview mode is read-only. No change was sent.');
      return;
    }
    // This state names a real pending write. It begins before the request and ends with its result.
    companionStage.setState('working');
    try {
      await currentSession!.commit(proposalId);
    } catch (error) {
      companionStage.setState('uncertain');
      panelFailure(confirm, error);
      return;
    }
    // Only a completed account-holder confirmation earns this state.
    companionStage.setState('settled');
    confirm.hide();
    // Re-read rather than patched. See the module comment.
    state.snapshot = await currentSession!.snapshot();
    selected = null;
    await mount();
  }
}

function syncIndexRoute(facets: IndexFacets): void {
  const url = new URL(window.location.href);
  for (const key of FACET_KEYS) url.searchParams.delete(key);
  const encoded = new URLSearchParams(encodeFacets(facets));
  for (const [key, value] of encoded) url.searchParams.set(key, value);
  window.history.replaceState(window.history.state, '', url);
}

function panelFailure(confirm: ReturnType<typeof buildConfirm>, error: unknown): void {
  confirm.reportFailure(
    error instanceof ApiError
      ? `${error.code}: ${error.message}`
      : error instanceof Error
        ? error.message
        : 'the write was refused',
  );
}

/**
 * The entity a bare occurrence would become.
 *
 * `draftEdit` and `confirmationFor` both take an `EntityRecord`, because both were written for
 * the case where the thing already exists. Naming a detection creates the entity, so there is no
 * record to hand them yet. This builds the one the write is about to produce: no name, no
 * assertions, and the occurrence's own island. Every field is either the truth or empty, and
 * nothing here is written anywhere: it exists to be described in the confirmation panel and is
 * discarded afterwards.
 */
function syntheticEntityFor(occurrence: OccurrenceRecord) {
  return {
    entityId: occurrence.entityId ?? occurrence.occurrenceId,
    kind: occurrence.kind === 'voice' || occurrence.kind === 'conversation'
      ? ('object' as const)
      : (occurrence.kind as 'person' | 'place' | 'object' | 'event'),
    displayName: null,
    status: 'inferred_only' as const,
    occurrenceCount: 1,
    islandIds: [occurrence.islandId],
    firstSeenMs: occurrence.capturedAtMs,
    lastSeenMs: occurrence.capturedAtMs,
    confidence: occurrence.confidence,
    openQuestionCount: 0,
    citingAnswerCount: 0,
    assertions: [],
    relations: [],
    contradictions: [],
    history: [],
    mergedInto: null,
  };
}


/**
 * The batch to watch, or none.
 *
 * The most recently started one, running or not. A finished batch replays its history and ends,
 * which is the same code path a live subscriber takes, so somebody who opens the page after an
 * ingest finished reads what happened rather than finding nothing and concluding it was lost.
 */
function mostRecentlyStarted(batches: readonly BatchSummary[]): BatchSummary | undefined {
  return [...batches].sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0];
}

/**
 * Boot: one session, one snapshot, one scene, and one write path.
 *
 * The shape of this file is the argument. It builds a session, reads the graph once, adapts it
 * into a scene, mounts the renderer, and wires the surfaces to that one snapshot. In a normal
 * build there is no second source of truth and no fixture: everything on the screen came from
 * `GET /graph`, `GET /evidence/{span}` or a write that went through the gate. The Vite development
 * server has one explicit `?preview=1` exception for UI work while the API is unavailable. It is
 * synthetic, identified in the document title and contextual surfaces, and read-only; production
 * builds cannot enter it.
 *
 * **This file composes; it does not implement.** Each surface lives in `composition/` behind a
 * mount function that takes its dependencies explicitly and returns a dispose. What remains here
 * is the order those mounts run in, the world shell they all talk through, and the two cycles
 * that are real: the Companion needs the confirmation surface to render a staged proposal, and
 * the confirmation surface needs the Companion's presence to report a pending commit on. Both are
 * closed here, in the one scope that legitimately knows every surface exists.
 *
 * **The credential stays in this file.** `CompanionAskClient` is constructed here and the
 * Companion module is handed a function rather than a client, for the same reason `session.ts`
 * builds the write gate: a surface that held a credential could reach a route nobody wired it to.
 *
 * **Every write goes through the confirmation surface**, and the confirmation surface is the only
 * caller of `session.commit`. The chain is: the user types a name, a draft is built by
 * `world-index`, translated into an update proposal, staged on the gate, rendered for reading,
 * and committed only when the user presses confirm. Skipping any link is not possible from here,
 * because `session` exposes `stage` and `commit` separately and the panel is what sits between.
 * `composition/write-path.ts` holds that whole chain, panel included.
 *
 * **The snapshot is re-read after a write rather than patched.** A local patch would be a second
 * model of the graph maintained by hand, and the first time it disagreed with the server the
 * interface would be confidently wrong. Re-reading costs one request and cannot drift.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';
import './appearance.css';
import './unified-interface.css';
import './ui/object-placement.css';
import './ui/scene-segments.css';

import { ApiError } from '@exulanica/graph-client';
import { anchorId as toAnchorId, islandId as toIslandId } from '@exulanica/atlas-core';
import { FACET_KEYS, encodeFacets, type IndexFacets } from '@exulanica/world-index';
import { applicationTitle, developmentToken } from './config.js';
import { buildScene } from './scene.js';
import { buildAtlasCommands, type AtlasCommand } from './ui/atlas-commands.js';
import { buildWorldChrome } from './ui/world-chrome.js';
import { CompanionAskClient, CompanionProposalClient } from './companion-ask-api.js';
import { CompanionMemoryClient, answerToRemember } from './companion-memory-api.js';
import type { PersistedMemory } from '@exulanica/companion-runtime';
import { buildDetail } from './ui/detail.js';
import { buildEmptyWorld } from './ui/empty-world.js';
import { buildStartupState } from './ui/startup-state.js';
import { el, replace } from './ui/dom.js';
import { createFirstUseGuidance, type FirstUseMode } from './ui/first-use-guidance.js';
import { buildWorldIndex } from './ui/world-index.js';
import { MapPeek } from './ui/map-peek.js';
import { buildRegionPlan } from './ui/region-plan.js';
import { MAP_ORIENTATION_CAPTION } from './ui/status.js';
import { applyDocumentAppearance, applyDocumentWorldStyle } from './theme.js';
import { worldArtProfile } from '@exulanica/presentation';
import { initialWorldShell, updateWorldShell, type WorldShellEvent } from './world-shell.js';
import { mountAppearance } from './composition/appearance.js';
import { mountObjects } from './composition/objects.js';
import { createSegmentSession, mountSegments, segmentsFirst } from './composition/segments.js';
import { mountWritePath, type MountedWritePath } from './composition/write-path.js';
import { disposeCompanionStage, mountCompanion } from './composition/companion.js';
import { disposeFormationWatch, mountFormation } from './composition/formation.js';
import { disposeRenderer, mountRenderer } from './composition/renderer.js';
import { disposeMountListeners, mountInputModes } from './composition/input-modes.js';
import {
  mountStatusAndInspector,
  type MountedStatusAndInspector,
} from './composition/status-and-inspector.js';
import {
  mountSessionGeometry,
  openAppSession,
  reconstructionsOf,
} from './composition/session-and-geometry.js';
import { createAppEnvironment, createSessionState } from './composition/session-state.js';

const env = createAppEnvironment();
const state = createSessionState();
const segmentSession = createSegmentSession();
const { shell, canvas, systemAppearance, systemReducedMotion, preview, previewArtProfile } = env;

window.addEventListener('pagehide', () => state.sourceMediaSession?.dispose(), { once: true });
systemReducedMotion.addEventListener('change', (event) => {
  state.atlas?.binding.setReducedMotion(event.matches);
});
applyDocumentAppearance(state.preferences, systemAppearance.matches);
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
    disposeCompanionStage(state);
    disposeFormationWatch(state);
    disposeMountListeners(state);
    disposeRenderer(state);
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
  disposeCompanionStage(state);
  // The canvas stays where the document put it: fixed, behind everything, outside the shell.
  // Moving it into the shell would put it in the shell's stacking context, where it paints over
  // the rail. The stage is the hole it shows through and the parent the anchor overlay writes
  // its nodes into, which is a different job from being the canvas.
  const stage = el('div', { class: 'stage' });

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

  const firstUse = createFirstUseGuidance(window.localStorage);
  let inputMode: FirstUseMode = 'converse';
  let reflectFirstUse = (): void => undefined;
  const finishFirstUse = (): void => {
    if (firstUse.complete()) reflectFirstUse();
  };

  // The Companion. The controller holds the turn, the panel renders it, and the confirmation
  // surface the write path builds is the only thing either of them can reach that writes.
  //
  // `askQuestion` is the read half: free text the parser cannot turn into a change is a question
  // about the library, and this is the only place holding the credential it takes to ask one.
  const companionAsk = new CompanionAskClient(currentCredentials);

  // The one thing the Companion may DO, and it is still not a write. `POST /selection/appearance`
  // reads an utterance as a bounded proposal drawn from the reviewed style catalogue; the world
  // style authority is what turns one into a preview, and the person's own Apply is what commits
  // it. Constructed here for the same reason as the two clients around it: this file holds the
  // credential and nothing under it does.
  const companionPropose = new CompanionProposalClient(currentCredentials);

  // The durable half of the same conversation. Read once per mount, because a reload used to be
  // amnesia: interaction-model.md 4.3 and 5.5 both say the Companion may never speak "within 7
  // days of a Skip or 14 days of a Not sure on the same entity", and a window held in a page had
  // never once survived one.
  //
  // A failed read is a Companion that has forgotten somebody, which is worse than one that never
  // offered to remember, so it is said rather than swallowed. It is NOT allowed to stop the world
  // from mounting: everything else on this page works without it.
  const companionMemory = new CompanionMemoryClient(currentCredentials);
  let persistedMemory: PersistedMemory | null = null;
  let memoryLoadFailure: string | null = null;
  try {
    persistedMemory = await companionMemory.recent();
  } catch (error) {
    memoryLoadFailure = error instanceof Error ? error.message : String(error);
  }

  let writePath: MountedWritePath;
  const companion = mountCompanion({
    state,
    engine: currentCompanion,
    evidence: currentEvidence,
    ask: (question) => companionAsk.ask(question),
    proposeAppearance: (utterance) => companionPropose.propose(utterance),
    persistedMemory,
    rememberAnswer: async (answer) => {
      await companionMemory.rememberAnswer(answerToRemember(answer));
    },
    stageParent: stage,
    confirm: () => writePath.confirm,
    reflectShell: () => reflectShell(),
    onAnswered: finishFirstUse,
    isSystemSurfaceOpen: () =>
      shellState.primary === 'options' || shellState.primary === 'controls',
  });

  if (memoryLoadFailure !== null) {
    companion.panel.noteMemoryFailure('memory.notLoaded', memoryLoadFailure);
  }

  writePath = mountWritePath({
    env,
    state,
    session: currentSession,
    snapshot: current,
    companionStage: () => companion.stage,
    detailRoot: () => detail.root,
    onConfirmVisibilityChange: (visible) => companion.panel.setConfirming(visible),
    remount: () => mount(),
  });


  // Authored objects. Mounted after the write path because it hides that panel before showing
  // its own confirmation, and before the renderer because its root enters the document below;
  // it reads `state.atlas` late for the same reason every pre-renderer surface does.
  const objects = mountObjects({
    env,
    state,
    credentials: currentCredentials,
    scene: built.scene,
    showTravelStatus: (message, kind) => showTravelStatus(message, kind),
    isWorldPrimary: () => shellState.primary === 'world',
    hideWritePathConfirm: () => writePath.confirm.hide(),
  });

  // Scene segments. Mounted after the write path because naming a segment stages on that path and
  // shows its confirmation panel; it reads `state.atlas` late and applies its overlay in `begin`.
  const segments = mountSegments({
    env,
    state,
    snapshot: current,
    segmentSession,
    session: currentSession,
    confirm: writePath.confirm,
    hideOtherConfirms: () => objects.confirm.hide(),
    inspect: (sceneId) => status.inspectReconstruction(sceneId),
    showWorld: () => dispatchShell({ type: 'show-world' }),
    showTravelStatus: (message, kind) => showTravelStatus(message, kind),
    travelUsesReducedMotion: () => travelUsesReducedMotion(),
  });

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
    onName: (occurrence) => writePath.propose(occurrence),
    onEvidenceOpened: (anchorId) => {
      // 5.2: the written claim and the spatial world point at the same evidence at the same
      // moment. Focusing the anchor is the spatial half of that one gesture.
      if (anchorId === null || state.atlas === null) return;
      const index = state.atlas.binding.table.indexOf.get(anchorId as never);
      if (index !== undefined) state.atlas.binding.focusAnchor(index);
    },
    onLocate: (targetAnchorId, targetIslandId) => {
      const binding = state.atlas?.binding;
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
      state.selected = entityId;
      const entity = current.entities.find((e) => e.entityId === entityId);
      if (entity !== undefined) {
        detail.showEntity(current, entity);
        dispatchShell({ type: 'show-detail', id: entityId });
      }
      worldIndex.render(current, state.indexFacets, state.selected);
      if (activation === 'keyboard') {
        window.setTimeout(() => detail.root.querySelector<HTMLElement>('button')?.focus(), 0);
      }
    },
    onOccurrence: (occurrenceId, activation) => {
      state.selected = occurrenceId;
      const occurrence = current.occurrences.find((o) => o.occurrenceId === occurrenceId);
      if (occurrence !== undefined) {
        detail.showOccurrence(occurrence);
        dispatchShell({ type: 'show-detail', id: occurrenceId });
      }
      worldIndex.render(current, state.indexFacets, state.selected);
      if (activation === 'keyboard') {
        window.setTimeout(() => detail.root.querySelector<HTMLElement>('button')?.focus(), 0);
      }
    },
    onSearch: (text) => {
      state.indexFacets = Object.freeze({ ...state.indexFacets, text });
      worldIndex.render(current, state.indexFacets, state.selected);
    },
    onFacets: (next) => {
      state.indexFacets = next;
      syncIndexRoute(next);
      worldIndex.render(current, state.indexFacets, state.selected);
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
  const formation = mountFormation({ state, credentials: currentCredentials });
  const chrome = buildWorldChrome(shell);
  const handleAtlasCommand = (command: AtlasCommand): void => {
    if (companion.panel.state() === 'open') companion.dismiss();
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
    companion.panel.setFirstUsePrompt(firstUse.prompt(inputMode));
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
  let status: MountedStatusAndInspector;
  const appearance = mountAppearance({
    env,
    state,
    applyProofLens: () => status.applyProofLens(),
    setCompanionAppearance: () => companion.applyAppearance(),
    onCloseOptions: () => dispatchShell({ type: 'toggle-options' }),
    onShowControls: () => dispatchShell({ type: 'toggle-controls' }),
    onCloseControls: () => dispatchShell({ type: 'toggle-controls' }),
    onShowCustomize: () => dispatchShell({ type: 'toggle-options' }),
  });

  status = mountStatusAndInspector({
    env,
    state,
    snapshot: current,
    built,
    showWorld: () => dispatchShell({ type: 'show-world' }),
    showTravelStatus,
  });
  replace(shell, [
    stage,
    chrome.reticle,
    worldIndex.root,
    detail.root,
    formation.root,
    companion.panel.root,
    writePath.confirm.root,
    objects.panel.root,
    objects.confirm.root,
    commandBar.root,
    mapCaption,
    travelStatus,
    minimap.root,
    appearance.options.root,
    appearance.settings.root,
    viewportBoundary,
    status.inspectorRoot,
    status.statusElement,
    segments.root,
  ]);

  reflectShell = (): void => {
    if (shellState.primary !== 'world') {
      state.atlas?.binding.endSceneInspection();
      status.hideInspector();
    }
    shell.setAttribute('data-primary', shellState.primary);
    shell.setAttribute('data-camera', shellState.camera);
    chrome.setIndexOpen(shellState.primary === 'index');
    worldIndex.root.inert = shellState.primary !== 'index';
    worldIndex.root.setAttribute('aria-hidden', shellState.primary === 'index' ? 'false' : 'true');
    appearance.options.setVisible(shellState.primary === 'options');
    appearance.settings.setVisible(shellState.primary === 'controls');
    const systemSurfaceOpen = shellState.primary === 'options' || shellState.primary === 'controls';
    const modalBackground = [
      stage,
      worldIndex.root,
      detail.root,
      formation.root,
      companion.panel.root,
      writePath.confirm.root,
      mapCaption,
      travelStatus,
    ];
    // On close, release the command bar before the dialog restores focus to its trigger. On open,
    // move focus into the dialog before making that same trigger inert.
    if (!systemSurfaceOpen) for (const surface of modalBackground) surface.inert = false;
    appearance.options.setVisible(shellState.primary === 'options');
    appearance.settings.setVisible(shellState.primary === 'controls');
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
    state.atlas?.binding.setMapMode(shellState.camera === 'map');
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
    state.atlas?.binding.setControlsEnabled(shellState.camera === 'ground');
    // Every surface here takes the cursor. None of them should take your feet with it.
    state.atlas?.binding.setFreeCursorActive(
      companion.panel.state() === 'open' || shellState.primary !== 'world',
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

  worldIndex.render(current, state.indexFacets, state.selected);
  formation.begin();

  const renderer = await mountRenderer({
    env,
    state,
    snapshot: current,
    scene: built.scene,
    stage,
    minimap,
    status,
    firstUse,
    reflectFirstUse: () => reflectFirstUse(),
    reflectShell: () => reflectShell(),
    showTravelStatus,
  });

  // -- the two input modes, and the one key that calls the Companion ----------------------
  //
  // The mode follows the browser's pointer lock state and is never guessed at: the browser drops
  // the lock on Escape and on focus loss without telling the application first, so a mode the
  // application tracked itself would be wrong within seconds of the user tabbing away.
  mountInputModes({
    env,
    state,
    snapshot: current,
    atlas: renderer.atlas,
    companion,
    // A click in the inspector asks for a segment before it asks for evidence.
    status: segmentsFirst(status, (clientX, clientY) => segments.resolveAt(clientX, clientY)),
    chrome,
    worldIndex,
    detail,
    mapPeek,
    firstUse,
    shellState: () => shellState,
    dispatchShell,
    handleAtlasCommand,
    showTravelStatus,
    travelUsesReducedMotion,
    setInputMode: (mode) => { inputMode = mode; },
    reflectFirstUse: () => reflectFirstUse(),
    applyPreferences: (next) => appearance.applyPreferences(next),
  });

  // Nothing is asked unprompted. The Companion arrives when it is called, and until then the
  // world is the whole of what is on screen.

  renderer.reportPlacementDisagreement();

  // After the renderer, because every object it draws needs a binding to draw into.
  void objects.begin();
  void segments.begin();

}

function syncIndexRoute(facets: IndexFacets): void {
  const url = new URL(window.location.href);
  for (const key of FACET_KEYS) url.searchParams.delete(key);
  const encoded = new URLSearchParams(encodeFacets(facets));
  for (const [key, value] of encoded) url.searchParams.set(key, value);
  window.history.replaceState(window.history.state, '', url);
}





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
import { anchorId as toAnchorId, islandId as toIslandId } from '@exulanica/atlas-core';
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
import { buildWorldChrome } from './ui/world-chrome.js';
import { buildCompanionStage, type CompanionStage } from './ui/companion-stage.js';
import { createCompanionController } from './companion.js';
import { CompanionAskClient } from './companion-ask-api.js';
import type { Turn } from '@exulanica/companion-runtime';
import { buildDetail } from './ui/detail.js';
import { buildFormation } from './ui/formation.js';
import { buildEmptyWorld } from './ui/empty-world.js';
import { buildStartupState } from './ui/startup-state.js';
import { el, replace } from './ui/dom.js';
import { createFirstUseGuidance, type FirstUseMode } from './ui/first-use-guidance.js';
import { buildWorldIndex } from './ui/world-index.js';
import { MapPeek } from './ui/map-peek.js';
import { buildRegionPlan } from './ui/region-plan.js';
import { MAP_ORIENTATION_CAPTION } from './ui/status.js';
import {
  applyDocumentAppearance,
  applyDocumentWorldStyle,
  themeForPreferences,
} from './theme.js';
import { companionAppearanceConfiguration, worldArtProfile } from '@exulanica/presentation';
import {
  commandForKeystroke,
  initialWorldShell,
  updateWorldShell,
  type WorldShellEvent,
} from './world-shell.js';
import { mountAppearance } from './composition/appearance.js';
import {
  mountStatusAndInspector,
  type MountedStatusAndInspector,
} from './composition/status-and-inspector.js';
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
    state.settingsStylePreviewId = null;
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
  let status: MountedStatusAndInspector;
  const appearance = mountAppearance({
    env,
    state,
    applyProofLens: () => status.applyProofLens(),
    setCompanionAppearance: () => companionStage.setAppearance(companionAppearance()),
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
    forming.root,
    companionPanel.root,
    confirm.root,
    commandBar.root,
    mapCaption,
    travelStatus,
    minimap.root,
    appearance.options.root,
    appearance.settings.root,
    viewportBoundary,
    status.inspectorRoot,
    status.statusElement,
  ]);

  reflectShell = (): void => {
    if (shellState.primary !== 'world') {
      atlas?.binding.endSceneInspection();
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
      forming.root,
      companionPanel.root,
      confirm.root,
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
  state.settingsStylePreviewId = null;
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
      if (state.pointMaps?.has(visual.island.islandId)) status.noteRenderedPreviewRegion(visual.island.islandId);
    }
  }
  const actualRendering = new Map<string, RenderingSubstrate>();
  for (const visual of atlas.binding.islands) actualRendering.set(visual.pointMap.sceneId, 'posed_point_maps');
  for (const visual of atlas.binding.trainedScenes) actualRendering.set(visual.geometry.sceneId, 'gaussian_splats');
  state.reconstructionRungs = reconstructionRungsFor(current.reconstructionScenes ?? [], actualRendering, state.notDrawnScenes, state.displayFrames);
  state.geometryNotices = Object.freeze([...state.geometryNotices, ...atlas.binding.trainedSceneFailures
    .map((failure) => `Trained reconstruction unavailable: ${failure.reason}`)]);
  status.refreshStatus();
  // The lens survives a remount. It is session state, not renderer state, so a world that has just
  // been rebuilt has to be told what the visitor is currently looking through.
  status.applyProofLens();
  canvas.dataset.companionRenderer = 'svg';
  reflectShell();

  // -- the two input modes, and the one key that calls the Companion ----------------------
  //
  // The mode follows the browser's pointer lock state and is never guessed at: the browser drops
  // the lock on Escape and on focus loss without telling the application first, so a mode the
  // application tracked itself would be wrong within seconds of the user tabbing away.
  const mounted = atlas;
  mounted.binding.onInspectionChange = (view) => {
    if (view === null) status.hideInspector();
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
      if (event.button !== 0 || status.inspectorRoot.hidden) return;
      status.resolveEvidenceAt(event.clientX, event.clientY);
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
    () => appearance.applyPreferences(state.preferences),
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

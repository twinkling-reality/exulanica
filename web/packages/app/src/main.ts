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

import { readBrowserAccount, type BrowserAccountState } from './account-session.js';
import {
  anchorId as toAnchorId,
  islandId as toIslandId,
  makeScene,
} from '@exulanica/atlas-core';
import { FACET_KEYS, encodeFacets, type IndexFacets } from '@exulanica/world-index';
import {
  applicationTitle,
  developmentToken,
  PREVIEW_NYC_OPEN_DATA_ADMISSION_ID,
} from './config.js';
import { buildScene, prioritizeOwnedArrival } from './scene.js';
import { ARRIVAL_PRESENTATION } from './arrival-presentation.js';
import { buildCredentialGate } from './ui/credential-gate.js';
import type { AtlasCommand } from './ui/atlas-commands.js';
import { buildWorldChrome } from './ui/world-chrome.js';
import { buildWorldMenu } from './ui/world-menu.js';
import { GENERATED_WORLD_READY_EVENT, type GeneratedWorldReady } from './composition/generated-world-ready.js';
import { buildWorldIdentity } from './ui/world-identity.js';
import {
  COMPANION_DRAFT_WAIT_MS,
  CompanionAskClient,
  CompanionProposalClient,
  type CompanionCityContext,
} from './companion-ask-api.js';
import { CompanionMemoryClient, answerToRemember } from './companion-memory-api.js';
import type { PersistedMemory } from '@exulanica/companion-runtime';
import { buildDetail } from './ui/detail.js';
import { PlaceNameRightsClient } from './place-name-rights-api.js';
import {
  buildStartupState,
  buildWorldOpeningFailure,
  worldDidNotOpen,
  worldOpeningCanRetry,
  worldOpeningReason,
} from './ui/startup-state.js';
import { el, replace } from './ui/dom.js';
import { button, errorState } from './ui/system/components.js';
import { createLayout, MODAL_BACKGROUND_REGIONS, type Layout } from './ui/system/layout.js';
import { mountActions, type MountedActions } from './composition/actions.js';
import { redrawWorldLook } from './composition/world-look-redraw.js';
import { buildLookRow, buildLookSheet } from './ui/look-sheet.js';
import type { WorldStylePackBinding } from './world-style-api.js';
import { readLookLibrary, type LookLibrary } from './composition/look-library.js';
import { fill, say } from './ui/copy.js';
import { actionState, perform } from './ui/actions/surfaces.js';
import { actionSpec, availability } from './ui/actions/registry.js';
import type { PlannedRequest } from './ui/actions/planned.js';
import { buildPlanSheet } from './ui/companion-plan.js';
import { CompanionActionsClient, type ActionPageContext } from './companion-actions-api.js';
import { mountCompanionPlans, type CompanionPlans } from './composition/companion-plan.js';
import { openWorldPath } from './world-scope.js';
import { createFirstUseGuidance, type FirstUseMode } from './ui/first-use-guidance.js';
import { buildWorldIndex } from './ui/world-index.js';
import { MapPeek } from './ui/map-peek.js';
import { buildRegionPlan } from './ui/region-plan.js';
import { MAP_ORIENTATION_CAPTION } from './ui/status.js';
import { applyDocumentAppearance, applyDocumentWorldStyle } from './theme.js';
import { worldArtProfile } from '@exulanica/presentation';
import { initialWorldShell, updateWorldShell, type WorldShellEvent } from './world-shell.js';
import { mountPersonalIntake } from './composition/personal-intake.js';
import { requireMetadataOnlyEntryUpdate } from './world-entry-api.js';
import { mountCharacter } from './composition/character.js';
import { mountAppearance } from './composition/appearance.js';
import { mountObjects } from './composition/objects.js';
import {
  buildPersonalWorldChoice,
  buildYourWorlds,
  type PersonalWorldControl,
} from './composition/world-entry.js';
import { keepWorldPicture, worldPicture } from './composition/world-pictures.js';
import { CapabilitiesClient } from './capabilities-api.js';
import { mountEnvironmentSelection } from './composition/environment-selection.js';
import { mountThingCard } from './composition/thing-card-mount.js';
import { createSavedWorldFlight } from './composition/saved-world-flight.js';
import { lazyPanel } from './composition/lazy-panel.js';
import { createSegmentSession, mountSegments, segmentsFirst } from './composition/segments.js';
import { mountWritePath, type MountedWritePath } from './composition/write-path.js';
import { disposeCompanionStage, mountCompanion, plannedAnswer } from './composition/companion.js';
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
  openWorldEntryContext,
  reconstructionsOf,
  StarterWorldOpeningError,
} from './composition/session-and-geometry.js';
import { createAppEnvironment, createSessionState } from './composition/session-state.js';
import { EnvironmentSelectionClient } from './environment-selection-api.js';
import {
  parseVersion,
  WorldObjectsClient,
  type AlternateVersion,
  type SavedEntryWriteBinding,
} from './world-objects-api.js';

/** How long a world draws before its picture for Your worlds is taken: past the arrival's fade. */
const WORLD_PICTURE_DELAY_MS = 6000;

const env = createAppEnvironment();
const state = createSessionState();
const segmentSession = createSegmentSession();
const { shell, canvas, systemAppearance, systemReducedMotion, preview, previewArtProfile } = env;

window.addEventListener('pagehide', () => {
  state.disposeCharacter?.();
  state.disposeObjects?.();
  state.disposeSocietyExperiment?.();
  state.disposeSocietyComparison?.();
  state.disposeEnvironmentSelection?.();
  state.personalIntake.dispose?.();
  disposeCompanionStage(state);
  disposeFormationWatch(state);
  disposeMountListeners(state);
  disposeRenderer(state);
  state.disposeEnvironmentSelection = null;
  state.sourceMediaSession?.dispose();
}, { once: true });
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
  shell.removeAttribute('aria-busy');
  replace(shell, [buildStartupState(error)]);
});

async function boot(): Promise<void> {
  if (shell.querySelector('.startup-thinking') === null) replace(shell, [buildStartupState()]);
  if (preview) {
    await start('');
    return;
  }
  const token = developmentToken();
  if (token !== null) {
    await start(token);
    return;
  }
  let account: BrowserAccountState;
  try {
    account = await readBrowserAccount();
  } catch {
    account = { kind: 'unavailable' };
  }
  if (account.kind === 'authenticated') {
    await start('', account.session.csrfToken);
    return;
  }
  askForAccess(account.kind);
}

/**
 * Account login is the normal entry. The folded bearer path remains for local operators and
 * retains its previous no-storage behavior.
 */
function askForAccess(accountState: 'signed-out' | 'unavailable'): void {
  replace(shell, [buildCredentialGate({
    accounts: accountState,
    signIn: () => window.location.assign('/api/auth/google/start'),
    enter: (token) => start(token),
  })]);
}

async function start(token: string, csrfToken?: string): Promise<void> {
  try {
    await openAppSession(env, state, token, csrfToken);
  } catch (error) {
    if (!(error instanceof StarterWorldOpeningError)) throw error;
    showWorldOpeningFailure(
      worldOpeningReason(error), worldOpeningCanRetry(error) ? () => start(token, csrfToken) : null,
    );
    return;
  }
  // Your worlds comes first: a signed-in person chooses or creates a world before one opens.
  if (!preview) {
    await mountNoWorld({ retry: () => start(token, csrfToken) });
    return;
  }
  await mount();
}

/**
 * Before a world opens: Your worlds whenever there is a saved world to show, else the failure.
 *
 * Your worlds is the way into every world, one or many: it names the world that would open, says
 * why it did not open where start-up already tried, and offers Create a world. A workspace with no
 * saved world at all reached here because its starter could not be made, which the failure says.
 */
async function mountNoWorld(deps: {
  readonly retry: () => Promise<void>;
  /**
   * Re-read the saved worlds before deciding. Start-up has just read them and must not ask
   * twice; arriving here from a mounted world means whatever removed that world happened while
   * this page was open, so the list held in memory is what it was before that.
   */
  readonly refresh?: boolean;
  /** A world chosen here that did not open, said at the top of Your worlds in its place. */
  readonly failed?: string;
}): Promise<void> {
  const client = state.worldEntries;
  if (deps.refresh === true && client !== null) {
    try {
      state.savedWorldEntries = await client.entries();
      state.worldEntryError = null;
    } catch (error: unknown) {
      state.worldEntryError = error;
    }
  }
  if (state.savedWorldEntries.length > 0) {
    await mountWorldEntry(deps.failed);
    return;
  }
  showWorldOpeningFailure(
    worldOpeningReason(state.worldEntryError),
    worldOpeningCanRetry(state.worldEntryError) ? deps.retry : null,
  );
}

function showWorldOpeningFailure(
  reason: string | null, retry: (() => Promise<void>) | null,
): void {
  canvas.hidden = true;
  shell.setAttribute('data-world-state', 'entry');
  replace(shell, [buildWorldOpeningFailure({ reason, retry })]);
  shell.removeAttribute('aria-busy');
  shell.removeAttribute('data-booting');
}

/**
 * The offer to make a world from reviewed photographs, or none where no saved worlds are served.
 *
 * Whatever it makes is opened the way a chosen saved world is: its entry becomes the active one,
 * so every request after it names that entry's world, and the world is mounted afresh.
 */
function personalWorldControl(): PersonalWorldControl | undefined {
  const client = state.worldEntries;
  if (client === null) return undefined;
  const control = buildPersonalWorldChoice({
    read: () => client.personalWorld(),
    make: (made, title) => client.makeFromPersonalSources(made, title),
    open: async (entry) => {
      state.savedWorldEntries = await client.entries();
      await openWorldEntryContext(state, entry);
      state.worldEntryError = null;
      shell.removeAttribute('data-world-state');
      await mount();
    },
  });
  void control.refresh();
  return control;
}

/**
 * A generated world whose tiles were still baking when it opened is opened again, in place, once
 * they are baked or one has failed (`GENERATED_WORLD_READY_EVENT`): its entry is read again and the
 * world mounted, if it is still the world open.
 */
shell.addEventListener(GENERATED_WORLD_READY_EVENT, (event) => {
  const client = state.worldEntries;
  const active = state.activeWorldEntry;
  const ready = (event as CustomEvent<GeneratedWorldReady | null>).detail;
  if (client === null || active === null || ready?.entryId !== active.entryId) return;
  void (async () => {
    const entry = await client.entry(active.entryId);
    state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((candidate) =>
      candidate.entryId === entry.entryId ? entry : candidate));
    await openWorldEntryContext(state, entry);
    await mount();
  })();
});

/** Create a world, as the shell holds it: the stand-in until its code arrives, then the panel. */
interface MakeWorldSurface {
  readonly isConnected: boolean;
  remove(): void;
}

/**
 * The presets a new world can be generated from, and the values a person may change. A world made
 * from one is opened the way a chosen saved world is: its entry becomes the active one and the
 * world is mounted afresh.
 *
 * Its code loads when it is first opened, so the page starts without it. Until it arrives the shell
 * holds a stand-in where the panel will be, saying "Opening Create a world."; a load that fails says
 * so with Try again, and a stand-in closed meanwhile is never replaced by the panel.
 */
function showWorldRecipes(
  onClose: () => void,
  start: { readonly recipeKey: string; readonly values: Readonly<Record<string, number | string>>; readonly origin: string } | null = null,
): MakeWorldSurface | null {
  const client = state.worldEntries;
  const credentials = state.credentials;
  if (client === null || credentials === null) return null;
  shell.querySelector('.world-recipes')?.remove();
  const stand = el('section', {
    class: 'world-recipes lazy-panel', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Create a world', tabindex: '-1',
    'data-ui-stage': 'dark',
  });
  let current: HTMLElement = stand;
  const load = (): void => {
    stand.replaceChildren(el('p', { class: 'lazy-panel-opening', role: 'status', text: 'Opening Create a world.' }));
    void Promise.all([
      import('./ui/world-recipes.js'),
      import('./composition/world-description.js'),
      import('./world-specification.js'),
      import('./world-kinds-api.js'),
    ]).then(([{ buildWorldRecipes }, { attachWorldDescription }, { WorldSpecificationClient }, { WorldKindsClient, KIND_DESCRIPTION_CHARACTERS }]) => {
      if (!stand.isConnected) return;
      const specification = new WorldSpecificationClient(credentials);
      const kinds = new WorldKindsClient(credentials);
      // The look the town is made in: the host's default until the person changes it, sent with
      // the making so the town is bound to it (`style_pack` on POST /worlds/generated).
      let looks: LookLibrary | null = null;
      let chosenLook: string | null = null;
      const lookRow = buildLookRow(() => {
        if (looks === null) return;
        const library = looks;
        shell.querySelector('section.look-sheet')?.remove();
        const sheet = buildLookSheet({
          worldTitle: 'A new town',
          choosing: { use: 'Choose this look', now: 'Chosen' },
          onUse: async (option) => {
            chosenLook = option.packId;
            lookRow.show(option, 'Your choice. You can change it any time later in Design.');
            sheet.root.remove();
            current.querySelector<HTMLElement>('.look-row-change')?.focus({ preventScroll: true });
            return '';
          },
          onClose: () => {
            sheet.root.remove();
            current.querySelector<HTMLElement>('.look-row-change')?.focus({ preventScroll: true });
          },
        });
        shell.append(sheet.root);
        sheet.show(library.options, chosenLook ?? library.defaultId);
        sheet.focus();
      });
      void readLookLibrary(credentials).then((library) => {
        looks = library;
        const first = library.options.find((option) => option.packId === library.defaultId);
        if (first === undefined) return;
        lookRow.show(first, 'The look this server draws new towns in. You can change it now, or any time later in Design.');
      }, () => undefined);
      const panel = buildWorldRecipes({
        specification: () => specification.specification(),
        make: (preset, values) => client.makeGenerated(
          preset.key, preset.label, values, chosenLook === null ? null : looks?.binding(chosenLook) ?? null,
        ),
        open: async (entry) => {
          panel.root.remove();
          state.savedWorldEntries = await client.entries();
          await openWorldEntryContext(state, entry);
          state.worldEntryError = null;
          shell.removeAttribute('data-world-state');
          await mount();
        },
        onClose,
        // A world of a kind of place is titled by the kind, as a town is by its recipe.
        kinds: {
          library: () => kinds.library(),
          drafts: () => kinds.drafts(),
          startDraft: (description) => kinds.startDraft(description),
          draft: (draftId) => kinds.draft(draftId),
          make: (kind, preset, values) => client.makeOfKind(kind, preset, kind.label, values),
          maximumCharacters: KIND_DESCRIPTION_CHARACTERS,
        },
      });
      // A dialog over the world, opened and closed through the shell state like the other major
      // surfaces, so it cannot stay open under the next one and Escape takes it back.
      panel.root.setAttribute('aria-modal', 'true');
      stand.replaceWith(panel.root);
      current = panel.root;
      // Focus moves into the panel as it replaces the stand-in, which took it with it; Describe it
      // takes it once attached (composition/world-description.ts).
      panel.lookSlot.append(lookRow.root);
      panel.focus();
      attachWorldDescription(panel, { credentials, specification: () => specification.specification() });
      // A saved world's own values, loaded as a person's edit is: what is out of range now is said
      // by the panel's own check, and the world they came from never changes.
      if (start !== null) {
        panel.showOrigin(start.origin);
        void panel.setValues(start.recipeKey, start.values);
      }
    }, (error: unknown) => {
      if (!stand.isConnected) return;
      const retry = button({ label: 'Try again', variant: 'primary', onClick: load });
      stand.replaceChildren(errorState({
        happened: 'Create a world did not open.',
        next: 'Check the connection, then try again.',
        action: retry,
        technical: { detail: error instanceof Error ? error.message : String(error) },
      }));
      retry.focus({ preventScroll: true });
    });
  };
  shell.append(stand);
  stand.focus({ preventScroll: true });
  load();
  return {
    get isConnected() { return current.isConnected; },
    remove() { current.remove(); },
  };
}

/** Show Your worlds. Only `mountNoWorld` calls this. */
async function mountWorldEntry(failed?: string): Promise<void> {
  const entries = state.worldEntries;
  canvas.hidden = true;
  shell.setAttribute('data-world-state', 'entry');
  const open = async (entry: typeof state.savedWorldEntries[number]): Promise<void> => {
    await openWorldEntryContext(state, entry);
    state.worldEntryError = null;
    shell.removeAttribute('data-world-state');
    await mount();
  };
  // Create a world opens over Your worlds and returns to it when closed.
  let creating: MakeWorldSurface | null = null;
  const closeCreate = (): void => {
    creating?.remove();
    creating = null;
    (shell.querySelector('.your-worlds-create') as HTMLElement | null)?.focus({ preventScroll: true });
  };
  const yourWorlds = buildYourWorlds({
    entries: state.savedWorldEntries,
    open,
    picture: worldPicture,
    ...(entries === null ? {} : {
      create: () => {
        if (creating?.isConnected === true) return;
        creating = showWorldRecipes(closeCreate);
      },
      viewValues: (entry) => {
        const ground = entry.generatedGround;
        if (creating?.isConnected === true || ground?.values == null) return;
        creating = showWorldRecipes(closeCreate, {
          recipeKey: ground.recipeKey,
          values: ground.values,
          origin: fill('yourWorlds.values.from', { title: entry.title }),
        });
      },
    }),
    arrivalFailure: failed ?? worldOpeningReason(state.worldEntryError),
    ...(() => {
      const personalWorld = personalWorldControl();
      return personalWorld === undefined ? {} : { personalWorld };
    })(),
    adoptLatest: async (entry) => {
      if (entries === null) throw new Error('The saved world is not connected.');
      const adopted = await entries.adoptLatestAuthored(entry);
      state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((candidate) =>
        candidate.entryId === adopted.entryId ? adopted : candidate));
      await open(adopted);
    },
  });
  replace(shell, [yourWorlds.root]);
  shell.removeAttribute('aria-busy');
  shell.removeAttribute('data-booting');
  // Create a world's availability, read the way a mounted world's registry reads it.
  if (entries !== null && state.credentials !== null) {
    const spec = actionSpec('world.make');
    const client = new CapabilitiesClient({ ...state.credentials, worldId: null });
    void client.creation()
      .then((creation) => yourWorlds.setCreate(availability(spec, creation)))
      .catch(() => yourWorlds.setCreate(availability(spec, null)));
  }
  (yourWorlds.root.querySelector('.your-worlds-card') as HTMLElement | null)?.focus({ preventScroll: true });
}

function activeEntryWriteBinding(): SavedEntryWriteBinding {
  const active = state.activeWorldEntry;
  if (active === null) throw new Error('The saved world entry is no longer active.');
  return {
    entryId: active.entryId,
    revision: active.revision,
    authoredVersionId: active.authoredVersionId,
    authoredStateSha256: active.authoredStateSha256,
    authoredEditSeq: active.authoredEditSeq,
  };
}

/**
 * What a mounted world draws from the saved entry and must redraw when the entry moves.
 *
 * The first-use greeting asks the entry whether the world has been built in. Nothing asked it
 * again after a placement, so a person who had just put a pillar in front of themselves was
 * still told "Nothing is in it yet" until something unrelated happened to redraw the prompt.
 * `mount` sets this; between mounts there is nothing drawn to redraw.
 */
let afterEntryAdvanced = (): void => undefined;

/** The layout of the mounted world; replaced on every mount, with the surfaces it places. */
let layout: Layout | null = null;
/** The action registry's host for the mounted world; replaced on every mount. */
let actions: MountedActions | null = null;

async function recordAuthoredEntryAdvance(
  version: AlternateVersion,
  base: SavedEntryWriteBinding,
): Promise<void> {
  const active = state.activeWorldEntry;
  if (active === null || active.entryId !== base.entryId || active.revision !== base.revision) {
    state.sourceMediaNotices = Object.freeze([
      'The edit and resume point were saved, but this page must reload before another change.',
      ...state.sourceMediaNotices,
    ]);
    return;
  }
  const updated = Object.freeze({
    ...active,
    authoredVersionId: version.versionId,
    authoredStateSha256: version.stateSha256,
    authoredEditSeq: version.editSeq,
    currentAuthoredStateSha256: version.stateSha256,
    currentAuthoredEditSeq: version.editSeq,
    revision: active.revision + 1,
    updatedAt: new Date().toISOString(),
  });
  state.activeWorldEntry = updated;
  state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((entry) =>
    entry.entryId === updated.entryId ? updated : entry));
  afterEntryAdvanced();
}
/**
 * Open the active world. Opening hands the whole shell to its opening screen first, so a failure
 * after that would leave "Opening your world" up with the place that asked for it gone: here a world
 * that does not open goes back to Your worlds, which says which and why (`worldDidNotOpen`). With no
 * saved world to go back to, and in the preview, the failure is the caller's to say, as before.
 */
async function mount(): Promise<void> {
  try {
    await mountWorld();
  } catch (error: unknown) {
    if (preview || state.savedWorldEntries.length === 0) throw error;
    const title = state.activeWorldEntry?.title ?? say('world.opening.thisWorld');
    disposeMountListeners(state);
    disposeRenderer(state);
    shell.removeAttribute('data-booting');
    shell.removeAttribute('aria-busy');
    await mountNoWorld({ retry: mount, failed: worldDidNotOpen(title, error) });
  }
}

async function mountWorld(): Promise<void> {
  shell.setAttribute('data-booting', '');
  shell.setAttribute('aria-busy', 'true');
  const retainedLoading = shell.querySelector<HTMLElement>('.startup-thinking') ?? buildStartupState();
  replace(shell, [retainedLoading]);
  disposeMountListeners(state);
  state.atlas?.binding.setControlsEnabled(false);
  state.disposeCharacter?.();
  state.disposeCharacter = null;
  state.disposeObjects?.();
  state.disposeObjects = null;
  state.disposeSocietyExperiment?.();
  state.disposeSocietyExperiment = null;
  state.disposeSocietyComparison?.();
  state.disposeSocietyComparison = null;
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
  const isAuthoredStarter = state.activeWorldEntry?.authoredScene != null;
  state.disposeEnvironmentSelection?.();
  state.disposeEnvironmentSelection = null;

  if (state.activeWorldEntry === null && current.islands.length === 0) {
    // Nothing to draw and no entry to draw it from. Stop every owner of the previous field
    // before replacing its DOM, or its frame loop and observers survive invisibly, and go to
    // the same saved-world surface start-up uses. A second full-page no-world screen said the
    // same thing in a different voice, and which one a person got depended on where their world
    // went. Nothing below this point is built, because all of it needs a world.
    disposeCompanionStage(state);
    disposeFormationWatch(state);
    disposeMountListeners(state);
    disposeRenderer(state);
    await mountNoWorld({
      refresh: true,
      retry: async () => {
        const session = state.session;
        if (session !== null) state.snapshot = await session.snapshot();
        await mount();
      },
    });
    shell.removeAttribute('data-booting');
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

  const retainActiveEntry = (updated: NonNullable<typeof state.activeWorldEntry>) => {
    const active = state.activeWorldEntry;
    if (active === null) {
      throw new Error('The saved world entry is no longer active.');
    }
    const retained = requireMetadataOnlyEntryUpdate(active, updated);
    state.activeWorldEntry = retained;
    state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((candidate) =>
      candidate.entryId === retained.entryId ? retained : candidate));
    return retained;
  };

  const intake = mountPersonalIntake({
    preview,
    credentials: currentCredentials, session: state.personalIntake, snapshot: current,
    media: state.previewSourceMedia,
    reloadSnapshot: () => currentSession.snapshot(),
    refreshWorld: async () => { state.snapshot = await currentSession.snapshot(); await mount(); },
    ...(() => {
      const personalWorld = preview ? undefined : personalWorldControl();
      return personalWorld === undefined ? {} : { personalWorld };
    })(),
    ...(state.activeWorldEntry === null ? {} : {
      getEntry: () => state.activeWorldEntry,
      attachSources: async (request) => {
        const client = state.worldEntries;
        if (client === null) throw new Error('The saved world is not connected.');
        return retainActiveEntry(await client.attachSources(request));
      },
      refreshEntry: async (entryId) => {
        const client = state.worldEntries;
        if (client === null) throw new Error('The saved world is not connected.');
        return retainActiveEntry(await client.entry(entryId));
      },
    }),
  });
  canvas.hidden = false;
  shell.removeAttribute('data-world-state');

  // A world with no personal source lays out no photographs: its scene is empty.
  const built = state.activeWorldEntry != null && state.activeWorldEntry.sourceKind !== 'personal'
    ? {
        scene: makeScene([], 1, current.stateVersion),
        omitted: Object.freeze([]),
        undrawable: new Map(),
      }
    : buildScene(
        state.arrivalVerified && state.activeWorldEntry?.arrival != null
          ? prioritizeOwnedArrival(current, state.activeWorldEntry.arrival.regionId)
          : current,
        ARRIVAL_PRESENTATION.layout_scale_milli / 1000,
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
  let makeWorld: MakeWorldSurface | null = null;
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

  const firstUse = createFirstUseGuidance(window.localStorage, {
    // A person who has already built in this world is not new, whatever this device remembers,
    // and a world drawn from their photographs, or generated from a recipe or a world kind, is not
    // empty: its places, its streets or its site are drawn content.
    worldHasContent: () => {
      const entry = state.activeWorldEntry;
      return entry !== null &&
        (entry.currentAuthoredEditSeq > 0 || entry.sourceAttachments.length > 0 ||
          built.scene.islands.length > 0 || entry.generatedGround != null || entry.generatedSite != null);
    },
    smallSquareOffered: () => objects.smallSquareOffered(),
  });
  let inputMode: FirstUseMode = 'converse';
  let reflectFirstUse = (): void => undefined;
  afterEntryAdvanced = () => { reflectFirstUse(); actions?.refresh(); };
  const finishFirstUse = (): void => {
    firstUse.complete();
    // `complete` also clears the per-page arrival prompt. That can change while the durable phase
    // is already complete, so reflection cannot depend only on the phase changing.
    reflectFirstUse();
  };

  // The Companion. The controller holds the turn, the panel renders it, and the confirmation
  // surface the write path builds is the only thing either of them can reach that writes.
  //
  // `askQuestion` is the read half: free text the parser cannot turn into a change is a question
  // about the library, and this is the only place holding the credential it takes to ask one.
  const companionAsk = new CompanionAskClient({
    ...currentCredentials, worldId: state.activeWorldEntry?.worldId ?? null,
  });
  // Where a place's name may go: read and decided on the two surfaces that show a place's name,
  // the detail pane and a Companion answer. Not in the preview, which has no decisions to read.
  const placeNames = preview ? undefined : new PlaceNameRightsClient(currentCredentials);
  let companionCityContext: CompanionCityContext | null = null;
  // The Companion's world actions, set once the action host exists (below the Companion's mount).
  let companionPlans: CompanionPlans | null = null;

  // The one thing the Companion may DO, and it is still not a write. `POST /selection/appearance`
  // reads an utterance as a bounded proposal drawn from the reviewed style catalogue; the world
  // style authority is what turns one into a preview, and the person's own Apply is what commits
  // it. Constructed here for the same reason as the two clients around it: this file holds the
  // credential and nothing under it does.
  const companionPropose = state.activeWorldEntry === null
    ? null
    : new CompanionProposalClient({
      ...currentCredentials, worldId: state.activeWorldEntry.worldId,
    });

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
  // The Companion mounts before the object and photo surfaces it can open. These callbacks are
  // assigned before any of the detached controls enter the document.
  let openStarterObjects = (): void => undefined;
  let openStarterPhotos = (): void => undefined;
  let runFirstUseAction = (): void => undefined;
  const companion = mountCompanion({
    state,
    onOpen: () => { environmentSelection.closePanels(); objects.close(); character.reach(); },
    engine: currentCompanion,
    evidence: currentEvidence,
    // A question is asked with the world's own society when it shows one, so a question about the
    // people in it is answered from its simulation.
    ask: (question) => companionAsk.ask(question, companionCityContext, environmentSelection.societyContext()),
    society: () => environmentSelection.societyNames(),
    openSimulation: (cited, answer) => environmentSelection.showSimulation(cited, answer),
    ...(companionPropose === null
      ? {}
      : {
        proposeAppearance: (utterance: string) => companionPropose.propose(utterance),
        planActions: (utterance: string) => companionPlans === null
          ? Promise.resolve({ route: 'fallback' } as const)
          : companionPlans.route(utterance),
      }),
    persistedMemory,
    rememberAnswer: async (answer) => {
      await companionMemory.rememberAnswer(answerToRemember(answer));
    },
    confirm: () => writePath.confirm,
    reflectShell: () => reflectShell(),
    onAnswered: finishFirstUse,
    isSystemSurfaceOpen: () =>
      shellState.primary === 'menu' || shellState.primary === 'options' ||
      shellState.primary === 'controls' || shellState.primary === 'character' ||
      shellState.primary === 'experiment' || shellState.primary === 'compare' ||
      shellState.primary === 'photos' || shellState.primary === 'make',
    onFirstUseAction: (action) => {
      const { activate } = action;
      if (activate === 'summon-companion') runFirstUseAction();
      // What Escape does on the welcome (composition/input-modes.ts), from a real control.
      else if (activate === 'dismiss') finishFirstUse();
      else if (activate === 'small-square') { firstUse.askSmallSquareRole(); reflectFirstUse(); }
      // The Create panel's square, with the role the person picked on the card.
      else if (activate === 'place-small-square') { finishFirstUse(); objects.arrangeSmallSquare(action.role); }
      else if (activate !== undefined) throw new Error(`no first-use action ${activate satisfies never}`);
    },
    ...(placeNames === undefined ? {} : { placeNames }),
    ...(isAuthoredStarter ? {
      starterActions: {
        onAddObject: () => openStarterObjects(),
        onAddPhotos: () => openStarterPhotos(),
      },
    } : {}),
  });
  runFirstUseAction = (): void => {
    finishFirstUse();
    companion.summon();
    companion.panel.showGreeting();
  };

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
    ...(state.activeWorldEntry === null ? {} : {
      client: new WorldObjectsClient({
        ...currentCredentials,
        worldId: state.activeWorldEntry.worldId,
        defaultVersionId: state.activeWorldEntry.authoredVersionId,
        savedEntry: activeEntryWriteBinding,
        onSavedEntryAdvanced: recordAuthoredEntryAdvance,
      }),
    }),
    scene: built.scene,
    ...(state.activeWorldEntry?.authoredScene === null ||
        state.activeWorldEntry?.authoredScene === undefined
      ? {}
      : {
          authoredRegion: {
            regionId: state.activeWorldEntry.authoredScene.region.regionId,
            ...state.activeWorldEntry.authoredScene.region.ground,
          },
        }),
    ...(state.activeWorldEntry?.declaredFloor == null
      ? {}
      : { declaredFloor: state.activeWorldEntry.declaredFloor }),
    showTravelStatus: (message, kind) => showTravelStatus(message, kind),
    isWorldPrimary: () => shellState.primary === 'world',
    onAuthoredEdit: (versionId) => environmentSelection.afterAuthoredEdit(versionId),
    districtPlacement: () => environmentSelection.districtPlacement(),
    onOpen: () => { companion.dismiss(); environmentSelection.closePanels(); character.reach(); },
    hideWritePathConfirm: () => writePath.confirm.hide(),
  });
  state.disposeObjects = () => objects.dispose();
  const environmentSelection = mountEnvironmentSelection({
    env,
    state,
    credentials: currentCredentials,
    ...(state.activeWorldEntry === null ? {} : {
      worldClient: new WorldObjectsClient({
        ...currentCredentials,
        worldId: state.activeWorldEntry.worldId,
        defaultVersionId: state.activeWorldEntry.authoredVersionId,
        savedEntry: activeEntryWriteBinding,
        onSavedEntryAdvanced: recordAuthoredEntryAdvance,
      }),
      // Placements go to the open world's versions, which is the world the version names.
      environmentClient: new EnvironmentSelectionClient({
        ...currentCredentials,
        worldId: state.activeWorldEntry.worldId,
      }),
    }),
    scene: built.scene,
    showStatus: (message, kind) => showTravelStatus(message, kind),
    ...(env.preview ? { admissionId: PREVIEW_NYC_OPEN_DATA_ADMISSION_ID } : {}),
    onSelect: (context) => { companionCityContext = context; },
    onAskAboutInhabitant: (question, asked) => companion.askAbout(
      question,
      () => companionAsk.ask(question, companionCityContext, environmentSelection.societyContext(), asked),
    ),
    onPanelOpen: () => { companion.dismiss(); objects.close(); character.reach(); },
    onObjects: () => objects.toggle(),
    // Somebody crossing in, leaving or turned away: one sentence where every notice appears.
    onVisitorNotice: (notice) => {
      const seeWho = notice.seeWho;
      actions?.host.toasts.show({
        message: notice.message,
        tone: notice.tone,
        // Long enough to read a sentence and reach See who before it goes.
        ...(seeWho === null ? {} : { action: { label: 'See who', run: seeWho }, durationMs: 10_000 }),
      });
    },
    onDistrictPlacementChange: () => {
      void objects.begin();
    },
    ...(state.activeWorldEntry === null ? {} : {
      flight: (world) => createSavedWorldFlight({
        ...world, credentials: currentCredentials, binding: () => state.atlas?.binding ?? null,
      }),
    }),
  });
  state.disposeEnvironmentSelection = () => environmentSelection.dispose();

  // Scene segments belong to source-backed geometry. A world with no personal source (the authored
  // starter, or one generated from a recipe) declares no source dependencies or reconstructed
  // scene, so it mounts no panel and makes no segment request.
  const sourceless = isAuthoredStarter || (state.activeWorldEntry != null
    && state.activeWorldEntry.sourceKind !== 'personal');
  const segments = sourceless ? null : mountSegments({
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
        showTravelStatus('Your world is still forming. Try again in a moment.', 'failure');
        return;
      }
      const resolution = targetAnchorId === null
        ? binding.navigateToIsland(toIslandId(targetIslandId), travelUsesReducedMotion())
        : binding.navigateToAnchor(toAnchorId(targetAnchorId), travelUsesReducedMotion());
      if (!resolution.ok) {
        const message = {
          'unknown-target': 'That source is not in this world.',
          'outside-resident-field': 'That region is outside the resident field.',
          'unlocated-placement': 'That source has no known place in this district yet, so there is nowhere here to arrive.',
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
    ...(placeNames === undefined ? {} : { placeNames }),
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
  const worldIdentity = state.activeWorldEntry === null ? null : buildWorldIdentity({
    entry: state.activeWorldEntry,
    personalIntake: intake.root,
    rename: async (title) => {
      const client = state.worldEntries;
      const active = state.activeWorldEntry;
      if (client === null || active === null) throw new Error('The saved world is not connected.');
      const updated = await client.rename(active, title);
      state.activeWorldEntry = updated;
      state.savedWorldEntries = Object.freeze(state.savedWorldEntries.map((entry) =>
        entry.entryId === updated.entryId ? updated : entry));
      return updated;
    },
    onOpenWorld: () => {
      companion.dismiss();
      environmentSelection.closePanels();
      objects.close();
      dispatchShell({ type: 'toggle-menu' });
    },
    onAddObject: () => {
      companion.dismiss();
      environmentSelection.closePanels();
      dispatchShell({ type: 'show-world' });
      objects.toggle();
    },
    onOpenPhotos: () => dispatchShell({ type: 'toggle-photos' }),
    onClosePhotos: () => dispatchShell({ type: 'toggle-photos' }),
  });
  // The Companion's starter offers are the registry's actions, run through the same path as a click.
  openStarterObjects = () => { if (actions !== null) void perform(actions.host, 'objects.open'); };
  openStarterPhotos = () => { if (actions !== null) void perform(actions.host, 'photos.open'); };
  const handleAtlasCommand = (command: AtlasCommand): void => {
    environmentSelection.closePanels();
    objects.close();
    if (command === 'companion') {
      dispatchShell({ type: 'show-world' });
      companion.toggle();
      return;
    }
    if (companion.panel.state() === 'open') companion.dismiss();
    if (command === 'index') dispatchShell({ type: 'toggle-index' });
    else if (command === 'character') dispatchShell({ type: 'toggle-character' });
    else if (command === 'map') dispatchShell({ type: 'toggle-map' });
    else if (command === 'options') dispatchShell({ type: 'toggle-options' });
    else dispatchShell({ type: 'toggle-controls' });
  };
  const worldMenu = buildWorldMenu({
    preview,
    onResume: () => dispatchShell({ type: 'toggle-menu' }),
    onWorld: () => {
      dispatchShell({ type: 'toggle-menu' });
      environmentSelection.openPanel('details');
    },
    ...(state.activeWorldEntry === null ? {} : {
      onCompare: () => dispatchShell({ type: 'toggle-compare' }),
    }),
    ...(state.worldEntries === null ? {} : {
      // Through the registry, so a create the workspace refuses is said and never opened.
      onMakeWorld: () => {
        if (actions === null) return;
        if (actionState(actions.host, actionSpec('world.make')).state === 'available') {
          dispatchShell({ type: 'toggle-menu' });
        }
        void perform(actions.host, 'world.make');
      },
    }),
    ...(preview ? {} : {
      // Back to Your worlds: keep this world's picture, then load the page afresh, which starts there.
      onYourWorlds: () => {
        const binding = state.atlas?.binding;
        const entryId = state.activeWorldEntry?.entryId ?? null;
        const leave = (): void => window.location.reload();
        if (binding === undefined || entryId === null) return leave();
        void keepWorldPicture(binding, entryId).finally(leave);
      },
    }),
    onCommand: handleAtlasCommand,
  });
  // Compare and the recorded-result reader load when first opened (composition/lazy-panel.ts).
  const societyExperiment = state.activeWorldEntry === null ? null : lazyPanel('Recorded result', async () =>
    (await import('./composition/society-experiment-result.js')).mountSocietyExperimentResult({
      getWorldId: () => state.activeWorldEntry?.worldId ?? null,
      getVersionId: () => state.activeWorldEntry?.authoredVersionId ?? null,
      credentials: currentCredentials,
      onClose: () => dispatchShell({ type: 'toggle-experiment' }),
    }));
  state.disposeSocietyExperiment = societyExperiment === null
    ? null
    : () => societyExperiment.dispose();
  const societyComparison = state.activeWorldEntry === null ? null : lazyPanel('Compare', async () =>
    (await import('./composition/society-comparison-mount.js')).mountSocietyComparison({
      getWorldId: () => state.activeWorldEntry?.worldId ?? null,
      getVersionId: () => state.activeWorldEntry?.authoredVersionId ?? null,
      credentials: currentCredentials,
      onClose: () => dispatchShell({ type: 'toggle-compare' }),
      onRecordedResult: () => dispatchShell({ type: 'toggle-experiment' }),
    }));
  state.disposeSocietyComparison = societyComparison === null
    ? null
    : () => societyComparison.dispose();
  // The thing card is what Selected shows first for whatever is picked: what it is, what mind runs
  // it (changed in place for a person), how it looks and where it came from.
  environmentSelection.useInhabitantView(mountThingCard({
    selection: environmentSelection,
    compare: societyComparison === null ? null : () => { if (actions !== null) void perform(actions.host, 'compare.open'); },
    shell: env.shell,
    credentials: currentCredentials,
  }).view);
  const character = mountCharacter({ env, state, onClose: () => dispatchShell({ type: 'toggle-character' }) });
  state.disposeCharacter = () => character.dispose();
  const mapPeek = new MapPeek({
    isMapActive: () => shellState.camera === 'map',
    enterMap: () => dispatchShell({ type: 'toggle-map' }),
    leaveMap: () => dispatchShell({ type: 'toggle-map' }),
    toggleMap: () => handleAtlasCommand('map'),
    schedule: (run, ms) => window.setTimeout(run, ms),
    cancel: (handle) => window.clearTimeout(handle),
  });
  reflectFirstUse = (): void => {
    const prompt = firstUse.prompt(inputMode);
    companion.panel.setFirstUsePrompt(prompt);
    shell.dataset['firstUse'] = firstUse.phase();
    const welcomeVisible = inputMode === 'converse' && prompt?.kind === 'welcome';
    shell.toggleAttribute('data-welcome', welcomeVisible);
    environmentSelection.setWelcomeVisible(welcomeVisible);
  };
  reflectFirstUse();
  const mapReturn = el('button', { type: 'button', text: 'Return  M' });
  mapReturn.addEventListener('click', () => handleAtlasCommand('map'));
  const mapCaption = el('section', {
    class: 'map-caption',
    'aria-label': 'Map orientation',
  }, [
    el('strong', { text: 'Map' }),
    el('span', { text: MAP_ORIENTATION_CAPTION }),
    mapReturn,
  ]);
  mapCaption.hidden = true;
  const viewportBoundary = el('aside', {
    class: 'viewport-boundary',
    'aria-labelledby': 'viewport-boundary-title',
  }, [
    el('p', { class: 'overlay-kicker', text: 'Window size' }),
    el('h1', { id: 'viewport-boundary-title', text: 'This window is too narrow' }),
    // Not "at least 60rem". A rem is the threshold this file's media query is written in, and
    // nobody reading this can measure one; what they can do is drag the edge until it opens.
    el('p', {
      text:
        'Exulanica is designed for laptop and desktop windows. '
        + 'Widen this window to continue.',
    }),
  ]);
  let status: MountedStatusAndInspector;
  // Look: the style pack a generated town is drawn in, chosen in the Look sheet (ui/look-sheet.ts)
  // and saved as an appearance version (`useStylePack`). Only generated towns are drawn in packs.
  const lookAccess = state.credentials;
  const lookOffered = state.activeWorldEntry?.generatedGround != null && lookAccess !== null && state.worldStyles !== null;
  let openLook: () => Promise<void> = async () => undefined;
  const appearance = mountAppearance({
    env,
    state,
    applyProofLens: () => status.applyProofLens(),
    setCompanionAppearance: () => companion.applyAppearance(),
    onCloseOptions: () => dispatchShell({ type: 'show-world' }),
    onShowControls: () => dispatchShell({ type: 'toggle-controls' }),
    onCloseControls: () => dispatchShell({ type: 'toggle-controls' }),
    onShowCustomize: () => dispatchShell({ type: 'toggle-options' }),
    ...(lookOffered ? { onChangeLook: () => void openLook() } : {}),
  });
  let library: Promise<LookLibrary> | null = null;
  const lookLibrary = (): Promise<LookLibrary> => (library ??= readLookLibrary(lookAccess!));
  /** The exact pack this world's appearance names, by digest; null for none, which is the host's default. */
  const boundLook = (): WorldStylePackBinding | null => state.worldStyleConnection?.state.current.stylePack ?? null;
  const reflectLook = (): void => {
    if (!lookOffered) { appearance.options.setLook(null); return; }
    void lookLibrary().then(
      async (looks) => {
        const now = await looks.now(boundLook());
        const title = looks.options.find((option) => option.packId === now.packId)?.title ?? null;
        const earlier = now.how.earlier ?? null;
        appearance.options.setLook(title === null || earlier === null ? title : `${title}, version ${earlier.version}`);
      },
      () => { library = null; appearance.options.setLook(null); },
    );
  };
  reflectLook();
  openLook = async () => {
    let looks: LookLibrary;
    let now: Awaited<ReturnType<LookLibrary['now']>>;
    try {
      looks = await lookLibrary();
      now = await looks.now(boundLook());
    } catch {
      library = null;
      appearance.options.reportWorldLifecycle('failed', 'The looks this server offers could not be read. Try again in a moment.');
      return;
    }
    dispatchShell({ type: 'show-world' });
    shell.querySelector('section.look-sheet')?.remove();
    const offered = looks.options;
    const bindingOf = (packId: string): WorldStylePackBinding | null => looks.binding(packId);
    // Whether the world behind the sheet is drawn in a look other than its own, from browsing.
    let browsedAway = false;
    const sheet = buildLookSheet({
      worldTitle: state.activeWorldEntry?.title ?? 'This world',
      onBrowse: (option, isNow) => {
        browsedAway = !isNow;
        // The look drawn now is drawn exactly as the world names it, an earlier version included;
        // any other at the version the host offers now.
        void redrawWorldLook(isNow ? boundLook() : bindingOf(option.packId)).then((done) => {
          // A world that cannot be drawn in another look while open is shown by its pictures.
          if (!done.drawn) sheet.setLive(false);
        });
      },
      onUse: async (option, say) => {
        const binding = bindingOf(option.packId)!;
        // Moving from an earlier version of the same pack is said by its number.
        const named = now.how.earlier?.packId === option.packId ? `version ${binding.version} of ${option.title}` : option.title;
        const result = await appearance.useStylePack(binding);
        if (!result.saved) return result.words;
        browsedAway = false;
        now = await looks.now(boundLook());
        sheet.show(offered, now.packId, now.how);
        reflectLook();
        // Saving names the pack; drawing the open world in it is the redraw's (LOOK's
        // composition/world-look-redraw.ts), which keeps the old look up until the new one is ready.
        say(`${result.words} Drawing the world in ${named}…`);
        const drawn = await redrawWorldLook(binding);
        return drawn.drawn
          ? `${result.words} The world is now drawn in ${named}.`
          : `${result.words} It could not be drawn now${drawn.reason === null ? '' : ` (${drawn.reason})`}, so it is drawn in ${named} the next time the world opens.`;
      },
      onClose: () => {
        // Leaving without Use puts the world back in its own look, exactly the version it names.
        if (browsedAway) void redrawWorldLook(boundLook());
        sheet.root.remove();
        canvas.focus({ preventScroll: true });
      },
    });
    shell.append(sheet.root);
    sheet.show(offered, now.packId, now.how);
    sheet.focus();
  };

  status = mountStatusAndInspector({
    env,
    state,
    snapshot: current,
    built,
    showWorld: () => dispatchShell({ type: 'show-world' }),
    showTravelStatus,
  });
  // Surfaces that live in a region are placed by the layout below; the rest keep their own place
  // until they move onto the system (ui/system/layout.ts).
  layout?.dispose();
  layout = createLayout(shell);
  replace(shell, [
    stage,
    chrome.reticle,
    ...(worldIdentity === null ? [] : [worldIdentity.photosDrawer]),
    worldIndex.root,
    detail.root,
    environmentSelection.root,
    worldMenu.root,
    ...(societyExperiment === null ? [] : [societyExperiment.root]),
    ...(societyComparison === null ? [] : [societyComparison.root]),
    minimap.root,
    appearance.options.root,
    appearance.settings.root,
    character.root,
    character.gestureRoot,
    viewportBoundary,
    ...Object.values(layout.regions),
    retainedLoading,
  ]);
  if (worldIdentity !== null) layout.place('top-bar', worldIdentity.root);
  const closeWorldPanels = (): void => environmentSelection.closePanels();
  const worldNav = environmentSelection.root.querySelector<HTMLElement>(':scope > .world-local-nav');
  if (worldNav !== null) layout.place('inspector', worldNav, { attachment: true });
  for (const worldPanel of environmentSelection.root.querySelectorAll<HTMLElement>(':scope > .world-panel')) {
    layout.place('inspector', worldPanel, { close: closeWorldPanels });
  }
  layout.place('inspector', objects.panel.root, { close: () => objects.close() });
  layout.place('inspector', status.inspectorRoot, {
    close: () => { state.atlas?.binding.endSceneInspection(); status.hideInspector(); },
  });
  layout.place('sheet', writePath.confirm.root, { close: () => writePath.confirm.hide() });
  layout.place('sheet', objects.confirm.root, { close: () => objects.confirm.hide() });
  layout.place('dock', companion.panel.root);
  layout.place('toast', travelStatus);
  layout.place('hud', formation.root);
  layout.place('hud', mapCaption);
  if (segments !== null) layout.place('hud', segments.root);
  layout.adopt('.world-traffic-note, .reconstruction-loading', 'hud');

  // Every action the rail, the top bar's clock and the palette offer is a registry entry bound
  // here to the same call its older control makes (ui/actions/registry.ts).
  actions?.dispose();
  const inspectorPanel = (id: string): HTMLElement | null => layout?.regions.inspector.querySelector(`#${id}`) ?? null;
  const panelOpen = (id: string): boolean => inspectorPanel(id)?.hidden === false;
  const offerPhotos = (): boolean => state.activeWorldEntry !== null && state.activeWorldEntry.takesPhotographs !== false;
  // A Companion plan step's request, sent once the person confirmed the plan. The route is the
  // registry entry's (`ui/actions/planned.ts`); the world scope is this page's. A world edit is
  // then recorded as the objects panel records its own: the saved entry advances, the objects are
  // read again and the people hear of the edit.
  const planClient = state.activeWorldEntry === null
    ? null
    : new CompanionActionsClient({ ...currentCredentials, worldId: state.activeWorldEntry.worldId });
  const PLANNED_EDITS = new Set(['objects.place', 'objects.move', 'objects.remove', 'objects.undo', 'arrangements.place']);
  const sendPlanned = async (
    request: PlannedRequest,
  ): Promise<{ readonly status: number; readonly body: unknown }> => {
    const active = state.activeWorldEntry;
    if (planClient === null || active === null) throw new Error('No world is open to change.');
    const binding = PLANNED_EDITS.has(request.actionId) ? activeEntryWriteBinding() : null;
    const sent = await planClient.send({
      method: request.method,
      path: openWorldPath(request.path, active.worldId, 'a planned change'),
      body: request.body,
    });
    const body = sent.body;
    if (binding !== null) {
      const version = parseVersion(request.actionId === 'arrangements.place' ? (body as { version: unknown }).version : body);
      await recordAuthoredEntryAdvance(version, binding);
      await objects.begin(version.versionId);
      await environmentSelection.afterAuthoredEdit(version.versionId);
    }
    return sent;
  };
  actions = mountActions({
    layout,
    credentials: currentCredentials,
    send: sendPlanned,
    worldId: state.activeWorldEntry?.worldId ?? null,
    versionId: () => state.activeWorldEntry?.authoredVersionId ?? null,
    people: environmentSelection.people,
    clockSlot: worldIdentity?.root.querySelector<HTMLElement>('.world-add-object') ?? null,
    searchSlot: worldIdentity?.root.querySelector<HTMLElement>('.world-open-menu') ?? null,
    bindings: {
      'objects.open': {
        run: () => {
          companion.dismiss();
          environmentSelection.closePanels();
          dispatchShell({ type: 'show-world' });
          objects.toggle();
        },
        active: () => !objects.panel.root.hidden,
      },
      'objects.undo': {
        run: () => objects.undo(),
        blocked: () => (objects.undoable() ? null : 'There is nothing left to take back.'),
      },
      'people.open': {
        run: () => {
          if (panelOpen('world-panel-nearby')) environmentSelection.closePanels();
          else { dispatchShell({ type: 'show-world' }); environmentSelection.openPanel('nearby'); }
        },
        active: () => panelOpen('world-panel-nearby'),
      },
      'people.decides': {
        run: () => {
          if (panelOpen('world-panel-decides')) environmentSelection.closePanels();
          else { companion.dismiss(); dispatchShell({ type: 'show-world' }); environmentSelection.openPanel('decides'); }
        },
        offered: () => environmentSelection.people.clock().society === 'present',
        active: () => panelOpen('world-panel-decides'),
      },
      'people.bring-in': {
        // Open People first, so whoever arrives, or the reason nobody did, is in view.
        run: () => {
          dispatchShell({ type: 'show-world' });
          if (!panelOpen('world-panel-nearby')) environmentSelection.openPanel('nearby');
          return environmentSelection.people.bringIn();
        },
        offered: () => environmentSelection.people.clock().society !== 'unconnected',
        blocked: () => (environmentSelection.people.clock().society === 'present' ? 'People already live here.' : null),
      },
      'clock.play': {
        run: () => environmentSelection.people.play(),
        offered: () => environmentSelection.people.clock().society === 'present',
        blocked: () => {
          const clock = environmentSelection.people.clock();
          return clock.busy ? 'Working.' : clock.playEligible ? null : 'This world cannot play on its own here.';
        },
      },
      'clock.pause': {
        run: () => environmentSelection.people.pause(),
        offered: () => environmentSelection.people.clock().society === 'present',
        blocked: () => (environmentSelection.people.clock().busy ? 'Working.' : null),
      },
      'clock.advance': {
        run: () => environmentSelection.people.advance(),
        offered: () => environmentSelection.people.clock().society === 'present',
        blocked: () => environmentSelection.people.clock().advanceBlocked,
      },
      ...(societyComparison === null ? {} : {
        'compare.open': {
          run: () => dispatchShell({ type: 'toggle-compare' }),
          active: () => shellState.primary === 'compare',
        },
      }),
      'companion.open': {
        run: () => handleAtlasCommand('companion'),
        active: () => companion.panel.state() === 'open',
      },
      'map.open': { run: () => handleAtlasCommand('map'), active: () => shellState.camera === 'map' },
      'library.open': { run: () => handleAtlasCommand('index'), active: () => shellState.primary === 'index' },
      'character.open': {
        run: () => handleAtlasCommand('character'),
        active: () => shellState.primary === 'character',
      },
      'photos.open': {
        run: () => dispatchShell({ type: 'toggle-photos' }),
        offered: offerPhotos,
        active: () => shellState.primary === 'photos',
      },
      'about.open': {
        run: () => { dispatchShell({ type: 'show-world' }); environmentSelection.openPanel('details'); },
      },
      ...(state.worldEntries === null ? {} : {
        'world.make': { run: () => dispatchShell({ type: 'toggle-make' }) },
      }),
      'design.open': { run: () => handleAtlasCommand('options'), active: () => shellState.primary === 'options' },
      'settings.open': {
        run: () => handleAtlasCommand('controls'),
        active: () => shellState.primary === 'controls',
      },
      'menu.open': { run: () => dispatchShell({ type: 'toggle-menu' }), active: () => shellState.primary === 'menu' },
    },
  });
  // The objects panel's own writes follow the same descriptors as the registry's actions.
  const gateObjects = (): void => {
    objects.setOperationGate((operation) => actions?.objectGate(operation) ?? null);
    environmentSelection.people.setGate((operation) => actions?.peopleGate(operation) ?? null);
  };
  actions.host.onChange(gateObjects);
  gateObjects();
  const reflectMake = (): void => {
    if (actions !== null) worldMenu.setMake(actionState(actions.host, actionSpec('world.make')));
  };
  actions.host.onChange(reflectMake);
  // The Companion's plans: the sheet in the sheet region, and the route the Companion asks first.
  if (planClient !== null && layout !== null) {
    const sheet = buildPlanSheet({
      onConfirm: () => companionPlans?.confirm(),
      onCancel: () => companionPlans?.cancel(),
      onChoose: (clarification, value) => companionPlans?.choose(clarification, value),
      onPlay: () => {
        if (actions !== null) void perform(actions.host, 'clock.play');
        companionPlans?.cancel();
      },
    });
    layout.place('sheet', sheet.root, { close: () => companionPlans?.cancel() });
    const planPage = (): ActionPageContext | null => {
      const active = state.activeWorldEntry;
      if (active === null) return null;
      const here = objects.selectionContext();
      return {
        versionId: active.authoredVersionId,
        baseStateSha256: active.authoredStateSha256,
        // The person's own choice for anything added, never inferred: the plan asks them.
        originRole: null,
        context: {
          ...(here.placement === null ? {} : { placement: here.placement }),
          ...(here.viewer === null ? {} : { viewer: here.viewer }),
          ...(here.selected_object_id === null ? {} : { selected_object_id: here.selected_object_id }),
        },
        savedEntry: {
          entry_id: active.entryId,
          base_revision: active.revision,
          authored_state_sha256: active.authoredStateSha256,
          authored_edit_seq: active.authoredEditSeq,
          ...(active.styleVersionId == null ? {} : { style_version_id: active.styleVersionId }),
        },
      };
    };
    companionPlans = mountCompanionPlans({
      client: () => planClient,
      page: planPage,
      host: () => actions?.host ?? null,
      sheet,
      afterTime: () => environmentSelection.people.reread(),
      particular: (step) => objects.titleOf({
        assetKey: typeof step.action['asset_key'] === 'string' ? step.action['asset_key'] : null,
        objectId: typeof step.action['object_id'] === 'string' ? step.action['object_id'] : null,
      }),
      waitMs: COMPANION_DRAFT_WAIT_MS,
      onSaid: (utterance, said) => companion.panel.showAnswer(plannedAnswer(utterance, said)),
    });
  }
  reflectMake();
  void intake.begin();

  let reflectedPrimary = shellState.primary;
  reflectShell = (): void => {
    const libraryOpened = shellState.primary === 'index' && reflectedPrimary !== 'index';
    reflectedPrimary = shellState.primary;
    if (shellState.primary !== 'world') {
      environmentSelection.closePanels();
      objects.close();
      state.atlas?.binding.endSceneInspection();
      status.hideInspector();
    }
    actions?.changed();
    shell.setAttribute('data-primary', shellState.primary);
    shell.setAttribute('data-camera', shellState.camera);
    chrome.setIndexOpen(shellState.primary === 'index');
    worldIndex.root.setAttribute('aria-hidden', shellState.primary === 'index' ? 'false' : 'true');
    appearance.options.setVisible(shellState.primary === 'options');
    appearance.settings.setVisible(shellState.primary === 'controls');
    worldMenu.setVisible(shellState.primary === 'menu');
    societyExperiment?.setVisible(shellState.primary === 'experiment');
    societyComparison?.setVisible(shellState.primary === 'compare');
    worldIdentity?.setPhotosVisible(shellState.primary === 'photos');
    if (shellState.primary === 'make') {
      if (makeWorld === null || !makeWorld.isConnected) {
        makeWorld = showWorldRecipes(() => dispatchShell({ type: 'step-back' }));
      }
    } else if (makeWorld !== null) {
      makeWorld.remove();
      makeWorld = null;
    }
    const systemSurfaceOpen = shellState.primary === 'menu' || shellState.primary === 'options' ||
      shellState.primary === 'controls' || shellState.primary === 'character' ||
      shellState.primary === 'experiment' || shellState.primary === 'compare' ||
      shellState.primary === 'photos' || shellState.primary === 'make';
    // Every region but the toasts sits behind a major surface, so Tab cannot reach the rail or an
    // inspector panel under it.
    const modalBackground = [
      stage,
      detail.root,
      formation.root,
      companion.panel.root,
      writePath.confirm.root,
      mapCaption,
      travelStatus,
      ...(worldIdentity === null ? [] : [worldIdentity.root]),
      ...(layout === null ? [] : MODAL_BACKGROUND_REGIONS.map((region) => layout!.regions[region])),
    ];
    // On close, release the command bar before the dialog restores focus to its trigger. On open,
    // move focus into the dialog before making that same trigger inert.
    if (!systemSurfaceOpen) for (const surface of modalBackground) surface.inert = false;
    appearance.options.setVisible(shellState.primary === 'options');
    appearance.settings.setVisible(shellState.primary === 'controls');
    character.setVisible(shellState.primary === 'character');
    if (systemSurfaceOpen) for (const surface of modalBackground) surface.inert = true;
    // The closed Library is transparent, not hidden, so it stays inert unless it is the one open.
    worldIndex.root.inert = shellState.primary !== 'index' || systemSurfaceOpen;
    // Opened from the rail, the palette or I, the Library takes the keyboard with it.
    if (libraryOpened) worldIndex.root.querySelector<HTMLElement>('button, input')?.focus({ preventScroll: true });
    mapCaption.hidden = shellState.camera !== 'map';
    // Only while traversing the ground: the Map is already the whole answer, and a plate has the
    // world behind it rather than under it.
    minimap.root.hidden =
      !state.preferences.regionMinimap ||
      shellState.primary !== 'world' ||
      shellState.camera !== 'ground';
    detail.root.hidden = shellState.primary !== 'index' || shellState.detailId === null;
    state.atlas?.binding.setMapMode(shellState.camera === 'map');
    // Keyboard ownership is exclusive: a visible surface and locomotion never consume the same
    // key state. Appearance changes remain live, but walking resumes only after returning to the
    // ready world.
    state.atlas?.binding.setControlsEnabled(
      shellState.camera === 'ground' &&
      shellState.primary === 'world' &&
      companion.panel.state() !== 'open',
    );
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
  const geographicDistrict = renderer.atlas.binding.ownedDistrict !== null;
  void character.attach(renderer.atlas.binding);
  if (geographicDistrict && segments !== null) {
    segments.root.hidden = true;
    segments.root.style.display = 'none';
  }

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
    status: segments === null
      ? status
      : segmentsFirst(status, (clientX, clientY) => segments.resolveAt(clientX, clientY)),
    chrome,
    worldIndex,
    detail,
    mapPeek,
    firstUse,
    shellState: () => shellState,
    dispatchShell,
    handleAtlasCommand,
    toggleDecides: () => { if (actions !== null) void perform(actions.host, 'people.decides'); },
    showTravelStatus,
    travelUsesReducedMotion,
    setInputMode: (mode) => { inputMode = mode; },
    reflectFirstUse: () => reflectFirstUse(),
    applyPreferences: (next) => appearance.applyPreferences(next),
  });
  void environmentSelection.begin();

  // Nothing is asked unprompted. The Companion arrives when it is called, and until then the
  // world is the whole of what is on screen.

  renderer.reportPlacementDisagreement();

  // After the renderer, because every object it draws needs a binding to draw into.
  void objects.begin(state.activeWorldEntry?.authoredVersionId);
  if (!geographicDistrict) void segments?.begin();

  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  retainedLoading.remove();
  shell.removeAttribute('aria-busy');
  shell.removeAttribute('data-booting');
  // A picture of this world for its card on Your worlds, once it has drawn for a few seconds.
  const pictured = state.activeWorldEntry?.entryId ?? null;
  if (!preview && pictured !== null) {
    window.setTimeout(() => {
      const binding = state.atlas?.binding;
      if (binding !== undefined && state.activeWorldEntry?.entryId === pictured) void keepWorldPicture(binding, pictured);
    }, WORLD_PICTURE_DELAY_MS);
  }
  if (preview) {
    const { companionPreviewScenario, showCompanionPreviewScenario } =
      await import('./dev/companion-scenarios.js');
    const scenario = companionPreviewScenario(window.location.search);
    if (scenario !== null) {
      finishFirstUse();
      companion.summon();
      showCompanionPreviewScenario(companion.panel, scenario);
    }
  }
}

function syncIndexRoute(facets: IndexFacets): void {
  const url = new URL(window.location.href);
  for (const key of FACET_KEYS) url.searchParams.delete(key);
  const encoded = new URLSearchParams(encodeFacets(facets));
  for (const [key, value] of encoded) url.searchParams.set(key, value);
  window.history.replaceState(window.history.state, '', url);
}

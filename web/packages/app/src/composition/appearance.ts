/**
 * Customize and Settings: the two panels that change how the world looks, and the authority the
 * change is saved against.
 *
 * Everything about a world style lives here, from the local renderer preview through the
 * reviewed server preview, Apply, rollback and the upstream proposal inbox, because all of them
 * are the same
 * decision seen from different distances, and splitting them would put the discard of a local
 * preview in one module and the discard of the server's copy in another.
 *
 * The module writes `state.preferences`, `state.settingsStylePreviewId`, the three world-style
 * fields and `state.stopWorldStyleProposalInbox`. It reads `state.atlas` and never stores it: the
 * renderer is rebuilt on every mount and a held binding would be a disposed one.
 */

import { ApiError } from '@exulanica/graph-client';
import {
  readSourceLight,
  sourceLightParameters,
  worldArtProfile,
  worldStyleControls,
} from '@exulanica/presentation';

import { writePreferences, type AtlasPreferences } from '../preferences.js';
import { applyDocumentAppearance, applyDocumentWorldStyle } from '../theme.js';
import { buildControlsGuide } from '../ui/controls-guide.js';
import { buildOptions } from '../ui/options.js';
import {
  WorldStyleContractError,
  type ActiveWorldStylePreview,
  type WorldStyleClient,
  type WorldStyleConnection,
  type WorldStyleVersionRecord,
} from '../world-style-api.js';
import {
  worldStyleProposalInbox,
  worldStyleProposalOutcomes,
  type WorldStyleProposalOutcomeKind,
} from '../world-style-proposals.js';
import type { AppEnvironment, SessionState } from './session-state.js';

export interface AppearanceDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  /**
   * Re-resolve the proof lens against the theme that has just changed.
   *
   * Late-bound because the status panel is built after this one, exactly as it was when both were
   * closures in one function: a new theme is a new palette, so a lit lens has to be re-resolved
   * from it, and off stays off.
   */
  readonly applyProofLens: () => void;
  /** Push the companion appearance the new preferences describe. Owned by `companion.ts`. */
  readonly setCompanionAppearance: () => void;
  readonly onCloseOptions: () => void;
  readonly onShowControls: () => void;
  readonly onCloseControls: () => void;
  readonly onShowCustomize: () => void;
}

export interface MountedAppearance {
  readonly options: ReturnType<typeof buildOptions>;
  readonly settings: ReturnType<typeof buildControlsGuide>;
  applyPreferences(next: AtlasPreferences): void;
  dispose(): void;
}

export function mountAppearance(deps: AppearanceDependencies): MountedAppearance {
  const { env, state } = deps;

  let optionsView: ReturnType<typeof buildOptions>;
  let serverPreviewTimer: number | null = null;
  let previewSequence = 0;
  /*
   * True while a proposal is being put into the panel's own controls.
   *
   * The panel reports every control move through `onPreview`, and `onPreview` debounces a
   * SETTINGS preview onto the authority. Without this, staging a Companion proposal would
   * silently replace it with a settings-origin preview of the same values 220 ms later, and the
   * provenance the person was shown would be gone by the time they pressed Apply.
   */
  let stagingProposal = false;

  const reflectLocalWorldPreview = (
    candidate: AtlasPreferences,
    origin: 'settings' | 'companion' = 'settings',
  ): boolean => {
    if (state.atlas === null) return false;
    const styleChanged = candidate.worldArtProfile !== state.preferences.worldArtProfile ||
      candidate.worldArtProfileVersion !== state.preferences.worldArtProfileVersion ||
      JSON.stringify(candidate.worldStyleParameters) !==
        JSON.stringify(state.preferences.worldStyleParameters);
    if (!styleChanged) return false;
    if (state.settingsStylePreviewId !== null) {
      state.atlas.binding.discardArtProfilePreview(state.settingsStylePreviewId);
      state.settingsStylePreviewId = null;
    }
    const candidateProfile = worldArtProfile(
      candidate.worldArtProfile,
      candidate.worldArtProfileVersion,
      candidate.worldStyleParameters,
    );
    const previewSession = state.atlas.binding.previewArtProfile(
      candidateProfile,
      origin,
      candidate.worldStyleParameters,
    );
    if (!previewSession.validation.ok) return false;
    state.settingsStylePreviewId = previewSession.sessionId;
    applyDocumentWorldStyle(candidateProfile);
    return true;
  };

  const previewOnServer = async (
    candidate: AtlasPreferences,
  ): Promise<ActiveWorldStylePreview | null> => {
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
        presentWorldStyleAuthority(
          optionsView, state.worldStyleConnection, state.worldStyleFailure, active,
        );
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

  /**
   * Say what became of a proposal that came from somewhere other than this panel.
   *
   * Read off the ACTIVE PREVIEW rather than from a variable held here, because the client is
   * what knows which proposal is current: a stale base makes it discard and refine silently, and
   * a local copy would name the attempt before that one. Settings changes report nothing, which
   * is not an omission: nobody is waiting to hear what happened to a slider they moved.
   */
  const reportProposalOutcome = (
    active: ActiveWorldStylePreview | null,
    kind: WorldStyleProposalOutcomeKind,
    detail: string,
  ): void => {
    if (active === null || active.request.origin === 'settings') return;
    worldStyleProposalOutcomes.report({
      originReference: active.request.originReference ?? '',
      kind,
      detail,
    });
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
      const { sampleSources } = await import('../media-sampler.js');
      const reading = readSourceLight(await sampleSources(sources));
      if (reading.sampled === 0) return null;
      return sourceLightParameters(reading, state.preferences.worldStyleParameters);
    },
    onPreview: (candidate) => {
      env.shell.setAttribute('data-vignette', candidate.vignette);
      state.atlas?.binding.setFieldOfView(candidate.fieldOfView);
      state.atlas?.binding.setSensitivityMultiplier(candidate.mouseSensitivity);
      // A staged proposal already HAS a reviewed preview on the authority, and it is a
      // companion-origin one. The local renderer preview still runs, because the person has to
      // see what they are being asked about.
      if (reflectLocalWorldPreview(candidate) && !stagingProposal) queueServerPreview(candidate);
    },
    onWorldDiscard: (restored) => {
      if (serverPreviewTimer !== null) {
        window.clearTimeout(serverPreviewTimer);
        serverPreviewTimer = null;
      }
      previewSequence += 1;
      if (state.settingsStylePreviewId !== null && state.atlas !== null) {
        state.atlas.binding.discardArtProfilePreview(state.settingsStylePreviewId);
        state.settingsStylePreviewId = null;
      }
      applyDocumentWorldStyle(env.previewArtProfile ?? worldArtProfile(
        restored.worldArtProfile,
        restored.worldArtProfileVersion,
        restored.worldStyleParameters,
      ));
      const client = state.worldStyles;
      if (client !== null) {
        // Read BEFORE the discard, because `discardActive` clears it. A proposal thrown away
        // with nobody able to say which one it was is a proposal the Companion cannot record.
        const discarded = client.activePreview();
        void client.discardActive().then(() => {
          reportProposalOutcome(discarded, 'discarded', 'The proposed design was not kept.');
          syncWorldStyleConnection(state, client);
          presentWorldStyleAuthority(
            optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
          );
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
          // Still open, not refused: the client has already made a refinement carrying the same
          // origin reference, and it is that one a person now confirms.
          reportProposalOutcome(
            result.preview,
            'previewed',
            'The saved world changed elsewhere, so the proposal was made again against it.',
          );
          return false;
        }
        presentWorldStyleAuthority(
          optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
        );
        optionsView.reportWorldLifecycle('saved');
        reportProposalOutcome(
          active, 'accepted', `Applied as revision ${result.version.revision}.`,
        );
        return true;
      } catch (error) {
        const detail = describeWorldStyleFailure(error);
        optionsView.reportWorldLifecycle('failed', detail);
        reportProposalOutcome(active, 'refused', detail);
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
        presentWorldStyleAuthority(
          optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
        );
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
    onClose: deps.onCloseOptions,
    onShowControls: deps.onShowControls,
  });
  presentWorldStyleAuthority(optionsView, state.worldStyleConnection, state.worldStyleFailure, null);
  state.stopWorldStyleProposalInbox?.();
  state.stopWorldStyleProposalInbox = worldStyleProposalInbox.subscribe(async (proposal) => {
    const client = state.worldStyles;
    if (client === null) {
      const detail =
        state.worldStyleFailure ??
        'World style authority is unavailable. The proposal was not previewed.';
      optionsView.reportWorldLifecycle('failed', detail);
      worldStyleProposalOutcomes.report({
        originReference: proposal.originReference ?? '',
        kind: 'refused',
        detail,
      });
      return;
    }
    if (proposal.scope?.kind === 'region') {
      const detail =
        'Regional style proposals require a regional renderer preview and are not shown as a global change.';
      optionsView.reportWorldLifecycle('failed', detail);
      worldStyleProposalOutcomes.report({
        originReference: proposal.originReference ?? '',
        kind: 'refused',
        detail,
      });
      return;
    }
    try {
      optionsView.reportWorldLifecycle('checking', 'Validating the upstream proposal…');
      const active = await client.previewUpstream(proposal);
      const candidate = preferencesForWorldReference(
        state.preferences,
        active.preview.candidate.globalStyle,
      );
      /*
       * Staged into the panel's OWN controls rather than pushed in as the applied state.
       *
       * `setPreferences` moves the panel's applied baseline as well as its draft, which leaves
       * `worldDirty()` false, and the panel disables Apply and Undo when it is false. So the
       * obvious version of this line rendered a proposal nobody could accept and whose Undo
       * would have restored it: the inbox had never been fed, so nothing had ever pressed those
       * buttons. Moving the controls instead means a proposal and a hand-moved slider arrive at
       * Apply by exactly the same route, and there is no path to a write that a person could not
       * have taken themselves.
       */
      stagingProposal = true;
      let staged = false;
      try {
        staged = stageWorldProposal(optionsView, candidate);
      } finally {
        stagingProposal = false;
      }
      if (!staged) {
        const detail =
          'That design cannot be shown on this panel, so it was not proposed and nothing changed.';
        await client.discardActive();
        syncWorldStyleConnection(state, client);
        presentWorldStyleAuthority(
          optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
        );
        optionsView.reportWorldLifecycle('failed', detail);
        worldStyleProposalOutcomes.report({
          originReference: proposal.originReference ?? '',
          kind: 'refused',
          detail,
        });
        return;
      }
      reflectLocalWorldPreview(
        candidate,
        proposal.origin === 'companion' ? 'companion' : 'settings',
      );
      syncWorldStyleConnection(state, client);
      presentWorldStyleAuthority(
        optionsView, state.worldStyleConnection, state.worldStyleFailure, active,
      );
      optionsView.reportWorldLifecycle(active.recoveredFromStale ? 'stale' : 'ready');
      reportProposalOutcome(active, 'previewed', 'Waiting to be confirmed in Customize.');
    } catch (error) {
      const detail = describeWorldStyleFailure(error);
      optionsView.reportWorldLifecycle('failed', detail);
      // Reported from the proposal rather than from an active preview, because there is none:
      // the authority refused before one existed, and the Companion still has to be able to say
      // what became of what it proposed.
      worldStyleProposalOutcomes.report({
        originReference: proposal.originReference ?? '',
        kind: 'refused',
        detail,
      });
    }
  });
  const settingsView = buildControlsGuide({
    preferences: state.preferences,
    onChange: applyPreferences,
    onClose: deps.onCloseControls,
    onShowCustomize: deps.onShowCustomize,
  });

  let latestSettingsSave = 0;
  function applyPreferences(next: AtlasPreferences): void {
    const previous = state.preferences;
    state.preferences = next;
    if (state.settingsStylePreviewId !== null && state.atlas !== null) {
      state.atlas.binding.discardArtProfilePreview(state.settingsStylePreviewId);
      state.settingsStylePreviewId = null;
    }
    try {
      writePreferences(window.localStorage, state.preferences);
    } catch {
      // Private browsing may refuse storage. The live setting still applies for this session.
    }
    const theme = applyDocumentAppearance(state.preferences, env.systemAppearance.matches);
    const profile = env.previewArtProfile ?? worldArtProfile(
      state.preferences.worldArtProfile,
      state.preferences.worldArtProfileVersion,
      state.preferences.worldStyleParameters,
    );
    applyDocumentWorldStyle(profile);
    optionsView.setPreferences(state.preferences);
    settingsView.setPreferences(state.preferences);
    deps.setCompanionAppearance();
    env.shell.setAttribute('data-vignette', state.preferences.vignette);
    state.atlas?.binding.setTheme(theme);
    // A new theme is a new palette, so a lit lens has to be re-resolved from it. Off stays off.
    deps.applyProofLens();
    state.atlas?.binding.setArtProfile(
      profile,
      'settings',
      state.preferences.worldStyleParameters,
    );
    state.atlas?.binding.setFieldOfView(state.preferences.fieldOfView);
    state.atlas?.binding.setSensitivityMultiplier(state.preferences.mouseSensitivity);
    if (state.interactionPolicies !== null) {
      latestSettingsSave += 1;
      const save = latestSettingsSave;
      optionsView.reportPersistence('saving');
      void state.interactionPolicies
        .syncSettings(previous, state.preferences, env.systemReducedMotion.matches)
        .then(() => {
          if (save === latestSettingsSave) optionsView.reportPersistence('saved');
        })
        .catch(() => {
          if (save === latestSettingsSave) optionsView.reportPersistence('failed');
        });
    }
  }

  return {
    options: optionsView,
    settings: settingsView,
    applyPreferences,
    /*
     * Deliberately not called on the empty-world path.
     *
     * The single-file version stops the inbox at the head of this surface's construction and
     * nowhere else, so a world that becomes empty mid-session keeps the previous mount's
     * subscription alive. That is preserved here rather than corrected: this change is a move,
     * and the next mount's `mountAppearance` is what stops it, exactly as before.
     */
    dispose: () => {
      if (serverPreviewTimer !== null) {
        window.clearTimeout(serverPreviewTimer);
        serverPreviewTimer = null;
      }
      state.stopWorldStyleProposalInbox?.();
      state.stopWorldStyleProposalInbox = null;
    },
  };
}

/**
 * Put a proposed design into the panel's own controls, as a person would have moved them.
 *
 * Returns false when it cannot, which is a refusal rather than a silent partial staging. The
 * panel builds its controls once, from the profile that was active when it was mounted, so a
 * proposal naming a different profile has no controls to move; today the reviewed registry
 * offers exactly one profile a new proposal may name, so that is a guard against a future
 * catalogue rather than a case anybody can reach.
 *
 * The event dispatched per control is the one the panel listens for, which differs by kind: a
 * range and a colour report on `input` and everything else on `change`. Sending the wrong one
 * moves the control on screen and tells the panel nothing, which is the failure mode this
 * function exists to not have.
 */
function stageWorldProposal(
  view: ReturnType<typeof buildOptions>,
  candidate: AtlasPreferences,
): boolean {
  const applied = view.preferences();
  if (
    candidate.worldArtProfile !== applied.worldArtProfile ||
    candidate.worldArtProfileVersion !== applied.worldArtProfileVersion
  ) return false;
  const definitions = worldStyleControls(
    candidate.worldArtProfile,
    candidate.worldArtProfileVersion,
  );
  const moves: { readonly node: HTMLInputElement | HTMLSelectElement; readonly event: string }[] =
    [];
  for (const definition of definitions) {
    const wanted = candidate.worldStyleParameters[definition.key];
    if (wanted === undefined || wanted === applied.worldStyleParameters[definition.key]) continue;
    const node = view.root.querySelector<HTMLInputElement | HTMLSelectElement>(
      `[aria-label="${CSS.escape(definition.label)}"]`,
    );
    if (node === null) return false;
    if (definition.kind === 'toggle') (node as HTMLInputElement).checked = wanted === true;
    else node.value = String(wanted);
    moves.push({
      node,
      event: definition.kind === 'range' || definition.kind === 'color' ? 'input' : 'change',
    });
  }
  if (moves.length === 0) return false;
  for (const move of moves) move.node.dispatchEvent(new Event(move.event, { bubbles: true }));
  return true;
}

export function preferencesForWorldVersion(
  local: AtlasPreferences,
  version: WorldStyleVersionRecord,
): AtlasPreferences {
  return preferencesForWorldReference(local, version.globalStyle);
}

function preferencesForWorldReference(
  local: AtlasPreferences,
  reference: WorldStyleVersionRecord['globalStyle'],
): AtlasPreferences {
  return Object.freeze({
    ...local,
    worldArtProfile: reference.profileId,
    worldArtProfileVersion: reference.profileVersion,
    worldStyleParameters: reference.parameters,
  });
}

function worldStylePreviewMatches(
  active: ActiveWorldStylePreview,
  candidate: AtlasPreferences,
): boolean {
  const profile = active.request.profile;
  if (
    active.request.scope.kind !== 'global' ||
    profile.profileId !== candidate.worldArtProfile ||
    profile.profileVersion !== candidate.worldArtProfileVersion
  ) return false;
  const keys = new Set([
    ...Object.keys(profile.parameters),
    ...Object.keys(candidate.worldStyleParameters),
  ]);
  return [...keys].every(
    (key) => profile.parameters[key] === candidate.worldStyleParameters[key],
  );
}

function syncWorldStyleConnection(state: SessionState, client: WorldStyleClient): void {
  const worldState = client.state();
  if (worldState === null) return;
  state.worldStyleConnection = Object.freeze({ state: worldState, versions: client.versions() });
}

function presentWorldStyleAuthority(
  view: ReturnType<typeof buildOptions>,
  connection: WorldStyleConnection | null,
  failure: string | null,
  active: ActiveWorldStylePreview | null,
): void {
  if (connection === null) {
    view.setWorldAuthority({
      state: failure === null ? 'unavailable' : 'failed',
      detail: failure ?? 'World style authority is unavailable. Local previews cannot be saved.',
    });
    return;
  }
  const current = connection.state.current;
  const provenance = current.provenance === null
    ? 'Authored initial version'
    : [
        `${current.provenance.origin} by ${current.provenance.actor}`,
        current.provenance.originReference,
        current.modelId,
        current.promptVersion,
        current.refinesProposalId === null ? null : `refines ${current.refinesProposalId}`,
      ].filter((item): item is string => item !== null).join(' · ');
  view.setWorldAuthority({
    state: 'ready',
    detail: 'Connected to immutable world style history.',
    currentVersionId: current.versionId,
    revision: current.revision,
    provenance,
    warnings: current.warnings,
    versions: connection.versions.map((version) => ({
      versionId: version.versionId,
      label: [
        `Revision ${version.revision}`,
        version.rollbackTargetVersionId === null ? null : 'rollback',
        version.provenance?.origin ?? 'authored',
        version.createdAt.slice(0, 10),
      ].filter((item): item is string => item !== null).join(' · '),
      current: version.versionId === current.versionId,
    })),
    ...(active === null
      ? {}
      : {
          proposal: {
            origin: active.request.origin,
            model: active.request.modelId,
            promptVersion: active.request.promptVersion,
            referenceCount: active.request.referenceIds.length,
            refinesProposalId: active.request.refinesProposalId,
          },
        }),
  });
}

export function describeWorldStyleFailure(error: unknown): string {
  if (error instanceof WorldStyleContractError) return error.message;
  if (error instanceof ApiError) {
    if (error.isUnauthenticated) return 'This session is no longer authorized to manage world design.';
    if (error.code === 'invalid_style_data') {
      return 'The proposal did not match the reviewed profile, capability, or parameter contract.';
    }
    if (error.code === 'protected_topology_conflict') {
      return 'The protected world layout changed. Reopen the design against the current Atlas.';
    }
    if (error.code === 'stale_style_version') {
      return 'The saved world changed elsewhere. Refresh and review a new preview.';
    }
    if (error.code === 'invalid_preview_state') {
      return 'That preview is already closed. Create and review a new preview.';
    }
    return `${error.code}: ${error.message.replace(`${error.code}: `, '')}`;
  }
  return error instanceof Error ? error.message : 'The world style request failed.';
}

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
import { buildOptions, sameWorldStyle } from '../ui/options.js';
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
import { RESTORE_BEFORE_CHANGING } from '../world-style-refusals.js';
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
  /** Advance the active saved entry only after the style authority accepted a version. */
  readonly onStyleSaved?: (version: WorldStyleVersionRecord) => Promise<void>;
}

export interface MountedAppearance {
  readonly options: ReturnType<typeof buildOptions>;
  readonly settings: ReturnType<typeof buildControlsGuide>;
  applyPreferences(next: AtlasPreferences): void;
  dispose(): void;
}

/**
 * What a refusal says: why, then what the person can do next. While this page can still change
 * the world the next step is `retry`. Once the live appearance moved from the one this page shows
 * (`WorldStyleClient.requiresReconciliation`), every change is held back until the saved version
 * is restored, and the next step is to restore it (`RESTORE_BEFORE_CHANGING`).
 */
interface Refusal {
  readonly why: string;
  readonly retry: string;
}

/** Why a proposal made for an earlier version of the world was refused, found open or made here. */
const REFUSED_FOR_AN_EARLIER_VERSION: Refusal = {
  why: 'This change was proposed for an earlier version of your world, so applying it would undo '
    + 'what changed since. It was not applied.',
  retry: 'Ask again for it.',
};

/** What the panel says about such a proposal before anybody presses Apply. */
const SHOWN_FOR_AN_EARLIER_VERSION =
  'This change was proposed for an earlier version of your world, so it cannot be applied. Ask '
  + 'again for it, or throw it away.';

/**
 * Why the authority refused a proposal that nobody decided within the lifetime it gives one.
 * No number: the lifetime is the server's (`OPEN_PREVIEW_LIFETIME`), and a copy here would drift.
 */
const REFUSED_AS_EXPIRED: Refusal = {
  why: 'This change waited too long to be confirmed and has expired, so it was not applied.',
  retry: 'Ask for it again, or make the change yourself.',
};

/** The same for the panel's own draft, which stays: Apply makes a fresh preview of it. */
const SETTINGS_EXPIRED: Refusal = {
  why: 'This preview waited too long to be confirmed and has expired, so nothing was saved.',
  retry: 'Apply again to save these settings.',
};

/** A refusal's words: why, then `behind` when the live appearance moved, else its retry. */
function refusalWords(refusal: Refusal, behind: string | null): string {
  return `${refusal.why} ${behind ?? refusal.retry}`;
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
  /*
   * The values the last staged proposal put into the panel, while nothing has decided it.
   *
   * A draft equal to these is a proposal's values, not the person's, and it is applied only
   * through that proposal's own preview: never as a Settings change, which would save a model's
   * design under the person's name.
   */
  let stagedCandidate: AtlasPreferences | null = null;
  /** Origin references of the proposals an earlier page made that this page found open. */
  const earlierReferences = new Set<string>();

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
    /*
     * A settings preview REPLACES whatever the client currently holds, so a person who moves a
     * slider while a Companion proposal is staged throws that proposal away. That is the right
     * behaviour and it was silent: the Companion had proposed something and would never learn
     * what became of it, so its memory kept the proposal and no outcome for ever.
     */
    // Said once the new preview exists: a refused one replaced nothing.
    const replaced = client.activePreview();
    optionsView.reportWorldLifecycle('checking');
    try {
      const active = await client.previewSettings({
        profileId: candidate.worldArtProfile,
        profileVersion: candidate.worldArtProfileVersion,
        parameters: candidate.worldStyleParameters,
      });
      reportReplaced(
        replaced, active, client, 'A change made on this panel replaced the proposed design.',
      );
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
   * what knows which proposal is current: another proposal replaces it, a refusal leaves the one
   * before it staged, and a local copy would name the wrong one. Settings changes report nothing,
   * which is not an omission: nobody is waiting to hear what happened to a slider they moved.
   */
  const reportProposalOutcome = (
    active: ActiveWorldStylePreview | null,
    kind: WorldStyleProposalOutcomeKind,
    detail: string,
  ): void => {
    if (active === null || active.request.origin === 'settings') return;
    const originReference = active.request.originReference ?? '';
    worldStyleProposalOutcomes.report({
      originReference,
      kind,
      detail,
      ...(earlierReferences.has(originReference) ? { earlier: true } : {}),
    });
  };

  /**
   * A preview from another origin whose base is not the version the world holds now, as far as
   * this page knows: one found open on opening, or one staged here that another writer overtook.
   */
  const madeForAnEarlierVersion = (
    active: ActiveWorldStylePreview,
    client: WorldStyleClient,
  ): boolean => {
    if (active.request.origin === 'settings') return false;
    const current = client.state();
    return current !== null && (
      active.baseStyleVersionId !== current.current.versionId
      || active.baseTopologyDigest !== current.currentTopologyDigest
    );
  };

  /** Throw away the local renderer preview, leaving the world drawn as `restored`. */
  const dropLocalWorldPreview = (restored: AtlasPreferences): void => {
    if (state.settingsStylePreviewId !== null && state.atlas !== null) {
      state.atlas.binding.discardArtProfilePreview(state.settingsStylePreviewId);
      state.settingsStylePreviewId = null;
    }
    applyDocumentWorldStyle(env.previewArtProfile ?? worldArtProfile(
      restored.worldArtProfile,
      restored.worldArtProfileVersion,
      restored.worldStyleParameters,
    ));
  };

  /**
   * Take a proposal the client no longer holds off the panel: its values, its local renderer
   * preview and its review. Left on the controls, its values would be saved as the person's own
   * Settings change by the first slider they moved.
   */
  const clearProposal = (client: WorldStyleClient): void => {
    stagedCandidate = null;
    dropLocalWorldPreview(state.preferences);
    optionsView.discardWorldDraft();
    syncWorldStyleConnection(state, client);
    presentWorldStyleAuthority(
      optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
    );
  };

  /**
   * List the version another writer made beside the saved one after a refusal that found it, so the
   * person sees what restoring the saved version replaces. The client reads its history when it
   * connects and after its own writes only, so without this read the writer's version is missing
   * until a reload. One read of the world's history; a failed read leaves the list as it was, and
   * one that answers after the page opened another world presents nothing.
   */
  const showVersionsAfterRefusal = (client: WorldStyleClient): void => {
    void client.refreshVersions().then(() => {
      if (state.worldStyles !== client) return;
      syncWorldStyleConnection(state, client);
      presentWorldStyleAuthority(
        optionsView, state.worldStyleConnection, state.worldStyleFailure, client.activePreview(),
      );
    }).catch(() => undefined);
  };

  /**
   * Refuse a proposal from another origin in words, and take it off the panel.
   *
   * The panel then shows the version this page shows as saved, which is the one it applied last.
   * While that is the live version, moving one control proposes only that change on it. When the
   * live appearance moved from it, the panel stays on it, because the client holds every change
   * back until the saved version is restored, and `behind` says what to do next instead of retry.
   */
  const refuseProposal = (
    active: ActiveWorldStylePreview,
    client: WorldStyleClient,
    refusal: Refusal,
    behind: string | null,
  ): void => {
    clearProposal(client);
    if (behind !== null) showVersionsAfterRefusal(client);
    const detail = refusalWords(refusal, behind);
    optionsView.reportWorldLifecycle('failed', detail);
    reportProposalOutcome(active, 'refused', detail);
  };

  /** Say what became of a preview another one replaced: closed, or still open if it could not be. */
  const reportReplaced = (
    replaced: ActiveWorldStylePreview | null,
    active: ActiveWorldStylePreview,
    client: WorldStyleClient,
    detail = 'Another proposal replaced it.',
  ): void => {
    const leftOpen = client.takeLeftOpen();
    if (replaced === null || replaced.request.originReference === active.request.originReference) {
      return;
    }
    if (leftOpen !== null && leftOpen.preview.previewId === replaced.preview.previewId) {
      reportProposalOutcome(
        replaced,
        'still_open',
        'Another proposal took its place on this panel, and it could not be closed, so it is still open.',
      );
      return;
    }
    reportProposalOutcome(replaced, 'discarded', detail);
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
      // The person moved a world control away from what the proposal put there: from here the
      // draft is theirs, and Apply saves it as their change even if they move it back.
      if (!stagingProposal && stagedCandidate !== null && !sameWorldStyle(candidate, stagedCandidate)) {
        stagedCandidate = null;
      }
    },
    /*
     * A staged proposal is the authority's active preview, from another origin, while the draft
     * on the panel is exactly that preview. Read off the client, which knows which proposal is
     * current. Once the person moves a control the draft is theirs, and the settings preview it
     * queues replaces the proposal and says so.
     */
    worldDraftIsProposal: () => {
      const active = state.worldStyles?.activePreview() ?? null;
      return active !== null && active.request.origin !== 'settings' &&
        worldStylePreviewMatches(active, optionsView.preferences());
    },
    onWorldDiscard: (restored) => {
      stagedCandidate = null;
      if (serverPreviewTimer !== null) {
        window.clearTimeout(serverPreviewTimer);
        serverPreviewTimer = null;
      }
      previewSequence += 1;
      dropLocalWorldPreview(restored);
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
      const matches = existing !== null && worldStylePreviewMatches(existing, candidate);
      /*
       * **A proposal made for an earlier version of the world is not applied.** Its candidate is
       * the whole design as it was at its base, so applying it, or re-making it against the
       * current version, would silently undo every change made since (a rollback, another
       * device's change). One this page already knows is that old, found open when the page
       * opened or overtaken by a change this page has heard of, is refused here without a
       * request, and this page stops holding it; it stays open on the authority, as opening a
       * world leaves it, until its lifetime closes it. One this page does not know is that old is
       * refused by the authority on Apply, below, by the same words. While the live appearance is
       * still the one this page shows, asking again drafts one for the world as it is. Once it is
       * not, every change is held back until the saved version is restored from Version history
       * over the change made elsewhere. After a writer that left the saved world alone the restore
       * goes through, and so does the next change, with no reload. After another page that
       * advanced the saved world the restore is refused with "Reload before trying again", and
       * after the reload the saved world is live and the next change goes through. A restore that
       * another change overtook in between is refused as stale, and the page shows the latest
       * version and asks for the restore target again (`onWorldRollback`).
       */
      if (existing !== null && madeForAnEarlierVersion(existing, client)) {
        client.release();
        refuseProposal(
          existing,
          client,
          REFUSED_FOR_AN_EARLIER_VERSION,
          client.requiresReconciliation() ? RESTORE_BEFORE_CHANGING : null,
        );
        return false;
      }
      /*
       * **A proposal is never quietly re-previewed as a Settings change.**
       *
       * `previewOnServer` posts `origin: settings` with no model, no prompt version and no
       * reference ids. Reaching it with a companion preview staged would discard that preview
       * and write a version whose provenance says a person moved a slider, which is the one
       * sentence about this path that must not be able to become false. It can only happen when
       * the panel's draft and the reviewed candidate have drifted apart, and the honest answer
       * to that is to say so.
       */
      if (
        (existing === null || existing.request.origin === 'settings') &&
        stagedCandidate !== null && sameWorldStyle(candidate, stagedCandidate)
      ) {
        optionsView.reportWorldLifecycle(
          'failed',
          'The proposed design is no longer held for this world, so it was not applied. Ask '
          + 'again, or make the change yourself.',
        );
        return false;
      }
      if (existing !== null && existing.request.origin !== 'settings' && !matches) {
        const detail =
          'The proposed design no longer matches what is on this panel. Discard it and ask '
          + 'again, or make the change yourself.';
        optionsView.reportWorldLifecycle('failed', detail);
        reportProposalOutcome(existing, 'refused', detail);
        return false;
      }
      const active = matches ? existing : await previewOnServer(candidate);
      if (active === null) return false;
      optionsView.reportWorldLifecycle('checking', 'Applying the reviewed preview…');
      try {
        const result = await client.applyActive();
        syncWorldStyleConnection(state, client);
        if (result.kind === 'stale') {
          // Overtaken by another writer this page had not heard of. The client stopped holding it
          // and made nothing again (`WorldStyleClient.applyActive`).
          refuseProposal(
            active,
            client,
            REFUSED_FOR_AN_EARLIER_VERSION,
            result.reconciliationRequired ? RESTORE_BEFORE_CHANGING : null,
          );
          return false;
        }
        if (result.kind === 'expired') {
          if (active.request.origin !== 'settings') {
            refuseProposal(
              active,
              client,
              REFUSED_AS_EXPIRED,
              result.reconciliationRequired ? RESTORE_BEFORE_CHANGING : null,
            );
            return false;
          }
          // The person's own draft stays on the panel, and Apply makes a fresh preview of it,
          // unless the live appearance moved from the one this page shows.
          presentWorldStyleAuthority(
            optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
          );
          optionsView.reportWorldLifecycle(
            'failed',
            refusalWords(
              SETTINGS_EXPIRED, result.reconciliationRequired ? RESTORE_BEFORE_CHANGING : null,
            ),
          );
          if (result.reconciliationRequired) showVersionsAfterRefusal(client);
          return false;
        }
        if (result.kind === 'stale-recovered') {
          // The panel's own Settings draft, made again on the version another writer saved, for
          // the person to review before Apply. Nobody is waiting to hear about a slider.
          presentWorldStyleAuthority(
            optionsView, state.worldStyleConnection, state.worldStyleFailure, result.preview,
          );
          optionsView.reportWorldLifecycle('stale');
          return false;
        }
        presentWorldStyleAuthority(
          optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
        );
        stagedCandidate = null;
        await deps.onStyleSaved?.(result.version);
        optionsView.reportWorldLifecycle('saved');
        reportProposalOutcome(
          active, 'accepted', `Applied as revision ${result.version.revision}.`,
        );
        return true;
      } catch (error) {
        const detail = describeWorldStyleFailure(error);
        // A proposal the client let go of, refused and then not followed by a read of the world,
        // leaves the panel too; one it still holds stays staged for another try.
        if (active.request.origin !== 'settings' && client.activePreview() !== active) {
          clearProposal(client);
        }
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
        await deps.onStyleSaved?.(result.version);
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
  /**
   * Put a preview from another origin into the panel's own controls, as the person reviews it.
   *
   * One path for a proposal that has just arrived and for one the page found still open when it
   * connected (``WorldStyleClient.connect``), so a staged proposal looks and applies the same after
   * a reload as before it.
   */
  async function stageActive(
    client: WorldStyleClient,
    active: ActiveWorldStylePreview,
    announce = true,
  ): Promise<void> {
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
      staged = stageWorldProposal(optionsView, candidate, state.preferences);
    } finally {
      stagingProposal = false;
    }
    if (!staged && !announce) {
      /*
       * Found open when the page opened, and this page cannot show it. Opening a world closes
       * nothing, so it is left open for the tab or the person that can decide it; this page stops
       * holding it and says so, in words the Companion keeps.
       */
      const detail =
        'A change proposed earlier could not be shown on this panel, so it is left as it was.';
      client.release();
      syncWorldStyleConnection(state, client);
      presentWorldStyleAuthority(
        optionsView, state.worldStyleConnection, state.worldStyleFailure, null,
      );
      optionsView.reportWorldLifecycle('failed', detail);
      reportProposalOutcome(active, 'still_open', detail);
      return;
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
        originReference: active.request.originReference ?? '',
        kind: 'refused',
        detail,
      });
      return;
    }
    stagedCandidate = candidate;
    reflectLocalWorldPreview(
      candidate,
      active.request.origin === 'companion' ? 'companion' : 'settings',
    );
    syncWorldStyleConnection(state, client);
    presentWorldStyleAuthority(
      optionsView, state.worldStyleConnection, state.worldStyleFailure, active,
    );
    // One made for an earlier version than the world holds now is shown as stale, and never
    // applied (`refuseProposal`), so it does not promise the fresh preview a Settings draft gets.
    const earlier = madeForAnEarlierVersion(active, client);
    optionsView.reportWorldLifecycle(
      earlier ? 'stale' : 'ready',
      earlier ? SHOWN_FOR_AN_EARLIER_VERSION : undefined,
    );
    if (announce) reportProposalOutcome(active, 'previewed', 'Waiting to be confirmed in Customize.');
  }

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
      // Read before the new preview replaces it, so the Companion hears what became of it.
      const replaced = client.activePreview();
      const active = await client.previewUpstream(proposal);
      reportReplaced(replaced, active, client);
      await stageActive(client, active);
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
      // The refused preview's read found the world moved: list what the restore would replace.
      if (
        error instanceof WorldStyleContractError && error.code === 'stale_proposal'
        && client.requiresReconciliation()
      ) {
        showVersionsAfterRefusal(client);
      }
    }
  });
  /*
   * What the page found open when it connected: a proposal still waiting for the person is staged
   * again. Nothing is closed here; another tab may be looking at the same preview.
   */
  const connected = state.worldStyles;
  const adopted = connected?.activePreview() ?? null;
  if (connected !== null && adopted !== null && adopted.request.origin !== 'settings') {
    if (adopted.request.originReference) earlierReferences.add(adopted.request.originReference);
    void stageActive(connected, adopted, false);
  }
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
 * proposal naming a different profile has no controls to move; the reviewed registry
 * offers exactly one profile a proposal may name, so that is a guard against a
 * catalogue that names more than one rather than a case anybody can reach.
 *
 * The event dispatched per control is the one the panel listens for, which differs by kind: a
 * range and a colour report on `input` and everything else on `change`. Sending the wrong one
 * moves the control on screen and tells the panel nothing, which is the failure mode this
 * function exists to not have.
 */
function stageWorldProposal(
  view: ReturnType<typeof buildOptions>,
  candidate: AtlasPreferences,
  applied: AtlasPreferences,
): boolean {
  // `applied` is the session's applied preferences, passed in rather than read off the panel.
  // `view.preferences()` returns the panel's live DRAFT, so a control the person had already
  // previewed by hand to the proposed value was skipped as "unchanged" and never dispatched,
  // and a proposal every one of whose controls they had touched staged nothing at all.
  if (
    candidate.worldArtProfile !== applied.worldArtProfile ||
    candidate.worldArtProfileVersion !== applied.worldArtProfileVersion
  ) return false;
  const definitions = worldStyleControls(
    candidate.worldArtProfile,
    candidate.worldArtProfileVersion,
  );
  let moved = 0;
  const draft = view.preferences().worldStyleParameters;
  for (const definition of definitions) {
    const wanted = candidate.worldStyleParameters[definition.key] ??
      applied.worldStyleParameters[definition.key];
    // A control the proposal leaves at the applied value is still moved back when the draft
    // holds something else, such as an earlier proposal's value, so the draft is this proposal.
    if (
      wanted === undefined ||
      (wanted === applied.worldStyleParameters[definition.key] && wanted === draft[definition.key])
    ) continue;
    const node = view.root.querySelector<HTMLInputElement | HTMLSelectElement>(
      `[aria-label="${escapeAttribute(definition.label)}"]`,
    );
    if (node === null) return false;
    if (definition.kind === 'toggle') {
      (node as HTMLInputElement).checked = wanted === true;
    } else {
      node.value = String(wanted);
      /*
       * **Read back, because the DOM sanitises.** A range input snaps its value to the declared
       * step and a colour input rewrites the text it was given, so a value off the control's
       * grid becomes a DIFFERENT value silently, and the person would then apply something the
       * authority never validated. Measured: a drafted 0.51 on a control whose step is 0.05
       * becomes 0.50 here. The drafter's schema now carries the step so this should not fire;
       * it is a refusal rather than an assertion because "should not" is not "cannot".
       */
      if (node.value !== String(wanted)) return false;
    }
    /*
     * Dispatched immediately, one control at a time, and that ORDER is the whole fix. The panel
     * re-renders on every reported change and rewrites every style input from its own draft, so
     * writing all the values first and dispatching afterwards meant the second and later
     * controls were overwritten before their event was sent: a five-control proposal staged
     * exactly one of them, and the other four were silently dropped.
     */
    node.dispatchEvent(new Event(
      definition.kind === 'range' || definition.kind === 'color' ? 'input' : 'change',
      { bubbles: true },
    ));
    moved += 1;
  }
  return moved > 0;
}

/**
 * One attribute value, safe inside a `[aria-label="..."]` selector.
 *
 * `CSS.escape` is the obvious call and is not universally present: happy-dom, which is what the
 * tests run in, does not define `CSS` at all, and a missing global here throws inside an inbox
 * listener whose caller does not await it, so the proposal vanished with nothing on the screen.
 */
function escapeAttribute(value: string): string {
  return value.replace(/["\\]/g, (match) => `\\${match}`);
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
        current.provenance.origin === 'settings'
          ? 'Saved from Customize'
          : current.provenance.origin === 'companion'
            ? 'Saved from a Companion proposal'
            : 'Saved from a reviewed appearance choice',
        current.modelId,
        current.promptVersion,
        current.refinesProposalId === null ? null : 'Refines an earlier proposal',
      ].filter((item): item is string => item !== null).join(' · ');
  view.setWorldAuthority({
    state: 'ready',
    detail: 'Appearance is saved across this workspace, including alternate versions. History is immutable.',
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


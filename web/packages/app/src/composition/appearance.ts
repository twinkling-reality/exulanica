/**
 * How the world looks: the saved preferences applied to the page and the renderer, and a style
 * pack saved against the authority the world's appearance is kept by.
 *
 * The module writes `state.preferences` and `state.worldStyleConnection`. It reads `state.atlas`
 * and never stores it: the renderer is rebuilt on every mount and a held binding would be a
 * disposed one.
 */

import { problemSentence } from '../ui/words/problems.js';
import { ApiError } from '@exulanica/graph-client';
import { worldArtProfile } from '@exulanica/presentation';

import { writePreferences, type AtlasPreferences } from '../preferences.js';
import { applyDocumentAppearance, applyDocumentWorldStyle } from '../theme.js';
import {
  WorldStyleContractError,
  type WorldStyleClient,
  type WorldStylePackBinding,
  type WorldStyleVersionRecord,
} from '../world-style-api.js';
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
  /** Advance the active saved entry only after the style authority accepted a version. */
  readonly onStyleSaved?: (version: WorldStyleVersionRecord) => Promise<void>;
}

export interface MountedAppearance {
  applyPreferences(next: AtlasPreferences): void;
  /**
   * Draw this world in a style pack (null for the default look), saved as a new version of its
   * appearance through one preview and Apply. Resolves to whether it was saved, with what happened
   * in words.
   */
  useStylePack(pack: WorldStylePackBinding | null): Promise<{ readonly saved: boolean; readonly words: string }>;
}

export function mountAppearance(deps: AppearanceDependencies): MountedAppearance {
  const { env, state } = deps;

  function applyPreferences(next: AtlasPreferences): void {
    const previous = state.preferences;
    state.preferences = next;
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
      void state.interactionPolicies
        .syncSettings(previous, state.preferences, env.systemReducedMotion.matches)
        .catch(() => undefined);
    }
  }

  /**
   * A look chosen in the Look sheet. A change already waiting in Design is the person's to decide
   * there, so a look is not previewed over it; a design another writer changed meanwhile is never
   * saved over (the client would make the pack's preview again from the profile this page read,
   * which would undo that change), so the person is asked to choose again.
   */
  async function useStylePack(
    pack: WorldStylePackBinding | null,
  ): Promise<{ readonly saved: boolean; readonly words: string }> {
    const client = state.worldStyles;
    if (client === null) {
      return { saved: false, words: state.worldStyleFailure ?? 'This world\'s appearance cannot be changed here.' };
    }
    if (client.requiresReconciliation()) return { saved: false, words: `Nothing was changed. ${RESTORE_BEFORE_CHANGING}` };
    if (client.activePreview() !== null) {
      return { saved: false, words: 'A change to this world\'s design is waiting in Design. Apply it or undo it there, then choose the look.' };
    }
    try {
      await client.previewStylePack(pack);
      const result = await client.applyActive();
      if (result.kind === 'stale-recovered') await client.discardActive();
      syncWorldStyleConnection(state, client);
      if (result.kind === 'applied') {
        await deps.onStyleSaved?.(result.version);
        return { saved: true, words: `Saved as revision ${result.version.revision} of this world's appearance.` };
      }
      if (result.kind === 'expired') return { saved: false, words: 'The choice waited too long to be confirmed, so nothing was changed. Choose the look again.' };
      if (result.kind === 'stale' && result.reconciliationRequired) {
        return { saved: false, words: `This world's design changed elsewhere, so nothing was changed. ${RESTORE_BEFORE_CHANGING}` };
      }
      return { saved: false, words: 'This world\'s design changed elsewhere, so nothing was changed. Choose the look again.' };
    } catch (error) {
      if (client.activePreview() !== null) await client.discardActive().catch(() => undefined);
      syncWorldStyleConnection(state, client);
      return { saved: false, words: describeWorldStyleFailure(error) };
    }
  }

  return { useStylePack, applyPreferences };
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

function syncWorldStyleConnection(state: SessionState, client: WorldStyleClient): void {
  const worldState = client.state();
  if (worldState === null) return;
  state.worldStyleConnection = Object.freeze({
    state: worldState,
    versions: client.versions(),
    liveVersionId: worldState.current.versionId,
    savedVersionId: client.savedVersionId(),
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
      return 'The protected world layout changed. Reopen the design against the current world.';
    }
    if (error.code === 'stale_style_version') {
      return 'The saved world changed elsewhere. Refresh and review a new preview.';
    }
    if (error.code === 'invalid_preview_state') {
      return 'That preview is already closed. Create and review a new preview.';
    }
    if (error.code === 'busy') {
      // Another transaction held a lock the write needs: a change to the look, a saved world's
      // entry, or a question reading the world. Nothing was written, whichever it was.
      return 'Your world was busy with something else a moment ago, so nothing was saved. Try again.';
    }
    return problemSentence(error);
  }
  return error instanceof Error ? error.message : 'The world style request failed.';
}

/**
 * The world style authority, as the vocabulary every caller of it shares.
 *
 * A world style is one decision seen from several distances: the session's opening read of the
 * saved version, the local renderer preview, the reviewed server preview, Apply, and rollback.
 * The functions below are the half that every one of those distances needs: how to describe a
 * failure, how to fold a saved version back into local preferences, and how to present the
 * authority's own history. They live here rather than beside any one caller because a
 * second phrasing of "the saved world changed elsewhere" is a second contract.
 *
 * The panels that drive them arrive in this module with the rest of the appearance surface.
 */

import { ApiError } from '@exulanica/graph-client';

import type { AtlasPreferences } from '../preferences.js';
import type { buildOptions } from '../ui/options.js';
import {
  WorldStyleContractError,
  type ActiveWorldStylePreview,
  type WorldStyleClient,
  type WorldStyleConnection,
  type WorldStyleVersionRecord,
} from '../world-style-api.js';
import type { SessionState } from './session-state.js';

export function preferencesForWorldVersion(
  local: AtlasPreferences,
  version: WorldStyleVersionRecord,
): AtlasPreferences {
  return preferencesForWorldReference(local, version.globalStyle);
}

export function preferencesForWorldReference(
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

export function worldStylePreviewMatches(
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

export function syncWorldStyleConnection(state: SessionState, client: WorldStyleClient): void {
  const worldState = client.state();
  if (worldState === null) return;
  state.worldStyleConnection = Object.freeze({ state: worldState, versions: client.versions() });
}

export function presentWorldStyleAuthority(
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

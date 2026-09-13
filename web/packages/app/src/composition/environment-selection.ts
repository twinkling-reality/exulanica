import type { AtlasScene } from '@exulanica/atlas-core';
import {
  localizeNYCFeatures,
  NYCSemanticOverlay,
  NYC_REFERENCE_FRAME,
  type NYCLocalFeature,
} from '@exulanica/atlas-react/playcanvas';
import { nycOpenDataAdmissionId } from '../config.js';
import {
  EnvironmentSelectionClient,
  type EnvironmentCatalog,
  type EnvironmentPlacementRequest,
  type EnvironmentProposal,
} from '../environment-selection-api.js';
import { el } from '../ui/dom.js';
import {
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  objectWriteFailure,
  type AlternateVersion,
  type ObjectRole,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';

export interface EnvironmentSelectionDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly scene: AtlasScene;
  readonly credentials: { readonly baseUrl: string; readonly token: string };
  readonly showStatus: (message: string, kind?: 'progress' | 'failure') => void;
  readonly admissionId?: string | null;
  readonly environmentClient?: EnvironmentSelectionClient;
  readonly worldClient?: WorldObjectsClient;
  readonly createOverlay?: (
    features: readonly NYCLocalFeature[],
  ) => {
    pick(
      origin: readonly [number, number, number],
      direction: readonly [number, number, number],
    ): NYCLocalFeature | null;
    destroy(): void;
  };
}

export interface MountedEnvironmentSelection {
  readonly root: HTMLElement;
  begin(): Promise<void>;
  dispose(): void;
}

const instanceId = (feature: NYCLocalFeature): string =>
  `nyc-open-data:${feature.providerFeatureId.replace(':', '-')}`;

export function mountEnvironmentSelection(
  deps: EnvironmentSelectionDependencies,
): MountedEnvironmentSelection {
  const root = el('aside', {
    class: 'environment-selection',
    'aria-label': 'NYC Open Data semantic selection',
  });
  const title = el('h2', { text: 'NYC Open Data' });
  const source = el('p', {
    class: 'environment-selection-source',
    text: 'Official BUILDING footprints. Neutral semantic overlays are separate from Google imagery.',
  });
  const selected = el('p', { class: 'environment-selection-selected', text: 'Aim at a teal footprint and press E.' });
  const reason = el('p', { class: 'environment-selection-reason' });
  const role = el('select', { 'aria-label': 'Authored role' });
  for (const value of ['fictional', 'personal'] as const) {
    role.append(el('option', { value, text: OBJECT_ROLE_LABELS[value] }));
  }
  const request = el('input', {
    type: 'text',
    'aria-label': 'Environment edit request',
    placeholder: 'Try “place this building”',
  });
  const ask = el('button', { type: 'button', text: 'Preview request', disabled: true });
  const place = el('button', { type: 'button', text: 'Preview placement', disabled: true });
  const remove = el('button', { type: 'button', text: 'Preview removal', disabled: true });
  const undo = el('button', { type: 'button', text: 'Preview undo latest edit', disabled: true });
  const controls = el('div', { class: 'environment-selection-controls' }, [role, place, remove, undo]);
  const language = el('div', { class: 'environment-selection-language' }, [request, ask]);
  const previewText = el('p', {
    class: 'environment-selection-preview',
    'aria-live': 'polite',
    text: 'No edit is waiting for review.',
  });
  const apply = el('button', { type: 'button', text: 'Apply', disabled: true });
  const discard = el('button', { type: 'button', text: 'Discard', disabled: true });
  const previewControls = el('div', {
    class: 'environment-selection-preview-controls',
    hidden: true,
  }, [apply, discard]);
  root.append(title, source, selected, reason, language, controls, previewText, previewControls);

  const admissionId = deps.admissionId === undefined ? nycOpenDataAdmissionId() : deps.admissionId;
  const environmentClient = deps.environmentClient ?? new EnvironmentSelectionClient(deps.credentials);
  const worldClient = deps.worldClient ?? new WorldObjectsClient(deps.credentials);
  let catalog: EnvironmentCatalog | null = null;
  let current: AlternateVersion | null = null;
  let chosen: NYCLocalFeature | null = null;
  let proposal: EnvironmentProposal | null = null;
  let phase: 'idle' | 'attaching' | 'attached' | 'disposed' = 'idle';
  let beginPromise: Promise<void> | null = null;
  let overlay: {
    pick(
      origin: readonly [number, number, number],
      direction: readonly [number, number, number],
    ): NYCLocalFeature | null;
    destroy(): void;
  } | null = null;
  let installedInteract: (() => void) | null = null;
  let priorInteract: (() => void) | null = null;
  let attachedControls: { onInteract: (() => void) | null } | null = null;

  function reportSelection(feature: NYCLocalFeature): void {
    if (chosen?.id !== feature.id) clearProposal();
    chosen = feature;
    const doitt = feature.providerFeatureId.replace('doitt_id:', '');
    selected.textContent = `DOITT_ID ${doitt} · BIN ${feature.bin?.replace('bin:', '') ?? 'not supplied'}`
      + ` · ${feature.name ?? 'Unnamed building'}`;
    reason.textContent = 'Match: reticle intersects the independently sourced NYC footprint.';
    place.disabled = false;
    ask.disabled = request.value.trim().length === 0;
    remove.disabled = current?.environmentInstances?.some((held) =>
      held.instanceId === instanceId(feature) && !held.removed) !== true;
  }

  function reflectVersion(): void {
    const undone = new Set(current?.edits
      .map((edit) => edit.undoneEditId)
      .filter((id): id is string => id !== null) ?? []);
    undo.disabled = current === null || !current.edits.some((edit) =>
      edit.kind !== 'undo' && !undone.has(edit.editId));
    if (chosen !== null) reportSelection(chosen);
  }

  function clearProposal(message = 'No edit is waiting for review.'): void {
    proposal = null;
    previewText.textContent = message;
    previewControls.hidden = true;
    apply.disabled = true;
    discard.disabled = true;
  }

  function showProposal(value: EnvironmentProposal): void {
    proposal = value;
    previewControls.hidden = false;
    apply.disabled = false;
    discard.disabled = false;
    if (value.operation === 'place_selected_feature') {
      previewText.textContent = `Proposed operation: place_selected_feature · feature `
        + `${value.featureId} · publication ${value.publicationId} · `
        + `role ${OBJECT_ROLE_LABELS[value.originRole]}.`;
    } else if (value.operation === 'remove_selected_authored_instance') {
      previewText.textContent = 'Proposed operation: remove_selected_authored_instance · '
        + `instance ${value.instanceId}.`;
    } else {
      previewText.textContent = 'Proposed operation: undo_latest_version_edit · latest edit.';
    }
  }

  function placementRequest(): EnvironmentPlacementRequest | null {
    if (chosen === null) return null;
    const west = chosen.bbox[0], south = chosen.bbox[1];
    const east = chosen.bbox[2], north = chosen.bbox[3];
    const centre = chosen.localFootprint[0]?.[0]?.reduce(
      (sum, point) => [sum[0] + point[0], sum[1] + point[1]] as [number, number],
      [0, 0],
    );
    const count = chosen.localFootprint[0]?.[0]?.length ?? 1;
    return {
      instanceId: instanceId(chosen),
      feature: chosen,
      sourceAnchor: [Math.round((west + east) / 2), Math.round((south + north) / 2)],
      regionId: String(deps.scene.islands[0]!.islandId),
      transform: {
        xMm: Math.round((centre?.[0] ?? 0) * 1000 / count),
        yMm: 0,
        zMm: Math.round((centre?.[1] ?? 0) * 1000 / count),
        yawMicroradians: 0,
        scaleMilli: 1000,
      },
      originRole: role.value as ObjectRole,
    };
  }

  async function applyResult(result: Awaited<ReturnType<EnvironmentSelectionClient['add']>>):
    Promise<boolean> {
    current = result.kind === 'recorded' ? result.version : result.current;
    reflectVersion();
    if (result.kind === 'stale') {
      deps.showStatus('The world changed. Current state was reloaded; review and try again.', 'failure');
      clearProposal('The preview is stale. Request a fresh proposal.');
      return false;
    }
    return true;
  }

  request.addEventListener('input', () => {
    ask.disabled = chosen === null || request.value.trim().length === 0;
  });
  role.addEventListener('change', () => clearProposal(
    'The role changed. Request a fresh proposal.',
  ));

  place.addEventListener('click', () => {
    const placement = placementRequest();
    if (catalog === null || current === null || placement === null) {
      deps.showStatus('Open an authored version and select a feature before previewing.', 'failure');
      return;
    }
    showProposal(environmentClient.deterministicPlace(current, catalog, placement));
  });

  remove.addEventListener('click', () => {
    if (current === null || chosen === null) return;
    showProposal({
      operation: 'remove_selected_authored_instance',
      versionId: current.versionId,
      baseStateSha256: current.stateSha256,
      instanceId: instanceId(chosen),
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    });
  });

  undo.addEventListener('click', () => {
    if (current === null) return;
    showProposal({
      operation: 'undo_latest_version_edit',
      versionId: current.versionId,
      baseStateSha256: current.stateSha256,
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    });
  });

  ask.addEventListener('click', () => void (async () => {
    const placement = placementRequest();
    if (catalog === null || current === null || placement === null) return;
    try {
      const result = await environmentClient.propose(
        current, catalog, placement, request.value.trim(),
      );
      if (result.kind === 'refused') {
        clearProposal(`No proposal: ${result.detail}`);
        deps.showStatus(`No environment proposal: ${result.detail}`, 'failure');
      } else {
        showProposal(result.proposal);
      }
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
    }
  })());

  discard.addEventListener('click', () => clearProposal('Proposal discarded. Nothing changed.'));

  apply.addEventListener('click', () => void (async () => {
    if (proposal === null) return;
    apply.disabled = true;
    try {
      const operation = proposal.operation;
      const ok = await applyResult(await environmentClient.apply(proposal));
      if (ok) {
        clearProposal('Applied. No edit is waiting for review.');
        deps.showStatus(
          operation === 'undo_latest_version_edit'
            ? 'Latest edit undone.'
            : operation === 'remove_selected_authored_instance'
              ? 'Environment placement removed. Undo latest edit remains available.'
              : 'NYC Open Data feature placed in the authored version.',
        );
      }
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
      apply.disabled = false;
    } finally {
      reflectVersion();
    }
  })());

  async function attach(): Promise<void> {
    if (admissionId === null) {
      root.dataset['state'] = 'unavailable';
      reason.textContent = 'No admitted NYC Open Data catalog is configured.';
      return;
    }
    const atlas = deps.state.atlas?.binding;
    if (atlas === undefined || deps.scene.islands.length === 0) return;
    try {
      [catalog, current] = await Promise.all([
        environmentClient.catalog(admissionId),
        worldClient.connect().then((connected) => connected.version),
      ]);
      if (phase === 'disposed') return;
      const features = localizeNYCFeatures(
        catalog.features,
        catalog.coordinateScale,
        NYC_REFERENCE_FRAME,
      );
      overlay = deps.createOverlay?.(features)
        ?? new NYCSemanticOverlay(atlas.device, atlas.renderRoot, features);
      attachedControls = atlas.controls;
      priorInteract = atlas.controls.onInteract;
      installedInteract = () => {
        const position = atlas.controls.state;
        const forward = atlas.camera.forward;
        const hit = overlay!.pick(
          [position.x, position.y, position.z],
          [forward.x, forward.y, forward.z],
        );
        if (hit === null) priorInteract?.();
        else reportSelection(hit);
      };
      atlas.controls.onInteract = installedInteract;
      phase = 'attached';
      root.dataset['state'] = 'ready';
      reason.textContent = `${catalog.attribution}. ${features.length} authorized features loaded.`;
      reflectVersion();
      atlas.invalidate();
    } catch (error) {
      root.dataset['state'] = 'unavailable';
      reason.textContent = error instanceof Error ? error.message : String(error);
      if (phase !== 'disposed') phase = 'idle';
    }
  }

  return {
    root,
    begin: () => {
      if (phase === 'disposed') {
        return Promise.reject(new Error('NYC environment selection mount is disposed'));
      }
      if (beginPromise !== null) return beginPromise;
      phase = 'attaching';
      beginPromise = attach();
      return beginPromise;
    },
    dispose: () => {
      if (phase === 'disposed') return;
      phase = 'disposed';
      if (attachedControls !== null && attachedControls.onInteract === installedInteract) {
        attachedControls.onInteract = priorInteract;
      }
      installedInteract = null;
      priorInteract = null;
      attachedControls = null;
      overlay?.destroy();
      overlay = null;
      root.remove();
    },
  };
}

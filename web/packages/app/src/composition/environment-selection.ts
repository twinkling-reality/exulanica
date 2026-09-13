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
  const place = el('button', { type: 'button', text: 'Place selected', disabled: true });
  const remove = el('button', { type: 'button', text: 'Remove', disabled: true });
  const undo = el('button', { type: 'button', text: 'Undo', disabled: true });
  const controls = el('div', { class: 'environment-selection-controls' }, [role, place, remove, undo]);
  root.append(title, source, selected, reason, controls);

  const admissionId = deps.admissionId === undefined ? nycOpenDataAdmissionId() : deps.admissionId;
  const environmentClient = deps.environmentClient ?? new EnvironmentSelectionClient(deps.credentials);
  const worldClient = deps.worldClient ?? new WorldObjectsClient(deps.credentials);
  let catalog: EnvironmentCatalog | null = null;
  let current: AlternateVersion | null = null;
  let chosen: NYCLocalFeature | null = null;
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
    chosen = feature;
    const doitt = feature.providerFeatureId.replace('doitt_id:', '');
    selected.textContent = `DOITT_ID ${doitt} · BIN ${feature.bin?.replace('bin:', '') ?? 'not supplied'}`
      + ` · ${feature.name ?? 'Unnamed building'}`;
    reason.textContent = 'Match: reticle intersects the independently sourced NYC footprint.';
    place.disabled = false;
    remove.disabled = current?.environmentInstances?.some((held) =>
      held.instanceId === instanceId(feature) && !held.removed) !== true;
  }

  function reflectVersion(): void {
    undo.disabled = current === null || !current.edits.some((edit) =>
      edit.kind.startsWith('add_environment') ||
      edit.kind.startsWith('remove_environment') ||
      edit.kind.startsWith('move_environment'));
    if (chosen !== null) reportSelection(chosen);
  }

  async function ensureVersion(): Promise<AlternateVersion> {
    if (current !== null) return current;
    const base = await worldClient.bootstrapBase();
    const id = await worldClient.bootstrapVersion(base);
    current = await worldClient.readVersion(id);
    return current;
  }

  async function applyResult(result: Awaited<ReturnType<EnvironmentSelectionClient['add']>>):
    Promise<boolean> {
    current = result.kind === 'recorded' ? result.version : result.current;
    reflectVersion();
    if (result.kind === 'stale') {
      deps.showStatus('The world changed. Current state was reloaded; review and try again.', 'failure');
      return false;
    }
    return true;
  }

  place.addEventListener('click', () => void (async () => {
    if (catalog === null || chosen === null) return;
    place.disabled = true;
    try {
      const base = await ensureVersion();
      const west = chosen.bbox[0], south = chosen.bbox[1];
      const east = chosen.bbox[2], north = chosen.bbox[3];
      const centre = chosen.localFootprint[0]?.[0]?.reduce(
        (sum, point) => [sum[0] + point[0], sum[1] + point[1]] as [number, number],
        [0, 0],
      );
      const count = chosen.localFootprint[0]?.[0]?.length ?? 1;
      const ok = await applyResult(await environmentClient.add(base, catalog, {
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
      }));
      if (ok) deps.showStatus('NYC Open Data feature placed in the authored version.');
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
    } finally {
      reflectVersion();
    }
  })());

  remove.addEventListener('click', () => void (async () => {
    if (current === null || chosen === null) return;
    try {
      const ok = await applyResult(await environmentClient.remove(current, instanceId(chosen)));
      if (ok) deps.showStatus('Environment placement removed. Undo remains available.');
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
    }
  })());

  undo.addEventListener('click', () => void (async () => {
    if (current === null) return;
    try {
      const ok = await applyResult(await environmentClient.undo(current));
      if (ok) deps.showStatus('Latest environment edit undone.');
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
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
      if (attachedControls !== null) {
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

// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { EnvironmentCatalog } from '../src/environment-selection-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

const version = {
  schemaVersion: 2,
  versionId: 'version',
  worldId: 'atlas:default',
  sourceSnapshotId: 'snapshot',
  parentVersionId: null,
  title: 'NYC',
  origin: 'authored',
  styleVersionId: null,
  stateSha256: '1'.repeat(64),
  editSeq: 0,
  sourceInvalidated: false,
  createdBy: 'actor',
  createdAt: '2026-09-12T00:00:00Z',
  objects: [],
  elementOverrides: [],
  environmentInstances: [],
  edits: [],
} satisfies AlternateVersion;

const catalog = {
  admissionId: 'admission',
  publicationId: 'publication',
  placeId: 'place',
  renderAssetId: 'render',
  coordinateScale: 10_000_000,
  frameName: 'nyc-open-data-crs84',
  receiptSha256: '1'.repeat(64),
  sourceSha256: '2'.repeat(64),
  sourceReceiptSha256: '3'.repeat(64),
  renderSha256: '4'.repeat(64),
  renderReceiptSha256: '5'.repeat(64),
  indexSha256: '6'.repeat(64),
  indexReceiptSha256: '7'.repeat(64),
  attribution: 'NYC Open Data',
  features: [{
    id: '0123456789abcdef0123456789abcdef',
    providerFeatureId: 'doitt_id:2327',
    bbox: [-739_904_139, 407_238_475, -739_902_608, 407_239_894],
    footprint: [[[
      [-739_904_139, 407_238_475],
      [-739_902_608, 407_238_475],
      [-739_902_608, 407_239_894],
      [-739_904_139, 407_238_475],
    ]]],
    renderBatchId: 0,
    name: null,
    bin: 'bin:1006070',
  }],
} satisfies EnvironmentCatalog;

describe('mounted NYC semantic selection lifecycle', () => {
  it('uses canonical controls coordinates, attaches once, and restores the exact handler', async () => {
    const prior = vi.fn();
    const controls = {
      state: { x: 1_200, y: 1.68, z: -340 },
      onInteract: prior as (() => void) | null,
    };
    const enginePosition = vi.fn(() => ({ x: 200, y: 1.68, z: -40 }));
    const binding = {
      controls,
      camera: {
        getPosition: enginePosition,
        forward: { x: 0, y: -1, z: 0 },
      },
      device: {},
      renderRoot: {},
      invalidate: vi.fn(),
    };
    const state = { atlas: { binding } } as unknown as SessionState;
    const readCatalog = vi.fn(async () => catalog);
    const connect = vi.fn(async () => ({ assets: [], version }));
    const pick = vi.fn(() => null);
    const destroy = vi.fn();
    const createOverlay = vi.fn(() => ({ pick, destroy }));
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(),
      admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: { catalog: readCatalog } as never,
      worldClient: { connect } as never,
      createOverlay,
    });

    const first = mounted.begin();
    const second = mounted.begin();
    expect(second).toBe(first);
    await first;
    expect(readCatalog).toHaveBeenCalledTimes(1);
    expect(connect).toHaveBeenCalledTimes(1);
    expect(createOverlay).toHaveBeenCalledTimes(1);

    controls.onInteract?.();
    expect(pick).toHaveBeenCalledWith([1_200, 1.68, -340], [0, -1, 0]);
    expect(enginePosition).not.toHaveBeenCalled();
    expect(prior).toHaveBeenCalledTimes(1);

    mounted.dispose();
    mounted.dispose();
    expect(destroy).toHaveBeenCalledTimes(1);
    expect(controls.onInteract).toBe(prior);
    await expect(mounted.begin()).rejects.toThrow(/disposed/);
    expect(createOverlay).toHaveBeenCalledTimes(1);
  });

  it('does not clobber a newer interaction owner during teardown', async () => {
    const prior = vi.fn();
    const newer = vi.fn();
    const controls = {
      state: { x: 0, y: 1.68, z: 0 },
      onInteract: prior as (() => void) | null,
    };
    const binding = {
      controls,
      camera: { forward: { x: 0, y: -1, z: 0 } },
      device: {},
      renderRoot: {},
      invalidate: vi.fn(),
    };
    const destroy = vi.fn();
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(),
      admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: { catalog: vi.fn(async () => catalog) } as never,
      worldClient: { connect: vi.fn(async () => ({ assets: [], version })) } as never,
      createOverlay: () => ({ pick: () => null, destroy }),
    });

    await mounted.begin();
    expect(controls.onInteract).not.toBe(prior);
    controls.onInteract = newer;
    mounted.dispose();
    expect(controls.onInteract).toBe(newer);
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it('shows an exact typed preview, captures role, discards, and applies only after confirmation', async () => {
    const controls = {
      state: { x: 0, y: 1.68, z: 0 },
      onInteract: null as (() => void) | null,
    };
    const binding = {
      controls,
      camera: { forward: { x: 0, y: -1, z: 0 } },
      device: {},
      renderRoot: {},
      invalidate: vi.fn(),
    };
    const feature = {
      ...catalog.features[0]!,
      localFootprint: [[[[1, 2], [3, 2], [1, 2]]]],
    };
    const apply = vi.fn(async (proposal) => ({ kind: 'stale', current: {
      ...version, stateSha256: '2'.repeat(64), editSeq: 1,
    }, proposal }));
    const deterministicPlace = vi.fn((base, heldCatalog, request) => ({
      operation: 'place_selected_feature',
      versionId: base.versionId,
      baseStateSha256: base.stateSha256,
      instanceId: request.instanceId,
      admissionId: heldCatalog.admissionId,
      renderAssetId: heldCatalog.renderAssetId,
      publicationId: heldCatalog.publicationId,
      featureId: request.feature.id,
      renderBatchId: request.feature.renderBatchId,
      sourceAnchorFrameName: heldCatalog.frameName,
      sourceAnchorCoordinateScale: heldCatalog.coordinateScale,
      sourceAnchorCoordinates: request.sourceAnchor,
      regionId: request.regionId,
      transform: request.transform,
      originRole: request.originRole,
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    }));
    const propose = vi.fn(async (base, heldCatalog, placement) => ({
      kind: 'proposed',
      proposal: deterministicPlace(base, heldCatalog, placement),
    }));
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(),
      admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: {
        catalog: vi.fn(async () => catalog),
        deterministicPlace,
        propose,
        apply,
      } as never,
      worldClient: { connect: vi.fn(async () => ({ assets: [], version })) } as never,
      createOverlay: () => ({ pick: () => feature as never, destroy: vi.fn() }),
    });
    await mounted.begin();
    controls.onInteract?.();
    const buttons = [...mounted.root.querySelectorAll('button')];
    const button = (label: string) => buttons.find((held) => held.textContent === label)!;
    const role = mounted.root.querySelector('select')!;
    role.value = 'personal';
    role.dispatchEvent(new Event('change'));

    button('Preview placement').click();
    expect(apply).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('Proposed operation: place_selected_feature');
    expect(mounted.root.textContent).toContain(catalog.publicationId);
    expect(mounted.root.textContent).toContain('Connected to something I experienced');
    expect(button('Apply').disabled).toBe(false);

    button('Discard').click();
    expect(apply).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('Proposal discarded. Nothing changed.');

    const input = mounted.root.querySelector('input')!;
    input.value = 'place this building';
    input.dispatchEvent(new Event('input'));
    button('Preview request').click();
    await vi.waitFor(() => expect(propose).toHaveBeenCalledTimes(1));
    button('Apply').click();
    await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
    expect(apply.mock.calls[0]![0].originRole).toBe('personal');
    expect(button('Apply').disabled).toBe(true);
    expect(mounted.root.textContent).toContain('The preview is stale. Request a fresh proposal.');
  });

  it('invalidates a preview when role changes and enables honest global latest-edit undo', async () => {
    const controls = {
      state: { x: 0, y: 1.68, z: 0 },
      onInteract: null as (() => void) | null,
    };
    const binding = {
      controls,
      camera: { forward: { x: 0, y: -1, z: 0 } },
      device: {},
      renderRoot: {},
      invalidate: vi.fn(),
    };
    const versionWithObjectEdit = {
      ...version,
      editSeq: 1,
      edits: [{
        editId: 'edit-object',
        editSeq: 1,
        kind: 'add_object',
        objectId: 'marker',
        elementId: null,
        environmentInstanceId: null,
        undoneEditId: null,
        baseStateSha256: '0'.repeat(64),
        resultStateSha256: version.stateSha256,
        actor: 'actor',
        recordedAt: '2026-09-12T00:00:00Z',
      }],
    } satisfies AlternateVersion;
    const feature = {
      ...catalog.features[0]!,
      localFootprint: [[[[1, 2], [3, 2], [1, 2]]]],
    };
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(),
      admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: {
        catalog: vi.fn(async () => catalog),
        deterministicPlace: vi.fn((base, heldCatalog, request) => ({
          operation: 'place_selected_feature',
          versionId: base.versionId,
          baseStateSha256: base.stateSha256,
          instanceId: request.instanceId,
          admissionId: heldCatalog.admissionId,
          renderAssetId: heldCatalog.renderAssetId,
          publicationId: heldCatalog.publicationId,
          featureId: request.feature.id,
          renderBatchId: request.feature.renderBatchId,
          sourceAnchorFrameName: heldCatalog.frameName,
          sourceAnchorCoordinateScale: heldCatalog.coordinateScale,
          sourceAnchorCoordinates: request.sourceAnchor,
          regionId: request.regionId,
          transform: request.transform,
          originRole: request.originRole,
          modelId: null,
          promptVersion: 'deterministic-environment-preview-1',
        })),
      } as never,
      worldClient: {
        connect: vi.fn(async () => ({ assets: [], version: versionWithObjectEdit })),
      } as never,
      createOverlay: () => ({ pick: () => feature as never, destroy: vi.fn() }),
    });
    await mounted.begin();
    controls.onInteract?.();
    const buttons = [...mounted.root.querySelectorAll('button')];
    const button = (label: string) => buttons.find((held) => held.textContent === label)!;
    expect(button('Preview undo latest edit').disabled).toBe(false);
    button('Preview undo latest edit').click();
    expect(mounted.root.textContent).toContain('Proposed operation: undo_latest_version_edit');

    button('Preview placement').click();
    const role = mounted.root.querySelector('select')!;
    role.value = 'personal';
    role.dispatchEvent(new Event('change'));
    expect(button('Apply').disabled).toBe(true);
    expect(mounted.root.textContent).toContain('The role changed. Request a fresh proposal.');
  });
});

// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_REPRESENTATION_INTENT,
  resolveRepresentation,
  type AtlasScene,
  type RepresentationIntent,
  type RepresentationSubject,
} from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { EnvironmentCatalog } from '../src/environment-selection-api.js';
import {
  WorldObjectsContractError,
  type AlternateVersion,
} from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import type { SocietyPlaybackControl } from '../src/society-control-api.js';

// Only the NYC footprint renderer is replaced, so a test can see whether one was built.
const nycOverlay = vi.hoisted(() => vi.fn());
vi.mock('@exulanica/atlas-react/playcanvas', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-react/playcanvas')>()),
  NYCSemanticOverlay: nycOverlay,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

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
  it('keeps scene and explicit data-view building selection on the same admitted feature', async () => {
    const controls = {
      state: { x: 12, y: 1.68, z: -4 },
      onInteract: null as (() => void) | null,
    };
    const metadata: RepresentationSubject = {
      subjectId: 'doitt_id:2327', subjectKind: 'object', sceneId: null,
      frameId: 'flatiron:render-metres', origin: 'external', sourceRefs: ['2'.repeat(64)],
      availability: 'available', rendered: true, points: null, compatibleBlend: false,
      bounds: { frameId: 'flatiron:render-metres', units: 'metres', origin: 'external',
        basis: 'source-bounds', min: [0, 0, 0], max: [10, 20, 10] },
      label: 'Source building', dataAvailable: true,
      unavailableReason: 'Building geometry shares an aggregate district draw; no per-feature point buffer.',
    };
    const group: RepresentationSubject = {
      ...metadata, subjectId: 'flatiron:render-group:buildings:0', subjectKind: 'geometry-group',
      origin: 'generated', points: 'mesh-surface-samples', compatibleBlend: true,
      bounds: { ...metadata.bounds!, origin: 'generated', basis: 'generated-extent' },
      label: 'buildings', unavailableReason: 'Aggregate generated surface samples.',
    };
    const unavailableMetadata: RepresentationSubject = {
      ...metadata,
      subjectId: 'doitt_id:9999',
      availability: 'withdrawn',
      label: 'Unavailable source building',
    };
    const secondFeature = {
      ...catalog.features[0]!,
      id: 'fedcba9876543210fedcba9876543210',
      providerFeatureId: unavailableMetadata.subjectId,
      name: 'Unavailable source building',
    };
    const heldCatalog = { ...catalog, features: [...catalog.features, secondFeature] };
    const observers = new Set<(
      subjectId: string | null,
      reason: 'explicit' | 'unavailable' | 'unregistered',
    ) => void>();
    const report = (
      intent: RepresentationIntent,
      selection: string | null,
      heldSubjects: readonly RepresentationSubject[] = [metadata, unavailableMetadata, group],
    ) => ({
      intent,
      subjects: heldSubjects.map(subject => ({
        subject, resolved: resolveRepresentation(intent, subject), allocatedPoints: 0, plannedPoints: 0,
      })),
      allocatedPoints: 0, pointBudget: 1_048_576, pendingSubjects: 0, selection,
    });
    const binding = {
      controls,
      camera: { forward: { x: 0, y: 0, z: -1 } },
      device: {}, environmentRoot: {}, renderRoot: {}, invalidate: vi.fn(),
      ownedDistrict: null, generatedTile: null,
      representationReport: report(DEFAULT_REPRESENTATION_INTENT, null),
      representationOverlayPlan: { refusals: [] },
      setRepresentationIntent: vi.fn((intent: RepresentationIntent) => {
        binding.representationReport = report(intent, binding.representationReport.selection);
        return binding.representationReport;
      }),
      setRepresentationSelection: vi.fn((subjectId: string | null) => {
        binding.representationReport = report(binding.representationReport.intent, subjectId);
        for (const observer of observers) observer(subjectId, 'explicit');
        return binding.representationReport;
      }),
      observeRepresentationSelection: vi.fn((observer: (
        subjectId: string | null,
        reason: 'explicit' | 'unavailable' | 'unregistered',
      ) => void) => {
        observers.add(observer);
        return () => { observers.delete(observer); };
      }),
      memoryLayerVisible: false,
      onMemoryLayerChange: null,
    };
    const selectedContexts: unknown[] = [];
    let localized: readonly { readonly providerFeatureId: string }[] = [];
    let picked = 0;
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(), admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: { catalog: vi.fn(async () => heldCatalog) } as never,
      worldClient: { connect: vi.fn(async () => ({ assets: [], version })) } as never,
      onSelect: context => { selectedContexts.push(context); },
      createOverlay: features => {
        localized = features;
        return { pick: () => features[picked]!, destroy: vi.fn() };
      },
    });
    await mounted.begin();

    const cameraBefore = { ...controls.state };
    controls.onInteract?.();
    expect(localized[0]!.providerFeatureId).toBe(metadata.subjectId);
    expect(binding.setRepresentationSelection).toHaveBeenLastCalledWith(metadata.subjectId);
    expect(binding.representationReport.selection).toBe(metadata.subjectId);
    expect(selectedContexts.at(-1)).toEqual({ admissionId: 'admission', featureId: catalog.features[0]!.id });

    picked = 1;
    controls.onInteract?.();
    expect(binding.representationReport.selection).toBe(metadata.subjectId);
    expect(selectedContexts.at(-1)).toEqual({ admissionId: 'admission', featureId: catalog.features[0]!.id });
    picked = 0;

    const list = mounted.root.querySelector<HTMLSelectElement>(
      'select[aria-label="Inspect a displayed geometry group"]',
    )!;
    const panel = list.closest('details')!;
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));
    expect(list.value).toBe(metadata.subjectId);
    expect(mounted.root.textContent).toContain('no per-feature point buffer');

    const slider = panel.querySelector<HTMLInputElement>('input[type=range]')!;
    slider.value = '75';
    slider.dispatchEvent(new Event('input'));
    expect(binding.representationReport.selection).toBe(metadata.subjectId);
    expect(controls.state).toEqual(cameraBefore);

    list.value = group.subjectId;
    list.dispatchEvent(new Event('change'));
    expect(binding.representationReport.selection).toBe(group.subjectId);
    expect(selectedContexts.at(-1)).toBeNull();
    expect(mounted.root.textContent).toContain('does not become city context');

    binding.setRepresentationSelection(metadata.subjectId);
    expect(selectedContexts.at(-1)).toEqual({ admissionId: 'admission', featureId: catalog.features[0]!.id });
    for (const observer of observers) observer('unknown:subject', 'explicit');
    expect(selectedContexts.at(-1)).toBeNull();
    expect(mounted.root.textContent).toContain('does not become city context');

    binding.setRepresentationSelection(metadata.subjectId);
    const withdrawn = { ...metadata, availability: 'withdrawn' as const };
    binding.representationReport = report(binding.representationReport.intent, null, [withdrawn, group]);
    for (const observer of observers) observer(null, 'unavailable');
    expect(selectedContexts.at(-1)).toBeNull();
    expect(mounted.root.textContent).toContain('authority changed');

    controls.onInteract?.();
    expect(selectedContexts.at(-1)).toBeNull();
    expect(mounted.root.textContent).toContain('authority changed');
    for (const observer of observers) observer(metadata.subjectId, 'explicit');
    expect(selectedContexts.at(-1)).toBeNull();
    expect(mounted.root.textContent).toContain('authority changed');
    mounted.dispose();
    expect(observers.size).toBe(0);
  });

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

  it('keeps source inspection read-only when the saved authored cursor needs reconciliation', async () => {
    const binding = {
      controls: { state: { x: 0, y: 1.62, z: 0 }, onInteract: null },
      camera: { forward: { x: 0, y: 0, z: -1 } },
      device: {}, environmentRoot: {}, renderRoot: {}, invalidate: vi.fn(),
    };
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(), admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: { catalog: vi.fn(async () => catalog) } as never,
      worldClient: { connect: vi.fn(async () => { throw new Error(
        'This saved world changed elsewhere. Reload to compare the latest changes before opening it.',
      ); }) } as never,
      createOverlay: () => ({ pick: () => null, destroy: vi.fn() }),
    });

    await mounted.begin();

    expect(mounted.root.dataset['state']).toBe('ready');
    expect(mounted.root.textContent).toContain('Editing this saved world is unavailable');
    expect(mounted.root.textContent).toContain('Reload to compare the latest changes');
    mounted.dispose();
  });

  it('draws NYC footprint lines only when neither an owned district nor a generated tile is in the world', async () => {
    nycOverlay.mockImplementation(function overlay() { return { pick: () => null, destroy: () => undefined }; });
    const built = async (world: { readonly ownedDistrict: unknown; readonly generatedTile: unknown }): Promise<number> => {
      nycOverlay.mockClear();
      const binding = {
        controls: { state: { x: 0, y: 1.62, z: 0 }, onInteract: null },
        camera: { getPosition: () => ({ x: 0, y: 1.62, z: 0 }), forward: { x: 0, y: 0, z: -1 } },
        device: {},
        environmentRoot: {},
        renderRoot: {},
        invalidate: vi.fn(),
        ...world,
      };
      const mounted = mountEnvironmentSelection({
        env: {} as AppEnvironment,
        state: { atlas: { binding } } as unknown as SessionState,
        scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
        credentials: { baseUrl: 'https://example.test', token: 'token' },
        showStatus: vi.fn(),
        admissionId: '12345678-1234-4123-8123-123456789abc',
        environmentClient: { catalog: async () => catalog } as never,
        worldClient: { connect: async () => ({ assets: [], version }) } as never,
      });
      await mounted.begin();
      const count = nycOverlay.mock.calls.length;
      mounted.dispose();
      return count;
    };
    // The Google reference view: no ground of its own, so the NYC footprints are drawn.
    expect(await built({ ownedDistrict: null, generatedTile: null })).toBe(1);
    // A generated city is not New York: no footprint line may draw over it.
    expect(await built({ ownedDistrict: null, generatedTile: { metrics: {}, dispose: () => undefined } })).toBe(0);
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
      proposal: {
        ...deterministicPlace(base, heldCatalog, placement),
        modelId: 'served/model',
        promptVersion: 'environment-proposal-1',
      },
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
    const role = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Authored role"]')!;
    role.value = 'personal';
    role.dispatchEvent(new Event('change'));

    button('Bring into my world').click();
    expect(apply).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('Proposed operation: place_selected_feature');
    expect(mounted.root.textContent).toContain(catalog.publicationId);
    expect(mounted.root.textContent).toContain('Connected to something I experienced');
    expect(mounted.root.textContent).toContain('Deterministic preview; no model ran.');
    expect(button('Apply').disabled).toBe(false);

    button('Discard').click();
    expect(apply).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('Proposal discarded. Nothing changed.');

    const input = mounted.root.querySelector<HTMLInputElement>('input[aria-label="Environment edit request"]')!;
    input.value = 'place this building';
    input.dispatchEvent(new Event('input'));
    button('Preview request').click();
    await vi.waitFor(() => expect(mounted.root.textContent).toContain('Model: served/model'));
    expect(mounted.root.textContent).toContain('prompt: environment-proposal-1');
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
    expect(mounted.root.textContent).toContain('This does not erase simulation history.');

    button('Bring into my world').click();
    const role = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Authored role"]')!;
    role.value = 'personal';
    role.dispatchEvent(new Event('change'));
    expect(button('Apply').disabled).toBe(true);
    expect(mounted.root.textContent).toContain('The role changed. Request a fresh proposal.');
  });

  it('never restores superseded model responses after role, feature, request, or disposal changes', async () => {
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
    const firstFeature = {
      ...catalog.features[0]!,
      localFootprint: [[[[1, 2], [3, 2], [1, 2]]]],
    };
    const secondFeature = {
      ...firstFeature,
      id: 'fedcba9876543210fedcba9876543210',
      providerFeatureId: 'doitt_id:9999',
    };
    let picked = firstFeature;
    const requests = [
      deferred<never>(), deferred<never>(), deferred<never>(), deferred<never>(), deferred<never>(),
      deferred<never>(),
    ];
    let proposalCall = 0;
    const propose = vi.fn(() => requests[proposalCall++]!.promise);
    const proposalFor = (
      featureId: string,
      role: 'fictional' | 'personal',
      model: string | null,
    ) => ({
      kind: 'proposed' as const,
      proposal: {
        operation: 'place_selected_feature' as const,
        versionId: version.versionId,
        baseStateSha256: version.stateSha256,
        instanceId: `nyc-open-data:${featureId}`,
        admissionId: catalog.admissionId,
        renderAssetId: catalog.renderAssetId,
        publicationId: catalog.publicationId,
        featureId,
        renderBatchId: 0,
        sourceAnchorFrameName: catalog.frameName,
        sourceAnchorCoordinateScale: catalog.coordinateScale,
        sourceAnchorCoordinates: [0, 0] as const,
        regionId: 'region-a',
        transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 },
        originRole: role,
        modelId: model,
        promptVersion: 'environment-proposal-1',
      },
    });
    const mounted = mountEnvironmentSelection({
      env: {} as AppEnvironment,
      state: { atlas: { binding } } as unknown as SessionState,
      scene: { islands: [{ islandId: 'region-a' }] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(),
      admissionId: '12345678-1234-4123-8123-123456789abc',
      environmentClient: { catalog: vi.fn(async () => catalog), propose } as never,
      worldClient: { connect: vi.fn(async () => ({ assets: [], version })) } as never,
      createOverlay: () => ({ pick: () => picked as never, destroy: vi.fn() }),
    });
    await mounted.begin();
    const buttons = [...mounted.root.querySelectorAll('button')];
    const button = (label: string) => buttons.find((held) => held.textContent === label)!;
    const input = mounted.root.querySelector<HTMLInputElement>('input[aria-label="Environment edit request"]')!;
    const role = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Authored role"]')!;
    const submit = (text: string) => {
      input.value = text;
      input.dispatchEvent(new Event('input'));
      button('Preview request').click();
    };

    controls.onInteract?.();
    submit('place this building');
    expect(button('Preview request').disabled).toBe(true);
    button('Preview request').click();
    expect(propose).toHaveBeenCalledTimes(1);
    role.value = 'personal';
    role.dispatchEvent(new Event('change'));
    requests[0]!.resolve(proposalFor(firstFeature.id, 'fictional', 'old-role-model') as never);
    await Promise.resolve();
    expect(mounted.root.textContent).not.toContain('old-role-model');
    expect(button('Apply').disabled).toBe(true);

    submit('place this building');
    picked = secondFeature;
    controls.onInteract?.();
    requests[1]!.resolve(proposalFor(firstFeature.id, 'personal', 'old-feature-model') as never);
    await Promise.resolve();
    expect(mounted.root.textContent).not.toContain('old-feature-model');
    expect(button('Apply').disabled).toBe(true);

    submit('place the second building');
    submit('place this selected building');
    expect(propose).toHaveBeenCalledTimes(4);
    requests[3]!.resolve(proposalFor(secondFeature.id, 'personal', 'newer-model') as never);
    await vi.waitFor(() => expect(mounted.root.textContent).toContain('newer-model'));
    requests[2]!.resolve(proposalFor(secondFeature.id, 'personal', 'older-model') as never);
    await Promise.resolve();
    expect(mounted.root.textContent).toContain('newer-model');
    expect(mounted.root.textContent).not.toContain('older-model');

    submit('place with unreported model');
    requests[4]!.resolve(proposalFor(secondFeature.id, 'personal', null) as never);
    await vi.waitFor(() => expect(mounted.root.textContent).toContain('Model: not reported'));
    expect(mounted.root.textContent).not.toContain('no model ran');

    submit('place after this');
    const previewText = mounted.root.querySelector('.environment-selection-preview')!;
    mounted.dispose();
    requests[5]!.resolve(proposalFor(secondFeature.id, 'personal', 'disposed-model') as never);
    await Promise.resolve();
    expect(previewText.textContent).not.toContain('disposed-model');
  });
});

import { ApiError } from '@exulanica/graph-client';
import { readFileSync } from 'node:fs';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
const producerLivingResponse = JSON.parse(readFileSync(
  `${process.cwd()}/packages/app/test/living-v4-grid-response.json`, 'utf8',
)) as { readonly fixture_provenance: { readonly canonical_state_sha256: string } };
function liveSnapshot(tick = 0): SocietySnapshot {
  return parseSociety({ society_id:'society', version_id:'version',branch_id:'version',place_id:'place',population_size:100,current_tick:tick,
    state_sha256:String(tick + 1).repeat(64),input_seq:1,input_sha256:'b'.repeat(64),
    state:{profile:'exulanica-society/v2',society_id:'society',branch_id:'version',tick,input_seq:1,input_sha256:'b'.repeat(64),
      inhabitants:Array.from({length:100},(_,i)=>({id:`person-${i}`,synthetic:true,display_name:`Person ${i}`,role:'steward',position_mm:[i,0],motion_path_mm:[[i,0]],goal:null,route:null,
        action:{kind:'idle',status:'active',target_id:null,remaining_ticks:0,reason:'awaiting_goal'},
        explanation:{summary:tick?'The target was removed.':'Awaiting a goal.',event_ids:tick?['event','outside-window']:[]}}))}});
}
function livingSnapshot(): SocietySnapshot { return parseSociety(producerLivingResponse); }
function liveMount(preview = false, living = false) {
  const canvas = document.createElement('canvas');
  const controls = {state:{x:0,y:1.68,z:0},onInteract:null as (()=>void)|null};
  const snapshot = living ? livingSnapshot : liveSnapshot;
  const initialSnapshot = snapshot();
  const inhabitantId = initialSnapshot.state.inhabitants[0]!.id;
  const connectedCatalog = living ? { ...catalog, placeId: initialSnapshot.placeId } : catalog;
  const connectedVersion = living ? { ...version, versionId: initialSnapshot.versionId } : version;
  const district = {district:{name:'Test district',sidewalks:[]},setAuthoredInstances:vi.fn(),setSociety:vi.fn(()=>24),clearSociety:vi.fn(),
    visibleInhabitantIds:[inhabitantId],drawnInhabitantCount:1,pickInhabitant:()=> inhabitantId,revealInhabitant:vi.fn(),inhabitantRepresentation:()=>undefined,coincidentInhabitants:()=>[inhabitantId],
    inhabitantDetail:()=>'near',societyCounts:{population:128,outdoors:128,indoors:0,near:1,far:0,drawn:1}};
  const binding = {controls,ownedDistrict:district,camera:{forward:{x:0,y:0,z:1}},invalidate:vi.fn(),setDistrictObjectFrame:vi.fn()};
  const client = {connect:vi.fn(async()=>snapshot()),read:vi.fn(async()=>snapshot(1)),advance:vi.fn(async(_snapshot:SocietySnapshot)=>snapshot(1)),events:vi.fn(async()=>[
    {event_id:'event',subject_id:inhabitantId,tick:1,event_kind:'replanned',document_sha256:'c'.repeat(64),document:{synthetic:true,summary:'Recorded target removal.',reason:'target_disabled_or_removed'}}])};
  let playback: SocietyPlaybackControl = {
    societyId:'society',versionId:'version',persisted:true,revision:0,mode:'paused',speed:1,
    tickIntervalMs:1000,currentTick:0,stateSha256:'1'.repeat(64),nextDueAt:null,reason:null,
    playEligible:true,playIneligibleReason:null,
  };
  const societyControlClient = {
    read:vi.fn(async()=>playback),
    configure:vi.fn(async(_control:SocietyPlaybackControl,mode:'paused'|'playing',speed:1|2|4)=>{
      playback={...playback,revision:playback.revision+1,mode,speed,tickIntervalMs:1000/speed};return playback;
    }),
    step:vi.fn(async(_control:SocietyPlaybackControl,snapshot:SocietySnapshot)=>{
      const society=await client.advance(snapshot);
      playback={...playback,revision:playback.revision+1,currentTick:society.currentTick,stateSha256:society.stateSha256};
      return {control:playback,society};
    }),
  };
  const districtResult = {placement:{versionId:connectedVersion.versionId,regionId:'registered-region',translationMm:[0,0,0],boundsMm:[0,0,100000,100000]},baseArtifactSha256:'b'.repeat(64),interpretationArtifactSha256:'c'.repeat(64)};
  const districtClient = {read:vi.fn(async()=>districtResult)};
  const onDistrictPlacementChange=vi.fn();
  const environment = {catalog:vi.fn(async()=>connectedCatalog),apply:vi.fn(async()=>({kind:'recorded',version:{...connectedVersion,editSeq:1}}))};
  const worldClient = {connect:vi.fn(async()=>({assets:[],version:{...connectedVersion,edits:[{kind:'add_object',editId:'prior',undoneEditId:null}]}}))};
  const mount = mountEnvironmentSelection({env:{canvas,preview} as AppEnvironment,state:{atlas:{binding}} as unknown as SessionState,
    scene:{islands:[{islandId:'region'}]} as unknown as AtlasScene,credentials:{baseUrl:'https://api.test',token:'test'},showStatus:vi.fn(),admissionId:'admission',
    environmentClient:environment as never,worldClient:worldClient as never,societyClient:client as never,societyControlClient:societyControlClient as never,societyDistrictClient:districtClient as never,onDistrictPlacementChange,
    createOverlay:()=>({pick:()=>null,destroy:vi.fn()})});
  const button = (label:string)=>[...mount.root.querySelectorAll('button')].find(b=>b.textContent===label)!;
  return {mount,client,societyControlClient,district,canvas,controls,button,environment,districtClient,districtResult,worldClient,binding,onDistrictPlacementChange};
}

describe('persisted living world controls',()=>{
  it('renders the canonical population and advances only on explicit user action',async()=>{
    const {mount,client,district,button,canvas}=liveMount();await mount.begin();
    expect(client.advance).not.toHaveBeenCalled();expect(district.setSociety).toHaveBeenCalledTimes(1);
    expect(district.setSociety).toHaveBeenCalledWith(liveSnapshot().state,[0,0]);
    expect(button('Advance one minute').disabled).toBe(false);button('Advance one minute').click();
    await vi.waitFor(()=>expect(canvas.dataset.societyTick).toBe('1'));
    expect(client.advance).toHaveBeenCalledTimes(1);expect(district.setSociety).toHaveBeenCalledTimes(2);
    mount.dispose();
  });
  it('inspects actual persisted event documents and discloses missing references',async()=>{
    const {mount,button,controls}=liveMount();await mount.begin();button('Advance one minute').click();
    await vi.waitFor(()=>expect(mount.root.textContent).toContain('Persisted tick 1'));
    controls.onInteract?.();
    expect(mount.root.textContent).toContain('Recorded target removal.');
    expect(mount.root.textContent).toContain('Referenced events unavailable in the latest event window: outside-window');
    expect(mount.root.textContent).toContain(`Sequence 1 · ${'b'.repeat(64)}`);
    expect(mount.root.textContent).toContain('Simulation clockUnavailable');
    expect(mount.root.textContent).toContain('Routine catalogsUnavailable');
    mount.dispose();
  });
  it('renders exact Python-produced v4 routine, input, tick, day and bounded event coverage',async()=>{
    expect(producerLivingResponse.fixture_provenance.canonical_state_sha256)
      .toBe('2305146307c266433a8c20912b85a040bcb1eaa5dc6a2bf6962211f1a531a52f');
    const {mount,controls}=liveMount(false,true);await mount.begin();controls.onInteract?.();
    expect(mount.root.textContent).toContain('society-activity v1, society-capacity v1, society-need v1, society-policy v1, society-use-class v1');
    expect(mount.root.textContent).toContain('5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931');
    expect(mount.root.textContent).toContain('Sequence 1 · f5396475c3196031391c8dd1cfb0772071c2710c490ed48202393896807b7aa6');
    expect(mount.root.textContent).toContain('Simulation tick1');
    expect(mount.root.textContent).toContain('Day 0 · 08:01');
    expect(mount.root.textContent).toContain('60 simulated seconds per tick');
    expect(mount.root.textContent).toContain('Latest bounded persisted event window');
    expect(mount.root.textContent).toContain('be802169-d4f0-5e83-a02d-a49d8138c14e');
    expect(mount.root.textContent).toContain('does not verify replay or send them to Companion');
    mount.dispose();
  });
  it('refreshes only the exact version after an authored object change, without advancing',async()=>{
    const {mount,client}=liveMount();await mount.begin();await mount.afterAuthoredEdit('other');expect(client.read).not.toHaveBeenCalled();
    await mount.afterAuthoredEdit('version');expect(client.read).toHaveBeenCalledTimes(1);expect(client.advance).not.toHaveBeenCalled();
    expect(mount.root.textContent).toContain('Restoring an object retains earlier simulation events');mount.dispose();
  });
  it('refreshes society after an internally confirmed authored restore',async()=>{
    const {mount,client,button,environment}=liveMount();await mount.begin();
    button('Preview undo latest edit').click();button('Apply').click();
    await vi.waitFor(()=>expect(client.read).toHaveBeenCalledTimes(1));
    expect(environment.apply).toHaveBeenCalledWith(expect.objectContaining({operation:'undo_latest_version_edit'}));
    expect(client.advance).not.toHaveBeenCalled();mount.dispose();
  });
  it('clears residents and selected details after permission loss without fabricating a tick',async()=>{
    const {mount,client,button,district,controls,canvas}=liveMount();await mount.begin();controls.onInteract?.();
    client.read.mockRejectedValueOnce(new ApiError(424,'unavailable_society_input','withdrawn'));
    button('Refresh persisted society').click();await vi.waitFor(()=>expect(canvas.dataset.societyTick).toBeUndefined());
    expect(district.clearSociety).toHaveBeenCalled();expect(button('Advance one minute').disabled).toBe(true);
    expect(mount.root.querySelector<HTMLElement>('.living-world-inspector')!.hidden).toBe(true);
    mount.dispose();
  });
  it('keeps preview isolated even if an authored version happens to be available',async()=>{
    const {mount,client,button}=liveMount(true);await mount.begin();
    expect(client.connect).not.toHaveBeenCalled();expect(button('Advance one minute').closest('details')?.hidden).toBe(true);
    await mount.afterAuthoredEdit('version');expect(client.read).not.toHaveBeenCalled();mount.dispose();
  });
  it('never installs residents from a response received after mount disposal',async()=>{
    const {mount,client,district}=liveMount();const held=deferred<SocietySnapshot>();client.connect.mockReturnValueOnce(held.promise);
    const beginning=mount.begin();await vi.waitFor(()=>expect(client.connect).toHaveBeenCalled());mount.dispose();held.resolve(liveSnapshot());await beginning;
    expect(district.setSociety).not.toHaveBeenCalled();expect(client.events).not.toHaveBeenCalled();
  });
});

describe('authorized district placement lifecycle',()=>{
  it('installs only the explicit registered frame and clears it on disposal',async()=>{
    const {mount,binding,onDistrictPlacementChange}=liveMount();await mount.begin();
    expect(mount.districtPlacement()?.regionId).toBe('registered-region');
    expect(binding.setDistrictObjectFrame).toHaveBeenCalledWith({regionId:'registered-region',translationMm:[0,0,0]});
    expect(onDistrictPlacementChange).toHaveBeenCalledTimes(1);
    mount.dispose();expect(mount.districtPlacement()).toBeNull();expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith(null);
  });
  it('revalidates before advancing and refuses edits/progression with unavailable frame dependencies',async()=>{
    const {mount,districtClient,binding,button,client,canvas}=liveMount();await mount.begin();
    districtClient.read.mockRejectedValueOnce(new ApiError(424,'unavailable_society_input','withdrawn'));
    button('Advance one minute').click();await vi.waitFor(()=>expect(mount.districtPlacement()).toBeNull());
    expect(client.advance).not.toHaveBeenCalled();expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith(null);
    expect(canvas.dataset.societyTick).toBeUndefined();expect(button('Advance one minute').disabled).toBe(true);
    mount.dispose();
  });
  it('clears the frame and authored controls when the branch already drifted',async()=>{
    const {mount,worldClient,binding,button,client,onDistrictPlacementChange}=liveMount();await mount.begin();
    worldClient.connect.mockRejectedValueOnce(new WorldObjectsContractError(
      'saved_entry_reconciliation_required',
      'This saved world changed elsewhere. Reload to compare the latest changes before opening it.',
    ));
    button('Advance one minute').click();
    await vi.waitFor(()=>expect(mount.districtPlacement()).toBeNull());
    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith(null);
    expect(onDistrictPlacementChange).toHaveBeenCalledTimes(2);
    expect(client.advance).not.toHaveBeenCalled();
    expect(mount.root.textContent).toContain('Editing this saved world is unavailable');
    expect(mount.root.textContent).toContain('Reload to compare the latest changes');
    mount.dispose();
  });
  it('does not apply a delayed district response after the saved branch advances',async()=>{
    const {mount,districtClient,districtResult,worldClient,binding,button,client}=liveMount();await mount.begin();
    const held=deferred<typeof districtResult>();
    districtClient.read.mockReturnValueOnce(held.promise);
    button('Advance one minute').click();
    await vi.waitFor(()=>expect(districtClient.read).toHaveBeenCalledTimes(2));
    worldClient.connect.mockRejectedValueOnce(new WorldObjectsContractError(
      'saved_entry_reconciliation_required',
      'This saved world changed elsewhere. Reload to compare the latest changes before opening it.',
    ));
    held.resolve(districtResult);
    await vi.waitFor(()=>expect(mount.districtPlacement()).toBeNull());
    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith(null);
    expect(client.advance).not.toHaveBeenCalled();
    mount.dispose();
  });
  it('accepts a district refresh after the saved cursor advances atomically',async()=>{
    const {mount,worldClient}=liveMount();await mount.begin();
    worldClient.connect.mockResolvedValue({
      assets:[],version:{...version,stateSha256:'d'.repeat(64),editSeq:1},
    });
    await mount.afterAuthoredEdit(version.versionId);
    expect(mount.districtPlacement()?.regionId).toBe('registered-region');
    expect(mount.root.textContent).not.toContain('Editing this saved world is unavailable');
    mount.dispose();
  });
  it('invalidates an old district result when a bound save advances mid-read',async()=>{
    const {mount,districtClient,districtResult,worldClient,binding}=liveMount();await mount.begin();
    const oldResult={...districtResult,placement:{...districtResult.placement,translationMm:[111,0,0]}};
    const newResult={...districtResult,placement:{...districtResult.placement,translationMm:[222,0,0]}};
    const held=deferred<typeof oldResult>();
    districtClient.read.mockReturnValueOnce(held.promise);

    const refreshing=mount.afterAuthoredEdit(version.versionId);
    await vi.waitFor(()=>expect(districtClient.read).toHaveBeenCalledTimes(2));
    worldClient.connect.mockResolvedValue({
      assets:[],version:{...version,stateSha256:'d'.repeat(64),editSeq:1},
    });
    held.resolve(oldResult);
    await refreshing;

    expect(binding.setDistrictObjectFrame).not.toHaveBeenCalledWith({
      regionId:'registered-region',translationMm:[111,0,0],
    });
    districtClient.read.mockResolvedValueOnce(newResult);
    await mount.afterAuthoredEdit(version.versionId);
    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith({
      regionId:'registered-region',translationMm:[222,0,0],
    });
    mount.dispose();
  });
  it('revokes authored controls when the district read exposes source invalidation',async()=>{
    const {mount,districtClient,worldClient,binding,button,client,onDistrictPlacementChange}=liveMount();await mount.begin();
    districtClient.read.mockRejectedValueOnce(new ApiError(
      424,'unavailable_society_input','the authored source is invalidated',
    ));
    worldClient.connect
      .mockResolvedValueOnce({assets:[],version})
      .mockRejectedValueOnce(new WorldObjectsContractError(
        'saved_entry_reconciliation_required',
        'This saved world changed elsewhere or its source became unavailable. Reload to compare the latest changes.',
      ));

    button('Advance one minute').click();
    await vi.waitFor(()=>expect(mount.districtPlacement()).toBeNull());

    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith(null);
    expect(onDistrictPlacementChange).toHaveBeenCalledTimes(2);
    expect(client.advance).not.toHaveBeenCalled();
    expect(mount.root.textContent).toContain('Editing this saved world is unavailable');
    expect(mount.root.textContent).toContain('source became unavailable');
    mount.dispose();
  });
  it('does not let a stale rejected revalidation clear a newer district refresh',async()=>{
    const {mount,districtClient,districtResult,worldClient,binding}=liveMount();await mount.begin();
    const held=deferred<Awaited<ReturnType<typeof worldClient.connect>>>();
    const validationStarted=deferred<void>();
    const newerResult={...districtResult,placement:{...districtResult.placement,translationMm:[333,0,0]}};
    districtClient.read.mockRejectedValueOnce(new ApiError(
      424,'unavailable_society_input','the authored source is invalidated',
    ));
    worldClient.connect
      .mockResolvedValueOnce({assets:[],version})
      .mockImplementationOnce(()=>{validationStarted.resolve();return held.promise;});

    const stale=mount.afterAuthoredEdit(version.versionId);
    await validationStarted.promise;
    districtClient.read.mockResolvedValueOnce(newerResult);
    await mount.afterAuthoredEdit(version.versionId);
    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith({
      regionId:'registered-region',translationMm:[333,0,0],
    });

    held.reject(new WorldObjectsContractError(
      'saved_entry_reconciliation_required',
      'This saved world changed elsewhere. Reload to compare the latest changes before opening it.',
    ));
    await stale;

    expect(binding.setDistrictObjectFrame).toHaveBeenLastCalledWith({
      regionId:'registered-region',translationMm:[333,0,0],
    });
    expect(mount.root.textContent).not.toContain('Editing this saved world is unavailable');
    mount.dispose();
  });
  it('can reauthorize frame and state after a prior society authorization failure',async()=>{
    const {mount,client,button}=liveMount();await mount.begin();client.read.mockRejectedValueOnce(new ApiError(424,'unavailable_society_input','withdrawn'));
    button('Refresh persisted society').click();await vi.waitFor(()=>expect(mount.districtPlacement()).toBeNull());
    button('Refresh persisted society').click();await vi.waitFor(()=>expect(button('Advance one minute').disabled).toBe(false));
    expect(mount.districtPlacement()?.regionId).toBe('registered-region');mount.dispose();
  });
  it('ignores a district binding response after disposal',async()=>{
    const {mount,districtClient,binding}=liveMount();const held=deferred<Awaited<ReturnType<typeof districtClient.read>>>();districtClient.read.mockReturnValueOnce(held.promise);
    const begin=mount.begin();await vi.waitFor(()=>expect(districtClient.read).toHaveBeenCalled());mount.dispose();
    held.resolve({placement:{versionId:'version',regionId:'other',translationMm:[0,0,0],boundsMm:[0,0,100,100]},baseArtifactSha256:'b'.repeat(64),interpretationArtifactSha256:'c'.repeat(64)});
    await begin;expect(mount.districtPlacement()).toBeNull();expect(binding.setDistrictObjectFrame).not.toHaveBeenCalled();
  });
});

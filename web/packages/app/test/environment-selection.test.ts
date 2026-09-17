// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { EnvironmentCatalog } from '../src/environment-selection-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
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
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
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
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
function liveSnapshot(tick = 0): SocietySnapshot {
  return parseSociety({ society_id:'society', version_id:'version',branch_id:'version',place_id:'place',population_size:100,current_tick:tick,
    state_sha256:String(tick + 1).repeat(64),input_seq:1,input_sha256:'b'.repeat(64),
    state:{profile:'exulanica-society/v2',society_id:'society',branch_id:'version',tick,input_seq:1,input_sha256:'b'.repeat(64),
      inhabitants:Array.from({length:100},(_,i)=>({id:`person-${i}`,synthetic:true,display_name:`Person ${i}`,role:'steward',position_mm:[i,0],motion_path_mm:[[i,0]],goal:null,route:null,
        action:{kind:'idle',status:'active',target_id:null,remaining_ticks:0,reason:'awaiting_goal'},
        explanation:{summary:tick?'The target was removed.':'Awaiting a goal.',event_ids:tick?['event','outside-window']:[]}}))}});
}
function liveMount(preview = false) {
  const canvas = document.createElement('canvas');
  const controls = {state:{x:0,y:1.68,z:0},onInteract:null as (()=>void)|null};
  const district = {district:{name:'Test district',sidewalks:[]},setAuthoredInstances:vi.fn(),setSociety:vi.fn(()=>24),clearSociety:vi.fn(),
    visibleInhabitantIds:['person-0'],drawnInhabitantCount:1,pickInhabitant:()=> 'person-0',revealInhabitant:vi.fn(),inhabitantRepresentation:()=>undefined,coincidentInhabitants:()=>['person-0'],
    inhabitantDetail:()=>'near',societyCounts:{population:128,outdoors:128,indoors:0,near:1,far:0,drawn:1}};
  const binding = {controls,ownedDistrict:district,camera:{forward:{x:0,y:0,z:1}},invalidate:vi.fn(),setDistrictObjectFrame:vi.fn()};
  const client = {connect:vi.fn(async()=>liveSnapshot()),read:vi.fn(async()=>liveSnapshot(1)),advance:vi.fn(async(_snapshot:SocietySnapshot)=>liveSnapshot(1)),events:vi.fn(async()=>[
    {event_id:'event',subject_id:'person-0',tick:1,event_kind:'replanned',document_sha256:'c'.repeat(64),document:{synthetic:true,summary:'Recorded target removal.',reason:'target_disabled_or_removed'}}])};
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
  const districtClient = {read:vi.fn(async()=>({placement:{versionId:'version',regionId:'registered-region',translationMm:[0,0,0],boundsMm:[0,0,100000,100000]},baseArtifactSha256:'b'.repeat(64),interpretationArtifactSha256:'c'.repeat(64)}))};
  const onDistrictPlacementChange=vi.fn();
  const environment = {catalog:vi.fn(async()=>catalog),apply:vi.fn(async()=>({kind:'recorded',version:{...version,editSeq:1}}))};
  const mount = mountEnvironmentSelection({env:{canvas,preview} as AppEnvironment,state:{atlas:{binding}} as unknown as SessionState,
    scene:{islands:[{islandId:'region'}]} as unknown as AtlasScene,credentials:{baseUrl:'https://api.test',token:'test'},showStatus:vi.fn(),admissionId:'admission',
    environmentClient:environment as never,worldClient:{connect:vi.fn(async()=>({assets:[],version:{...version,edits:[{kind:'add_object',editId:'prior',undoneEditId:null}]}}))} as never,societyClient:client as never,societyControlClient:societyControlClient as never,societyDistrictClient:districtClient as never,onDistrictPlacementChange,
    createOverlay:()=>({pick:()=>null,destroy:vi.fn()})});
  const button = (label:string)=>[...mount.root.querySelectorAll('button')].find(b=>b.textContent===label)!;
  return {mount,client,societyControlClient,district,canvas,controls,button,environment,districtClient,binding,onDistrictPlacementChange};
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

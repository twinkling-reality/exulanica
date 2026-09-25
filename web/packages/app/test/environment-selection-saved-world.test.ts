// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { SeatingLayout } from '@exulanica/atlas-react/playcanvas';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { parseSociety, parseSocietyActionRecord, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';

/*
 * A person's own saved world: inhabitants are drawn over its authored region, they exist only
 * after the person asks for them, and every request names the saved world. No district, no NYC
 * admission and no owned district take part.
 */

const WORLD = 'world:authored:saved';
const plate = (objectId: string, xMm: number, zMm: number, yawMicroradians = 0) => ({
  objectId,
  asset: { assetKey: 'cc0.marker-plate', title: 'Marker plate', summary: '', mediaType: 'model/gltf-binary',
    contentSha256: 'c'.repeat(64), byteSize: 1, licenceId: 'CC0-1.0', licenceSha256: 'd'.repeat(64), availability: 'available' },
  regionId: 'region:starter',
  transform: { coordinateSpace: 'region_local', coordinateUnit: 'millimetre', xMm, yMm: 0, zMm, yawMicroradians, scaleMilli: 1000 },
  origin: { kind: 'authored', role: 'fictional' },
  behaviour: null,
  removed: false,
});
const version = {
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 2,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-22T00:00:00Z',
  // Turned to face the person who placed it, as placing one in front of yourself does.
  objects: [plate('object-near', 3000, 5000, 3_141_593), plate('object-far', 0, 14000)],
  elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion;

const society = (tick: number, firstRests = false): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 100, current_tick: tick, state_sha256: String(tick).repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick, input_seq: 1,
    input_sha256: 'b'.repeat(64), inhabitants: Array.from({ length: 100 }, (_, i) => ({
      id: `person-${i}`, synthetic: true, position_mm: [2000, 4000], display_name: `Person ${i}`, role: 'steward',
      goal: firstRests && i === 0
        ? { kind: 'rest', target_id: 'authored:version:object-near:rest', reason: 'remembered_target_selected' }
        : null,
      route: null, motion_path_mm: [[2000, 4000]],
      action: firstRests && i === 0
        ? { kind: 'rest', status: 'active', target_id: 'authored:version:object-near:rest', remaining_ticks: 2, reason: 'arrived_at_access_node' }
        : { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
      explanation: { summary: firstRests && i === 0 ? 'Person 0 (simulated) rests at the plate.' : `Person ${i} (simulated) waits.`, event_ids: [] } })) },
  places: {
    input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450,
    targets: [{ target_id: 'authored:version:object-near:rest', subject_id: 'authored:version:object-near',
      node_id: 'ground:+00002000:+00004000', affordance: 'rest', duration_ticks: 3, origin: 'authored',
      object_id: 'object-near', version_id: 'version', enabled: true }],
    unavailable_affordances: [{ target_id: 'authored:version:object-far:rest', subject_id: 'authored:version:object-far',
      object_id: 'object-far', version_id: 'version', affordance: 'rest', reason: 'authored_affordance_unreachable' }],
  },
});
const control = (tick: number) => parseSocietyControl({
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
  revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 0, current_tick: tick, state_sha256: String(tick).repeat(64),
  play_ineligible_reason: null, play_eligible: true,
}, 'version');

function mount() {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  let held: SocietySnapshot | null = null;
  const crowd = {
    setSociety: vi.fn(() => 100), clearSociety: vi.fn(), revealInhabitant: vi.fn(),
    visibleInhabitantIds: ['person-0', 'person-1'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 100, outdoors: 100, indoors: 0, near: 2, far: 0, drawn: 2 },
    drawnInhabitantCount: 2, pickInhabitant: vi.fn(() => 'person-0'), inhabitantSeatAtPlace: vi.fn(() => false),
    setSeatingLayout: vi.fn(), seatingMisses: [{ inhabitantId: 'person-7', reason: 'target-unknown' }],
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    controls, camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
    ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => { if (held === null) throw missing(); return held; }),
    create: vi.fn(async () => { held = society(0); return held; }),
    connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []),
    requestAction: vi.fn(async (snapshot: SocietySnapshot, subjectId: string, intent: { targetId: string }) =>
      parseSocietyActionRecord({
        request: { profile: 'exulanica.society-action-request/v1', request_id: 'request', requested_by: 'actor',
          subject_id: subjectId, branch_id: 'version', base_tick: snapshot.currentTick, base_state_sha256: snapshot.stateSha256,
          input_seq: 1, input_sha256: 'b'.repeat(64), intent: { kind: 'perform', target_id: intent.targetId, affordance: 'rest' },
          target: { target_id: intent.targetId }, document_sha256: 'e'.repeat(64) },
        status: 'pending', consumption: null,
      }, 'version')),
  };
  const controlClient = {
    read: vi.fn(async () => { if (held === null) throw missing(); return control(held.currentTick); }),
    configure: vi.fn(),
    step: vi.fn(async () => { held = society(1, true); return { control: control(1), society: held }; }),
  };
  // The registry list the page reads, with what inhabitants do with the plate: rest, at places
  // the society derives for a marker.
  const assets = [{ ...plate('unused', 0, 0).asset, placeable: true, use: { affordance: 'rest', places: null } }];
  const worldClient = { connect: vi.fn(async () => ({ assets, version })), assets: vi.fn(() => assets) };
  const canvas = document.createElement('canvas');
  const mounted = mountEnvironmentSelection({
    env: { canvas, preview: false } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'My world',
        authoredScene: { region: { regionId: 'region:starter' } } },
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
  });
  document.body.append(mounted.root);
  const panel = () => mounted.root.querySelector<HTMLElement>('section.world-inhabitants')!;
  return { mounted, crowd, controls, societyClient, controlClient, worldClient, panel, canvas };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('a saved world holds inhabitants only when the person asks', () => {
  it('opening reads the saved world and creates nothing; the request brings them in and draws them', async () => {
    const { mounted, crowd, societyClient, panel, canvas, worldClient } = mount();
    await mounted.begin();
    expect(societyClient.read).toHaveBeenCalledWith('version', { places: true });
    expect(societyClient.create).not.toHaveBeenCalled();
    expect(panel().dataset['state']).toBe('absent');
    expect(panel().querySelector('.world-inhabitants-summary')?.textContent).toBe('Nobody lives here yet.');
    expect(crowd.setSociety).not.toHaveBeenCalled();
    // The workspace's own line would say nobody is near right under "Nobody lives here yet".
    const nearbyLine = mounted.root.querySelector<HTMLElement>('#world-panel-nearby p.world-help[role="status"]')!;
    expect(nearbyLine.hidden).toBe(true);

    [...panel().querySelectorAll('button')].find((b) => b.textContent === 'Bring in inhabitants')!.click();
    for (let i = 0; i < 6; i += 1) await settle();
    expect(societyClient.create).toHaveBeenCalledWith('version', null, 'region:starter', 'exulanica-society/v2');
    expect(crowd.setSociety).toHaveBeenCalledTimes(1);
    // The crowd is handed the seating the drawn objects give: each kind's use, the objects, and
    // which object each target belongs to.
    const layout = (crowd.setSociety.mock.calls[0] as unknown[])[3] as SeatingLayout;
    expect(layout.uses.get('cc0.marker-plate')).toEqual({ affordance: 'rest', places: null });
    expect(layout.objects.map((object) => [object.objectId, object.xMm, object.zMm, object.yawMicroradians]))
      .toEqual([['object-near', 3000, 5000, 3_141_593], ['object-far', 0, 14000, 0]]);
    expect(layout.targets.get('authored:version:object-near:rest')).toBe('object-near');
    // Whoever the crowd draws as everyone else, it says so by reason on the canvas.
    expect(canvas.dataset['societySeatingMisses']).toBe('target-unknown');
    expect(panel().dataset['state']).toBe('present');
    const rows = [...panel().querySelectorAll<HTMLElement>('.world-inhabitants-places li')];
    expect(rows.map((row) => [row.dataset['objectId'], row.dataset['status']])).toEqual([
      ['object-near', 'usable'], ['object-far', 'unreachable'],
    ]);
    expect(rows[1]!.textContent).toMatch(/outside the area they walk in/);
    // An object taken away is taken out of the seating at once, before any new minute is read.
    const without = { ...version, objects: version.objects.filter((object) => object.objectId !== 'object-near') };
    worldClient.connect.mockResolvedValueOnce({ assets: worldClient.assets(), version: without as AlternateVersion });
    await mounted.afterAuthoredEdit('version');
    const relaid = crowd.setSeatingLayout.mock.calls.at(-1)![0] as SeatingLayout;
    expect(relaid.objects.map((object) => object.objectId)).toEqual(['object-far']);
    expect(crowd.setSociety).toHaveBeenCalledTimes(1);
    expect(canvas.dataset['societySeatingLayout']).toBe('current');
    // A re-read that fails keeps the last seating it built, so nobody stands up for it, and says so.
    worldClient.connect.mockRejectedValueOnce(new ApiError(503, 'unavailable', 'the store is restarting'));
    await mounted.afterAuthoredEdit('version');
    expect(crowd.setSeatingLayout.mock.calls.at(-1)![0]).toBe(relaid);
    expect(canvas.dataset['societySeatingLayout']).toBe('kept-after-failed-read');
    mounted.dispose();
    expect(crowd.clearSociety).toHaveBeenCalled();
  });

  it('a chosen inhabitant can be asked to rest at a place, and a minute can be advanced', async () => {
    const { mounted, crowd, controls, societyClient, controlClient, panel } = mount();
    await mounted.begin();
    [...panel().querySelectorAll('button')].find((b) => b.textContent === 'Bring in inhabitants')!.click();
    for (let i = 0; i < 6; i += 1) await settle();

    // Aiming at a person and pressing E selects them over whatever the world would do.
    controls.onInteract?.();
    const rest = [...mounted.root.querySelectorAll('button')].find((b) => b.textContent === 'Rest at Marker plate 1')!;
    expect(rest).toBeDefined();
    expect(rest.disabled).toBe(false);
    rest.click();
    for (let i = 0; i < 4; i += 1) await settle();
    expect(societyClient.requestAction).toHaveBeenCalledWith(
      expect.objectContaining({ versionId: 'version' }), 'person-0',
      { kind: 'perform', targetId: 'authored:version:object-near:rest', affordance: 'rest' },
    );
    expect(rest.parentElement!.textContent).toMatch(/Asked to rest at Marker plate 1\. They set off at the next simulated minute\./);

    const advance = [...panel().querySelectorAll('button')].find((b) => b.textContent === 'Advance one minute')!;
    expect(advance.disabled).toBe(false);
    advance.click();
    for (let i = 0; i < 6; i += 1) await settle();
    expect(controlClient.step).toHaveBeenCalledTimes(1);
    expect(panel().querySelector('.world-inhabitants-summary')?.textContent).toMatch(/Simulated minute 1\./);
    // The top says who, what now and why in words, naming the place by the object's title.
    const inspector = mounted.root.querySelector<HTMLElement>('.living-world-inspector')!;
    expect(inspector.querySelector('h3')?.textContent).toBe('Person 0');
    expect(inspector.querySelector('p')?.textContent).toBe(
      'A simulated steward, invented for this world: not anyone you know, and nothing they do is a memory.');
    expect(inspector.querySelector('.living-world-activity')?.textContent)
      .toBe('Resting at Marker plate 1, 2 more simulated minutes. Because you asked them to go there.');
    // The recorded explanation and how the person is drawn stay below, in the details.
    const details = [...inspector.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(details).toContainEqual(['Recorded explanation', 'Person 0 (simulated) rests at the plate.']);
    // Resting is what the simulation says; at a plate, which has no seat, a catalog person sits on
    // the ground in front of the place.
    expect(details).toContainEqual(['Drawn as', 'Sitting on the ground in front of the place.']);
    // At a place with a seat, the words say the seat, from the place, before they have reached it.
    crowd.inhabitantSeatAtPlace.mockReturnValue(true);
    controls.onInteract?.();
    for (let i = 0; i < 2; i += 1) await settle();
    const seated = [...inspector.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(seated).toContainEqual(['Drawn as', 'Sitting on the seat at the place.']);
    mounted.dispose();
  });
});

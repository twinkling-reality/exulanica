// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  atlasVec3, islandId, localVec3, makeIsland, placement, sceneDisplayFrame,
} from '@exulanica/atlas-core';
import { ApiError } from '@exulanica/graph-client';
import {
  AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M,
  authoredGroundSurface,
} from '@exulanica/atlas-react/playcanvas';
import { COMPOSITION_BLOCKED_REASONS } from '../src/composition-preview-api.js';
import { mountObjects, type MountedObjects, type ObjectsDependencies } from '../src/composition/objects.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { WorldObjectsClient, WorldObjectsContractError } from '../src/world-objects-api.js';
import type {
  AlternateVersion, AuthoredObject, ReviewedAsset,
} from '../src/world-objects-api.js';

/**
 * The authored-object surface, against a scripted authority.
 *
 * The thing under test is the ORDER: nothing reaches the client until the confirmation surface has
 * been shown and confirmed. So the client here is a script that records every call, and the
 * assertion that matters most in this file is the one that counts zero of them.
 *
 * The renderer is a script too. What the surface owes the renderer is a region-local pose and a
 * control call; what the renderer owes the surface is a refusal it can put on the screen. Neither
 * needs a GPU, and the container decoding that does is tested where it lives, in
 * `atlas-react/test/scene-objects.test.ts`.
 */

const REGION = islandId('region-a');
const SCENE = 'scene-a';
const STATE = 'a'.repeat(64);

/**
 * The region an object stands in, built the way the scene graph builds one.
 *
 * A hand-written literal is not enough: `footprintRadiusLocal` is what decides whether the visitor
 * is standing IN this region or merely nearest to it, and a fixture missing it made every
 * placement refuse. That is the same defect in miniature that the browser check found in the
 * product, so the fixture is built by the same function the application uses.
 */
const region = (footprintRadiusLocal = 20, awayBy = 0) => makeIsland({
  islandId: REGION,
  createdAt: 0,
  placement: placement(atlasVec3(awayBy, 0, 0), 0, 1),
  rung: 3,
  scaleIsMetric: false,
  footprintRadiusLocal,
  viewpointLocal: localVec3(0, 0, 0),
  anchors: [],
  layoutEntities: new Set(),
});

const asset = (over: Partial<ReviewedAsset> = {}): ReviewedAsset => Object.freeze({
  assetKey: 'cc0.marker-pillar',
  title: 'Marker pillar',
  summary: 'A square pillar.',
  mediaType: 'model/gltf-binary',
  contentSha256: 'b'.repeat(64),
  byteSize: 784,
  licenceId: 'CC0-1.0',
  licenceSha256: 'c'.repeat(64),
  availability: 'available',
  ...over,
});

const objectRecord = (over: Partial<AuthoredObject> = {}): AuthoredObject => Object.freeze({
  objectId: 'object:lantern',
  asset: asset(),
  regionId: String(REGION),
  transform: Object.freeze({
    coordinateSpace: 'region_local',
    coordinateUnit: 'millimetre',
    xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 0, scaleMilli: 1000,
  }),
  origin: Object.freeze({ kind: 'authored', role: 'fictional' as const }),
  behaviour: null,
  removed: false,
  ...over,
});

const version = (over: Partial<AlternateVersion> = {}): AlternateVersion => Object.freeze({
  schemaVersion: 1,
  versionId: '6f1d2c40-0000-7000-8000-000000000001',
  worldId: 'atlas:default',
  sourceSnapshotId: '6f1d2c40-0000-7000-8000-000000000002',
  parentVersionId: null,
  title: 'Lantern study',
  origin: 'authored',
  styleVersionId: null,
  stateSha256: STATE,
  editSeq: 0,
  sourceInvalidated: false,
  createdBy: '6f1d2c40-0000-7000-8000-000000000003',
  createdAt: '2026-09-09T12:00:00+00:00',
  objects: Object.freeze([]),
  elementOverrides: Object.freeze([]),
  edits: Object.freeze([]),
  ...over,
});

const edit = (editSeq: number, kind: string, over: Record<string, unknown> = {}) => Object.freeze({
  editId: `edit-${editSeq}`,
  editSeq,
  kind,
  objectId: 'object:lantern',
  elementId: null,
  undoneEditId: null,
  baseStateSha256: STATE,
  resultStateSha256: STATE,
  actor: 'actor',
  recordedAt: '2026-09-09T12:00:00+00:00',
  ...over,
});

/** The renderer, scripted: it records what it was told to draw and answers what it refuses. */
function runtime() {
  const placed = new Map<string, { pose: unknown; motion: string }>();
  return {
    get objectIds() { return [...placed.keys()]; },
    clear: vi.fn(() => { placed.clear(); }),
    cancelPending: vi.fn(),
    motionStateOf: (id: string) => placed.get(id)?.motion ?? null,
    place: vi.fn(async (object: { objectId: string; behaviour: unknown; transform: unknown }) => {
      const behaviour = object.behaviour as { behaviourKey: string; behaviourVersion: number } | null;
      const supported = behaviour === null
        || (behaviour.behaviourKey === 'motion.bounded-path' && behaviour.behaviourVersion === 1);
      placed.set(object.objectId, {
        pose: object.transform,
        motion: behaviour === null ? 'none' : supported ? 'at-rest' : 'none',
      });
      return {
        objectId: object.objectId,
        motion: behaviour !== null && supported ? 'attached' as const : 'none' as const,
        notices: supported ? [] : [`“${behaviour!.behaviourKey}@${behaviour!.behaviourVersion}” is not a behaviour this client can run.`],
      };
    }),
    remove: vi.fn((id: string) => placed.delete(id)),
    setTransform: vi.fn((id: string, pose: unknown) => {
      const held = placed.get(id);
      if (held === undefined) return false;
      placed.set(id, { ...held, pose });
      return true;
    }),
    control: vi.fn((id: string, action: string) => {
      const held = placed.get(id);
      if (held === undefined) return { ok: false as const, reason: 'That object is not in this world.' };
      if (held.motion === 'none') {
        return { ok: false as const, reason: 'This object carries no motion this client can run, so there is nothing to start.' };
      }
      placed.set(id, {
        ...held,
        motion: action === 'trigger' ? 'running' : action === 'stop' ? 'held' : 'at-rest',
      });
      return { ok: true as const };
    }),
    poseOf: (id: string) => placed.get(id)?.pose ?? null,
  };
}

/** A composition preview body, in the wire shape the server answers with. Ready unless told. */
type WireBody = {
  readonly source: { readonly asset_key: string };
  readonly placement: { readonly subject_id: string } | null;
};
function previewAnswer(
  base: AlternateVersion,
  body: WireBody,
  blockedReason: string | null = null,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    availability: blockedReason === null ? 'ready' : 'blocked',
    blocked_reason: blockedReason,
    blocked_detail: blockedReason === null ? null : 'The server said why in its own words.',
    source: {
      kind: 'reviewed_asset', asset_key: body.source.asset_key,
      content_sha256: blockedReason === null ? 'b'.repeat(64) : null,
      bytes: blockedReason === null ? 'available' : null,
    },
    version: {
      authored_version_id: base.versionId, world_id: base.worldId,
      state_sha256: base.stateSha256, edit_seq: base.editSeq,
      source_snapshot_id: base.sourceSnapshotId, style_version_id: null,
    },
    would_change: {
      kind: 'add_object',
      subject_id: body.placement?.subject_id ?? null,
      document: blockedReason === null ? { object_id: body.placement?.subject_id } : null,
      preserves: ['source_snapshot_id', 'style_version_id', 'other_subjects', 'prior_edits'],
    },
    ...over,
  };
}

/** The authority, scripted: it records every call and answers whatever the test queued. */
function script(initial: AlternateVersion = version()) {
  const calls: { name: string; args: unknown[] }[] = [];
  let current = initial;
  let answer: unknown = null;
  let verdict: ((base: AlternateVersion, body: WireBody) => unknown) | Error | null = null;
  const record = (name: string) => (...args: unknown[]) => {
    calls.push({ name, args });
    if (answer instanceof Error) { const thrown = answer; answer = null; return Promise.reject(thrown); }
    const queued = answer;
    answer = null;
    return Promise.resolve(queued ?? { kind: 'recorded', version: current });
  };
  return {
    calls,
    answerWith(next: unknown) { answer = next; },
    /** The next preview answer: a verdict built from the request, or a thrown failure. */
    previewWith(next: ((base: AlternateVersion, body: WireBody) => unknown) | Error) { verdict = next; },
    setCurrent(next: AlternateVersion) { current = next; },
    client: {
      connect: vi.fn(async () => {
        calls.push({ name: 'connect', args: [] });
        return { assets: [asset()], version: current };
      }),
      readVersion: vi.fn(async () => {
        calls.push({ name: 'readVersion', args: [] });
        return current;
      }),
      compositionPreview: vi.fn(async (base: AlternateVersion, body: WireBody) => {
        calls.push({ name: 'preview', args: [base, body] });
        const next = verdict;
        verdict = null;
        if (next instanceof Error) throw next;
        return next === null ? previewAnswer(base, body) : next(base, body);
      }),
      compositionApply: record('apply'),
      place: record('place'),
      move: record('move'),
      remove: record('remove'),
      undo: record('undo'),
    } as unknown as WorldObjectsClient,
  };
}

const mounts: MountedObjects[] = [];
afterEach(() => { for (const mounted of mounts.splice(0)) mounted.dispose(); });

function harness(
  over: Partial<ObjectsDependencies> & {
    readonly noClient?: true;
    readonly footprint?: number;
    readonly awayBy?: number;
    readonly initial?: AlternateVersion;
    readonly representationSubjects?: readonly string[];
    /** Where the visitor stands, in atlas metres, looking down -Z. */
    readonly standAt?: readonly [number, number, number];
  } = {},
  previewMode = false,
) {
  const objects = runtime();
  const authority = script(over.initial ?? version());
  const representationObservers = new Set<(subjectId: string | null, reason: string) => void>();
  const representationReport = {
    subjects: (over.representationSubjects ?? []).map(subjectId => ({
      subject: { subjectId, availability: 'available' },
    })),
    selection: null as string | null,
  };
  const binding = {
    objects,
    // A third-person camera is behind the player, outside this region's placement reach.
    cameraPose: () => ({ position: atlasVec3(12, 3, 12), forward: atlasVec3(-1, 0, -1) }),
    playerPose: () => ({
      position: atlasVec3(...(over.standAt ?? [0, 1.6, 0])),
      forward: atlasVec3(0, 0, -1),
    }),
    engageFocusedAnchor: () => null,
    table: { atlasPositions: new Float32Array([0, 0, 0]) },
    representationReport,
    setRepresentationSelection: vi.fn((subjectId: string | null) => {
      representationReport.selection = subjectId;
      for (const observer of representationObservers) observer(subjectId, 'explicit');
      return representationReport;
    }),
    observeRepresentationSelection: vi.fn((observer: (subjectId: string | null, reason: string) => void) => {
      representationObservers.add(observer);
      return () => { representationObservers.delete(observer); };
    }),
    field: {
      setPlacementLandingPose: vi.fn(),
    },
  };
  const clearObjects = objects.clear.getMockImplementation()!;
  objects.clear.mockImplementation(() => {
    clearObjects();
    if (representationReport.selection === null) return;
    representationReport.selection = null;
    for (const observer of representationObservers) observer(null, 'unregistered');
  });
  const state = {
    atlas: {
      binding,
    },
    displayFrames: new Map(),
    placedPointMaps: [{ islandId: REGION, sceneId: SCENE }],
    trainedGeometry: [],
    pointMaps: undefined,
  } as unknown as SessionState;
  const env = { preview: previewMode } as unknown as AppEnvironment;
  const travel: { message: string; kind?: string }[] = [];
  const mounted = mountObjects({
    env,
    state,
    credentials: { baseUrl: 'https://exulanica.test', token: 'token' },
    scene: {
      islands: [region(over.footprint, over.awayBy)],
    } as unknown as ObjectsDependencies['scene'],
    showTravelStatus: (message, kind) => travel.push({ message, ...(kind === undefined ? {} : { kind }) }),
    isWorldPrimary: () => true,
    hideWritePathConfirm: vi.fn(),
    ...(over.noClient === true ? {} : { client: authority.client }),
    loadBytes: async () => new ArrayBuffer(784),
    ...over,
  });
  mounts.push(mounted);
  document.body.append(mounted.panel.root, mounted.confirm.root);
  return { mounted, objects, authority, travel, state, binding, representationObservers };
}

const button = (root: HTMLElement, label: string): HTMLButtonElement => {
  const all = [...root.querySelectorAll('button')];
  const found = all.find((node) => node.textContent === label)
    ?? all.find((node) => node.textContent?.startsWith(label) === true);
  if (found === undefined) throw new Error(`no “${label}” control in ${root.className}`);
  return found as HTMLButtonElement;
};

/** Every write. `place` is here so a regression to the direct object route would show. */
const writes = (calls: { name: string }[]): string[] =>
  calls.filter((call) => ['apply', 'place', 'move', 'remove', 'undo'].includes(call.name))
    .map((call) => call.name);

type AppliedBody = {
  readonly source: Record<string, unknown>;
  readonly placement: {
    readonly subject_id: string;
    readonly region_id: string;
    readonly transform: Record<string, number>;
    readonly origin_role: string;
    readonly behaviour: unknown;
  };
};

/** The body the one apply call carried. */
const applied = (calls: { name: string; args: unknown[] }[]): AppliedBody =>
  calls.find((call) => call.name === 'apply')!.args[1] as AppliedBody;

const confirmButton = (h: { mounted: MountedObjects }): HTMLButtonElement =>
  button(h.mounted.confirm.root, 'Confirm');

/** Wait for the server's ready verdict and the Confirm it releases. */
async function verdictReady(h: { mounted: MountedObjects }): Promise<void> {
  await vi.waitFor(() => {
    expect(h.mounted.confirm.root.querySelector('.composition-verdict')?.getAttribute('data-state'))
      .toBe('ready');
    expect(confirmButton(h).disabled).toBe(false);
  });
}

/** The words a person reads in the verdict, without the folded-away details. */
function visibleVerdict(root: HTMLElement): string {
  const verdict = root.querySelector<HTMLElement>('.composition-verdict');
  if (verdict === null) return '';
  const copy = verdict.cloneNode(true) as HTMLElement;
  for (const details of copy.querySelectorAll('details')) details.remove();
  return copy.textContent ?? '';
}

const arrow = (code: string) => {
  window.dispatchEvent(new KeyboardEvent('keydown', { code, bubbles: true, cancelable: true }));
};

async function place(
  h: ReturnType<typeof harness>,
  motion = false,
  role: string | null = 'fictional',
): Promise<void> {
  if (role !== null) {
    const select = h.mounted.panel.root.querySelector<HTMLSelectElement>('#object-placement-role')!;
    select.value = role;
    select.dispatchEvent(new Event('change'));
  }
  if (motion) {
    const toggle = h.mounted.panel.root.querySelector<HTMLInputElement>('#object-placement-motion')!;
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change'));
  }
  button(h.mounted.panel.root, 'Place before me').click();
}

beforeEach(() => { document.body.replaceChildren(); });

describe('authorized district placement', () => {
  const district = () => ({ versionId: version().versionId, regionId: String(REGION),
    translationMm: [10000, 3000, -7000] as const,
    boundsMm: [-20000, -20000, 20000, 20000] as const });

  it('uses district-local ground and translation without changing the memory island', async () => {
    const h = harness({ districtPlacement: district, awayBy: 1000 });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    await place(h);
    expect(h.mounted.confirm.root.textContent).toContain('district’s authored ground');
    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    expect(applied(h.authority.calls).placement.transform)
      .toMatchObject({ x_mm: -10000, y_mm: -3000, z_mm: 3500 });
  });

  it('refuses an unavailable binding, a different version and a target beyond the district', async () => {
    for (const binding of [null, { ...district(), versionId: 'other' }, { ...district(), boundsMm: [-1000, -1000, 1000, 1000] as const }]) {
      const h = harness({ districtPlacement: () => binding });
      h.state.placedPointMaps = [];
      await h.mounted.begin();
      await place(h);
      expect(h.mounted.confirm.root.hidden).toBe(true);
      expect(writes(h.authority.calls)).toEqual([]);
      h.mounted.dispose();
    }
  });

  it('does not draw late asset bytes after the district is withdrawn', async () => {
    let binding: ReturnType<typeof district> | null = district();
    let resolve!: (bytes: ArrayBuffer) => void;
    const bytes = new Promise<ArrayBuffer>(done => { resolve = done; });
    const loadBytes = vi.fn(() => bytes);
    const h = harness({ districtPlacement: () => binding, loadBytes,
      initial: version({ objects: [objectRecord()] }) });
    h.state.placedPointMaps = [];
    const loading = h.mounted.begin();
    await vi.waitFor(() => expect(loadBytes).toHaveBeenCalled());
    binding = null;
    resolve(new ArrayBuffer(784));
    await loading;
    expect(h.objects.place).not.toHaveBeenCalled();
  });

  it('refuses a confirmation after the authorized frame is withdrawn', async () => {
    let binding: ReturnType<typeof district> | null = district();
    const h = harness({ districtPlacement: () => binding });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    binding = null;
    confirmButton(h).click();
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent).toContain('district binding changed'));
    expect(writes(h.authority.calls)).toEqual([]);
  });
});

describe('nothing reaches the authority without a confirmation', () => {
  it('refreshes society only after a recorded edit and preserves save success if refresh fails', async () => {
    const onAuthoredEdit = vi.fn(async () => { throw new Error('refresh failed'); });
    const h = harness({ onAuthoredEdit });
    await h.mounted.begin();
    await place(h);
    expect(onAuthoredEdit).not.toHaveBeenCalled();
    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(onAuthoredEdit).toHaveBeenCalledWith(version().versionId));
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(true));
    expect(writes(h.authority.calls)).toEqual(['apply']);
    expect(h.travel.some(item => item.message.includes('Your change was saved.'))).toBe(true);
  });

  it('shows the confirmation surface and writes nothing when an object is placed', async () => {
    const h = harness();
    await h.mounted.begin();
    expect(writes(h.authority.calls)).toEqual([]);

    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(false);
    expect(h.mounted.confirm.root.textContent).toContain('Before anything is written');
    expect(h.mounted.confirm.root.textContent).toContain('Marker pillar');
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('marks the placementPoseBeforeVisitor landing on the ground during confirm, then applies that pose', async () => {
    const h = harness();
    await h.mounted.begin();
    const setLanding = h.binding.field.setPlacementLandingPose as ReturnType<typeof vi.fn>;
    expect(setLanding).not.toHaveBeenCalled();

    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(false);
    expect(setLanding).toHaveBeenCalledTimes(1);
    const landing = setLanding.mock.calls[0]![0] as {
      position: { x: number; y: number; z: number };
      yaw: number;
    };
    // Same step `placementPoseBeforeVisitor` returns for the harness player looking down -Z.
    expect(landing.position.x).toBeCloseTo(0, 5);
    expect(landing.position.z).toBeCloseTo(-3.5, 5);
    expect(Number.isFinite(landing.yaw)).toBe(true);

    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    expect(setLanding).toHaveBeenLastCalledWith(null);
    const request = applied(h.authority.calls);
    expect(request.placement.transform['x_mm']).toBe(0);
    expect(request.placement.transform['z_mm']).toBeCloseTo(-3500, 0);
  });

  it('clears the placement landing mark when confirmation is cancelled', async () => {
    const h = harness();
    await h.mounted.begin();
    const setLanding = h.binding.field.setPlacementLandingPose as ReturnType<typeof vi.fn>;
    await place(h);
    expect(setLanding).toHaveBeenCalledWith(expect.objectContaining({
      position: expect.objectContaining({ z: expect.closeTo(-3.5, 5) }),
    }));
    button(h.mounted.confirm.root, 'Cancel').click();
    expect(setLanding).toHaveBeenLastCalledWith(null);
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('places from the player despite an offset third-person camera, only after confirmation', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));

    const request = applied(h.authority.calls);
    // The source is named by reviewed key; the server resolves its digest and bytes.
    expect(request.source).toEqual({ kind: 'reviewed_asset', asset_key: 'cc0.marker-pillar' });
    expect(request.placement.region_id).toBe(String(REGION));
    expect(request.placement.origin_role).toBe('fictional');
    expect(request.placement.behaviour).toBeNull();
    expect(request.placement.subject_id).toMatch(/^object-/);
    // Region-local millimetres, a step ahead of a visitor looking down region -Z.
    const pose = request.placement.transform;
    expect(pose['x_mm']).toBe(0);
    expect(pose['y_mm']).toBe(0);
    expect(pose['z_mm']).toBeCloseTo(-3500, 0);
    expect(pose['scale_milli']).toBe(1000);
    for (const value of Object.values(pose)) expect(Number.isSafeInteger(value)).toBe(true);
  });

  it('writes nothing when the confirmation is cancelled', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    button(h.mounted.confirm.root, 'Cancel').click();
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('carries the chosen motion through in the reviewed parameter names and units', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h, true);
    expect(h.mounted.confirm.root.textContent).toContain('travelling');
    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    expect(applied(h.authority.calls).placement.behaviour).toEqual({
      behaviour_key: 'motion.bounded-path',
      behaviour_version: 1,
      // The registry's own defaults, in the registry's own units.
      parameters: { axis: 'x', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000 },
    });
  });

  it('says a removal CAN be taken back, because the authority stores it rather than executing it', async () => {
    const h = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    button(h.mounted.panel.root, 'Remove').click();
    // The contract keeps the row with removed = true so undo restores the same identity. Saying
    // "this cannot be undone" here would be the false reversibility claim confirm.ts warns about.
    expect(h.mounted.confirm.root.textContent).toContain('reversible event');
    expect(h.mounted.confirm.root.textContent).toContain('Use “Take back the last change”');
    expect(h.mounted.confirm.root.textContent).not.toContain('This cannot be undone');
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['remove']));
  });

  it('reports a refused write in the confirmation surface and writes nothing more', async () => {
    const h = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    h.authority.answerWith(new Error('the authority refused'));
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('the authority refused');
  });

  it('treats a moved base as a refusal that re-reads, never as an overwrite', async () => {
    const onAuthoredEdit = vi.fn(async () => undefined);
    const h = harness({ onAuthoredEdit, initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await h.mounted.begin();
    h.authority.answerWith({ kind: 'stale', current: version({ objects: [] }) });
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() =>
      expect(h.mounted.panel.root.textContent).toContain('This world changed while you were deciding'));
    expect(writes(h.authority.calls)).toEqual(['remove']);
    expect(onAuthoredEdit).not.toHaveBeenCalled();
  });

  it('refuses to add to a version whose source was deleted, before staging anything', async () => {
    const h = harness({ initial: version({ sourceInvalidated: true }) });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('was deleted');
  });

  it('refuses an asset whose reviewed bytes are not in storage, and still lists it', async () => {
    const unavailable = asset({ availability: 'unavailable_asset' });
    const h = harness();
    (h.authority.client as unknown as { connect: unknown }).connect = vi.fn(async () => ({
      assets: [unavailable], version: version(),
    }));
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    // Listed, named, and unselectable: a storage failure must not become a shorter menu.
    expect(h.mounted.panel.root.textContent).toContain('Marker pillar');
    expect(h.mounted.panel.root.textContent).toContain('unavailable_asset');
    expect(button(h.mounted.panel.root, 'Place before me').disabled).toBe(true);
  });
});

describe('adding goes through the server’s preview, then the same request is applied', () => {
  const refusedVerdict = async (h: { mounted: MountedObjects }): Promise<HTMLElement> => {
    await vi.waitFor(() => expect(
      h.mounted.confirm.root.querySelector('.composition-verdict')?.getAttribute('data-state'),
    ).toBe('refused'));
    return h.mounted.confirm.root.querySelector<HTMLElement>('.composition-verdict')!;
  };

  it('holds Confirm until the server says ready, and applies exactly what it previewed', async () => {
    let answer!: (value: unknown) => void;
    const h = harness();
    await h.mounted.begin();
    h.authority.previewWith((base, body) => new Promise((resolve) => {
      answer = () => resolve(previewAnswer(base, body));
    }));
    await place(h);
    expect(h.mounted.confirm.root.textContent).toContain('Checking with the world');
    expect(confirmButton(h).disabled).toBe(true);
    confirmButton(h).click();
    // Even a Confirm forced open before the verdict arrives sends nothing.
    confirmButton(h).disabled = false;
    confirmButton(h).click();
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(writes(h.authority.calls)).toEqual([]);

    answer(undefined);
    await verdictReady(h);
    expect(visibleVerdict(h.mounted.confirm.root)).toContain(
      'Ready to add. “Marker pillar” will stand where the mark shows.',
    );
    // Said only because the server listed what apply leaves as it is.
    expect(visibleVerdict(h.mounted.confirm.root)).toContain('Everything else in this world stays as it is.');
    expect(writes(h.authority.calls)).toEqual([]);

    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    const previewed = h.authority.calls.find((call) => call.name === 'preview')!;
    const apply = h.authority.calls.find((call) => call.name === 'apply')!;
    expect(apply.args[1]).toEqual(previewed.args[1]);
    expect(apply.args[0]).toBe(previewed.args[0]);
    expect((apply.args[0] as AlternateVersion).stateSha256).toBe(STATE);
  });

  it('says what happened and what to do for every blocked code, with the code only in the details', async () => {
    const sentences = new Set<string>();
    for (const code of COMPOSITION_BLOCKED_REASONS) {
      const h = harness();
      await h.mounted.begin();
      h.authority.previewWith((base, body) => previewAnswer(base, body, code));
      await place(h);
      const verdict = await refusedVerdict(h);
      const visible = visibleVerdict(h.mounted.confirm.root);
      expect(visible, code).not.toContain(code);
      expect(visible, code).not.toMatch(/[a-z]_[a-z]/);
      expect(verdict.querySelector('details')?.textContent, code).toContain(code);
      expect(confirmButton(h).disabled, code).toBe(true);
      confirmButton(h).click();
      sentences.add(verdict.querySelector('.composition-verdict-sentence')!.textContent ?? '');
      expect(writes(h.authority.calls), code).toEqual([]);
      h.mounted.dispose();
    }
    // Every code has its own sentence rather than one generic refusal.
    expect(sentences.size).toBe(COMPOSITION_BLOCKED_REASONS.length);
  });

  it('gives a code it does not know a generic sentence and keeps that code in the details', async () => {
    const h = harness();
    await h.mounted.begin();
    h.authority.previewWith((base, body) => previewAnswer(base, body, 'a_code_from_later'));
    await place(h);
    const verdict = await refusedVerdict(h);
    expect(visibleVerdict(h.mounted.confirm.root)).toContain('does not recognise');
    expect(visibleVerdict(h.mounted.confirm.root)).not.toContain('a_code_from_later');
    expect(verdict.querySelector('details')?.textContent).toContain('a_code_from_later');
    expect(confirmButton(h).disabled).toBe(true);
  });

  it('reads a stale base again, draws the current world, and checks again only when asked', async () => {
    const moved = version({
      stateSha256: 'd'.repeat(64),
      editSeq: 1,
      objects: [objectRecord()],
      edits: [edit(1, 'add_object')],
    });
    const h = harness();
    await h.mounted.begin();
    h.authority.setCurrent(moved);
    h.authority.previewWith((base, body) => previewAnswer(base, body, 'stale_base', {
      version: {
        authored_version_id: base.versionId, world_id: base.worldId,
        state_sha256: moved.stateSha256, edit_seq: 1,
        source_snapshot_id: base.sourceSnapshotId, style_version_id: null,
      },
    }));
    await place(h);
    await refusedVerdict(h);
    await vi.waitFor(() => expect(h.objects.objectIds).toEqual(['object:lantern']));
    expect(h.authority.calls.filter((call) => call.name === 'preview')).toHaveLength(1);

    button(h.mounted.confirm.root, 'Check again').click();
    await verdictReady(h);
    const previews = h.authority.calls.filter((call) => call.name === 'preview');
    expect(previews).toHaveLength(2);
    expect((previews[1]!.args[0] as AlternateVersion).stateSha256).toBe('d'.repeat(64));
    const second = previews[1]!.args[1] as AppliedBody;
    expect(second.placement.subject_id).toMatch(/^object-2-/);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    expect((applied(h.authority.calls) as AppliedBody).placement.subject_id)
      .toBe(second.placement.subject_id);
  });

  it('leaves the world unchanged and says why when apply is refused', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    const drawsBefore = h.objects.clear.mock.calls.length;
    h.authority.answerWith(new ApiError(409, 'composition_blocked', 'asset_bytes_unavailable'));
    confirmButton(h).click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('missing from storage');
    expect(h.mounted.confirm.root.querySelector('details')?.textContent)
      .toContain('asset_bytes_unavailable');
    expect(h.mounted.confirm.root.querySelector('.confirm-refused')?.textContent)
      .not.toContain('asset_bytes_unavailable');
    expect(h.objects.clear.mock.calls.length).toBe(drawsBefore);
    expect(h.objects.objectIds).toEqual([]);
    expect(writes(h.authority.calls)).toEqual(['apply']);
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });

  it('offers a stale apply back as a fresh check against the world read again', async () => {
    const moved = version({ stateSha256: 'e'.repeat(64), editSeq: 4 });
    const h = harness();
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    h.authority.answerWith({ kind: 'stale', current: moved });
    confirmButton(h).click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('This world changed after it was last read'));
    button(h.mounted.confirm.root, 'Check again').click();
    await verdictReady(h);
    const previews = h.authority.calls.filter((call) => call.name === 'preview');
    expect((previews.at(-1)!.args[0] as AlternateVersion).stateSha256).toBe('e'.repeat(64));
    expect(writes(h.authority.calls)).toEqual(['apply']);
  });

  it('draws what the returned version holds, and takes it back through the version undo', async () => {
    const added = version({
      stateSha256: 'f'.repeat(64),
      editSeq: 1,
      objects: [objectRecord()],
      edits: [edit(1, 'add_object')],
    });
    const h = harness();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    await verdictReady(h);
    h.authority.answerWith({ kind: 'recorded', version: added });
    confirmButton(h).click();
    await vi.waitFor(() => expect(h.objects.objectIds).toEqual(['object:lantern']));
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(true));
    expect(h.mounted.panel.root.textContent).toContain('Added.');

    const undo = button(h.mounted.panel.root, 'Take back the last change');
    expect(undo.disabled).toBe(false);
    undo.click();
    expect(h.mounted.confirm.root.textContent).toContain('an object you added');
    h.authority.answerWith({
      kind: 'recorded',
      version: version({
        stateSha256: STATE,
        editSeq: 2,
        edits: [edit(1, 'add_object'), edit(2, 'undo', { editId: 'edit-2', undoneEditId: 'edit-1' })],
      }),
    });
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply', 'undo']));
    expect(h.authority.calls.find((call) => call.name === 'undo')!.args[0]).toBe(added);
    await vi.waitFor(() => expect(h.objects.objectIds).toEqual([]));
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });

  it('says it is not known whether an apply was recorded when its answer is lost', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    h.authority.answerWith(new TypeError('Failed to fetch'));
    confirmButton(h).click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('not known whether this was added'));
    expect(h.mounted.confirm.root.textContent).toContain('Not confirmed');
    expect(h.mounted.confirm.root.textContent).not.toContain('Nothing was written');
    expect(() => button(h.mounted.confirm.root, 'Check again')).toThrow();
  });

  it('asks for a reload, not a retry, when the saved world moved elsewhere', async () => {
    const h = harness();
    await h.mounted.begin();
    await place(h);
    await verdictReady(h);
    h.authority.answerWith(new WorldObjectsContractError(
      'saved_entry_conflict',
      'This saved world changed elsewhere. The edit was not recorded. Reload before trying again.',
    ));
    confirmButton(h).click();
    await vi.waitFor(() =>
      expect(h.mounted.confirm.root.textContent).toContain('changed elsewhere'));
    expect(h.mounted.confirm.root.textContent).toContain('Reload the world');
    expect(() => button(h.mounted.confirm.root, 'Check again')).toThrow();
  });

  it('does not take a ready answer about a different subject or base as this placement’s verdict', async () => {
    for (const over of [
      (base: AlternateVersion, body: WireBody) => previewAnswer(base, body, null, {
        would_change: { kind: 'add_object', subject_id: 'object:someone-else', document: {}, preserves: [] },
      }),
      (base: AlternateVersion, body: WireBody) => previewAnswer(base, body, null, {
        version: {
          authored_version_id: base.versionId, world_id: base.worldId,
          state_sha256: '0'.repeat(64), edit_seq: 9,
          source_snapshot_id: base.sourceSnapshotId, style_version_id: null,
        },
      }),
    ]) {
      const h = harness();
      await h.mounted.begin();
      h.authority.previewWith(over);
      await place(h);
      await refusedVerdict(h);
      expect(visibleVerdict(h.mounted.confirm.root)).toContain('different change');
      expect(confirmButton(h).disabled).toBe(true);
      h.mounted.dispose();
    }
  });

  it('ignores a verdict that arrives after the placement was cancelled', async () => {
    let answer!: () => void;
    const h = harness();
    await h.mounted.begin();
    h.authority.previewWith((base, body) => new Promise((resolve) => {
      answer = () => resolve(previewAnswer(base, body));
    }));
    await place(h);
    button(h.mounted.confirm.root, 'Cancel').click();
    answer();
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('says the check could not be made when the preview request fails, and offers it again', async () => {
    const h = harness();
    await h.mounted.begin();
    h.authority.previewWith(new TypeError('Failed to fetch'));
    await place(h);
    await refusedVerdict(h);
    expect(visibleVerdict(h.mounted.confirm.root)).toContain('could not be reached');
    button(h.mounted.confirm.root, 'Check again').click();
    await verdictReady(h);
    expect(writes(h.authority.calls)).toEqual([]);
  });
});

describe('an authored starter keeps additions on its declared ground', () => {
  const starter = {
    regionId: 'region:starter', kind: 'flat', halfWidthMm: 12_000, halfDepthMm: 12_000, elevationMm: 0,
  } as const;

  it('previews and applies a spot on the ground in the starter region', async () => {
    const h = harness({ authoredRegion: starter });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    await place(h);
    expect(h.mounted.confirm.root.textContent).toContain('this world’s authored ground');
    await verdictReady(h);
    const previewed = h.authority.calls.find((call) => call.name === 'preview')!.args[1] as AppliedBody;
    expect(previewed.placement.region_id).toBe('region:starter');
    expect(previewed.placement.transform).toMatchObject({ x_mm: 0, y_mm: 0, z_mm: -3500 });
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
  });

  it('refuses a spot past the edge of the ground before asking the server anything', async () => {
    const h = harness({ authoredRegion: starter, standAt: [0, 1.6, -10] });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.panel.root.textContent).toContain('outside this world’s authored ground');
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.authority.calls.filter((call) => call.name === 'preview')).toEqual([]);
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('never shows the person a region id, in the confirmation or in the list', async () => {
    const h = harness({ authoredRegion: starter });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.confirm.root.textContent)
      .toContain('Add “Marker pillar” where the mark shows, standing on this world’s authored ground.');
    expect(h.mounted.confirm.root.textContent).not.toContain('region');
    await verdictReady(h);
    h.authority.answerWith({
      kind: 'recorded',
      version: version({
        stateSha256: 'f'.repeat(64), editSeq: 1,
        objects: [objectRecord({ regionId: 'region:starter' })],
        edits: [edit(1, 'add_object')],
      }),
    });
    confirmButton(h).click();
    await vi.waitFor(() => expect(h.objects.objectIds).toEqual(['object:lantern']));
    const list = h.mounted.panel.root.querySelector('.object-placement-list')!.textContent ?? '';
    expect(list).toContain('Marker pillar');
    expect(list).not.toContain('region');

    // A photographed region's id is no more a place name than the starter's.
    const photographed = harness({ initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }) });
    await photographed.mounted.begin();
    expect(photographed.mounted.panel.root.querySelector('.object-placement-list')!.textContent)
      .not.toContain(String(REGION));
  });

  it('does not draw a saved object that stands outside the ground', async () => {
    const h = harness({
      authoredRegion: starter,
      initial: version({ objects: [objectRecord({
        regionId: 'region:starter',
        transform: Object.freeze({
          coordinateSpace: 'region_local', coordinateUnit: 'millimetre',
          xMm: 20_000, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000,
        }),
      })] }),
    });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    expect(h.objects.objectIds).toEqual([]);
    expect(h.travel.some((item) => item.message.includes('outside this world’s authored ground'))).toBe(true);
  });
});

/**
 * A ground with no extent, at the surface that puts things on it.
 *
 * The bounded case above is version 1 of the ground module and keeps its rectangle. This is
 * version 2, which states there is no rectangle, so the only limit left is how far this renderer
 * can still draw a position. Both remain browser constraints; the authored-object API validates
 * region ownership and transforms and enforces neither.
 */
describe('an authored starter with no edge keeps additions where it can still draw them', () => {
  const endless = { regionId: 'region:starter', kind: 'endless', elevationMm: 0 } as const;
  const supportedMm = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M * 1000;

  it('adds an object a hundred metres out, where the bounded ground refused at twelve', async () => {
    const h = harness({ authoredRegion: endless, standAt: [0, 1.6, -100] });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.panel.root.textContent).not.toContain('outside this world’s authored ground');
    await verdictReady(h);
    const previewed = h.authority.calls.find((call) => call.name === 'preview')!.args[1] as AppliedBody;
    expect(previewed.placement.region_id).toBe('region:starter');
    expect(previewed.placement.transform).toMatchObject({ x_mm: 0, y_mm: 0, z_mm: -103_500 });
  });

  it('refuses a spot past the distance this renderer can still draw, before asking the server', async () => {
    const h = harness({
      authoredRegion: endless,
      standAt: [AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M + 10, 1.6, 0],
    });
    h.state.placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.panel.root.textContent).toContain('outside this world’s authored ground');
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.authority.calls.filter((call) => call.name === 'preview')).toEqual([]);
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('draws a saved object well past the old rectangle and refuses one past the support', async () => {
    const far = (xMm: number) => objectRecord({
      regionId: 'region:starter',
      transform: Object.freeze({
        coordinateSpace: 'region_local', coordinateUnit: 'millimetre',
        xMm, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000,
      }),
    });

    const drawn = harness({
      authoredRegion: endless,
      initial: version({ objects: [far(100_000)] }),
    });
    drawn.state.placedPointMaps = [];
    await drawn.mounted.begin();
    expect(drawn.objects.objectIds).toEqual(['object:lantern']);

    const refused = harness({
      authoredRegion: endless,
      initial: version({ objects: [far(supportedMm + 1)] }),
    });
    refused.state.placedPointMaps = [];
    await refused.mounted.begin();
    expect(refused.objects.objectIds).toEqual([]);
    expect(refused.travel.some(
      (item) => item.message.includes('outside this world’s authored ground'),
    )).toBe(true);
  });

  it('measures the same ground the person walks on: the placement bound is the walking radius', () => {
    // Two surfaces under one walker is a recurring defect in this product. This asserts the one
    // number rather than a copy of it: the object bound and the walking surface come from the
    // same constant, so an object can never be saved somewhere the ground does not answer.
    const surface = authoredGroundSurface({ kind: 'endless', elevationMm: 0 });
    expect(surface.sample(AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M, 0)).not.toBeNull();
    expect(surface.sample(AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M + 1, 0)).toBeNull();
  });
});

describe('a placement that cannot land honestly is refused, not faked', () => {
  it('refuses when the visitor is not standing in a region with reconstructed ground', async () => {
    const h = harness({ footprint: 2, awayBy: 500 });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('not standing in a region with reconstructed ground');
  });

  it('says so when no region in the world draws a reconstruction at all', async () => {
    const h = harness({ footprint: 2, awayBy: 500 });
    (h.state as unknown as { placedPointMaps: unknown }).placedPointMaps = [];
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.panel.root.textContent).toContain('No authorized district or reconstructed ground is available');
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('stands the object at the visitor’s feet, and says why, when no cameras were recovered', async () => {
    const h = harness();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.confirm.root.textContent).toContain('standing at your feet');
    expect(h.mounted.confirm.root.textContent).toContain('no recovered cameras');
    await verdictReady(h);
    confirmButton(h).click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['apply']));
    // Eye at 1.6 m, so feet at 0 mm.
    expect(applied(h.authority.calls).placement.transform['y_mm']).toBe(0);
  });

  it('claims measured ground only when the frame was derived from cameras', async () => {
    const h = harness();
    (h.state as unknown as { displayFrames: Map<string, unknown> }).displayFrames = new Map([
      [SCENE, sceneDisplayFrame(
        [
          { position: [3, 0, 0], forward: [-1, 0, 0], up: [0, 0, 1] },
          { position: [-3, 0, 0], forward: [1, 0, 0], up: [0, 0, 1] },
          { position: [0, 0, 3], forward: [0, 0, -1], up: [0, 0, 1] },
        ],
        [[-4, -4, -4], [4, 4, 4]],
      )],
    ]);
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    await place(h);
    expect(h.mounted.confirm.root.textContent).toContain('standing on the ground its cameras recovered');
    expect(h.mounted.confirm.root.textContent).not.toContain('at your feet');
  });
});

describe('a nudge is shown at once and written once', () => {
  const withObject = () => harness({
    initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
  });

  it('moves the object in the world and sends nothing until it is saved', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();

    arrow('ArrowLeft');
    arrow('ArrowLeft');
    arrow('PageUp');
    expect(h.objects.setTransform).toHaveBeenCalledTimes(3);
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.panel.root.textContent).toContain('Not saved yet');

    button(h.mounted.panel.root, 'Save this position').click();
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['move']));

    const moved = h.authority.calls.find((c) => c.name === 'move')!.args[2] as Record<string, number>;
    // Two quarter-metre steps left and one up, in whole millimetres.
    expect(moved['xMm']).toBe(1200 - 500);
    expect(moved['yMm']).toBe(250);
    for (const value of Object.values(moved)) expect(Number.isSafeInteger(value)).toBe(true);
  });

  it('puts the object back where it is saved when the nudge is discarded', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    arrow('ArrowRight');
    button(h.mounted.panel.root, 'Put it back').click();
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.objects.poseOf('object:lantern')).toMatchObject({ xMm: 1200, yMm: 0, zMm: -450 });
    expect(h.mounted.panel.root.textContent).not.toContain('Not saved yet');
  });

  it('ignores the arrow keys while the surface is closed or something is being typed into', async () => {
    const h = withObject();
    await h.mounted.begin();
    arrow('ArrowLeft');
    expect(h.objects.setTransform).not.toHaveBeenCalled();

    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    const input = document.createElement('input');
    document.body.append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft', bubbles: true }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('asks for a selection rather than moving nothing', async () => {
    const h = withObject();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    arrow('ArrowLeft');
    expect(h.mounted.panel.root.textContent).toContain('Choose an object in the list first');
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('opens and closes the surface on its own key', async () => {
    const h = harness();
    await h.mounted.begin();
    expect(h.mounted.panel.visible()).toBe(false);
    arrow('KeyP');
    expect(h.mounted.panel.visible()).toBe(true);
    arrow('KeyP');
    expect(h.mounted.panel.visible()).toBe(false);
  });
});

describe('the add-object hint follows what the server holds', () => {
  it('offers the add-object hint only while the version it read holds no objects', async () => {
    const hint = (h: ReturnType<typeof harness>) =>
      h.travel.filter((item) => item.message === 'Press P to add an object to this world.');

    const empty = harness();
    await empty.mounted.begin();
    expect(hint(empty)).toHaveLength(1);

    const furnished = harness({
      initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
    });
    await furnished.mounted.begin();
    expect(furnished.objects.objectIds).toEqual(['object:lantern']);
    expect(hint(furnished)).toEqual([]);
    // Read again, as a reload does: still no hint.
    await furnished.mounted.begin();
    expect(hint(furnished)).toEqual([]);

    // Everything taken out again is a world with nothing added, and the hint returns.
    const emptied = harness({
      initial: version({ objects: [objectRecord({ removed: true })], edits: [edit(1, 'add_object')] }),
    });
    await emptied.mounted.begin();
    expect(hint(emptied)).toHaveLength(1);
  });
});

describe('undo is the authority’s, not this surface’s memory of one', () => {
  it('offers nothing to take back on a version with no edits', async () => {
    const h = harness();
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });

  it('offers the newest edit no undo already names, and sends undo once confirmed', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord()],
        editSeq: 3,
        edits: [
          edit(1, 'add_object'),
          edit(2, 'move_object'),
          edit(3, 'undo', { editId: 'edit-3', undoneEditId: 'edit-2' }),
        ],
      }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    const undo = button(h.mounted.panel.root, 'Take back the last change');
    expect(undo.disabled).toBe(false);
    undo.click();
    // Edit 2 is already named by the undo at 3, and 3 is itself an undo, so 1 is next.
    expect(h.mounted.confirm.root.textContent).toContain('an object you added');
    expect(writes(h.authority.calls)).toEqual([]);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['undo']));
  });

  it('disables the control when every edit has already been taken back', async () => {
    const h = harness({
      initial: version({
        edits: [edit(1, 'add_object'), edit(2, 'undo', { editId: 'edit-2', undoneEditId: 'edit-1' })],
      }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    expect(button(h.mounted.panel.root, 'Take back the last change').disabled).toBe(true);
  });
});

describe('a removed object is kept by the authority and not drawn', () => {
  it('draws only what is not removed, and lists only that', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord(), objectRecord({ objectId: 'object:plinth', removed: true })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();
    expect(h.objects.objectIds).toEqual(['object:lantern']);
    expect(h.mounted.panel.root.textContent).toContain('Marker pillar');
    expect(h.mounted.panel.root.querySelectorAll('.object-placement-item')).toHaveLength(1);
  });
});

describe('running a motion writes nothing, and a refusal is visible', () => {
  it('triggers, stops and resets through the renderer alone', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord({
          behaviour: {
            behaviourKey: 'motion.bounded-path',
            behaviourVersion: 1,
            parameters: { axis: 'y', easing: 'smooth', travel_mm: 1000, period_milliseconds: 4000 },
          },
        })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();

    for (const [label, expected] of [
      ['Start', 'running'], ['Stop', 'held'], ['Reset', 'at-rest'],
    ] as const) {
      button(h.mounted.panel.root, label).click();
      expect(h.objects.motionStateOf('object:lantern')).toBe(expected);
    }
    expect(writes(h.authority.calls)).toEqual([]);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('Back exactly where it was placed');
  });

  it('says why a behaviour this client cannot run did not start, and keeps saying it', async () => {
    const h = harness({
      initial: version({
        objects: [objectRecord({
          behaviour: { behaviourKey: 'motion.orbit', behaviourVersion: 1, parameters: {} },
        })],
        edits: [edit(1, 'add_object')],
      }),
    });
    await h.mounted.begin();
    expect(h.mounted.panel.root.textContent).toContain('motion.orbit@1');
    expect(h.travel.some((e) => e.message.includes('motion.orbit') && e.kind === 'failure')).toBe(true);
    expect(h.mounted.panel.root.textContent).toContain('motion this client cannot run');
    expect(button(h.mounted.panel.root, 'Start').disabled).toBe(true);
  });

  it('reports an object whose bytes could not be verified without losing the rest', async () => {
    let first = true;
    const h = harness({
      initial: version({
        objects: [objectRecord(), objectRecord({ objectId: 'object:plinth' })],
        edits: [edit(1, 'add_object')],
      }),
      loadBytes: async () => {
        if (first) { first = false; throw new Error('asset SHA-256 does not match'); }
        return new ArrayBuffer(784);
      },
    });
    await h.mounted.begin();
    expect(h.travel.some((e) => e.message.includes('SHA-256'))).toBe(true);
    // The second object is still drawn: one failed asset is not a failed world.
    expect(h.objects.objectIds).toEqual(['object:plinth']);
    expect(h.mounted.panel.root.textContent).toContain('SHA-256');
  });
});

describe('the development preview offers nothing and never sends', () => {
  /*
   * The preview used to offer a marker whose content, licence and version digests were sixty-four
   * zeros. No bytes were ever hashed to them. Having nothing to place, and saying so, is the honest
   * preview.
   */
  it('lists no object, says why, and sends nothing', async () => {
    const h = harness({ noClient: true }, true);
    await h.mounted.begin();
    const text = h.mounted.panel.root.textContent ?? '';
    expect(text).toContain('no reviewed objects and no saved world');
    expect(text).toContain('No reviewed objects are available');

    await place(h);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.objects.place).not.toHaveBeenCalled();
    expect(writes(h.authority.calls)).toEqual([]);
  });
});

describe('the role is the person’s answer', () => {
  it('starts with no role chosen, refuses to place, and sends nothing', async () => {
    const h = harness();
    await h.mounted.begin();
    const role = h.mounted.panel.root.querySelector<HTMLSelectElement>('#object-placement-role')!;
    expect(role.value).toBe('');

    await place(h, false, null);
    expect(h.mounted.panel.root.textContent).toContain('Choose what this object is to you');
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.objects.place).not.toHaveBeenCalled();
    expect(writes(h.authority.calls)).toEqual([]);
  });

  it('keeps the chosen role when the panel is refreshed', async () => {
    const h = harness();
    await h.mounted.begin();
    const role = h.mounted.panel.root.querySelector<HTMLSelectElement>('#object-placement-role')!;
    role.value = 'personal';
    await h.mounted.begin();
    expect(role.value).toBe('personal');
  });
});

describe('teardown', () => {
  it('stops listening for keys once disposed', async () => {
    const h = harness({
      initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    (h.mounted as MountedObjects).dispose();
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowLeft' }));
    expect(h.objects.setTransform).not.toHaveBeenCalled();
  });

  it('ignores an authority connection that finishes after disposal', async () => {
    let resolve!: (value: { assets: readonly ReviewedAsset[]; version: AlternateVersion }) => void;
    const connected = new Promise<{ assets: readonly ReviewedAsset[]; version: AlternateVersion }>(
      (done) => { resolve = done; },
    );
    const client = { connect: vi.fn(() => connected) } as unknown as WorldObjectsClient;
    const h = harness({ client });
    const beginning = h.mounted.begin();
    h.mounted.dispose();
    resolve({ assets: [asset()], version: version({ objects: [objectRecord()] }) });
    await beginning;
    expect(h.objects.place).not.toHaveBeenCalled();
    expect(h.mounted.panel.root.textContent).not.toContain('Marker pillar');
  });

  it('discards a pending object load when a newer version omits that object', async () => {
    let resolveBytes!: (bytes: ArrayBuffer) => void;
    const bytes = new Promise<ArrayBuffer>(done => { resolveBytes = done; });
    const first = version({ versionId: 'version-one', objects: [objectRecord()] });
    const second = version({ versionId: 'version-two', objects: [] });
    const client = {
      connect: vi.fn(async (versionId?: string) => ({
        assets: [asset()], version: versionId === 'version-two' ? second : first,
      })),
    } as unknown as WorldObjectsClient;
    const h = harness({ client, loadBytes: vi.fn(() => bytes) });
    const oldRead = h.mounted.begin('version-one');
    await vi.waitFor(() => expect(h.objects.place).not.toHaveBeenCalled());
    await h.mounted.begin('version-two');
    resolveBytes(new ArrayBuffer(784));
    await oldRead;
    expect(h.objects.place).not.toHaveBeenCalled();
    expect(h.objects.objectIds).toEqual([]);
    expect(h.mounted.panel.root.querySelector('.object-placement-item')).toBeNull();
  });

  it('keeps the newer begin request when overlapping authority reads finish out of order', async () => {
    const resolvers = new Map<string, (answer: { assets: ReviewedAsset[]; version: AlternateVersion }) => void>();
    const client = {
      connect: vi.fn((versionId: string) => new Promise(resolve => { resolvers.set(versionId, resolve); })),
    } as unknown as WorldObjectsClient;
    const h = harness({ client });
    const older = h.mounted.begin('older');
    const newer = h.mounted.begin('newer');
    resolvers.get('newer')!({ assets: [asset()], version: version({ versionId: 'newer', objects: [] }) });
    await newer;
    resolvers.get('older')!({
      assets: [asset()], version: version({ versionId: 'older', objects: [objectRecord()] }),
    });
    await older;
    expect(h.objects.place).not.toHaveBeenCalled();
    expect(h.objects.objectIds).toEqual([]);
    expect(h.mounted.panel.root.querySelector('.object-placement-item')).toBeNull();
  });

  it('clears the admitted object view when a district refresh finds a saved-entry mismatch', async () => {
    const exact = version({ objects: [objectRecord()] });
    const client = {
      connect: vi.fn()
        .mockResolvedValueOnce({ assets: [asset()], version: exact })
        .mockRejectedValueOnce(new Error(
          'This saved world changed elsewhere. Reload to compare the latest changes before opening it.',
        )),
    } as unknown as WorldObjectsClient;
    const h = harness({ client });
    await h.mounted.begin();
    expect(h.objects.objectIds).toEqual(['object:lantern']);

    // The district-placement callback in main invokes this same no-argument begin path.
    await h.mounted.begin();

    expect(h.objects.objectIds).toEqual([]);
    expect(h.mounted.panel.root.querySelector('.object-placement-item')).toBeNull();
    expect(h.mounted.panel.root.textContent).toContain('Reload to compare the latest changes');
  });
});

describe('object and data-view selection share one supported identity', () => {
  it('reflects selection both ways, clears cross-context selection, and releases the observer', async () => {
    const h = harness({
      initial: version({ objects: [objectRecord()] }),
      representationSubjects: ['object:lantern', 'doitt_id:other'],
    });
    await h.mounted.begin();
    button(h.mounted.panel.root, 'Marker pillar').click();
    expect(h.binding.representationReport.selection).toBe('object:lantern');

    h.binding.setRepresentationSelection('doitt_id:other');
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).toBeNull();
    h.binding.setRepresentationSelection('object:lantern');
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).not.toBeNull();

    expect(h.representationObservers.size).toBe(1);
    h.mounted.dispose();
    expect(h.representationObservers.size).toBe(0);
  });

  it('clears another highlighted subject when the chosen object has no point capability', async () => {
    const h = harness({
      initial: version({ objects: [objectRecord()] }),
      representationSubjects: ['doitt_id:other'],
    });
    await h.mounted.begin();
    h.binding.setRepresentationSelection('doitt_id:other');
    button(h.mounted.panel.root, 'Marker pillar').click();
    expect(h.binding.representationReport.selection).toBeNull();
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).not.toBeNull();
  });

  it('preserves a supported selection across a confirmed move redraw', async () => {
    const h = harness({
      initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
      representationSubjects: ['object:lantern'],
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    arrow('ArrowLeft');
    button(h.mounted.panel.root, 'Save this position').click();
    button(h.mounted.confirm.root, 'Confirm').click();

    await vi.waitFor(() => expect(writes(h.authority.calls)).toEqual(['move']));
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(true));
    expect(h.binding.representationReport.selection).toBe('object:lantern');
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).not.toBeNull();
  });

  it('does not restore an object over a later data-view choice during redraw', async () => {
    let loadCount = 0;
    let resolveRedraw!: (bytes: ArrayBuffer) => void;
    const redrawBytes = new Promise<ArrayBuffer>(resolve => { resolveRedraw = resolve; });
    const h = harness({
      initial: version({ objects: [objectRecord()], edits: [edit(1, 'add_object')] }),
      representationSubjects: ['object:lantern', 'doitt_id:other'],
      loadBytes: vi.fn(() => ++loadCount === 1 ? Promise.resolve(new ArrayBuffer(784)) : redrawBytes),
    });
    await h.mounted.begin();
    h.mounted.panel.setVisible(true);
    button(h.mounted.panel.root, 'Marker pillar').click();
    arrow('ArrowLeft');
    button(h.mounted.panel.root, 'Save this position').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(loadCount).toBe(2));

    h.binding.setRepresentationSelection('doitt_id:other');
    resolveRedraw(new ArrayBuffer(784));
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(true));
    expect(h.binding.representationReport.selection).toBe('doitt_id:other');
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).toBeNull();
  });

  it('clears selection on confirmed removal, authority withdrawal and version switch', async () => {
    const initial = version({ versionId: 'version-one', objects: [objectRecord()] });
    const removed = version({
      versionId: 'version-one',
      objects: [objectRecord({ removed: true })],
      edits: [edit(1, 'remove')],
    });
    const h = harness({ initial, representationSubjects: ['object:lantern'] });
    await h.mounted.begin('version-one');
    button(h.mounted.panel.root, 'Marker pillar').click();
    h.authority.answerWith({ kind: 'recorded', version: removed });
    button(h.mounted.panel.root, 'Remove').click();
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(true));
    expect(h.binding.representationReport.selection).toBeNull();
    expect(h.mounted.panel.root.querySelector('[data-selected="yes"]')).toBeNull();

    const withdrawn = harness({ initial, representationSubjects: ['object:lantern'] });
    await withdrawn.mounted.begin('version-one');
    button(withdrawn.mounted.panel.root, 'Marker pillar').click();
    withdrawn.binding.representationReport.selection = null;
    for (const observer of withdrawn.representationObservers) observer(null, 'unavailable');
    expect(withdrawn.mounted.panel.root.querySelector('[data-selected="yes"]')).toBeNull();

    const switched = version({ versionId: 'version-two', objects: [objectRecord()] });
    const client = {
      connect: vi.fn(async (versionId: string) => ({
        assets: [asset()], version: versionId === 'version-two' ? switched : initial,
      })),
    } as unknown as WorldObjectsClient;
    const changed = harness({ client, representationSubjects: ['object:lantern'] });
    await changed.mounted.begin('version-one');
    button(changed.mounted.panel.root, 'Marker pillar').click();
    await changed.mounted.begin('version-two');
    expect(changed.binding.representationReport.selection).toBeNull();
    expect(changed.mounted.panel.root.querySelector('[data-selected="yes"]')).toBeNull();
  });
});


describe('opening the first alternate through confirmation', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  const returnedId = '6f1d2c40-0000-7000-8000-000000000020';
  const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  function emptyWorld() {
    const connect = vi.fn(async (versionId?: string) => ({
      assets: [asset()],
      version: versionId === undefined ? null : version({ versionId }),
    }));
    const placeObject = vi.fn();
    const fetcher = vi.fn<typeof fetch>();
    const client = new WorldObjectsClient({ baseUrl: 'https://exulanica.test', token: 'token', fetch: fetcher });
    client.connect = connect;
    client.place = placeObject;
    return { ...harness({ client }), connect, placeObject, fetcher };
  }

  it('stages bootstrap for an empty world and sends no POST before confirmation or after cancel', async () => {
    const h = emptyWorld();
    h.fetcher.mockResolvedValueOnce(response({ current_topology_digest: STATE }));
    await h.mounted.begin();
    expect(h.mounted.panel.root.textContent).toContain('open an alternate version first');
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    expect(h.mounted.confirm.root.textContent).toContain('Open an alternate version');
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    expect(h.fetcher.mock.calls[0]![0]).toBe('https://exulanica.test/world/styles/current');
    expect(h.fetcher.mock.calls[0]![1]?.method).toBe('GET');
    expect(h.placeObject).not.toHaveBeenCalled();
    button(h.mounted.confirm.root, 'Cancel').click();
    await new Promise((resolve) => { setTimeout(resolve, 0); });
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    expect(h.mounted.confirm.root.hidden).toBe(true);
    expect(h.connect).toHaveBeenCalledTimes(1);
    h.mounted.dispose();
  });

  it('POSTs exactly the reviewed digest on confirm and reconnects to the returned version ID', async () => {
    const h = emptyWorld();
    h.fetcher
      .mockResolvedValueOnce(response({ current_topology_digest: STATE }))
      .mockResolvedValueOnce(response({ version_id: returnedId }));
    await h.mounted.begin();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    expect(h.fetcher).toHaveBeenCalledTimes(1);
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.connect).toHaveBeenLastCalledWith(returnedId));
    const [url, request] = h.fetcher.mock.calls[1]!;
    expect(url).toBe('https://exulanica.test/world/versions/bootstrap');
    expect(request?.method).toBe('POST');
    expect(JSON.parse(String(request?.body))).toEqual({ base_topology_digest: STATE });
    expect(new Headers(request?.headers).get('authorization')).toBe('Bearer token');
    expect(new Headers(request?.headers).get('content-type')).toBe('application/json');
    expect(h.fetcher).toHaveBeenCalledTimes(2);
    expect(h.placeObject).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(h.mounted.panel.root.textContent).toContain('Alternate version opened'));
    expect(h.mounted.confirm.root.hidden).toBe(true);
    h.mounted.dispose();
  });

  it('keeps a stale 409 actionable and rereads the digest before another confirmation', async () => {
    const h = emptyWorld();
    const freshDigest = 'f'.repeat(64);
    h.fetcher
      .mockResolvedValueOnce(response({ current_topology_digest: STATE }))
      .mockResolvedValueOnce(response({ code: 'protected_topology_conflict' }, 409))
      .mockResolvedValueOnce(response({ current_topology_digest: freshDigest }))
      .mockResolvedValueOnce(response({ version_id: returnedId }));
    await h.mounted.begin();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.hidden).toBe(false));
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent).toContain('Nothing was written'));
    expect(h.mounted.confirm.root.textContent).toContain('Choose “Place before me” again');
    expect(h.connect).toHaveBeenCalledTimes(1);
    expect(h.fetcher).toHaveBeenCalledTimes(2);
    button(h.mounted.confirm.root, 'Close').click();
    await place(h);
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent).toContain('Open an alternate version'));
    expect(h.fetcher).toHaveBeenCalledTimes(3);
    expect(h.fetcher.mock.calls[2]![1]?.method).toBe('GET');
    button(h.mounted.confirm.root, 'Confirm').click();
    await vi.waitFor(() => expect(h.connect).toHaveBeenLastCalledWith(returnedId));
    expect(JSON.parse(String(h.fetcher.mock.calls[3]![1]?.body))).toEqual({ base_topology_digest: freshDigest });
    expect(h.placeObject).not.toHaveBeenCalled();
    h.mounted.dispose();
  });
});


it('releases browser pointer lock when P or the app toggle opens object controls', async () => {
  const h = harness({ noClient: true }, true);
  await h.mounted.begin();
  const canvas = document.createElement('canvas');
  const exit = vi.fn();
  const pointer = Object.getOwnPropertyDescriptor(document, 'pointerLockElement');
  const release = Object.getOwnPropertyDescriptor(document, 'exitPointerLock');
  Object.defineProperty(document, 'pointerLockElement', { configurable: true, value: canvas });
  Object.defineProperty(document, 'exitPointerLock', { configurable: true, value: exit });
  try {
    window.dispatchEvent(new KeyboardEvent('keydown', {code:'KeyP'}));
    expect(h.mounted.panel.visible()).toBe(true);
    expect(exit).toHaveBeenCalledTimes(1);
    h.mounted.toggle();
    expect(exit).toHaveBeenCalledTimes(1);
    h.mounted.toggle();
    expect(exit).toHaveBeenCalledTimes(2);
  } finally {
    if (pointer) Object.defineProperty(document, 'pointerLockElement', pointer);
    else Reflect.deleteProperty(document, 'pointerLockElement');
    if (release) Object.defineProperty(document, 'exitPointerLock', release);
    else Reflect.deleteProperty(document, 'exitPointerLock');
    h.mounted.dispose();
  }
});

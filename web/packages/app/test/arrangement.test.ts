// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { atlasVec3, islandId, localVec3, makeIsland, placement } from '@exulanica/atlas-core';

import {
  ARRANGEMENT_REFUSALS,
  SMALL_SQUARE,
  applyArrangement,
  arrangementRequestBody,
  parseArrangementApplied,
  parseArrangementPreview,
} from '../src/arrangement-api.js';
import { mountObjects, type MountedObjects, type ObjectsDependencies } from '../src/composition/objects.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { explainArrangementRefusal } from '../src/ui/arrangement-refusals.js';
import type { AlternateVersion, ReviewedAsset, WorldObjectsClient } from '../src/world-objects-api.js';

/**
 * A small square in one request, as the Create panel offers it.
 *
 * The arrangement is named by the key and version the server publishes it under, and its refusals
 * by the codes the server declares; both are read from the server's own files here, so a change
 * on either side fails rather than drifting. The flow goes through the real mount: nothing is
 * sent until the server says the square fits and the person confirms.
 */

const REGION = islandId('region:starter');
const STATE = 'a'.repeat(64);
const HALF_TURN_MICRORADIANS = 3_141_593;

const repository = `${process.cwd()}/..`;

describe('the arrangement is the server’s own', () => {
  it('names an arrangement the published catalog holds, at its version', () => {
    const catalog = JSON.parse(
      readFileSync(`${repository}/assets/catalogs/world-objects/world-arrangement.v1.json`, 'utf8'),
    ) as { catalog_version: number; entries: { key: string }[] };
    expect(catalog.entries.map((entry) => entry.key)).toContain(SMALL_SQUARE.key);
    expect(catalog.catalog_version).toBe(SMALL_SQUARE.version);
  });

  const declaredByTheServer = (): readonly string[] => {
    const source = readFileSync(`${repository}/exulanica/world/arrangements.py`, 'utf8');
    const opens = source.indexOf('ARRANGEMENT_REFUSALS: frozenset[str] = frozenset(');
    expect(opens, 'ARRANGEMENT_REFUSALS is not declared where this test reads it').toBeGreaterThan(-1);
    const closes = source.indexOf('\n)\n', opens);
    expect(closes, 'the ARRANGEMENT_REFUSALS literal does not end where this test reads it')
      .toBeGreaterThan(opens);
    return [...source.slice(opens, closes).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
  };

  it('reads a non-empty list of refusal codes out of the server source', () => {
    expect(declaredByTheServer().length).toBeGreaterThan(0);
  });

  it('knows exactly those codes, each with words that say what to do and never the code', () => {
    const declared = declaredByTheServer();
    expect([...declared].sort()).toEqual([...ARRANGEMENT_REFUSALS].sort());
    for (const code of declared) {
      const words = explainArrangementRefusal(code);
      expect(words.code).toBe(code);
      expect(words.next, code).toMatch(/^Nothing was changed/);
      expect(`${words.happened} ${words.next}`, code).not.toMatch(/[a-z]_[a-z]/);
    }
  });
});

describe('the client sends intent and reads the answer strictly', () => {
  it('sends where the person stands and faces, in whole units, and no position of any object', () => {
    const body = arrangementRequestBody({
      key: SMALL_SQUARE.key,
      version: SMALL_SQUARE.version,
      viewer: { xMm: 12.4, zMm: -3.6, yawMicroradians: 3_141_592.7 },
      originRole: 'fictional',
    });
    expect(body).toEqual({
      arrangement_key: 'small_square',
      arrangement_version: 1,
      viewer: { x_mm: 12, z_mm: -4, yaw_microradians: 3_141_593 },
      origin_role: 'fictional',
    });
  });

  it('refuses a preview whose availability and reason disagree', () => {
    const answer = previewAnswer(version(), null);
    expect(() => parseArrangementPreview({ ...answer, availability: 'blocked' })).toThrow(/disagree/);
  });

  it('reads the version out of what apply added, and keeps what it added', async () => {
    const base = version();
    const wire = appliedAnswer(base);
    expect(parseArrangementApplied(wire).addedObjectIds).toEqual(['small_square-1-1-bench']);
    const client = {
      arrangementApply: vi.fn(async (_base: AlternateVersion, _body: unknown, read: (value: unknown) => AlternateVersion) => ({
        kind: 'recorded' as const,
        version: read(wire),
      })),
      arrangementPreview: vi.fn(),
    };
    const result = await applyArrangement(client as unknown as WorldObjectsClient, base, {
      key: SMALL_SQUARE.key, version: SMALL_SQUARE.version,
      viewer: { xMm: 0, zMm: 0, yawMicroradians: 0 }, originRole: 'personal',
    });
    expect(result.kind).toBe('recorded');
    if (result.kind === 'recorded') {
      expect(result.applied.arrangement.title).toBe('A small square');
      expect(result.version.stateSha256).toBe('d'.repeat(64));
    }
  });
});

// -- through the Create panel -------------------------------------------------------------------

const asset = (over: Partial<ReviewedAsset> = {}): ReviewedAsset => Object.freeze({
  assetKey: 'cc0.bench',
  title: 'Bench',
  summary: 'A timber bench 1.8 metres long with a back, on painted metal legs.',
  mediaType: 'model/gltf-binary',
  contentSha256: 'b'.repeat(64),
  byteSize: 784,
  licenceId: 'CC0-1.0',
  licenceSha256: 'c'.repeat(64),
  availability: 'available',
  placeable: true,
  ...over,
});

function version(over: Partial<AlternateVersion> = {}): AlternateVersion {
  return Object.freeze({
    schemaVersion: 1,
    versionId: '6f1d2c40-0000-7000-8000-000000000001',
    worldId: 'world:authored:test',
    sourceSnapshotId: '6f1d2c40-0000-7000-8000-000000000002',
    parentVersionId: null,
    title: 'A world of my own',
    origin: 'authored',
    styleVersionId: null,
    stateSha256: STATE,
    editSeq: 0,
    sourceInvalidated: false,
    createdBy: '6f1d2c40-0000-7000-8000-000000000003',
    createdAt: '2026-09-24T12:00:00+00:00',
    objects: Object.freeze([]),
    elementOverrides: Object.freeze([]),
    edits: Object.freeze([]),
    ...over,
  });
}

function wireVersion(base: AlternateVersion, state: string): Record<string, unknown> {
  return {
    schema_version: 1,
    version_id: base.versionId,
    world_id: base.worldId,
    source_snapshot_id: base.sourceSnapshotId,
    parent_version_id: null,
    title: base.title,
    origin: 'authored',
    style_version_id: null,
    state_sha256: state,
    edit_seq: base.editSeq + 1,
    source_invalidated: false,
    created_by: base.createdBy,
    created_at: base.createdAt,
    objects: [],
    element_overrides: [],
    edits: [],
  };
}

function appliedAnswer(base: AlternateVersion): Record<string, unknown> {
  return {
    arrangement: { key: 'small_square', version: 1, title: 'A small square', summary: 'A tree between two benches.' },
    added_object_ids: ['small_square-1-1-bench'],
    version: wireVersion(base, 'd'.repeat(64)),
  };
}

function previewAnswer(base: AlternateVersion, blockedReason: string | null): Record<string, unknown> {
  return {
    availability: blockedReason === null ? 'ready' : 'blocked',
    blocked_reason: blockedReason,
    blocked_detail: blockedReason === null ? null : 'The server said why in its own words.',
    arrangement: { key: 'small_square', version: 1, title: 'A small square', summary: 'A tree between two benches.' },
    version: {
      authored_version_id: base.versionId, world_id: base.worldId,
      state_sha256: base.stateSha256, edit_seq: base.editSeq, source_snapshot_id: base.sourceSnapshotId,
    },
    anchor: blockedReason === null ? { x_mm: 0, z_mm: -8000, quarter_turns: 2 } : null,
    would_add: blockedReason === null
      ? ['bench', 'bench', 'planter_tree'].map((kind, index) => ({
        object_id: `small_square-1-${index + 1}-${kind}`, asset_key: `cc0.${kind}`, title: kind, document: {},
      }))
      : [],
  };
}

const mounts: MountedObjects[] = [];
afterEach(() => { for (const mounted of mounts.splice(0)) mounted.dispose(); });
beforeEach(() => { document.body.replaceChildren(); });

function harness(blockedReason: string | null = null) {
  const calls: { name: string; args: unknown[] }[] = [];
  const current = version();
  const client = {
    connect: vi.fn(async () => ({ assets: [asset(), asset({ assetKey: 'cc0.lamp-post', title: 'Lamp post', summary: 'A lamp post.' })], version: current })),
    readVersion: vi.fn(async () => current),
    arrangementPreview: vi.fn(async (base: AlternateVersion, body: unknown) => {
      calls.push({ name: 'preview', args: [base, body] });
      return previewAnswer(base, blockedReason);
    }),
    arrangementApply: vi.fn(async (base: AlternateVersion, body: unknown, read: (value: unknown) => AlternateVersion) => {
      calls.push({ name: 'apply', args: [base, body] });
      return { kind: 'recorded' as const, version: read(appliedAnswer(base)) };
    }),
  } as unknown as WorldObjectsClient;
  const objects = {
    clear: vi.fn(),
    cancelPending: vi.fn(),
    place: vi.fn(async (object: { objectId: string }) => ({ objectId: object.objectId, motion: 'none', notices: [] })),
    remove: vi.fn(),
    motionStateOf: () => null,
    setTransform: vi.fn(),
    control: vi.fn(),
    poseOf: () => null,
  };
  const binding = {
    objects,
    cameraPose: () => ({ position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, 0, -1) }),
    playerPose: () => ({ position: atlasVec3(0, 1.6, 0), forward: atlasVec3(0, 0, -1) }),
    engageFocusedAnchor: () => null,
    table: { atlasPositions: new Float32Array([0, 0, 0]) },
    representationReport: { subjects: [], selection: null },
    setRepresentationSelection: vi.fn(),
    observeRepresentationSelection: vi.fn(() => () => undefined),
    field: { setPlacementLandingPose: vi.fn() },
  };
  const state = {
    atlas: { binding },
    displayFrames: new Map(),
    placedPointMaps: [],
    trainedGeometry: [],
    pointMaps: undefined,
  } as unknown as SessionState;
  const mounted = mountObjects({
    env: { preview: false } as unknown as AppEnvironment,
    state,
    credentials: { baseUrl: 'https://exulanica.test', token: 'token' },
    scene: {
      islands: [makeIsland({
        islandId: REGION,
        createdAt: 0,
        placement: placement(atlasVec3(0, 0, 0), 0, 1),
        rung: 3,
        scaleIsMetric: false,
        footprintRadiusLocal: 20,
        viewpointLocal: localVec3(0, 0, 0),
        anchors: [],
        layoutEntities: new Set(),
      })],
    } as unknown as ObjectsDependencies['scene'],
    showTravelStatus: () => undefined,
    isWorldPrimary: () => true,
    hideWritePathConfirm: vi.fn(),
    authoredRegion: {
      regionId: 'region:starter', kind: 'flat', halfWidthMm: 12_000, halfDepthMm: 12_000, elevationMm: 0,
    },
    client,
    loadBytes: async () => new ArrayBuffer(784),
  });
  mounts.push(mounted);
  document.body.append(mounted.panel.root, mounted.confirm.root);
  return { mounted, calls };
}

const button = (root: HTMLElement, label: string): HTMLButtonElement => {
  const found = [...root.querySelectorAll('button')].find((node) => node.textContent === label);
  if (found === undefined) throw new Error(`no “${label}” control`);
  return found as HTMLButtonElement;
};

function chooseRole(h: ReturnType<typeof harness>, role: string): void {
  const select = h.mounted.panel.root.querySelector<HTMLSelectElement>('#object-placement-role')!;
  select.value = role;
  select.dispatchEvent(new Event('change'));
}

const SQUARE_CONTROL = 'Place a small square before me';

describe('the Create panel offers the catalog’s kinds and a small square', () => {
  it('lists each kind by its title and says what the chosen one is', async () => {
    const h = harness();
    await h.mounted.begin();
    const options = [...h.mounted.panel.root.querySelectorAll<HTMLOptionElement>('#object-placement-asset option')];
    expect(options.map((option) => option.textContent)).toEqual(['Bench', 'Lamp post']);
    expect(h.mounted.panel.root.querySelector('.object-placement-summary')?.textContent)
      .toBe('A timber bench 1.8 metres long with a back, on painted metal legs.');
  });

  it('asks what the objects are to the person before anything else', async () => {
    const h = harness();
    await h.mounted.begin();
    button(h.mounted.panel.root, SQUARE_CONTROL).click();
    expect(h.mounted.panel.root.textContent).toContain('Choose what these objects are to you');
    expect(h.calls).toEqual([]);
  });

  it('sends where the person stands and faces, holds Confirm until ready, then applies it', async () => {
    const h = harness();
    await h.mounted.begin();
    chooseRole(h, 'fictional');
    button(h.mounted.panel.root, SQUARE_CONTROL).click();
    const confirm = button(h.mounted.confirm.root, 'Confirm');
    expect(confirm.disabled).toBe(true);
    await vi.waitFor(() => expect(confirm.disabled).toBe(false));
    const previewed = h.calls.find((call) => call.name === 'preview')!.args[1];
    expect(previewed).toEqual({
      arrangement_key: 'small_square',
      arrangement_version: 1,
      viewer: { x_mm: 0, z_mm: 0, yaw_microradians: HALF_TURN_MICRORADIANS },
      origin_role: 'fictional',
    });
    expect(h.mounted.confirm.root.textContent).toContain('It adds 3 objects in front of you');
    expect(h.calls.filter((call) => call.name === 'apply')).toEqual([]);
    confirm.click();
    await vi.waitFor(() => expect(h.calls.filter((call) => call.name === 'apply')).toHaveLength(1));
    await vi.waitFor(() => expect(h.mounted.panel.root.textContent)
      .toContain('Placed “A small square”: one object, each its own change.'));
  });

  it('shows a refusal in words that say what to do, and sends nothing', async () => {
    const h = harness('arrangement_overlaps');
    await h.mounted.begin();
    chooseRole(h, 'personal');
    button(h.mounted.panel.root, SQUARE_CONTROL).click();
    await vi.waitFor(() => expect(h.mounted.confirm.root.textContent)
      .toContain('Something already stands where the square would go, or where people stand to use it.'));
    expect(h.mounted.confirm.root.textContent).toContain('take that object away first');
    expect(button(h.mounted.confirm.root, 'Confirm').disabled).toBe(true);
    expect(h.calls.filter((call) => call.name === 'apply')).toEqual([]);
  });
});

// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { atlasVec3 } from '@exulanica/atlas-core';
import { DEFAULT_PLACEMENT_DISTANCE_MM, generatedRegionName } from '@exulanica/atlas-react/playcanvas';
import { ApiError } from '@exulanica/graph-client';
import { mountCreatureMaker, offerWords, placementInGeneratedRegion } from '../src/composition/creature-maker.js';
import type { CreatureDraft, CreatureDraftsClient, CreatureOffer } from '../src/creature-drafts-api.js';
import type { CreatureSheet, CreatureSheetOffer } from '../src/ui/creature-sheet.js';

/*
 * Making a creature from the open world, with the creature routes and the page's edit path stood in:
 * what the sheet is told, and what is placed where, for each way a draft can go.
 */

const OFFER: CreatureOffer = { offered: true, code: null, timing: { typicalSeconds: 18, longestSeconds: 25, timeoutSeconds: 50 } };
const DRAFT = 'aabbccdd-0000-4000-8000-000000000001';
const ENTRY = { entry_id: 'entry-1', base_revision: 3, authored_state_sha256: '1'.repeat(64), authored_edit_seq: 3 };

const draft = (status: CreatureDraft['status'], more: Partial<CreatureDraft> = {}): CreatureDraft => ({
  draftId: DRAFT, status, label: null, kind: null, look: null, model: null, refusal: null, failure: null, ...more,
});

function harness(answers: CreatureDraft[], options: { asked?: CreatureDraft; running?: CreatureDraft[]; askRefused?: ApiError } = {}) {
  const said: string[] = [];
  const placed: { versionId: string; body: Readonly<Record<string, unknown>> }[] = [];
  const sheet: CreatureSheet = {
    root: document.createElement('section'),
    show: (offer: CreatureSheetOffer) => { said.push(`show:${offer.unavailable ?? 'offered'}`); },
    imagining: () => { said.push('imagining'); },
    placing: (label) => { said.push(`placing:${label}`); },
    made: (label) => { said.push(`made:${label}`); },
    notMade: (sentence) => { said.push(`not made:${sentence}`); },
    focus: () => undefined,
  };
  const client = {
    offer: async () => OFFER,
    drafts: async () => options.running ?? [],
    ask: async () => {
      if (options.askRefused !== undefined) throw options.askRefused;
      return options.asked ?? draft('queued');
    },
    draft: async () => answers.shift() ?? draft('running'),
  } as unknown as CreatureDraftsClient;
  const maker = mountCreatureMaker({
    client,
    sheet,
    version: () => ({ versionId: 'version-1', stateSha256: '1'.repeat(64), savedEntry: ENTRY }),
    placement: () => ({ region_id: 'region:starter', transform: { x_mm: 1000, y_mm: 0, z_mm: -4000, yaw_microradians: 1_000_000 } }),
    place: async (versionId, body) => { placed.push({ versionId, body }); return { status: 201 }; },
    wait: async () => undefined,
  });
  return { maker, said, placed };
}

const kept = draft('kept', { label: 'hill walker', kind: { key: 'hill_walker', version: 1, sha256: 'a'.repeat(64) } });

describe('making a creature from the open world', () => {
  it('says why a world may not ask, in words by the offer\'s code, and how long one takes', () => {
    expect(offerWords({ ...OFFER, offered: false, code: 'creatures_not_run_here' })).toEqual({
      unavailable: 'Creatures are not made on this server yet.', timing: 'Usually about 18 seconds; at most 50.',
    });
  });

  it('places a kept creature by its kind\'s digest alone, in front of the person and facing them, advancing the saved entry', async () => {
    const { maker, said, placed } = harness([draft('running'), kept]);
    await maker.make('a gentle walker of the hills');
    expect(placed).toEqual([{
      versionId: 'version-1',
      body: {
        base_state_sha256: '1'.repeat(64),
        thing_id: 'creature:aabbccdd',
        kind: { source: 'workspace', sha256: 'a'.repeat(64) },
        region_id: 'region:starter',
        // The place ahead carries the person's heading (1 rad); the creature turns half round to face them.
        pose: { x_mm: 1000, y_mm: 0, z_mm: -4000, yaw_microradians: 4_141_593 },
        origin_role: 'fictional',
        // The world's saved entry advances with the version, so it reopens with no reconciling.
        saved_entry: ENTRY,
      },
    }]);
    expect(said).toEqual(['imagining', 'placing:hill walker', 'made:hill walker']);
  });

  it('shows a refusal\'s own fixed sentence and places nothing', async () => {
    const refused = draft('refused', { refusal: { code: 'creature_movement_unbuilt', field: 'moves', detail: 'This world has no flying creatures yet.' } });
    const { maker, said, placed } = harness([refused]);
    await maker.make('a dragon that flies over the town');
    expect(placed).toEqual([]);
    expect(said.at(-1)).toBe('not made:This world has no flying creatures yet.');
  });

  it('says why an ask was refused before anything was queued, by the route\'s code', async () => {
    const { maker, said } = harness([], { askRefused: new ApiError(429, 'creature_limit_reached', 'at most one open') });
    await maker.make('another walker');
    expect(said.at(-1)).toBe('not made:A creature of yours is still being made, or you have made as many as one may this hour.');
  });

  it('places in a town made from a recipe ahead of the person, in the region drawn here', () => {
    const town = { regionId: 'region:city', arrivalMm: [0, 2_000, 0] };
    const pose = { position: atlasVec3(10, 3.6, -20), forward: atlasVec3(0, 0, -1) };
    const placed = placementInGeneratedRegion(town, generatedRegionName('region:city'), pose);
    expect(placed?.region_id).toBe('region:city');
    expect(placed?.transform).toMatchObject({ x_mm: 10_000, y_mm: 0, z_mm: -20_000 - DEFAULT_PLACEMENT_DISTANCE_MM });
    // Never where this page would not show it: another region drawn, or no town at all.
    expect(placementInGeneratedRegion(town, generatedRegionName('region:other'), pose)).toBeNull();
    expect(placementInGeneratedRegion(null, generatedRegionName('region:city'), pose)).toBeNull();
  });

  it('follows a draft still running when the sheet opens, so a reload never loses it', async () => {
    const { maker, said, placed } = harness([kept], { running: [draft('running')] });
    await maker.open();
    expect(said).toEqual(['show:offered', 'imagining', 'placing:hill walker', 'made:hill walker']);
    expect(placed).toHaveLength(1);
  });
});

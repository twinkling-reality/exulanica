// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { createLiveSociety, type LiveSocietyView } from '../src/composition/live-society.js';
import { parseSociety, parseSocietyEvents, SocietyClient, type SocietyEvent, type SocietySnapshot } from '../src/society-api.js';
import { buildWorldInhabitants } from '../src/ui/world-inhabitants.js';

/*
 * A person can send the inhabitants of their own world away and bring them back. The server
 * records each as one simulated minute; the browser proposes, reads back what the server decided,
 * says in plain words who is here, and says a refusal by the name the server gave it.
 */

const WORLD = 'world:authored:one';
const person = (i: number) => ({ id: `person-${i}`, synthetic: true, position_mm: [i, 0],
  display_name: `Person ${i}`, role: 'steward', goal: null, route: null, motion_path_mm: [[i, 0]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: 'Awaiting a supported goal.', event_ids: [] } });
const row = (tick: number, away: boolean) => ({
  society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'place', population_size: 8,
  current_tick: tick, state_sha256: (away ? 'c' : 'a').repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick, input_seq: 1,
    input_sha256: 'b'.repeat(64), inhabitants: away ? [] : Array.from({ length: 8 }, (_, i) => person(i)),
    ...(tick > 0 ? { presence: { status: away ? 'away' : 'here', since_tick: tick, request_id: 'r', request_sha256: 'd'.repeat(64) } } : {}) },
});
const here = (tick = 0): SocietySnapshot => parseSociety(row(tick, false));
const away = (tick = 1): SocietySnapshot => parseSociety(row(tick, true));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });

describe('the society a person sent away', () => {
  it('reads with nobody in it, says since when, and keeps the people it had', () => {
    const gone = away(4);
    expect(gone.state.inhabitants).toHaveLength(0);
    expect(gone.populationSize).toBe(8);
    expect(gone.presence).toEqual({ status: 'away', sinceTick: 4 });
    expect(here().presence).toEqual({ status: 'here', sinceTick: null });
    // Their departures are still their events, though the state names nobody now.
    const events = parseSocietyEvents({ events: [{ event_id: 'e', subject_id: 'person-3', tick: 4,
      event_kind: 'departed', document_sha256: 'e'.repeat(64), document: { synthetic: true,
        summary: 'Person 3 (simulated) left: the world\'s owner sent everyone away.', profile: 'exulanica-society/v2',
        branch_id: 'branch', subject_id: 'person-3', tick: 4, order: 3, input_seq: 1, input_sha256: 'b'.repeat(64),
        reason: 'sent_away', outcome: 'departed' } }] }, gone);
    expect(events.map((event) => event.event_kind)).toEqual(['departed']);
    // A state that says it is away and still holds people is not what the server writes.
    expect(() => parseSociety({ ...row(4, true), state: { ...row(4, true).state, inhabitants: [person(0)] } }))
      .toThrow('Invalid society response');
  });

  it('asks in the named world, against the state the person saw', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(json(row(1, true)));
    const client = new SocietyClient({ baseUrl: 'https://api.test', token: 'test', fetch, worldId: WORLD });
    const result = await client.changePresence(here(0), 'away', 'key');
    expect(fetch.mock.calls[0]![0]).toBe(
      `https://api.test/world/versions/branch/society/presence?world_id=${encodeURIComponent(WORLD)}`);
    expect(JSON.parse(String(fetch.mock.calls[0]![1]!.body))).toEqual({
      idempotency_key: 'key', presence: 'away', base_tick: 0, base_state_sha256: 'a'.repeat(64),
    });
    expect(result.presence.status).toBe('away');
  });
});

function live(read: () => Promise<SocietySnapshot>) {
  const views: LiveSocietyView[] = [];
  const client = {
    connect: vi.fn(async () => here()),
    read: vi.fn(read),
    advance: vi.fn(async () => here(1)),
    events: vi.fn(async (): Promise<readonly SocietyEvent[]> => []),
    changePresence: vi.fn(async (_snapshot: SocietySnapshot, wanted: 'away' | 'here') => (wanted === 'away' ? away() : here(2))),
  };
  const society = createLiveSociety({
    preview: false, credentials: { baseUrl: 'https://example.test', token: 'test' }, worldId: WORLD,
    versionId: 'branch', placeId: null, regionId: 'region:starter', profile: 'exulanica-society/v2',
    createOnConnect: false, places: true, onChange: (view) => views.push(view), client,
  });
  return { society, client, views };
}

describe('sending everyone away from the live world', () => {
  it('asks, then reads back what the server decided', async () => {
    let current = here();
    const { society, client } = live(async () => current);
    await society.connect();
    current = away();
    await society.sendAway();
    expect(client.changePresence).toHaveBeenCalledWith(here(), 'away');
    expect(society.view.snapshot?.presence.status).toBe('away');
    expect(society.view.message).toMatch(/still in this world's history/);
    current = here(2);
    await society.bringBack();
    expect(client.changePresence).toHaveBeenLastCalledWith(away(), 'here');
    expect(society.view.snapshot?.state.inhabitants).toHaveLength(8);
  });

  it('keeps a refusal by its name and changes nothing', async () => {
    const { society, client } = live(async () => away());
    await society.connect();
    client.changePresence.mockRejectedValueOnce(new ApiError(409, 'nobody_to_send_away', 'nobody_to_send_away'));
    await society.sendAway();
    expect(society.view.refusal).toEqual({ status: 409, code: 'nobody_to_send_away', detail: 'nobody_to_send_away' });
    expect(society.view.snapshot?.presence.status).toBe('away');
  });
});

describe('the panel says who is here in plain words', () => {
  const view = (snapshot: SocietySnapshot, refusal: LiveSocietyView['refusal'] = null) => ({
    status: 'ready', busy: false, snapshot, message: '', refusal,
  });

  it('offers to send everyone away while they are here, and to bring them back while they are not', () => {
    const onSendAway = vi.fn(), onBringBack = vi.fn();
    const panel = buildWorldInhabitants({ onBringIn: vi.fn(), onAdvance: vi.fn(), onSendAway, onBringBack });
    panel.render({ society: view(here(3)), objects: [], walked: 2, advanceBlocked: null });
    expect(panel.sendAway.hidden).toBe(false);
    expect(panel.sendAway.textContent).toBe('Send everyone away');
    expect(panel.bringBack.hidden).toBe(true);
    panel.sendAway.click();
    expect(onSendAway).toHaveBeenCalledTimes(1);

    panel.render({ society: view(away(4)), objects: [], walked: 0, advanceBlocked: null });
    expect(panel.root.querySelector('.world-inhabitants-summary')?.textContent)
      .toBe('Nobody lives here now: you sent everyone away at simulated minute 4.');
    expect(panel.sendAway.hidden).toBe(true);
    expect(panel.advance.hidden).toBe(true);
    expect(panel.bringBack.hidden).toBe(false);
    expect(panel.bringBack.textContent).toBe('Bring them back');
    expect(panel.root.textContent).toMatch(/a new arrival/);
    panel.bringBack.click();
    expect(onBringBack).toHaveBeenCalledTimes(1);
  });

  it('offers nothing to send away when the engine table says its people stay', () => {
    const panel = buildWorldInhabitants({ onBringIn: vi.fn(), onAdvance: vi.fn(), onSendAway: vi.fn(), onBringBack: vi.fn() });
    const social = { ...here(3), state: { ...here(3).state, profile: 'exulanica-society/v3' } } as SocietySnapshot;
    panel.render({ society: view(social), objects: [], walked: 0, advanceBlocked: null });
    expect(panel.advance.hidden).toBe(false);
    expect(panel.sendAway.hidden).toBe(true);
    expect(panel.bringBack.hidden).toBe(true);
    const shown = [...panel.root.querySelectorAll('p')].filter((p) => !p.hidden).map((p) => p.textContent).join(' ');
    expect(shown).not.toMatch(/Sending everyone away/);
  });

  it('says a refusal in words, never by its code', () => {
    const panel = buildWorldInhabitants({ onBringIn: vi.fn(), onAdvance: vi.fn(), onSendAway: vi.fn(), onBringBack: vi.fn() });
    panel.render({ society: view(away(4), { status: 409, code: 'nobody_to_send_away', detail: 'nobody_to_send_away' }),
      objects: [], walked: 0, advanceBlocked: null });
    const refusal = panel.root.querySelector('.world-inhabitants-refusal') as HTMLElement;
    expect(refusal.hidden).toBe(false);
    expect(refusal.textContent).toBe('Nobody is here to send away.');
  });
});

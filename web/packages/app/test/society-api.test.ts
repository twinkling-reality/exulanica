import { describe, expect, it } from 'vitest';
import { parseSociety } from '../src/society-api.js';

describe('society browser contract', () => {
  it('accepts at least one hundred explicitly synthetic inhabitants', () => {
    const inhabitants = Array.from({ length: 128 }, (_, ordinal) => ({
      id: `synthetic-${ordinal}`,
      synthetic: true,
      position_mm: [ordinal, -ordinal],
    }));
    const snapshot = parseSociety({
      society_id: 'society',
      version_id: 'version',
      place_id: 'place',
      population_size: 128,
      current_tick: 42,
      state_sha256: 'a'.repeat(64),
      state: { tick: 42, inhabitants },
    });
    expect(snapshot.populationSize).toBe(128);
    expect(snapshot.state.inhabitants).toHaveLength(128);
  });

  it('rejects an undersized crowd', () => {
    expect(() => parseSociety({
      society_id: 'society',
      version_id: 'version',
      place_id: 'place',
      population_size: 99,
      current_tick: 0,
      state_sha256: 'a'.repeat(64),
      state: { tick: 0, inhabitants: [] },
    })).toThrow(/Invalid society/);
  });
});

describe('society identity and malformed data rejection', () => {
  const valid = () => ({society_id:'society',version_id:'branch',place_id:'place',population_size:100,current_tick:0,state_sha256:'a'.repeat(64),state:{tick:0,inhabitants:Array.from({length:100},(_,i)=>({id:`person-${i}`,synthetic:true,position_mm:[i,0]}))}});
  it('rejects duplicate subjects, non-synthetic subjects and mismatched population/tick', () => {
    const duplicate=valid(); duplicate.state.inhabitants[1]!.id=duplicate.state.inhabitants[0]!.id;
    expect(()=>parseSociety(duplicate)).toThrow();
    const real=valid(); real.state.inhabitants[0]!.synthetic=false;
    expect(()=>parseSociety(real)).toThrow();
    expect(()=>parseSociety({...valid(),population_size:128})).toThrow();
    expect(()=>parseSociety({...valid(),current_tick:1})).toThrow();
  });
  it('rejects malformed positions and unknown profile', () => {
    const invalid=valid(); invalid.state.inhabitants[0]!.position_mm=[NaN,0];
    expect(()=>parseSociety(invalid)).toThrow();
    const row=valid(); expect(()=>parseSociety({...row,state:{...row.state,profile:'unknown'}})).toThrow();
  });
});

import { vi } from 'vitest';
import { SocietyClient, parseSocietyEvents } from '../src/society-api.js';

const responseRow = () => ({society_id:'society',version_id:'branch',place_id:'place',population_size:100,current_tick:4,state_sha256:'a'.repeat(64),state:{tick:4,inhabitants:Array.from({length:100},(_,i)=>({id:`person-${i}`,synthetic:true,position_mm:[i,0]}))}});
const persistedEvent = () => ({event_id:'event',subject_id:'person-0',tick:4,event_kind:'departed',document_sha256:'b'.repeat(64),document:{synthetic:true,summary:'Departed on the simulated schedule.'}});
const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers:{'content-type':'application/json'}});

describe('society authenticated transport', () => {
  it('reads an existing branch without creating or advancing it', async () => {
    const fetch = vi.fn(async () => jsonResponse(responseRow())); const client = new SocietyClient({baseUrl:'https://api.test/',token:'scoped-test-token',fetch});
    await client.connect('branch','place','region');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual(['https://api.test/world/versions/branch/society',expect.objectContaining({method:'GET',headers:{authorization:'Bearer scoped-test-token'}})]);
  });
  it('explicitly creates v2 only after missing society and sends no authoritative geometry', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(jsonResponse({code:'unknown_society',detail:'unavailable'},404)).mockResolvedValueOnce(jsonResponse(responseRow()));
    const client = new SocietyClient({baseUrl:'https://api.test',token:'test',fetch}); await client.connect('branch','place','region');
    const init = fetch.mock.calls[1]![1]!;
    expect(JSON.parse(String(init.body))).toEqual({place_id:'place',region_id:'region',seed:'7a'.repeat(32),profile:'exulanica-society/v2'});
  });
  it.each([401,403,409,424,500])('does not create on read error %s', async status => {
    const fetch = vi.fn(async () => jsonResponse({code:'unavailable',detail:'unavailable'},status));
    const client = new SocietyClient({baseUrl:'https://api.test',token:'test',fetch});
    await expect(client.connect('branch','place','region')).rejects.toThrow(); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('uses only canonical tick and digest for advance and limits event reads', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(jsonResponse(responseRow())).mockResolvedValueOnce(jsonResponse({events:[persistedEvent()]}));
    const client = new SocietyClient({baseUrl:'https://api.test',token:'test',fetch}); const snapshot = parseSociety(responseRow());
    await client.advance(snapshot); await client.events(snapshot);
    expect(JSON.parse(String(fetch.mock.calls[0]![1]!.body))).toEqual({base_tick:4,base_state_sha256:'a'.repeat(64)});
    expect(fetch.mock.calls[1]![0]).toBe('https://api.test/world/versions/branch/society/events?limit=256');
  });
  it('rejects responses from another branch for read, create and advance', async () => {
    for (const action of ['read','connect','advance']) {
      const fetch = vi.fn<typeof globalThis.fetch>();
      if (action === 'connect') fetch.mockResolvedValueOnce(jsonResponse({code:'unknown_society',detail:'missing'},404));
      fetch.mockResolvedValueOnce(jsonResponse({...responseRow(),version_id:'other'}));
      const client = new SocietyClient({baseUrl:'https://api.test',token:'test',fetch});
      await expect(action === 'advance' ? client.advance(parseSociety(responseRow())) : action === 'connect' ? client.connect('branch','place','region') : client.read('branch')).rejects.toThrow(/another branch/);
    }
  });
});

describe('persisted event identity and window', () => {
  it('rejects forged subjects, duplicate IDs, non-synthetic events and malformed envelopes', () => {
    const snapshot = parseSociety(responseRow());
    for (const events of [[{...persistedEvent(),subject_id:'other'}], [persistedEvent(),persistedEvent()], [{...persistedEvent(),document:{synthetic:false,summary:'bad'}}], [{...persistedEvent(),document_sha256:'bad'}]]) {
      expect(() => parseSocietyEvents({events},snapshot)).toThrow();
    }
    expect(() => parseSocietyEvents({events:null},snapshot)).toThrow();
    expect(() => parseSocietyEvents({events:Array(257).fill(persistedEvent())},snapshot)).toThrow();
  });
  it('excludes newer events read concurrently with a held snapshot', () => {
    expect(parseSocietyEvents({events:[{...persistedEvent(),tick:5}]},parseSociety(responseRow()))).toEqual([]);
  });
  it('validates explicit v2 branch, profile, tick, subject and input bindings', () => {
    // The snapshot parser is tested separately; this isolates the event boundary.
    const snapshot = {...parseSociety(responseRow()),state:{...parseSociety(responseRow()).state,profile:'exulanica-society/v2' as const}};
    const document = {...persistedEvent().document,profile:'exulanica-society/v2',branch_id:'branch',subject_id:'person-0',tick:4,order:0,input_seq:1,input_sha256:'c'.repeat(64),reason:'visit_place',outcome:'goal_selected'};
    expect(parseSocietyEvents({events:[{...persistedEvent(),document}]},snapshot)).toHaveLength(1);
    for (const changed of [{branch_id:'other'}, {profile:'exulanica-society/v3'}, {subject_id:'person-1'}, {tick:3}, {input_seq:0}, {input_sha256:'bad'}]) {
      expect(() => parseSocietyEvents({events:[{...persistedEvent(),document:{...document,...changed}}]},snapshot)).toThrow(/binding/);
    }
  });
});

describe('living society snapshots', () => {
  const person = (i: number, extra: Record<string, unknown> = {}) => ({
    id: `person-${i}`, ordinal: i, synthetic: true, role: i ? {key: 'baker', label: 'baker', destination_id: 'premises:b:0'} : null,
    role_reason: i ? 'works_at_premises' : 'place_publishes_no_premises', walk_speed_mm_per_tick: 70000,
    needs: {leisure: 300}, position_mm: [4000, i * 4000], motion_path_mm: [[0, i * 4000], [4000, i * 4000]],
    location: {node_id: `n${i}`, edge: null, spot_id: `n${i}`, destination_id: null, indoors: i === 1},
    goal: {activity: 'stroll', destination_id: null, spot_id: `n${i}`, node_id: `n${i}`, need: 'leisure', shift_day: null, reason: 'most_pressing_need', because: 'leisure at 300 of 1000'},
    route: null, action: {kind: 'stroll', status: 'active', destination_id: null, remaining_ticks: 2, reason: 'arrived'},
    explanation: {summary: 'A person (simulated): action started; arrived.', event_ids: ['e']}, memory: ['e'], ...extra,
  });
  const row = (people: unknown[]) => ({
    society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'place', population_size: 2,
    current_tick: 3, state_sha256: 'a'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
    state: {profile: 'exulanica-society/v4', society_id: 'society', branch_id: 'branch', tick: 3, input_seq: 1,
      input_sha256: 'b'.repeat(64), tick_seconds: 60,
      routine: {catalog_versions: {
        'society-activity': 1, 'society-capacity': 1, 'society-need': 1,
        'society-policy': 1, 'society-use-class': 1,
      }, sha256: '5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931'},
      clock: {start_minute_of_day: 480, minute_of_day: 483, day: 0},
      population: {size: 2}, inhabitants: people},
  });
  it('presents roles, routine, input and exact simulated clock bindings from canonical fields', () => {
    const snapshot = parseSociety(row([person(0), person(1)]));
    expect(snapshot.populationSize).toBe(2);
    expect(snapshot.state).toMatchObject({
      input_seq: 1,
      input_sha256: 'b'.repeat(64),
      tick: 3,
      tick_seconds: 60,
      start_minute_of_day: 480,
      minute_of_day: 483,
      day: 0,
      routine: {catalog_versions: {
        'society-activity': 1, 'society-capacity': 1, 'society-need': 1,
        'society-policy': 1, 'society-use-class': 1,
      }, sha256: '5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931'},
    });
    expect(snapshot.state.inhabitants.map((p) => [p.role, p.indoors, p.walk_speed_mm_per_tick])).toEqual([
      [null, false, 70000], ['baker', true, 70000],
    ]);
    expect(snapshot.state.inhabitants[0]!.goal).toEqual({activity: 'stroll', destination_id: null, because: 'leisure at 300 of 1000'});
  });
  it('shows a canonical day rollover without reinterpreting another timestamp', () => {
    const document = row([person(0), person(1)]);
    document.current_tick = 2;
    document.state.tick = 2;
    document.state.clock = {start_minute_of_day: 1439, minute_of_day: 1, day: 1};
    expect(parseSociety(document).state).toMatchObject({
      tick: 2, start_minute_of_day: 1439, minute_of_day: 1, day: 1,
    });
  });
  it('refuses malformed or inconsistent authoritative routine and clock fields', () => {
    const altered = (change: (document: ReturnType<typeof row>) => void) => {
      const document = row([person(0), person(1)]);
      change(document);
      expect(() => parseSociety(document)).toThrow(/living society/);
    };
    altered(document => { document.state.tick_seconds = 30; });
    altered(document => { document.state.routine.sha256 = 'bad'; });
    altered(document => { document.state.routine.catalog_versions['society-activity'] = 0; });
    altered(document => { document.state.clock.minute_of_day = 484; });
    altered(document => { document.state.clock.day = 1; });
    altered(document => { document.state.clock.start_minute_of_day = 1_440; });
  });
  it('refuses names, truncation, detached motion and foreign branches', () => {
    expect(() => parseSociety(row([person(0, {display_name: 'Emi Fox'}), person(1)]))).toThrow(/living society/);
    expect(() => parseSociety(row([person(0)]))).toThrow(/living society/);
    expect(() => parseSociety(row([person(0, {position_mm: [8000, 0]}), person(1)]))).toThrow(/endpoint/);
    // A place that states heights has nowhere to put them here yet, and says so rather than
    // letting the number vanish between the response and the renderer.
    expect(() => parseSociety(row([person(0, {support_z_mm: 146}), person(1)]))).toThrow(
      /carries no support height/,
    );
    expect(() => parseSociety(row([person(0, {support_z_mm: 0}), person(1)]))).toThrow(
      /carries no support height/,
    );
    expect(() => parseSociety({...row([person(0), person(1)]), version_id: 'other'})).toThrow(/living society/);
  });
});

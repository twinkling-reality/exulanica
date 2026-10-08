import { describe, expect, it } from 'vitest';
import { parseSocietyControl } from '../src/society-control-api.js';

const version = 'version';
const control = {
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: version,
  persisted: true, revision: 2, mode: 'playing', speed: 2,
  base_tick_interval_ms: 8000, tick_interval_ms: 4000,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 1, current_tick: 4, state_sha256: 'a'.repeat(64),
  play_ineligible_reason: null, play_eligible: true,
};

describe('whether this host plays the world', () => {
  it('reads the host statement exactly, with a reason only when it does not play', () => {
    expect(parseSocietyControl({ ...control, host_playback: { running: true, interval_ms: 4000, reason: null } }, version)
      .hostPlayback).toEqual({ running: true, intervalMs: 4000, reason: null, code: null });
    expect(parseSocietyControl({
      ...control, host_playback: { running: false, interval_ms: 4000, reason: 'This host does not play worlds on its own.' },
    }, version).hostPlayback).toEqual({ running: false, intervalMs: 4000, reason: 'This host does not play worlds on its own.', code: null });
  });

  it('reads why it does not play by code, so the page can say it in its own words', () => {
    const waiting = { running: false, interval_ms: 4000, reason: 'Many visitors\' worlds are playing.' };
    expect(parseSocietyControl({ ...control, host_playback: waiting, host_playback_code: 'guest_towns_full' }, version)
      .hostPlayback?.code).toBe('guest_towns_full');
    expect(parseSocietyControl({ ...control, host_playback: waiting, host_playback_code: null }, version).hostPlayback?.code).toBeNull();
    expect(() => parseSocietyControl({ ...control, host_playback: waiting, host_playback_code: 7 }, version))
      .toThrow('Invalid society playback response');
  });

  it('says nothing about a host that states nothing, rather than guessing', () => {
    expect(parseSocietyControl(control, version).hostPlayback).toBeNull();
  });

  it('refuses a statement that contradicts itself or carries anything else', () => {
    const refused = [
      { running: true, interval_ms: 4000, reason: 'but it plays' },
      { running: false, interval_ms: 4000, reason: null },
      { running: false, interval_ms: 4000, reason: '' },
      { running: 'yes', interval_ms: 4000, reason: null },
      { running: true, interval_ms: 0, reason: null },
      { running: true, interval_ms: 4000.5, reason: null },
      { running: true, interval_ms: 4000 },
      { running: true, interval_ms: 4000, reason: null, worker: 'w1' },
      null,
      [],
    ];
    for (const host of refused) {
      expect(() => parseSocietyControl({ ...control, host_playback: host }, version), JSON.stringify(host))
        .toThrow('Invalid society playback response');
    }
  });
});

describe('whether open models are asked for the people here', () => {
  const host_playback = { running: true, interval_ms: 4000, reason: null };
  it('reads a code with its sentence, and nothing from a server that says nothing', () => {
    const spent = parseSocietyControl({ ...control, host_playback, model_minds_code: 'spending_cap_reached', model_minds_reason: 'Used up.' }, version);
    expect(spent.modelMinds).toEqual({ code: 'spending_cap_reached', reason: 'Used up.' });
    // The world keeps playing: it is not a playback refusal.
    expect(spent.hostPlayback?.running).toBe(true);
    expect(parseSocietyControl({ ...control, host_playback, model_minds_code: null, model_minds_reason: null }, version).modelMinds).toBeNull();
    expect(parseSocietyControl({ ...control, host_playback }, version).modelMinds).toBeNull();
  });

  it('refuses a code without its sentence, or a sentence without its code', () => {
    for (const minds of [
      { model_minds_code: 'spending_cap_reached', model_minds_reason: null },
      { model_minds_code: null, model_minds_reason: 'Used up.' },
      { model_minds_code: '', model_minds_reason: 'Used up.' },
    ]) {
      expect(() => parseSocietyControl({ ...control, host_playback, ...minds }, version), JSON.stringify(minds))
        .toThrow('Invalid society playback response');
    }
  });
});

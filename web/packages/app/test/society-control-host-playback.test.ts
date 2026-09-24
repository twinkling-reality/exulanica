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
      .hostPlayback).toEqual({ running: true, intervalMs: 4000, reason: null });
    expect(parseSocietyControl({
      ...control, host_playback: { running: false, interval_ms: 4000, reason: 'This host does not play worlds on its own.' },
    }, version).hostPlayback).toEqual({ running: false, intervalMs: 4000, reason: 'This host does not play worlds on its own.' });
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

import { describe, expect, it } from 'vitest';
import {
  parseLivingSocietyRecording,
  recordingState,
} from '../src/society-preview-presentation.js';

const districtDigest = 'd'.repeat(64);
const inhabitant = (minute: number) => ({
  position_mm: [minute, 0],
  motion_path_mm: [[minute, 0]],
  indoors: false,
  action: { kind: 'idle', status: 'active', destination_id: null, reason: 'awaiting_choice' },
  goal: null,
  needs: { leisure: 300 },
  explanation_event_ids: [],
});
const recording = () => ({
  profile: 'exulanica.living-society-recording/v1',
  engine_profile: 'exulanica-society/v4',
  district_document_sha256: districtDigest,
  status: 'Recorded preview.',
  society_id: 'society',
  branch_id: 'branch',
  district_id: 'district',
  input_sha256: 'b'.repeat(64),
  routine: {
    catalog_versions: {
      'society-activity': 1, 'society-capacity': 1, 'society-need': 1,
      'society-policy': 1, 'society-use-class': 1,
    },
    sha256: '5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931',
  },
  population: {
    size: 1, limit: 1, capacity: 2, rule: 'bounded', reason: 'fixture', supported_needs: ['leisure'],
  },
  place: { destinations: [], unsupported: [] },
  environment: {
    weather: { availability: 'unavailable', reason: 'No weather source.' },
  },
  roster: [{
    id: 'person-0', synthetic: true, role: null,
    role_reason: 'place_publishes_no_premises', walk_speed_mm_per_tick: 70_000,
  }],
  frames: [
    { tick: 0, minute_of_day: 1_439, day: 0, state_sha256: '1'.repeat(64), inhabitants: [inhabitant(0)] },
    { tick: 1, minute_of_day: 0, day: 1, state_sha256: '2'.repeat(64), inhabitants: [inhabitant(1)] },
  ],
  events: [],
});

describe('living society recorded-preview projection', () => {
  it('preserves recorded routine, input and day while leaving unstated tick duration unavailable', () => {
    const parsed = parseLivingSocietyRecording(recording(), districtDigest);
    const state = recordingState(parsed, 1);
    expect(state).toMatchObject({
      profile: 'exulanica-society/v4',
      society_id: 'society',
      branch_id: 'branch',
      input_sha256: 'b'.repeat(64),
      routine: {
        catalog_versions: {
          'society-activity': 1, 'society-capacity': 1, 'society-need': 1,
          'society-policy': 1, 'society-use-class': 1,
        },
        sha256: '5ed1a63d6589763693bec365d41f46b00de3a6ee8b9c25fa0cd35e2381f10931',
      },
      tick: 1,
      minute_of_day: 0,
      day: 1,
    });
    expect(state.input_seq).toBeUndefined();
    expect(state.tick_seconds).toBeUndefined();
    expect(state.start_minute_of_day).toBeUndefined();
  });

  it('refuses malformed bindings and a discontinuous recorded clock', () => {
    const changed = (change: (document: ReturnType<typeof recording>) => void) => {
      const document = recording();
      change(document);
      expect(() => parseLivingSocietyRecording(document, districtDigest)).toThrow(/recording is invalid/);
    };
    changed(document => { document.routine.sha256 = 'bad'; });
    changed(document => { document.routine.catalog_versions['society-activity'] = 0; });
    changed(document => { document.input_sha256 = 'bad'; });
    changed(document => { document.frames[1]!.day = 0; });
    changed(document => { document.frames[1]!.minute_of_day = 1_440; });
  });
});

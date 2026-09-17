import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';

/**
 * The development preview's recording of the v4 living society, produced by the real engine
 * (`scripts/record_living_society.py`). Only the labelled preview reads this shape; it is not an
 * API and never persistence evidence. Frames are presented exactly as recorded.
 */
export interface LivingSocietyRecording {
  readonly status: string;
  readonly societyId: string;
  readonly branchId: string;
  readonly districtId: string;
  readonly population: {
    readonly size: number;
    readonly limit: number;
    readonly capacity: number;
    readonly rule: string;
    readonly reason: string;
    readonly supportedNeeds: readonly string[];
  };
  readonly unsupported: readonly string[];
  readonly environment: Readonly<Record<string, { readonly availability: string; readonly reason: string }>>;
  readonly destinations: ReadonlyMap<string, { readonly affordances: readonly string[]; readonly capacity: number }>;
  readonly roster: readonly RosterEntry[];
  readonly frames: readonly RecordedFrame[];
  readonly events: ReadonlyMap<string, RecordedEvent>;
  readonly eventsBySubject: ReadonlyMap<string, readonly RecordedEvent[]>;
}

export interface RosterEntry {
  readonly id: string;
  readonly role: string | null;
  readonly roleReason: string;
  readonly walkSpeedMmPerTick: number;
}

export interface RecordedFrame {
  readonly tick: number;
  readonly minuteOfDay: number;
  readonly stateSha256: string;
  readonly inhabitants: readonly RecordedInhabitant[];
}

export interface RecordedInhabitant {
  readonly position_mm: readonly [number, number];
  readonly motion_path_mm: readonly (readonly [number, number])[];
  readonly indoors: boolean;
  readonly action: { readonly kind: string; readonly status: 'active' | 'completed' | 'blocked'; readonly destination_id: string | null; readonly reason: string };
  readonly goal: null | { readonly activity: string; readonly destination_id: string | null; readonly because: string };
  readonly needs: Readonly<Record<string, number>>;
  readonly explanation_event_ids: readonly string[];
}

export interface RecordedEvent {
  readonly eventId: string;
  readonly subjectId: string;
  readonly tick: number;
  readonly kind: string;
  readonly summary: string;
}

const PROFILE = 'exulanica.living-society-recording/v1';
const fail = (message: string): never => { throw new Error(`Living society recording is invalid: ${message}`); };
const object = (value: unknown, where: string): Readonly<Record<string, unknown>> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>> : fail(where);
const text = (value: unknown, where: string): string =>
  typeof value === 'string' && value.length > 0 ? value : fail(where);
const whole = (value: unknown, where: string): number =>
  Number.isSafeInteger(value) ? value as number : fail(where);
const point = (value: unknown, where: string): readonly [number, number] =>
  Array.isArray(value) && value.length === 2 && value.every(Number.isSafeInteger)
    ? value as unknown as readonly [number, number] : fail(where);

export function parseLivingSocietyRecording(value: unknown, districtDigest: string): LivingSocietyRecording {
  const row = object(value, 'document');
  if (row['profile'] !== PROFILE) fail('profile');
  if (row['engine_profile'] !== 'exulanica-society/v4') fail('engine profile');
  if (row['district_document_sha256'] !== districtDigest) fail('it was recorded over another district');
  const population = object(row['population'], 'population');
  const place = object(row['place'], 'place');
  const roster = (Array.isArray(row['roster']) ? row['roster'] : fail('roster')).map((raw, index) => {
    const entry = object(raw, `roster ${index}`);
    if (entry['synthetic'] !== true) fail('every inhabitant is synthetic');
    return Object.freeze({
      id: text(entry['id'], `roster ${index} id`),
      role: entry['role'] === null ? null : text(entry['role'], `roster ${index} role`),
      roleReason: text(entry['role_reason'], `roster ${index} role reason`),
      walkSpeedMmPerTick: whole(entry['walk_speed_mm_per_tick'], `roster ${index} speed`),
    });
  });
  if (new Set(roster.map((entry) => entry.id)).size !== roster.length) fail('duplicate inhabitant');
  if (roster.length !== whole(population['size'], 'population size')) fail('population size');
  const frames = (Array.isArray(row['frames']) ? row['frames'] : fail('frames')).map((raw, index) => {
    const frame = object(raw, `frame ${index}`);
    if (frame['tick'] !== index) fail('frames are not contiguous from tick 0');
    const people = Array.isArray(frame['inhabitants']) ? frame['inhabitants'] : fail(`frame ${index} inhabitants`);
    if (people.length !== roster.length) fail(`frame ${index} truncates the population`);
    return Object.freeze({
      tick: index,
      minuteOfDay: whole(frame['minute_of_day'], `frame ${index} minute`),
      stateSha256: /^[0-9a-f]{64}$/.test(String(frame['state_sha256'])) ? String(frame['state_sha256']) : fail(`frame ${index} digest`),
      inhabitants: people.map((person, n) => {
        const held = object(person, `frame ${index} inhabitant ${n}`);
        const path = (Array.isArray(held['motion_path_mm']) ? held['motion_path_mm'] : fail('motion path'))
          .map((p) => point(p, 'motion path point'));
        const end = point(held['position_mm'], 'position');
        const last = path.at(-1) ?? fail('empty motion path');
        if (last[0] !== end[0] || last[1] !== end[1]) fail('motion path does not end at the position');
        const action = object(held['action'], 'action');
        if (!['active', 'completed', 'blocked'].includes(String(action['status']))) fail('action status');
        text(action['kind'], 'action kind');
        if (held['goal'] !== null) text(object(held['goal'], 'goal')['activity'], 'goal activity');
        if (typeof held['indoors'] !== 'boolean') fail('indoors');
        return held as unknown as RecordedInhabitant;
      }),
    });
  });
  if (frames.length === 0) fail('no frames');
  const events = new Map<string, RecordedEvent>();
  const bySubject = new Map<string, RecordedEvent[]>();
  const ids = new Set(roster.map((entry) => entry.id));
  for (const raw of Array.isArray(row['events']) ? row['events'] : fail('events')) {
    const held = object(raw, 'event');
    const event = Object.freeze({
      eventId: text(held['event_id'], 'event id'),
      subjectId: text(held['subject_id'], 'event subject'),
      tick: whole(held['tick'], 'event tick'),
      kind: text(held['kind'], 'event kind'),
      summary: text(held['summary'], 'event summary'),
    });
    if (!ids.has(event.subjectId) || events.has(event.eventId)) fail('event binding');
    events.set(event.eventId, event);
    const list = bySubject.get(event.subjectId) ?? [];
    list.push(event);
    bySubject.set(event.subjectId, list);
  }
  const destinations = new Map<string, { affordances: readonly string[]; capacity: number }>();
  for (const raw of Array.isArray(place['destinations']) ? place['destinations'] : fail('destinations')) {
    const held = object(raw, 'destination');
    destinations.set(text(held['destination_id'], 'destination id'), {
      affordances: Array.isArray(held['affordances']) ? held['affordances'].map(String) : [],
      capacity: whole(held['visitor_capacity'], 'destination capacity'),
    });
  }
  const environment: Record<string, { availability: string; reason: string }> = {};
  for (const [key, raw] of Object.entries(object(row['environment'], 'environment'))) {
    const held = object(raw, key);
    environment[key] = { availability: text(held['availability'], key), reason: text(held['reason'], key) };
  }
  return Object.freeze({
    status: text(row['status'], 'status'),
    societyId: text(row['society_id'], 'society id'),
    branchId: text(row['branch_id'], 'branch id'),
    districtId: text(row['district_id'], 'district id'),
    population: Object.freeze({
      size: roster.length,
      limit: whole(population['limit'], 'population limit'),
      capacity: whole(population['capacity'], 'population capacity'),
      rule: text(population['rule'], 'population rule'),
      reason: text(population['reason'], 'population reason'),
      supportedNeeds: Array.isArray(population['supported_needs']) ? population['supported_needs'].map(String) : [],
    }),
    unsupported: Array.isArray(place['unsupported']) ? place['unsupported'].map(String) : [],
    environment,
    destinations,
    roster,
    frames,
    events,
    eventsBySubject: bySubject,
  });
}

/** One recorded frame in the shape the renderer and inspector read. */
export function recordingState(recording: LivingSocietyRecording, index: number): OwnedSocietyState {
  const frame = recording.frames[index] ?? fail(`frame ${index} is outside the recording`);
  return {
    profile: 'exulanica-society/v4',
    society_id: recording.societyId,
    branch_id: recording.branchId,
    tick: frame.tick,
    minute_of_day: frame.minuteOfDay,
    inhabitants: frame.inhabitants.map((person, n) => {
      const entry = recording.roster[n]!;
      const summary = recording.events.get(person.explanation_event_ids[0] ?? '')?.summary;
      return {
        id: entry.id,
        synthetic: true as const,
        role: entry.role,
        role_reason: entry.roleReason,
        walk_speed_mm_per_tick: entry.walkSpeedMmPerTick,
        position_mm: person.position_mm,
        motion_path_mm: person.motion_path_mm,
        indoors: person.indoors,
        action: person.action,
        goal: person.goal,
        needs: person.needs,
        explanation: {
          summary: summary ?? 'Simulated inhabitant awaiting its first choice.',
          event_ids: person.explanation_event_ids,
        },
      };
    }),
  };
}

export function clockText(minuteOfDay: number): string {
  const hours = Math.floor(minuteOfDay / 60) % 24;
  return `${String(hours).padStart(2, '0')}:${String(minuteOfDay % 60).padStart(2, '0')}`;
}

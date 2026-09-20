import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';

export interface SocietySnapshot {
  readonly societyId: string;
  readonly versionId: string;
  readonly placeId: string;
  readonly populationSize: number;
  readonly currentTick: number;
  readonly stateSha256: string;
  readonly state: OwnedSocietyState;
}

const record = (value: unknown): Readonly<Record<string, unknown>> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid society response');
  }
  return value as Readonly<Record<string, unknown>>;
};

const textValue = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const integer = (value: unknown, minimum = 0): value is number => Number.isSafeInteger(value) && (value as number) >= minimum;
const boundedInteger = (value: unknown, minimum: number, maximum: number): value is number =>
  integer(value, minimum) && (value as number) <= maximum;
const digest = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const point = (value: unknown): value is readonly [number, number] => Array.isArray(value) && value.length === 2 && value.every(Number.isSafeInteger);
const MINUTES_PER_DAY = 1_440;
const LIVING_TICK_SECONDS = 60;

function routineBinding(value: unknown): NonNullable<OwnedSocietyState['routine']> {
  const routine = record(value);
  const versions = record(routine['catalog_versions']);
  const entries = Object.entries(versions);
  if (entries.length === 0 || !digest(routine['sha256']) || entries.some(([key, version]) =>
    !/^[a-z][a-z0-9_-]*$/.test(key) || !integer(version, 1))) {
    throw new Error('Invalid living society routine');
  }
  return Object.freeze({
    catalog_versions: Object.freeze(Object.fromEntries(entries.sort(([left], [right]) => left.localeCompare(right))) as Record<string, number>),
    sha256: routine['sha256'],
  });
}

/**
 * A persisted v4 state in the shape the renderer and inspector read. Roles, indoor presence,
 * speed and the simulated clock are copied from canonical fields; nothing is derived here.
 */
function livingPresentation(row: Readonly<Record<string, unknown>>, state: Readonly<Record<string, unknown>>): OwnedSocietyState {
  const population = record(state['population']);
  const clock = record(state['clock']);
  const routine = routineBinding(state['routine']);
  const inhabitants = state['inhabitants'];
  if (!integer(row['population_size'], 1) || !Array.isArray(inhabitants) || inhabitants.length !== row['population_size'] ||
      population['size'] !== row['population_size'] ||
      state['tick_seconds'] !== LIVING_TICK_SECONDS ||
      !boundedInteger(clock['start_minute_of_day'], 0, MINUTES_PER_DAY - 1) ||
      !boundedInteger(clock['minute_of_day'], 0, MINUTES_PER_DAY - 1) || !integer(clock['day']) ||
      state['society_id'] !== row['society_id'] || state['branch_id'] !== row['version_id'] ||
      row['branch_id'] !== state['branch_id'] || !integer(state['input_seq'], 1) || row['input_seq'] !== state['input_seq'] ||
      !digest(state['input_sha256']) || row['input_sha256'] !== state['input_sha256']) throw new Error('Invalid living society state');
  const absoluteMinute = (clock['start_minute_of_day'] as number) + (state['tick'] as number);
  if (!Number.isSafeInteger(absoluteMinute) || clock['minute_of_day'] !== absoluteMinute % MINUTES_PER_DAY ||
      clock['day'] !== Math.floor(absoluteMinute / MINUTES_PER_DAY)) {
    throw new Error('Invalid living society clock');
  }
  const ids = new Set<string>();
  const people = inhabitants.map((value) => {
    const person = record(value);
    // A v2 place states the height of the surface each person stands on. Nothing here carries it
    // to the crowd, which draws every walker on the ground plane, so a height that arrives is
    // refused rather than dropped on the way: see the same refusal in the crowd itself.
    if ('support_z_mm' in person) {
      throw new Error('This app carries no support height to a crowd that draws the ground plane');
    }
    const location = record(person['location']), action = record(person['action']), explanation = record(person['explanation']);
    const path = person['motion_path_mm'];
    if (!textValue(person['id']) || ids.has(person['id']) || person['synthetic'] !== true || !point(person['position_mm']) ||
        'display_name' in person || typeof location['indoors'] !== 'boolean' || !integer(person['walk_speed_mm_per_tick'], 1) ||
        !textValue(action['kind']) || !['active', 'completed', 'blocked'].includes(String(action['status'])) ||
        !(action['destination_id'] === null || textValue(action['destination_id'])) || !textValue(action['reason']) ||
        !textValue(explanation['summary']) || !Array.isArray(explanation['event_ids']) || !explanation['event_ids'].every(textValue) ||
        !Array.isArray(path) || path.length < 1 || !path.every(point)) throw new Error('Invalid living society inhabitant');
    const end = path[path.length - 1] as readonly number[];
    if (end[0] !== person['position_mm'][0] || end[1] !== person['position_mm'][1]) throw new Error('Invalid society motion endpoint');
    ids.add(person['id']);
    const role = person['role'] === null ? null : record(person['role']);
    const goal = person['goal'] === null ? null : record(person['goal']);
    if ((role && !textValue(role['label'])) || (goal && (!textValue(goal['activity']) || !textValue(goal['because'])))) {
      throw new Error('Invalid living society role or goal');
    }
    return {
      id: person['id'],
      synthetic: true as const,
      role: role ? role['label'] as string : null,
      role_reason: String(person['role_reason']),
      position_mm: person['position_mm'],
      motion_path_mm: path as readonly (readonly [number, number])[],
      indoors: location['indoors'],
      walk_speed_mm_per_tick: person['walk_speed_mm_per_tick'],
      needs: record(person['needs']) as Readonly<Record<string, number>>,
      action: action as unknown as NonNullable<OwnedSocietyState['inhabitants'][number]['action']>,
      goal: goal ? { activity: goal['activity'] as string, destination_id: (goal['destination_id'] ?? null) as string | null, because: goal['because'] as string } : null,
      explanation: explanation as unknown as { summary: string; event_ids: readonly string[] },
    };
  });
  return {
    profile: 'exulanica-society/v4',
    society_id: state['society_id'] as string,
    branch_id: state['branch_id'] as string,
    input_seq: state['input_seq'] as number,
    input_sha256: state['input_sha256'] as string,
    routine,
    tick: state['tick'] as number,
    tick_seconds: state['tick_seconds'] as number,
    start_minute_of_day: clock['start_minute_of_day'] as number,
    minute_of_day: clock['minute_of_day'] as number,
    day: clock['day'] as number,
    inhabitants: people,
  };
}

export function parseSociety(value: unknown): SocietySnapshot {
  const row = record(value);
  const state = record(row['state']);
  if (state['profile'] === 'exulanica-society/v4') {
    if (!textValue(row['society_id']) || !textValue(row['version_id']) || !textValue(row['place_id']) ||
        !integer(row['current_tick']) || state['tick'] !== row['current_tick'] || !digest(row['state_sha256'])) {
      throw new Error('Invalid society response');
    }
    return Object.freeze({
      societyId: row['society_id'], versionId: row['version_id'], placeId: row['place_id'],
      populationSize: row['population_size'] as number, currentTick: row['current_tick'], stateSha256: row['state_sha256'],
      state: livingPresentation(row, state),
    });
  }
  const inhabitants = state['inhabitants'];
  const v2 = state['profile'] === 'exulanica-society/v2';
  if (!textValue(row['society_id']) || !textValue(row['version_id']) || !textValue(row['place_id']) ||
      !integer(row['population_size'], 100) || row['population_size'] > 512 ||
      !integer(row['current_tick']) || state['tick'] !== row['current_tick'] ||
      !digest(row['state_sha256']) || !Array.isArray(inhabitants) || inhabitants.length !== row['population_size'] ||
      (state['profile'] !== undefined && state['profile'] !== 'exulanica-society/v1' && !v2)) throw new Error('Invalid society response');
  const ids = new Set<string>();
  for (const value of inhabitants) {
    const inhabitant = record(value);
    if (!textValue(inhabitant['id']) || ids.has(inhabitant['id']) || inhabitant['synthetic'] !== true ||
        !point(inhabitant['position_mm'])) throw new Error('Invalid society inhabitant');
    ids.add(inhabitant['id']);
    if (!v2) continue;
    const action = record(inhabitant['action']), explanation = record(inhabitant['explanation']);
    const path = inhabitant['motion_path_mm'];
    if (!textValue(inhabitant['display_name']) || !textValue(inhabitant['role']) ||
        !['idle', 'move', 'visit', 'rest'].includes(String(action['kind'])) ||
        !['active', 'completed', 'blocked'].includes(String(action['status'])) ||
        !(action['target_id'] === null || textValue(action['target_id'])) ||
        !integer(action['remaining_ticks']) || !textValue(action['reason']) ||
        !textValue(explanation['summary']) || !Array.isArray(explanation['event_ids']) ||
        !explanation['event_ids'].every(textValue) || !Array.isArray(path) || path.length < 1 ||
        !path.every(point)) throw new Error('Invalid society action or explanation');
    const end = path[path.length - 1] as readonly number[];
    if (end[0] !== inhabitant['position_mm'][0] || end[1] !== inhabitant['position_mm'][1]) throw new Error('Invalid society motion endpoint');
    if (inhabitant['goal'] !== null) {
      const goal = record(inhabitant['goal']);
      if (!['visit', 'rest'].includes(String(goal['kind'])) || !textValue(goal['target_id']) || !textValue(goal['reason'])) throw new Error('Invalid society goal');
    }
    if (inhabitant['route'] !== null) {
      const route = record(inhabitant['route']);
      if (!Array.isArray(route['node_ids']) || !route['node_ids'].every(textValue) ||
          !integer(route['edge_index']) || !integer(route['edge_progress_mm']) ||
          !textValue(route['destination_node_id']) || !digest(route['input_sha256'])) throw new Error('Invalid society route');
    }
  }
  if (v2 && (state['society_id'] !== row['society_id'] || state['branch_id'] !== row['version_id'] ||
      row['branch_id'] !== state['branch_id'] || !integer(state['input_seq'], 1) ||
      row['input_seq'] !== state['input_seq'] || !digest(state['input_sha256']) ||
      row['input_sha256'] !== state['input_sha256'])) throw new Error('Invalid society branch or input');
  return Object.freeze({
    societyId: row['society_id'], versionId: row['version_id'], placeId: row['place_id'],
    populationSize: row['population_size'], currentTick: row['current_tick'], stateSha256: row['state_sha256'],
    state: state as unknown as OwnedSocietyState,
  });
}

export type SocietyProfile = 'exulanica-society/v1' | 'exulanica-society/v2' | 'exulanica-society/v4';

/** Authorized persisted events. The endpoint returns only its latest bounded window. */
export interface SocietyEvent {
  readonly event_id: string;
  readonly subject_id: string;
  readonly tick: number;
  readonly event_kind: string;
  readonly document_sha256: string;
  readonly document: Readonly<Record<string, unknown>> & {
    readonly synthetic: true;
    readonly summary: string;
  };
}

export function parseSocietyEvents(value: unknown, snapshot: SocietySnapshot): readonly SocietyEvent[] {
  const rows = record(value)['events'];
  if (!Array.isArray(rows) || rows.length > 256) throw new Error('Invalid society events');
  const ids = new Set<string>();
  const subjects = new Set(snapshot.state.inhabitants.map(person => person.id));
  const events = rows.map(raw => {
    const row = record(raw), doc = record(row['document']);
    if (!textValue(row['event_id']) || ids.has(row['event_id']) ||
        !textValue(row['subject_id']) || !subjects.has(row['subject_id']) ||
        !integer(row['tick']) || !textValue(row['event_kind']) ||
        !digest(row['document_sha256']) || doc['synthetic'] !== true || !textValue(doc['summary'])) {
      throw new Error('Invalid society event');
    }
    ids.add(row['event_id']);
    const pathful = snapshot.state.profile === 'exulanica-society/v2' || snapshot.state.profile === 'exulanica-society/v4';
    if (pathful &&
        (doc['profile'] !== snapshot.state.profile || doc['branch_id'] !== snapshot.versionId ||
         doc['subject_id'] !== row['subject_id'] || doc['tick'] !== row['tick'] ||
         !integer(doc['order']) || !integer(doc['input_seq'], 1) || !digest(doc['input_sha256']) ||
         !textValue(doc['reason']) || !textValue(doc['outcome']))) throw new Error('Invalid society event binding');
    return row as unknown as SocietyEvent;
  });
  // Another browser can advance between GET snapshot and GET events. Do not attach future
  // reasons to the held state, nor claim this bounded endpoint is the complete history.
  return Object.freeze(events.filter(event => event.tick <= snapshot.currentTick));
}

function boundSnapshot(value: unknown, versionId: string): SocietySnapshot {
  const snapshot = parseSociety(value);
  if (snapshot.versionId !== versionId) throw new Error('Society response belongs to another branch');
  return snapshot;
}

export class SocietyClient {
  private readonly transport: Transport;

  constructor(options: TransportOptions) {
    this.transport = new Transport(options);
  }

  async connect(
    versionId: string,
    placeId: string,
    regionId: string,
    profile: SocietyProfile = 'exulanica-society/v2',
  ): Promise<SocietySnapshot> {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society`;
    try {
      return await this.read(versionId);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      return boundSnapshot(await this.transport.postJson<unknown>(path, {
        place_id: placeId,
        region_id: regionId,
        seed: '7a'.repeat(32),
        profile,
      }), versionId);
    }
  }

  read(versionId: string): Promise<SocietySnapshot> {
    return this.transport.getJson<unknown>(
      `/world/versions/${encodeURIComponent(versionId)}/society`,
    ).then(value => boundSnapshot(value, versionId));
  }

  events(snapshot: SocietySnapshot): Promise<readonly SocietyEvent[]> {
    return this.transport.getJson<unknown>(
      `/world/versions/${encodeURIComponent(snapshot.versionId)}/society/events`,
      { limit: '256' },
    ).then(value => parseSocietyEvents(value, snapshot));
  }

  advance(snapshot: SocietySnapshot): Promise<SocietySnapshot> {
    return this.transport.postJson<unknown>(
      `/world/versions/${encodeURIComponent(snapshot.versionId)}/society/steps`,
      {
        base_tick: snapshot.currentTick,
        base_state_sha256: snapshot.stateSha256,
      },
    ).then(value => boundSnapshot(value, snapshot.versionId));
  }
}

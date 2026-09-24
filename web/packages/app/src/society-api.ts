/**
 * Authenticated society snapshot, events, one deterministic step, and typed directed actions.
 *
 * Speaks `/world/versions/{id}/society` (`exulanica/api/routes/society.py`) and
 * `/world/versions/{id}/society/actions` (`exulanica/api/routes/society_actions.py`).
 * `connect` reads an existing society or creates one; `create` only creates, for a person who
 * asked; `advance` posts one step against the tick and digest the caller already holds;
 * `requestAction` records a typed `go_to` or `perform` against a canonical target. This module
 * does not start playback or request a model decision.
 *
 * Every request names the open world as `world_id`, because the server reads a version only in
 * the world a request names and has no default world to fall back on.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { DEFAULT_SOCIETY_ENGINE, societyEngine, type SocietyEngineProfile } from './society-engines.js';
import { openWorldPath } from './world-scope.js';

export interface SocietySnapshot {
  readonly societyId: string;
  readonly versionId: string;
  readonly placeId: string;
  /** How many people the society was created with, whether or not they are here now. */
  readonly populationSize: number;
  readonly currentTick: number;
  readonly stateSha256: string;
  readonly state: OwnedSocietyState;
  /** Where inhabitants can go, when the read asked for it; null otherwise. */
  readonly places: SocietyPlaces | null;
  /** Whether the people are here, or were sent away, and since which simulated minute. */
  readonly presence: SocietyPresence;
}

/** Everyone here, or everyone sent away by the person whose world it is. */
export interface SocietyPresence {
  readonly status: 'here' | 'away';
  /** The simulated minute of the last change, or null when nobody was ever sent away. */
  readonly sinceTick: number | null;
}

const EVERYONE_HERE: SocietyPresence = Object.freeze({ status: 'here', sinceTick: null });

function presenceOf(state: Readonly<Record<string, unknown>>): SocietyPresence {
  if (state['presence'] === undefined) return EVERYONE_HERE;
  const held = record(state['presence']);
  if (!['here', 'away'].includes(String(held['status'])) || !integer(held['since_tick'], 1) ||
      !textValue(held['request_id']) || !digest(held['request_sha256'])) {
    throw new Error('Invalid society presence');
  }
  return Object.freeze({ status: held['status'] as 'here' | 'away', sinceTick: held['since_tick'] as number });
}

export type SocietyAffordance = 'visit' | 'rest';

/** One activity an inhabitant can be directed to, as the consumed input states it. */
export interface SocietyPlace {
  readonly targetId: string;
  readonly subjectId: string;
  /** The authored object the activity belongs to, or null for a district's own destination. */
  readonly objectId: string | null;
  readonly affordance: SocietyAffordance;
  readonly durationTicks: number;
  readonly enabled: boolean;
  /**
   * Where its occupants stand, one person to a place, when the input states places; empty for
   * an input that does not, where the activity is used at its access node with no limit.
   */
  readonly placeNodeIds: readonly string[];
}

/** An object's activity the input says no inhabitant can reach, with the server's reason. */
export interface SocietyUnreachablePlace {
  readonly targetId: string;
  readonly objectId: string;
  readonly affordance: SocietyAffordance;
  readonly reason: string;
}

/** The area a society walks, and whether the ground states it or the society declared it. */
export interface SocietyWalkableArea {
  readonly source: 'ground' | 'declared';
  readonly centreMm: readonly [number, number];
  readonly halfWidthMm: number;
  readonly halfDepthMm: number;
}

/**
 * Where inhabitants can go, copied from the one input the society's current state consumed.
 * An input queued by an edit that no step has consumed yet is not described: nothing in the
 * society has acted on it.
 */
export interface SocietyPlaces {
  readonly inputSeq: number;
  readonly inputSha256: string;
  readonly available: boolean;
  readonly unavailableReason: string | null;
  readonly walkableArea: SocietyWalkableArea | null;
  readonly clearanceMm: number;
  readonly targets: readonly SocietyPlace[];
  readonly unreachable: readonly SocietyUnreachablePlace[];
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

const affordance = (value: unknown): value is SocietyAffordance => value === 'visit' || value === 'rest';

/** The places a read carries, bound to the input the snapshot says its state consumed. */
function placesOf(row: Readonly<Record<string, unknown>>): SocietyPlaces | null {
  if (row['places'] === undefined || row['places'] === null) return null;
  const places = record(row['places']);
  const targets = places['targets'], unreachable = places['unavailable_affordances'];
  const area = places['walkable_area'];
  if (!integer(places['input_seq'], 1) || places['input_seq'] !== row['input_seq'] ||
      !digest(places['input_sha256']) || places['input_sha256'] !== row['input_sha256'] ||
      !['available', 'unavailable'].includes(String(places['availability'])) ||
      !(places['unavailable_reason'] === null || textValue(places['unavailable_reason'])) ||
      !integer(places['clearance_mm']) || !Array.isArray(targets) || !Array.isArray(unreachable)) {
    throw new Error('Invalid society places');
  }
  let walkableArea: SocietyWalkableArea | null = null;
  if (area !== null && area !== undefined) {
    const held = record(area);
    if (!['ground', 'declared'].includes(String(held['source'])) || !point(held['centre_mm']) ||
        !integer(held['half_width_mm'], 1) || !integer(held['half_depth_mm'], 1)) {
      throw new Error('Invalid society walkable area');
    }
    walkableArea = Object.freeze({
      source: held['source'] as 'ground' | 'declared',
      centreMm: held['centre_mm'] as readonly [number, number],
      halfWidthMm: held['half_width_mm'] as number,
      halfDepthMm: held['half_depth_mm'] as number,
    });
  }
  return Object.freeze({
    inputSeq: places['input_seq'] as number,
    inputSha256: places['input_sha256'] as string,
    available: places['availability'] === 'available',
    unavailableReason: places['unavailable_reason'] as string | null,
    walkableArea,
    clearanceMm: places['clearance_mm'] as number,
    targets: Object.freeze(targets.map((value) => {
      const target = record(value);
      const places = target['place_node_ids'];
      if (!textValue(target['target_id']) || !textValue(target['subject_id']) ||
          !(target['object_id'] === null || textValue(target['object_id'])) ||
          !affordance(target['affordance']) || !integer(target['duration_ticks'], 1) ||
          typeof target['enabled'] !== 'boolean' ||
          !(places === undefined || (Array.isArray(places) && places.length > 0 && places.every(textValue)))) {
        throw new Error('Invalid society place');
      }
      return Object.freeze({
        targetId: target['target_id'], subjectId: target['subject_id'],
        objectId: target['object_id'] as string | null, affordance: target['affordance'],
        durationTicks: target['duration_ticks'] as number, enabled: target['enabled'] as boolean,
        placeNodeIds: Object.freeze([...((places ?? []) as string[])]),
      });
    })),
    unreachable: Object.freeze(unreachable.map((value) => {
      const held = record(value);
      if (!textValue(held['target_id']) || !textValue(held['object_id']) ||
          !affordance(held['affordance']) || !textValue(held['reason'])) {
        throw new Error('Invalid unreachable society place');
      }
      return Object.freeze({
        targetId: held['target_id'], objectId: held['object_id'],
        affordance: held['affordance'], reason: held['reason'],
      });
    })),
  });
}

export function parseSociety(value: unknown): SocietySnapshot {
  const row = record(value);
  const state = record(row['state']);
  // Which reader applies, and how many people the engine may hold, come from the engine table;
  // an engine it does not state is refused by name. A state that names no profile is the
  // default engine's, the one a society is created with when a request names none.
  const engine = societyEngine(state['profile'] ?? DEFAULT_SOCIETY_ENGINE);
  if (!boundedInteger(row['population_size'], engine.populationMinimum, engine.populationMaximum)) {
    throw new Error('Invalid society response');
  }
  if (engine.stateFamily === 'living') {
    if (!textValue(row['society_id']) || !textValue(row['version_id']) || !textValue(row['place_id']) ||
        !integer(row['current_tick']) || state['tick'] !== row['current_tick'] || !digest(row['state_sha256'])) {
      throw new Error('Invalid society response');
    }
    return Object.freeze({
      societyId: row['society_id'], versionId: row['version_id'], placeId: row['place_id'],
      populationSize: row['population_size'] as number, currentTick: row['current_tick'], stateSha256: row['state_sha256'],
      state: livingPresentation(row, state), places: placesOf(row), presence: EVERYONE_HERE,
    });
  }
  const inhabitants = state['inhabitants'];
  const v2 = engine.stateFamily === 'purposeful';
  // Sent away, a society holds nobody until the same people are brought back.
  const presence = presenceOf(state);
  const holding = presence.status === 'away' ? 0 : row['population_size'];
  if (!textValue(row['society_id']) || !textValue(row['version_id']) || !textValue(row['place_id']) ||
      !integer(row['current_tick']) || state['tick'] !== row['current_tick'] ||
      !digest(row['state_sha256']) || !Array.isArray(inhabitants) || inhabitants.length !== holding) {
    throw new Error('Invalid society response');
  }
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
      // A goal is an activity at a target, or a walk that makes room at a busy destination,
      // which names no target.
      const goal = record(inhabitant['goal']);
      const activity = ['visit', 'rest'].includes(String(goal['kind'])) && textValue(goal['target_id']);
      const makingRoom = goal['kind'] === 'make_room' && goal['target_id'] === null;
      if (!(activity || makingRoom) || !textValue(goal['reason'])) throw new Error('Invalid society goal');
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
    state: state as unknown as OwnedSocietyState, places: v2 ? placesOf(row) : null, presence,
  });
}

/** Every engine profile the server's engine table states. */
export type SocietyProfile = SocietyEngineProfile;

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
  // While everyone is away the state names nobody, yet the history still holds their events:
  // those belong to the society's own people, whom the state will name again when they return.
  const subjects = new Set(snapshot.state.inhabitants.map(person => person.id));
  const anyoneOfTheSociety = snapshot.presence.status === 'away';
  const events = rows.map(raw => {
    const row = record(raw), doc = record(row['document']);
    if (!textValue(row['event_id']) || ids.has(row['event_id']) ||
        !textValue(row['subject_id']) || !(anyoneOfTheSociety || subjects.has(row['subject_id'])) ||
        !integer(row['tick']) || !textValue(row['event_kind']) ||
        !digest(row['document_sha256']) || doc['synthetic'] !== true || !textValue(doc['summary'])) {
      throw new Error('Invalid society event');
    }
    ids.add(row['event_id']);
    const pathful = societyEngine(snapshot.state.profile ?? DEFAULT_SOCIETY_ENGINE).takesInputs;
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

/** Typed user-directed action over a canonical simulation target. Not personal evidence. */
export type SocietyActionKind = 'go_to' | 'perform';
export type SocietyActionAffordance = 'visit' | 'rest';
export type SocietyActionStatus = 'pending' | 'consumed';

export interface SocietyActionIntent {
  readonly kind: SocietyActionKind;
  readonly targetId: string;
  readonly affordance?: SocietyActionAffordance;
}

export interface SocietyActionRequest {
  readonly profile: 'exulanica.society-action-request/v1';
  readonly requestId: string;
  readonly requestedBy: string;
  readonly subjectId: string;
  readonly branchId: string;
  readonly baseTick: number;
  readonly baseStateSha256: string;
  readonly inputSeq: number;
  readonly inputSha256: string;
  readonly intent: Readonly<{
    readonly kind: SocietyActionKind;
    readonly target_id: string;
    readonly affordance?: SocietyActionAffordance;
  }>;
  readonly target: Readonly<Record<string, unknown>>;
  readonly documentSha256: string;
}

export interface SocietyActionRecord {
  readonly request: SocietyActionRequest;
  readonly status: SocietyActionStatus;
  readonly consumption: Readonly<{
    readonly tick: number;
    readonly disposition: string;
  }> | null;
}

export function parseSocietyActionRecord(value: unknown, versionId: string): SocietyActionRecord {
  const row = record(value);
  const request = record(row['request']);
  const intent = record(request['intent']);
  const target = record(request['target']);
  const kind = intent['kind'];
  const affordance = intent['affordance'];
  if (request['profile'] !== 'exulanica.society-action-request/v1'
    || request['branch_id'] !== versionId
    || !textValue(request['request_id']) || !textValue(request['requested_by'])
    || !textValue(request['subject_id']) || !integer(request['base_tick'])
    || !digest(request['base_state_sha256']) || !integer(request['input_seq'], 1)
    || !digest(request['input_sha256']) || !digest(request['document_sha256'])
    || !textValue(intent['target_id'])
    || (kind !== 'go_to' && kind !== 'perform')
    || (kind === 'go_to' && affordance !== undefined)
    || (kind === 'perform' && affordance !== 'visit' && affordance !== 'rest')
    || !textValue(target['target_id'])
    || (row['status'] !== 'pending' && row['status'] !== 'consumed')) {
    throw new Error('Invalid society action response');
  }
  let consumption: SocietyActionRecord['consumption'] = null;
  if (row['consumption'] !== null && row['consumption'] !== undefined) {
    const held = record(row['consumption']);
    if (!integer(held['tick']) || !textValue(held['disposition'])) {
      throw new Error('Invalid society action consumption');
    }
    consumption = Object.freeze({ tick: held['tick'] as number, disposition: held['disposition'] as string });
  } else if (row['status'] === 'consumed') {
    throw new Error('Invalid society action consumption');
  }
  return Object.freeze({
    request: Object.freeze({
      profile: 'exulanica.society-action-request/v1' as const,
      requestId: request['request_id'] as string,
      requestedBy: request['requested_by'] as string,
      subjectId: request['subject_id'] as string,
      branchId: request['branch_id'] as string,
      baseTick: request['base_tick'] as number,
      baseStateSha256: request['base_state_sha256'] as string,
      inputSeq: request['input_seq'] as number,
      inputSha256: request['input_sha256'] as string,
      intent: Object.freeze({
        kind: kind as SocietyActionKind,
        target_id: intent['target_id'] as string,
        ...(kind === 'perform' ? { affordance: affordance as SocietyActionAffordance } : {}),
      }),
      target: Object.freeze({ ...target }),
      documentSha256: request['document_sha256'] as string,
    }),
    status: row['status'] as SocietyActionStatus,
    consumption,
  });
}

export interface SocietyClientOptions extends TransportOptions {
  /** The open world the versions belong to; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

export class SocietyClient {
  private readonly transport: Transport;
  private readonly worldId: string | null;

  constructor(options: SocietyClientOptions) {
    this.transport = new Transport(options);
    this.worldId = options.worldId;
  }

  /** A society route in the open world. */
  private path(versionId: string, suffix = ''): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society${suffix}`;
    return openWorldPath(path, this.worldId, 'society to read or change');
  }

  async connect(
    versionId: string,
    placeId: string | null,
    regionId: string,
    profile: SocietyProfile = 'exulanica-society/v2',
  ): Promise<SocietySnapshot> {
    try {
      return await this.read(versionId);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      return this.create(versionId, placeId, regionId, profile);
    }
  }

  /**
   * Create this version's society, or read back the one already there. A null place asks the
   * server for a saved world's own, which it derives from the version; the client never makes one.
   */
  async create(
    versionId: string,
    placeId: string | null,
    regionId: string,
    profile: SocietyProfile = 'exulanica-society/v2',
  ): Promise<SocietySnapshot> {
    return this.transport.postJson<unknown>(this.path(versionId), {
      ...(placeId === null ? {} : { place_id: placeId }),
      region_id: regionId,
      seed: '7a'.repeat(32),
      profile,
    }).then(value => boundSnapshot(value, versionId));
  }

  /**
   * Send everyone away, or bring them back, against the state the person was shown. The server
   * records the change as one simulated minute of history and answers with the new state; a
   * refusal names what stands in the way (`nobody_to_send_away`, `already_here`, ...).
   */
  async changePresence(snapshot: SocietySnapshot, presence: 'away' | 'here', idempotencyKey: string = crypto.randomUUID()): Promise<SocietySnapshot> {
    return this.transport.postJson<unknown>(this.path(snapshot.versionId, '/presence'), {
      idempotency_key: idempotencyKey,
      presence,
      base_tick: snapshot.currentTick,
      base_state_sha256: snapshot.stateSha256,
    }).then(value => boundSnapshot(value, snapshot.versionId));
  }

  /** The current state; `places` also reads where inhabitants can go. */
  async read(versionId: string, options: { readonly places?: boolean } = {}): Promise<SocietySnapshot> {
    return this.transport.getJson<unknown>(
      this.path(versionId),
      options.places === true ? { places: 'true' } : undefined,
    ).then(value => boundSnapshot(value, versionId));
  }

  async events(snapshot: SocietySnapshot): Promise<readonly SocietyEvent[]> {
    return this.transport.getJson<unknown>(
      this.path(snapshot.versionId, '/events'),
      { limit: '256' },
    ).then(value => parseSocietyEvents(value, snapshot));
  }

  async advance(snapshot: SocietySnapshot): Promise<SocietySnapshot> {
    return this.transport.postJson<unknown>(
      this.path(snapshot.versionId, '/steps'),
      {
        base_tick: snapshot.currentTick,
        base_state_sha256: snapshot.stateSha256,
      },
    ).then(value => boundSnapshot(value, snapshot.versionId));
  }

  /**
   * Record one typed directed action through `record_action` on the society actions route.
   * Returns the server envelope; does not advance simulation time.
   */
  async requestAction(
    snapshot: SocietySnapshot,
    subjectId: string,
    intent: SocietyActionIntent,
    idempotencyKey: string = crypto.randomUUID(),
  ): Promise<SocietyActionRecord> {
    const bodyIntent = intent.kind === 'perform'
      ? { kind: 'perform' as const, target_id: intent.targetId, affordance: intent.affordance }
      : { kind: 'go_to' as const, target_id: intent.targetId };
    if (intent.kind === 'perform' && intent.affordance !== 'visit' && intent.affordance !== 'rest') {
      return Promise.reject(new Error('perform requires a visit or rest affordance'));
    }
    return this.transport.postJson<unknown>(
      this.path(snapshot.versionId, '/actions'),
      {
        idempotency_key: idempotencyKey,
        base_tick: snapshot.currentTick,
        base_state_sha256: snapshot.stateSha256,
        subject_id: subjectId,
        intent: bodyIntent,
      },
    ).then(value => parseSocietyActionRecord(value, snapshot.versionId));
  }
}

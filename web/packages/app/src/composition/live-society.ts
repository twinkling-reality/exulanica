import { ApiError, type TransportOptions } from '@exulanica/graph-client';
import {
  SocietyClient,
  type SocietyEvent,
  type SocietyProfile,
  type SocietySnapshot,
} from '../society-api.js';

type SocietyPort = Pick<SocietyClient, 'connect' | 'read' | 'advance' | 'events'> &
  Partial<Pick<SocietyClient, 'create'>>;
export interface LiveSocietyView {
  readonly mode: 'authenticated';
  /** `absent`: this world holds no society yet, and none is made until somebody asks. */
  readonly status: 'idle' | 'loading' | 'ready' | 'stale' | 'unauthorized' | 'unavailable' | 'absent';
  readonly busy: boolean;
  readonly snapshot: SocietySnapshot | null;
  readonly events: readonly SocietyEvent[];
  readonly eventsAvailable: boolean;
  readonly message: string;
  /** The server's refusal of the last request to bring inhabitants in, until the next one. */
  readonly refusal: { readonly status: number; readonly code: string; readonly detail: string } | null;
}
export interface LiveSocietyOptions {
  /** Preview composition must never construct this authenticated adapter. */
  readonly preview: boolean;
  readonly credentials: TransportOptions;
  /** The saved world the version belongs to; omitted for the default world. */
  readonly worldId?: string;
  readonly versionId: string;
  /** Null asks the server for a saved world's own place, which it derives from the version. */
  readonly placeId: string | null;
  readonly regionId: string;
  /** The profile a new society is created with. The district's living society is v4. */
  readonly profile?: SocietyProfile;
  /**
   * Whether connecting may create the society. A saved world never gets inhabitants by being
   * opened: connecting only reads it, and `bringIn` is the person's own request.
   */
  readonly createOnConnect?: boolean;
  /** Whether each read also carries where inhabitants can go. */
  readonly places?: boolean;
  readonly onChange: (view: LiveSocietyView) => void;
  readonly client?: SocietyPort;
}

export interface LiveSociety {
  readonly view: LiveSocietyView;
  connect(): Promise<void>;
  /** Create this world's society because the person asked. Never called on their behalf. */
  bringIn(): Promise<void>;
  refresh(): Promise<void>;
  advance(): Promise<void>;
  /** Call only after the authored API confirms an edit or restore succeeded. */
  afterAuthoredEdit(): Promise<void>;
  inspect(subjectId: string): {
    readonly inhabitant: SocietySnapshot['state']['inhabitants'][number] | null;
    readonly events: readonly SocietyEvent[];
    readonly missingEventIds: readonly string[];
  };
  dispose(): void;
}

const emptyEvents: readonly SocietyEvent[] = Object.freeze([]);
const revokes = (error: unknown): boolean => error instanceof ApiError &&
  [401, 403, 404, 424].includes(error.status);

/** A single branch/session owner. It never simulates locally or replays a failed write. */
export function createLiveSociety(options: LiveSocietyOptions): LiveSociety {
  if (options.preview) throw new Error('Recorded preview cannot connect to a persisted society');
  const abort = new AbortController();
  const abortFromParent = () => api.dispose();
  const client = options.client ?? new SocietyClient({
    ...options.credentials,
    signal: abort.signal,
    ...(options.worldId === undefined ? {} : { worldId: options.worldId }),
  });
  const profile = options.profile ?? 'exulanica-society/v4';
  const createOnConnect = options.createOnConnect ?? true;
  const readOptions = { places: options.places === true };
  let disposed = false;
  let pending: Promise<void> | null = null;
  let view: LiveSocietyView = Object.freeze({ mode: 'authenticated', status: 'idle', busy: false,
    snapshot: null, events: emptyEvents, eventsAvailable: false, message: 'Persisted society is not connected.',
    refusal: null });
  const alive = () => !disposed && !abort.signal.aborted;
  const publish = (patch: Partial<LiveSocietyView>) => {
    if (!alive()) return;
    view = Object.freeze({ ...view, ...patch });
    options.onChange(view);
  };
  const checked = (snapshot: SocietySnapshot) => {
    // A saved world's place is the server's to name. The first snapshot says which it is, and
    // every later one must say the same.
    const place = options.placeId ?? view.snapshot?.placeId ?? snapshot.placeId;
    if (snapshot.versionId !== options.versionId || snapshot.placeId !== place ||
        (view.snapshot && view.snapshot.societyId !== snapshot.societyId)) {
      throw new Error('Society response does not match the connected world');
    }
    if (snapshot.state.profile !== 'exulanica-society/v2' && snapshot.state.profile !== 'exulanica-society/v4') {
      throw new Error('This world does not use a supported society profile. Its existing history was preserved.');
    }
    return snapshot;
  };
  const fail = (error: unknown) => {
    const unauthorized = error instanceof ApiError && [401, 403].includes(error.status);
    // Current authorization applies to snapshots and events alike. Never keep displaying
    // revoked state because an earlier request happened to succeed.
    publish({ status: unauthorized ? 'unauthorized' : 'unavailable', busy: false,
      ...(revokes(error) ? { snapshot: null } : {}), events: emptyEvents, eventsAvailable: false,
      message: unauthorized ? 'Sign in again to read this world.' :
        error instanceof ApiError && error.status === 424 ? 'Society dependencies are unavailable. Reconnect after access is restored.' :
        `Society unavailable. ${error instanceof Error ? error.message : 'The request failed.'}` });
  };
  const accept = async (raw: SocietySnapshot, message = 'Persisted simulation. Each advance consumes one simulated minute.') => {
    if (!alive()) return;
    const snapshot = checked(raw);
    publish({ snapshot, events: emptyEvents, eventsAvailable: false });
    if (!alive()) return;
    const events = await client.events(snapshot);
    if (!alive()) return;
    publish({ snapshot, events, eventsAvailable: true, status: 'ready', message });
  };
  const run = (operation: () => Promise<void>): Promise<void> => {
    if (!alive()) return Promise.resolve();
    if (pending) return pending;
    // Defer work until pending is installed so reentrant subscribers cannot start a second write.
    pending = Promise.resolve().then(async () => {
      if (!alive()) return;
      publish({ busy: true, status: 'loading' });
      try { if (alive()) await operation(); } catch (error) { if (alive()) fail(error); }
      finally { pending = null; publish({ busy: false }); }
    });
    return pending;
  };
  const absent = () => publish({ status: 'absent', snapshot: null, events: emptyEvents,
    eventsAvailable: false, message: 'Nobody lives in this world yet.' });
  /** Read the society. Where connecting may not create one, a missing society is an answer. */
  const read = async (message?: string) => {
    try {
      await accept(await client.read(options.versionId, readOptions), message);
    } catch (error) {
      if (createOnConnect || !(error instanceof ApiError) || error.status !== 404) throw error;
      absent();
    }
  };
  const refresh = () => run(() => read());
  const api: LiveSociety = {
    get view() { return view; },
    // An existing society keeps its own profile. A new one is created with the profile this
    // world asks for, and only where connecting may create one at all.
    connect: () => run(async () => {
      if (!createOnConnect) { await read(); return; }
      await accept(await client.connect(options.versionId, options.placeId, options.regionId, profile));
    }),
    bringIn: () => run(async () => {
      if (client.create === undefined) throw new Error('This society client cannot create a society.');
      publish({ refusal: null });
      try {
        await client.create(options.versionId, options.placeId, options.regionId, profile);
      } catch (error) {
        // A refusal is an answer about the world, such as nothing in it anybody can reach, and
        // it changed nothing on the server. It is kept for the surface to say in words.
        if (!(error instanceof ApiError) || ![409, 422, 424].includes(error.status)) throw error;
        const prefix = `${error.code}: `;
        const detail = error.message.startsWith(prefix) ? error.message.slice(prefix.length) : error.message;
        publish({ refusal: { status: error.status, code: error.code, detail } });
        if (view.snapshot === null) absent();
        return;
      }
      // Read back rather than trusting the write's body, so places come with it.
      await read('Inhabitants live in this world now. Each advance is one simulated minute.');
    }),
    refresh,
    advance: () => run(async () => {
      const snapshot = view.snapshot;
      if (!snapshot || !view.eventsAvailable) {
        throw new Error('Reconnect to an available society before advancing.');
      }
      try {
        const advanced = await client.advance(snapshot);
        // A step's body carries no places; read them back with the state they belong to.
        if (readOptions.places) await read(); else await accept(advanced);
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'stale_society_state') throw error;
        await accept(await client.read(options.versionId, readOptions));
        publish({ status: 'stale', message: 'Another session changed this society. Its current state is loaded; your advance was not repeated.' });
      }
    }),
    afterAuthoredEdit: async () => {
      // A completed object edit can arrive while a step is in flight. Re-read after it, never
      // discard the edit notification or submit authored JSON as authoritative society input.
      if (pending) await pending;
      await run(() => read('Authored change saved. Advance to consume queued inputs. Restoring an object retains earlier simulation events.'));
    },
    inspect: subjectId => {
      const inhabitant = view.snapshot?.state.inhabitants.find(person => person.id === subjectId) ?? null;
      const refs = inhabitant?.explanation?.event_ids ?? [];
      // Include preceding same-tick decisions: the latest explanation can point at arrival
      // after a replan, and filtering to that reference would hide why the goal changed.
      const events = view.events.filter(event => event.subject_id === subjectId);
      const found = new Set(events.map(event => event.event_id));
      return { inhabitant, events, missingEventIds: refs.filter(id => !found.has(id)) };
    },
    dispose: () => {
      if (disposed) return;
      disposed = true;
      abort.abort();
      options.credentials.signal?.removeEventListener('abort', abortFromParent);
      view = Object.freeze({ ...view, snapshot: null, events: emptyEvents, eventsAvailable: false, busy: false, status: 'idle', message: 'Disconnected.' });
    },
  };
  options.credentials.signal?.addEventListener('abort', abortFromParent, { once: true });
  if (options.credentials.signal?.aborted) api.dispose();
  return api;
}

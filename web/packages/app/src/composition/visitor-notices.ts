/**
 * A plain notice when somebody crosses into a world from outside it, leaves again, or is turned
 * away at the gate: one sentence from the minute's own events (a society of things' crossings,
 * `thing_arrived`, `thing_departed` and `arrival_refused`), with "See who" for an arrival.
 *
 * Every word comes from the event, the thing library's kind labels, the door's entry for the
 * bridge a visitor crossed through and the words catalog's reasons (`reasonWords`), never from a
 * game's or a kind's name in code, so a new game or an outside agent reads correctly with none. An author's placements are not crossings and raise
 * no notice, and nothing that happened before the page first read the world's events does either.
 */

import type { DoorBridge } from '../door-bridges-api.js';
import type { SocietyEvent } from '../society-api.js';
import { reasonWords } from '../society-inhabitant-words.js';
import { withArticle } from './thing-origin-words.js';

/** A thing kind by key, version and digest, as the society's state and events name it. */
export interface KindReference {
  readonly kind: string;
  readonly version: number;
  readonly sha256: string;
}

export interface VisitorNotice {
  /** The event it tells of, so one event is told once. */
  readonly eventId: string;
  readonly message: string;
  /** Who to show for "See who": the visitor that arrived, or null. */
  readonly subjectId: string | null;
  readonly tone: 'info' | 'caution';
}

export interface VisitorNoticeWords {
  /** A kind's label by its reference ("knight"), or null where the library does not list it. */
  kindLabel(kind: KindReference): string | null;
  /** The door's entry for a bridge key, or null where the door does not list it here. */
  bridge(key: string): DoorBridge | null;
}

const capital = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1);

const record = (value: unknown): Readonly<Record<string, unknown>> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

function kindOf(value: unknown): KindReference | null {
  const held = record(value);
  const { kind, version, sha256 } = held;
  return typeof kind === 'string' && typeof version === 'number' && typeof sha256 === 'string' ? { kind, version, sha256 } : null;
}

/** A kind reference as one key, for keeping what was read about it. */
export const kindKey = (kind: KindReference): string => `${kind.kind}/${kind.version}/${kind.sha256}`;

/** Every kind a crossing event names (the visitor's and what it carried), for reading their labels. */
export function noticeKinds(event: SocietyEvent): readonly KindReference[] {
  const thing = record(record(event.document)['thing']);
  const carried = Array.isArray(thing['carried']) ? thing['carried'] : [];
  return [thing['kind'], ...carried.map((held) => record(held)['kind'])].flatMap((value) => {
    const kind = kindOf(value);
    return kind === null ? [] : [kind];
  });
}

/** A kind document's own label, or null where it states none. */
export function kindDocumentLabel(document: unknown): string | null {
  const label = record(document)['label'];
  return typeof label === 'string' && label.trim() !== '' ? label : null;
}

/** What a list of carried things is, in words: "a sword and a lantern"; null for nothing. */
export function carriedWords(labels: readonly string[]): string | null {
  const named = labels.map(withArticle);
  if (named.length === 0) return null;
  if (named.length === 1) return named[0]!;
  return `${named.slice(0, -1).join(', ')} and ${named[named.length - 1]!}`;
}

function carriedLabels(value: unknown, words: VisitorNoticeWords): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((held) => {
    const kind = kindOf(record(held)['kind']);
    const label = kind === null ? null : words.kindLabel(kind);
    return label === null ? [] : [label];
  });
}

/**
 * The notice an event raises, or null: only a crossing's arrival, a visitor's departure and a
 * refused crossing do. `bridgeKey` is the bridge a visitor crossed through, as its state said.
 */
export function visitorNotice(event: SocietyEvent, words: VisitorNoticeWords, bridgeKey: string | null): VisitorNotice | null {
  const document = record(event.document);
  const thing = record(document['thing']);
  const reason = typeof document['reason'] === 'string' ? document['reason'] : '';
  const kind = kindOf(thing['kind']);
  const label = kind === null ? null : words.kindLabel(kind);
  const entry = bridgeKey === null ? null : words.bridge(bridgeKey);
  const from = entry === null ? 'outside this world' : entry.label;
  if (event.event_kind === 'thing_arrived' && thing['came_by'] === 'crossed') {
    const who = label === null ? 'A visitor' : capital(withArticle(label));
    const carrying = carriedWords(carriedLabels(thing['carried'], words));
    return {
      eventId: event.event_id,
      message: `${who} came in from ${from}${carrying === null ? '' : `, carrying ${carrying}`}.`,
      subjectId: event.subject_id,
      tone: 'info',
    };
  }
  if (event.event_kind === 'thing_departed' && thing['came_by'] === 'crossed') {
    const who = label === null ? 'A visitor' : `The ${label}`;
    const carrying = carriedWords(carriedLabels(thing['carried'], words));
    return {
      eventId: event.event_id,
      message: `${who} from ${from} left${carrying === null ? '' : `, taking ${carrying},`} because ${reasonWords(reason)}.`,
      subjectId: null,
      tone: 'info',
    };
  }
  // A crossing names its crossing; a refused placement of the author's does not, and is no visitor.
  if (event.event_kind === 'arrival_refused' && typeof thing['crossing_id'] === 'string') {
    const who = label === null ? 'A visitor' : capital(withArticle(label));
    return {
      eventId: event.event_id,
      message: `${who} could not come in, because ${reasonWords(reason)}.`,
      subjectId: null,
      tone: 'caution',
    };
  }
  return null;
}

/** An event new to the page, and the bridge its subject crossed through, where known. */
export interface FreshEvent {
  readonly event: SocietyEvent;
  readonly bridgeKey: string | null;
}

const CROSSING_EVENTS: ReadonlySet<string> = new Set(['thing_arrived', 'thing_departed', 'arrival_refused']);

/**
 * Which events of a society are new to the page. The first window of events read for a society
 * is what happened before the page looked, and raises nothing; each later read hands back each
 * event it has not seen that may tell of a visitor. It also remembers the bridge each visitor
 * crossed through from every state it is shown (`see`, before `take`), so a departure still
 * names where the visitor came from once the state no longer lists it.
 */
export class VisitorNoticeWatch {
  #societyId: string | null = null;
  #seen = new Set<string>();
  readonly #bridges = new Map<string, string>();

  /** Remember each visitor's bridge from a state about to be drawn. */
  see(people: readonly { readonly id: string; readonly came_by?: string; readonly crossing?: { readonly bridge: string } | null }[]): void {
    for (const person of people) {
      if (person.came_by === 'crossed' && person.crossing != null) this.#bridges.set(person.id, person.crossing.bridge);
    }
  }

  /**
   * The events of `societyId` not seen before that may tell of a visitor, oldest first, each with
   * the bridge its subject crossed through where a state said so; `visitorNotice` words each.
   */
  take(societyId: string, events: readonly SocietyEvent[]): readonly FreshEvent[] {
    const first = this.#societyId !== societyId;
    this.#societyId = societyId;
    const fresh = first ? [] : events.filter((event) => !this.#seen.has(event.event_id) && CROSSING_EVENTS.has(event.event_kind));
    // The window read is bounded; an event that has left it never comes back, so only it is kept.
    this.#seen = new Set(events.map((event) => event.event_id));
    return [...fresh]
      .sort((a, b) => a.tick - b.tick || order(a) - order(b))
      .map((event) => ({ event, bridgeKey: this.#bridges.get(event.subject_id) ?? null }));
  }

  /** Forget the society, as when the world is closed. */
  reset(): void {
    this.#societyId = null;
    this.#seen.clear();
    this.#bridges.clear();
  }
}

const order = (event: SocietyEvent): number => {
  const value = record(event.document)['order'];
  return typeof value === 'number' ? value : 0;
};

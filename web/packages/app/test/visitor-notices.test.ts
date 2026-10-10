// A notice when somebody crosses in from outside, leaves again or is turned away. The events are
// shaped as the society of things records them (docs/synthetic-society-contract.md, "The society of
// things (v7)": `thing_arrived` with reason `crossed_in`, `thing_departed` with `sent_home` or
// `grant_ended`, `arrival_refused` naming its crossing), the refusal codes are the ones that
// contract lists, the reasons' words are the words catalog's own
// (assets/catalogs/society-words/society-inhabitant-words.v1.json) and the labels are the shipped
// kinds' own (assets/catalogs/things).
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { departedNowWords, isMadeKind, kindKey, kindOf, libraryKind, sameKind, visitorNotice, VisitorNoticeWatch, type VisitorNoticeWords } from '../src/composition/visitor-notices.js';
import type { SocietyEvent } from '../src/society-api.js';
import type { DoorBridge } from '../src/door-bridges-api.js';

const repository = `${process.cwd()}/..`;
const kindDocument = (file: string) =>
  JSON.parse(readFileSync(`${repository}/assets/catalogs/things/kinds/${file}`, 'utf8')) as { kind: string; version: number; label: string };
const KNIGHT = kindDocument('knight.v2.json');
const SWORD = kindDocument('sword.v3.json');
const catalog = JSON.parse(readFileSync(`${repository}/assets/catalogs/society-words/society-inhabitant-words.v1.json`, 'utf8')) as
  { entries: { kind: string; code: string; words: string }[] };
/** Why an event happened, as the words catalog says it. */
const because = (code: string): string => catalog.entries.find((entry) => entry.kind === 'event_reason' && entry.code === code)!.words;
const ref = (kind: { kind: string; version: number }) => ({ kind: kind.kind, version: kind.version, sha256: 'a'.repeat(64) });

const GAME: DoorBridge = { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', runBy: 'server', ai: false };
const words: VisitorNoticeWords = {
  kindLabel: (kind) => [KNIGHT, SWORD].find((one) => one.kind === kind.kind)?.label ?? null,
  bridge: (key) => (key === GAME.bridge ? GAME : null),
};

let order = 0;
function event(kind: string, subject: string, tick: number, reason: string, thing: Record<string, unknown>): SocietyEvent {
  order += 1;
  return {
    event_id: `event-${order}`, subject_id: subject, tick, event_kind: kind, document_sha256: 'e'.repeat(64),
    document: { synthetic: true, summary: 'Knight (simulated): arrived; crossed in.', reason, order, thing },
  } as SocietyEvent;
}
const arrived = (subject: string, tick: number, carried: unknown[] = []) =>
  event('thing_arrived', subject, tick, 'crossed_in', { kind: ref(KNIGHT), came_by: 'crossed', placed_id: null, crossing_id: 'c', gate: 'gate', carried });

describe('a visitor notice', () => {
  it('says who came in, from where and carrying what, with the visitor to see', () => {
    const notice = visitorNotice(arrived('visitor-1', 4, [{ thing_id: 'sword-1', kind: ref(SWORD) }]), words, 'blockgame');
    expect(notice).toMatchObject({ message: 'A knight came in from Block Game, carrying a sword.', subjectId: 'visitor-1', tone: 'info' });
  });

  it('says where it came from only as the door lists it', () => {
    expect(visitorNotice(arrived('visitor-1', 4), words, 'unlisted')?.message).toBe('A knight came in from outside this world.');
    expect(visitorNotice(arrived('visitor-1', 4), words, null)?.message).toBe('A knight came in from outside this world.');
  });

  it('says why a visitor left, and what it took', () => {
    const left = (reason: string) => event('thing_departed', 'visitor-1', 6, reason,
      { kind: ref(KNIGHT), came_by: 'crossed', placed_id: null, carried: [{ id: 'sword-1', kind: ref(SWORD) }] });
    expect(visitorNotice(left('sent_home'), words, 'blockgame')).toMatchObject({
      message: `The knight from Block Game left, taking a sword, because ${because('sent_home')}.`, subjectId: null,
    });
    expect(visitorNotice(left('grant_ended'), words, 'blockgame')?.message)
      .toBe(`The knight from Block Game left, taking a sword, because ${because('grant_ended')}.`);
  });

  it('gives a departed visitor\'s open card its leaving, by the latest departure, in place of its last Now', () => {
    const left = event('thing_departed', 'visitor-1', 6, 'sent_home', { kind: ref(KNIGHT), came_by: 'crossed', placed_id: null, carried: [] });
    const events = [arrived('visitor-1', 4), left, arrived('visitor-2', 7)];
    expect(departedNowWords(events, 'visitor-1')).toBe(`Left this world because ${because('sent_home')}.`);
    // Somebody still here, or whose leaving was never read, keeps what the card said.
    expect(departedNowWords(events, 'visitor-2')).toBeNull();
  });

  it('words every refusal and departure the contract names from the catalog, and says nothing of an author\'s placements', () => {
    // docs/synthetic-society-contract.md, the society of things' crossings: each reason has its own words.
    for (const code of ['already_here', 'malformed_crossing', 'no_arrival_place', 'unknown_kind', 'visitor_limit', 'sent_home', 'grant_ended']) {
      const refused = event('arrival_refused', 'visitor-2', 5, code, { kind: ref(KNIGHT), came_by: 'crossed', crossing_id: 'c' });
      expect(visitorNotice(refused, words, null)?.message).toBe(`A knight could not come in, because ${because(code)}.`);
    }
    const refused = event('arrival_refused', 'visitor-2', 5, 'visitor_limit', { kind: ref(KNIGHT), came_by: 'crossed', crossing_id: 'c' });
    expect(visitorNotice(refused, words, null)).toMatchObject({ tone: 'caution', subjectId: null });
    const malformed = event('arrival_refused', 'c', 5, 'malformed_crossing', { crossing_id: 'c' });
    expect(visitorNotice(malformed, words, null)?.message).toBe(`A visitor could not come in, because ${because('malformed_crossing')}.`);
    // The author's own placing and removing are no crossings.
    expect(visitorNotice(event('thing_arrived', 'knight-0', 5, 'placed_by_author', { kind: ref(KNIGHT), came_by: 'placed', placed_id: 'p' }), words, null)).toBeNull();
    expect(visitorNotice(event('thing_departed', 'knight-0', 5, 'removed_by_author', { kind: ref(KNIGHT), came_by: 'placed', placed_id: 'p', carried: [] }), words, null)).toBeNull();
    expect(visitorNotice(event('arrival_refused', 'knight-0', 5, 'no_place_to_stand', { kind: ref(KNIGHT), came_by: 'placed', placed_id: 'p' }), words, null)).toBeNull();
  });
});

describe('the watch over a society\'s events', () => {
  it('tells nothing that happened before the page looked, then each new crossing once, oldest first', () => {
    const watch = new VisitorNoticeWatch();
    const before = arrived('visitor-0', 2);
    expect(watch.take('society', [before])).toEqual([]);
    const first = arrived('visitor-1', 4);
    const second = arrived('visitor-2', 4);
    const walk = event('walked', 'person-0', 4, 'goal', {});
    expect(watch.take('society', [second, walk, first, before]).map((fresh) => fresh.event.subject_id)).toEqual(['visitor-1', 'visitor-2']);
    expect(watch.take('society', [second, walk, first, before])).toEqual([]);
    // Another society's first window is its past too.
    expect(watch.take('other', [arrived('visitor-9', 9)])).toEqual([]);
  });

  it('names the bridge a visitor crossed through after the state stops listing it', () => {
    const watch = new VisitorNoticeWatch();
    watch.take('society', []);
    watch.see([{ id: 'visitor-1', came_by: 'crossed', crossing: { bridge: 'blockgame' } }, { id: 'person-0', came_by: 'populated' }]);
    watch.see([]);
    const left = event('thing_departed', 'visitor-1', 6, 'sent_home', { kind: ref(KNIGHT), came_by: 'crossed', placed_id: null, carried: [] });
    expect(watch.take('society', [left])).toEqual([{ event: left, bridgeKey: 'blockgame' }]);
  });
});

describe('a kind as a society names it', () => {
  const shipped = { kind: 'knight', version: 2, sha256: 'a'.repeat(64) };
  const made = { source: 'workspace' as const, sha256: 'd'.repeat(64) };

  it('is read in either shape: a shipped kind by key, version and digest, a kept one by digest alone', () => {
    expect(kindOf(shipped)).toEqual(shipped);
    expect(kindOf(made)).toEqual(made);
    // A kept kind states no key: one that does is not that shape, and half a reference is none.
    expect(kindOf({ source: 'workspace' })).toBeNull();
    expect(kindOf({ kind: 'knight', sha256: 'a'.repeat(64) })).toBeNull();
    expect(isMadeKind(kindOf(made)!)).toBe(true);
    expect(isMadeKind(kindOf(shipped)!)).toBe(false);
  });

  it('is kept and asked for by what names it', () => {
    expect(kindKey(shipped)).toBe(`knight/2/${'a'.repeat(64)}`);
    expect(kindKey(made)).toBe(`workspace/${'d'.repeat(64)}`);
    expect(sameKind(made, { source: 'workspace', sha256: 'd'.repeat(64) })).toBe(true);
    expect(sameKind(made, shipped)).toBe(false);
    // The library is asked for a shipped kind by key, version and digest, a kept one by its digest.
    expect(libraryKind(shipped)).toEqual({ key: 'knight', version: 2, sha256: 'a'.repeat(64) });
    expect(libraryKind(made)).toEqual({ source: 'workspace', sha256: 'd'.repeat(64) });
  });
});

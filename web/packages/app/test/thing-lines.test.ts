// The lines beings say, as the drawing reads them from the society of things' said events
// (docs/synthetic-society-contract.md): what a line is, which are new, and who said it to whom in words.
import { describe, expect, it } from 'vitest';
import type { SocietyEvent } from '../src/society-api.js';
import { LineWatch, saidLine, thingLine } from '../src/composition/thing-lines.js';
import { AN_AI_MODEL } from '../src/composition/thing-marks.js';

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const SPIRIT = { kind: 'lantern_spirit', version: 1, sha256: 'b'.repeat(64) };
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

let seq = 0;
function event(kind: string, subject: string, tick: number, thing: Record<string, unknown>): SocietyEvent {
  seq += 1;
  return {
    event_id: `event-${String(seq).padStart(3, '0')}`, subject_id: subject, tick, event_kind: kind, document_sha256: 'e'.repeat(64),
    document: { synthetic: true, summary: 'said (simulated)', thing },
  } as SocietyEvent;
}
const said = (subject: string, tick: number, line: string, extra: Record<string, unknown> = {}) => event('said', subject, tick, {
  line, to: null, to_kind: null, to_number: null, from_kind: KNIGHT, from_number: 1, heard_by: [], decider: 'model', ...extra,
});

describe('saidLine', () => {
  it('reads a said event\'s line, its decider, its model where named, and who it was said to', () => {
    const line = saidLine(said('knight-0', 3, 'Who goes there?', {
      to: 'spirit-0', to_kind: SPIRIT, to_number: 2, model: { provider: 'nebius', model_id: QWEN.modelId },
    }))!;
    expect(line).toMatchObject({
      speakerId: 'knight-0', tick: 3, text: 'Who goes there?', decider: 'model',
      model: { provider: 'nebius', modelId: QWEN.modelId },
      from: { kind: KNIGHT, number: 1 }, to: { kind: SPIRIT, number: 2 },
    });
  });

  it('reads nothing from another event, an empty line or a decider it does not know', () => {
    expect(saidLine(event('thing_arrived', 'v', 1, { line: 'hi', decider: 'model' }))).toBeNull();
    expect(saidLine(said('k', 1, '   '))).toBeNull();
    expect(saidLine(said('k', 1, 'hi', { decider: 'routine' }))).toBeNull();
  });
});

describe('a line a person said while playing a being', () => {
  it('is read with its decider, names no model, and is said to be a person\'s', () => {
    const line = saidLine(said('knight-0', 4, 'Could I borrow your sword?', { decider: 'person' }))!;
    expect(line).toMatchObject({ speakerId: 'knight-0', decider: 'person', model: null });
    const drawn = thingLine(line, { running: QWEN, played: { byYou: true } }, {
      kindLabel: (kind) => (kind.kind === 'knight' ? 'knight' : null), countOf: () => 1,
    });
    // The words agreed with lane UI: "<label> · played by a person", the Person pill, never "You".
    expect(drawn).toEqual({
      subjectId: 'knight-0', text: 'Could I borrow your sword?', header: 'knight · played by a person',
      mark: { kind: 'person', mine: false, label: 'Person', full: 'Played by a person' }, spoken: 'Played by a person',
    });
  });
});

describe('LineWatch', () => {
  it('draws nothing said before the first read, each new line once, oldest first, and starts again after a reset', () => {
    const watch = new LineWatch();
    const before = said('knight-0', 1, 'Old.');
    expect(watch.take('society', [before])).toEqual([]);
    const later = said('knight-0', 3, 'Later.');
    const earlier = said('spirit-0', 2, 'Earlier.');
    const other = event('thing_arrived', 'v', 2, {});
    expect(watch.take('society', [before, later, earlier, other]).map((line) => line.text)).toEqual(['Earlier.', 'Later.']);
    expect(watch.take('society', [before, later, earlier, other])).toEqual([]);
    // Another society is a first read again.
    expect(watch.take('other', [said('x', 4, 'Elsewhere.')])).toEqual([]);
    watch.reset();
    expect(watch.take('other', [said('x', 5, 'After reset.')])).toEqual([]);
  });
});

describe('thingLine', () => {
  const words = (counts: Record<string, number>) => ({
    kindLabel: (kind: { kind?: string | undefined }) => (kind.kind === 'knight' ? 'knight' : kind.kind === 'lantern_spirit' ? 'lantern spirit' : null),
    countOf: (kind: { kind?: string | undefined }) => counts[kind.kind ?? ''] ?? 0,
    modelName: (model: { provider: string; modelId: string }) => (model.modelId === QWEN.modelId ? QWEN : null),
  });

  it('says who said it to whom, numbering a kind only where more than one is drawn, and names the model its event names', () => {
    const line = saidLine(said('knight-0', 3, 'Who goes there?', {
      from_number: 2, to: 'spirit-0', to_kind: SPIRIT, to_number: 1, model: { provider: 'nebius', model_id: QWEN.modelId },
    }))!;
    const drawn = thingLine(line, null, words({ knight: 2, lantern_spirit: 1 }));
    expect(drawn).toEqual({
      subjectId: 'knight-0', text: 'Who goes there?', header: 'knight 2 to lantern spirit · Qwen3 235B Instruct',
      mark: { kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' }, spoken: 'run by an AI model, Qwen3 235B Instruct',
    });
  });

  it('says someone where the library names no kind, and names no model a page has not read', () => {
    const line = saidLine(said('x-0', 3, 'Hello.', { from_kind: { kind: 'unknown', version: 1, sha256: 'c'.repeat(64) }, model: { provider: 'p', model_id: 'm' } }))!;
    const drawn = thingLine(line, null, words({}));
    expect(drawn.header).toBe('someone');
    expect(drawn.mark).toBe(AN_AI_MODEL);
  });

  it('reads a line said by or to a being of a kind its workspace keeps, named by digest alone', () => {
    // As the society records it for a creature drafted from words: no key and no version.
    const made = { source: 'workspace', sha256: 'd'.repeat(64) };
    const line = saidLine(said('creature-0', 5, 'Who are you?', { from_kind: made, from_number: 3, to: 'knight-0', to_kind: KNIGHT, to_number: 1 }))!;
    expect(line.from).toEqual({ kind: made, number: 3 });
    // The page names it as its maker did once the workspace's store answers, and "someone" until then.
    const labels = (kind: { kind?: string | undefined; source?: string | undefined; sha256: string }) =>
      (kind.source === 'workspace' && kind.sha256 === made.sha256 ? 'street dragon' : kind.kind === 'knight' ? 'knight' : null);
    const named = thingLine(line, null, { kindLabel: labels, countOf: () => 1, modelName: () => null });
    expect(named.header.startsWith('street dragon to knight')).toBe(true);
    const unread = thingLine(line, null, { kindLabel: (kind) => (kind.kind === 'knight' ? 'knight' : null), countOf: () => 1, modelName: () => null });
    expect(unread.header.startsWith('someone to knight')).toBe(true);
  });
});

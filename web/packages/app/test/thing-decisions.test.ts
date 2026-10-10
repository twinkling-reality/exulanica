import { describe, expect, it } from 'vitest';
import { DecisionWatch, deciderCounts, statedIndoors } from '../src/composition/thing-decisions.js';
import type { PersonDecision } from '../src/society-models-api.js';
import { decisionLineWords } from '../src/ui/society-models.js';

/*
 * The line that opens under a decider's name: what was chosen and what came of it, from a being's
 * latest decision as the models read serves it. Decisions here are written by hand in the read's
 * own shape.
 */
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };
const decided = (subjectId: string, seq: number, extra: Partial<PersonDecision> = {}): PersonDecision => ({
  ...QWEN, subjectId, decisionSeq: seq, baseTick: seq, consumedTick: null, status: 'accepted', reason: 'accepted',
  disposition: null, dispositionReason: null, chose: 'walk to the well', ...extra,
});

describe('what a decision line says', () => {
  it('says what was chosen once a minute has taken it up, and nothing before', () => {
    expect(decisionLineWords(decided('knight', 1))).toBeNull();
    expect(decisionLineWords(decided('knight', 1, { consumedTick: 2, disposition: 'applied' }))).toBe('Chose “walk to the well”.');
    // A decision that names no action still says a choice was made.
    expect(decisionLineWords(decided('knight', 1, { consumedTick: 2, disposition: 'applied', chose: null }))).toBe('Chose “an action”.');
  });

  it('says a choice the minute did not act on, why by its code\'s words, and who decided instead', () => {
    const late = decisionLineWords(decided('knight', 1, { consumedTick: 2, disposition: 'superseded', dispositionReason: 'superseded' }))!;
    expect(late).toMatch(/^Chose “walk to the well”, but .+, and that came first\.$/u);
    const refused = decisionLineWords(decided('knight', 1, { consumedTick: 2, disposition: 'not_applied', dispositionReason: 'option_not_offered' }))!;
    expect(refused).toMatch(/^Chose “walk to the well”, but .+, so its routine decided\.$/u);
    const unfollowed = decisionLineWords(decided('knight', 1, { status: 'rejected', reason: 'stale_state' }))!;
    expect(unfollowed).toMatch(/^Not followed: .+\. Its routine decided\.$/u);
    // It never says why the decider chose as it did: a decision records no reason of its decider\'s.
    for (const words of [late, refused, unfollowed]) expect(words).not.toMatch(/because it|it said|reason:/iu);
  });
});

describe('the decisions opened since the page first read a society', () => {
  it('opens nothing on the first read, each later decision once when a minute takes it up, oldest first', () => {
    const watch = new DecisionWatch();
    // Before the visit: one acted on, one still waiting for its minute.
    expect(watch.take('society', [decided('knight', 4, { consumedTick: 5, disposition: 'applied' }), decided('spirit', 5)])).toEqual([]);
    // The same read again opens nothing.
    expect(watch.take('society', [decided('knight', 4, { consumedTick: 5, disposition: 'applied' }), decided('spirit', 5)])).toEqual([]);
    // The spirit's waiting decision is taken up, and the knight has a newer one that a minute acted on.
    const opened = watch.take('society', [
      decided('knight', 7, { consumedTick: 8, disposition: 'applied', chose: 'rest' }),
      decided('spirit', 5, { consumedTick: 6, disposition: 'applied', chose: 'give the lantern to the knight' }),
    ]);
    expect(opened).toEqual([
      { subjectId: 'spirit', chose: 'Chose “give the lantern to the knight”.', said: null },
      { subjectId: 'knight', chose: 'Chose “rest”.', said: null },
    ]);
    // Nothing new: nothing opens again.
    expect(watch.take('society', [
      decided('knight', 7, { consumedTick: 8, disposition: 'applied', chose: 'rest' }),
      decided('spirit', 5, { consumedTick: 6, disposition: 'applied', chose: 'give the lantern to the knight' }),
    ])).toEqual([]);
  });

  it('starts again for another society, and after it is reset', () => {
    const watch = new DecisionWatch();
    watch.take('first', [decided('knight', 1)]);
    // Another society's first read primes, however its decisions stand.
    expect(watch.take('second', [decided('knight', 9, { consumedTick: 10, disposition: 'applied' })])).toEqual([]);
    expect(watch.take('second', [decided('knight', 10, { consumedTick: 11, disposition: 'applied' })]).length).toBe(1);
    watch.reset();
    expect(watch.take('second', [decided('knight', 11, { consumedTick: 12, disposition: 'applied' })])).toEqual([]);
  });
});

describe('who decides for a society\'s beings, counted', () => {
  it('counts each being once by its decider, and those indoors whoever decides for them', () => {
    const model = { kind: 'ai' };
    const agent = { kind: 'ai', outside: true as const };
    const game = { kind: 'from' };
    const you = { kind: 'person', mine: true };
    const played = { kind: 'person', mine: false };
    expect(deciderCounts([
      { mark: model, indoors: false }, { mark: model, indoors: true }, { mark: agent, indoors: false },
      { mark: game, indoors: false }, { mark: you, indoors: false }, { mark: played, indoors: false },
      { mark: null, indoors: true }, { mark: null, indoors: true }, { mark: null, indoors: false },
    ])).toEqual({ models: 2, you: 1, played: 1, outside: 2, routine: 3, indoors: 3 });
    expect(deciderCounts([])).toEqual({ models: 0, you: 0, played: 0, outside: 0, routine: 0, indoors: 0 });
  });
});

describe('whether a being is indoors', () => {
  it('is what its own state says, in the shape its society states it, and the street where it says nothing', () => {
    // A living town's person, as the page reads them: stated beside their position.
    expect(statedIndoors({ id: 'a', indoors: true })).toBe(true);
    expect(statedIndoors({ id: 'a', indoors: false })).toBe(false);
    // A being of a society that records the day: stated in its place.
    expect(statedIndoors({ id: 'b', location: { node_id: 'home:1', edge: null, indoors: true } })).toBe(true);
    expect(statedIndoors({ id: 'b', location: { node_id: 'home:1', edge: null, indoors: false } })).toBe(false);
    // A being of a society of things today states no such thing: it is in the street.
    expect(statedIndoors({ id: 'c', location: { node_id: 'corner:0', edge: null } })).toBe(false);
    expect(statedIndoors({ id: 'c' })).toBe(false);
    // Only its own word counts: a truthy value that is not true is not a statement.
    expect(statedIndoors({ id: 'd', indoors: 'yes', location: { indoors: 1 } })).toBe(false);
    expect(statedIndoors(null)).toBe(false);
  });
});

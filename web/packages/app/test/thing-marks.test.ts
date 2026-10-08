// The mark: one decision for the card, the world and every line. Expected marks are the ones
// agreed with the drawing lane and the outside agents' card (a model asked: "AI" and the model's
// first word; a game's visitor: "from" its game, never said to be a person; an outside agent: AI in its own name;
// a bridge the door does not list: "from outside"; a routine being or an object: nothing).
import { describe, expect, it } from 'vitest';
import { AN_AI_MODEL, lineMarkOf, markLabel, markOf } from '../src/composition/thing-marks.js';

const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

describe('markOf', () => {
  it('marks a being a model is asked for as AI, short by the served name', () => {
    expect(markOf({ running: QWEN })).toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' });
  });

  it('marks nothing its own routine runs', () => {
    expect(markOf({ running: null })).toBeNull();
  });

  it('marks a visitor a game\'s program decides for by where it came from, never as AI and never as a person', () => {
    expect(markOf({ running: null, crossing: { bridge: 'blockgame' }, bridge: { label: 'Block Game', ai: false } }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' });
  });

  it('marks an outside agent as AI from outside, in its own name', () => {
    expect(markOf({
      running: null, crossing: { bridge: 'agents' }, bridge: { label: 'Agents', ai: true }, declared: { name: 'Scout' },
    })).toEqual({ kind: 'ai', short: 'Scout', full: 'An outside AI agent, Scout', outside: true });
  });

  it('never guesses for a bridge the door does not list here', () => {
    expect(markOf({ running: QWEN, crossing: { bridge: 'unknown' }, bridge: null }))
      .toEqual({ kind: 'from', label: 'from outside', full: 'Someone from outside this world' });
  });

  it('marks a visitor the world decides for by who decides here: its model, with where it came from', () => {
    const crossing = { bridge: 'blockgame', decided_by: 'world' as const };
    const game = { label: 'Block Game', ai: false };
    expect(markOf({ running: QWEN, crossing, bridge: game }))
      .toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct', from: 'Block Game' });
    // Its routine runs it while no model is asked: from where it came, run by this world, never said to be a person.
    expect(markOf({ running: null, crossing, bridge: game }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, run by this world' });
    // A bridge the door does not list here: from outside, still the world's to run.
    expect(markOf({ running: QWEN, crossing, bridge: null }))
      .toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct', from: 'outside' });
  });

  it('marks a visitor its own program decides for as before, said or not', () => {
    const game = { label: 'Block Game', ai: false };
    const playing = { kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' };
    expect(markOf({ running: QWEN, crossing: { bridge: 'blockgame', decided_by: 'program' }, bridge: game })).toEqual(playing);
    expect(markOf({ running: QWEN, crossing: { bridge: 'blockgame' }, bridge: game })).toEqual(playing);
  });

  it('says who runs it to a screen reader', () => {
    expect(markLabel({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct', from: 'Block Game' }))
      .toBe('run by an AI model, Qwen3 235B Instruct, from Block Game');
    expect(markLabel({ kind: 'from', label: 'from Block Game', full: 'From Block Game, run by this world' }))
      .toBe('From Block Game, run by this world');
    expect(markLabel({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' })).toBe('run by an AI model, Qwen3 235B Instruct');
    expect(markLabel({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' })).toBe('From Block Game, decided from outside');
  });
});

describe('lineMarkOf', () => {
  const game = { label: 'Block Game', ai: false };
  it('marks a model\'s line AI, naming only the model its record names', () => {
    expect(lineMarkOf({ decider: 'model', model: QWEN })).toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' });
    // The speaker's model now is not evidence for an older line: no model on the record, none named.
    expect(lineMarkOf({ decider: 'model', model: null, speaker: { running: QWEN } })).toBe(AN_AI_MODEL);
    expect(markLabel(AN_AI_MODEL)).toBe('run by an AI model');
    expect(markLabel({ ...AN_AI_MODEL, from: 'Block Game' } as typeof AN_AI_MODEL)).toBe('run by an AI model, from Block Game');
  });

  it('keeps where a visitor the world runs came from on its model\'s line', () => {
    const speaker = { running: QWEN, crossing: { bridge: 'blockgame', decided_by: 'world' as const }, bridge: game };
    expect(lineMarkOf({ decider: 'model', model: QWEN, speaker }))
      .toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct', from: 'Block Game' });
    expect(lineMarkOf({ decider: 'model', speaker })).toEqual({ kind: 'ai', short: 'AI', full: 'an AI model', from: 'Block Game' });
  });

  it('marks an outside program\'s line by its speaker, from outside when the speaker is gone, and no line no event decides', () => {
    expect(lineMarkOf({ decider: 'external', speaker: { running: null, crossing: { bridge: 'blockgame' }, bridge: game } }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' });
    expect(lineMarkOf({ decider: 'external', speaker: null }))
      .toEqual({ kind: 'from', label: 'from outside', full: 'Someone from outside this world' });
    expect(lineMarkOf({ decider: null, model: QWEN })).toBeNull();
  });
});

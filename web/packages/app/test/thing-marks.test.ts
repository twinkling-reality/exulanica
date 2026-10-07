// The mark: one decision for the card, the world and every line. Expected marks are the ones
// agreed with the drawing lane and the outside agents' card (a model asked: "AI" and the model's
// first word; a person playing a game: "from" its game; an outside agent: AI in its own name;
// a bridge the door does not list: "from outside"; a routine being or an object: nothing).
import { describe, expect, it } from 'vitest';
import { markLabel, markOf } from '../src/composition/thing-marks.js';

const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

describe('markOf', () => {
  it('marks a being a model is asked for as AI, short by the served name', () => {
    expect(markOf({ running: QWEN })).toEqual({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' });
  });

  it('marks nothing its own routine runs', () => {
    expect(markOf({ running: null })).toBeNull();
  });

  it('marks a visitor a person plays from a game by where it came from, never as AI', () => {
    expect(markOf({ running: null, crossing: { bridge: 'blockgame' }, bridge: { label: 'Block Game', ai: false } }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'A person playing Block Game' });
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

  it('says who runs it to a screen reader', () => {
    expect(markLabel({ kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' })).toBe('run by an AI model, Qwen3 235B Instruct');
    expect(markLabel({ kind: 'from', label: 'from Block Game', full: 'A person playing Block Game' })).toBe('A person playing Block Game');
  });
});

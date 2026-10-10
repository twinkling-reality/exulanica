// The mark: one decision for the card, the world and every line. Expected marks are the ones
// agreed with the drawing lane and the outside agents' card (a model asked: "AI" and the model's
// whole served name; a game's visitor: "from" its game, never said to be a person; an outside agent: AI in its own name;
// a bridge the door does not list: "from outside"; a routine being or an object: nothing at rest,
// and its own routine while it is the picked one).
import { describe, expect, it } from 'vitest';
import { AN_AI_MODEL, ROUTINE_MARK, lineMarkOf, markLabel, markOf } from '../src/composition/thing-marks.js';

const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

describe('markOf', () => {
  it('marks a being a model is asked for as AI, by the model\'s whole served name', () => {
    expect(markOf({ running: QWEN })).toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' });
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
    })).toEqual({ kind: 'ai', name: 'Scout', full: 'An outside AI agent, Scout', outside: true });
  });

  it('never guesses for a bridge the door does not list here', () => {
    expect(markOf({ running: QWEN, crossing: { bridge: 'unknown' }, bridge: null }))
      .toEqual({ kind: 'from', label: 'from outside', full: 'Someone from outside this world' });
  });

  it('marks a visitor the world decides for by who decides here: its model, with where it came from', () => {
    const crossing = { bridge: 'blockgame', decided_by: 'world' as const };
    const game = { label: 'Block Game', ai: false };
    expect(markOf({ running: QWEN, crossing, bridge: game }))
      .toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'Block Game' });
    // Its routine runs it while no model is asked: from where it came, run by this world, never said to be a person.
    expect(markOf({ running: null, crossing, bridge: game }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, run by this world' });
    // A bridge the door does not list here: from outside, still the world's to run.
    expect(markOf({ running: QWEN, crossing, bridge: null }))
      .toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'outside' });
  });

  it('marks a visitor its own program decides for as before, said or not', () => {
    const game = { label: 'Block Game', ai: false };
    const playing = { kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' };
    expect(markOf({ running: QWEN, crossing: { bridge: 'blockgame', decided_by: 'program' }, bridge: game })).toEqual(playing);
    expect(markOf({ running: QWEN, crossing: { bridge: 'blockgame' }, bridge: game })).toEqual(playing);
  });

  it('names a model by its whole served name, never a part of it', () => {
    const long = { provider: 'nebius', modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super 120B' };
    expect(markOf({ running: long })).toEqual({ kind: 'ai', name: 'Nemotron 3 Super 120B', full: 'Nemotron 3 Super 120B' });
    expect(lineMarkOf({ decider: 'model', model: long })).toEqual({ kind: 'ai', name: 'Nemotron 3 Super 120B', full: 'Nemotron 3 Super 120B' });
  });

  it('gives a being its own routine decides for no mark, and one answer for when it is picked', () => {
    expect(markOf({ running: null })).toBeNull();
    // Worn only while picked, so it is never painted on everyone: it names no model and no person.
    expect(ROUTINE_MARK).toEqual({ kind: 'routine', label: 'Their own routine', full: 'Their own routine decides for them' });
  });

  it('says who runs it to a screen reader', () => {
    expect(markLabel({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'Block Game' }))
      .toBe('run by an AI model, Qwen3 235B Instruct, from Block Game');
    expect(markLabel({ kind: 'from', label: 'from Block Game', full: 'From Block Game, run by this world' }))
      .toBe('From Block Game, run by this world');
    expect(markLabel({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' })).toBe('run by an AI model, Qwen3 235B Instruct');
    expect(markLabel({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' })).toBe('From Block Game, decided from outside');
  });
});

describe('lineMarkOf', () => {
  const game = { label: 'Block Game', ai: false };
  it('marks a model\'s line AI, naming only the model its record names', () => {
    expect(lineMarkOf({ decider: 'model', model: QWEN })).toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' });
    // The speaker's model now is not evidence for an older line: no model on the record, none named.
    expect(lineMarkOf({ decider: 'model', model: null, speaker: { running: QWEN } })).toBe(AN_AI_MODEL);
    expect(markLabel(AN_AI_MODEL)).toBe('run by an AI model');
    expect(markLabel({ ...AN_AI_MODEL, from: 'Block Game' } as typeof AN_AI_MODEL)).toBe('run by an AI model, from Block Game');
  });

  it('keeps where a visitor the world runs came from on its model\'s line', () => {
    const speaker = { running: QWEN, crossing: { bridge: 'blockgame', decided_by: 'world' as const }, bridge: game };
    expect(lineMarkOf({ decider: 'model', model: QWEN, speaker }))
      .toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'Block Game' });
    expect(lineMarkOf({ decider: 'model', speaker })).toEqual({ kind: 'ai', name: 'AI', full: 'an AI model', from: 'Block Game' });
  });

  it('marks an outside program\'s line by its speaker, from outside when the speaker is gone, and no line no event decides', () => {
    expect(lineMarkOf({ decider: 'external', speaker: { running: null, crossing: { bridge: 'blockgame' }, bridge: game } }))
      .toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' });
    expect(lineMarkOf({ decider: 'external', speaker: null }))
      .toEqual({ kind: 'from', label: 'from outside', full: 'Someone from outside this world' });
    expect(lineMarkOf({ decider: null, model: QWEN })).toBeNull();
  });
});

// Play this one (deliveries/DRAW/design-play-this-one-marks.md, agreed with lane UI): "You" to the
// one playing, "Played" to anyone else, a person's line "Person", "played by a person", never "You".
describe('the person mark', () => {
  const crossing = { bridge: 'blockgame', decided_by: 'world' as const };
  const game = { label: 'Block Game', ai: false };

  it('marks a being the viewer plays You and one another person plays Played, over its mind', () => {
    expect(markOf({ running: QWEN, played: { byYou: true } })).toEqual({ kind: 'person', mine: true, label: 'You', full: 'Played by you' });
    expect(markOf({ running: QWEN, played: { byYou: false } }))
      .toEqual({ kind: 'person', mine: false, label: 'Played', full: 'Played by another person' });
    expect(markOf({ running: null, played: { byYou: true } })).toMatchObject({ kind: 'person', label: 'You' });
    // Given back: its mind's mark again.
    expect(markOf({ running: QWEN, played: null })).toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' });
  });

  it('keeps where a played visitor the world decides for came from, in the words a reader hears only', () => {
    const mark = markOf({ running: QWEN, crossing, bridge: game, played: { byYou: true } })!;
    expect(mark).toEqual({ kind: 'person', mine: true, label: 'You', full: 'Played by you', from: 'Block Game' });
    expect(markLabel(mark)).toBe('Played by you, from Block Game');
    expect(markLabel(markOf({ running: null, played: { byYou: false } })!)).toBe('Played by another person');
  });

  it('marks a person\'s line Person, played by a person, never You, keeping a world-decided visitor\'s origin', () => {
    const line = { kind: 'person', mine: false, label: 'Person', full: 'Played by a person' };
    expect(lineMarkOf({ decider: 'person', speaker: { running: QWEN, played: { byYou: true } } })).toEqual(line);
    expect(lineMarkOf({ decider: 'person', speaker: null })).toEqual(line);
    const visitor = lineMarkOf({ decider: 'person', speaker: { running: null, crossing, bridge: game, played: { byYou: true } } })!;
    expect(visitor).toEqual({ ...line, from: 'Block Game' });
    expect(markLabel(visitor)).toBe('Played by a person, from Block Game');
  });

  it('keeps a model\'s line an AI\'s, with where its speaker came from, while a person plays that speaker now', () => {
    const speaker = { running: QWEN, crossing, bridge: game, played: { byYou: true } };
    expect(lineMarkOf({ decider: 'model', model: QWEN, speaker }))
      .toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct', from: 'Block Game' });
  });
});

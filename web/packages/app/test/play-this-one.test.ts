// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { mountPlayThisOne, optionsFor } from '../src/composition/play-this-one.js';
import { parsePlayTurn, type PlayTurn } from '../src/society-play-api.js';

/**
 * Play this one: a person plays one being of a society of things from the world. The turn's
 * shape is THINGS 3p's (`GET .../society/play/{subject_id}/turn`, recorded in UI.txt 2026-10-09).
 */

const turnBody = (tick: number, extra: Record<string, unknown> = {}) => ({
  subject_id: 'knight', base_tick: tick, line_characters_maximum: 120, played: true, played_by_you: true,
  quiet_minutes: 5, quiet_left: 5, next_due_at: null, minute_ms: null,
  options: [
    { label: 'wait a moment', kind: 'wait', target_id: null, being_id: null, takes_line: false },
    { label: 'say something to everyone near', kind: 'say_all', target_id: null, being_id: null, takes_line: true },
    { label: 'walk to the well', kind: 'target', target_id: 'thing:well:visit', being_id: null, takes_line: false },
    { label: 'talk with the traveller', kind: 'talk', target_id: null, being_id: 'traveller', takes_line: false },
    { label: 'say something to the traveller', kind: 'say_to', target_id: null, being_id: 'traveller', takes_line: true },
    { label: 'pick up the sword', kind: 'pick_up', target_id: 'sword', being_id: null, takes_line: false },
  ],
  ...extra,
});

function harness(turns: unknown[], answer: (label: string, line: string | null) => Promise<unknown> = async () => ({ base_tick: 3, answer_seq: 1 })) {
  const queue = [...turns];
  const client = {
    start: vi.fn(async () => undefined),
    giveBack: vi.fn(async () => undefined),
    turn: vi.fn(async (): Promise<PlayTurn> => parsePlayTurn(queue.length > 1 ? queue.shift() : queue[0])),
    answer: vi.fn(async (_v: string, _s: string, baseTick: number, label: string, line: string | null) => {
      const body = await answer(label, line) as { base_tick: number; answer_seq: number };
      return { baseTick: body.base_tick ?? baseTick, answerSeq: body.answer_seq ?? 1 };
    }),
  };
  const refreshModels = vi.fn(async () => undefined);
  const play = mountPlayThisOne({
    client, versionId: () => 'version', refreshModels,
    nameOf: (id) => ({ knight: 'Knight', traveller: 'Traveller' } as Record<string, string>)[id] ?? 'them',
    every: () => () => undefined,
  });
  document.body.replaceChildren(play.band.root);
  return { play, client, refreshModels, band: play.band.root };
}

const settle = async () => { for (let i = 0; i < 10; i += 1) await Promise.resolve(); };
const text = (root: Element, selector: string) => root.querySelector(selector)?.textContent ?? '';

describe('playing one being from the world', () => {
  it('names what a click acts on: the being involved, or the thing or place acted on', () => {
    const turn = parsePlayTurn(turnBody(3));
    expect(optionsFor(turn, { subjectId: 'traveller', thingId: null }).map((o) => o.kind)).toEqual(['talk', 'say_to']);
    expect(optionsFor(turn, { subjectId: null, thingId: 'well' }).map((o) => o.kind)).toEqual(['target']);
    expect(optionsFor(turn, { subjectId: null, thingId: 'sword' }).map((o) => o.kind)).toEqual(['pick_up']);
    expect(optionsFor(turn, { subjectId: null, thingId: 'bench' })).toEqual([]);
  });

  it('starts, shows whom they play, and answers a click that names one option for the next minute', async () => {
    const { play, client, refreshModels, band } = harness([turnBody(3)]);
    await play.play('knight');
    expect(client.start).toHaveBeenCalledWith('version', 'knight');
    expect(refreshModels).toHaveBeenCalled();
    expect(text(band, '.play-band-title')).toBe('You are playing Knight');
    expect(text(band, '.play-band-when')).toBe('Minute 3 · paused: play the world or move it on a minute');
    // Options that act on nothing in the world are the band's own buttons.
    expect([...band.querySelectorAll('.play-band-loose .play-band-option')].map((b) => b.textContent))
      .toEqual(['wait a moment', 'say something to everyone near']);
    expect(play.onPick({ subjectId: null, thingId: 'well' })).toBe(true);
    await settle();
    expect(client.answer).toHaveBeenCalledWith('version', 'knight', 3, 'walk to the well', null);
    expect(text(band, '.play-band-chosen')).toBe('At the next minute: walk to the well');
  });

  it('asks which, and for the line, where a click offers more than one thing', async () => {
    const { play, client, band } = harness([turnBody(3)]);
    await play.play('knight');
    play.onPick({ subjectId: 'traveller', thingId: null });
    expect([...band.querySelectorAll('.play-band-asking .play-band-option')].map((b) => b.textContent))
      .toEqual(['talk with the traveller', 'say something to the traveller']);
    (band.querySelectorAll('.play-band-asking .play-band-option')[1] as HTMLButtonElement).click();
    const field = band.querySelector<HTMLInputElement>('.play-band-line')!;
    expect(field.placeholder).toBe('Say to Traveller');
    field.value = '  Well met.  ';
    field.dispatchEvent(new Event('input'));
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    expect(client.answer).toHaveBeenCalledWith('version', 'knight', 3, 'say something to the traveller', 'Well met.');
    // Said: the panel closes and the keys go back to the world, so G gives it back.
    expect(band.querySelector('.play-band-line')).toBeNull();
    expect(band.contains(document.activeElement)).toBe(false);
  });

  it('says an answer the minute already holds is taken, and does not send it again', async () => {
    const { play, client, band } = harness([turnBody(3)], async () => {
      throw new ApiError(409, 'minute_passed', 'the minute has this answer', { current_tick: 3 });
    });
    await play.play('knight');
    play.onPick({ subjectId: null, thingId: 'sword' });
    await settle();
    expect(client.answer).toHaveBeenCalledTimes(1);
    expect(client.turn).toHaveBeenCalledTimes(1);
    expect(text(band, '.play-band-status')).toBe('Taken: it happens at the next minute.');
  });

  it('gives it back on G, and says the being\'s own mind decides again', async () => {
    const { play, client, refreshModels, band } = harness([turnBody(3)]);
    await play.play('knight');
    refreshModels.mockClear();
    play.toggle(null);
    await settle();
    expect(client.giveBack).toHaveBeenCalledWith('version', 'knight');
    expect(refreshModels).toHaveBeenCalled();
    expect(text(band, '.play-band-title')).toBe('You gave Knight back. Its own mind decides again from the next minute.');
    expect(play.playing()).toBeNull();
    // Once not playing, a click opens what it would have opened.
    expect(play.onPick({ subjectId: 'traveller', thingId: null })).toBe(false);
  });

  it('ends playing when a read says the being is no longer theirs (the host gave it back after quiet minutes)', async () => {
    const { play, band } = harness([turnBody(3), turnBody(4, { played: false, played_by_you: false })]);
    await play.play('knight');
    play.minuteMoved();
    await settle();
    expect(text(band, '.play-band-title')).toBe('You are no longer playing Knight: its own mind decides again.');
    expect(play.playing()).toBeNull();
  });
});

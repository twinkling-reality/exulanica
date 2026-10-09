// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { mountPlayThisOne, optionsFor, walkOption } from '../src/composition/play-this-one.js';
import { parsePlayTurn, type PlayTurn } from '../src/society-play-api.js';

/**
 * Play this one: a person plays one being of a society of things from the world. The turn's
 * shape is THINGS 3p's (`GET .../society/play/{subject_id}/turn`, recorded in UI.txt 2026-10-09), with
 * 3p.1's walk to a spot the person chooses (`takes_point`, answered with `point: [x_mm, z_mm]`).
 */

const option = (label: string, kind: string, target: string | null, being: string | null, line = false, point = false) => ({
  label, kind, target_id: target, being_id: being, takes_line: line, takes_point: point,
});
const WALK = option('walk to a spot you choose', 'point', null, null, false, true);
const turnBody = (tick: number, extra: Record<string, unknown> = {}) => ({
  subject_id: 'knight', base_tick: tick, line_characters_maximum: 120, played: true, played_by_you: true,
  quiet_minutes: 5, quiet_left: 5, next_due_at: null, minute_ms: null,
  options: [
    option('wait a moment', 'wait', null, null),
    option('say something to everyone near', 'say_all', null, null, true),
    option('walk to the well', 'target', 'thing:well:visit', null),
    option('talk with the traveller', 'talk', null, 'traveller'),
    option('say something to the traveller', 'say_to', null, 'traveller', true),
    option('pick up the sword', 'pick_up', 'sword', null),
    WALK,
  ],
  ...extra,
});

function harness(
  turns: unknown[],
  answer: (label: string, line: string | null) => Promise<unknown> = async () => ({ base_tick: 3, answer_seq: 1 }),
  now: () => number = () => 0,
) {
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
  const showDestination = vi.fn();
  const play = mountPlayThisOne({
    client, versionId: () => 'version', refreshModels, showDestination, now,
    nameOf: (id) => ({ knight: 'Knight', traveller: 'Traveller' } as Record<string, string>)[id] ?? 'them',
    every: () => () => undefined,
  });
  document.body.replaceChildren(play.band.root);
  return { play, client, refreshModels, showDestination, band: play.band.root };
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
    expect(client.answer).toHaveBeenCalledWith('version', 'knight', 3, 'walk to the well', null, null);
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
    expect(client.answer).toHaveBeenCalledWith('version', 'knight', 3, 'say something to the traveller', 'Well met.', null);
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

  it('walks to a spot clicked on open ground, rings it, and clears the ring when that minute is drawn', async () => {
    const { play, client, showDestination, band } = harness([turnBody(3), turnBody(4)]);
    await play.play('knight');
    expect(text(band, '.play-band-chosen')).toBe('Click someone or something in the world to act on it, or open ground to walk there.');
    // The walk is no button and no click on a being or thing matches it.
    expect([...band.querySelectorAll('.play-band-option')].map((b) => b.textContent)).not.toContain(WALK.label);
    const turn = parsePlayTurn(turnBody(3));
    expect(walkOption(turn)?.label).toBe(WALK.label);
    expect(optionsFor(turn, { subjectId: null, thingId: 'well' }).map((o) => o.kind)).toEqual(['target']);
    expect(play.onGround({ xMm: 1200, zMm: -800 })).toBe(true);
    await settle();
    expect(client.answer).toHaveBeenLastCalledWith('version', 'knight', 3, WALK.label, null, { xMm: 1200, zMm: -800 });
    expect(showDestination).toHaveBeenLastCalledWith({ xMm: 1200, zMm: -800 });
    expect(text(band, '.play-band-chosen')).toBe('At the next minute: walk to a spot you choose');
    // Another choice before the minute replaces the walk, and its ring.
    play.onPick({ subjectId: null, thingId: 'sword' });
    await settle();
    expect(showDestination).toHaveBeenLastCalledWith(null);
    play.onGround({ xMm: 500, zMm: 500 });
    await settle();
    play.minuteMoved();
    await settle();
    expect(showDestination).toHaveBeenLastCalledWith(null);
    expect(text(band, '.play-band-chosen')).toBe('Click someone or something in the world to act on it, or open ground to walk there.');
  });

  it('leaves a click on the ground to looking around where the minute offers no walk, or it met no ground', async () => {
    const { play, client } = harness([turnBody(3, { options: [option('wait a moment', 'wait', null, null)] })]);
    expect(play.onGround({ xMm: 0, zMm: 0 })).toBe(false);
    await play.play('knight');
    expect(play.onGround({ xMm: 0, zMm: 0 })).toBe(false);
    expect(play.onGround(null)).toBe(false);
    expect(play.onPick({ subjectId: null, thingId: null })).toBe(false);
    expect(client.answer).not.toHaveBeenCalled();
  });

  it('says where nobody walks, and when more answers are taken again, in plain words', async () => {
    const refusals = [
      new ApiError(422, 'not_walkable', 'the point is not on the ground anybody walks'),
      new ApiError(429, 'too_many_answers', 'too many answers this minute'),
    ];
    const due = new Date(60_000).toISOString();
    const { play, showDestination, band } = harness([turnBody(3, { next_due_at: due, minute_ms: 8000 })], async () => { throw refusals.shift()!; }, () => 53_500);
    await play.play('knight');
    play.onGround({ xMm: 90_000, zMm: 0 });
    await settle();
    expect(text(band, '.play-band-status')).toBe('Nobody walks there. Click open ground nearer the paths.');
    expect(showDestination).not.toHaveBeenCalledWith({ xMm: 90_000, zMm: 0 });
    play.onPick({ subjectId: null, thingId: 'sword' });
    await settle();
    expect(text(band, '.play-band-status')).toBe('That is as many choices as one minute takes. Choose again in 7 s.');
  });

  it('says under the pointer what a click there would do, and nothing once not playing', async () => {
    const { play, band } = harness([turnBody(3), turnBody(4)]);
    play.hover({ subjectId: 'traveller', thingId: null }, false);
    expect(text(band, '.play-band-hint')).toBe('');
    await play.play('knight');
    play.hover({ subjectId: null, thingId: 'sword' }, false);
    expect(text(band, '.play-band-hint')).toBe('Click to pick up the sword');
    play.hover({ subjectId: 'traveller', thingId: null }, false);
    expect(text(band, '.play-band-hint')).toBe('Click to choose: talk with the traveller, say something to the traveller');
    play.hover({ subjectId: null, thingId: 'bench' }, false);
    expect(text(band, '.play-band-hint')).toBe('Nothing to do with that this minute.');
    play.hover({ subjectId: 'knight', thingId: null }, false);
    expect(text(band, '.play-band-hint')).toBe('You are playing Knight');
    play.hover(null, true);
    expect(text(band, '.play-band-hint')).toBe('Click to walk here');
    play.hover(null, false);
    expect(text(band, '.play-band-hint')).toBe('');
    // A new minute may offer no walk: the hint is said again only as the pointer moves.
    play.hover(null, true);
    play.minuteMoved();
    await settle();
    expect(text(band, '.play-band-hint')).toBe('');
  });

  it('holds where the band ends on the shell while it shows, so toasts start below it', async () => {
    const { play, band } = harness([turnBody(3)]);
    await play.play('knight');
    expect(document.body.style.getPropertyValue('--play-band-bottom')).toMatch(/^\d+px$/u);
    play.band.hide();
    expect(document.body.style.getPropertyValue('--play-band-bottom')).toBe('');
    expect(band.hidden).toBe(true);
  });
});

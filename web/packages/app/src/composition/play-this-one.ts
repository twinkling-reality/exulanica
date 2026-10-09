/**
 * Play this one: a person plays one being of a society of things (THINGS 3p) from the world itself.
 *
 * Starting records the person as the being's decider; the turn read (`GET .../play/{id}/turn`)
 * gives the options for the next minute, read again whenever the world's minute moves. A click on
 * someone or something in the world is offered here first (`onPick`): it acts on the options that
 * name what was clicked (another being by `beingId`; a thing or a place by `targetId`), at once where
 * one option without a line matches, else through the band's small panel. Options that name nothing
 * clickable are the band's own buttons. An answer counts for the minute it names; a later one before
 * that minute replaces it. A 409 `minute_passed` whose `current_tick` is the minute answered means the
 * answer was taken and the minute has not run yet: said so, never sent again. Giving it back, or the
 * server giving it back after its quiet minutes, ends the band with a sentence saying so.
 */

import { ApiError } from '@exulanica/graph-client';
import type { PlayOption, PlayTurn, SocietyPlayClient } from '../society-play-api.js';
import { buildPlayBand, PLAY_WORDS, type PlayBand } from '../ui/play-this-one.js';
import { choiceRefusalWords } from '../ui/society-models.js';

/** Kinds that act on nothing a person can click in the world: the band's own buttons. */
const LOOSE_KINDS: ReadonlySet<string> = new Set(['wait', 'stand', 'carry_on', 'say_all', 'leave']);

/** Why an answer was not taken, by the answer route's codes. */
export const ANSWER_REFUSAL_WORDS: Readonly<Record<string, string>> = Object.freeze({
  label_not_offered: 'That is no longer offered this minute. Choose again.',
  line_needed: 'That needs something to say. Type it, then press Enter.',
  line_not_taken: 'That takes no words. Choose it again without any.',
  line_out_of_bounds: 'That is longer than a line can be here. Say it in fewer words.',
  line_refused_by_rules: 'That line cannot be said in this world. Say it another way.',
  too_many_answers: 'That is as many choices as one minute takes. Wait for the next minute.',
  not_played: 'You are not playing this being any more.',
});

const TAKEN = 'Taken: it happens at the next minute.';
const MINUTE_MOVED = 'That minute has passed. Choose again for this one.';
const NOTHING_HERE = 'Nothing to do with {name} this minute.';
/** How long the band's last sentence stays once playing ended. */
const LAST_WORDS_MS = 8000;

const fill = (words: string, values: Readonly<Record<string, string | number>>): string =>
  words.replace(/\{(\w+)\}/gu, (all, key: string) => (key in values ? String(values[key]) : all));

/** What a click in the world picked: a being, or a thing (by its society id). */
export interface PlayPick {
  readonly subjectId: string | null;
  readonly thingId: string | null;
}

/** The options a click names: the being they involve, or the thing or place they act on. */
export function optionsFor(turn: PlayTurn, pick: PlayPick): readonly PlayOption[] {
  return turn.options.filter((option) => {
    if (LOOSE_KINDS.has(option.kind)) return false;
    if (pick.subjectId !== null && option.beingId === pick.subjectId) return true;
    if (pick.thingId === null || option.targetId === null) return false;
    // A place is named by the thing it belongs to and the activity there (`thing:well:visit`).
    return option.targetId === pick.thingId || option.targetId.startsWith(`thing:${pick.thingId}:`);
  });
}

export interface MountedPlayThisOne {
  readonly band: PlayBand;
  /** Who is played from this page, or null. */
  playing(): string | null;
  play(subjectId: string): Promise<void>;
  /**
   * Take up again a being the server says this person plays (a reload, a second tab): the band and
   * the turn, with no new start.
   */
  resume(subjectId: string): Promise<void>;
  giveBack(): Promise<void>;
  /** G: give back while playing, else play the one chosen in the world, if any. */
  toggle(selected: string | null): void;
  /** A click in the world while playing: true where it was taken here (no card opens). */
  onPick(pick: PlayPick): boolean;
  /** The world's minute moved: read the turn again. */
  minuteMoved(): void;
  dispose(): void;
}

export function mountPlayThisOne(deps: {
  readonly client: Pick<SocietyPlayClient, 'start' | 'giveBack' | 'turn' | 'answer'>;
  readonly versionId: () => string | null;
  readonly nameOf: (subjectId: string) => string;
  /** Read who decides again, so the marks and Who decides show the person at once. */
  readonly refreshModels: () => Promise<void>;
  readonly now?: () => number;
  /** Run `tick` every second while playing; returns the stop. Tests pass their own. */
  readonly every?: (tick: () => void, ms: number) => () => void;
}): MountedPlayThisOne {
  const now = deps.now ?? (() => Date.now());
  const every = deps.every ?? ((tick: () => void, ms: number) => {
    const timer = window.setInterval(tick, ms);
    return () => window.clearInterval(timer);
  });
  let subject: string | null = null;
  let turn: PlayTurn | null = null;
  let chosen: string | null = null;
  let status: string | null = null;
  let asking: { readonly name: string; readonly options: readonly PlayOption[] } | null = null;
  let stopTicking: (() => void) | null = null;
  let reading = false;
  let lastWords: number | null = null;

  const nextIn = (): number | null => {
    if (turn?.nextDueAt == null) return null;
    return Math.max(0, Math.ceil((Date.parse(turn.nextDueAt) - now()) / 1000));
  };

  const render = (keepFields = true): void => {
    if (subject === null || turn === null) return;
    band.show({
      keepFields,
      name: deps.nameOf(subject),
      minute: turn.baseTick,
      nextInSeconds: nextIn(),
      chosen,
      status,
      loose: turn.options.filter((option) => LOOSE_KINDS.has(option.kind)),
      asking,
      lineCharactersMaximum: turn.lineCharactersMaximum,
    });
  };

  const end = (words: string): void => {
    stopTicking?.();
    stopTicking = null;
    subject = null;
    turn = null;
    chosen = null;
    status = null;
    asking = null;
    band.say(words);
    if (lastWords !== null) window.clearTimeout(lastWords);
    lastWords = window.setTimeout(() => { lastWords = null; if (subject === null) band.hide(); }, LAST_WORDS_MS);
  };

  const read = async (): Promise<void> => {
    const version = deps.versionId();
    if (subject === null || version === null || reading) return;
    reading = true;
    const playing = subject;
    try {
      const next = await deps.client.turn(version, playing);
      if (subject !== playing) return;
      if (!next.played || !next.playedByYou) {
        end(fill(PLAY_WORDS.stopped, { name: deps.nameOf(playing) }));
        await deps.refreshModels();
        return;
      }
      // A new minute clears what was chosen for the last one.
      const newMinute = turn === null || next.baseTick !== turn.baseTick;
      if (newMinute) { chosen = null; status = null; asking = null; }
      turn = next;
      render(!newMinute);
    } catch (error) {
      if (subject === playing) {
        status = error instanceof ApiError && error.code === 'person_not_in_this_world'
          ? 'This being is no longer in this world.' : 'The minute could not be read. It is asked again at the next one.';
        render();
      }
    } finally {
      reading = false;
    }
  };

  const choose = async (option: PlayOption, line: string | null): Promise<void> => {
    const version = deps.versionId();
    if (subject === null || turn === null || version === null) return;
    const asked = turn.baseTick;
    try {
      await deps.client.answer(version, subject, asked, option.label, line);
      chosen = option.label;
      status = null;
      asking = null;
      render(false);
      return;
    } catch (error) {
      if (!(error instanceof ApiError)) { status = 'That was not sent. Try again.'; render(); return; }
      if (error.code === 'minute_passed') {
        // The minute has this being's answer and has not run yet: taken, not sent again.
        if (error.extensions['current_tick'] === asked) { status = TAKEN; render(); return; }
        status = MINUTE_MOVED;
        asking = null;
        await read();
        return;
      }
      if (error.code === 'not_played') { end(fill(PLAY_WORDS.stopped, { name: deps.nameOf(subject) })); await deps.refreshModels(); return; }
      status = ANSWER_REFUSAL_WORDS[error.code] ?? 'That was not taken. Choose again.';
    }
    render();
  };

  const band = buildPlayBand({
    onGiveBack: () => { void api.giveBack(); },
    onChoose: (option, line) => { void choose(option, line); },
    onCloseAsking: () => { asking = null; render(); },
  });

  const api: MountedPlayThisOne = {
    band,
    playing: () => subject,
    async play(subjectId) {
      const version = deps.versionId();
      if (version === null || subject !== null) return;
      band.say(fill(PLAY_WORDS.starting, { name: deps.nameOf(subjectId) }));
      try {
        await deps.client.start(version, subjectId);
      } catch (error) {
        band.say(error instanceof ApiError ? choiceRefusalWords(error.code, error.message) : 'Playing could not start. Try again.');
        return;
      }
      subject = subjectId;
      stopTicking = every(() => {
        if (turn !== null && nextIn() === 0) void read();
        render();
      }, 1000);
      await deps.refreshModels();
      await read();
    },
    async resume(subjectId) {
      if (subject !== null) return;
      subject = subjectId;
      stopTicking = every(() => {
        if (turn !== null && nextIn() === 0) void read();
        render();
      }, 1000);
      await read();
    },
    async giveBack() {
      const version = deps.versionId();
      const played = subject;
      if (version === null || played === null) return;
      try {
        await deps.client.giveBack(version, played);
      } catch (error) {
        if (!(error instanceof ApiError && error.code === 'not_played')) {
          status = 'It was not given back. Try again.';
          render();
          return;
        }
      }
      end(fill(PLAY_WORDS.givenBack, { name: deps.nameOf(played) }));
      await deps.refreshModels();
    },
    toggle(selected) {
      if (subject !== null) { void api.giveBack(); return; }
      if (selected !== null) void api.play(selected);
    },
    onPick(pick) {
      if (subject === null || turn === null) return false;
      // The played being itself: what it can do alone is in the band already.
      if (pick.subjectId === subject) return true;
      const offered = optionsFor(turn, pick);
      const name = pick.subjectId !== null ? deps.nameOf(pick.subjectId) : 'that';
      if (offered.length === 0) {
        status = fill(NOTHING_HERE, { name });
        asking = null;
      } else if (offered.length === 1 && !offered[0]!.takesLine) {
        void choose(offered[0]!, null);
        return true;
      } else {
        asking = { name, options: offered };
        status = null;
      }
      render();
      return true;
    },
    minuteMoved() { void read(); },
    dispose() {
      stopTicking?.();
      if (lastWords !== null) window.clearTimeout(lastWords);
      band.root.remove();
    },
  };
  return api;
}

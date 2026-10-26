// @vitest-environment happy-dom
// The world screen's corners (tools/previews/world-workspace/world-corners.ts): a world whose society
// keeps no time of day still has its clock, Playing or Paused, which P and a press play and pause; and a
// run on shows in the top pill in place of the people line, with Stop, then says why it ended.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Clock { society: 'present' | 'absent'; mode: 'paused' | 'playing' | null; minute: number | null; startMinuteOfDay: number | null; population: number | null; busy: boolean; waiting?: string | null }
interface Corners {
  frame(now: number): void;
  togglePlay(): void;
  hasClock(): boolean;
  run(state: { line: string; onStop: () => void } | null): void;
  runEnded(words: string): void;
  keysTaken(on: boolean): void;
  dispose(): void;
}
interface WorldCorners {
  mountCorners(options: { host: HTMLElement; people: { clock(): Clock; play(): Promise<void>; pause(): Promise<void> }; onLeave: () => void; title?: string }): Corners;
}
// A joined path: the test runner still finds the file, and the type checker leaves the preview module
// (outside this package) out of the program.
const corners = async (): Promise<WorldCorners> => import('../../../../tools/previews/world-workspace/' + 'world-corners.ts') as Promise<WorldCorners>;

afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

const clockOf = (host: HTMLElement) => [...host.querySelectorAll<HTMLButtonElement>('.wu-clock-pill')].find((one) => !one.hidden) ?? null;

describe('the clock of a world that keeps no time of day', () => {
  it('shows whether it plays, and P plays it', async () => {
    const { mountCorners } = await corners();
    const host = document.createElement('div');
    document.body.append(host);
    const state: Clock = { society: 'present', mode: 'paused', minute: null, startMinuteOfDay: null, population: 3, busy: false };
    const play = vi.fn(async () => { state.mode = 'playing'; });
    const made = mountCorners({ host, people: { clock: () => state, play, pause: vi.fn(async () => {}) }, onLeave: () => {}, title: 'A small town' });
    const clock = clockOf(host);
    expect(clock?.textContent).toBe('Paused');
    expect(made.hasClock()).toBe(true);
    made.togglePlay();
    await vi.waitFor(() => expect(play).toHaveBeenCalledOnce());
    made.frame(performance.now() + 1000);
    expect(clockOf(host)?.textContent).toBe('Playing');
    made.dispose();
  });

  it('shows the time where the world keeps one, and says in words, with no glyph, when it is paused (F2)', async () => {
    const { mountCorners } = await corners();
    const host = document.createElement('div');
    const state: Clock = { society: 'present', mode: 'paused', minute: 55, startMinuteOfDay: 360, population: 24, busy: false };
    mountCorners({ host, people: { clock: () => state, play: vi.fn(async () => {}), pause: vi.fn(async () => {}) }, onLeave: () => {} });
    expect(clockOf(host)?.textContent).toBe('06:55 · Day 1 · Paused');
    expect(clockOf(host)?.querySelector('i, .wu-pause, .wu-play')).toBeNull();
    const playing = document.createElement('div');
    mountCorners({ host: playing, people: { clock: () => ({ ...state, mode: 'playing' }), play: vi.fn(async () => {}), pause: vi.fn(async () => {}) }, onLeave: () => {} });
    expect(clockOf(playing)?.textContent).toBe('06:55 · Day 1');
  });
});

describe('a world set to play that this server does not advance', () => {
  // As the judges' server answers a ninth guest while eight towns play (host_playback_code guest_towns_full).
  const FULL = "Many visitors' worlds are playing on this server right now, so yours waits until one of them stops.";
  const line = (host: HTMLElement) => host.querySelector<HTMLElement>('.wu-clock-waiting');

  it('says why under its clock, and says nothing once it plays or its person pauses it', async () => {
    const { mountCorners } = await corners();
    const host = document.createElement('div');
    const state: Clock = { society: 'present', mode: 'playing', minute: 55, startMinuteOfDay: 360, population: 128, busy: false, waiting: FULL };
    const made = mountCorners({ host, people: { clock: () => state, play: vi.fn(async () => {}), pause: vi.fn(async () => {}) }, onLeave: () => {} });
    expect(clockOf(host)?.textContent).toBe('06:55 · Day 1');
    expect(line(host)?.hidden).toBe(false);
    expect(line(host)?.textContent).toBe(FULL);
    expect(line(host)?.getAttribute('role')).toBe('status');
    state.waiting = null;
    made.frame(performance.now() + 1000);
    expect(line(host)?.hidden).toBe(true);
    Object.assign(state, { mode: 'paused', waiting: FULL });
    made.frame(performance.now() + 2000);
    expect(line(host)?.hidden).toBe(true);
    made.dispose();
  });
});

describe('a run on, in the top pill', () => {
  it('takes the people line\'s place with its line and Stop, then says why it ended', async () => {
    const { mountCorners } = await corners();
    const host = document.createElement('div');
    const state: Clock = { society: 'present', mode: 'playing', minute: 55, startMinuteOfDay: 360, population: 24, busy: false };
    const made = mountCorners({ host, people: { clock: () => state, play: vi.fn(async () => {}), pause: vi.fn(async () => {}) }, onLeave: () => {}, title: 'Terraces on the bay' });
    const top = host.querySelector<HTMLElement>('.wu-top')!;
    expect(top.textContent).toContain('24 people live here');
    const stop = vi.fn();
    made.run({ line: "Teo's model is deciding · 9:13 left · $0.0011 of $0.05", onStop: stop });
    const run = top.querySelector<HTMLElement>('.wu-top-run')!;
    expect(run.hidden).toBe(false);
    expect(run.textContent).toBe("Teo's model is deciding · 9:13 left · $0.0011 of $0.05Stop");
    expect([...top.querySelectorAll<HTMLElement>('.wu-top-people')].filter((one) => !one.hidden && !run.contains(one))).toHaveLength(0);
    run.querySelector<HTMLButtonElement>('.wu-run-stop')!.click();
    expect(stop).toHaveBeenCalledOnce();
    made.run(null);
    made.runEnded('The run reached its time.');
    expect(run.hidden).toBe(true);
    expect(top.textContent).toContain('The run reached its time.');
    // After a while the people line returns.
    made.frame(performance.now() + 7000);
    expect(top.textContent).toContain('24 people live here');
  });
});

describe('the first hint while something else has the keys (V14)', () => {
  it('is out of sight while a list or question is open, or a field is typed in, and back after', async () => {
    const { mountCorners } = await corners();
    const host = document.createElement('div');
    document.body.append(host);
    const state: Clock = { society: 'present', mode: 'paused', minute: null, startMinuteOfDay: null, population: 3, busy: false };
    const made = mountCorners({ host, people: { clock: () => state, play: vi.fn(async () => {}), pause: vi.fn(async () => {}) }, onLeave: () => {} });
    const hint = host.querySelector('.wu-first-hint') as HTMLElement;
    const shown = () => !hint.hidden && hint.style.visibility !== 'hidden';
    made.frame(performance.now());
    expect(shown()).toBe(true);
    // The chosen person's model list or Run question open.
    made.keysTaken(true);
    made.frame(performance.now());
    expect(shown()).toBe(false);
    made.keysTaken(false);
    made.frame(performance.now());
    expect(shown()).toBe(true);
    // A field typed in: Create's line, a creature's words, Ask.
    const field = document.createElement('textarea');
    document.body.append(field);
    field.focus();
    made.frame(performance.now());
    expect(shown()).toBe(false);
    field.blur();
    made.frame(performance.now());
    expect(shown()).toBe(true);
    made.dispose();
  });
});

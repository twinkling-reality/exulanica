import { describe, expect, it } from 'vitest';
import { FRAME_GOVERNOR_RULES, FrameGovernor, type FrameSample } from '../src/frame-governor.js';

/*
 * The governor reads a computer's frames, never its hardware: a steady machine stays at full
 * quality at any refresh rate; a machine whose graphics fall behind steps down, one level at a time;
 * a busy main thread with idle graphics never makes the drawing lighter; a hidden tab, a pause and
 * the first seconds after a load are not judged; and with stepping off nothing changes at all.
 */

interface Frame { readonly intervalMs: number; readonly graphicsMs?: number | null; readonly hidden?: boolean; readonly drawing?: boolean }

/** Run `seconds` of frames from `startMs`, each made by `frame(n)`; returns the time the run ended. */
function run(governor: FrameGovernor, startMs: number, seconds: number, frame: (n: number) => Frame): number {
  let at = startMs;
  for (let n = 0; at < startMs + seconds * 1000; n += 1) {
    const one = frame(n);
    at += one.intervalMs;
    const sample: FrameSample = { atMs: at, graphicsMs: one.graphicsMs ?? null, hidden: one.hidden ?? false, drawing: one.drawing ?? true };
    governor.observe(sample);
  }
  return at;
}

const at60 = 1000 / 60;
const at120 = 1000 / 120;
/** Two frames in five shown twice: a machine whose graphics fall behind. */
const behind = (graphicsMs: number | null) => (n: number): Frame => ({ intervalMs: n % 5 < 2 ? 2 * at60 : at60, graphicsMs });

describe('a computer that draws in time', () => {
  it('stays at full quality, at 60 Hz and at 120 Hz, and reads its display from its own frames', () => {
    for (const [display, graphics] of [[at60, 5], [at120, 3]] as const) {
      const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
      governor.restart(0);
      run(governor, 0, 40, (n) => ({ intervalMs: display + (n % 3 === 0 ? 0.3 : -0.1), graphicsMs: graphics }));
      const state = governor.state();
      expect(state.displayMs).toBeCloseTo(display - 0.1, 1);
      expect(state.lastWindow?.verdict).toBe('steady');
      expect(state.level).toBe(0);
    }
  });

  it('does not judge the first seconds after a load, a hidden tab, a pause or a still scene', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    // Shaders building: every frame a tenth of a second, all inside the settle period.
    let at = run(governor, 0, FRAME_GOVERNOR_RULES.settleMs / 1000 - 0.2, () => ({ intervalMs: 100 }));
    at = run(governor, at, 10, () => ({ intervalMs: at60, graphicsMs: 5 }));
    // Hidden for twenty seconds at a slow, throttled pace; then a two second pause; then still.
    at = run(governor, at, 20, () => ({ intervalMs: 200, hidden: true }));
    at = run(governor, at, 2, () => ({ intervalMs: 2000 }));
    at = run(governor, at, 20, () => ({ intervalMs: 40, drawing: false }));
    run(governor, at, 10, () => ({ intervalMs: at60, graphicsMs: 5 }));
    expect(governor.state().lastWindow?.verdict).toBe('steady');
    expect(governor.level).toBe(0);
  });
});

describe('a computer whose graphics fall behind', () => {
  it('steps down one level a window, no faster than the rules allow, and no lower than the budget states', () => {
    const governor = new FrameGovernor({ mostLevel: 2, mode: 'automatic' });
    governor.restart(0);
    let at = run(governor, 0, 4 + 1 + 5.5, behind(15));
    expect(governor.state().lastWindow?.verdict).toBe('weak');
    expect(governor.level).toBe(1);
    // The next window is weak too, but a step waits for the last one by `stepEveryMs`.
    at = run(governor, at, 5, behind(15));
    expect(governor.level).toBe(1);
    at = run(governor, at, 10, behind(15));
    expect(governor.level).toBe(2);
    run(governor, at, 30, behind(15));
    expect(governor.level).toBe(2);
  });

  it('steps back up once its graphics have had room long enough', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    let at = run(governor, 0, 11, behind(15));
    expect(governor.level).toBe(1);
    at = run(governor, at, 20, () => ({ intervalMs: at60, graphicsMs: 4 }));
    expect(governor.level).toBe(1);
    run(governor, at, 20, () => ({ intervalMs: at60, graphicsMs: 4 }));
    expect(governor.level).toBe(0);
  });

  it('reads steady slow frames as late, since no display it draws for refreshes under 60 Hz', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    run(governor, 0, 11, () => ({ intervalMs: 2 * at60, graphicsMs: 30 }));
    expect(governor.state().displayMs).toBeCloseTo(at60, 5);
    expect(governor.state().lastWindow).toMatchObject({ verdict: 'weak', lateShare: 1 });
    expect(governor.level).toBe(1);
  });
});

describe('late frames the graphics do not cause', () => {
  it('never step down when the timer says the graphics had room', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    run(governor, 0, 60, behind(4));
    expect(governor.state().lastWindow?.verdict).toBe('busy');
    expect(governor.level).toBe(0);
  });

  it('without a timer step down once, and when that does not help step back and stop for the session', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    let at = run(governor, 0, 11, behind(null));
    expect(governor.level).toBe(1);
    at = run(governor, at, 5, behind(null));
    expect(governor.state()).toMatchObject({ level: 0, stopped: true });
    run(governor, at, 60, behind(null));
    expect(governor.level).toBe(0);
  });

  it('without a timer keep the step down when it helped', () => {
    const governor = new FrameGovernor({ mostLevel: 4, mode: 'automatic' });
    governor.restart(0);
    const at = run(governor, 0, 11, behind(null));
    run(governor, at, 6, () => ({ intervalMs: at60, graphicsMs: null }));
    expect(governor.state()).toMatchObject({ level: 1, stopped: false });
  });
});

describe('with stepping off', () => {
  it('judges every window and advises, and draws at full quality all the same', () => {
    const governor = new FrameGovernor({ mostLevel: 4 });
    governor.restart(0);
    run(governor, 0, 11, behind(15));
    expect(governor.state()).toMatchObject({ level: 0, advised: 1, lastWindow: { verdict: 'weak' } });
  });

  it('has nowhere to step when the budget states only full quality', () => {
    const governor = new FrameGovernor({ mostLevel: 0, mode: 'automatic' });
    governor.restart(0);
    run(governor, 0, 30, behind(15));
    expect(governor.state()).toMatchObject({ level: 0, advised: 0, lastWindow: { verdict: 'weak' } });
    expect(() => new FrameGovernor({ mostLevel: -1 })).toThrow('mostLevel');
  });
});

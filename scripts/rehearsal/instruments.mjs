// What a page session installs in the page before it loads, by the name a session's `instruments`
// gives in steps.json. An instrument reads what no control shows and changes nothing the page
// does; tests/test_rehearsal_steps.py holds the step list's names to this registry.

/**
 * Where the page draws each walker, every animation frame: lane W2's measure of continuous
 * walking (its driver, watch.mjs, measured 0.149 of walker-frames moving when people walked in
 * bursts and 0.786 when they walked on, on a production build).
 *
 * Positions are read without touching product code: the crowd keeps its walkers in a Map whose
 * values carry `position`, `facing`, `arrived` and `indoors` (the crowd's own field names in
 * web/packages/atlas-react/src/playcanvas/society/crowd.ts), so the latest Map a value of that
 * shape is stored in is noted, and a requestAnimationFrame sampler reads every outdoor walker's
 * drawn ground position from it once a frame. `window.__rehearsalWalkerMotion(seconds, floor)`
 * samples for that long and answers a summary, so the protocol carries numbers rather than every
 * frame: the per-frame displacement of each walker drawn in two consecutive frames, in metres, how
 * many of those walker-frames moved at all, the speeds they were drawn at in bands, and the pace of
 * the walker-frames at or above `floor` metres a second, which is how fast drawn people walk.
 */
const WALKER_POSITIONS = `(() => {
  const set = Map.prototype.set;
  const walker = (v) => v !== null && typeof v === 'object' && 'position' in v && 'facing' in v && 'arrived' in v && 'indoors' in v;
  Map.prototype.set = function (key, value) {
    if (walker(value)) window.__rehearsalWalkers = this;
    return set.call(this, key, value);
  };
  const sample = (seconds) => new Promise((done) => {
    const frames = [];
    const start = performance.now();
    const step = (now) => {
      const map = window.__rehearsalWalkers;
      const at = {};
      if (map) for (const [id, w] of map) if (!w.indoors) at[id] = [w.position[0], w.position[1]];
      frames.push({ t: now, at });
      if (now - start < seconds * 1000) requestAnimationFrame(step); else done(frames);
    };
    requestAnimationFrame(step);
  });
  window.__rehearsalWalkerMotion = async (seconds, floor) => {
    const frames = await sample(seconds);
    const moves = [], still = [], intervals = [], speeds = [];
    const perWalker = {};
    for (let i = 1; i < frames.length; i += 1) {
      const dt = (frames[i].t - frames[i - 1].t) / 1000;
      intervals.push(frames[i].t - frames[i - 1].t);
      for (const [id, [x, z]] of Object.entries(frames[i].at)) {
        const held = frames[i - 1].at[id];
        if (!held) continue;
        const d = Math.hypot(x - held[0], z - held[1]);
        (d > 0 ? moves : still).push(d);
        (perWalker[id] ??= []).push(d);
        if (dt > 0) speeds.push(d / dt);
      }
    }
    // How fast drawn walkers go, in bands of metres a second: what separates walking from a
    // walker standing while its drawn position settles by fractions of a millimetre a frame.
    const bands = [0, 0.01, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6];
    const speedBands = bands.map((low, i) => ({ from_m_per_s: low, to_m_per_s: bands[i + 1] ?? null,
      walker_frames: speeds.filter((s) => s >= low && (bands[i + 1] === undefined || s < bands[i + 1])).length }));
    const q = (values, p) => { if (!values.length) return null; const s = [...values].sort((a, b) => a - b);
      return s[Math.min(s.length - 1, Math.floor(p * (s.length - 1) + 0.5))]; };
    const all = [...moves, ...still];
    const walking = speeds.filter((s) => s >= floor);
    return {
      seconds, frames: frames.length, walkers_seen: Object.keys(perWalker).length,
      frame_ms: { median: q(intervals, 0.5), p95: q(intervals, 0.95), max: intervals.length ? Math.max(...intervals) : null },
      walker_frames: all.length, moving_walker_frames: moves.length,
      moving_share: all.length ? moves.length / all.length : null,
      step_m: { median: q(all, 0.5), p95: q(all, 0.95), max: all.length ? Math.max(...all) : null },
      speed_bands: speedBands,
      walking: { floor_m_per_s: floor, walker_frames: walking.length,
        pace_m_per_s: { median: q(walking, 0.5), p95: q(walking, 0.95), max: walking.length ? Math.max(...walking) : null } },
      walkers: Object.fromEntries(Object.entries(perWalker).map(([id, ds]) => [id, {
        walker_frames: ds.length, moving: ds.filter((d) => d > 0).length,
        metres: ds.reduce((a, b) => a + b, 0), max_step_m: Math.max(...ds) }])),
    };
  };
})();`;

export const INSTRUMENTS = Object.freeze({
  'walker-positions': WALKER_POSITIONS,
});

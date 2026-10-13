/** One time vocabulary for the timeline and content entrances, in milliseconds. */
export const CAPABILITY_MOTION = Object.freeze({
  duration: 7200,
  transition: 480,
  // Text and guide switch atomically. One particle field morphs from the outgoing pose.
  overlap: 0,
  assembly: 800,
  stagger: 70,
  phases: Object.freeze({ observe: 480, action: [2200, 4500] as const, complete: 5550 }),
  easing: [0.22, 1, 0.36, 1] as const,
});

/** CSS and SVG use the same cubic-bezier, sampled by elapsed time rather than independent loops. */
export function capabilityEase(value: number): number {
  const x = Math.max(0, Math.min(1, value));
  const [x1, y1, x2, y2] = CAPABILITY_MOTION.easing;
  const curve = (t: number, a: number, b: number) => 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t ** 2 * b + t ** 3;
  let lower = 0;
  let upper = 1;
  for (let step = 0; step < 12; step++) {
    const mid = (lower + upper) / 2;
    if (curve(mid, x1, x2) < x) lower = mid;
    else upper = mid;
  }
  return x === 0 || x === 1 ? x : curve((lower + upper) / 2, y1, y2);
}

/** Stored active time. Suspension never catches up hidden time; selection starts at zero. */
export function createCapabilitySequence(count: number) {
  let index = 0;
  let elapsed = 0;
  let last: number | null = null;
  const advance = (now: number) => {
    if (last !== null) {
      elapsed += Math.max(0, now - last);
      if (elapsed >= CAPABILITY_MOTION.duration) {
        index = (index + Math.floor(elapsed / CAPABILITY_MOTION.duration)) % count;
        elapsed %= CAPABILITY_MOTION.duration;
      }
      last = now;
    }
    return { index, elapsed };
  };
  return {
    advance,
    setRunning(running: boolean, now: number) {
      const state = advance(now);
      last = running ? now : null;
      return state;
    },
    select(next: number, now: number) {
      index = (next + count) % count;
      elapsed = 0;
      if (last !== null) last = now;
      return { index, elapsed };
    },
  };
}

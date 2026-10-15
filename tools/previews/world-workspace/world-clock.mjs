// The world's clock in the corners' words (DESIGN's WORDS.md: "06:14", "Day 2"). A society's tick
// is one simulated minute after its first (exulanica/world/society_*: the clock's day is
// floor((start_minute_of_day + tick) / 1440), counted from 0); a person reads the first day as Day 1.

export const MINUTES_PER_DAY = 1440;

/** The time of day and the day a tick falls on, or null where either is unknown. */
export function worldTime(tick, startMinuteOfDay) {
  if (!Number.isSafeInteger(tick) || tick < 0 || !Number.isSafeInteger(startMinuteOfDay) || startMinuteOfDay < 0 || startMinuteOfDay >= MINUTES_PER_DAY) return null;
  const absolute = startMinuteOfDay + tick, minuteOfDay = absolute % MINUTES_PER_DAY;
  const hhmm = `${String(Math.floor(minuteOfDay / 60)).padStart(2, '0')}:${String(minuteOfDay % 60).padStart(2, '0')}`;
  return { minuteOfDay, day: Math.floor(absolute / MINUTES_PER_DAY) + 1, hhmm };
}

/** The line under the time: "Day 1 · Paused" or "Day 1 · Playing". */
export function clockLine(day, mode) {
  return `Day ${day} · ${mode === 'playing' ? 'Playing' : 'Paused'}`;
}

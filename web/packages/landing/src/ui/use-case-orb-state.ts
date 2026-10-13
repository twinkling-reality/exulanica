/** One active-time clock for all category materials. Focus changes the field, never its silhouette. */
export function createOrbState(phases: readonly number[]) {
  const values = phases.map(phase => ({ phase, emphasis: 0 }));
  let previous: number | null = null;
  let selected = -1;
  return {
    values,
    select(index: number) { selected = index; },
    suspend() { previous = null; },
    advance(now: number) {
      const delta = previous === null ? 0 : Math.max(0, Math.min((now - previous) / 1000, 1 / 30));
      previous = now;
      values.forEach((value, index) => {
        const target = index === selected ? 1 : 0;
        value.emphasis += (target - value.emphasis) * (1 - Math.exp(-delta * (target > value.emphasis ? 18 : 7)));
        value.phase += delta * (.32 + value.emphasis * .6);
      });
    },
  };
}

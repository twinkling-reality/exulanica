/** Distance along the recorded polyline. This does not plan, snap or change canonical state. */
export function sampleMotionPath(
  path: readonly (readonly [number, number])[],
  fraction: number,
): readonly [number, number] {
  if (path.length === 0)
    throw new Error('A recorded motion path needs a position');
  const lengths = path
    .slice(1)
    .map((point, i) =>
      Math.hypot(point[0] - path[i]![0], point[1] - path[i]![1]),
    );
  let remaining =
    lengths.reduce((a, b) => a + b, 0) * Math.min(1, Math.max(0, fraction));
  for (let i = 0; i < lengths.length; i++) {
    const length = lengths[i]!;
    if (length === 0) continue;
    if (remaining <= length) {
      const a = path[i]!,
        b = path[i + 1]!,
        t = remaining / length;
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    remaining -= length;
  }
  return path[path.length - 1]!;
}

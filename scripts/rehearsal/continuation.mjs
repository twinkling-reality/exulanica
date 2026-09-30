/** A timing-only failure does not prevent later functional actions in a loaded capture. */
export function timingOnlyFailure(step, observations, failure) {
  const timing = new Set(step.timing_observations ?? []);
  if (timing.size === 0) return false;
  const declared = new Set(Object.values(step.expect).flat().map((item) => item.id));
  const observed = new Set(observations.map((item) => item.id));
  if (observed.size !== declared.size || observations.length !== declared.size
    || [...observed].some((id) => !declared.has(id))) return false;
  const broken = observations.filter((item) => !item.ok);
  return broken.length > 0 && broken.every((item) => timing.has(item.id))
    && failure === `did not hold: ${broken.map((item) => item.id).join(', ')}`;
}

/** A running flag alone is insufficient: the host must have advanced a durable tick. */
export function hostProgresses(control, end, advanced) {
  return control?.mode === 'playing' && control?.host_playback?.running === true
    && end?.mode === 'playing' && Number.isInteger(advanced) && advanced > 0;
}

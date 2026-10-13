const words = value => typeof value === 'string' && value.trim() ? value.trim() : null;
export const capitalise = value => value ? value.charAt(0).toUpperCase() + value.slice(1) : '';
export const propertyOf = (offer, key) => offer?.properties?.find(item => item.key === key);

/** Never combine a selected identity with another world's or subject's offer. */
export function assertSelectedOffer(offer, entry, row) {
  if (!offer || offer.profile !== 'exulanica.subject-offer/v1'
    || offer.world_id !== entry.worldId || offer.version_id !== entry.authoredVersionId
    || offer.subject?.ref !== row.detail?.bind?.ref) {
    throw Error('This entity changed while its details were loading. Close this view and inspect it again.');
  }
}

/** Render only supplied facts. A body's fallback label is not an individual name. */
export function inspectionFacts(row, offer, playback, activityLabels, reasonLabels = {}) {
  const kind = offer?.subject?.kind;
  const name = words(offer?.subject?.name);
  const bodyName = words(kind?.body?.name);
  const named = name && (!bodyName || name.toLowerCase() !== bodyName.toLowerCase());
  const appearance = words(propertyOf(offer, 'look')?.value?.label);
  const title = capitalise((named ? name : null) || words(kind?.label) || appearance
    || (bodyName && row.label?.toLowerCase() === bodyName.toLowerCase() ? null : words(row.label))
    || (row.scene?.type === 'being' ? 'Unnamed entity' : 'Object'));
  const person = row.sources?.find(item => item.source === 'society-being')?.record;
  const facts = [];
  if (person?.action) {
    const label = activityLabels.get(person.action.kind);
    if (person.action.status === 'blocked') facts.push({ label: 'Activity', value: 'Unable to act', note: reasonLabels[person.action.reason] ? capitalise(reasonLabels[person.action.reason]) : undefined });
    else if (label) facts.push({ label: 'Activity', value: capitalise(label) });
    if (person.target?.place?.label) facts.push({ label: 'At', value: person.target.place.label });
    if (person.goal === null) facts.push({ label: 'Current task', value: 'No current task' });
    else if (person.goal) {
      const goalLabel = activityLabels.get(person.goal.activity || person.goal.kind);
      if (goalLabel) facts.push({ label: 'Current task', value: capitalise(goalLabel) });
    }
  }
  const decider = propertyOf(offer, 'decided_by')?.value;
  if (row.scene?.type === 'being' && decider) {
    const label = { routine: 'Preset behaviour', person: decider.played_by_you ? 'You' : 'Another player', external: words(decider.label) || 'External controller' }[decider.kind];
    if (label) facts.push({ label: 'Controlled by', value: label });
    if (decider.kind === 'model') facts.push({ label: 'Controlled by', value: words(decider.name) || words(decider.model_id) || 'Assigned AI', note: decider.refusal ? 'This AI is unavailable here' : 'AI assigned' });
  }
  const where = propertyOf(offer, 'where')?.value;
  if (row.scene?.type !== 'being' && where?.on_ground === true) facts.push({ label: 'Placement', value: 'On the ground' });
  if (appearance) facts.push({ label: 'Appearance', value: capitalise(appearance) });
  // A failed or mismatched status read never defaults to paused.
  const playbackKnown = playback?.profile === 'exulanica.society-control/v1'
    && playback.branch_id === offer?.version_id
    && playback.current_tick === offer?.read?.tick;
  return { title, named: Boolean(named), facts, paused: playbackKnown && playback.mode === 'paused' };
}

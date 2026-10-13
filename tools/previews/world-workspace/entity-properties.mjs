/** Physical properties are declared values, never inferred from a rendered picture. */
export function entityProperties(offer, document) {
  const dimensions = [];
  if (document?.profile === 'exulanica.thing-kind/v1') {
    for (const [key, label] of [['height', 'Height'], ['length', 'Length'], ['width', 'Width'], ['span', 'Span']]) {
      const mm = document.body?.extent_mm?.[key];
      if (Number.isSafeInteger(mm) && mm > 0) dimensions.push({ key, label, value: mm / 1000, unit: 'm' });
    }
  }
  const fields = [];
  const look = offer?.properties?.find(property => property.key === 'look')?.value;
  if (look?.label) fields.push({ label: 'Appearance', value: look.label });
  const moves = (document?.moves || []).flatMap(module => {
    const matched = typeof module === 'string' && module.match(/^exulanica-movement\/([a-z-]+)\/v\d+$/);
    return matched ? [matched[1].charAt(0).toUpperCase() + matched[1].slice(1).replaceAll('-', ' ')] : [];
  });
  if (moves.length) fields.push({ label: 'Movement', value: moves.join(', ') });
  const location = offer?.properties?.find(property => property.key === 'where')?.value;
  if (location?.on_ground === true) fields.push({ label: 'Placement', value: 'On the ground' });
  return { dimensions, fields };
}

/** The entity's action, role membership and permissions must name the same subject. */
export function assignmentSubject(inventory, row, offer) {
  const action = offer.actions?.find(action => action.id === 'minds.choose');
  const bind = action?.runs_by?.bind;
  const link = row.roleInstances?.find(link => link.role_key === bind?.role_key && link.subject_id === bind?.subject_id);
  const role = inventory.roles?.find(role => role.key === bind?.role_key && role.subject === 'person');
  return action?.state === 'available' && action.permitted && bind.version_id === inventory.version_id
    && role?.available && role.capability?.permitted && role.capability?.state === 'available'
    && link ? { subjectId: link.subject_id, roleKey: role.key } : null;
}

export function offeredModel(view, model) {
  return model === null || view.models.some(item => item.provider === model.provider && item.modelId === model.modelId);
}

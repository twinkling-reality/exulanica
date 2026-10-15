/**
 * The subject a model may be chosen for, or null. A being with an offer is held to it: the offer's
 * minds.choose action, the row's role membership and the role's permission must name the same
 * subject. A being whose inventory entry serves no offer (a town's resident) is held to its row's
 * own person-role link and that role's capability, the write the role names for this version.
 */
export function assignmentSubject(inventory, row, offer) {
  if (!offer) {
    const roles = (inventory.roles || []).filter(role => role.subject === 'person' && role.available
      && role.capability?.permitted && role.capability?.state === 'available' && role.capability?.bind?.version_id === inventory.version_id);
    const link = row.roleInstances?.find(link => link.subject_id === row.scene?.id && roles.some(role => role.key === link.role_key));
    return link ? { subjectId: link.subject_id, roleKey: link.role_key } : null;
  }
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

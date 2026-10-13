import { assignmentSubject } from './entity-properties.mjs';

/** Assignment, playback and a recorded decision are distinct authoritative states. */
export function modelRunState(models, control, subjectId, selected = null) {
  const choice = models?.choices.find(item => item.subjectId === subjectId);
  const model = selected || choice?.model;
  const refusal = model?.refusal || choice?.refusal || models?.hostRefusal;
  let reason = !model ? 'Choose a model before starting AI behavior.'
    : refusal === 'provider_credential_absent' ? 'The AI service is not connected.'
    : refusal ? 'This model cannot run here right now.'
    : !control ? 'Reading the world’s running state…'
    : !control.playEligible ? control.playIneligibleReason || 'This world cannot run right now.'
    : control.modelMinds ? control.modelMinds.reason
    : !control.hostPlayback?.running ? control.hostPlayback?.reason || 'Automatic world playback is unavailable.'
    : null;
  return { ready: reason === null, reason, playing: control?.mode === 'playing', model: model || null };
}

function assertExecutionBinding(models, control, entry) {
  if (control.versionId !== entry.authoredVersionId || models.societyId !== control.societyId) throw Error('The world’s running state could not be verified.');
}

export async function runSelectedModel({ modelsClient, controlClient, entry, subjectId, expectedModel, current, refresh }) {
  const fresh = await refresh();
  if (!current() || fresh.row.scene?.id !== subjectId || fresh.inventory.world_id !== entry.worldId || fresh.inventory.version_id !== entry.authoredVersionId) throw Error('The selected entity changed. Open it again.');
  if (assignmentSubject(fresh.inventory, fresh.row, fresh.offer)?.subjectId !== subjectId) throw Error('Model control is no longer available for this entity.');
  const [models, control] = await Promise.all([modelsClient.read(entry.authoredVersionId), controlClient.read(entry.authoredVersionId)]);
  assertExecutionBinding(models, control, entry);
  const actual = models.choices.find(choice => choice.subjectId === subjectId)?.model;
  if (!actual || actual.provider !== expectedModel.provider || actual.modelId !== expectedModel.modelId) throw Error('The selected model changed. Review it again.');
  const readiness = modelRunState(models, control, subjectId);
  if (!readiness.ready) throw Error(readiness.reason);
  if (!current()) throw Error('The world changed. Open it again.');
  if (control.mode === 'playing') return control;
  await controlClient.configure(control, 'playing', control.speed);
  const verified = await controlClient.read(entry.authoredVersionId);
  if (verified.versionId !== entry.authoredVersionId || verified.societyId !== control.societyId || verified.mode !== 'playing') throw Error('The model is assigned, but world playback could not be confirmed. Refresh its activity.');
  return verified;
}

/** Observe through existing authenticated clients; never advance a tick or ask a provider. */
export async function readEntityActivity({ modelsClient, controlClient, societyClient, entry, subjectId, current }) {
  const [models, control, society] = await Promise.all([modelsClient.read(entry.authoredVersionId), controlClient.read(entry.authoredVersionId), societyClient.read(entry.authoredVersionId)]);
  assertExecutionBinding(models, control, entry);
  if (society.versionId !== entry.authoredVersionId || society.societyId !== models.societyId || !current()) throw Error('The selected world changed.');
  const person = society.state.inhabitants.find(item => item.id === subjectId);
  if (!person) throw Error('This character is no longer in the world.');
  const events = await societyClient.events(society);
  if (!current()) throw Error('The activity view is no longer open.');
  return { models, control, person, events: events.filter(event => event.subject_id === subjectId).slice(-6).reverse(), latest: models.latest.find(item => item.subjectId === subjectId) || null, tick: society.currentTick };
}

export function decisionView(data, entry, subjectId) {
  if (data.request.branch_id !== entry.authoredVersionId || data.request.subject_id !== subjectId) throw Error('This decision belongs to another entity.');
  const context = data.request.context;
  if (context && (context.branch_id !== entry.authoredVersionId || context.subject_id !== subjectId)) throw Error('The decision’s input belongs to another entity.');
  return { status: data.status, options: (context?.options || []).flatMap(option => typeof option.label === 'string' ? [option.label] : []), context: context || null, receipt: data.decision };
}

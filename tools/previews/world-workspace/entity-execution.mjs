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

/** The run (living session) the control read states is open, or null. */
export function openRun(control) {
  return control?.livingSession?.state === 'open' ? control.livingSession : null;
}

/** How many characters a run would ask a model for: those whose current choice is a model. */
export function modelAskers(models) {
  return models?.choices.filter(choice => choice.model).length ?? 0;
}

/**
 * Start a run for the world this character lives in: the same checks as before (the entity, its
 * model, the world's readiness), then one living session with `limits`, opened on the control read
 * and verified open. A world already in a run answers that run. A world playing without one is
 * opened as it plays: the server starts the run at the minute the world is at, in one write, so
 * nothing pauses it on the way.
 */
export async function startRun({ modelsClient, controlClient, entry, subjectId, expectedModel, current, refresh, limitsFor, requestId }) {
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
  if (openRun(control)) return control;
  const opened = await controlClient.openSession(control, limitsFor(control, models), requestId);
  const verified = await controlClient.read(entry.authoredVersionId);
  if (verified.versionId !== entry.authoredVersionId || verified.societyId !== control.societyId || openRun(verified)?.sessionId !== opened.sessionId) throw Error('The run started, but it could not be confirmed. Look again in a moment.');
  return verified;
}

/** Stop the open run: it closes and the world is handed back as the run found it, as the server answers it. */
export async function stopRun({ controlClient, entry, current }) {
  const control = await controlClient.read(entry.authoredVersionId);
  if (control.versionId !== entry.authoredVersionId || !current()) throw Error('The world changed. Open it again.');
  const run = openRun(control);
  if (!run) return control;
  await controlClient.stopSession(entry.authoredVersionId, run.sessionId);
  return controlClient.read(entry.authoredVersionId);
}

/**
 * A being's newest recorded events, newest first. The events read serves minutes newest first and,
 * within a minute, events in the order the engine gave them, so a minute's later events go first.
 */
function newestEvents(events, subjectId, count) {
  return events.flatMap((event, index) => event.subject_id === subjectId ? [{ event, index }] : [])
    .sort((a, b) => b.event.tick - a.event.tick || b.index - a.index).slice(0, count).map(item => item.event);
}

/** How many of the society's newest applied decisions one read takes, for a being's newest choices. */
const CHOICES_READ = 64;

/**
 * Observe through existing authenticated clients; never advance a tick or ask a provider. With
 * `read` (an authenticated GET of a path), `choices` holds the being's applied decisions from the
 * events read kept to that kind, so a world of many people still shows its own; without it, from
 * the newest events.
 */
export async function readEntityActivity({ modelsClient, controlClient, societyClient, entry, subjectId, current, read = null }) {
  const [models, control, society] = await Promise.all([modelsClient.read(entry.authoredVersionId), controlClient.read(entry.authoredVersionId), societyClient.read(entry.authoredVersionId)]);
  assertExecutionBinding(models, control, entry);
  if (society.versionId !== entry.authoredVersionId || society.societyId !== models.societyId || !current()) throw Error('The selected world changed.');
  const person = society.state.inhabitants.find(item => item.id === subjectId);
  if (!person) throw Error('This character is no longer in the world.');
  const [events, applied] = await Promise.all([societyClient.events(society), read
    ? read(`/world/versions/${encodeURIComponent(entry.authoredVersionId)}/society/events?world_id=${encodeURIComponent(entry.worldId)}&kinds=decision_applied&limit=${CHOICES_READ}`)
    : null]);
  if (!current()) throw Error('The activity view is no longer open.');
  const choices = (Array.isArray(applied?.events) ? applied.events : events).filter(event => event.subject_id === subjectId && event.event_kind === 'decision_applied');
  return { models, control, person, events: newestEvents(events, subjectId, 6), choices, latest: models.latest.find(item => item.subjectId === subjectId) || null, tick: society.currentTick };
}

export function decisionView(data, entry, subjectId) {
  if (data.request.branch_id !== entry.authoredVersionId || data.request.subject_id !== subjectId) throw Error('This decision belongs to another entity.');
  const context = data.request.context;
  if (context && (context.branch_id !== entry.authoredVersionId || context.subject_id !== subjectId)) throw Error('The decision’s input belongs to another entity.');
  return { status: data.status, options: (context?.options || []).flatMap(option => typeof option.label === 'string' ? [option.label] : []), context: context || null, receipt: data.decision };
}

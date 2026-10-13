import { CompanionAskClient } from '/src/companion-ask-api.ts';
import { drawSimulated } from '/src/companion-simulated.ts';
import { askEntityCompanion } from './entity-companion.mjs';
import { SocietyControlClient } from '/src/society-control-api.ts';
import { SocietyClient } from '/src/society-api.ts';
import { ACTION_LABELS, ACTIVITY_LABELS } from '/src/society-activity-words.ts';
import { modelRunState, runSelectedModel, readEntityActivity, decisionView } from './entity-execution.mjs';
import { SocietyModelsClient } from '/src/society-models-api.ts';
import { openThingLibrary } from '/src/things-library.ts';
import { choiceRefusalWords, HOST_REFUSAL_WORDS, MODEL_REFUSAL_WORDS, decisionWordsFor } from '/src/ui/society-models.ts';
import { problemSentence } from '/src/ui/words/problems.ts';
import { entityProperties, assignmentSubject } from './entity-properties.mjs';
import { recordEntityModel } from './entity-model-actions.mjs';

/** The entity sheet has one selected identity and uses native model clients for writes. */
export function mountEntitySheet({ panel, row, offer, title, entry, inventory, credentials, read, refresh, close, isCurrent, societyNames }) {
  const observerOnly = import.meta.env.VITE_EXULANICA_REVIEW_OBSERVER_ONLY === '1';
  let live = true, tab = 'properties', mode = 'summary', models = null, roleRead = null;
  let kind = null, kindFailure = '', modelFailure = '', picked = null, message = '', busy = false, assignmentKey = null;
  let playback = null, activity = null, activityFailure = '', activityTimer = null, activityEpoch = 0, activityPending = null;
  const controlClient = new SocietyControlClient({ ...credentials, worldId: entry.worldId });
  const societyClient = new SocietyClient({ ...credentials, worldId: entry.worldId });
  let requestSerial = 0, companionAnswer = null, companionQuestion = '', companionFailure = '';
  let decisionReturn = 'summary';
  const companion = new CompanionAskClient({ ...credentials, worldId: entry.worldId });
  offer ||= { subject: {}, properties: [], actions: [] };
  const client = new SocietyModelsClient({ ...credentials, worldId: entry.worldId });
  const candidate = row.roleInstances?.find(link => inventory.roles.find(role => role.key === link.role_key)?.subject === 'person');
  const subjectId = candidate?.subject_id;
  const $ = (tag, text = '', cls = '') => { const el = document.createElement(tag); el.textContent = text; el.className = cls; return el; };
  const button = (text, run, cls = '', key = '') => {
    const el = $('button', '', cls); el.type = 'button'; el.onclick = run;
    if (key) el.append($('kbd', key)); el.append($('span', text)); return el;
  };
  const currentChoice = () => models?.choices.find(choice => choice.subjectId === subjectId);
  const rawRole = () => roleRead?.roles.find(role => role.key === candidate?.role_key);
  const target = () => assignmentSubject(inventory, row, offer);
  const canAssign = () => !observerOnly && Boolean(target() && models?.takesModelChoices && rawRole()?.capability?.permitted && rawRole()?.capability?.state === 'available' && rawRole()?.available);
  const back = () => {
    if (mode === 'model-details') mode = 'pick';
    else if (mode === 'decision') mode = decisionReturn;
    else if (mode === 'pick' || mode === 'activity') mode = 'summary';
    else if (mode === 'companion' || tab === 'model') { mode = 'summary'; tab = 'properties'; }
    else { close(); return; }
    ++activityEpoch; clearTimeout(activityTimer); message = ''; render();
    if (mode === 'activity') void loadActivity();
  };
  const rowValue = (parent, label, value) => {
    if (value == null) return; const item = $('div', '', 'es-row'); item.append($('dt', label), $('dd', value)); parent.append(item);
  };

  function render(preserveTaskState = false) {
    if (!live) return;
    const openRecords = preserveTaskState ? [...panel.querySelectorAll('details[open]')].map(item => item.querySelector('summary')?.textContent) : [];
    const focusText = preserveTaskState && panel.contains(document.activeElement) ? document.activeElement.textContent : null;
    panel.replaceChildren(); panel.classList.add('cw-entity-sheet'); panel.dataset.view = tab === 'properties' && mode === 'summary' ? 'details' : 'task';
    const header = $('header', '', 'es-header'), heading = $('h2', title); heading.id = 'cw-panel-title'; heading.tabIndex = -1; header.append(heading); panel.append(header);
    const content = $('div', '', 'es-content');  panel.append(content);
    if (mode === 'companion') renderCompanion(content);
    else if (tab === 'properties') renderProperties(content);
    else if (mode === 'pick') renderPicker(content);
    else if (mode === 'model-details') renderModelDetails(content);
    else if (mode === 'decision') renderDecision(content);
    else if (mode === 'activity') renderActivity(content);
    else renderModel(content);
    if (message) { const status = $('p', message, 'es-message'); status.setAttribute('role', 'status'); content.append(status); if (candidate) content.append(button('Refresh model information', () => { message = ''; void loadModels(); }, 'es-secondary', 'R')); }
    const footer = $('footer', '', 'es-footer'); footer.append(button(tab === 'properties' && mode === 'summary' ? 'Close' : 'Back', back, 'cw-back', 'Esc')); panel.append(footer);
    for (const item of panel.querySelectorAll('details')) if (openRecords.includes(item.querySelector('summary')?.textContent)) item.open = true;
    if (focusText) [...panel.querySelectorAll('button,summary,h2')].find(item => item.textContent === focusText)?.focus({ preventScroll: true });
  }
  function renderProperties(content) {
    const data = entityProperties(offer, kind);
    const details = $('section', '', 'es-data-group'), fields = $('dl', '', 'es-properties');
    for (const dimension of data.dimensions) rowValue(fields, dimension.label, dimension.value + ' ' + dimension.unit);
    for (const field of data.fields) if (field.label !== 'Placement') rowValue(fields, field.label, field.value);
    if (fields.children.length) details.append(fields);
    else details.append($('p', !kind && !kindFailure ? 'Reading entity details…' : 'No further details are recorded for this entity.', 'es-note'));
    content.append(details);
    const actions = $('section', '', 'es-entity-actions');
    if (candidate) {
      const manage = button(observerOnly ? 'View behavior' : 'Manage behavior', openBehavior, 'es-action', 'M');
      actions.append(manage);
    }
    if (row.scene?.type === 'being' && !observerOnly) actions.append(button('Ask Companion', () => { mode = 'companion'; render(); }, 'es-action', 'C'));
    if (actions.children.length) content.append(actions);
  }
  function renderCompanion(content) {
    content.append($('p', 'Companion', 'es-section-title'));
    if (busy) content.append($('p', 'Reading this character’s world records…', 'es-note'));
    if (companionAnswer) {
      content.append($('p', companionQuestion, 'es-question'));
      const nativeNames = societyNames?.();
      const names = nativeNames?.versionId === entry.authoredVersionId ? { ...nativeNames, people: new Map(nativeNames.people) }
        : { versionId: entry.authoredVersionId, people: new Map(), spots: new Map() };
      names.people.set(row.scene.id, title);
      panel.dataset.companionCalls = String(companionAnswer.calls.length);
      for (const clause of companionAnswer.clauses) content.append($('p', drawSimulated([{kind:'text',text:clause.text}], companionAnswer, names).map(piece => piece.text).join(''), clause.type === 'meta' ? 'es-note' : 'es-answer'));
      if (!companionAnswer.clauses.length) content.append($('p', 'The world has no answer recorded for this question.', 'es-note'));
      if (companionAnswer.simulation?.length) {
        const evidence = $('details', '', 'es-record'); evidence.append($('summary', 'World records'));
        for (const source of companionAnswer.simulation) evidence.append($('p', drawSimulated([{kind:'text',text:source.line}], companionAnswer, names).map(piece => piece.text).join(''), 'es-note'));
        content.append(evidence);
      }
    } else content.append($('p', 'Ask about this character using its world records.', 'es-note'));
    if (companionFailure) { const error = $('p', companionFailure, 'es-message'); error.setAttribute('role','status'); content.append(error); }
    if (companionAnswer) { content.append(button('Ask another question', () => { companionAnswer = null; render(); }, 'es-action')); return; }
    for (const [aspect, words, key] of [['who','Who is this?','1'],['doing','What is it doing?','2'],['why','Why is it doing that?','3']]) {
      const ask = button(words, () => void askCompanion(aspect, words), 'es-action', key); ask.disabled = busy; content.append(ask);
    }
  }
  async function askCompanion(aspect, words) {
    if (busy) return;
    busy = true; companionFailure = ''; companionQuestion = words; render();
    const request = ++requestSerial;
    try {
      const { answer, fresh } = await askEntityCompanion({ aspect, entry, row, client: companion, refresh,
        current: () => live && isCurrent() && request === requestSerial && mode === 'companion' });
      if (!live || request !== requestSerial) return;
      row = fresh.row; inventory = fresh.inventory; offer = fresh.offer; companionAnswer = answer;
    } catch (error) { if (live && request === requestSerial) companionFailure = error.message || 'The world records could not be read. Try again.'; }
    finally { if (live && request === requestSerial) { busy = false; render(); } }
  }
  function renderModel(content) {
    if (!models) {
      content.append($('p', modelFailure || 'Loading model information…', 'es-note'));
      if (modelFailure) content.append(button('Retry', () => void loadModels(), 'es-action')); return;
    }
    content.append($('p', 'Behavior', 'es-section-title'));
    const choice = currentChoice(), fields = $('dl', '', 'es-properties');
    rowValue(fields, 'Assigned model', choice?.model?.name || (offer.decided_by?.kind === 'routine' ? 'Routine' : 'None'));
    const refusal = choice?.refusal || models.hostRefusal;
    if (choice?.model && !observerOnly) rowValue(fields, 'Connection', refusal === 'provider_credential_absent' ? 'Not connected' : refusal ? 'Unavailable' : 'Connected');
    content.append(fields);
    if (observerOnly) content.append($('p', 'This viewer shows recorded activity. Model and run controls are unavailable here.', 'es-note'));
    else if (choice?.model && refusal) content.append($('p', refusal === 'provider_credential_absent' ? 'The AI service needs a connection before this model can make decisions.' : HOST_REFUSAL_WORDS[refusal] || MODEL_REFUSAL_WORDS[refusal] || 'This model cannot make decisions here right now.', 'es-note'));
    const actions = $('div', '', 'es-actions');
    const change = button(choice?.model ? 'Change model' : 'Assign model', () => { mode = 'pick'; picked = null; message = ''; render(); }, 'es-action', 'M');
    change.disabled = !canAssign(); if (!observerOnly) actions.append(change);
    if (choice?.model && !observerOnly) { const remove = button('Remove model', () => { mode = 'model-details'; picked = { model: null }; assignmentKey = crypto.randomUUID(); render(); }, 'es-secondary'); remove.disabled = !canAssign(); actions.append(remove); }
    actions.append(button('View activity', openActivity, 'es-action', 'A'));
    if (choice?.model && !observerOnly) { const run = button('Run world', () => void startAI(choice.model), 'es-action'); run.disabled = !modelRunState(models, playback, subjectId).ready || busy; actions.append(run); }
    content.append(actions);
    if (!observerOnly && !canAssign()) content.append($('p', 'Model assignment is not available for this entity with your current access.', 'es-note'));
    const decision = models.latest.find(item => item.subjectId === subjectId);
    if (!decision && choice?.model) content.append($('p', 'No AI decisions recorded for this entity.', 'es-note'));
    else if (decision) {
      content.append($('p', decisionWordsFor(models, subjectId) || 'A model decision is recorded.', 'es-note'));
      if (decision.requestId) content.append(button('Inspect decision', () => openDecision(decision), 'es-secondary', 'D'));
    }
  }
  function openBehavior() {
    tab = 'model'; mode = 'summary'; message = ''; render();
    if (!models || !playback) void loadModels();
  }
  function openActivity() {
    tab = 'model'; mode = 'activity'; activityFailure = ''; ++activityEpoch; clearTimeout(activityTimer); render(); void loadActivity();
  }
  async function loadActivity() {
    if (!live || mode !== 'activity') return;
    const epoch = activityEpoch;
    if (activityPending === epoch) return;
    activityPending = epoch; clearTimeout(activityTimer);
    try {
      const fresh = await readEntityActivity({ modelsClient: client, controlClient, societyClient, entry, subjectId,
        current: () => live && isCurrent() && mode === 'activity' && epoch === activityEpoch });
      if (!live || mode !== 'activity' || epoch !== activityEpoch) return;
      const changed = activityFailure || JSON.stringify(fresh) !== JSON.stringify(activity);
      activity = fresh; models = fresh.models; playback = fresh.control; activityFailure = ''; if (changed) render(true);
    } catch (error) { if (live && mode === 'activity' && epoch === activityEpoch) { activityFailure = error.message || 'Activity could not be read. Try again.'; render(true); } }
    finally { if (activityPending === epoch) activityPending = null; }
    scheduleActivity(epoch);
  }
  function scheduleActivity(epoch) {
    if (!live || mode !== 'activity' || epoch !== activityEpoch) return;
    activityTimer = setTimeout(() => { if (!document.hidden) void loadActivity(); else scheduleActivity(epoch); }, 2500);
  }
  function renderActivity(content) {
    content.append($('p', 'Activity', 'es-section-title'));
    if (!activity) { content.append($('p', activityFailure || 'Reading this character’s activity…', 'es-note')); return; }
    const readiness = modelRunState(models, playback, subjectId);
    const state = $('p', (!observerOnly && readiness.reason) || (playback.mode === 'playing' ? 'The world is running.' : 'The world is paused.'), 'es-note'); content.append(state);
    const facts = $('dl', '', 'es-properties'), action = activity.person.action;
    const assignedName = currentChoice()?.model?.name || (offer.decided_by?.kind === 'routine' ? 'Routine' : 'None');
    rowValue(facts, 'Assigned model', assignedName);
    rowValue(facts, 'Now', ACTION_LABELS[action?.kind] || ACTIVITY_LABELS.get(action?.kind) || action?.kind);
    if (activity.latest) {
      if (activity.latest.name !== assignedName) rowValue(facts, 'Last decision by', activity.latest.name);
      rowValue(facts, 'Chosen action', activity.latest.chose);
      rowValue(facts, 'Result', decisionWordsFor(models, subjectId));
    }
    content.append(facts);
    if (!activity.latest) content.append($('p', 'No AI decisions have been recorded for this character.', 'es-note'));
    else if (activity.latest.requestId) content.append(button('See decision inputs and result', () => openDecision(activity.latest), 'es-action', 'D'));
    if (activity.events.length) {
      const records = $('details', '', 'es-record'); records.append($('summary', 'Recent actions'));
      for (const event of activity.events) records.append($('p', event.document.summary, 'es-note'));
      content.append(records);
    }
    if (!observerOnly) {
      if (readiness.playing) content.append(button('Pause world', () => void pauseWorld(), 'es-action'));
      else { const run = button('Run world', () => void startAI(currentChoice()?.model), 'es-action'); run.disabled = !readiness.ready || busy; content.append(run); }
    }
    content.append($('p', observerOnly ? 'This viewer shows recorded activity. Run controls are unavailable here.' : 'Running advances the characters in this world.', 'es-note'));
    if (activityFailure) content.append($('p', activityFailure, 'es-message'));
  }
  async function startAI(model) {
    if (observerOnly || busy || !model) return;
    busy = true; message = ''; render();
    try { playback = await runSelectedModel({ modelsClient: client, controlClient, entry, subjectId, expectedModel: model, current: () => live && isCurrent(), refresh }); message = 'The world is running. Open Activity to see recorded decisions and actions.'; }
    catch (error) { message = error.message || 'The world could not start.'; }
    finally { if (live) { busy = false; render(); if (mode === 'activity') void loadActivity(); } }
  }
  async function pauseWorld() {
    if (observerOnly || busy) return;
    busy = true; render();
    try { const control = await controlClient.read(entry.authoredVersionId); if (!live || !isCurrent()) return; playback = await controlClient.configure(control, 'paused', control.speed); message = 'The world is paused.'; }
    catch (error) { message = error.message || 'The world could not pause.'; }
    finally { if (live) { busy = false; render(); if (mode === 'activity') void loadActivity(); } }
  }
  function renderPicker(content) {
    if (!models) { renderModel(content); return; }
    content.append($('p', 'Choose who makes this character’s decisions', 'es-section-title'));
    content.append($('p', 'Models available in this workspace', 'es-note'));
    const list = $('div', '', 'es-model-list'); list.setAttribute('role', 'radiogroup');
    const options = [{ model: null, name: 'Routine', description: 'Use this character’s routine.' }, ...models.models.map(model => ({ model, name: model.name, description: model.description }))];
    for (const option of options) {
      const selected = picked && (picked.model === null ? option.model === null : option.model && picked.model.provider === option.model.provider && picked.model.modelId === option.model.modelId);
      const card = button(option.name, () => { picked = { model: option.model }; assignmentKey = crypto.randomUUID(); mode = 'model-details'; message = ''; render(); panel.querySelector('h2')?.focus(); }, 'es-model-option');
      card.setAttribute('role', 'radio'); card.setAttribute('aria-checked', String(Boolean(selected))); card.disabled = busy;
      list.append(card);
    }
    content.append(list);
  }
  function renderModelDetails(content) {
    if (picked) {
      const model = picked.model;
      content.append($('p', model?.name || 'Routine', 'es-section-title'));
      if (model) {
        content.append($('p', model.description, 'es-note'));
        content.append($('p', model.providerDescription, 'es-note'));
        const data = $('dl', '', 'es-properties');
        const refusal = model.refusal || models.hostRefusal;
        rowValue(data, 'Connection', refusal === 'provider_credential_absent' ? 'Not connected' : refusal ? 'Unavailable' : 'Connected');
        if (model.price) { rowValue(data, 'Input / 1M tokens', '$' + model.price.input); rowValue(data, 'Output / 1M tokens', '$' + model.price.output); }
        const budget = rawRole()?.budget;
        if (budget?.usd_per_hour) rowValue(data, 'World limit / hour', '$' + Number(budget.usd_per_hour).toFixed(2));
        content.append(data);
      }
      content.append($('p', 'AI starts when the service is connected and the world is running.', 'es-note'));
      const current = currentChoice()?.model || null;
      const unchanged = model === null ? current === null : current && current.provider === model.provider && current.modelId === model.modelId;
      const readyToRun = model && modelRunState(models, playback, subjectId, model).ready;
      if (readyToRun) content.append($('p', 'Running advances the characters in this world.', 'es-note'));
      const save = button(busy ? 'Saving…' : unchanged ? model ? 'Already assigned' : 'Routine selected' : model ? readyToRun ? 'Assign and run world' : 'Assign model' : 'Use routine', () => void saveAssignment(Boolean(readyToRun)), 'es-action', 'Enter');
      save.disabled = busy || !canAssign() || Boolean(unchanged); content.append(save);
    }
  }
  async function loadModels() {
    try {
      const [view, raw, control] = await Promise.all([client.read(entry.authoredVersionId), read('/world/versions/' + encodeURIComponent(entry.authoredVersionId) + '/models?world_id=' + encodeURIComponent(entry.worldId)), controlClient.read(entry.authoredVersionId)]);
      if (raw.profile !== 'exulanica.world-models/v1' || raw.world_id !== entry.worldId || raw.version_id !== entry.authoredVersionId || raw.roles.find(role => role.key === candidate.role_key)?.view?.society_id !== view.societyId) throw Error('Model information could not be verified.');
      if (!live) return; models = view; roleRead = raw; playback = control; modelFailure = ''; render();
    } catch (error) { if (live) { modelFailure = 'Model information could not be loaded. Try again.'; render(); } }
  }
  async function saveAssignment(runAfter = false) {
    if (busy || !picked || !canAssign()) return;
    busy = true; message = ''; render();
    let saved = false;
    const chosen = picked.model, key = assignmentKey || (assignmentKey = crypto.randomUUID());
    const request = ++requestSerial;
    try {
      const { fresh: refreshed, verified } = await recordEntityModel({ entry, subjectId, selected: chosen, key, refresh, client, current: () => live && isCurrent() && request === requestSerial });
      if (!live || request !== requestSerial) return;
      saved = true; models = verified; offer = refreshed.offer; inventory = refreshed.inventory; row = refreshed.row;
      if (chosen && runAfter) playback = await runSelectedModel({ modelsClient: client, controlClient, entry, subjectId, expectedModel: chosen, current: () => live && isCurrent(), refresh });
      mode = 'summary'; picked = null; assignmentKey = null; message = chosen ? runAfter ? 'Model assigned. The world is running.' : 'Model assigned. Connect the AI service and run the world to begin.' : 'Model assignment removed.';
    } catch (error) {
      if (!live) return;
      message = saved && runAfter ? 'Model assigned. The world did not start: ' + error.message : error.code ? choiceRefusalWords(error.code, error.message) : error.submitted ? 'The assignment could not be confirmed. Refresh, or retry this same choice.' : error.message || problemSentence(error);
    } finally { busy = false; if (live) render(); }
  }
  function openDecision(decision) {
    decisionReturn = mode; mode = 'decision'; ++activityEpoch; clearTimeout(activityTimer); render(); void loadDecision(decision);
  }
  async function loadDecision(decision) {
    const request = ++requestSerial;
    try {
      const data = await client.readDecision(entry.authoredVersionId, decision.requestId);
      const detail = decisionView(data, entry, subjectId);
      if (!live || request !== requestSerial || mode !== 'decision') return;
      const content = panel.querySelector('.es-content'); content.replaceChildren();
      const facts = $('dl', '', 'es-properties'); rowValue(facts, 'Model', decision.name); rowValue(facts, 'Result', decision.chose || 'No action selected'); rowValue(facts, 'Record status', data.status === 'completed' ? 'Recorded' : 'Pending'); content.append(facts);
      if (detail.options.length) {
        const options = $('details', '', 'es-record'); options.append($('summary', 'Actions it could choose'));
        const list = $('ul'); for (const words of detail.options) list.append($('li', words)); options.append(list); content.append(options);
      }
      if (detail.context) { const input = $('details', '', 'es-record'); input.append($('summary', 'Recorded inputs'), $('pre', JSON.stringify(detail.context, null, 2))); content.append(input); }
      const details = $('details', '', 'es-record'); details.append($('summary', 'Full decision record'), $('pre', JSON.stringify(data, null, 2))); content.append(details);
    } catch (error) { if (live && mode === 'decision') { message = 'The recorded decision could not be loaded. Try again.'; render(); } }
  }
  function renderDecision(content) { content.append($('p', 'Loading recorded decision…', 'es-note')); }
  render(); panel.querySelector('h2').focus({ preventScroll: true });
  if (offer.subject.kind?.sha256) void openThingLibrary(credentials).then(library => library.kindDocument(offer.subject.kind)).then(document => { if (live) { kind = document; render(); } }).catch(() => { if (live) { kindFailure = 'Physical properties unavailable.'; render(); } });
  else kind = {};
  return {
    dispose() { live = false; ++requestSerial; ++activityEpoch; clearTimeout(activityTimer); },
    key(event) {
      if (mode === 'companion' && !busy && !companionAnswer && ['Digit1','Digit2','Digit3'].includes(event.code)) { event.preventDefault(); const aspect = ['who','doing','why'][Number(event.code.slice(-1)) - 1]; void askCompanion(aspect, {who:'Who is this?',doing:'What is it doing?',why:'Why is it doing that?'}[aspect]); return true; }
      if (!observerOnly && !busy && row.scene?.type === 'being' && event.code === 'KeyC') { event.preventDefault(); mode = 'companion'; render(); return true; }
      if (event.target?.closest?.('input,textarea,select')) return false;
      if (event.code === 'Escape' && (mode !== 'summary' || tab !== 'properties')) { event.preventDefault(); back(); return true; }
      if (!busy && candidate && event.code === 'KeyM') { event.preventDefault(); if (tab === 'model' && mode === 'summary' && canAssign()) { mode = 'pick'; picked = null; render(); } else if (tab === 'properties') openBehavior(); return true; }
      if (!busy && tab === 'model' && event.code === 'KeyA') { event.preventDefault(); openActivity(); return true; }
      if (!busy && tab === 'model' && ['summary','activity'].includes(mode) && event.code === 'KeyD') { const decision = models?.latest.find(item => item.subjectId === subjectId); if (decision?.requestId) { event.preventDefault(); openDecision(decision); return true; } }
      if (!busy && tab === 'model' && candidate && event.code === 'KeyR') { event.preventDefault(); message = ''; void loadModels(); return true; }
      if (!busy && mode === 'model-details' && picked && event.code === 'Enter' && !event.target?.closest?.('button')) { event.preventDefault(); void saveAssignment(Boolean(picked.model && modelRunState(models, playback, subjectId, picked.model).ready)); return true; }
      return false;
    },
  };
}

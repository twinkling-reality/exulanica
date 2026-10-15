// History's rows, from the reads alone (pure, checked in verify-history.mjs): every change of a world
// version, newest first, each with its time, its row words, its timeline mark, the money it spent
// and what the chosen view says of it. Edits are worded by build mode's own sentences (one sentence
// for one change, DESIGN's W2); the rest by history-words.mjs.

import {
  COMPARE_MARK,
  compareWords,
  cost,
  creationWords,
  modelMark,
  modelWords,
  personalityWords,
  runFacts,
  runHappened,
  runMark,
  runWords,
} from './history-words.mjs';

const at = (text) => {
  const value = Date.parse(text);
  return Number.isFinite(value) ? value : null;
};

/** Build mode's edits as rows: its own sentence, never a distance the log does not keep. */
function editRows(edits, wordsOf) {
  return edits
    .map((edit) => ({ edit, time: at(edit.recorded_at) }))
    .filter(({ time }) => time !== null)
    .map(({ edit, time }) => {
      const words = wordsOf(edit, edits);
      return { id: `edit:${edit.edit_id}`, kind: 'edit', at: time, words, mark: words, cost: '' };
    });
}

/** A run of models: its minutes, whose models, what it spent; the facts and counts for the chosen view. */
function runRows(runs, names) {
  return runs
    .map((run) => ({ run, time: at(run.opened_at) }))
    .filter(({ time }) => time !== null)
    .map(({ run, time }) => {
      const who = run.subjects.map((subject) => names.subject(subject));
      return {
        id: `run:${run.session_id}`,
        kind: 'run',
        at: time,
        words: runWords(run.minutes, who.length ? who : ['a character']),
        mark: runMark(run.minutes),
        cost: cost(run.spent),
        models: run.models,
        facts: runFacts({ from: run.from, to: run.to, decisions: run.decisions, spent: run.spent, limit: run.limit }),
        ended: run.ended ?? null,
        happened: runHappened(run.decisions, run.done),
      };
    });
}

/** Model choices of a model or the routine; a person's play and an outside program are not changes of model. */
function modelRows(choices, names) {
  return choices
    .filter((choice) => !choice.ended && (choice.decider.kind === 'model' || choice.decider.kind === 'routine'))
    .map((choice) => ({ choice, time: at(choice.recorded_at) }))
    .filter(({ time }) => time !== null)
    .map(({ choice, time }) => {
      const name = choice.subjects.length === 1
        ? names.subject(choice.subjects[0])
        : `${choice.subjects.length} characters`;
      const modelName = choice.model ? choice.model.name : null;
      return {
        id: `model:${choice.choice_seq}`,
        kind: 'model',
        at: time,
        words: choice.subjects.length === 1
          ? modelWords(name, modelName)
          : `Changed ${name}' models to ${modelName ?? 'Routine'}`,
        mark: choice.subjects.length === 1 ? modelMark(name) : `Changed ${name}' models`,
        cost: '',
        models: modelName ? [modelName] : [],
      };
    });
}

/** Personalities: the first record of a being wrote one, a record stating nothing cleared it. */
function characterRows(records, names) {
  const seen = new Set();
  return [...records]
    .sort((a, b) => a.revision - b.revision)
    .map((record) => {
      const time = at(record.written_at);
      const states = record.states_name || record.states_about;
      const change = !states ? 'cleared' : seen.has(record.placed_id) ? 'changed' : 'wrote';
      seen.add(record.placed_id);
      if (time === null) return null;
      const words = personalityWords(names.placed(record.placed_id), change);
      return { id: `character:${record.placed_id}:${record.revision}`, kind: 'personality', at: time, words, mark: words, cost: '' };
    })
    .filter(Boolean);
}

/** A comparison of two models: drawn as a branch named by its models. */
function compareRows(comparisons) {
  return comparisons
    .map((comparison) => ({ comparison, time: at(comparison.created_at) }))
    .filter(({ time }) => time !== null)
    .map(({ comparison, time }) => ({
      id: `compare:${comparison.comparison_id}`,
      kind: 'compare',
      at: time,
      words: compareWords(comparison.subject),
      mark: COMPARE_MARK,
      cost: cost(comparison.spent),
      branches: comparison.models.slice(0, 2),
    }));
}

/**
 * Every row of a version's History, newest first. `reads` holds what the page read (each list may
 * be empty); `names` says what a society subject and a placed thing are called; `wordsOf` is build
 * mode's change sentence for an edit.
 */
export function historyRows(reads, names, wordsOf) {
  const rows = [
    ...editRows(reads.edits ?? [], wordsOf),
    ...runRows(reads.runs ?? [], names),
    ...modelRows(reads.models ?? [], names),
    ...characterRows(reads.characters ?? [], names),
    ...compareRows(reads.comparisons ?? []),
  ];
  const creation = reads.creation;
  if (creation && at(creation.at) !== null) {
    const words = creationWords(creation.readyWorld ?? null);
    rows.push({ id: 'creation', kind: 'creation', at: at(creation.at), words, mark: words, cost: cost(creation.spent) });
  }
  return rows.sort((a, b) => b.at - a.at || a.id.localeCompare(b.id));
}

/** The rows grouped under their day headings, newest first: [{ heading, rows }]. */
export function byDay(rows, headingOf) {
  const days = [];
  for (const row of rows) {
    const heading = headingOf(row.at);
    const last = days[days.length - 1];
    if (last && last.heading === heading) last.rows.push(row);
    else days.push({ heading, rows: [row] });
  }
  return days;
}

/**
 * The marks the timeline draws: at most `most` rows around the chosen one, oldest first, each placed
 * evenly across the line; "Now" is drawn after them by the page. A comparison carries its branches.
 */
export function timelineMarks(rows, chosenId, most) {
  const chronological = [...rows].reverse();
  const index = Math.max(0, chronological.findIndex((row) => row.id === chosenId));
  const start = Math.max(0, Math.min(index - Math.floor((most - 1) / 2), chronological.length - most));
  return chronological.slice(start, start + most).map((row, position) => ({
    id: row.id,
    words: row.mark,
    at: row.at,
    position,
    chosen: row.id === chosenId,
    branches: row.branches ?? null,
    above: position % 2 === 0,
  }));
}

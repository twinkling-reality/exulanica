import { assertSelectedOffer } from './entity-inspection.mjs';
import { assignmentSubject, offeredModel } from './entity-properties.mjs';

/** Record one explicit assignment, then verify that exact entity and model through a fresh read. */
export async function recordEntityModel({ entry, subjectId, selected, key, refresh, client, current }) {
  let submitted = false;
  try {
    const fresh = await refresh();
    // A being with an offer is held to it; one without (a town's resident) to its row's role link.
    if (fresh.offer) assertSelectedOffer(fresh.offer, entry, fresh.row);
    const target = assignmentSubject(fresh.inventory, fresh.row, fresh.offer);
    const available = await client.read(entry.authoredVersionId);
    if (!current()) throw Error('This inspection is closed. Nothing was sent.');
    if (!target || target.subjectId !== subjectId || !available.takesModelChoices || !offeredModel(available, selected)) throw Error('This entity or model changed. Refresh and choose again.');
    submitted = true;
    await client.choose(entry.authoredVersionId, [target.subjectId], selected, key);
    const verified = await client.read(entry.authoredVersionId);
    const actual = verified.choices.find(choice => choice.subjectId === subjectId)?.model || null;
    if (selected === null ? actual !== null : !actual || actual.provider !== selected.provider || actual.modelId !== selected.modelId) throw Error('The assignment could not be verified.');
    return { fresh, verified };
  } catch (error) {
    const failure = Error(error.message || 'The assignment could not be saved.');
    failure.code = error.code; failure.submitted = submitted; throw failure;
  }
}

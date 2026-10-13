const QUESTIONS = Object.freeze({ who: 'Who is this?', doing: 'What is it doing?', why: 'Why is it doing that?' });

/** These native structured questions read society records; they do not ask a provider. */
export async function askEntityCompanion({ aspect, entry, row, client, refresh, current }) {
  if (!Object.hasOwn(QUESTIONS, aspect) || row.scene?.type !== 'being') throw Error('This question is unavailable for this entity.');
  const fresh = await refresh();
  if (!current() || fresh.row.key !== row.key || fresh.row.scene?.id !== row.scene.id
    || fresh.inventory.world_id !== entry.worldId || fresh.inventory.version_id !== entry.authoredVersionId) throw Error('The selected entity changed. Open it again.');
  const answer = await client.ask(QUESTIONS[aspect], null,
    { versionId: entry.authoredVersionId, inhabitantId: row.scene.id }, { scope: 'selected', aspect });
  if (!current()) throw Error('The question is no longer open.');
  if ((answer.calls || []).length || (answer.simulation || []).some(citation => citation.versionId !== entry.authoredVersionId)) throw Error('This answer could not be verified as a record of this world.');
  return { answer, fresh };
}

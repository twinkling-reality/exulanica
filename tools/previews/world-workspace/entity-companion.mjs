// The questions a request sends, as the Companion's aspects have always been asked; the server
// answers by aspect. On screen they call the character by name or kind (WORDS-CATALOG-FIXES 3).
const QUESTIONS = Object.freeze({ who: 'Who is this?', doing: 'What is it doing?', why: 'Why is it doing that?' });

/** The aspects in the order Ask lists them. */
export const ASK_ASPECTS = Object.freeze(['who', 'doing', 'why']);

/** "Who is Teo?", "What is the resident doing?", "Why is Teo doing that?" */
export function askWords(aspect, who) {
  if (aspect === 'who') return `Who is ${who.within}?`;
  if (aspect === 'doing') return `What is ${who.within} doing?`;
  if (aspect === 'why') return `Why is ${who.within} doing that?`;
  throw Error('This question is unavailable.');
}

/** Ask's own words for why it shows no answer, marked so the page shows them as they are rather than its one failure line. */
const said = words => Object.assign(Error(words), { plain: true });

/** These native structured questions read society records; they do not ask a provider. */
export async function askEntityCompanion({ aspect, entry, row, client, refresh, current }) {
  if (!Object.hasOwn(QUESTIONS, aspect) || row.scene?.type !== 'being') throw said('This question is unavailable here.');
  const fresh = await refresh();
  if (!current() || fresh.row.key !== row.key || fresh.row.scene?.id !== row.scene.id
    || fresh.inventory.world_id !== entry.worldId || fresh.inventory.version_id !== entry.authoredVersionId) throw said('The world changed a moment ago. Ask again.');
  const answer = await client.ask(QUESTIONS[aspect], null,
    { versionId: entry.authoredVersionId, inhabitantId: row.scene.id }, { scope: 'selected', aspect });
  if (!current()) throw said('The question is no longer open.');
  if ((answer.calls || []).length || (answer.simulation || []).some(citation => citation.versionId !== entry.authoredVersionId)) throw said('This answer could not be checked against this world, so it is not shown.');
  return { answer, fresh };
}

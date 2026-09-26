/**
 * What a world style refusal says to do next once the world's live appearance is no longer the one
 * the page shows (`WorldStyleClient.requiresReconciliation`), which holds every change back until
 * the saved version is restored from Version history over the change made elsewhere. One sentence,
 * whatever found the move, because the same step is right after either kind of writer:
 *
 * - After a writer that left the saved world alone, such as an agent writing through the API, the
 *   restore goes through, and so does the next change, with no reload.
 * - After another page that advanced the saved world, the restore is refused with "Reload before
 *   trying again", and after the reload the saved world is live and the next change goes through.
 *
 * A restore that another change overtook in between is refused as stale, and the page shows the
 * latest version and asks for the restore target again. A reload first would not do: after a
 * writer that left the saved world alone it reopens the same saved version, which Version history
 * then marks current and cannot restore. The client's refusals (`StaleProposalError`) and the
 * page's (`composition/appearance.ts`) end with this sentence, so it lives here, once.
 */
export const RESTORE_BEFORE_CHANGING =
  'To keep changing your world here, restore your saved version in Version history, which replaces '
  + 'the change made elsewhere, and reload if it asks you to.';

/** Never combine a selected identity with another world's or subject's offer. */
export function assertSelectedOffer(offer, entry, row) {
  if (!offer || offer.profile !== 'exulanica.subject-offer/v1'
    || offer.world_id !== entry.worldId || offer.version_id !== entry.authoredVersionId
    || offer.subject?.ref !== row.detail?.bind?.ref) {
    throw Error('This world could not be read. Try again.');
  }
}

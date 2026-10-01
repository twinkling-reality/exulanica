/**
 * What the character studio says when a look cannot be drawn or saved.
 *
 * The codes are the server's `render_status` values for a saved look
 * (`exulanica/world/character_appearance_repository.py`, `character_body_preparations.py`) and the
 * studio's own (`people_catalog_unavailable`, `catalog_unavailable`). A code with no words here
 * gets the generic sentence; the code itself is never the status text.
 */

export const CHARACTER_STATUS_WORDS: Readonly<Record<string, string>> = {
  people_catalog_unavailable: 'The people you can look like are not available on this installation right now. Try again later.',
  catalog_unavailable: 'Your saved look comes from a set of looks this installation no longer serves. Choose a look to wear instead.',
  no_prepared_representation: 'Your saved look has not been prepared for this world yet. Choose a look to wear, or try again later.',
  preparation_unavailable: 'Looks cannot be prepared on this installation right now. Choose one of the ready looks instead.',
  asset_store_unavailable: 'The files for your saved look cannot be read right now. Try again in a moment.',
  asset_bytes_unavailable: 'The files for your saved look are missing on this installation. Choose a look to wear instead.',
  asset_integrity_unavailable: 'The files for your saved look did not match what was saved, so it is not drawn. Choose a look to wear instead.',
  asset_withdrawn_or_unreviewed: 'Part of your saved look was withdrawn, so it is not drawn. Choose a look to wear instead.',
  saved_look_options_not_offered: 'Your saved look uses options this studio no longer offers, so it opens on the nearest look it offers.',
};

const UNKNOWN_STATUS = 'This look cannot be drawn right now. Choose another look, or try again later.';

/** The studio's words for a status code; never the code. */
export function characterStatusWords(code: string): string {
  return CHARACTER_STATUS_WORDS[code] ?? UNKNOWN_STATUS;
}

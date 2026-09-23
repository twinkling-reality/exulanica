/**
 * How many people are drawn in full at once, the player included; everyone beyond is drawn in a
 * far form.
 *
 * Measured 2026-09-23 on this machine's release build: a production bundle (release engine,
 * index-Bdu_k0ox.js, built from base e9dee3c2 with the character lane's work) in headless Chrome 153
 * on an Apple M5 Max at 1440x900, over the Flatiron district in third person with the player drawn in
 * full, a crowd of 128, 20 s a configuration, two repeats in opposite orders, every configuration
 * through the machine-wide timing gate. With 60 of the crowd in full beside the player, frame work at
 * the 95th percentile was 7.5 and 7.6 ms; with 64 it was 8.8 and 7.6 ms. This is the largest count
 * every repeat of which stays within half a 60 Hz frame, leaving the rest for the city, the society,
 * the interface and slower machines. The run and its harness are retained in
 * test/character-evidence/frame-budget-production-2026-09-23.log.txt, which
 * character-budget.test.ts reads. A development server serves the debug engine instead; the
 * development-preview run of 2026-09-17, on another machine with that engine, measured 24 and is
 * retained beside it.
 */
export const NEAR_CHARACTER_BUDGET = 61;

/**
 * Places in that budget the player's own body holds.
 *
 * The budget counts everyone drawn in full, the player included, and the player is drawn in full
 * whenever their body is on screen. A society display therefore fills at most the rest. In first
 * person the place stays empty rather than passing to an inhabitant who would lose it again the
 * moment the camera pulls back.
 */
export const PLAYER_NEAR_PLACES = 1;

/** Full places a society display may give its inhabitants. */
export const NEAR_INHABITANT_BUDGET = NEAR_CHARACTER_BUDGET - PLAYER_NEAR_PLACES;

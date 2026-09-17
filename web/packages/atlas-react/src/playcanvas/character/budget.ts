/**
 * How many people are drawn in full at once; everyone beyond is drawn in a far form.
 *
 * Measured 2026-09-17 in the development preview at 1440x900 (headless Chrome 152, Apple M3 Pro) with
 * a crowd of 128 people all on screen, 20 s a configuration, on a quiet machine (one-minute load 5.6
 * to 6.9): a full character costs 0.18 ms of frame work at the 95th percentile and a far figure about
 * 0.01 ms, so 24 full characters cost 7.5 ms of the 16.7 ms frame and 36 cost 9.0 ms. This is the
 * largest measured count that stays within half a frame, leaving the rest for the city, the society,
 * the interface and slower machines. The full table is retained in
 * test/character-evidence/frame-budget-2026-09-17.log.txt, which character-budget.test.ts reads.
 */
export const NEAR_CHARACTER_BUDGET = 24;

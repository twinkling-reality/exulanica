/**
 * How many people are drawn in full at once; everyone beyond is drawn in a far form.
 *
 * This is the resident cap the native runtime used to enforce by refusing larger sets, kept until
 * the frame measurement at 1440x900 replaces it with a measured number.
 */
export const NEAR_CHARACTER_BUDGET = 24;

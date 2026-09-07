/**
 * What the world may draw of a person, decided in one place.
 *
 * Three predicates, and the reason they are functions rather than three comparisons written at
 * each draw site: there are three separate places a photograph reaches the screen -- the world
 * veils, the reconstruction inspector, and the citation image in the detail pane -- and a rule
 * copied three times is a rule that will be corrected in two of them.
 *
 * Every default here is the hiding one. An unrecognised state draws a silhouette, an absent
 * review state reads as `unscreened`, and a missing region list is treated as "nobody has looked"
 * rather than "there is nobody here". Those two are opposite facts that look identical in an
 * empty array, and resolving the ambiguity toward drawing is how somebody who never agreed to
 * appear ends up on screen.
 */

export type PersonState = 'unknown' | 'present' | 'shown' | 'hidden' | 'withdrawn';
export type PersonReviewState = 'unscreened' | 'screened' | 'stale';

export interface PersonRegionView {
  readonly region_id: string;
  readonly state: PersonState;
  readonly silhouette_ppm: readonly (readonly number[])[];
  readonly display_name: string | null;
  readonly subject_id: string | null;
}

/** The one state whose pixels may be drawn. Everything else is a silhouette. */
export function drawsPixels(state: unknown): boolean {
  return state === 'shown';
}

/**
 * Whether this person is drawn as an outline instead of as themselves.
 *
 * `withdrawn` is deliberately excluded: a withdrawn person is absent from the world rather than
 * outlined in it, because an outline still says "somebody was standing here", which is the
 * presence claim they took back.
 */
export function drawsSilhouette(state: unknown): boolean {
  return state === 'unknown' || state === 'present' || state === 'hidden';
}

/**
 * Whether a name may be drawn beside this person.
 *
 * Gated on the name having actually arrived, not on the state. The server sends `display_name`
 * only when naming was consented, so a name present here has already passed that consent; a
 * person may be named on a silhouette, which is exactly what "present and named but not shown"
 * looks like.
 */
export function drawsName(region: Pick<PersonRegionView, 'display_name'>): boolean {
  return typeof region.display_name === 'string' && region.display_name.length > 0;
}

/** Whether a photograph may be shown at all, or must be withheld pending a screening. */
export function mayDrawPhotograph(
  reviewState: unknown,
  regions: readonly PersonRegionView[] | undefined,
): boolean {
  if (reviewState !== 'screened') {
    return false;
  }
  return (regions ?? []).every((region) => drawsPixels(region.state));
}

/** Every person in this photograph who is not being drawn. */
export function hiddenRegions(
  regions: readonly PersonRegionView[] | undefined,
): readonly PersonRegionView[] {
  return (regions ?? []).filter((region) => !drawsPixels(region.state));
}

/**
 * The status sentence's person clause, or null when there is nothing to say.
 *
 * Says "not screened" rather than "no people" for an unscreened scene. Reporting zero hidden
 * people for a photograph nobody has looked at is the same false reassurance the old yes-or-no
 * gate gave, in a different place.
 */
export function personPresenceSentence(input: {
  readonly hiddenPersonCount: number;
  readonly maskedMemberCount: number;
  readonly unscreenedMemberCount: number;
}): string | null {
  const parts: string[] = [];
  if (input.hiddenPersonCount > 0) {
    const people = input.hiddenPersonCount === 1 ? '1 person is' : `${input.hiddenPersonCount} people are`;
    const photographs =
      input.maskedMemberCount === 1 ? '1 photograph' : `${input.maskedMemberCount} photographs`;
    parts.push(`${people} hidden across ${photographs}; their regions are blank, not reconstructed.`);
  }
  if (input.unscreenedMemberCount > 0) {
    const photographs =
      input.unscreenedMemberCount === 1 ? '1 photograph has' : `${input.unscreenedMemberCount} photographs have`;
    parts.push(`${photographs} not been screened for people and ${input.unscreenedMemberCount === 1 ? 'is' : 'are'} not drawn.`);
  }
  return parts.length === 0 ? null : parts.join(' ');
}

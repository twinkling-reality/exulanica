// The words of keeping a world from History (DESIGN's WORDS.md H7 and H12; the R23 build sheet, sections 2, 11 and
// 13): [K] Keep in a project asks nothing first; [G] Keep on GitHub asks H12's question as a card on the light page.
// Refusals are sentences by code, drawn in the refusal ink; no sentence names a key.

export const KEEP_WORDS = Object.freeze({
  keepInProject: 'Keep in a project',
  keepOnGitHub: 'Keep on GitHub',
  create: 'Create',
  tryAgain: 'Try again',
  back: 'Back',
  question: 'Keep this world in a new private repository on your GitHub account',
  account: 'GitHub account',
  name: 'Repository name',
  private: 'Private: only you can see it.',
  readable: 'What goes there: this world\'s kept changes, with names and the words people wrote.',
  notReadable: 'What goes there: this world\'s kept changes, without names or the words people wrote.',
  signIn: 'Exulanica uses your own GitHub sign-in on this computer and never sees or keeps it.',
  madeOnce: 'A private repository, made once.',
  checking: 'Checking your GitHub account…',
  putting: 'Putting it on GitHub…',
  refusals: Object.freeze({
    name_taken: 'You already have a repository with that name. Choose another.',
    changed: 'Your GitHub account or the name changed since it was checked, so nothing was made. Try again.',
    gh_missing: 'GitHub\'s command line tool, gh, is not on this computer. Install it and sign in once, then try again.',
    not_signed_in: 'Sign in to GitHub on this computer once (gh auth login), then try again.',
    not_private: 'GitHub did not make it private, so nothing was sent. Check it on GitHub.',
    rights_refused: 'Part of this world may not leave this computer, so nothing was sent.',
    failed: 'This could not be put on GitHub. Look on GitHub before you try again.',
  }),
});

/** The longest repository name GitHub takes. */
export const NAME_MOST = 100;
/** A repository name GitHub takes: letters, digits, "-", "_" and ".", not "." or "..". */
export const NAME_PATTERN = /^[A-Za-z0-9_.-]{1,100}$/;

export function nameAllowed(name) {
  return NAME_PATTERN.test(name) && name !== '.' && name !== '..';
}

/** The name field's count: "28 of 100". */
export function nameCount(name) {
  return `${name.length} of ${NAME_MOST}`;
}

/**
 * How often changes go once the repository exists: "From then on each change is sent by itself, at most 4 times a
 * day. If anything looks wrong, sending stops and History says so." The bound is the follower's own, as its status
 * serves it; where it serves none the sentence says no number.
 */
export function sendingWords(perDay) {
  const bound = Number.isSafeInteger(perDay) && perDay > 0 ? `, at most ${perDay === 1 ? 'once' : `${perDay} times`} a day` : '';
  return `From then on each change is sent by itself${bound}. If anything looks wrong, sending stops and History says so.`;
}

/** Why a publication could not go on, by its code; an unknown code says the general failure. */
export function refusalWords(code) {
  return KEEP_WORDS.refusals[code] ?? KEEP_WORDS.refusals.failed;
}

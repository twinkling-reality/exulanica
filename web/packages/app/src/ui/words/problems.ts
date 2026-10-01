/**
 * How a refusal is said: what happened, then what to do next.
 *
 * The browser's transport keeps a problem's `code` and `detail` (`ApiError`); its message is
 * "code: detail", which is for logs, not people. A surface asks here for the words of a problem
 * and gets two sentences with no code in them, plus the record (code, status, detail) that only
 * the technical details show. A code this table does not know gets the caller's own fallback, or
 * the generic pair, never the code itself.
 *
 * Codes that only one surface meets keep their words with that surface's own table; this table
 * holds the ones any request can meet (the interface packet's request-time refusals) and the
 * transport's own failures.
 */

import { ApiError } from '@exulanica/graph-client';
import type { TechnicalRecord } from '../system/components.js';

export interface ProblemWords {
  readonly happened: string;
  readonly next: string;
}

/** Refusals any request can meet, whichever surface made it. */
export const REQUEST_REFUSALS: Readonly<Record<string, ProblemWords>> = {
  busy: { happened: 'The world was busy for a moment, so nothing was changed.', next: 'Try again.' },
  capacity_exhausted: {
    happened: 'This installation is at its limit right now, so nothing was changed.',
    next: 'Try again in a minute.',
  },
  workspace_capacity_exhausted: {
    happened: 'Your workspace is doing as much as it may at once, so nothing was changed.',
    next: 'Try again when something you started has finished.',
  },
  derivative_queue_full: {
    happened: 'Photos you added earlier are still being processed, so nothing was added.',
    next: 'Try again when they have finished.',
  },
  budget_exceeded: {
    happened: 'The spending allowance for models refused this, so nothing was spent.',
    next: 'Ask the owner of this workspace about its allowance.',
  },
  provider_credential_absent: {
    happened: 'No model can be asked on this installation.',
    next: 'Ask the person who runs it to add one.',
  },
  unknown_reference: {
    happened: 'That is no longer here, or it is not in this workspace.',
    next: 'Reload the page to see what is here now.',
  },
  unauthenticated: { happened: 'This session is no longer signed in.', next: 'Sign in again.' },
  not_authorised: {
    happened: 'Your access does not include this.',
    next: 'Ask the owner of this workspace.',
  },
  operation_denied: {
    happened: 'Your access does not include this.',
    next: 'Ask the owner of this workspace.',
  },
};

/** The transport's own failures: no answer, or an answer it could not read. */
const UNREACHABLE: ProblemWords = {
  happened: 'Exulanica did not answer, so nothing was changed.',
  next: 'Check your connection, then try again.',
};
export const GENERIC_PROBLEM: ProblemWords = {
  happened: 'That could not be done just now, so nothing was changed.',
  next: 'Try again, or look at the technical details.',
};

/** The code of a problem, when it carries one. */
export function problemCode(error: unknown): string | null {
  if (error instanceof ApiError) return error.code;
  if (error !== null && typeof error === 'object' && typeof (error as { code?: unknown }).code === 'string') {
    return (error as { code: string }).code;
  }
  return null;
}

/** The server's detail, without the code the message repeats. */
export function problemDetail(error: unknown): string | null {
  if (error instanceof ApiError) return error.message.replace(`${error.code}: `, '');
  if (error instanceof Error) return error.message;
  return error === undefined || error === null ? null : String(error);
}

/**
 * The words for a problem: the surface's own words for its code first, then the words any request
 * can meet, then the surface's fallback, then the generic pair. Never the code.
 */
export function problemWords(
  error: unknown,
  own: Readonly<Record<string, ProblemWords>> = {},
  fallback: ProblemWords = GENERIC_PROBLEM,
): ProblemWords {
  const code = problemCode(error);
  if (code !== null) {
    const known = own[code] ?? REQUEST_REFUSALS[code];
    if (known !== undefined) return known;
  }
  if (error instanceof TypeError && /fetch|network/i.test(error.message)) return UNREACHABLE;
  return fallback;
}

/** The two sentences as one line, for a status line or a toast. */
export function problemSentence(
  error: unknown,
  own: Readonly<Record<string, ProblemWords>> = {},
  fallback: ProblemWords = GENERIC_PROBLEM,
): string {
  const words = problemWords(error, own, fallback);
  return `${words.happened} ${words.next}`;
}

/** What the technical details show: the code, the status and the server's detail. */
export function problemRecord(error: unknown): TechnicalRecord {
  return {
    code: problemCode(error),
    status: error instanceof ApiError ? error.status : null,
    detail: problemDetail(error),
  };
}

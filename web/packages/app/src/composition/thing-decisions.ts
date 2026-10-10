/**
 * The decisions taken up since the page first read a society, so each can open once under its
 * decider's name in the world (`ThingMarks.showDecision`): what the models read serves as each
 * being's latest decision, watched from read to read.
 *
 * Nothing from before the visit is opened: the first read of a society only notes where each being
 * stands. A decision opens when a minute has taken it up (it was acted on, or not, and why), or at
 * once where its decider was not followed; the same decision never opens twice.
 */

import type { ThingDecision } from '@exulanica/atlas-react/things';
import type { PersonDecision } from '../society-models-api.js';
import { decisionLineWords } from '../ui/society-models.js';

/** What of a being's latest decision has been seen: which decision, and whether a minute had taken it up. */
const seenKey = (decision: PersonDecision): string =>
  `${decision.decisionSeq}:${decision.status}:${decision.disposition ?? ''}`;

export class DecisionWatch {
  private societyId: string | null = null;
  private readonly seen = new Map<string, string>();

  /** The decisions to open now, oldest first; none on the first read of a society. */
  take(societyId: string, latest: readonly PersonDecision[]): ThingDecision[] {
    const first = this.societyId !== societyId;
    if (first) {
      this.societyId = societyId;
      this.seen.clear();
    }
    const opened: { readonly decision: ThingDecision; readonly seq: number }[] = [];
    for (const decision of latest) {
      const key = seenKey(decision);
      if (this.seen.get(decision.subjectId) === key) continue;
      this.seen.set(decision.subjectId, key);
      if (first) continue;
      const chose = decisionLineWords(decision);
      // The decider's own words: none is served by this decision contract, so the place stays empty.
      if (chose !== null) opened.push({ decision: { subjectId: decision.subjectId, chose, said: null }, seq: decision.decisionSeq });
    }
    return opened.sort((a, b) => a.seq - b.seq).map((one) => one.decision);
  }

  reset(): void {
    this.societyId = null;
    this.seen.clear();
  }
}

/** How many beings each kind of decider decides for, and how many are indoors: counted, never ranked. */
export interface DeciderCounts {
  readonly models: number;
  readonly you: number;
  readonly played: number;
  readonly outside: number;
  readonly routine: number;
  /** Beings whose state says they are indoors, whoever decides for them; one that states none is in the street. */
  readonly indoors: number;
}

/**
 * Whether a being's own state says it is indoors. A living town's person states it as the page reads
 * them (`indoors`); a being of a society that records the day states it in its place
 * (`location.indoors`). One that states neither is in the street: nothing else decides it.
 */
export function statedIndoors(being: unknown): boolean {
  if (being === null || typeof being !== 'object') return false;
  const stated = being as { readonly indoors?: unknown; readonly location?: unknown };
  if (stated.indoors === true) return true;
  const place = stated.location;
  return place !== null && typeof place === 'object' && (place as { readonly indoors?: unknown }).indoors === true;
}

/** Count who decides for a society's beings from each one's mark and stated place. */
export function deciderCounts(
  beings: readonly { readonly mark: { readonly kind: string; readonly outside?: true; readonly mine?: boolean } | null; readonly indoors: boolean }[],
): DeciderCounts {
  const counts = { models: 0, you: 0, played: 0, outside: 0, routine: 0, indoors: 0 };
  for (const { mark, indoors } of beings) {
    if (indoors) counts.indoors += 1;
    if (mark === null) counts.routine += 1;
    else if (mark.kind === 'person') counts[mark.mine === true ? 'you' : 'played'] += 1;
    else if (mark.kind === 'from' || mark.outside === true) counts.outside += 1;
    else counts.models += 1;
  }
  return counts;
}

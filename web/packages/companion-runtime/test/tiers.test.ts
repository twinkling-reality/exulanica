import { readdir, readFile } from 'node:fs/promises';
import { describe, expect, it } from 'vitest';
import { ProposalGateError } from '@exulanica/graph-client/mutations';
import { deriveTier } from '@exulanica/graph-client';
import {
  CompanionSession,
  ConfirmationRefusedError,
  MOCK_NOW_MS,
  SNAPSHOT_T2,
  SNAPSHOT_T3,
  TierPolicyError,
  assertBatchable,
  assertMultiSelectable,
  assertOfferable,
  draftOperation,
  finalizeDraft,
  makeDraft,
  sequentialIds,
  tierPolicy,
  unmetRequirements,
  validateTurn,
} from '../src/index.js';
import type { Turn } from '../src/index.js';
import { fullAck, recordingGate } from './harness.js';

describe('the tier is derived from what an operation touches, never declared', () => {
  it('escalates a rename to tier 2 the moment it spans two regions', () => {
    expect(deriveTier('name', 1, 1)).toBe(1);
    expect(deriveTier('name', 1, 2)).toBe(2);
    expect(deriveTier('name', 7, 1)).toBe(2);
    expect(deriveTier('merge', 0, 0)).toBe(2);
    expect(deriveTier('delete', 0, 0)).toBe(3);
  });

  it('gives the same answer through the draft builder, which has no tier parameter', () => {
    const op = draftOperation('name', ['a1', 'a2'], ['i1', 'i2'], { displayName: 'Julie' });
    expect(op.tier).toBe(2);
  });
});

describe('tier 2 cannot be confirmed without its blast radius and its live preview', () => {
  const stageTier2 = () => {
    const { gate, committed } = recordingGate(SNAPSHOT_T3.stateVersion);
    const s = new CompanionSession({ snapshot: SNAPSHOT_T3, gate, ids: sequentialIds() });
    s.advance(MOCK_NOW_MS, 'ent-julie');
    // Julie now spans two regions, so setting her display name everywhere is tier 2.
    const outcome = s.select('enrich_relation:useEverywhere', MOCK_NOW_MS);
    if (outcome.kind !== 'awaiting_confirmation') throw new Error('expected a proposal');
    return { session: s, committed, outcome };
  };

  it('states the blast radius in counts, and names the regions', () => {
    const { outcome } = stageTier2();
    expect(outcome.proposal.maxTier).toBe(2);
    expect(outcome.confirmation.blastRadius).not.toBeNull();
    expect(outcome.confirmation.blastRadius?.islandCount).toBe(2);
    expect(outcome.confirmation.blastRadius?.anchorCount).toBeGreaterThan(0);
    expect(outcome.confirmation.policy.controls).toBe('cancel_and_confirm');
    // "Reversibility stated in words, and true."
    expect(outcome.confirmation.reversible).toBe(true);
  });

  it('refuses the commit when the preview was never shown', async () => {
    const { session: s, outcome, committed } = stageTier2();
    await expect(
      s.commit(outcome.proposal.proposalId, fullAck({ livePreviewShown: false })),
    ).rejects.toThrow(/livePreview.notShown/);
    expect(committed).toEqual([]);
  });

  it('refuses the commit when the confirm control was clicked through immediately', async () => {
    const { session: s, outcome, committed } = stageTier2();
    await expect(
      s.commit(outcome.proposal.proposalId, fullAck({ openForMs: 0 })),
    ).rejects.toBeInstanceOf(ConfirmationRefusedError);
    expect(committed).toEqual([]);
  });

  it('commits once every requirement is met', async () => {
    const { session: s, outcome, committed } = stageTier2();
    await s.commit(outcome.proposal.proposalId, fullAck());
    expect(committed.length).toBe(1);
  });

  it('refuses to batch a tier 2 operation', () => {
    expect(() => assertBatchable(1)).not.toThrow();
    expect(() => assertBatchable(2)).toThrow(TierPolicyError);
    expect(() => assertBatchable(3)).toThrow(TierPolicyError);
  });

  it('refuses to put a tier 2 option in a multi-select set', () => {
    expect(() => assertMultiSelectable(1)).not.toThrow();
    expect(() => assertMultiSelectable(2)).toThrow(TierPolicyError);
  });

  it('rejects a multi-select set that somehow carries a tier 2 option', () => {
    // The test above tests the function. This tests the only CALL of it that can refuse
    // anything, in validateTurn. Measured 2026-09-19: deleting that line left every one of the
    // 2846 tests in web/ passing, so 4.3's "never mix a tier 2 option into a multi-select set"
    // was held in place by nothing. The pool refuses to build such a set, which is why the turn
    // has to be hand-built here, the same way the tier 3 case below builds the turn the pool
    // would never produce.
    const mergeDraft = makeDraft({
      draftId: 'draft-merge',
      origin: 'user_choice',
      rawUtterance: '',
      subjectEntityId: 'ent-julie',
      operations: [draftOperation('merge', ['a1'], ['i1'], {})],
      provenanceSummaryKey: 'provenance.x',
    });
    // Derived, not declared: a merge is tier 2 because of what it is, not because this said so.
    expect(mergeDraft.maxTier).toBe(2);
    // Tier 2 IS offerable from the dialogue surface and this set does require a submit, so
    // neither the tier 3 guard on the line above nor the submit rule can be what answers.
    expect(() => assertOfferable(2, 'dialogue')).not.toThrow();
    const turn: Turn = {
      turnId: 'turn-multi',
      intent: 'resolve_identity',
      subjectEntityId: 'ent-julie',
      subjectAnchorId: 'a1',
      utteranceKey: 'utterance.resolveIdentity',
      utterance: null,
      evidence: [],
      choiceSet: {
        mode: 'multi',
        submitRequired: true,
        options: [
          {
            optionId: 'x:merge',
            kind: 'multi_select',
            textKey: 'option.mergeThesePeople',
            phrasing: null,
            available: true,
            unavailableReasonKey: null,
            tier: mergeDraft.maxTier,
            draft: mergeDraft,
            escape: null,
          },
        ],
      },
      freeTextAllowed: true,
      escapes: [
        {
          optionId: 'escape:skip',
          kind: 'escape',
          textKey: 'escape.skip',
          phrasing: null,
          available: true,
          unavailableReasonKey: null,
          tier: 0,
          draft: null,
          escape: 'skip',
        },
      ],
      stateVersion: 1,
    };
    expect(() => validateTurn(turn)).toThrow(TierPolicyError);
  });
});

/**
 * Calls of `name` in one source text, with comments removed first so a MENTION is not a call.
 *
 * Needed the moment it was written: the pool's own comment explains what
 * `assertOfferable(_, 'dialogue')` refuses, and a scan of raw text counted that sentence as a
 * second call site. The `[^:]` before `//` keeps a URL inside a string from being read as a
 * comment and swallowing the rest of its line.
 */
function countCalls(text: string, name: string): number {
  const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
  const calls = [...code.matchAll(new RegExp(`(?<![.\\w])${name}\\(`, 'g'))].length;
  return calls - (new RegExp(`export function ${name}\\(`).test(code) ? 1 : 0);
}

/** Every call of `name` across every package's `src`, by path, declaration not counted. */
async function callSites(name: string): Promise<Record<string, number>> {
  const root = new URL('../../', import.meta.url);
  const found: Record<string, number> = {};
  const walk = async (dir: URL): Promise<void> => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue;
      const here = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir);
      if (entry.isDirectory()) {
        await walk(here);
        continue;
      }
      const relative = here.pathname.slice(root.pathname.length);
      if (!entry.name.endsWith('.ts') || !relative.includes('/src/')) continue;
      const calls = countCalls(await readFile(here, 'utf8'), name);
      if (calls > 0) found[relative] = calls;
    }
  };
  await walk(root);
  return found;
}

describe('the tier assertions state their own call sites', () => {
  it('counts them from the source: a justification naming a number is a claim', async () => {
    // `assertOfferable` documented itself as called from "three independent places", naming
    // proposal drafting and the initiative gate. Counted 2026-09-19: two places, and neither of
    // those two was one of them. Nothing asserted the count, so the prose and the code drifted
    // with nothing watching. This is that assertion. When a call site is added or removed, fix
    // the docstring in the same change rather than only the expectation here.
    expect(await callSites('assertOfferable')).toEqual({
      'companion-runtime/src/pool.ts': 1,
      'companion-runtime/src/turn.ts': 1,
    });
    // session.ts's is the re-check on submit, which cannot refuse anything: validateTurn has
    // already put the same option through the same assertion. turn.ts's is the live one.
    expect(await callSites('assertMultiSelectable')).toEqual({
      'companion-runtime/src/session.ts': 1,
      'companion-runtime/src/turn.ts': 1,
    });
    // Called from another package entirely, which is why a search of this one reads as zero.
    expect(await callSites('assertBatchable')).toEqual({ 'world-index/src/actions.ts': 1 });
  });

  it('is a scan that can fail, which is the only reason to believe the counts above', () => {
    // The positive control, on the same axis as the negative result: a scan that matched nothing
    // would return {} for all three above and read exactly like agreement.
    expect(countCalls("assertOfferable(3, 'dialogue');\n", 'assertOfferable')).toBe(1);
    const mention = "// what assertOfferable(3, 'dialogue') refuses\n";
    expect(countCalls(mention, 'assertOfferable')).toBe(0);
    expect(countCalls('/* calls assertOfferable(3) */\n', 'assertOfferable')).toBe(0);
    const afterUrl = "const u = 'https://x'; assertOfferable(1, 'd');\n";
    expect(countCalls(afterUrl, 'assertOfferable')).toBe(1);
    expect(countCalls('thing.assertOfferable(1);\n', 'assertOfferable')).toBe(0);
    expect(countCalls('assertOfferableTwice(1);\n', 'assertOfferable')).toBe(0);
    expect(countCalls('export function assertOfferable(t) {}\n', 'assertOfferable')).toBe(0);
  });

  it('finds nothing for a name nothing calls, so an empty answer means absence', async () => {
    expect(await callSites('assertNothingIsNamedThis')).toEqual({});
  });
});

describe('tier 3 is unreachable from the conversation, in any phrasing', () => {
  it('refuses to offer a tier 3 operation from the dialogue surface', () => {
    expect(() => assertOfferable(3, 'dialogue')).toThrow(TierPolicyError);
    expect(() => assertOfferable(3, 'world_index')).not.toThrow();
    expect(tierPolicy(3).offerableFrom).toEqual(['world_index']);
    expect(tierPolicy(3).offerableByInitiative).toBe(false);
  });

  it('rejects a turn that somehow carries a tier 3 option', () => {
    const deleteDraft = makeDraft({
      draftId: 'draft-delete',
      origin: 'user_choice',
      rawUtterance: '',
      subjectEntityId: 'ent-julie',
      operations: [draftOperation('delete', ['a1'], ['i1'], {})],
      provenanceSummaryKey: 'provenance.x',
    });
    const turn: Turn = {
      turnId: 'turn-x',
      intent: 'resolve_identity',
      subjectEntityId: 'ent-julie',
      subjectAnchorId: 'a1',
      utteranceKey: 'utterance.resolveIdentity',
      utterance: null,
      evidence: [],
      choiceSet: {
        mode: 'single',
        submitRequired: false,
        options: [
          {
            optionId: 'x:forget',
            kind: 'exclusive',
            textKey: 'option.forgetThisPerson',
            phrasing: null,
            available: true,
            unavailableReasonKey: null,
            tier: 3,
            draft: deleteDraft,
            escape: null,
          },
        ],
      },
      freeTextAllowed: true,
      escapes: [
        {
          optionId: 'escape:skip',
          kind: 'escape',
          textKey: 'escape.skip',
          phrasing: null,
          available: true,
          unavailableReasonKey: null,
          tier: 0,
          draft: null,
          escape: 'skip',
        },
      ],
      stateVersion: 1,
    };
    expect(() => validateTurn(turn)).toThrow(TierPolicyError);
  });

  it('states what tier 3 must show, and the gate still refuses it in the MVP', async () => {
    const policy = tierPolicy(3);
    expect(policy.requiresTypedDisplayName).toBe(true);
    expect(policy.requiresMediaRetentionStatement).toBe(true);
    expect(policy.requiresCitationLossCount).toBe(true);
    expect(policy.inMvp).toBe(false);

    const unmet = unmetRequirements(
      3,
      fullAck({ typedDisplayName: 'wrong name' }, 'world_index'),
      'Julie',
    );
    expect(unmet).toContain('typedName.mismatch');
    expect(unmet).toContain('tier.outOfMvpCut');

    const { gate } = recordingGate();
    const proposal = finalizeDraft(
      makeDraft({
        draftId: 'draft-delete',
        origin: 'user_choice',
        rawUtterance: '',
        subjectEntityId: 'ent-julie',
        operations: [draftOperation('delete', [], [], {})],
        provenanceSummaryKey: 'provenance.x',
      }),
      'proposal-delete',
      'turn-x',
      11,
    );
    gate.stage(proposal);
    await expect(gate.commit('proposal-delete')).rejects.toBeInstanceOf(ProposalGateError);
  });

  it('never marks a delete reversible', () => {
    const draft = makeDraft({
      draftId: 'draft-delete',
      origin: 'user_choice',
      rawUtterance: '',
      subjectEntityId: 'ent-julie',
      operations: [draftOperation('delete', [], [], {})],
      provenanceSummaryKey: 'provenance.x',
    });
    expect(draft.reversible).toBe(false);
  });
});

describe('tier 1 is one click and no typing', () => {
  it('needs no blast radius, no preview and no delay', async () => {
    const policy = tierPolicy(1);
    expect(policy.controls).toBe('single_save');
    expect(policy.requiresBlastRadius).toBe(false);
    expect(policy.confirmEnabledAfterMs).toBe(0);
    expect(policy.undoToast).toBe(true);

    const { gate, committed } = recordingGate(SNAPSHOT_T2.stateVersion);
    const s = new CompanionSession({ snapshot: SNAPSHOT_T2, gate, ids: sequentialIds() });
    s.advance(MOCK_NOW_MS, 'ent-julie');
    const outcome = s.select('confirm_continuity:differentPeople', MOCK_NOW_MS);
    if (outcome.kind !== 'awaiting_confirmation') throw new Error('expected a proposal');
    expect(outcome.proposal.maxTier).toBe(1);

    await s.commit(
      outcome.proposal.proposalId,
      fullAck({ openForMs: 0, blastRadiusShown: false, livePreviewShown: false }),
    );
    expect(committed.length).toBe(1);
  });
});

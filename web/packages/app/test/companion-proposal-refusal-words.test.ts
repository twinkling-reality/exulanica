import { describe, expect, it, vi } from 'vitest';

import { CompanionProposalClient } from '../src/companion-ask-api.js';
import { say } from '../src/ui/copy.js';

/**
 * An appearance refusal is said in words that state the server's cause.
 *
 * Two causes used to share `unsupported_reference`: a draft that named none of the photographs
 * the world is drawn over, and a world that holds no photograph a proposal could cite at all, as
 * an authored starter world with nothing attached does. The page said the first over both, which
 * told a person in the second case that the change had named the wrong photograph when there was
 * none to name. The server states the second as `no_evidence`, and these words are keyed to it.
 */

const json = (body: unknown): Response =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });

async function refusedWith(code: string, detail: string) {
  const fetch = vi.fn(async () =>
    json({
      classification: 'appearance',
      proposal: null,
      refusal: { code, detail },
      execution: { prompt_version: 'proposal-2', calls: [] },
    }),
  ) as unknown as typeof globalThis.fetch;
  const client = new CompanionProposalClient({
    worldId: 'world:starter:refusal-words',
    baseUrl: 'https://exulanica.test/api',
    token: 'not-a-real-token',
    fetch,
  });
  const outcome = await client.propose('could the sky be warmer');
  if (outcome.refusal === null) throw new Error('the refusal did not reach the client');
  return outcome.refusal;
}

describe('the words for an appearance refusal', () => {
  it('say a world with nothing to cite needs a photograph attached, not a better draft', async () => {
    const refusal = await refusedWith(
      'no_evidence',
      'this world holds no evidence a proposal could cite; attach a reviewed photograph to it, '
        + 'and a proposal can cite that photograph',
    );
    expect(refusal.code).toBe('no_evidence');
    const words = say(`proposal.refused.${refusal.code}`);
    expect(words).toContain('Attach a reviewed photograph');
    expect(words).not.toContain('did not name any of the photographs');
  });

  it('keep saying a draft named none of the photographs where that is what happened', async () => {
    const refusal = await refusedWith('unsupported_reference', 'draft named no evidence');
    expect(refusal.code).toBe('unsupported_reference');
    expect(say(`proposal.refused.${refusal.code}`)).toContain(
      'did not name any of the photographs this world is drawn over',
    );
  });
});

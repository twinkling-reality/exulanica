import { describe, expect, it, vi } from 'vitest';
import { WorldStyleProposalInbox } from '../src/world-style-proposals.js';

const proposal = {
  origin: 'companion' as const,
  originReference: 'companion-world-design',
  profile: { profileId: 'origin-landscape', profileVersion: 1 },
  referenceIds: ['span-1'],
  modelId: 'reviewed-personalizer-v1',
  promptVersion: 'world-style-v1',
};

describe('upstream world style proposal inbox', () => {
  it('delivers structured proposals without inventing a conversational service', async () => {
    const inbox = new WorldStyleProposalInbox();
    const listener = vi.fn();
    const unsubscribe = inbox.subscribe(listener);
    await expect(inbox.submit(proposal)).resolves.toBe(true);
    expect(listener).toHaveBeenCalledWith(proposal);
    unsubscribe();
    await expect(inbox.submit(proposal)).resolves.toBe(false);
  });

  it('settles only once every listener has finished with the proposal', async () => {
    const inbox = new WorldStyleProposalInbox();
    let finish: () => void = () => undefined;
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    inbox.subscribe(async () => finished);
    let settled = false;
    const submitted = inbox.submit(proposal).then(() => { settled = true; });

    for (let turn = 0; turn < 8; turn += 1) await Promise.resolve();
    expect(settled).toBe(false);
    finish();
    await submitted;
    expect(settled).toBe(true);
  });

  it('does not fail the proposal for a listener that fails', async () => {
    const inbox = new WorldStyleProposalInbox();
    const after = vi.fn();
    inbox.subscribe(() => { throw new Error('this surface broke'); });
    inbox.subscribe(async () => Promise.reject(new Error('and so did this one')));
    inbox.subscribe(after);

    await expect(inbox.submit(proposal)).resolves.toBe(true);
    expect(after).toHaveBeenCalledWith(proposal);
  });
});

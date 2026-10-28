// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { describeWorldStyleFailure } from '../src/composition/appearance.js';

describe('a write another lock held', () => {
  it('is said in the page\'s own words, never the server\'s sentence, and not as a look change', () => {
    const server = 'another change held a lock this write needs for more than 2000 ms; nothing was written';
    const words = describeWorldStyleFailure(new ApiError(409, 'busy', server));
    expect(words).toBe('Your world was busy with something else a moment ago, so nothing was saved. Try again.');
    expect(words).not.toContain('2000');
  });
});

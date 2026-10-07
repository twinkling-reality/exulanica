import { describe, expect, it, vi } from 'vitest';
import { THING_LOOK_CHOICES_PROFILE, ThingLooksClient, parseThingLookChoices } from '../src/thing-looks-api.js';

/*
 * The looks chosen for a version's things, read strictly. The body is THINGS's agreed read
 * (exulanica.thing-look-choices/v1: the version, and per thing its society id, the author's id
 * where it was placed, the look named by key, version and SHA-256, who chose it and when).
 */

const SHA = 'c'.repeat(64);
const served = (looks: unknown[], versionId = 'version-1') => ({ profile: THING_LOOK_CHOICES_PROFILE, version_id: versionId, looks });
const crossing = { thing_id: '0b1e6a3c-1111-5222-8333-944455556666', placed_id: null, look: { look: 'kaykit-mannequin', version: 1, sha256: SHA }, chosen_by: 'crossing', chosen_at: '2026-10-09T14:03:11.123456Z' };
const owner = { thing_id: '7f0c2d1e-aaaa-5bbb-8ccc-dddd00001111', placed_id: 'knight', look: { look: 'blocky-traveller', version: 2, sha256: SHA }, chosen_by: 'owner', chosen_at: '2026-10-09T14:05:00.000001Z' };

describe('the looks chosen for a version\'s things', () => {
  it('reads each choice by the thing it was made for, in the open world', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(served([crossing, owner])), {
      status: 200, headers: { 'content-type': 'application/json' },
    }));
    const looks = await new ThingLooksClient({ baseUrl: 'http://host.test', token: 'token-1', worldId: 'world:1', fetch }).read('version-1');
    expect(looks.get(crossing.thing_id)).toEqual({
      thingId: crossing.thing_id, placedId: null, look: { key: 'kaykit-mannequin', version: 1, sha256: SHA },
      chosenBy: 'crossing', chosenAt: '2026-10-09T14:03:11.123456Z',
    });
    expect(looks.get(owner.thing_id)!.placedId).toBe('knight');
    expect(String(fetch.mock.calls[0]![0])).toBe('http://host.test/world/versions/version-1/thing-looks?world_id=world%3A1');
  });

  it('refuses another version\'s choices, another profile, two choices for one thing and a look without its digest', () => {
    expect(() => parseThingLookChoices(served([], 'version-2'), 'version-1')).toThrow(/another version/u);
    expect(() => parseThingLookChoices({ ...served([]), profile: 'exulanica.thing-look-choices/v2' }, 'version-1')).toThrow(/v1/u);
    expect(() => parseThingLookChoices(served([crossing, crossing]), 'version-1')).toThrow(/two look choices/u);
    expect(() => parseThingLookChoices(served([{ ...crossing, look: { ...crossing.look, sha256: 'x' } }]), 'version-1')).toThrow(/SHA-256/u);
    expect(() => parseThingLookChoices(served([{ ...crossing, chosen_by: 'anyone' }]), 'version-1')).toThrow(/who chose it/u);
  });

  it('reads a version whose things wear their kinds\' first looks as no choices', () => {
    expect(parseThingLookChoices(served([]), 'version-1')).toEqual([]);
  });
});

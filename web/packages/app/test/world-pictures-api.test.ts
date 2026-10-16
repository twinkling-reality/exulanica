// The History pictures client (src/world-pictures-api.ts): what it sends for a moment's picture and a
// look's portrait, that a page which raced another shows the picture kept first, and that a read
// asks only what the server answers and refuses what it should not trust.
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { HistoryPicturesClient, LOOKS_ASKED_AT_MOST, PORTRAITS_PROFILE, parseHistoryPicture } from '../src/world-pictures-api.js';

const DIGEST = 'a'.repeat(64);
const OTHER = 'b'.repeat(64);
const kept = { sha256: DIGEST, width: 600, height: 340 };
/** A fetch double that records what it was asked. */
const answering = (answer: () => Response) => vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => answer());
const jpeg = (): Blob => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: 'image/jpeg' });

describe('keeping a picture', () => {
  it('puts the picture itself, typed as it is, under the moment and its recipe', async () => {
    const fetch = answering(() => Response.json(kept));
    const client = new HistoryPicturesClient({ baseUrl: 'https://exulanica.test/', token: 'private', csrfToken: 'csrf', fetch });
    const picture = jpeg();
    await expect(client.putMomentPicture('world 1', 'version-1', 'moment/1', 'moment-framing/v1', picture)).resolves.toEqual(kept);
    const [url, init] = fetch.mock.calls[0]! as [string, RequestInit];
    const address = new URL(url);
    expect(address.pathname).toBe('/world/versions/version-1/history/moments/moment%2F1/picture');
    expect(Object.fromEntries(address.searchParams)).toEqual({ world_id: 'world 1', recipe: 'moment-framing/v1' });
    expect(init.method).toBe('PUT');
    expect(init.body).toBe(picture);
    expect(init.headers).toEqual({ 'content-type': 'image/jpeg', authorization: 'Bearer private', 'x-csrf-token': 'csrf' });
  });

  it('names a portrait by its look, and sends no bearer header without a token', async () => {
    const fetch = answering(() => Response.json({ ...kept, width: 156, height: 156 }));
    const client = new HistoryPicturesClient({ baseUrl: 'https://exulanica.test', token: '', fetch });
    await expect(client.putPortrait('w', DIGEST, 'portrait/v1', jpeg())).resolves.toEqual({ sha256: DIGEST, width: 156, height: 156 });
    const [url, init] = fetch.mock.calls[0]! as [string, RequestInit];
    expect(Object.fromEntries(new URL(url).searchParams)).toEqual({ world_id: 'w', look_sha256: DIGEST, recipe: 'portrait/v1' });
    expect(init.headers).toEqual({ 'content-type': 'image/jpeg' });
  });

  it('answers with the picture another page kept first, and refuses anything else', async () => {
    const raced = new HistoryPicturesClient({
      baseUrl: 'https://exulanica.test', token: '',
      fetch: answering(() => Response.json({ code: 'picture_kept', detail: 'kept', kept: { ...kept, sha256: OTHER } }, { status: 409 })),
    });
    await expect(raced.putPortrait('w', DIGEST, 'portrait/v1', jpeg())).resolves.toEqual({ ...kept, sha256: OTHER });
    const full = new HistoryPicturesClient({
      baseUrl: 'https://exulanica.test', token: '',
      fetch: answering(() => Response.json({ code: 'pictures_full', detail: 'full' }, { status: 409 })),
    });
    const refused = full.putPortrait('w', DIGEST, 'portrait/v1', jpeg());
    await expect(refused).rejects.toBeInstanceOf(ApiError);
    await expect(refused).rejects.toMatchObject({ code: 'pictures_full' });
  });
});

describe('reading portraits', () => {
  it('asks each look once and answers each with its portrait or null', async () => {
    const fetch = answering(() => Response.json({ profile: PORTRAITS_PROFILE, portraits: { [DIGEST]: kept, [OTHER]: null } }));
    const client = new HistoryPicturesClient({ baseUrl: 'https://exulanica.test', token: '', fetch });
    const portraits = await client.portraits('w', [DIGEST, OTHER, DIGEST], 'portrait/v1');
    expect([...portraits]).toEqual([[DIGEST, kept], [OTHER, null]]);
    const address = new URL(fetch.mock.calls[0]![0] as string);
    expect(address.searchParams.get('looks')).toBe(`${DIGEST},${OTHER}`);
    expect(address.searchParams.get('world_id')).toBe('w');
    await expect(client.portraits('w', [], 'portrait/v1')).resolves.toEqual(new Map());
    expect(fetch).toHaveBeenCalledOnce();
  });

  it('refuses to ask for too many looks or a name that is not a digest, and an answer of another profile', async () => {
    const fetch = answering(() => Response.json({ profile: 'something else', portraits: {} }));
    const client = new HistoryPicturesClient({ baseUrl: 'https://exulanica.test', token: '', fetch });
    const many = Array.from({ length: LOOKS_ASKED_AT_MOST + 1 }, (_, n) => n.toString(16).padStart(64, '0'));
    await expect(client.portraits('w', many, 'portrait/v1')).rejects.toThrow(TypeError);
    await expect(client.portraits('w', ['not-a-digest'], 'portrait/v1')).rejects.toThrow(TypeError);
    expect(fetch).not.toHaveBeenCalled();
    await expect(client.portraits('w', [DIGEST], 'portrait/v1')).rejects.toThrow('invalid portraits');
  });

  it('trusts a picture only with a digest and a whole positive size', () => {
    expect(parseHistoryPicture(kept)).toEqual(kept);
    for (const bad of [null, { ...kept, sha256: 'A'.repeat(64) }, { ...kept, width: 0 }, { ...kept, height: 1.5 }, { ...kept, width: '600' }]) {
      expect(() => parseHistoryPicture(bad)).toThrow(TypeError);
    }
  });
});

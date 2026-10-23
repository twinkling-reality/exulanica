// The pictures on the cards a world is started from (src/ui/card-pictures.ts): a card shows its
// entry's picture only where the release's record states what is served for the card now.
import { describe, expect, it } from 'vitest';
import { CARD_PICTURES_PROFILE, cardPicture, readCardPictures } from '../src/ui/card-pictures.js';

const record = (entries: unknown[], profile = CARD_PICTURES_PROFILE) => async (address: string): Promise<Response> => {
  expect(address).toBe('/card-pictures/card-pictures.v1.json');
  return new Response(JSON.stringify({ profile, entries, held: [] }), { status: 200 });
};
const town = { card: 'recipe:small_town', reference: { key: 'small_town', values: { storeys: 3, street: 'local_street' } }, picture: 'recipe-small_town.jpg' };
const kind = { card: 'kind:town', reference: { kind: 'town', version: 1, sha256: 'ab12' }, picture: 'kind-town.jpg' };

describe('the pictures on the cards a world is started from', () => {
  it('shows a card its picture where the record states what is served for it now', async () => {
    const pictures = await readCardPictures(record([town, kind]));
    expect(cardPicture(pictures, 'recipe:small_town', { values: { street: 'local_street', storeys: 3 } })).toBe('/card-pictures/recipe-small_town.jpg');
    expect(cardPicture(pictures, 'kind:town', { version: 1, sha256: 'ab12' })).toBe('/card-pictures/kind-town.jpg');
  });

  it('shows the quiet tile where what is served differs from the record, or the record has no entry', async () => {
    const pictures = await readCardPictures(record([town, kind]));
    expect(cardPicture(pictures, 'recipe:small_town', { values: { storeys: 4, street: 'local_street' } })).toBeNull();
    expect(cardPicture(pictures, 'recipe:small_town', { values: { storeys: 3 } })).toBeNull();
    expect(cardPicture(pictures, 'recipe:small_town', { values: { storeys: 3, street: 'local_street', blocks: 2 } })).toBeNull();
    expect(cardPicture(pictures, 'kind:town', { version: 2, sha256: 'ab12' })).toBeNull();
    // A workspace's own kind of the same name is another kind.
    expect(cardPicture(pictures, 'kind:town', { version: 1, sha256: 'cd34' })).toBeNull();
    expect(cardPicture(pictures, 'kind:island_hamlet', { version: 1, sha256: 'ab12' })).toBeNull();
  });

  it('shows every card quiet where the record cannot be read, and takes no path or address for a picture', async () => {
    expect(await readCardPictures(async () => new Response('', { status: 404 }))).toBeNull();
    expect(await readCardPictures(async () => { throw new Error('offline'); })).toBeNull();
    expect(await readCardPictures(record([town], 'exulanica.other/v1'))).toBeNull();
    expect(cardPicture(null, 'recipe:small_town', { values: { storeys: 3, street: 'local_street' } })).toBeNull();
    const pictures = await readCardPictures(record([{ ...town, picture: '../private.jpg' }, { ...kind, picture: 'https://elsewhere.example/a.jpg' }]));
    expect(pictures?.size).toBe(0);
  });
});

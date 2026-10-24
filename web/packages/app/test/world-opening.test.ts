// @vitest-environment happy-dom
// @vitest-environment-options { "url": "http://127.0.0.1/" }
// Opening a world (tools/previews/world-workspace/world-opening.ts): the opening shows on a world's
// own address, and never in a scene preview, the front door's live background, which draws the world
// in an inert frame but never mounts the world view that ends the opening.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Opening { mountOpening(): void; endOpening(): boolean }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const opening = async (): Promise<Opening> => import('../../../../tools/previews/world-workspace/' + 'world-opening.ts') as Promise<Opening>;

afterEach(() => { document.body.replaceChildren(); vi.resetModules(); });

describe('the opening', () => {
  it("shows on a world's own address", async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).not.toBeNull();
  });

  it('names a town\'s bake while it bakes, moves its line by the share and never back, then the loader\'s stages', async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const step = (): string | null | undefined => document.querySelector('.wu-opening-step')?.textContent;
    const drawn = (): string | undefined => (document.querySelector('.wu-opening-fill') as HTMLElement | null)?.style.width;
    expect(step()).toBe('Reading the world');
    say({ baking: 0 });
    expect([step(), drawn()]).toEqual(['Making the land', '0.0%']);
    say({ baking: 0.5 });
    expect(drawn()).toBe('12.5%');
    say({ baking: 0 });
    expect(drawn()).toBe('12.5%');
    say({ report: 'land-made' });
    expect([step(), drawn()]).toEqual(['Reading the world', '25.0%']);
    say({ baking: 1 });
    expect(drawn()).toBe('25.0%');
    say({ report: 'world-read', title: 'A town' });
    expect([step(), drawn()]).toEqual(['Drawing the land', '50.0%']);
  });

  it('opens a town the front door says is still baking on its bake from the first frame (C3b)', async () => {
    const entryId = '01a13bd3-fa95-7c62-8683-42e78f2a0e2c';
    history.replaceState(null, '', `/?entry=${entryId}`);
    sessionStorage.setItem('exulanica.opening.v1', JSON.stringify({ entryId, title: 'A town', picture: null, baking: true }));
    (await opening()).mountOpening();
    const step = (): string | null | undefined => document.querySelector('.wu-opening-step')?.textContent;
    const drawn = (): string | undefined => (document.querySelector('.wu-opening-fill') as HTMLElement | null)?.style.width;
    expect([step(), drawn()]).toEqual(['Making the land', '0.0%']);
    // It read baked before its bake was waited for: the world's first report counts the bake done.
    window.dispatchEvent(new CustomEvent('exulanica:opening', { detail: { report: 'world-read' } }));
    expect([step(), drawn()]).toEqual(['Drawing the land', '50.0%']);
    sessionStorage.clear();
  });

  it('opens a town the front door does not say is baking on reading the world, as before', async () => {
    const entryId = '01a13bd3-fa95-7c62-8683-42e78f2a0e2c';
    history.replaceState(null, '', `/?entry=${entryId}`);
    sessionStorage.setItem('exulanica.opening.v1', JSON.stringify({ entryId, title: 'A town', picture: null }));
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening-step')?.textContent).toBe('Reading the world');
    sessionStorage.clear();
  });

  it.each(['capture=1', 'livePreview=1'])('shows nothing in a scene preview (%s)', async (preview) => {
    history.replaceState(null, '', `/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c&${preview}`);
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).toBeNull();
  });
});

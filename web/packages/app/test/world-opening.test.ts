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
// The stage words on show (words that leave stay a moment as they go), and the line's length, which it draws as scaleX.
const shownStep = (): string | null | undefined => document.querySelector('.wu-opening-step > :not([data-leaving])')?.textContent;
const length = (): string | undefined => {
  const drawn = /scaleX\(([\d.]+)\)/u.exec((document.querySelector('.wu-opening-fill') as HTMLElement | null)?.style.transform ?? '');
  return drawn ? `${(Number(drawn[1]) * 100).toFixed(1)}%` : undefined;
};

afterEach(() => { document.body.replaceChildren(); vi.resetModules(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('the opening', () => {
  it("shows on a world's own address, taking the screen from the page's first frame of its ground (rule 9)", async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    // index.html marks a world's address so its first frame is the opening's ground, with nothing of the page's own.
    document.documentElement.dataset.opening = '';
    document.documentElement.style.backgroundImage = 'url("data:image/png;base64,AAAA")';
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).not.toBeNull();
    expect([document.documentElement.hasAttribute('data-opening'), document.documentElement.style.backgroundImage]).toEqual([false, '']);
  });

  it('names a town\'s bake while it bakes, moves its line by the share and never back, then the loader\'s stages', async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const step = shownStep;
    const drawn = length;
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
    const step = shownStep;
    const drawn = length;
    expect([step(), drawn()]).toEqual(['Making the land', '0.0%']);
    // It read baked before its bake was waited for: the world's first report counts the bake done.
    window.dispatchEvent(new CustomEvent('exulanica:opening', { detail: { report: 'world-read' } }));
    expect([step(), drawn()]).toEqual(['Drawing the land', '50.0%']);
    sessionStorage.clear();
  });

  it('eases the line within a running bake step toward that step\'s end, never to it nor back (C3c)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] });
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const drawn = (): number => Number.parseFloat(length() ?? '');
    // Two of four steps served; the two bakes run: the line starts at 12.5% and eases toward 18.75%, the next step's.
    say({ baking: 0.5, reach: 0.75 });
    expect(drawn()).toBe(12.5);
    vi.advanceTimersByTime(4000);
    expect(drawn()).toBeCloseTo(15.3, 1);
    vi.advanceTimersByTime(60_000);
    expect(drawn()).toBeGreaterThan(17.5);
    expect(drawn()).toBeLessThan(18.75);
    // A step ends: the line stands at once where the served steps say, and eases on toward the next step's end.
    say({ baking: 0.75, reach: 1 });
    expect(drawn()).toBe(18.8);
    vi.advanceTimersByTime(4000);
    expect(drawn()).toBeCloseTo(21.6, 1);
    // A read that answers the older steps never moves it back.
    say({ baking: 0.5, reach: 0.75 });
    vi.advanceTimersByTime(1000);
    expect(drawn()).toBeGreaterThanOrEqual(21.6);
    expect(drawn()).toBeLessThan(25);
    // The bake ends: the loader's own stages, which ease nowhere.
    say({ report: 'land-made' });
    expect(drawn()).toBe(25);
    vi.advanceTimersByTime(10_000);
    expect(drawn()).toBe(25);
  });

  it('eases on from where the line stands when one of two tiles ends its step behind it, never back (C3c)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] });
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const drawn = (): number => Number.parseFloat(length() ?? '');
    say({ baking: 0.5, reach: 0.75 });
    vi.advanceTimersByTime(60_000);
    const eased = drawn();
    // One tile's step ends: the served share (15.6%) is behind the line; it eases on from there toward 21.9%.
    say({ baking: 0.625, reach: 0.875 });
    expect(drawn()).toBe(eased);
    vi.advanceTimersByTime(4000);
    expect(drawn()).toBeGreaterThan(eased);
    expect(drawn()).toBeLessThan(21.875);
  });

  it('eases nowhere without the running step\'s end, nor where motion is reduced (C3c)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] });
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const drawn = length;
    const first = await opening();
    first.mountOpening();
    say({ baking: 0.5 });
    vi.advanceTimersByTime(10_000);
    expect(drawn()).toBe('12.5%');
    first.endOpening();
    document.body.replaceChildren();
    vi.resetModules();
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query === '(prefers-reduced-motion: reduce)', media: query }));
    (await opening()).mountOpening();
    say({ baking: 0.5, reach: 0.75 });
    vi.advanceTimersByTime(10_000);
    expect(drawn()).toBe('12.5%');
  });

  it('swaps the stage words only when they change, and goes when its own fade ends, not its words\' (motion catalog)', async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    const shown = await opening();
    shown.mountOpening();
    const say = (detail: object): void => { window.dispatchEvent(new CustomEvent('exulanica:opening', { detail })); };
    const leaving = (): number => document.querySelectorAll('.wu-opening-step > [data-leaving]').length;
    say({ baking: 0 });
    expect([shownStep(), leaving()]).toEqual(['Making the land', 1]);
    // Redrawn with the same words: nothing arrives or leaves again.
    say({ baking: 0.5 });
    expect([shownStep(), leaving(), document.querySelectorAll('.wu-opening-step > :not([data-leaving])').length]).toEqual(['Making the land', 1, 1]);
    const root = document.querySelector('.wu-opening')!;
    shown.endOpening();
    root.querySelector('.wu-opening-words')!.dispatchEvent(new Event('animationend', { bubbles: true }));
    expect(root.isConnected).toBe(true);
    root.dispatchEvent(new Event('animationend', { bubbles: true }));
    expect(root.isConnected).toBe(false);
  });

  it('opens a town the front door does not say is baking on reading the world, as before', async () => {
    const entryId = '01a13bd3-fa95-7c62-8683-42e78f2a0e2c';
    history.replaceState(null, '', `/?entry=${entryId}`);
    sessionStorage.setItem('exulanica.opening.v1', JSON.stringify({ entryId, title: 'A town', picture: null }));
    (await opening()).mountOpening();
    expect(shownStep()).toBe('Reading the world');
    sessionStorage.clear();
  });

  it.each(['capture=1', 'livePreview=1'])('shows nothing in a scene preview (%s)', async (preview) => {
    history.replaceState(null, '', `/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c&${preview}`);
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).toBeNull();
  });
});

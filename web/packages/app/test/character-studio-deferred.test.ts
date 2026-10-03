// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

/*
 * The character studio's code loads when the studio is first opened; the person's figure the world
 * draws at start does not wait for it (composition/character.ts `deferredStudio`).
 */

const built: { calls: [string, unknown[]][]; root: HTMLElement }[] = [];
const build = vi.fn((_callbacks: unknown) => {
  const root = document.createElement('section');
  root.className = 'character-studio real';
  const calls: [string, unknown[]][] = [];
  built.push({ calls, root });
  return new Proxy({ root, canvas: document.createElement('canvas') } as Record<string, unknown>, {
    get(target, name: string) {
      if (name in target) return target[name];
      return (...args: unknown[]) => { calls.push([name, args]); };
    },
  });
});
vi.mock('../src/ui/character-studio.js', () => ({ buildCharacterStudio: build }));

const { deferredStudio } = await import('../src/composition/character.js');
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => { built.length = 0; build.mockClear(); document.body.replaceChildren(); });

describe('the character studio, loaded when first opened', () => {
  it('holds what the figure reports until the studio exists, then replays the latest of each, in order', async () => {
    const studio = deferredStudio({} as never);
    const view = studio.view as unknown as Record<string, (...args: unknown[]) => void>;
    document.body.append(studio.view.root);
    view['setPeopleStatus']!('Loading…', false);
    view['setWorldView']!('third');
    view['setPeopleStatus']!('Ready', true);
    expect(build).not.toHaveBeenCalled();
    expect(studio.built()).toBe(false);
    const opened = vi.fn();
    studio.open(opened);
    expect(document.body.textContent).toContain('Opening Character.');
    await vi.waitFor(() => expect(opened).toHaveBeenCalledOnce());
    expect(built[0]!.calls).toEqual([['setWorldView', ['third']], ['setPeopleStatus', ['Ready', true]]]);
    // The stand-in gave its place to the studio, and the view is now the studio's own.
    expect(document.body.querySelector('.character-studio.real')).toBe(built[0]!.root);
    expect(studio.view.root).toBe(built[0]!.root);
    view['setStatus']!('direct', true);
    expect(built[0]!.calls.at(-1)).toEqual(['setStatus', ['direct', true]]);
  });

  it('opens nothing when it was closed while loading', async () => {
    const studio = deferredStudio({} as never);
    document.body.append(studio.view.root);
    const opened = vi.fn();
    studio.open(opened);
    studio.close();
    await vi.waitFor(() => expect(build).toHaveBeenCalled());
    await settle();
    expect(opened).not.toHaveBeenCalled();
  });

  it('says it did not open, and opens on Try again', async () => {
    build.mockImplementationOnce(() => { throw new Error('the module did not load'); });
    const studio = deferredStudio({} as never);
    document.body.append(studio.view.root);
    const opened = vi.fn();
    studio.open(opened);
    await vi.waitFor(() => expect(document.body.textContent).toContain('Character did not open.'));
    expect(opened).not.toHaveBeenCalled();
    document.body.querySelector<HTMLButtonElement>('.x-error button')!.click();
    await vi.waitFor(() => expect(opened).toHaveBeenCalledOnce());
  });
});

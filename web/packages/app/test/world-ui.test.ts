// @vitest-environment happy-dom
// The world workspace's shared in-world parts (tools/previews/world-workspace/world-ui.ts): what
// they say to a keyboard and a screen reader. A prompt is one button named by its word, with its
// key as aria-keyshortcuts and its drawn caps hidden; a hint that only says a key is not a button;
// a note is one at a time and leaves on its own; a page is a modal dialog with its key row.
import { afterEach, describe, expect, it, vi } from 'vitest';

/** What these tests use of world-ui.ts, a preview module outside this package. */
interface Notes { show(words: string, options?: { prompt?: HTMLElement; ms?: number }): void; place(where: 'world' | 'build' | 'page'): void; readonly root: HTMLElement }
interface Page { readonly root: HTMLElement; readonly content: HTMLElement; readonly keys: HTMLElement; open(host: HTMLElement): void; close(): void }
interface WorldUi {
  keyWord(options: { keys: readonly string[] | 'mouse' | 'mouse-click'; word: string; shortcut?: string; onPress?: () => void; small?: boolean; disabled?: boolean }): HTMLElement;
  setWord(prompt: HTMLElement, word: string): void;
  chip(text: string, options?: { quiet?: boolean; live?: boolean }): HTMLElement;
  setChipLive(made: HTMLElement, on: boolean): void;
  notes(host: HTMLElement): Notes;
  page(options: { form: 'character' | 'creature' | 'full' }): Page;
  stepList(steps: readonly { words: string; state: 'done' | 'now' | 'next'; time?: string }[]): HTMLElement;
  mountUiScale(root: HTMLElement, signal?: AbortSignal): void;
  scaleOf(root: HTMLElement): number;
}
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const parts = async (): Promise<WorldUi> => import('../../../../tools/previews/world-workspace/' + 'world-ui.ts') as Promise<WorldUi>;

afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

describe('a key and its word', () => {
  it('is one button named by its word, with the key as its shortcut and the caps hidden', async () => {
    const { keyWord } = await parts();
    const pressed = vi.fn();
    const prompt = keyWord({ keys: ['E'], word: 'Inspect', shortcut: 'E', onPress: pressed });
    document.body.append(prompt);
    expect(prompt.tagName).toBe('BUTTON');
    expect(prompt.getAttribute('type')).toBe('button');
    expect(prompt.getAttribute('aria-keyshortcuts')).toBe('E');
    expect(prompt.querySelector('.wu-key')!.getAttribute('aria-hidden')).toBe('true');
    expect(prompt.querySelector('.wu-word')!.textContent).toBe('Inspect');
    prompt.click();
    expect(pressed).toHaveBeenCalledOnce();
  });

  it('draws several keys and a mouse, and says only what a key does when nothing is pressed', async () => {
    const { keyWord } = await parts();
    const move = keyWord({ keys: ['W', 'A', 'S', 'D'], word: 'Move' });
    expect(move.tagName).toBe('SPAN');
    expect([...move.querySelectorAll('.wu-key')].map((key) => key.textContent)).toEqual(['W', 'A', 'S', 'D']);
    expect(move.querySelector('.wu-keys')!.getAttribute('aria-hidden')).toBe('true');
    const look = keyWord({ keys: 'mouse-click', word: 'Look' });
    expect(look.querySelector('.wu-key')!.className).toBe('wu-key wu-mouse wu-click');
    // ⌘Z is one cap; only the symbol is set in the symbol face.
    const undo = keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: () => {}, small: true });
    expect(undo.querySelectorAll('.wu-key.wu-small')).toHaveLength(1);
    expect(undo.querySelector('.wu-key')!.textContent).toBe('⌘Z');
    expect(undo.querySelector('.wu-sym')!.textContent).toBe('⌘');
  });

  it('when disabled is not focusable and does not run', async () => {
    const { keyWord } = await parts();
    const pressed = vi.fn();
    const prompt = keyWord({ keys: ['H'], word: 'History', shortcut: 'H', onPress: pressed, disabled: true }) as HTMLButtonElement;
    document.body.append(prompt);
    expect(prompt.disabled).toBe(true);
    prompt.click();
    expect(pressed).not.toHaveBeenCalled();
  });

  it('changes its word in place', async () => {
    const { keyWord, setWord } = await parts();
    const prompt = keyWord({ keys: ['P'], word: 'Play', shortcut: 'P', onPress: () => {} });
    setWord(prompt, 'Pause');
    expect(prompt.textContent).toBe('PPause');
  });
});

describe('the other parts', () => {
  it('a chip carries the live dot only while its model decides, and is never a button', async () => {
    const { chip, setChipLive } = await parts();
    const made = chip('Nemotron 3 Nano 30B');
    expect(made.tagName).toBe('SPAN');
    expect(made.querySelector('.wu-live-dot')).toBeNull();
    setChipLive(made, true); setChipLive(made, true);
    expect(made.querySelectorAll('.wu-live-dot')).toHaveLength(1);
    setChipLive(made, false);
    expect(made.querySelector('.wu-live-dot')).toBeNull();
    expect(chip('Private', { quiet: true }).classList.contains('wu-quiet')).toBe(true);
  });

  it('a note is one at a time, and leaves after its time', async () => {
    vi.useFakeTimers();
    const { notes, keyWord } = await parts();
    const shown = notes(document.body);
    expect(shown.root.getAttribute('role')).toBe('status');
    expect(shown.root.dataset.place).toBe('world');
    shown.place('build');
    expect(shown.root.dataset.place).toBe('build');
    shown.show('Moved the bench.');
    shown.show('Removed the fan palm.', { prompt: keyWord({ keys: ['⌘Z'], word: 'Undo', onPress: () => {} }) });
    expect(document.querySelectorAll('.wu-note')).toHaveLength(1);
    expect(shown.root.textContent).toBe('Removed the fan palm.⌘ZUndo');
    vi.advanceTimersByTime(7_999);
    expect(shown.root.hidden).toBe(false);
    vi.advanceTimersByTime(301 + 1);
    expect(shown.root.hidden).toBe(true);
    expect(shown.root.textContent).toBe('');
  });

  it('a page is a modal dialog with its key row, and closing removes it', async () => {
    const { page } = await parts();
    const shown = page({ form: 'character' });
    shown.open(document.body);
    expect(shown.root.getAttribute('role')).toBe('dialog');
    expect(shown.root.getAttribute('aria-modal')).toBe('true');
    expect(shown.root.classList.contains('wu-character')).toBe(true);
    expect(shown.content.contains(shown.keys)).toBe(true);
    shown.close();
    expect(document.querySelector('.wu-page')).toBeNull();
  });

  it('steps mark the one in progress as current', async () => {
    const { stepList } = await parts();
    const list = stepList([{ words: 'Reading the world', state: 'done', time: '0:01' }, { words: 'Drawing the land', state: 'now' }, { words: 'Bringing in its people', state: 'next' }]);
    expect([...list.children].map((step) => (step as HTMLElement).dataset.state)).toEqual(['done', 'now', 'next']);
    expect(list.querySelector('[aria-current="step"]')!.textContent).toContain('Drawing the land');
  });

  it('the scale follows the window, within its bounds', async () => {
    const { mountUiScale, scaleOf } = await parts();
    const lifetime = new AbortController();
    Object.assign(window, { innerWidth: 1440, innerHeight: 900 });
    mountUiScale(document.body, lifetime.signal);
    expect(scaleOf(document.body)).toBe(0.78);
    Object.assign(window, { innerWidth: 1920, innerHeight: 1080 });
    window.dispatchEvent(new Event('resize'));
    expect(scaleOf(document.body)).toBe(1);
    lifetime.abort();
  });
});

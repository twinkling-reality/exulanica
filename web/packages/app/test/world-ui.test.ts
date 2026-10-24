// @vitest-environment happy-dom
// The world workspace's shared in-world parts (tools/previews/world-workspace/world-ui.ts): what
// they say to a keyboard and a screen reader. A prompt is one button named by its word, with its
// key as aria-keyshortcuts and its drawn caps hidden; a hint that only says a key is not a button;
// a note is one at a time and leaves on its own; a page is a modal dialog with its key row.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

/** What these tests use of world-ui.ts, a preview module outside this package. */
interface Notes { show(words: string, options?: { prompt?: HTMLElement; ms?: number; under?: string }): void; place(where: 'world' | 'build' | 'page'): void; readonly root: HTMLElement }
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
  nameTag(options?: { scale?: () => number }): { readonly root: HTMLElement; set(words: { name: string; doing?: string | null; model?: string | null; live?: boolean }): void; place(x: number, y: number): void; hide(): void };
  outline(options?: { form?: 'chosen' | 'copy' | 'refused' | 'origin' }): { readonly root: SVGSVGElement; place(corners: readonly { x: number; y: number }[]): void; form(form: 'chosen' | 'copy' | 'refused' | 'origin'): void; hide(): void };
  path(): { readonly root: SVGSVGElement; place(from: { x: number; y: number }, to: { x: number; y: number }): void; hide(): void };
  areaBanner(words: { name: string; over?: string; sub?: string }): { readonly root: HTMLElement; remove(): void };
  pill(...parts: (Node | string)[]): HTMLElement;
  tip(word: string, key: string): HTMLElement;
  shade(options?: { small?: boolean }): HTMLElement;
  glyphRows(rows: readonly { key: string; word: string; shortcut?: string; onPress?: () => void; disabled?: boolean }[], sizes?: { glyph?: number | string; rowGap?: number | string; colGap?: number | string; word?: number | string; nudge?: number; bars?: boolean }): HTMLElement;
  keysToWorld(target: HTMLElement): (shown: boolean) => void;
  sideCard(options?: { scale?: () => number }): { readonly root: HTMLElement; readonly body: HTMLElement; place(bounds: { left: number; top: number; right: number; bottom: number }): 'right' | 'left'; hide(): void };
  promptColumn(prompts: readonly HTMLElement[]): HTMLElement;
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

  it('a note can carry a second line under its words, beside its prompt (B1)', async () => {
    const { notes, keyWord } = await parts();
    const shown = notes(document.body);
    shown.show('You placed the bench', { prompt: keyWord({ keys: ['⌘Z'], word: 'Undo', onPress: () => {} }), under: 'Cars now keep to the other lane.' });
    const lines = shown.root.querySelector('.wu-note-lines');
    expect([...lines!.children].map((line) => [line.className, line.textContent])).toEqual([
      ['wu-note-words', 'You placed the bench'], ['wu-note-under', 'Cars now keep to the other lane.'],
    ]);
    expect(lines!.nextElementSibling?.textContent).toBe('⌘ZUndo');
    shown.show('Moved the bench.');
    expect(shown.root.querySelector('.wu-note-lines, .wu-note-under')).toBeNull();
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

describe('the parts beside a subject', () => {
  it('a name tag says the name, what the character does and its model, in one polite announcement', async () => {
    const { nameTag } = await parts();
    const tag = nameTag();
    document.body.append(tag.root);
    expect(tag.root.hidden).toBe(true);
    // One live line is what a reader hears; what is drawn is hidden from it.
    const spoken = tag.root.querySelector('[aria-live="polite"]')!;
    tag.set({ name: 'Teo', doing: 'Waiting by the bench', model: 'Nemotron 3 Nano 30B', live: true });
    expect(spoken.textContent).toBe('Teo, waiting by the bench, Nemotron 3 Nano 30B');
    expect(tag.root.querySelector('.wu-tag-name')!.getAttribute('aria-hidden')).toBe('true');
    expect(tag.root.querySelector('.wu-chip')!.getAttribute('aria-hidden')).toBe('true');
    expect(tag.root.querySelectorAll('.wu-chip')).toHaveLength(1);
    expect(tag.root.querySelector('.wu-live-dot')).not.toBeNull();
    // While a pop speaks for the character, and for a thing, the doing line goes; a thing has no chip.
    tag.set({ name: 'Fan palm' });
    expect((tag.root.querySelector('.wu-tag-doing') as HTMLElement).hidden).toBe(true);
    expect(tag.root.querySelector('.wu-chip')).toBeNull();
    expect(spoken.textContent).toBe('Fan palm');
    tag.place(400, 300);
    expect(tag.root.hidden).toBe(false);
    expect(tag.root.style.transform).toMatch(/^translate3d\(/u);
  });

  it('an outline changes its form in place, and a path draws one curve between two points', async () => {
    const { outline, path } = await parts();
    const copy = outline({ form: 'copy' });
    copy.place([{ x: 0, y: 0 }, { x: 10, y: 0 }]);
    expect(copy.root.style.display).toBe('none');
    copy.place([{ x: 0, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 30 }, { x: 0, y: 30 }]);
    expect(copy.root.style.display).toBe('');
    expect(copy.root.querySelector('.wu-outline-line')!.getAttribute('d')).toMatch(/^M.*Z$/u);
    copy.form('refused');
    expect(copy.root.dataset.form).toBe('refused');
    expect(outline().root.dataset.form).toBe('chosen');
    const way = path();
    way.place({ x: 0, y: 0 }, { x: 70, y: 0 });
    expect(way.root.querySelector('path')!.getAttribute('d')).toBe('M0.0 0.0Q35.0 -10.0 70.0 0.0');
  });
});

describe('the area banner', () => {
  it('names the world once, with who lives there, and takes frame 22\'s form with an over-label', async () => {
    const { areaBanner } = await parts();
    const arriving = areaBanner({ name: 'Terraces on the bay', sub: '24 people live here' });
    expect(arriving.root.getAttribute('role')).toBe('status');
    expect(arriving.root.textContent).toBe('Terraces on the bay24 people live here');
    expect(arriving.root.classList.contains('wu-made')).toBe(false);
    const made = areaBanner({ name: 'Harbour at night', over: 'Made from your words' });
    expect(made.root.classList.contains('wu-made')).toBe(true);
    expect(made.root.querySelector('.wu-banner-over')!.textContent).toBe('Made from your words');
    expect(made.root.querySelector('.wu-banner-sub')).toBeNull();
  });
});

describe('the redraws\' shared craft', () => {
  it('draws rows of key and word: a pressable row is one button named by its word, Enter a drawn return arrow', async () => {
    const { glyphRows } = await parts();
    const pressed = vi.fn();
    const group = glyphRows([
      { key: 'Enter', word: "Teo's day", shortcut: 'Enter', onPress: pressed },
      { key: 'V', word: 'Follow Teo', shortcut: 'V', onPress: () => {}, disabled: true },
      { key: '[ ]', word: 'Turn' },
    ], { glyph: 48, colGap: 20, word: 'max(28px, calc(32 * var(--u)))', nudge: -1 });
    document.body.append(group);
    const [enter, follow, turn] = [...group.children] as HTMLElement[];
    expect(enter!.tagName).toBe('BUTTON');
    expect(enter!.getAttribute('aria-keyshortcuts')).toBe('Enter');
    expect(enter!.querySelector('.wu-glyph')!.getAttribute('aria-hidden')).toBe('true');
    expect(enter!.querySelector('.wu-glyph svg')).not.toBeNull();
    expect(enter!.textContent).toBe("Teo's day");
    enter!.click();
    expect(pressed).toHaveBeenCalledOnce();
    expect((follow as HTMLButtonElement).disabled).toBe(true);
    expect(turn!.tagName).toBe('DIV');
    expect(turn!.querySelector('.wu-glyph')!.textContent).toBe('[ ]');
    // A number is reference pixels, a string a length as given; those left out keep the stylesheet's.
    expect(group.style.getPropertyValue('--glyph')).toBe('calc(48 * var(--u))');
    expect(group.style.getPropertyValue('--word')).toBe('max(28px, calc(32 * var(--u)))');
    expect(group.style.getPropertyValue('--nudge')).toBe('-1px');
    expect(group.style.getPropertyValue('--row-gap')).toBe('');
    expect(glyphRows([], { bars: true }).className).toBe('wu-rows wu-bars');
    expect(glyphRows([{ key: 'mouse', word: 'Place' }]).querySelector('.wu-glyph svg')).not.toBeNull();
  });

  it('puts floating words on a shade, a pill and a tip on thin glass', async () => {
    const { shade, pill, tip } = await parts();
    expect(shade().className).toBe('wu-shade');
    expect(shade({ small: true }).className).toBe('wu-shade wu-small');
    const top = pill('Terraces on the bay', document.createElement('i'));
    expect(top.className).toBe('wu-glass-thin wu-pill');
    expect(top.childNodes).toHaveLength(2);
    const history = tip('History', 'H');
    expect(history.textContent).toBe('HistoryH');
    expect(history.querySelector('.wu-key.wu-small')!.getAttribute('aria-hidden')).toBe('true');
  });

  it('keeps the sheets\' 1440 sizes as floors where the scale alone would draw them smaller', () => {
    const css = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui.css`, 'utf8');
    const start = css.indexOf('.wu-root {');
    const root = css.slice(start, css.indexOf('\n}', start));
    for (const token of ['--edge-inset: calc(32 * var(--u))', '--pill-height: max(36px, calc(40 * var(--u)))', '--pill-text: max(14px, calc(15 * var(--u)))',
      '--pill-text-small: max(12px, calc(13 * var(--u)))', '--glass-thin-fill: rgba(13, 20, 27, .40)', '--shade-fill: rgba(6, 12, 16, .46)']) expect(root).toContain(token);
  });
});

/** What these tests use of world-ui-build.ts, build mode's own parts. */
interface TrayTile { readonly id: string; readonly name: string; readonly picture: string | null; readonly make?: boolean }
interface BuildUi {
  heldGroup(): { readonly root: HTMLElement; set(words: { title: string; line?: { words: string; refused?: boolean } | null; rows: readonly { key: string; word: string; shortcut?: string; onPress?: () => void; disabled?: boolean }[] }): void; hide(): void };
  tray(options: { words: { label: string; things: string; creatures: string }; onTab: (tab: 'things' | 'creatures') => void; onPick: (tile: TrayTile) => void }): {
    readonly root: HTMLElement;
    set(state: { tab: 'things' | 'creatures'; tiles: readonly TrayTile[] | null; held: string | null; offline: boolean; empty: string }): void;
    picture(id: string, url: string): void;
    hide(): void;
  };
  namesNear(): { readonly root: HTMLElement; place(names: readonly { words: string; x: number; y: number }[], scale: number): void; hide(): void };
}
const buildParts = async (): Promise<BuildUi> => import('../../../../tools/previews/world-workspace/' + 'world-ui-build.ts') as Promise<BuildUi>;

describe('build mode\'s own parts', () => {
  it('the held group is a region named by its title, a refusal drawn refused, and rows that press', async () => {
    const { heldGroup } = await buildParts();
    const group = heldGroup();
    document.body.append(group.root);
    expect(group.root.hidden).toBe(true);
    const back = vi.fn();
    group.set({ title: 'Bench', line: { words: 'Not here: that spot is in the pool.', refused: true }, rows: [
      { key: 'mouse-click', word: 'Place', shortcut: 'Enter', onPress: () => {}, disabled: true },
      { key: 'Esc', word: 'Put back', shortcut: 'Escape', onPress: back },
    ] });
    expect(group.root.hidden).toBe(false);
    expect(group.root.classList.contains('wu-shade')).toBe(true);
    const title = group.root.querySelector('h2')!;
    expect(group.root.getAttribute('role')).toBe('region');
    expect(group.root.getAttribute('aria-labelledby')).toBe(title.id);
    expect(title.textContent).toBe('Bench');
    expect(group.root.querySelector('.wu-held-line.wu-refused')!.textContent).toBe('Not here: that spot is in the pool.');
    const [place, putBack] = [...group.root.querySelectorAll('.wu-rows > button')] as HTMLButtonElement[];
    expect(place!.disabled).toBe(true);
    expect(place!.querySelector('.wu-glyph svg')).not.toBeNull();
    putBack!.click();
    expect(back).toHaveBeenCalledOnce();
    group.set({ title: 'Remove the bench?', line: { words: 'Nobody can use it from the next minute.' }, rows: [] });
    expect(group.root.querySelector('.wu-held-line')!.classList.contains('wu-refused')).toBe(false);
    group.hide();
    expect(group.root.hidden).toBe(true);
  });

  it('the tray is two tabs over picture tiles: the held one pressed, an empty tab said, offline dimmed', async () => {
    const { tray } = await buildParts();
    const tabbed = vi.fn(), picked = vi.fn();
    const made = tray({ words: { label: 'Things to place', things: 'Things', creatures: 'Creatures' }, onTab: tabbed, onPick: picked });
    document.body.append(made.root);
    made.set({ tab: 'things', tiles: null, held: null, offline: false, empty: '' });
    expect(made.root.hidden).toBe(false);
    expect(made.root.querySelectorAll('.wu-tile')).toHaveLength(0);
    const tiles = [{ id: 'make', name: 'Make a creature', picture: null, make: true }, { id: 'kind:bench', name: 'Bench', picture: null }, { id: 'kind:well', name: 'Well', picture: 'data:image/png;base64,AA' }];
    made.set({ tab: 'things', tiles, held: 'kind:bench', offline: false, empty: 'Nothing.' });
    const tabs = [...made.root.querySelectorAll('[role="tab"]')] as HTMLButtonElement[];
    expect(tabs.map(tab => [tab.textContent, tab.getAttribute('aria-selected')])).toEqual([['Things', 'true'], ['Creatures', 'false']]);
    expect(made.root.querySelector('[role="tabpanel"]')!.getAttribute('aria-labelledby')).toBe(tabs[0]!.id);
    tabs[1]!.click();
    expect(tabbed).toHaveBeenCalledWith('creatures');
    const buttons = [...made.root.querySelectorAll('.wu-tile')] as HTMLButtonElement[];
    expect(buttons.map(button => button.textContent)).toEqual(['+Make a creature', 'Bench', 'Well']);
    expect(buttons.map(button => button.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);
    expect((buttons[2]!.querySelector('.wu-tile-picture') as HTMLElement).style.backgroundImage).toContain('data:image/png');
    made.picture('kind:bench', 'data:image/png;base64,BB');
    expect((buttons[1]!.querySelector('.wu-tile-picture') as HTMLElement).style.backgroundImage).toContain('BB');
    buttons[1]!.click();
    expect(picked).toHaveBeenCalledWith(tiles[1]);
    made.set({ tab: 'creatures', tiles: [tiles[0]!], held: null, offline: true, empty: 'No creatures made yet.' });
    expect(made.root.querySelector('.wu-tray-empty')!.textContent).toBe('No creatures made yet.');
    expect(made.root.dataset.offline).toBe('true');
    expect((made.root.querySelector('.wu-tile') as HTMLButtonElement).disabled).toBe(true);
  });

  it('names over people stand above their point, and the ones not asked for hide', async () => {
    const { namesNear } = await buildParts();
    const names = namesNear();
    document.body.append(names.root);
    names.place([{ words: 'Teo and Ines', x: 400, y: 300 }, { words: 'Ari', x: 700, y: 320 }], 1);
    const labels = [...names.root.children] as HTMLElement[];
    expect(labels.map(label => [label.textContent, label.hidden])).toEqual([['Teo and Ines', false], ['Ari', false]]);
    expect(labels[0]!.style.transform).toContain('translate3d(400.0px,284.0px,0)');
    expect(names.root.getAttribute('aria-hidden')).toBe('true');
    names.place([{ words: 'Ari', x: 10, y: 20 }], 0.78);
    expect(labels.map(label => label.hidden)).toEqual([false, true]);
    expect(labels[0]!.textContent).toBe('Ari');
  });
});

describe('the keys going back to the world (TERRAIN rehearsal 5, finding 3)', () => {
  /** The scene's canvas, which the renderer walks for only while it has focus, beside the world's panels. */
  const scene = (): { host: HTMLElement; canvas: HTMLCanvasElement } => {
    const host = document.createElement('div'), canvas = document.createElement('canvas');
    canvas.tabIndex = 0;
    document.body.append(host, canvas);
    return { host, canvas };
  };

  it('takes focus back to the scene when Esc lets go of the chosen card while its prompt has focus', async () => {
    const { keysToWorld, sideCard, keyWord, promptColumn } = await parts();
    const { host, canvas } = scene();
    // The chosen card as character-presence.ts fills it: its words, then its prompts.
    const card = sideCard();
    host.append(card.root);
    const prompt = keyWord({ keys: ['Enter'], word: 'Details', onPress: () => {} });
    card.body.append(promptColumn([prompt]));
    card.place({ left: 400, top: 200, right: 520, bottom: 600 });
    const back = keysToWorld(canvas);
    prompt.focus();
    back(true);
    expect(document.activeElement).toBe(prompt);
    // What Esc does: the page lets go of the chosen person and the card empties (character-presence.ts choose(null)).
    // Focus falls to the body, where the renderer's keys walk nothing.
    card.hide(); card.body.replaceChildren();
    expect(document.activeElement).toBe(document.body);
    back(true);
    expect(document.activeElement).toBe(canvas);
  });

  it('takes it back from a focused button its panel hid, as the model list closes', async () => {
    const { keysToWorld } = await parts();
    const { host, canvas } = scene();
    const list = document.createElement('div'), model = document.createElement('button');
    list.append(model);
    host.append(list);
    const back = keysToWorld(canvas);
    model.focus();
    back(true);
    list.hidden = true;
    back(true);
    expect(document.activeElement).toBe(canvas);
    // A model picked with a click: the click focuses its button and closes the list in one go, before a frame looks.
    const again = document.createElement('button');
    list.replaceChildren(again);
    list.hidden = false;
    again.focus();
    list.hidden = true;
    back(true);
    expect(document.activeElement).toBe(canvas);
  });

  it('leaves focus where it is under a page, after a click on blank page, in a field and on a live button', async () => {
    const { keysToWorld } = await parts();
    const { host, canvas } = scene();
    const field = document.createElement('input'), button = document.createElement('button');
    host.append(field, button);
    const back = keysToWorld(canvas);
    // A page over the world keeps its own focus, even where its button went: the page gives it back as it closes.
    button.focus();
    back(false);
    button.remove();
    back(false);
    expect(document.activeElement).toBe(document.body);
    // A click on blank page leaves the field it blurred still there: focus stays on the body.
    field.focus();
    back(true);
    field.blur();
    back(true);
    expect(document.activeElement).toBe(document.body);
    // A field and a live button keep focus.
    field.focus();
    back(true);
    expect(document.activeElement).toBe(field);
    const live = document.createElement('button');
    host.append(live);
    live.focus();
    back(true);
    expect(document.activeElement).toBe(live);
  });
});

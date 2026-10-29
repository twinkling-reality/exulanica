// @vitest-environment happy-dom
// Create a world (tools/previews/world-workspace/create-world.ts, ROOT's composer mock of 27 October) and its parts
// (world-ui-create.ts): what they say to a keyboard and a screen reader, and the page over stand-in answers. The
// composer's pill is one button, "Create", with its key; the web search toggle says its details as a tooltip; the
// strip's cards name themselves, Blank last, one Tab stop, the current one marked and the page's picture following it;
// Esc is drawn once; the steps are a polite live region; the made note is announced once and leaves when dismissed.
// Every first Enter starts, showing the making view before the start answers, or says why in the price's place.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Step { key?: string; words: string; state: 'done' | 'now' | 'next'; sub?: string; time?: string }
interface StripCard { key: string; name: string; picture: string | null; blank?: boolean }
interface CreatePage { readonly root: HTMLElement; readonly column: HTMLElement; readonly foot: HTMLElement; readonly corner: HTMLElement; form(next: 'create' | 'creating'): void; picture(address: string | null): void }
interface Composer {
  readonly root: HTMLElement; readonly field: HTMLTextAreaElement; readonly pill: HTMLButtonElement; readonly web: HTMLButtonElement | null;
  set(words: string): void; say(why: string | null, price: string | null): void; again(): void; ready(on: boolean): void;
  offerWeb(web: { on: boolean; tip: string; onChange: (on: boolean) => void } | null): void;
}
interface WorldStrip { readonly root: HTMLElement; readonly cards: readonly HTMLButtonElement[]; readonly chosen: number; choose(index: number, focus?: boolean): void }
interface CreateParts {
  createPage(options: { labelledBy: string }): CreatePage;
  createTitle(words: string, id: string): HTMLElement;
  composer(options: { value?: string; onInput?: (words: string) => void; onCreate: () => void }): Composer;
  worldStrip(cards: readonly StripCard[], options: { onStart: (key: string) => void; onChoose?: (card: StripCard) => void; labelledBy?: string }): WorldStrip;
  makingSteps(): { readonly root: HTMLElement; set(steps: readonly Step[]): void };
  webNotes(): { readonly root: HTMLElement; notes(label: string, notes: readonly { aspect: string; text: string }[]): void; instead(label: string, line: string): void };
  quietCommand(options: { onPress: () => void; place?: 'quiet' | 'row' | 'corner' }): HTMLButtonElement;
  madeNote(line: string): { readonly root: HTMLElement; dismiss(): void };
}
interface CreateSteps { startCards(recipes?: readonly unknown[], kinds?: readonly unknown[]): StripCard[] }
// Joined paths: the test runner still finds the files, and the type checker leaves the preview
// modules (outside this package) out of the program.
const parts = async (): Promise<CreateParts> => import('../../../../tools/previews/world-workspace/' + 'world-ui-create.ts') as Promise<CreateParts>;
const steps = async (): Promise<CreateSteps> => import('../../../../tools/previews/world-workspace/' + 'create-steps.mjs') as Promise<CreateSteps>;

afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

const nameOf = (element: Element): string => {
  const by = element.getAttribute('aria-labelledby');
  return by ? by.split(' ').map((id) => document.getElementById(id)?.textContent ?? '').join(' ') : (element.getAttribute('aria-label') ?? element.textContent ?? '').trim();
};
const type = (field: HTMLTextAreaElement, words: string): void => { field.value = words; field.dispatchEvent(new Event('input')); };

describe('the composer', () => {
  it('takes the words with the mock\'s placeholder, and is one Create pill with its key, dimmed while it cannot start', async () => {
    const { composer } = await parts();
    let pressed = 0;
    const box = composer({ onCreate: () => { pressed += 1; } });
    document.body.append(box.root);
    expect(box.field.tagName).toBe('TEXTAREA');
    expect(box.field.placeholder).toBe('A cozy little town by the sea at dusk');
    expect(box.field.getAttribute('aria-label')).toBe('Prompt');
    expect([...box.root.querySelectorAll('button')]).toEqual([box.pill]);
    expect(box.pill.textContent).toBe('Create↵');
    expect(box.pill.getAttribute('aria-keyshortcuts')).toBe('Enter');
    expect(box.pill.querySelector('.wu-composer-key')!.getAttribute('aria-hidden')).toBe('true');
    // Dimmed, it is still a button that can be pressed: the press says why (N2, the first Enter).
    expect(box.pill.getAttribute('aria-disabled')).toBe('true');
    expect(box.pill.disabled).toBe(false);
    box.pill.click();
    expect(pressed).toBe(1);
    box.ready(true);
    expect(box.pill.hasAttribute('aria-disabled')).toBe(false);
  });

  it('says the price, and why it cannot start in the price\'s place, each a polite status', async () => {
    const { composer } = await parts();
    const box = composer({ onCreate: () => {} });
    document.body.append(box.root);
    const why = box.root.querySelector<HTMLElement>('.wu-composer-why')!, price = box.root.querySelector<HTMLElement>('.wu-composer-price')!;
    expect([why.getAttribute('role'), price.getAttribute('role')]).toEqual(['status', 'status']);
    // In the foot's order: the toggle's place, the reason, the price, then Create.
    expect([...box.root.querySelector('.wu-composer-foot')!.children].map((one) => one.className)).toEqual(['wu-composer-web', 'wu-composer-why', 'wu-composer-price', 'wu-composer-pill']);
    expect([why.hidden, price.hidden]).toEqual([true, true]);
    box.say(null, 'Up to $0.26');
    expect([why.hidden, price.textContent]).toEqual([true, 'Up to $0.26']);
    box.say('Reading what you can make here…', null);
    expect([why.textContent, price.hidden]).toEqual(['Reading what you can make here…', true]);
    // Pressed again on the same reason, it is said again: emptied, then said.
    vi.useFakeTimers();
    box.again();
    expect(why.textContent).toBe('');
    vi.advanceTimersByTime(0);
    expect(why.textContent).toBe('Reading what you can make here…');
  });

  it('draws "Search the web" as a toggle where web notes are offered, its details a tooltip in the page\'s type', async () => {
    const { composer } = await parts();
    const box = composer({ onCreate: () => {} });
    document.body.append(box.root);
    expect(box.web).toBeNull();
    const heard: boolean[] = [];
    const tip = 'Looks up what such a place looks like before it is made: up to 3 searches with Tavily, which keeps them. Adds at most $0.05.';
    box.offerWeb({ on: true, tip, onChange: (on) => heard.push(on) });
    const chip = box.web!;
    expect(chip.tagName).toBe('BUTTON');
    expect(chip.textContent).toBe('Web Search');
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.hasAttribute('title')).toBe(false);
    const said = document.getElementById(chip.getAttribute('aria-describedby')!)!;
    expect(said.getAttribute('role')).toBe('tooltip');
    expect(said.textContent).toBe(tip);
    chip.click();
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    chip.click();
    expect(heard).toEqual([false, true]);
    // The tab order runs through the words, the toggle, then Create.
    const order = [...box.root.querySelectorAll<HTMLElement>('textarea, button')].filter((one) => one.tabIndex >= 0);
    expect(order).toEqual([box.field, chip, box.pill]);
    box.offerWeb(null);
    expect(box.web).toBeNull();
    expect(box.root.querySelector('.wu-composer-chip')).toBeNull();
  });
});

describe('the strip of ready worlds', () => {
  const strip = async (onChoose?: (card: StripCard) => void) => {
    const create = await parts();
    const { startCards } = await steps();
    const cards = startCards([{ key: 'recipe:town', name: 'A small town', picture: '/card-pictures/recipe-town.jpg' }], [{ key: 'kind:wall', name: 'Wall city', priceUsd: '0.4' }]);
    const started: string[] = [];
    const shown = create.worldStrip(cards, { onStart: (key) => started.push(key), ...(onChoose ? { onChoose } : {}) });
    document.body.append(shown.root);
    return { shown, started };
  };

  it('names each card, says Ready World over a ready world and Empty over Blank, last, and makes one Tab stop', async () => {
    const { shown, started } = await strip();
    expect(shown.cards.map(nameOf)).toEqual(['A small town', 'Wall city', 'Blank']);
    expect(shown.cards.map((card) => document.getElementById(card.getAttribute('aria-describedby')!)!.textContent)).toEqual(['Ready World', 'Ready World', 'Empty']);
    expect(shown.cards.map((card) => card.tabIndex)).toEqual([0, -1, -1]);
    expect(shown.cards[0]!.getAttribute('aria-current')).toBe('true');
    expect(shown.cards.map((card) => card.dataset['picture'])).toEqual(['served', 'none', 'blank']);
    expect(shown.cards[0]!.querySelector('img')!.getAttribute('src')).toBe('/card-pictures/recipe-town.jpg');
    expect(shown.cards[0]!.querySelector('img')!.alt).toBe('');
    expect(shown.cards[1]!.querySelector('img')).toBeNull();
    // No price or sub-line under a name (the mock): its kind and its name alone.
    expect(shown.cards[1]!.textContent).toBe('Ready WorldWall city');
    shown.cards[1]!.click();
    expect(started).toEqual(['kind:wall']);
    expect(shown.root.getAttribute('role')).toBe('group');
    expect(nameOf(shown.root)).toBe('Or start from');
  });

  it('moves the current card with its arrows, held at the ends, and tells the page each new one', async () => {
    const chosen: (string | null)[] = [];
    const { shown } = await strip((card) => chosen.push(card.picture));
    const [previous, next] = [...shown.root.querySelectorAll<HTMLButtonElement>('.wu-strip-arrow')];
    expect([previous!.getAttribute('aria-label'), next!.getAttribute('aria-label')]).toEqual(['Previous', 'Next']);
    expect(previous!.getAttribute('aria-disabled')).toBe('true');
    expect(chosen).toEqual(['/card-pictures/recipe-town.jpg']);
    next!.click();
    expect(shown.chosen).toBe(1);
    expect(previous!.hasAttribute('aria-disabled')).toBe(false);
    next!.click(); next!.click();
    expect(shown.chosen).toBe(2);
    expect(next!.getAttribute('aria-disabled')).toBe('true');
    // Blank's tile is empty: the picture behind gives way to the ground.
    expect(chosen).toEqual(['/card-pictures/recipe-town.jpg', null, null]);
    shown.choose(0, true);
    expect(document.activeElement).toBe(shown.cards[0]);
    expect(shown.cards.filter((card) => card.hasAttribute('aria-current'))).toEqual([shown.cards[0]]);
  });
});

describe('the page and Esc', () => {
  it('crossfades the current ready world\'s picture behind it, and the ground where there is none', async () => {
    const { createPage } = await parts();
    const page = createPage({ labelledBy: 'title' });
    document.body.append(page.root);
    const shown = (): string[] => [...page.root.querySelectorAll<HTMLElement>('.wu-create-media[data-shown="true"]')].map((one) => one.style.backgroundImage);
    expect(page.root.getAttribute('role')).toBe('dialog');
    expect(page.root.getAttribute('aria-modal')).toBe('true');
    expect(page.root.querySelector('.wu-create-mark')!.textContent).toBe('exulanica');
    expect(shown()).toEqual([]);
    page.picture('/card-pictures/a.jpg');
    expect(shown()).toHaveLength(1);
    expect(shown()[0]).toContain('/card-pictures/a.jpg');
    page.picture('/card-pictures/b.jpg');
    expect(shown()).toHaveLength(1);
    expect(shown()[0]).toContain('/card-pictures/b.jpg');
    page.picture(null);
    expect(shown()).toEqual([]);
    page.form('creating');
    expect(page.root.dataset['form']).toBe('creating');
  });

  it('draws Esc once, as the command "Your worlds" at the top right, its cap hidden', async () => {
    const { createPage, quietCommand } = await parts();
    const page = createPage({ labelledBy: 'title' });
    document.body.append(page.root);
    const leave = quietCommand({ onPress: () => {}, place: 'corner' });
    page.corner.append(leave);
    expect(leave.tagName).toBe('BUTTON');
    expect(nameOf(leave)).toContain('Your worlds');
    expect(leave.getAttribute('aria-keyshortcuts')).toBe('Escape');
    expect(leave.querySelector('.wu-qcmd-key')!.getAttribute('aria-hidden')).toBe('true');
    expect([...page.root.querySelectorAll('[aria-keyshortcuts="Escape"]')]).toEqual([leave]);
  });
});

describe('the making view', () => {
  it('marks the running step and says each new one once in a polite live region', async () => {
    const create = await parts();
    const shown = create.makingSteps();
    shown.set([{ words: 'Planning Layout', state: 'done', time: '1 s' }, { words: 'Designing World', state: 'now', time: '6 s' }]);
    document.body.append(shown.root);
    const live = shown.root.querySelector('[aria-live]')!;
    expect(live.getAttribute('aria-live')).toBe('polite');
    expect(live.textContent).toBe('Designing World');
    const now = shown.root.querySelector('[aria-current="step"]')!;
    expect(now.querySelector('.wu-making-words')!.textContent).toBe('Designing World');
    expect(now.querySelector('.wu-making-now')!.getAttribute('aria-hidden')).toBe('true');
    expect(shown.root.querySelectorAll('[aria-current]')).toHaveLength(1);
    shown.set([{ words: 'Planning Layout', state: 'done', time: '1 s' }, { words: 'Designing World', state: 'done', time: '9 s' }, { words: 'Building World', state: 'now', time: '12 s' }]);
    expect(live.textContent).toBe('Building World');
    expect(shown.root.querySelectorAll('.wu-making-step')).toHaveLength(3);
    expect(shown.root.querySelectorAll('.wu-making-now')).toHaveLength(1);
    expect(shown.root.querySelector('[aria-current="step"] .wu-making-time')!.textContent).toBe('12 s');
  });

  it('keeps each step\'s row across reads, so a time changes in place', async () => {
    const create = await parts();
    const shown = create.makingSteps();
    shown.set([{ key: 'queued', words: 'Queued', state: 'now', time: '0 s' }]);
    const row = shown.root.querySelector('.wu-making-step');
    shown.set([{ key: 'queued', words: 'Queued', state: 'now', time: '1 s' }]);
    shown.set([{ key: 'queued', words: 'Queued', state: 'done', time: '2 s' }, { key: 'choosing', words: 'Planning Layout', state: 'now', time: '3 s' }]);
    expect(shown.root.querySelector('.wu-making-step')).toBe(row);
    expect(row!.textContent).toBe('Queued2 s');
  });

  it('says the web notes under their label, each under its aspect, or the line in their place', async () => {
    const { webNotes } = await parts();
    const web = webNotes();
    document.body.append(web.root);
    expect(web.root.hidden).toBe(true);
    web.notes('Web References · 3 Searches', [{ aspect: 'buildings', text: 'Low clusters of buildings with simple gabled roofs.' }]);
    expect(web.root.hidden).toBe(false);
    expect(nameOf(web.root)).toBe('Web References · 3 Searches');
    expect([...web.root.querySelectorAll('.wu-making-note')].map((note) => note.textContent)).toEqual(['BuildingsLow clusters of buildings with simple gabled roofs.']);
    web.instead('Web References', 'The web notes could not be made, so it is made from your words alone.');
    expect(web.root.textContent).toBe('Web ReferencesThe web notes could not be made, so it is made from your words alone.');
  });
});

describe('the made note', () => {
  it('is announced once, says its one plain line with no labels, and leaves when dismissed', async () => {
    vi.useFakeTimers();
    const { madeNote } = await parts();
    const note = madeNote('12 notes from the web · $0.0058 · Not in it yet: fishing, wooden boats');
    document.body.append(note.root);
    expect(note.root.getAttribute('role')).toBe('status');
    // On the page empty, then filled, so it is announced once (N24).
    expect(note.root.childElementCount).toBe(0);
    vi.advanceTimersByTime(0);
    expect(note.root.textContent).toBe('12 notes from the web · $0.0058 · Not in it yet: fishing, wooden boats');
    expect(note.root.querySelector('.wu-made-label')).toBeNull();
    note.dismiss();
    expect(note.root.dataset.leaving).toBe('true');
    vi.advanceTimersByTime(300);
    expect(note.root.isConnected).toBe(false);
  });
});

// Create a world as a page (create-world.ts) over stand-in answers: the offer and the draft reads come through the
// workspace's own read path, a start through the app's client.
const opened: string[] = [];
const starts: { words: string; key: string; most: string; reference?: string | null }[] = [];
let startAnswer: () => Promise<unknown> = async () => ({ draftId: 'd-1', state: 'queued', refusal: null });
vi.mock('../../../../tools/previews/world-workspace/front-door.ts', () => ({
  chosenWorldPicture: () => null,
  openMadeWorld: async (entry: { entryId: string }) => { opened.push(entry.entryId); },
}));
// The cards to start from arrive when a test lets them (`cardsHeld`), else at once.
const cardsHeld = vi.hoisted(() => ({ until: null as Promise<void> | null }));
vi.mock('../src/world-specification.ts', () => ({
  WorldSpecificationClient: class { async specification() { await cardsHeld.until; return { presets: [{ key: 'town', label: 'Small town', values: {} }] }; } },
}));
vi.mock('../src/world-kinds-api.ts', () => ({ WorldKindsClient: class { async library() { return { kinds: [] }; } } }));
vi.mock('../src/world-making-api.ts', async (original) => {
  const real = await original<typeof import('../src/world-making-api.ts')>();
  return {
    ...real,
    WorldMakingClient: class {
      async start(words: string, submission: { idempotencyKey: string; maximumUsd: string; referenceId?: string }) {
        starts.push({ words, key: submission.idempotencyKey, most: submission.maximumUsd, reference: submission.referenceId ?? null });
        return startAnswer();
      }
    },
  };
});

interface CreatePageModule { mountCreateWorld(options: { root: HTMLElement; credentials: unknown; entries: unknown; onClose: () => void }): { readonly isConnected: boolean; remove(): void } | null }
const page = async (): Promise<CreatePageModule> => import('../../../../tools/previews/world-workspace/' + 'create-world.ts') as Promise<CreatePageModule>;

const OPERATION = {
  profile: 'exulanica.world-draft-operation/v1', basis: 'full_context_reservation_ceiling', estimate_is_expected_spend: false,
  maximum_usd: '1.4227', document_sha256: 'a'.repeat(64),
};
const offerOf = (extra: Record<string, unknown> = {}) => {
  const now = Date.now();
  return {
    offered: true, code: null, detail: null, calls_at_most: 4, description_characters: 1000, running_draft_id: null, refusals: [],
    starts: { an_hour: 12, left: 2, retry_after_seconds: null },
    operation: { ...OPERATION, read_at: new Date(now).toISOString(), expires_at: new Date(now + 30_000).toISOString() },
    ...extra,
  };
};

/** Answers the workspace's reads: the offer, then each draft read in turn. */
function serve(offer: Record<string, unknown>, reads: Record<string, unknown>[] = []): void {
  vi.stubGlobal('fetch', vi.fn(async (address: string) => {
    const body = address.endsWith('/worlds/drafts') ? offer : reads.shift() ?? { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
    return { ok: true, status: 200, json: async () => body };
  }));
}

const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) await new Promise((resolve) => setTimeout(resolve, 0)); };
const key = (target: Element, code: string, extra: KeyboardEventInit = {}): KeyboardEvent => {
  const event = new KeyboardEvent('keydown', { code, key: code === 'Enter' ? 'Enter' : code, bubbles: true, cancelable: true, ...extra });
  target.dispatchEvent(event);
  return event;
};
const field = (): HTMLTextAreaElement => document.querySelector<HTMLTextAreaElement>('textarea.wu-composer-words')!;
/** What the composer's foot says: why Create cannot start, and the price; each '' where it says none. */
const why = (): string => { const said = document.querySelector<HTMLElement>('.wu-composer-why'); return said && !said.hidden ? said.textContent ?? '' : ''; };
const price = (): string => { const said = document.querySelector<HTMLElement>('.wu-composer-price'); return said && !said.hidden ? said.textContent ?? '' : ''; };
const making = (): boolean => document.querySelector('.wu-create[data-form="creating"]') !== null;
const stepRows = (): string[][] => [...document.querySelectorAll('.wu-making-step')].map((row) => [row.querySelector('.wu-making-words')!.textContent ?? '', (row as HTMLElement).dataset['state'] ?? '', row.querySelector('.wu-making-time')!.textContent ?? '']);

describe('Create a world as a page', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); opened.length = 0; starts.length = 0; cardsHeld.until = null; startAnswer = async () => ({ draftId: 'd-1', state: 'queued', refusal: null }); });
  const mount = async (onClose = () => {}) => {
    const root = document.createElement('div'); document.body.append(root);
    const shown = (await page()).mountCreateWorld({ root, credentials: {}, entries: { ensureStarter: async () => ({ entryId: 'starter' }), entries: async () => [] }, onClose });
    await settle();
    return shown!;
  };

  it('opens on the mock: the wordmark, "Create a world", the composer, the strip and Esc, with nothing under the composer', async () => {
    serve(offerOf({ host_keeps_until: '2026-12-15', starts: { an_hour: 12, left: 2, retry_after_seconds: null } }));
    await mount();
    expect(document.querySelector('.wu-create-mark')!.textContent).toBe('exulanica');
    expect(document.querySelector('h1.wu-create-title')!.textContent).toBe('Create a world');
    expect(document.activeElement).toBe(field());
    expect(price()).toBe('Up to $1.43');
    expect(why()).toBe('');
    expect([...document.querySelectorAll('.wu-strip-card')].map(nameOf)).toEqual(['Small town', 'Blank']);
    expect(document.querySelector('.wu-create-corner .wu-qcmd')!.textContent).toBe('EscYour worlds');
    // No lines of explanation (the mock): no count, no starts left, no host's keeping line, no line under the title.
    const text = document.body.textContent!;
    for (const filler of ['of 1000', 'more worlds can be started', 'stay on this server', 'People move in', 'An open model makes it', 'Or start from', 'You can leave this page']) {
      expect(text).not.toContain(filler);
    }
    expect(document.querySelector('.wu-create-column')!.lastElementChild!.classList.contains('wu-composer')).toBe(true);
  });

  it('keeps Tab within the page, from its last stop to its first and back, never on to the front door under it (C6)', async () => {
    serve(offerOf());
    const behind = document.createElement('button'); behind.textContent = 'Open My world'; document.body.append(behind);
    await mount();
    field().focus();
    // Shift+Tab from the composer, the first stop, goes to the last, Your worlds.
    expect(key(field(), 'Tab', { shiftKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement?.classList.contains('wu-qcmd')).toBe(true);
    // Tab from the last stop comes back to the composer, not on to the front door's own button.
    expect(key(document.activeElement!, 'Tab').defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(field());
    expect(document.activeElement).not.toBe(behind);
    // Between the first and the last, the browser moves the focus.
    expect(key(field(), 'Tab').defaultPrevented).toBe(false);
  });

  it('says a refusal of the offer in its own words in the price\'s place, with no price beside it and Create dimmed', async () => {
    serve(offerOf({ offered: false, code: 'kind_draft_limit', operation: null }));
    await mount();
    expect(why()).toBe('You’ve started as many worlds as you can this hour. Try again later.');
    expect(price()).toBe('');
    expect(document.body.textContent).not.toMatch(/USD|reservation|kind_draft_limit|more worlds can be started/u);
    expect(document.querySelector('.wu-composer-pill')!.getAttribute('aria-disabled')).toBe('true');
    // Enter says it again, and starts nothing.
    type(field(), 'A harbour');
    key(field(), 'Enter');
    await settle();
    expect(why()).toBe('You’ve started as many worlds as you can this hour. Try again later.');
    expect(starts).toEqual([]);
  });

  it('says what a step of making could cost against what is left, in the composer\'s place, where the budget left is short of one (N31, A1b)', async () => {
    serve(offerOf({ offered: false, code: 'world_draft_bound_exceeds_left', left_usd: '0.01', operation: { ...offerOf().operation, step_usd_at_most: '0.0344064' } }));
    await mount();
    expect(document.querySelector('.wu-create-sentence')!.textContent).toBe('Making a world from your words can cost up to $0.04 a step, more than the $0.01 left for AI models here. You can still start from these:');
    expect(document.body.textContent).not.toContain('The budget for AI models here is spent.');
    expect(document.querySelector('.wu-composer')).toBeNull();
    // The strip under it is named by the sentence.
    expect(document.querySelector('.wu-strip')!.getAttribute('aria-labelledby')).toBe(document.querySelector('.wu-create-sentence')!.id);
    expect(document.querySelectorAll('.wu-strip-card').length).toBeGreaterThan(0);
  });

  it('says spending is paused, not spent, in the composer\'s place, where the authority is held closed (N34)', async () => {
    serve(offerOf({ offered: false, code: 'spending_suspended', operation: null }));
    await mount();
    const text = document.body.textContent!;
    expect(text).toContain('Spending on AI models is paused here, so nothing can be made from your words now. You can still start from these:');
    expect(text).not.toContain('is spent');
    expect(text).not.toContain('spending_suspended');
    expect(document.querySelector('.wu-composer')).toBeNull();
  });

  it('still says a spent budget is spent: a control for N31', async () => {
    serve(offerOf({ offered: false, code: 'budget_exceeded', operation: null }));
    await mount();
    expect(document.querySelector('.wu-create-sentence')!.textContent).toBe('The budget for AI models here is spent. You can still start from these:');
  });

  it('says the most is what is left where less than the whole is left, and the whole where it is (A1b)', async () => {
    serve(offerOf({ left_usd: '0.05' }));
    await mount();
    expect(price()).toBe('Up to $0.05');
    document.body.replaceChildren();
    serve(offerOf({ own_key: true }));
    await mount();
    expect(price()).toBe('Up to $1.43');
  });

  describe('the first Enter', () => {
    it('shows the making view at once, "Waiting to start" timed from the press, with the start still unanswered', async () => {
      serve(offerOf());
      let now = 5_000;
      vi.spyOn(performance, 'now').mockImplementation(() => now);
      let answer: (value: unknown) => void = () => {};
      startAnswer = () => new Promise((resolve) => { answer = resolve; });
      await mount();
      type(field(), 'A cozy little town by the sea at dusk');
      key(field(), 'Enter');
      // Nothing awaited: the view is there before the start answers.
      expect(making()).toBe(true);
      expect(document.querySelector('h1.wu-create-title')!.textContent).toBe('Creating World');
      expect(document.querySelector('.wu-making-quote')!.textContent).toBe('“A cozy little town by the sea at dusk”');
      expect(stepRows()).toEqual([['Queued', 'now', '0 s']]);
      expect(document.querySelector('.wu-strip, .wu-composer')).toBeNull();
      await settle();
      expect(starts.map((one) => one.words)).toEqual(['A cozy little town by the sea at dusk']);
      now += 2_400;
      await new Promise((resolve) => setTimeout(resolve, 1_200));
      expect(stepRows()).toEqual([['Queued', 'now', '2 s']]);
      // Answered, the draft's own steps follow the wait, which ends where they begin.
      answer({ draftId: 'd-1', state: 'queued', refusal: null });
      await settle();
      expect(stepRows()[0]).toEqual(['Queued', 'done', '2 s']);
      expect(stepRows()[1]).toEqual(['Building World', 'now', '1 s']);
    });

    it('sends no second start for a second Enter, or a press, while the first is in flight', async () => {
      serve(offerOf());
      startAnswer = () => new Promise(() => {});
      await mount();
      const pill = document.querySelector<HTMLButtonElement>('.wu-composer-pill')!;
      type(field(), 'A quiet valley');
      const first = field();
      key(first, 'Enter');
      key(document.querySelector('section.wu-create')!, 'Enter');
      key(first, 'Enter');
      pill.click();
      await settle();
      expect(starts).toHaveLength(1);
      expect(making()).toBe(true);
    });

    it('says the price cannot be read where the offer has none, and reads it again until it can start', async () => {
      const noPrice = offerOf({ operation: null });
      const offers = [noPrice, noPrice, offerOf()];
      let reads = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        const body = address.endsWith('/worlds/drafts') ? offers[Math.min(reads++, offers.length - 1)] : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      await mount();
      expect(why()).toBe('The price can’t be read right now. Trying again.');
      expect(price()).toBe('');
      type(field(), 'A quiet valley');
      key(field(), 'Enter');
      await settle();
      // Pressed, it reads the offer again at once, and says why still.
      expect(reads).toBe(2);
      expect(why()).toBe('The price can’t be read right now. Trying again.');
      expect(starts).toEqual([]);
      expect(making()).toBe(false);
      // Read again after L14's first backoff: a price, and the next Enter starts.
      await new Promise((resolve) => setTimeout(resolve, 1_100));
      await settle();
      expect(reads).toBe(3);
      expect([why(), price()]).toEqual(['', 'Up to $1.43']);
      key(field(), 'Enter');
      await settle();
      expect(starts.map((one) => one.words)).toEqual(['A quiet valley']);
    });

    it('says the price cannot be read where the offer refuses for it, and reads it again at the press', async () => {
      let reads = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        if (address.endsWith('/worlds/drafts')) reads += 1;
        const body = address.endsWith('/worlds/drafts') ? offerOf({ offered: false, code: 'world_draft_price_unavailable', operation: null }) : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      await mount();
      expect(why()).toBe('The price can’t be read right now. Trying again.');
      expect(reads).toBe(1);
      type(field(), 'A quiet valley');
      key(field(), 'Enter');
      await settle();
      expect(reads).toBe(2);
      expect(starts).toEqual([]);
      expect(why()).toBe('The price can’t be read right now. Trying again.');
    });

    it('says what it waits for where the offer is not read yet, then starts on an Enter once it is', async () => {
      let release: () => void = () => {};
      const held = new Promise<void>((resolve) => { release = resolve; });
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        if (address.endsWith('/worlds/drafts')) await held;
        const body = address.endsWith('/worlds/drafts') ? offerOf() : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      await mount();
      expect([why(), price()]).toEqual(['', '']);
      type(field(), 'A quiet valley');
      key(field(), 'Enter');
      expect(why()).toBe('Reading what you can make here…');
      expect(starts).toEqual([]);
      expect(making()).toBe(false);
      expect(document.activeElement).toBe(field());
      release();
      await settle();
      expect([why(), price()]).toEqual(['', 'Up to $1.43']);
      key(field(), 'Enter');
      await settle();
      expect(starts.map((one) => one.words)).toEqual(['A quiet valley']);
    });

    it('says "Prompt" for an Enter with no words, and starts nothing', async () => {
      serve(offerOf());
      await mount();
      type(field(), '');
      key(field(), 'Enter');
      expect(why()).toBe('Prompt');
      expect(price()).toBe('Up to $1.43');
      expect(starts).toEqual([]);
      type(field(), 'A');
      expect(why()).toBe('');
    });

    it('starts or says why on the first Enter in every order the offer, the cards, the typing and the Enter come in', async () => {
      const events = ['offer', 'cards', 'type', 'enter'] as const;
      const orders: (typeof events[number])[][] = [];
      const permute = (done: (typeof events[number])[], left: readonly (typeof events[number])[]): void => {
        if (left.length === 0) { orders.push(done); return; }
        left.forEach((one, at) => permute([...done, one], left.filter((_, other) => other !== at)));
      };
      permute([], events);
      expect(orders).toHaveLength(24);
      for (const order of orders) {
        document.body.replaceChildren();
        starts.length = 0;
        startAnswer = () => new Promise(() => {});
        let offerIn: () => void = () => {}, cardsIn: () => void = () => {};
        const offerHeld = new Promise<void>((resolve) => { offerIn = resolve; });
        cardsHeld.until = new Promise<void>((resolve) => { cardsIn = resolve; });
        vi.stubGlobal('fetch', vi.fn(async (address: string) => {
          if (address.endsWith('/worlds/drafts')) await offerHeld;
          const body = address.endsWith('/worlds/drafts') ? offerOf() : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
          return { ok: true, status: 200, json: async () => body };
        }));
        const surface = await mount();
        // The words kept from the order before go, so each order types its own.
        type(field(), '');
        let first: 'started' | string | null = null;
        for (const event of order) {
          if (event === 'offer') offerIn();
          else if (event === 'cards') cardsIn();
          else if (event === 'type') { if (!making()) type(field(), 'A market town'); }
          else {
            key(field(), 'Enter');
            first = making() ? 'started' : why();
          }
          await settle();
        }
        const said = `${order.join(', ')}: ${first}`;
        // Started only with the offer read and words typed before it; else a reason, never nothing.
        const could = order.indexOf('offer') < order.indexOf('enter') && order.indexOf('type') < order.indexOf('enter');
        expect(said).toBe(`${order.join(', ')}: ${could ? 'started' : order.indexOf('offer') > order.indexOf('enter') ? 'Reading what you can make here…' : 'Prompt'}`);
        expect(starts).toHaveLength(could ? 1 : 0);
        // With everything in, an Enter starts.
        if (!could) {
          key(field(), 'Enter');
          await settle();
          expect(starts.map((one) => one.words), said).toEqual(['A market town']);
        }
        surface.remove();
      }
    });
  });

  it('reads a sheet held past the server\'s 60 s again before the start, and starts with the fresh one (fake clock)', async () => {
    let clock = Date.now();
    const now = vi.spyOn(Date, 'now').mockImplementation(() => clock);
    try {
      const offers = [offerOf(), offerOf({ operation: { ...offerOf().operation, maximum_usd: '1.3' } })];
      let reads = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        const body = address.endsWith('/worlds/drafts') ? offers[Math.min(reads++, offers.length - 1)] : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      await mount();
      type(field(), 'A harbour at night');
      clock += 61_000;
      key(field(), 'Enter');
      await settle(); await settle();
      expect(reads).toBe(2);
      expect(starts.map((one) => one.most)).toEqual(['1.3']);
    } finally { now.mockRestore(); }
  });

  it('starts with the sheet it holds where it was read under 45 s before: a control', async () => {
    let clock = Date.now();
    const now = vi.spyOn(Date, 'now').mockImplementation(() => clock);
    try {
      let reads = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        if (address.endsWith('/worlds/drafts')) reads += 1;
        const body = address.endsWith('/worlds/drafts') ? offerOf() : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      await mount();
      type(field(), 'A harbour at night');
      clock += 30_000;
      key(field(), 'Enter');
      await settle(); await settle();
      expect(reads).toBe(1);
      expect(starts.map((one) => one.most)).toEqual(['1.4227']);
    } finally { now.mockRestore(); }
  });

  describe('a draft held a step at a time (A1b)', () => {
    const STEP = { ...offerOf().operation, step_usd_at_most: '0.0344064' };
    const short = () => offerOf({ offered: false, code: 'world_draft_bound_exceeds_left', left_usd: '0.0085632', operation: { ...STEP } });
    /** The offer as `offers` give it, one per read and the last again; each draft read as `reads` give it. */
    const answer = (offers: Record<string, unknown>[], reads: Record<string, unknown>[] = []): { offerReads: () => number } => {
      let read = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        const body = address.endsWith('/worlds/drafts')
          ? offers[Math.min(read++, offers.length - 1)]
          : reads.shift() ?? { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      return { offerReads: () => read };
    };

    it('says less than one step left at the press as the offer does before a word, with the cards, never "Something went wrong"', async () => {
      const reads = answer([offerOf({ left_usd: '0.05', operation: { ...STEP } }), short()]);
      startAnswer = async () => ({ draftId: 'd-1', state: 'refused', refusal: { code: 'world_draft_bound_exceeds_left' } });
      await mount();
      type(field(), 'A harbour at night');
      key(field(), 'Enter');
      await settle(); await settle();
      const text = document.body.textContent!;
      expect(reads.offerReads()).toBe(2);
      expect(text).toContain('Making a world from your words can cost up to $0.04 a step, more than the $0.0085 left for AI models here. You can still start from these:');
      expect(text).not.toContain('Something went wrong');
      expect(document.querySelector('.wu-composer')).toBeNull();
      expect(document.querySelectorAll('.wu-strip-card').length).toBeGreaterThan(0);
    });

    it('says a draft stopped part way with its next step, what was left and what it spent, then reads what is left again', async () => {
      const reads = answer([offerOf({ left_usd: '0.0344064', operation: { ...STEP } }), short()], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        {
          state: 'refused', elapsed_seconds: 2, poll_after_seconds: null, accounting: { reported_usd: '0.00583680' },
          refusal: {
            code: 'budget_exceeded',
            spending: { reason: 'spending_limit_reached', retry: 'never', scope: 'workspace', detail: 'usd', limit: '0.03440640', committed: '0.02583680', requested: '0.03440640' },
          },
        },
      ]);
      await mount();
      type(field(), 'A quiet town');
      key(field(), 'Enter');
      await settle(); await settle();
      expect(why()).toBe('Making stopped part way: its next step could cost up to $0.04, more than the $0.0085 left for AI models here. No world was made, and it spent $0.0058.');
      // In place of the spent budget's words and what was spent, and with no price the offer read before can no longer hold.
      const text = document.body.textContent!;
      expect(text).not.toContain('The budget for AI models here is spent.');
      expect(text).not.toContain('before it stopped');
      expect(price()).toBe('');
      expect(field().value).toBe('A quiet town');
      expect(reads.offerReads()).toBe(1);
      // The next word reads what is left again.
      type(field(), 'A quiet town by the sea');
      await settle();
      expect(reads.offerReads()).toBe(2);
      expect(document.body.textContent).toContain('can cost up to $0.04 a step, more than the $0.0085 left for AI models here.');
    });

    it('says what a draft spent of the most it was funded with, where that is less than the whole', async () => {
      answer([offerOf({ left_usd: '0.05', operation: { ...STEP } })], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        { state: 'drafting', elapsed_seconds: 1, poll_after_seconds: 30, accounting: { reported_usd: '0.0003' }, funded_usd: '0.05000000', operation: { ...STEP } },
      ]);
      await mount();
      type(field(), 'A quiet town');
      key(field(), 'Enter');
      await settle(); await settle();
      expect(document.querySelector('.wu-making-spent')!.textContent).toBe('Spent $0.0003 of up to $0.05');
    });

    it('says the whole’s most where the draft was funded with all of it: a control', async () => {
      answer([offerOf({ operation: { ...STEP } })], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        { state: 'drafting', elapsed_seconds: 1, poll_after_seconds: 30, accounting: { reported_usd: '0.0003' }, funded_usd: '1.42270000', operation: { ...STEP } },
      ]);
      await mount();
      type(field(), 'A quiet town');
      key(field(), 'Enter');
      await settle(); await settle();
      expect(document.querySelector('.wu-making-spent')!.textContent).toBe('Spent $0.0003 of up to $1.43');
    });

    it('still says a spent budget and what was spent where the refusal states no figures: a control', async () => {
      answer([offerOf({ operation: { ...STEP } })], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        { state: 'refused', elapsed_seconds: 2, poll_after_seconds: null, accounting: { reported_usd: '0.02' }, refusal: { code: 'budget_exceeded', spending: { reason: 'not_granted', retry: 'never' } } },
      ]);
      await mount();
      type(field(), 'A quiet town');
      key(field(), 'Enter');
      await settle(); await settle();
      expect(why()).toBe('The budget for AI models here is spent. Spent $0.02 before it stopped.');
      expect(document.body.textContent).not.toContain('Making stopped part way');
    });
  });

  it('opens with the focus in the composer and starts once for Enter, with the same key on a retry', async () => {
    serve(offerOf());
    await mount();
    expect(document.activeElement).toBe(field());
    type(field(), 'A harbour at night');
    // An answer that never came: back with the words and the reason, and Create again sends the same start.
    startAnswer = async () => { throw new TypeError('network'); };
    key(field(), 'Enter');
    await settle();
    expect(why()).toBe('Something went wrong while making it, so nothing was made. Try again.');
    expect(field().value).toBe('A harbour at night');
    expect(document.activeElement).toBe(field());
    key(field(), 'Enter');
    await settle();
    expect(starts.map((one) => one.words)).toEqual(['A harbour at night', 'A harbour at night']);
    expect(starts[1]!.key).toBe(starts[0]!.key);
    // Shift+Enter is a new line, never a start.
    const event = key(field(), 'Enter', { shiftKey: true });
    expect(event.defaultPrevented).toBe(false);
    expect(starts).toHaveLength(2);
  });

  it('keeps the focus in the composer when the cards to start from arrive after it', async () => {
    let release = () => {};
    cardsHeld.until = new Promise<void>((resolve) => { release = resolve; });
    serve(offerOf());
    await mount();
    const focusedFirst = document.activeElement === field();
    const cardsFirst = document.body.textContent?.includes('Small town');
    const before = field();
    type(before, 'A harbour');
    release();
    await settle();
    expect(focusedFirst).toBe(true);
    expect(cardsFirst).toBe(false);
    // The strip drew again with the cards: the composer is the same one, its words and focus kept.
    expect(document.body.textContent).toContain('Small town');
    expect(field()).toBe(before);
    expect(document.activeElement).toBe(before);
    expect(before.value).toBe('A harbour');
  });

  it('draws a served card\'s picture, and the current card\'s behind the page', async () => {
    const offer = offerOf();
    vi.stubGlobal('fetch', vi.fn(async (address: string) => {
      const body = address === '/card-pictures/card-pictures.v1.json'
        ? { profile: 'exulanica.card-pictures/v1', entries: [{ card: 'recipe:town', reference: { values: {} }, picture: 'recipe-town.jpg' }], held: [] }
        : address.endsWith('/worlds/drafts') ? offer : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
      return { ok: true, status: 200, json: async () => body };
    }));
    await mount();
    await settle();
    const card = document.querySelector<HTMLElement>('.wu-strip-card[data-key="recipe:town"]')!;
    expect(card.dataset['picture']).toBe('served');
    expect(card.getAttribute('aria-current')).toBe('true');
    expect(card.querySelector('img')!.getAttribute('src')).toBe('/card-pictures/recipe-town.jpg');
    const behind = (): string[] => [...document.querySelectorAll<HTMLElement>('.wu-create-media[data-shown="true"]')].map((one) => one.style.backgroundImage);
    expect(behind()).toHaveLength(1);
    expect(behind()[0]).toContain('/card-pictures/recipe-town.jpg');
    // Moved to Blank by its arrow key, the picture gives way to the ground; back, it returns.
    card.focus();
    key(card, 'ArrowRight');
    expect(document.activeElement).toBe(document.querySelector('.wu-strip-card[data-key="blank"]'));
    expect(behind()).toEqual([]);
    key(document.activeElement!, 'ArrowLeft');
    expect(behind()[0]).toContain('/card-pictures/recipe-town.jpg');
  });

  it('leaves on the first Esc, even from the composer, and keeps the words for next time', async () => {
    serve(offerOf());
    let closed = 0;
    const shown = await mount(() => { closed += 1; });
    type(field(), 'A quiet valley');
    key(field(), 'Escape');
    expect(closed).toBe(1);
    expect(shown.isConnected).toBe(false);
    await mount();
    expect(field().value).toBe('A quiet valley');
  });

  it('answers a starter card\'s press at once with its making steps, starts nothing else meanwhile, and gives the cards back on a refusal', async () => {
    serve(offerOf());
    const made: string[] = [];
    let answer: { reject: (error: unknown) => void } | null = null;
    let now = 1_000;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    const root = document.createElement('div'); document.body.append(root);
    (await page()).mountCreateWorld({ root, credentials: {}, onClose: () => {}, entries: {
      ensureStarter: async () => { made.push('blank'); return { entryId: 'starter' }; },
      entries: async () => [],
      makeGenerated: (key: string) => { made.push(key); return new Promise((_resolve, reject) => { answer = { reject }; }); },
    } });
    await settle();
    type(field(), 'A harbour');
    const card = document.querySelector<HTMLButtonElement>('.wu-strip-card[data-key="recipe:town"]')!;
    card.click();
    // At once, the start not yet answered: the making view, the card's name, and its one live step timed from the press.
    expect(document.querySelector('.wu-making-quote')!.textContent).toBe('Small town');
    expect(document.querySelector('h1.wu-create-title')!.textContent).toBe('Creating World');
    expect(stepRows()).toEqual([['Building World', 'now', '0 s']]);
    now += 7_400;
    vi.advanceTimersByTime(1_000);
    expect(stepRows()).toEqual([['Building World', 'now', '7 s']]);
    // No card, composer or Create is left to press; Enter, and the pressed card again, start nothing.
    expect(document.querySelector('.wu-strip-card, .wu-composer, .wu-composer-pill')).toBeNull();
    key(document.querySelector('section.wu-create')!, 'Enter');
    card.click();
    await settle();
    expect(made).toEqual(['town']);
    expect(starts).toEqual([]);
    // Refused: the page before Create again with the refusal said, every card pressable, and the step's clock stopped.
    answer!.reject(Object.assign(new Error('refused'), { code: 'world_draft_failed' }));
    await settle();
    expect(document.querySelector('.wu-making-steps')).toBeNull();
    expect(why()).toBe('Something went wrong while making it, so nothing was made. Try again.');
    expect(field().value).toBe('A harbour');
    expect(vi.getTimerCount()).toBe(0);
    document.querySelector<HTMLButtonElement>('.wu-strip-card[data-key="blank"]')!.click();
    await settle();
    expect(made).toEqual(['town', 'blank']);
  });

  it('follows a draft by its served steps and comes back with the words, the refusal and what was spent', async () => {
    serve(offerOf(), [
      { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
      { state: 'drafting', elapsed_seconds: 1, poll_after_seconds: 0, accounting: { reported_usd: '0.01' } },
      { state: 'refused', elapsed_seconds: 4, poll_after_seconds: null, refusal: { code: 'world_not_a_place' }, accounting: { reported_usd: '0.02' } },
    ]);
    await mount();
    type(field(), 'Purple');
    key(field(), 'Enter');
    await settle(); await settle();
    expect(why()).toBe('These words don’t describe a place, so no world could be made from them. Try a place and what is in it. Spent $0.02 before it stopped.');
    expect(price()).toBe('Up to $1.43');
    expect(field().value).toBe('Purple');
    expect(opened).toEqual([]);
    // A word typed takes the refusal away.
    type(field(), 'Purple hills');
    expect(why()).toBe('');
  });

  it('opens Blank through its opening, marked for build mode', async () => {
    serve(offerOf());
    await mount();
    const blank = document.querySelector<HTMLButtonElement>('.wu-strip-card[data-key="blank"]')!;
    expect([...document.querySelectorAll('.wu-strip-card')].at(-1)).toBe(blank);
    blank.click();
    await settle();
    expect(opened).toEqual(['starter']);
    expect(JSON.parse(sessionStorage.getItem('exulanica.made.v1')!)).toMatchObject({ entryId: 'starter', build: true });
  });

  describe('a start refused for its price (N32)', () => {
    const quoted = (maximum: string) => offerOf({ operation: { ...offerOf().operation, maximum_usd: maximum } });
    /** The offer first at $1.43, then at `next` once the start is refused for an expired quote. */
    const pressedWith = async (next: string): Promise<void> => {
      const offers = [quoted('1.4227'), quoted(next)];
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        const body = address.endsWith('/worlds/drafts') ? (offers.length > 1 ? offers.shift() : offers[0]) : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      let answers = 0;
      startAnswer = async () => (answers++ === 0
        ? { draftId: 'd-1', state: 'refused', refusal: { code: 'world_draft_price_expired' } }
        : { draftId: 'd-2', state: 'queued', refusal: null });
      await mount();
      type(field(), 'A harbour at night');
      key(field(), 'Enter');
      await settle(); await settle();
    };

    it('stops and says the new figure when the price went up: a positive control', async () => {
      await pressedWith('1.6');
      expect(starts.map((one) => one.most)).toEqual(['1.4227']);
      expect(why()).toBe('The price went up before it started. It can now spend at most $1.60.');
      expect(price()).toBe('Up to $1.60');
      // Create again starts at the new price.
      key(field(), 'Enter');
      await settle();
      expect(starts.map((one) => one.most)).toEqual(['1.4227', '1.6']);
    });

    it('starts again at once with the new quote and says nothing of a price when it is the same', async () => {
      await pressedWith('1.4227');
      expect(starts.map((one) => [one.words, one.most])).toEqual([['A harbour at night', '1.4227'], ['A harbour at night', '1.4227']]);
      expect(starts[1]!.key).not.toBe(starts[0]!.key);
      expect(making()).toBe(true);
      expect(document.body.textContent).not.toMatch(/price changed|price went up/u);
    });

    it('starts again at once when the new quote is lower, at the lower price', async () => {
      await pressedWith('1.2');
      expect(starts.map((one) => one.most)).toEqual(['1.4227', '1.2']);
      expect(document.body.textContent).not.toMatch(/price changed|price went up/u);
    });

    it('says the price cannot be read while the new quote is unreadable, then starts at the same price', async () => {
      const unreadable = offerOf({ offered: false, code: 'world_draft_price_unavailable', operation: null });
      const offers = [quoted('1.4227'), unreadable, quoted('1.4227')];
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        const body = address.endsWith('/worlds/drafts') ? (offers.length > 1 ? offers.shift() : offers[0]) : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
        return { ok: true, status: 200, json: async () => body };
      }));
      let answers = 0;
      startAnswer = async () => (answers++ === 0
        ? { draftId: 'd-1', state: 'refused', refusal: { code: 'world_draft_price_expired' } }
        : { draftId: 'd-2', state: 'queued', refusal: null });
      await mount();
      type(field(), 'A harbour at night');
      key(field(), 'Enter');
      await settle(); await settle();
      const said = document.body.textContent!;
      expect(said).toContain('The price can’t be read right now. Trying again.');
      expect(said).not.toContain('The price changed before it started.');
      expect(starts).toHaveLength(1);
      // Still on the making view, read again after the first backoff: the same price, so it starts at once and says nothing.
      expect(making()).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 1100));
      await settle();
      expect(starts.map((one) => one.most)).toEqual(['1.4227', '1.4227']);
    });

    it('says the price cannot be read in the plain ink where the read again fails, not that it changed', async () => {
      let reads = 0;
      vi.stubGlobal('fetch', vi.fn(async (address: string) => {
        if (!address.endsWith('/worlds/drafts')) return { ok: true, status: 200, json: async () => ({ state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 }) };
        // The offer reads once, then every read again fails.
        return reads++ === 0 ? { ok: true, status: 200, json: async () => quoted('1.4227') } : { ok: false, status: 503, json: async () => ({}) };
      }));
      startAnswer = async () => ({ draftId: 'd-1', state: 'refused', refusal: { code: 'world_draft_price_expired' } });
      await mount();
      type(field(), 'A harbour at night');
      key(field(), 'Enter');
      await settle(); await settle();
      const line = [...document.querySelectorAll('p, div, span')].find((one) => one.children.length === 0 && one.textContent === 'The price can’t be read right now. Trying again.');
      expect(line).toBeDefined();
      expect(line!.getAttribute('data-tone')).toBeNull();
      expect(document.body.textContent).not.toContain('The price changed before it started.');
      expect(starts).toHaveLength(1);
    });
  });
});

// Web notes in Create: asked for with the composer's "Search the web" toggle (on until it is pressed), the notes' steps
// and the notes on the making view, the draft started with them, or from the words alone where none came.
describe('Create a world with web notes', () => {
  const READY = (JSON.parse(readFileSync('../tests/snapshots/world-drafts.served.json', 'utf8')) as Record<string, Record<string, unknown>>)['ready_place']!;
  const NOTES_OFFER = { offered: true, code: null, searches_at_most: 3, maximum_usd: '0.0153' };
  const request = (status: string, extra: Record<string, unknown> = {}) => ({
    reference_id: 'r-1', purpose: 'world_draft', web: true, status, missed: [], failure: null, bundle_sha256: null, cancel_requested: false,
    created_at: '2026-10-26T10:00:00Z', finished_at: null, notes: [], searches: [],
    steps: [{ step: 'plan', state: 'done' }, { step: 'search', state: 'running' }, { step: 'read', state: 'waiting' }, { step: 'bundle', state: 'waiting' }],
    ...extra,
  });
  const search = { source: 'tavily', outcome: 'sent', result_count: 5, credits: 1, sent_at: '2026-10-26T10:00:01Z' };
  const KEPT = request('complete', {
    steps: ['plan', 'search', 'read', 'bundle'].map((step) => ({ step, state: 'done' })),
    notes: [{ aspect: 'buildings', text: 'Narrow terraced houses in soft pastel colours', basis: 'web_description' },
      { aspect: 'vehicles_and_boats', text: 'Small wooden fishing boats moored in a row', basis: 'web_description' }],
    searches: [search, search, search],
  });
  const asked: { method: string; path: string; body: unknown }[] = [];
  afterEach(() => { vi.unstubAllGlobals(); starts.length = 0; asked.length = 0; opened.length = 0; sessionStorage.clear(); startAnswer = async () => ({ draftId: 'd-1', state: 'queued', refusal: null }); });

  /** The offer with notes (or as `offers` give it, one per read and the last again), the notes request's answers in turn
   * (or a refusal), then the draft's reads. */
  function serveNotes(answers: unknown[] | 'refused', reads: Record<string, unknown>[], offers: Record<string, unknown>[] | null = null): void {
    let offerReads = 0;
    vi.stubGlobal('fetch', vi.fn(async (address: string, init?: RequestInit) => {
      const path = new URL(address).pathname, method = init?.method ?? 'GET';
      asked.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
      const answer = (status: number, body: unknown) => ({ ok: status < 300, status, statusText: '', headers: new Headers(), json: async () => body });
      if (path === '/worlds/references') {
        return answers === 'refused' ? answer(409, { code: 'references_not_run_here', detail: 'no' }) : answer(202, answers.shift());
      }
      if (path.startsWith('/worlds/references/')) return answer(200, (answers as unknown[]).shift());
      if (path === '/worlds/drafts') return answer(200, offers === null ? offerOf({ own_key: true, notes: NOTES_OFFER }) : offers[Math.min(offerReads++, offers.length - 1)]);
      return answer(200, reads.shift() ?? { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 });
    }));
  }
  const mountNotes = async () => {
    const root = document.createElement('div'); document.body.append(root);
    (await page()).mountCreateWorld({ root, credentials: { baseUrl: 'https://host.test', token: 'install' }, entries: { ensureStarter: async () => ({ entryId: 'starter' }), entries: async () => [] }, onClose: () => {} });
    await settle();
  };
  const chip = (): HTMLButtonElement => document.querySelector<HTMLButtonElement>('.wu-composer-chip')!;

  it('searches the web first by default, prices the notes, drafts with them and says what they gave', async () => {
    serveNotes([request('running'), KEPT], [{ ...READY, references: { state: 'used', reference_id: 'r-1', code: null, detail: null, notes: 2, bundle_sha256: 'a'.repeat(64), basis: ['web_description'], searches: 3, spent_usd: '0.00200000' } }]);
    await mountNotes();
    expect(chip().textContent).toBe('Web Search');
    expect(chip().getAttribute('aria-pressed')).toBe('true');
    expect(document.getElementById(chip().getAttribute('aria-describedby')!)!.textContent)
      .toBe('Looks up what such a place looks like before it is made: up to 3 searches with Tavily, which keeps them. Adds at most $0.02.');
    // On, the price is the whole most with the notes; off, the draft's alone.
    expect(price()).toBe('Up to $1.44');
    chip().click();
    expect(price()).toBe('Up to $1.43');
    chip().click();
    expect(price()).toBe('Up to $1.44');
    type(field(), 'a cozy little town by the sea at dusk');
    key(field(), 'Enter');
    // The making view at once, the wait first, before the notes request answers.
    expect(making()).toBe(true);
    expect(stepRows()[0]).toEqual(['Queued', 'now', '0 s']);
    await settle();
    await new Promise((resolve) => setTimeout(resolve, 1100));
    await settle(); await settle();
    const posted = asked.find((one) => one.method === 'POST' && one.path === '/worlds/references')!;
    expect(posted.body).toMatchObject({ purpose: 'world_draft', description: 'a cozy little town by the sea at dusk', web: true });
    expect(starts.map((one) => one.reference)).toEqual(['r-1']);
    const web = document.querySelector('.wu-making-web')!;
    expect(web.querySelector('.wu-making-kind')!.textContent).toBe('Web References · 3 Searches');
    expect([...web.querySelectorAll('.wu-making-note')].map((note) => note.textContent)).toEqual([
      'BuildingsNarrow terraced houses in soft pastel colours', 'Vehicles and boatsSmall wooden fishing boats moored in a row',
    ]);
    // No line of explanation under the notes (the mock).
    expect(web.textContent).not.toContain('A model wrote these');
    const words = stepRows().map((row) => row[0]);
    expect(words.slice(0, 4)).toEqual(['Queued', 'Planning Queries', 'Searching Web', 'Synthesizing Context']);
    expect(words.filter((one) => one === 'Queued')).toHaveLength(1);
    await settle(); await settle();
    const handed = JSON.parse(sessionStorage.getItem('exulanica.made.v1') ?? 'null') as { line: string | null } | null;
    expect(handed?.line?.startsWith('2 notes from the web · $')).toBe(true);
  });

  it('drafts from the words alone where no notes came, and says why where they would stand', async () => {
    serveNotes('refused', []);
    await mountNotes();
    type(field(), 'a cozy little town by the sea at dusk');
    // The toggle is a button: Enter and Space on it press it, as anywhere; Enter in the words creates.
    chip().focus();
    expect(key(chip(), 'Space').defaultPrevented).toBe(false);
    expect(key(chip(), 'Enter').defaultPrevented).toBe(false);
    field().focus();
    key(field(), 'Enter');
    await settle(); await settle();
    expect(starts.map((one) => one.reference)).toEqual([null]);
    expect(document.querySelector('.wu-making-web')!.textContent).toBe('Web ReferencesThe web notes could not be made, so it is made from your words alone.');
  });

  describe('the start after the notes (the judges\' server, 27 October: a quote expired while the notes ran)', () => {
    const priced = (maximum: string) => offerOf({ own_key: true, notes: NOTES_OFFER, operation: { ...offerOf().operation, maximum_usd: maximum } });
    const refusedFor = (code: string) => Object.assign(new Error('refused'), { code });
    const offerReads = () => asked.filter((one) => one.method === 'GET' && one.path === '/worlds/drafts').length;
    /** With "Search the web" on, as it opens, types, presses Enter in the words and lets the notes and the start answer. */
    const pressedWithNotes = async (): Promise<void> => {
      await mountNotes();
      expect(chip().getAttribute('aria-pressed')).toBe('true');
      type(field(), 'a cozy little town by the sea at dusk');
      field().focus();
      key(field(), 'Enter');
      await settle(); await settle(); await settle();
    };

    it('reads the sheet again after the notes, and after a start refused for its price reads again and starts once', async () => {
      serveNotes([KEPT], [{ state: 'making', elapsed_seconds: 1, poll_after_seconds: 30 }]);
      let answers = 0;
      startAnswer = async () => { if (answers++ === 0) throw refusedFor('world_draft_price_expired'); return { draftId: 'd-2', state: 'queued', refusal: null }; };
      await pressedWithNotes();
      // Read when Create opened, again after the notes, and again after the refusal.
      expect(offerReads()).toBe(3);
      expect(starts.map((one) => one.reference)).toEqual(['r-1', 'r-1']);
      // Following the draft on the making view, never left on the notes' last step.
      expect(making()).toBe(true);
      expect(stepRows().map((row) => row[0])).toContain('Building World');
      expect(document.body.textContent).not.toMatch(/price changed|price went up/u);
    });

    it('stops at a higher price and says the new figure in the price\'s place, waiting for Create', async () => {
      serveNotes([KEPT], [], [priced('1.4227'), priced('1.4227'), priced('1.6')]);
      startAnswer = async () => { throw refusedFor('world_draft_price_expired'); };
      await pressedWithNotes();
      expect(starts).toHaveLength(1);
      expect(making()).toBe(false);
      expect(why()).toBe('The price went up before it started. It can now spend at most $1.60.');
      expect(price()).toBe('Up to $1.62');
      expect(field().value).toBe('a cozy little town by the sea at dusk');
    });

    it('stops at a higher price read after the notes before any start is sent', async () => {
      serveNotes([KEPT], [], [priced('1.4227'), priced('1.6')]);
      await pressedWithNotes();
      expect(starts).toEqual([]);
      expect(making()).toBe(false);
      expect(why()).toBe('The price went up before it started. It can now spend at most $1.60.');
      expect(field().value).toBe('a cozy little town by the sea at dusk');
    });

    it('does not loop on a second refusal for its price: it says the price changed, with the new most, and waits', async () => {
      serveNotes([KEPT], []);
      startAnswer = async () => { throw refusedFor('world_draft_price_expired'); };
      await pressedWithNotes();
      await new Promise((resolve) => setTimeout(resolve, 1200));
      await settle();
      expect(starts.map((one) => one.reference)).toEqual(['r-1', 'r-1']);
      expect(making()).toBe(false);
      expect(why()).toBe('The price changed before it started. Here is the new most it can spend.');
      expect(price()).toBe('Up to $1.44');
    });

    it('leaves the making view for any other refusal, its sentence said and the words kept', async () => {
      serveNotes([KEPT], []);
      startAnswer = async () => { throw refusedFor('kind_draft_busy'); };
      await pressedWithNotes();
      expect(starts).toHaveLength(1);
      expect(making()).toBe(false);
      expect(why()).toBe('A world is being made already. It waits in Your worlds when it\u2019s done.');
      expect(document.querySelector('.wu-making-steps, .wu-making-web')).toBeNull();
      expect(field().value).toBe('a cozy little town by the sea at dusk');
      expect(document.activeElement).toBe(field());
    });
  });

  it('asks the web for nothing where the toggle is pressed off: a control', async () => {
    serveNotes([request('running')], []);
    await mountNotes();
    chip().click();
    type(field(), 'a cozy little town by the sea at dusk');
    key(field(), 'Enter');
    await settle();
    expect(asked.some((one) => one.path.startsWith('/worlds/references'))).toBe(false);
    expect(starts.map((one) => one.reference)).toEqual([null]);
    // Pressed off, it stays off when the page opens again, until it is pressed on.
    document.body.replaceChildren();
    await mountNotes();
    expect(chip().getAttribute('aria-pressed')).toBe('false');
    chip().click();
    expect(chip().getAttribute('aria-pressed')).toBe('true');
  });
});

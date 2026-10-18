// @vitest-environment happy-dom
// Making a world's light parts (tools/previews/world-workspace/world-ui-create.ts): what they say to
// a keyboard and a screen reader. The orb is one button, "Create", out of reach while it cannot
// start; the field stops at its limit and counts from the first letter; the cards name themselves,
// Blank last, one Tab stop; Esc is drawn once, as the quiet command, never in the key row; the
// steps are a polite live region; the made note is announced once and leaves when dismissed.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Step { words: string; state: 'done' | 'now' | 'next'; sub?: string; time?: string }
interface SentenceField { readonly root: HTMLElement; readonly label: HTMLElement; readonly field: HTMLTextAreaElement; readonly count: HTMLElement; set(words: string): void }
interface LightPage { readonly root: HTMLElement; readonly head: HTMLElement; readonly lower: HTMLElement; readonly quiet: HTMLElement; readonly keys: HTMLElement; form(next: 'create' | 'creating'): void }
interface FilmCardWords { key: string; name: string; sub: string; picture: string | null; blank?: boolean }
interface FilmStrip { readonly root: HTMLElement; readonly cards: readonly HTMLButtonElement[]; choose(index: number, focus?: boolean): void; readonly chosen: number }
interface CreateParts {
  lightPage(options?: { form?: 'create' | 'creating'; picture?: string | null; labelledBy?: string }): LightPage;
  sentenceField(options: { limit: number; value?: string; onInput?: (words: string) => void }): SentenceField;
  createOrb(options: { onPress: () => void; ready?: boolean }): HTMLButtonElement;
  setOrbReady(button: HTMLButtonElement, ready: boolean): void;
  sentenceRow(field: SentenceField, button: HTMLButtonElement): HTMLElement;
  filmStrip(cards: readonly FilmCardWords[], onStart: (key: string) => void): FilmStrip;
  quietCommand(options: { onPress: () => void; place?: 'quiet' | 'row' }): HTMLButtonElement;
  createKeyRow(row: HTMLElement, keys: { create: boolean; start: boolean }): void;
  lightSteps(steps?: readonly Step[]): { readonly root: HTMLElement; set(steps: readonly Step[]): void };
  lightLine(words: string, options?: { tone?: 'plain' | 'refused'; live?: boolean }): HTMLElement;
  madeNote(columns: readonly { label: string; value: string }[]): { readonly root: HTMLElement; dismiss(): void };
}
interface CreateSteps { startCards(recipes?: readonly unknown[], kinds?: readonly unknown[]): FilmCardWords[] }
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

/** Frame 20 built from the parts, as the page will build it. */
async function frame20(words = '') {
  const create = await parts();
  const { startCards } = await steps();
  const page = create.lightPage({ labelledBy: 'title' });
  document.body.append(page.root);
  const title = document.createElement('h1'); title.id = 'title'; title.tabIndex = -1; title.textContent = 'Create a world';
  const field = create.sentenceField({ limit: 1000, value: words });
  const orb = create.createOrb({ onPress: () => {}, ready: words.trim().length > 0 });
  page.head.append(title, create.sentenceRow(field, orb));
  const strip = create.filmStrip(startCards([{ key: 'town', name: 'Small town', picture: null }], [{ key: 'wall', name: 'Wall city', priceUsd: '0.4' }]), () => {});
  page.lower.append(strip.root);
  const leave = create.quietCommand({ onPress: () => {} });
  page.quiet.append(leave);
  create.createKeyRow(page.keys, { create: words.trim().length > 0, start: false });
  return { create, page, title, field, orb, strip, leave };
}

describe('the Create orb', () => {
  it('is one button named "Create", dimmed and out of the Tab order until a word is typed', async () => {
    const { create, page, orb, field } = await frame20();
    const orbs = [...page.root.querySelectorAll('.wu-orb')];
    expect(orbs).toEqual([orb]);
    expect(orb.tagName).toBe('BUTTON');
    expect(orb.querySelector('.wu-orb-word')!.textContent).toBe('Create');
    expect(orb.disabled).toBe(true);
    type(field.field, 'a harbour');
    create.setOrbReady(orb, true);
    expect(orb.disabled).toBe(false);
  });
});

describe('the sentence field', () => {
  it('stops at the offer\'s limit, is labelled "Describe it" and counts from the first letter', async () => {
    const { field } = await frame20();
    expect(field.field.maxLength).toBe(1000);
    const label = field.label as HTMLLabelElement;
    expect(label.textContent).toBe('Describe it');
    expect(label.htmlFor).toBe(field.field.id);
    expect(field.field.placeholder).toBe('A harbour with fishing boats, a market on the quay and a lighthouse');
    // Empty, the count keeps its line but is out of sight and out of a screen reader's reading (N23).
    expect(field.count.dataset.empty).toBe('true');
    expect(field.count.getAttribute('aria-hidden')).toBe('true');
    type(field.field, 'Glass terraces with glowing pools above the sea at night, and a grand hotel at the top');
    expect(field.count.dataset.empty).toBeUndefined();
    expect(field.count.hasAttribute('aria-hidden')).toBe(false);
    expect(field.count.textContent).toBe('86 of 1000');
    expect(field.field.getAttribute('aria-describedby')).toBe(field.count.id);
    field.set('x'.repeat(1200));
    expect(field.count.textContent).toBe('1000 of 1000');
    expect(field.count.dataset.full).toBe('true');
    type(field.field, '');
    expect(field.count.dataset.empty).toBe('true');
  });
});

describe('the cards to start from', () => {
  it('name themselves, keep Blank last and make one Tab stop that arrows move', async () => {
    const { strip } = await frame20();
    expect(strip.cards.map(nameOf)).toEqual(['Small town', 'Wall city', 'Blank']);
    expect(strip.cards.map((card) => document.getElementById(card.getAttribute('aria-describedby')!)!.textContent)).toEqual(['No AI model · Free', 'At most $0.40', 'Build it yourself']);
    expect(strip.cards.map((card) => card.tabIndex)).toEqual([0, -1, -1]);
    expect(strip.cards.map((card) => card.getAttribute('aria-keyshortcuts'))).toEqual(['Enter', 'Enter', 'Enter']);
    strip.choose(2, true);
    expect(strip.cards.map((card) => card.tabIndex)).toEqual([-1, -1, 0]);
    expect(strip.cards[2]!.getAttribute('aria-current')).toBe('true');
    expect(strip.cards.filter((card) => card.hasAttribute('aria-current'))).toHaveLength(1);
    expect(document.activeElement).toBe(strip.cards[2]);
    expect(strip.cards[2]!.dataset.picture).toBe('blank');
    expect(strip.cards[0]!.dataset.picture).toBe('none');
    // A quiet card's tile is the material alone: its name is said once, by the line under it (N30).
    expect(strip.cards[0]!.querySelector('.wu-film-picture')!.textContent).toBe('');
    expect(strip.cards[0]!.textContent).toBe('Small townNo AI model · Free');
    expect(strip.root.querySelector('[role="group"]')!.getAttribute('aria-labelledby')).toBe(strip.root.querySelector('.wu-light-label')!.id);
  });

  it('keep Blank after the cards that scroll, outside the scroll, so it always shows (N27)', async () => {
    const { strip } = await frame20();
    const scroller = strip.root.querySelector<HTMLElement>('.wu-film-strip')!;
    const blank = strip.cards.at(-1)!;
    expect(scroller.contains(blank)).toBe(false);
    expect(strip.cards.slice(0, -1).every((card) => scroller.contains(card))).toBe(true);
    expect(blank.parentElement).toBe(scroller.parentElement);
    expect(blank.parentElement!.getAttribute('role')).toBe('group');
  });

  it('measure their faded edges once laid out and whenever the strip changes size (N27)', async () => {
    const observed: { callback: () => void; target: Element | null }[] = [];
    vi.stubGlobal('ResizeObserver', class { constructor(callback: () => void) { observed.push({ callback, target: null }); } observe(target: Element) { observed.at(-1)!.target = target; } disconnect() {} });
    try {
      const { strip } = await frame20();
      const scroller = strip.root.querySelector<HTMLElement>('.wu-film-strip')!;
      const watch = observed.find((one) => one.target === scroller);
      expect(watch).toBeDefined();
      // Laid out wider than it shows: the far end fades without any scroll.
      Object.defineProperties(scroller, { clientWidth: { value: 600, configurable: true }, scrollWidth: { value: 1400, configurable: true } });
      watch!.callback();
      expect(scroller.dataset.moreAfter).toBe('true');
      expect(scroller.dataset.moreBefore).toBe('false');
    } finally { vi.unstubAllGlobals(); }
  });
});

describe('Esc and the key row', () => {
  it('draws Esc once, as the quiet command "Your worlds", and never in the key row', async () => {
    const { create, page, leave } = await frame20('a harbour');
    expect(leave.tagName).toBe('BUTTON');
    expect(nameOf(leave)).toContain('Your worlds');
    expect(leave.getAttribute('aria-keyshortcuts')).toBe('Escape');
    expect(leave.querySelector('.wu-qcmd-key')!.getAttribute('aria-hidden')).toBe('true');
    expect(leave.dataset.place).toBe('quiet');
    expect(page.quiet.contains(leave)).toBe(true);
    for (const keys of [{ create: true, start: false }, { create: false, start: true }, { create: true, start: true }]) {
      create.createKeyRow(page.keys, keys);
      const row = [...page.keys.querySelectorAll('[aria-keyshortcuts]')];
      expect(row.map((one) => one.getAttribute('aria-keyshortcuts'))).not.toContain('Escape');
      expect(page.keys.textContent).not.toContain('Esc');
      expect([...page.root.querySelectorAll('[aria-keyshortcuts="Escape"]')]).toEqual([leave]);
    }
    create.createKeyRow(page.keys, { create: true, start: false });
    expect(page.keys.textContent).toBe('EnterCreate');
    // The row says keys; it is not a set of buttons (the orb and the cards are).
    expect(page.keys.querySelectorAll('button')).toHaveLength(0);
    create.createKeyRow(page.keys, { create: false, start: true });
    expect(page.keys.textContent).toBe('EnterStart');
  });

  it('puts the focusable parts in reading order: field, orb, the chosen card, then Your worlds', async () => {
    const { page, field, orb, strip, leave } = await frame20('a harbour');
    const order = [...page.root.querySelectorAll<HTMLElement>('button, textarea, [tabindex]')].filter((one) => one.tabIndex >= 0 && !(one as HTMLButtonElement).disabled);
    expect(order).toEqual([field.field, orb, strip.cards[0], leave]);
    expect(page.root.getAttribute('role')).toBe('dialog');
    expect(page.root.getAttribute('aria-labelledby')).toBe('title');
  });
});

describe('the steps', () => {
  it('mark the running step and say each new one once in a polite live region', async () => {
    const create = await parts();
    const shown = create.lightSteps([{ words: 'Worked out what to make', state: 'done', time: '1 s' }, { words: 'Planning the place', state: 'now', time: '6 s' }]);
    document.body.append(shown.root);
    const live = shown.root.querySelector('[aria-live]')!;
    expect(live.getAttribute('aria-live')).toBe('polite');
    expect(live.textContent).toBe('Planning the place');
    const now = shown.root.querySelector('[aria-current="step"]')!;
    expect(now.querySelector('.wu-step-words')!.textContent).toBe('Planning the place');
    expect(shown.root.querySelectorAll('[aria-current]')).toHaveLength(1);
    shown.set([{ words: 'Worked out what to make', state: 'done', time: '1 s' }, { words: 'Planning the place', state: 'now', time: '9 s' }]);
    expect(live.textContent).toBe('Planning the place');
    shown.set([{ words: 'Worked out what to make', state: 'done', time: '1 s' }, { words: 'Planning the place', state: 'done', time: '9 s' }, { words: 'Building it', state: 'now', time: '12 s' }]);
    expect(live.textContent).toBe('Building it');
    expect(shown.root.querySelectorAll('.wu-step')).toHaveLength(3);
    expect(shown.root.querySelector('[aria-current="step"] .wu-step-time')!.textContent).toBe('12 s');
  });

  it('says a refusal in the light refusal ink as a status', async () => {
    const { lightLine } = await parts();
    const line = lightLine('These words don’t describe a place, so no world could be made from them. Try a place and what is in it.', { tone: 'refused', live: true });
    expect(line.getAttribute('role')).toBe('status');
    expect(line.dataset.tone).toBe('refused');
  });
});

describe('the made note', () => {
  it('is announced once, leaves an empty column out and leaves when dismissed', async () => {
    vi.useFakeTimers();
    const { madeNote } = await parts();
    const note = madeNote([{ label: 'In it', value: 'Four pools, a hotel' }, { label: 'Not in it yet', value: ' ' }, { label: 'Spent', value: '$0.31 of the $1.43 set aside' }]);
    document.body.append(note.root);
    expect(note.root.getAttribute('role')).toBe('status');
    // On the page empty, then filled, so it is announced once (N24).
    expect(note.root.childElementCount).toBe(0);
    vi.advanceTimersByTime(0);
    expect([...note.root.querySelectorAll('.wu-made-label')].map((one) => one.textContent)).toEqual(['In it', 'Spent']);
    note.dismiss();
    expect(note.root.dataset.leaving).toBe('true');
    vi.advanceTimersByTime(300);
    expect(note.root.isConnected).toBe(false);
  });
});

// Create a world as a page (create-world.ts, frames 20 and 21) over stand-in answers: the offer and
// the draft reads come through the workspace's own read path, a start through the app's client.
const opened: string[] = [];
const starts: { words: string; key: string }[] = [];
let startAnswer: () => Promise<unknown> = async () => ({ draftId: 'd-1', state: 'queued', refusal: null });
vi.mock('../../../../tools/previews/world-workspace/front-door.ts', () => ({
  chosenWorldPicture: () => null,
  openMadeWorld: async (entry: { entryId: string }) => { opened.push(entry.entryId); },
}));
vi.mock('../src/world-specification.ts', () => ({
  WorldSpecificationClient: class { async specification() { return { presets: [{ key: 'town', label: 'Small town', values: {} }] }; } },
}));
vi.mock('../src/world-kinds-api.ts', () => ({ WorldKindsClient: class { async library() { return { kinds: [] }; } } }));
vi.mock('../src/world-making-api.ts', async (original) => {
  const real = await original<typeof import('../src/world-making-api.ts')>();
  return {
    ...real,
    WorldMakingClient: class {
      async start(words: string, submission: { idempotencyKey: string }) { starts.push({ words, key: submission.idempotencyKey }); return startAnswer(); }
    },
  };
});

interface CreatePage { mountCreateWorld(options: { root: HTMLElement; credentials: unknown; entries: unknown; onClose: () => void }): { readonly isConnected: boolean; remove(): void } | null }
const page = async (): Promise<CreatePage> => import('../../../../tools/previews/world-workspace/' + 'create-world.ts') as Promise<CreatePage>;

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
    const body = address === '/review-api/worlds/drafts' ? offer : reads.shift() ?? { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
    return { ok: true, status: 200, json: async () => body };
  }));
}

const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) await new Promise((resolve) => setTimeout(resolve, 0)); };
const key = (target: Element, code: string, extra: KeyboardEventInit = {}): KeyboardEvent => {
  const event = new KeyboardEvent('keydown', { code, key: code === 'Enter' ? 'Enter' : code, bubbles: true, cancelable: true, ...extra });
  target.dispatchEvent(event);
  return event;
};

describe('Create a world as a page', () => {
  let saved: unknown[] = [];
  afterEach(() => { vi.unstubAllGlobals(); opened.length = 0; starts.length = 0; saved = []; startAnswer = async () => ({ draftId: 'd-1', state: 'queued', refusal: null }); });
  const mount = async (onClose = () => {}) => {
    const root = document.createElement('div'); document.body.append(root);
    const shown = (await page()).mountCreateWorld({ root, credentials: {}, entries: { ensureStarter: async () => ({ entryId: 'starter' }), entries: async () => saved }, onClose });
    await settle();
    return shown!;
  };

  it('says a refusal now in its own words, with no starts left over it and Create dimmed', async () => {
    serve(offerOf({ offered: false, code: 'kind_draft_limit', operation: null }));
    await mount();
    const text = document.body.textContent!;
    expect(text).toContain('You’ve started as many worlds as you can this hour. Try again later.');
    expect(text).not.toContain('more worlds can be started');
    expect(text).not.toMatch(/USD|reservation|kind_draft_limit/u);
    expect(document.querySelector<HTMLButtonElement>('.wu-light-orb')!.disabled).toBe(true);
  });

  it('opens with the focus in the field and starts once for Enter, with the same key on a retry', async () => {
    serve(offerOf());
    await mount();
    const field = document.querySelector<HTMLTextAreaElement>('.wu-light-field')!;
    expect(document.activeElement).toBe(field);
    expect(document.body.textContent).toContain('2 more worlds can be started this hour.');
    type(field, 'A harbour at night');
    // An answer that never came: Create again sends the same start.
    startAnswer = async () => { throw new TypeError('network'); };
    key(field, 'Enter');
    await settle();
    key(document.querySelector('.wu-light-field')!, 'Enter');
    await settle();
    expect(starts.map((one) => one.words)).toEqual(['A harbour at night', 'A harbour at night']);
    expect(starts[1]!.key).toBe(starts[0]!.key);
    // Shift+Enter is a new line, never a start.
    const event = key(document.querySelector('.wu-light-field')!, 'Enter', { shiftKey: true });
    expect(event.defaultPrevented).toBe(false);
    expect(starts).toHaveLength(2);
  });

  it('leaves on the first Esc, even from the field, and keeps the words for next time', async () => {
    serve(offerOf());
    let closed = 0;
    const shown = await mount(() => { closed += 1; });
    type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet valley');
    key(document.querySelector('.wu-light-field')!, 'Escape');
    expect(closed).toBe(1);
    expect(shown.isConnected).toBe(false);
    await mount();
    expect(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!.value).toBe('A quiet valley');
  });

  it('follows a draft by its served steps and comes back with the words, the refusal and what was spent', async () => {
    serve(offerOf(), [
      { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
      { state: 'drafting', elapsed_seconds: 1, poll_after_seconds: 0, accounting: { reported_usd: '0.01' } },
      { state: 'refused', elapsed_seconds: 4, poll_after_seconds: null, refusal: { code: 'world_not_a_place' }, accounting: { reported_usd: '0.02' } },
    ]);
    await mount();
    type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'Purple');
    key(document.querySelector('.wu-light-field')!, 'Enter');
    await settle(); await settle();
    const text = document.body.textContent!;
    expect(text).toContain('These words don’t describe a place, so no world could be made from them. Try a place and what is in it.');
    expect(text).toContain('Spent $0.02 before it stopped.');
    expect(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!.value).toBe('Purple');
    expect(opened).toEqual([]);
  });

  it('says Blank opens My world again where the blank world is saved already (N27)', async () => {
    serve(offerOf());
    await mount();
    const sub = () => document.querySelector('.wu-film-card[data-key="blank"] .wu-film-sub')!.textContent;
    expect(sub()).toBe('Build it yourself');
    document.body.replaceChildren();
    saved = [{ entryId: 'other', authoredScene: null }, { entryId: 'starter', authoredScene: { kind: 'authored-starter' } }];
    await mount();
    expect(sub()).toBe('Opens My world again');
  });

  it('opens Blank through its opening, marked for build mode', async () => {
    serve(offerOf());
    await mount();
    const blank = document.querySelector<HTMLButtonElement>('.wu-film-card[data-key="blank"]')!;
    expect([...document.querySelectorAll('.wu-film-card')].at(-1)).toBe(blank);
    blank.click();
    await settle();
    expect(opened).toEqual(['starter']);
    expect(JSON.parse(sessionStorage.getItem('exulanica.made.v1')!)).toMatchObject({ entryId: 'starter', build: true });
  });
});

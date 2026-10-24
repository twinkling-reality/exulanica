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
    const note = madeNote([{ label: 'In it', value: 'Four pools, a hotel' }, { label: 'Not in it yet', value: ' ' }, { label: 'Spent', value: '$0.31 of at most $1.43' }]);
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
const starts: { words: string; key: string; most: string }[] = [];
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
      async start(words: string, submission: { idempotencyKey: string; maximumUsd: string }) { starts.push({ words, key: submission.idempotencyKey, most: submission.maximumUsd }); return startAnswer(); }
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

describe('Create a world as a page', () => {
  let saved: unknown[] = [];
  afterEach(() => { vi.unstubAllGlobals(); opened.length = 0; starts.length = 0; saved = []; startAnswer = async () => ({ draftId: 'd-1', state: 'queued', refusal: null }); });
  const mount = async (onClose = () => {}) => {
    const root = document.createElement('div'); document.body.append(root);
    const shown = (await page()).mountCreateWorld({ root, credentials: {}, entries: { ensureStarter: async () => ({ entryId: 'starter' }), entries: async () => saved }, onClose });
    await settle();
    return shown!;
  };

  it('keeps Tab within the page, from its last stop to its first and back, never on to the front door under it (C6)', async () => {
    serve(offerOf());
    const behind = document.createElement('button'); behind.textContent = 'Open My world'; document.body.append(behind);
    await mount();
    const field = document.querySelector<HTMLTextAreaElement>('textarea.wu-light-field')!;
    field.focus();
    // Shift+Tab from the field, the first stop, goes to the last, Your worlds.
    expect(key(field, 'Tab', { shiftKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement?.classList.contains('wu-qcmd')).toBe(true);
    // Tab from the last stop comes back to the field, not on to the front door's own button.
    expect(key(document.activeElement!, 'Tab').defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(field);
    expect(document.activeElement).not.toBe(behind);
    // Between the first and the last, the browser moves the focus.
    expect(key(field, 'Tab').defaultPrevented).toBe(false);
    document.body.replaceChildren();
  });

  it('says under the field how long a host keeps what is made where it states a day, and nothing where it states none (A5)', async () => {
    const kept = 'The worlds you make here and the words you type stay on this server until it is deleted after 15\u00a0December\u00a02026.';
    serve(offerOf());
    const quiet = await mount();
    expect(document.body.textContent).not.toContain('stay on this server');
    quiet.remove(); document.body.replaceChildren();
    serve(offerOf({ host_keeps_until: '2026-12-15' }));
    await mount();
    expect(document.body.textContent).toContain(kept);
    document.body.replaceChildren();
    // Said too where words make no world here and the starters stand alone (a host that takes none from a person).
    serve(offerOf({ offered: false, code: 'kinds_from_people_not_offered', operation: null, host_keeps_until: '2026-12-15' }));
    await mount();
    expect(document.body.textContent).toContain(kept);
  });

  it('says a refusal now in its own words, with no starts left over it and Create dimmed', async () => {
    serve(offerOf({ offered: false, code: 'kind_draft_limit', operation: null }));
    await mount();
    const text = document.body.textContent!;
    expect(text).toContain('You’ve started as many worlds as you can this hour. Try again later.');
    expect(text).not.toContain('more worlds can be started');
    expect(text).not.toMatch(/USD|reservation|kind_draft_limit/u);
    expect(document.querySelector<HTMLButtonElement>('.wu-light-orb')!.disabled).toBe(true);
  });

  it('says what a step of making could cost against what is left, with no field, where the budget left is short of one (N31, A1b)', async () => {
    serve(offerOf({ offered: false, code: 'world_draft_bound_exceeds_left', left_usd: '0.01', operation: { ...offerOf().operation, step_usd_at_most: '0.0344064' } }));
    await mount();
    const text = document.body.textContent!;
    expect(text).toContain('Making a world from your words can cost up to $0.04 a step, more than the $0.01 left for AI models here. You can still start from these:');
    expect(text).not.toContain('The budget for AI models here is spent.');
    expect(document.querySelector('.wu-light-field')).toBeNull();
  });

  it('says spending is paused, not spent, with no field, where the authority is held closed (N34)', async () => {
    serve(offerOf({ offered: false, code: 'spending_suspended', operation: null }));
    await mount();
    const text = document.body.textContent!;
    expect(text).toContain('Spending on AI models is paused here, so nothing can be made from your words now. You can still start from these:');
    expect(text).not.toContain('is spent');
    expect(text).not.toContain('spending_suspended');
    expect(document.querySelector('.wu-light-field')).toBeNull();
  });

  it('says the most is what is left where less than the whole is left, and the whole where it is (A1b)', async () => {
    serve(offerOf({ left_usd: '0.05' }));
    await mount();
    expect(document.body.textContent).toContain('An open model makes it from your words: at most the $0.05 left for AI models here, and you see what it really spent.');
    document.body.replaceChildren();
    serve(offerOf());
    await mount();
    expect(document.body.textContent).toContain('An open model makes it from your words: at most $1.43, and you see what it really spent.');
  });

  it('says under the title what a newcomer can do, and names the person\'s own key where the draft runs on it (C4)', async () => {
    const keyed = (extra: Record<string, unknown> = {}) => offerOf({ own_key: true, operation: { ...offerOf().operation, providers: [{ provider: 'nebius_token_factory', ceiling_usd: '1.4227' }] }, ...extra });
    serve(keyed());
    await mount();
    const sub = document.querySelector('.wu-light-title + .wu-light-sub');
    expect(sub?.textContent).toBe('People move in, and you choose an open AI model to decide for any of them.');
    expect(document.body.textContent).toContain('An open model makes it with your Nebius key: at most $1.43, and you see what it really spent.');
    document.body.replaceChildren();
    serve(keyed({ left_usd: '0.12' }));
    await mount();
    expect(document.body.textContent).toContain('An open model makes it with your Nebius key: at most the $0.12 left for AI models here, and you see what it really spent.');
    // A guest's page, or any server's budget: the line keeps its words, and the line under the title stands as well.
    document.body.replaceChildren();
    serve(keyed({ own_key: false }));
    await mount();
    expect(document.querySelector('.wu-light-sub')?.textContent).toBe('People move in, and you choose an open AI model to decide for any of them.');
    expect(document.body.textContent).toContain('An open model makes it from your words: at most $1.43, and you see what it really spent.');
    expect(document.body.textContent).not.toContain('your Nebius key');
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A harbour at night');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      const text = document.body.textContent!;
      expect(reads.offerReads()).toBe(2);
      expect(text).toContain('Making a world from your words can cost up to $0.04 a step, more than the $0.0085 left for AI models here. You can still start from these:');
      expect(text).not.toContain('Something went wrong');
      expect(document.querySelector('.wu-light-field')).toBeNull();
      expect(document.querySelectorAll('.wu-film-card').length).toBeGreaterThan(0);
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet town');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      const text = document.body.textContent!;
      expect(text).toContain('Making stopped part way: its next step could cost up to $0.04, more than the $0.0085 left for AI models here. No world was made, and it spent $0.0058.');
      // In place of the spent budget's words and what was spent, and with no price the offer read before it can no longer hold.
      expect(text).not.toContain('The budget for AI models here is spent.');
      expect(text).not.toContain('before it stopped');
      expect(text).not.toContain('An open model makes it');
      expect(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!.value).toBe('A quiet town');
      expect(reads.offerReads()).toBe(1);
      // The next word reads what is left again.
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet town by the sea');
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet town');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      expect(document.body.textContent).toContain('Spent $0.0003 of at most $0.05');
    });

    it('says the whole\u2019s most where the draft was funded with all of it: a control', async () => {
      answer([offerOf({ operation: { ...STEP } })], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        { state: 'drafting', elapsed_seconds: 1, poll_after_seconds: 30, accounting: { reported_usd: '0.0003' }, funded_usd: '1.42270000', operation: { ...STEP } },
      ]);
      await mount();
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet town');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      expect(document.body.textContent).toContain('Spent $0.0003 of at most $1.43');
    });

    it('still says a spent budget and what was spent where the refusal states no figures: a control', async () => {
      answer([offerOf({ operation: { ...STEP } })], [
        { state: 'choosing', elapsed_seconds: 0, poll_after_seconds: 0 },
        { state: 'refused', elapsed_seconds: 2, poll_after_seconds: null, accounting: { reported_usd: '0.02' }, refusal: { code: 'budget_exceeded', spending: { reason: 'not_granted', retry: 'never' } } },
      ]);
      await mount();
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A quiet town');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      const text = document.body.textContent!;
      expect(text).toContain('The budget for AI models here is spent.');
      expect(text).toContain('Spent $0.02 before it stopped.');
      expect(text).not.toContain('Making stopped part way');
    });
  });

  it('still says a spent budget is spent: a control for N31', async () => {
    serve(offerOf({ offered: false, code: 'budget_exceeded', operation: null }));
    await mount();
    expect(document.body.textContent).toContain('The budget for AI models here is spent. You can still start from these:');
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

  it('keeps the focus in the field when the cards to start from arrive after it', async () => {
    let release = () => {};
    cardsHeld.until = new Promise<void>((resolve) => { release = resolve; });
    serve(offerOf());
    await mount();
    const focusedFirst = document.activeElement === document.querySelector('.wu-light-field');
    const cardsFirst = document.body.textContent?.includes('Small town');
    cardsHeld.until = null;
    release();
    await settle();
    expect(focusedFirst).toBe(true);
    expect(cardsFirst).toBe(false);
    // The page drew again with the cards: the field it drew has the focus, the caret in it.
    expect(document.body.textContent).toContain('Small town');
    expect(document.activeElement).toBe(document.querySelector('.wu-light-field'));
  });

  it('draws a served card\'s picture where the release captured one for what is served now', async () => {
    const offer = offerOf();
    vi.stubGlobal('fetch', vi.fn(async (address: string) => {
      const body = address === '/card-pictures/card-pictures.v1.json'
        ? { profile: 'exulanica.card-pictures/v1', entries: [{ card: 'recipe:town', reference: { values: {} }, picture: 'recipe-town.jpg' }], held: [] }
        : address.endsWith('/worlds/drafts') ? offer : { state: 'making', elapsed_seconds: 1, poll_after_seconds: 3 };
      return { ok: true, status: 200, json: async () => body };
    }));
    await mount();
    await settle();
    const card = document.querySelector<HTMLElement>('.wu-film-card[data-key="recipe:town"]')!;
    expect(card.dataset['picture']).toBe('served');
    expect(card.querySelector<HTMLElement>('.wu-film-picture')!.style.backgroundImage).toContain('/card-pictures/recipe-town.jpg');
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
    const live = (): Element => document.querySelector('.wu-light-steps [aria-current="step"]')!;
    type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A harbour');
    const card = document.querySelector<HTMLButtonElement>('.wu-film-card[data-key="recipe:town"]')!;
    card.click();
    // At once, the start not yet answered: frame 21, its head, and its one live step timed from the press.
    expect(document.querySelector('.wu-light-quote')!.textContent).toBe('Small town');
    expect(document.querySelector('.wu-light-label')!.textContent).toBe('Creating your world');
    expect(live().querySelector('.wu-step-words')!.textContent).toBe('Building it');
    expect(live().querySelector('.wu-step-time')!.textContent).toBe('0 s');
    expect(document.body.textContent).toContain('You can leave this page. It carries on, and it waits in Your worlds.');
    now += 7_400;
    vi.advanceTimersByTime(1_000);
    expect(live().querySelector('.wu-step-time')!.textContent).toBe('7 s');
    // No card, field or Create is left to press; Enter, and the pressed card again, start nothing.
    expect(document.querySelector('.wu-film-card, .wu-light-field, .wu-light-orb')).toBeNull();
    key(document.querySelector('section.wu-light')!, 'Enter');
    card.click();
    await settle();
    expect(made).toEqual(['town']);
    expect(starts).toEqual([]);
    // Refused: frame 20 again with the refusal said, every card pressable, and the step's clock stopped.
    answer!.reject(Object.assign(new Error('refused'), { code: 'world_draft_failed' }));
    await settle();
    expect(document.querySelector('.wu-light-steps')).toBeNull();
    expect(document.body.textContent).toContain('Something went wrong while making it, so nothing was made. Try again.');
    expect(vi.getTimerCount()).toBe(0);
    document.querySelector<HTMLButtonElement>('.wu-film-card[data-key="blank"]')!.click();
    await settle();
    expect(made).toEqual(['town', 'blank']);
    vi.restoreAllMocks();
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A harbour at night');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
    };

    it('stops and says the new figure when the price went up: a positive control', async () => {
      await pressedWith('1.6');
      expect(starts.map((one) => one.most)).toEqual(['1.4227']);
      expect(document.body.textContent).toContain('The price went up before it started. It can now spend at most $1.60.');
      // Create again starts at the new price.
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle();
      expect(starts.map((one) => one.most)).toEqual(['1.4227', '1.6']);
    });

    it('starts again at once with the new quote and says nothing of a price when it is the same', async () => {
      await pressedWith('1.4227');
      expect(starts.map((one) => [one.words, one.most])).toEqual([['A harbour at night', '1.4227'], ['A harbour at night', '1.4227']]);
      expect(starts[1]!.key).not.toBe(starts[0]!.key);
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A harbour at night');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      const said = document.body.textContent!;
      expect(said).toContain('The price can’t be read right now. Trying again.');
      expect(said).not.toContain('The price changed before it started.');
      expect(starts).toHaveLength(1);
      // Read again after the first backoff: the same price, so it starts at once and says nothing.
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
      type(document.querySelector<HTMLTextAreaElement>('.wu-light-field')!, 'A harbour at night');
      key(document.querySelector('.wu-light-field')!, 'Enter');
      await settle(); await settle();
      const line = [...document.querySelectorAll('p, div, span')].find((one) => one.children.length === 0 && one.textContent === 'The price can’t be read right now. Trying again.');
      expect(line).toBeDefined();
      expect(line!.getAttribute('data-tone')).toBeNull(); // The plain ink, not the refusal's.
      expect(document.body.textContent).not.toContain('The price changed before it started.');
      expect(starts).toHaveLength(1);
    });
  });
});

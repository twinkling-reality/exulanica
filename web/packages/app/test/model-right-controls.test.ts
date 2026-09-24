// @vitest-environment happy-dom
/**
 * The rights a grounded answer needs, given, seen and stopped inside the photo drawer.
 *
 * Every word a right is shown with is the server's: these tests serve offers whose words are
 * deliberately not the product's, so anything the drawer shows or sends back can only have come
 * from the response. The transport is scripted. What this proves is what the client sends and
 * shows; the server's own checks are tests/test_model_right_offers.py.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '@exulanica/graph-client';
import { mountPersonalIntake, createPersonalIntakeSession } from '../src/composition/personal-intake.js';
import { sha256, type ModelRightOffer, type ModelRightState } from '../src/personal-admission-api.js';
import {
  buildModelRightGrants,
  readOffers,
  standingControls,
  standingOf,
  standingText,
} from '../src/ui/model-right-controls.js';

vi.mock('../src/formation.js', () => ({ listBatches: async () => [], watchBatch: () => () => undefined }));
vi.mock('../src/source-media-api.js', () => ({ SourceMediaClient: class {
  async load() { return { catalog: new Map(), issues: [], dispose: () => undefined }; }
} }));

const HOST = 'https://models.fixture.test';
const offer = (role: string, models: string[], offeredWith: 'detect' | 'review' = 'detect'): ModelRightOffer =>
  Object.freeze({
    role, offered_with: offeredWith,
    label: `Fixture label for ${role}`, short: `Fixture ${role}`,
    notice: `Fixture notice for ${role}: only the server's words, sent back unchanged.`,
    stop: `Fixture stop sentence for ${role}.`, stop_action: `Fixture stop ${role}`,
    stop_confirm: `Fixture confirm ${role}`, destination: HOST,
    models: models.map((model_id) => ({ provider: 'fixture', role, model_id, revision: null })),
  });
const VISION = offer('vision', ['primary-vision', 'fallback-vision']);
const EMBEDDING = offer('embedding', ['only-embedding']);
const COMPOSER = offer('reasoning_cheap', ['primary-composer', 'fallback-composer']);
const OFFERS = [VISION, EMBEDDING, COMPOSER];

const right = (role: string, modelId: string, id: string, over: Partial<ModelRightState> = {}): ModelRightState => ({
  right_id: id, capture_id: 'capture', operation: 'model_processing',
  model: { provider: 'fixture', role, model_id: modelId, revision: null },
  destination: HOST, granted_at: '2026-09-23T10:00:00.000000Z', valid_until: '2099-01-01T00:00:00.000000Z',
  withdrawn: false, state: 'current', notice_current: true, ...over,
});
/** The fixture rights' term as the drawer shows it, on this machine's clock. */
const UNTIL = new Date('2099-01-01T00:00:00.000000Z').toLocaleString();
const allowed = (name: string) => `${name}: allowed until ${UNTIL}`;

describe('the rights controls, drawn from the server offers', () => {
  it('draws one unticked control per offer with the offer notice, and returns only what is ticked', () => {
    const grants = buildModelRightGrants('Fixture group');
    grants.show(OFFERS);
    const ticks = [...grants.root.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(ticks.map((tick) => tick.getAttribute('aria-label'))).toEqual(OFFERS.map((o) => o.label));
    expect(ticks.every((tick) => !tick.checked)).toBe(true);
    expect([...grants.root.querySelectorAll('.model-right-notice')].map((n) => n.textContent))
      .toEqual(OFFERS.map((o) => o.notice));
    expect(grants.chosen()).toEqual([]);
    ticks[2]!.checked = true;
    expect(grants.chosen()).toEqual([COMPOSER]);
    grants.reset();
    expect(grants.chosen()).toEqual([]);
    ticks[0]!.checked = true;
    grants.show(OFFERS);
    expect(grants.chosen()).toEqual([]);
    grants.show([]);
    expect(grants.root.hidden).toBe(true);
  });

  it('allows a role only when every model of its chain is covered at its destination', () => {
    expect(standingText(standingOf(VISION, []))).toBe('Fixture vision: not allowed');
    const both = [right('vision', 'primary-vision', 'r1'), right('vision', 'fallback-vision', 'r2')];
    expect(standingOf(VISION, both).standing).toBe('current');
    expect(standingText(standingOf(VISION, both))).toBe(allowed('Fixture vision'));
    const one = [both[0]!, right('vision', 'fallback-vision', 'r2', { state: 'ended', withdrawn: true })];
    expect(standingOf(VISION, one).standing).toBe('partial');
    expect(standingOf(VISION, one).current.map((r) => r.right_id)).toEqual(['r1']);
    const elsewhere = both.map((r) => ({ ...r, destination: 'https://elsewhere.test' }));
    expect(standingOf(VISION, elsewhere).standing).toBe('partial');
    const ended = both.map((r) => ({ ...r, state: 'ended' as const, withdrawn: true }));
    expect(standingText(standingOf(VISION, ended))).toBe('Fixture vision: stopped');
    // Ended by its term or its authority, not by the person: it was not stopped.
    const lapsed = both.map((r) => ({ ...r, state: 'ended' as const }));
    expect(standingText(standingOf(VISION, lapsed))).toBe('Fixture vision: no longer allowed');
    const unworded = [{ ...both[0]!, notice_current: false }, both[1]!];
    expect(standingText(standingOf(VISION, unworded)))
      .toBe(`${allowed('Fixture vision')}, without the wording shown here`);
    // Another role's rights say nothing about this one.
    expect(standingOf(EMBEDDING, both).standing).toBe('none');
  });

  it('states the term the server recorded: the first model of the chain whose rights run out ends the role', () => {
    const terms = [
      right('vision', 'primary-vision', 'r1', { valid_until: '2098-01-01T00:00:00.000000Z' }),
      right('vision', 'primary-vision', 'r3', { valid_until: '2099-01-01T00:00:00.000000Z' }),
      right('vision', 'fallback-vision', 'r2', { valid_until: '2097-06-01T00:00:00.000000Z' }),
    ];
    expect(standingOf(VISION, terms).until).toBe('2097-06-01T00:00:00.000000Z');
    expect(standingText(standingOf(VISION, terms)))
      .toBe(`Fixture vision: allowed until ${new Date('2097-06-01T00:00:00.000000Z').toLocaleString()}`);
    // The fallback's later grant carries the role to the primary's latest term.
    const renewed = [...terms, right('vision', 'fallback-vision', 'r4', { valid_until: '2099-06-01T00:00:00.000000Z' })];
    expect(standingOf(VISION, renewed).until).toBe('2099-01-01T00:00:00.000000Z');
    expect(standingOf(VISION, [terms[0]!]).until).toBeNull();
  });

  it('asks before stopping, in the offer words, and stops only on the confirmation', () => {
    const calls: string[] = [];
    const standing = standingOf(VISION, [right('vision', 'primary-vision', 'r1'), right('vision', 'fallback-vision', 'r2')]);
    const handlers = {
      locked: false,
      onAsk: () => calls.push('ask'), onStop: () => calls.push('stop'), onKeep: () => calls.push('keep'),
    };
    const asking = standingControls(standing, { ...handlers, confirming: false });
    const ask = asking.flatMap((node) => [...node.querySelectorAll('button')]).find((b) => b.textContent === VISION.stop_action)!;
    ask.click();
    const confirming = standingControls(standing, { ...handlers, confirming: true });
    const words = confirming.map((node) => node.textContent).join(' ');
    expect(words).toContain(VISION.stop);
    const buttons = confirming.flatMap((node) => [...node.querySelectorAll('button')]);
    buttons.find((b) => b.textContent === 'Keep allowing them')!.click();
    buttons.find((b) => b.textContent === VISION.stop_confirm)!.click();
    expect(calls).toEqual(['ask', 'keep', 'stop']);
    expect(standingControls(standingOf(VISION, []), { ...handlers, confirming: false })
      .flatMap((node) => [...node.querySelectorAll('button')])).toEqual([]);
  });

  it('keeps only whole offers, so nothing is drawn from a half read', () => {
    expect(readOffers(undefined)).toEqual([]);
    expect(readOffers([VISION, { ...VISION, notice: '' }, { ...VISION, offered_with: 'upload' },
      { ...VISION, models: [] }, null, 'vision'])).toEqual([VISION]);
  });
});

const CAPTURE = '11111111-1111-4111-8111-111111111111';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** One uploaded photograph in the drawer, a server that states OFFERS, and every POST recorded. */
function drawer(options: { rights?: ModelRightState[]; refuse?: string; offersAfterRefusal?: ModelRightOffer[] } = {}) {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const file = new File(['fixture JPEG bytes'], 'a.jpg');
  let rights = options.rights ?? [];
  let offers: ModelRightOffer[] = OFFERS;
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    if (path === '/personal-admission' && (init.method ?? 'GET') === 'GET') {
      return json({
        sources: [{
          capture_id: CAPTURE, sha256: await sha256(await file.arrayBuffer()), bytes: file.size,
          media_type: 'image/jpeg', authority: null, model_rights: rights,
        }],
        requests: [],
        model_right_offers: offers,
      });
    }
    if (init.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      posts.push({ path, body });
      const withdrawn = /^\/personal-admission\/model-rights\/([^/]+)\/withdraw$/.exec(path);
      if (withdrawn) {
        rights = rights.map((r) => r.right_id === withdrawn[1] ? { ...r, withdrawn: true, state: 'ended' } : r);
        return json({ right_id: withdrawn[1], state: 'ended', withdrawn: true });
      }
      if (path === '/personal-admission') {
        if (options.refuse !== undefined) {
          if (options.offersAfterRefusal !== undefined) offers = options.offersAfterRefusal;
          return json({ detail: options.refuse }, 409);
        }
        return json({ request_id: body['request_id'], batch_id: 'admitted', queued_job_id: 'job',
          receipts: [{ capture_id: CAPTURE, authorization_id: 'auth', screening_id: 'screen', eligibility_state: 'blocked' }] }, 202);
      }
      return json({});
    }
    if (path.startsWith('/person-regions/')) return json({ capture_id: CAPTURE, review_state: 'screened', regions: [] });
    throw new Error(`Unexpected fixture request: ${path}`);
  });
  const snapshot = () => adaptSnapshot({ state_version: 1, entities: [], occurrences: [], proposals: [],
    scene_groups: [], reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
    review_sources: [{
      kind: 'admitted_capture' as const, capture_id: CAPTURE, evidence_span_id: 'span-0',
      captured_at: null, media_type: 'image/jpeg', state: 'unavailable_asset' as const,
      reason: 'Fixture viewer unavailable', evidence_path: null, content_sha256: null,
      person_review_state: 'screened' as const, person_regions: [],
    }] });
  const mounted = mountPersonalIntake({
    credentials: { baseUrl: 'https://fixture.test', token: 'fixture-token', fetch },
    session: createPersonalIntakeSession(), snapshot: snapshot(), media: undefined,
    reloadSnapshot: async () => snapshot(), refreshWorld: vi.fn(async () => undefined),
    storage: window.sessionStorage,
  });
  return { posts, mounted };
}

const settle = async (root: HTMLElement) =>
  vi.waitFor(() => expect(root.querySelector('fieldset')!.disabled).toBe(false));
const field = (root: HTMLElement, label: string) =>
  root.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
const button = (root: HTMLElement, text: string) =>
  [...root.querySelectorAll('button')].find((b) => b.textContent === text)!;
/** The drawer's own status line: the one directly under its root, not a card's or a notice's. */
const said = (root: HTMLElement) =>
  [...root.children].find((node) => node.getAttribute('role') === 'status')!.textContent ?? '';

async function readyToDetect(root: HTMLElement): Promise<void> {
  const include = field(root, 'Include photograph 1 in this admission');
  if (!include.checked) { include.checked = true; include.dispatchEvent(new Event('change')); }
  field(root, 'Purpose of this use').value = 'Fixture place';
  field(root, 'Your account authority basis').value = 'Fixture operator permission';
  field(root, 'Authority valid until').value = '2099-01-01T12:00';
}

afterEach(() => {
  document.body.replaceChildren();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

describe('giving, seeing and stopping the rights an answer needs, in the drawer', () => {
  it('offers each hosted right at detection, unticked, and sends exactly the ticked ones with the server words', async () => {
    const { posts, mounted } = drawer();
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    for (const each of OFFERS) {
      expect(field(mounted.root, each.label).checked).toBe(false);
      expect(mounted.root.textContent).toContain(each.notice);
    }
    // The control: authorizing detection with nothing ticked grants nothing.
    await readyToDetect(mounted.root);
    button(mounted.root, 'Authorize personal admission and request detection').click();
    await settle(mounted.root);
    const untouched = posts.at(-1)!.body;
    expect(untouched['operation']).toBe('detect');
    expect(untouched['model_rights']).toBeUndefined();

    await readyToDetect(mounted.root);
    for (const each of [VISION, COMPOSER]) {
      const tick = field(mounted.root, each.label);
      tick.checked = true;
      tick.dispatchEvent(new Event('change'));
    }
    expect(mounted.root.textContent).toContain('Allowed until');
    button(mounted.root, 'Authorize personal admission and request detection').click();
    await settle(mounted.root);
    const ticked = posts.at(-1)!.body;
    const until = new Date('2099-01-01T12:00').toISOString();
    expect(ticked['model_rights']).toEqual([
      { role: 'vision', valid_until: until, notice: VISION.notice },
      { role: 'reasoning_cheap', valid_until: until, notice: COMPOSER.notice },
    ]);
    // Recorded, so the ticks are taken back: a later admission carries only what is ticked for it.
    for (const each of OFFERS) expect(field(mounted.root, each.label).checked).toBe(false);
    mounted.dispose();
  });

  it('shows each right over a photo and stops a role by withdrawing every current right it holds', async () => {
    const rights = [
      right('vision', 'primary-vision', 'v1'), right('vision', 'fallback-vision', 'v2'),
      right('embedding', 'only-embedding', 'e1'),
      right('reasoning_cheap', 'primary-composer', 'c1'), right('reasoning_cheap', 'fallback-composer', 'c2'),
    ];
    const { posts, mounted } = drawer({ rights });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const row = () => mounted.root.querySelector('.intake-original-rights')!;
    const lines = () => [...row().querySelectorAll('.photo-right-state')].map((n) => n.textContent);
    expect(lines()).toEqual([
      allowed('Fixture vision'), allowed('Fixture embedding'), allowed('Fixture reasoning_cheap'),
    ]);

    button(mounted.root, VISION.stop_action).click();
    await settle(mounted.root);
    // A stop is final, so the person reads what it does, in the server's words, before it is sent.
    expect(row().textContent).toContain(VISION.stop);
    expect(posts.some((p) => p.path.endsWith('/withdraw'))).toBe(false);

    button(mounted.root, VISION.stop_confirm).click();
    await settle(mounted.root);
    // Both models of the chain, and nothing of the other roles.
    expect(posts.filter((p) => p.path.endsWith('/withdraw')).map((p) => p.path)).toEqual([
      '/personal-admission/model-rights/v1/withdraw', '/personal-admission/model-rights/v2/withdraw',
    ]);
    expect(lines()).toEqual([
      'Fixture vision: stopped', allowed('Fixture embedding'), allowed('Fixture reasoning_cheap'),
    ]);
    expect(button(mounted.root, VISION.stop_action)).toBeUndefined();
    expect(said(mounted.root)).toBe('Fixture vision: stopped for that photo.');
    mounted.dispose();
  });

  it('lists no line for a role never given over a photo', async () => {
    const { mounted } = drawer({ rights: [right('embedding', 'only-embedding', 'e1')] });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const lines = [...mounted.root.querySelectorAll('.intake-original-rights .photo-right-state')]
      .map((n) => n.textContent);
    expect(lines).toEqual([allowed('Fixture embedding')]);
    mounted.dispose();
  });

  it('says a refusal in words with its reason, and nothing is recorded', async () => {
    const { posts, mounted } = drawer({
      refuse: "the vision model right is granted against this server's own notice",
    });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    await readyToDetect(mounted.root);
    const tick = field(mounted.root, VISION.label);
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));
    button(mounted.root, 'Authorize personal admission and request detection').click();
    await settle(mounted.root);
    expect(posts.filter((p) => p.path === '/personal-admission')).toHaveLength(1);
    expect(said(mounted.root)).toBe("Nothing was recorded. The server said: the vision model right is granted against this server's own notice");
    expect(said(mounted.root)).not.toContain('http_409');
    mounted.dispose();
  });

  it('says when the words changed while the person was reading, and takes the tick back', async () => {
    const reworded = OFFERS.map((each) => each.role === 'vision'
      ? { ...each, notice: `${each.notice} Reworded.` } : each);
    const { mounted } = drawer({
      refuse: "the vision model right is granted against this server's own notice",
      offersAfterRefusal: reworded,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    await readyToDetect(mounted.root);
    const tick = field(mounted.root, VISION.label);
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));
    button(mounted.root, 'Authorize personal admission and request detection').click();
    await settle(mounted.root);
    expect(said(mounted.root))
      .toContain('The wording for what you allowed changed while you were reading it');
    expect(mounted.root.textContent).toContain(`${VISION.notice} Reworded.`);
    expect(field(mounted.root, VISION.label).checked).toBe(false);
    mounted.dispose();
  });
});

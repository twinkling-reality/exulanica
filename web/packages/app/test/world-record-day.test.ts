// @vitest-environment happy-dom
// Teo's day as r06 with r11's fields (tools/previews/world-workspace/character-page.ts): who the character is at the
// left, What Teo did as a path of moment cards at the right, newest first, the chosen card with "[Enter] See the
// decision"; N's two light fields in place with their counts, Save and Cancel, and the saved note for four seconds;
// the keys each only where they work; the 1440 sizes. The page only draws and says what was asked through `act`.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';

type State = Record<string, unknown>;
interface CharacterPage { draw(state: State): void; hide(hidden: boolean): void; close(): void }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const module = async (): Promise<{ openCharacterPage(host: HTMLElement, act: (action: string, value?: unknown) => void): CharacterPage }> =>
  import('../../../../tools/previews/world-workspace/' + 'character-page.ts') as Promise<{ openCharacterPage(host: HTMLElement, act: (action: string, value?: unknown) => void): CharacterPage }>;

const ABOUT = 'A retired fisherman who walks the quay every morning and talks to anyone who will listen.';
const teo = { title: 'Teo', start: 'Teo', within: 'Teo', named: true };
const resident = { title: 'Resident', start: 'The resident', within: 'the resident', named: false };
const NEMOTRON = 'Nemotron 3 Nano 30B';

/** What Teo did as r06 draws it: the newest first, a line heard second, the chosen meeting third. */
function rows() {
  return [
    { time: '07:10 · Day 1', what: 'Said to Marco: “Sardines, mostly. Come down early tomorrow.”', sub: `${NEMOTRON} · 7 choices`, decision: true,
      moment: true, title: 'Teo spoke to Marco', said: '“Sardines, mostly. Come down early tomorrow.”', picture: '/pictures/spoke.png', model: NEMOTRON, choices: 7 },
    { time: '07:09 · Day 1', what: 'Heard Marco: “Did they bring in anything good?”', sub: '', decision: false, heard: true,
      title: 'Marco asked Teo', said: 'Marco: “Did they bring in anything good?”', picture: null, model: null, decider: 'person' },
    { time: '06:52 · Day 1', what: 'Said to Ines: “Morning, Ines. The boats are out early.”', sub: `${NEMOTRON} · 9 choices`, decision: true,
      moment: true, title: 'Teo met Ines at the bench', said: '“Morning, Ines. The boats are out early.”', picture: '/pictures/met.png', model: NEMOTRON, choices: 9 },
    { time: '06:31 · Day 1', what: 'Went to the lower pools', sub: `${NEMOTRON} · 6 choices`, decision: true, moment: true, title: 'Teo went to the lower pools', model: NEMOTRON, choices: 6 },
    { time: '06:00 · Day 1', what: 'Left home', sub: 'Routine', decision: false, moment: true, title: 'Teo left home', model: null },
  ];
}

/** Teo with a model and a personality, nothing open over the day. */
function teoState(extra: State = {}): State {
  return {
    who: teo, sub: 'Resident · Terraces on the bay', assignable: true,
    model: { name: NEMOTRON, price: { input: '0.06', output: '0.24' } }, connected: true, runLine: null,
    run: { open: false, big: '10 minutes · at most $0.05', small: "Teo's model decides. Everyone else keeps their routine.", busy: false, refusal: null },
    did: rows(), didFocus: 2, canAsk: true, ask: null, lastRun: 'Last run 06:00 to 07:15 · 12 decisions · spent $0.0042',
    personality: { character: { name: 'Teo', about: ABOUT }, shown: true }, editing: null, choosing: null, canCompare: true, compare: null,
    portrait: '/portraits/teo.png', doing: 'Waiting by the bench', decides: `${NEMOTRON} decides for Teo`,
    ...extra,
  };
}

/** A resident the society made, on its routine, whose owner has written no personality. */
function residentState(extra: State = {}): State {
  return {
    who: resident, sub: 'Terraces on the bay', assignable: false, model: null, connected: true, runLine: 'The resident follows a routine.',
    run: { open: false, big: '10 minutes · at most $0.05', small: '', busy: false, refusal: null },
    did: [], didFocus: null, canAsk: false, ask: null, lastRun: null,
    personality: { character: null, shown: true }, editing: null, choosing: null, canCompare: false, compare: null,
    decides: 'The resident follows a routine',
    ...extra,
  };
}

async function open(width = 1920, height = 1080) {
  const root = document.createElement('div');
  // The page lays itself out for the window it is in: r06's own 1920 by 1080, or 1440 by 900.
  Object.defineProperty(root, 'clientWidth', { value: width });
  Object.defineProperty(root, 'clientHeight', { value: height });
  document.body.append(root);
  const act = vi.fn();
  const page = (await module()).openCharacterPage(root, act);
  return { root, act, page };
}

const all = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)].map((node) => node.textContent);
const one = (root: ParentNode, selector: string) => root.querySelector(selector)?.textContent ?? null;
const keys = (root: HTMLElement) => all(root, '.wu-hr-keys .wu-hr-key');
const keyNamed = (root: HTMLElement, word: string) => [...root.querySelectorAll<HTMLElement>('.wu-hr-keys .wu-hr-key')].find((node) => node.querySelector('.wu-hr-key-word')?.textContent === word)!;
const items = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('.wu-day-item')];

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("Teo's day", () => {
  it('shows who Teo is at the left: portrait, kind and world, name, what Teo is doing, the personality and who decides', async () => {
    const { root, page } = await open();
    page.draw(teoState());
    const dialog = root.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.classList.contains('wu-record')).toBe(true);
    expect(dialog.classList.contains('wu-record-day')).toBe(true);
    expect(dialog.getAttribute('aria-label')).toBe('Teo');
    // It opens with the focus on the name, so a reader announces whose day it is (L18).
    expect(document.activeElement?.textContent).toBe('Teo');
    const who = root.querySelector('.wu-day-who') as HTMLElement;
    expect([who.style.left, who.style.top, who.style.width]).toEqual(['120px', '84px', '600px']);
    expect(who.querySelector('.wu-day-face img')?.getAttribute('src')).toBe('/portraits/teo.png');
    expect((who.querySelector('.wu-day-face') as HTMLElement).style.width).toBe('112px');
    expect(one(who, '.wu-hr-over')).toBe('Resident · Terraces on the bay');
    expect(one(who, '.wu-day-name')).toBe('Teo');
    expect(one(who, '.wu-day-doing')).toBe('Waiting by the bench');
    expect(one(who, '.wu-day-persona')).toBe(`“${ABOUT}”`);
    expect(one(who, '.wu-day-by')).toBe('Written by you');
    // Who decides with History's Current tag; the price, the last run and what [R] would start in the small print.
    expect(one(who, '.wu-day-decides')).toBe(`${NEMOTRON} decides for TeoCurrent`);
    expect(one(who, '.wu-day-decides .wu-hr-tag')).toBe('Current');
    expect(all(who, '.wu-day-small .wu-day-line')).toEqual([
      '$0.06 in · $0.24 out per million tokens', 'Last run 06:00 to 07:15 · 12 decisions · spent $0.0042',
      '10 minutes · at most $0.05', "Teo's model decides. Everyone else keeps their routine.",
    ]);
  });

  it('shows what Run would start, its length and most it may spend, before R starts it', async () => {
    const { root, act, page } = await open();
    const run = { open: false, big: '10 minutes · at most $0.05', small: "Teo's model decides. Everyone else keeps their routine.", busy: false, refusal: null };
    page.draw(teoState({ lastRun: null, run }));
    expect(all(root, '.wu-day-small .wu-day-line')).toEqual(['$0.06 in · $0.24 out per million tokens', '10 minutes · at most $0.05', "Teo's model decides. Everyone else keeps their routine."]);
    // The figures wrap only between their parts (J9).
    expect(all(root, '.wu-day-small .wu-nowrap')).toEqual(['10 minutes', 'at most $0.05']);
    keyNamed(root, 'Run').click();
    expect(act).toHaveBeenLastCalledWith('run');
    // While it starts, and when a refusal asks to press Run again, the limits it names stay on screen.
    page.draw(teoState({ lastRun: null, run: { ...run, busy: true, refusal: 'That run already started with other limits. Press Run again.' } }));
    expect(all(root, '.wu-day-small .wu-day-line')).toContain('10 minutes · at most $0.05');
    expect(one(root, '.wu-day-who .wu-day-refused')).toBe('That run already started with other limits. Press Run again.');
    // Once it is on, the running line stands in its place; where no run is offered, there are no limits to show.
    page.draw(teoState({ lastRun: null, run: { ...run, open: true, big: '9:13 left · $0.0011 of $0.05' }, running: "Teo's model is deciding · 9:13 left" }));
    expect(all(root, '.wu-day-small .wu-day-line')).toEqual(['$0.06 in · $0.24 out per million tokens', "Teo's model is deciding · 9:13 left"]);
    page.draw(teoState({ lastRun: null, run, connected: false }));
    expect(all(root, '.wu-day-small .wu-day-line')).toEqual(['$0.06 in · $0.24 out per million tokens']);
    expect(keys(root)).not.toContain('RRun');
  });

  it('keeps a long line to two lines on its card, the whole line still in its text', async () => {
    const { root, page } = await open(1440, 900);
    const line = `Said to Marco: “${'The boats were out before the light and came back heavy, so come down early. '.repeat(3).trim()}”`;
    expect(line.length).toBeGreaterThan(200);
    page.draw(teoState({ did: [{ time: '07:10 · Day 1', what: line, sub: `${NEMOTRON} · 7 choices`, decision: true }, ...rows().slice(1)], didFocus: 0 }));
    expect(one(root, '.wu-day-item .wu-day-title')).toBe(line);
    // The stylesheet clamps a card's title and its line said to two lines with an ellipsis (the test runner loads
    // stylesheets empty, so the rule is read from the file).
    const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../tools/previews/world-workspace/world-ui-record-day.css'), 'utf8');
    const rule = css.match(/\.wu-record-day \.wu-day-title, \.wu-record-day \.wu-day-said \{([^}]*)\}/)?.[1] ?? '';
    expect(rule).toMatch(/-webkit-line-clamp: 2;/);
    expect(rule).toMatch(/line-clamp: 2;/);
    expect(rule).toMatch(/display: -webkit-box;/);
    expect(rule).toMatch(/overflow: hidden;/);
    expect(rule).toMatch(/text-overflow: ellipsis;/);
  });

  it('shows the name as written where a personality holds only a name', async () => {
    const { root, page } = await open();
    page.draw(teoState({ personality: { character: { name: 'Puddle', about: null }, shown: true } }));
    expect(one(root, '.wu-day-persona')).toBe('“Puddle”');
    expect(one(root, '.wu-day-by')).toBe('Written by you');
    expect(root.querySelector('.wu-day-none')).toBeNull();
    page.draw(teoState({ personality: { character: { name: ' ', about: '' }, shown: true } }));
    expect(one(root, '.wu-day-none')).toBe('No personality written yet.');
  });

  it('fades a picture in once: drawn again, a picture already shown starts shown and one still coming still fades', async () => {
    const { root, page } = await open();
    // This case's own addresses, so no other case has shown them.
    const state = (doing: string) => teoState({ doing, did: rows().map((row) => (row.picture ? { ...row, picture: `${row.picture}?once` } : row)) });
    const loaded = () => [...root.querySelectorAll('.wu-hr-pic img')].map((image) => image.getAttribute('data-loaded'));
    page.draw(state('Waiting by the bench'));
    const before = root.querySelector('.wu-hr-pic img');
    expect(loaded()).toEqual([null, null]);
    root.querySelector('.wu-hr-pic img')!.dispatchEvent(new Event('load'));
    expect(loaded()).toEqual(['true', null]);
    // The page draws again with something else changed, as it does each second during a run: new pictures, the shown
    // one already shown.
    page.draw(state('Walking to the quay'));
    expect(root.querySelector('.wu-hr-pic img')).not.toBe(before);
    expect(loaded()).toEqual(['true', null]);
  });

  it('draws What Teo did newest first on the path at x 880, the chosen card filled and offering its decision', async () => {
    const { root, act, page } = await open();
    page.draw(teoState());
    expect(one(root, '.wu-day-over')).toBe('What Teo did');
    const cards = items(root);
    expect(cards.map((card) => card.querySelector('.wu-day-title')?.textContent)).toEqual([
      'Teo spoke to Marco', 'Marco asked Teo', 'Teo met Ines at the bench', 'Teo went to the lower pools', 'Teo left home',
    ]);
    // 160px apart from 150, at x 920, each a 208 by 118 picture with its words beside it; a line heard is no moment of
    // Teo's, so it draws no tile and its words keep the same column (R5e).
    expect(cards.map((card) => [card.style.left, card.style.top])).toEqual([['920px', '150px'], ['920px', '310px'], ['920px', '470px'], ['920px', '630px'], ['920px', '790px']]);
    expect(cards.map((card) => (card.firstElementChild as HTMLElement).style.width)).toEqual(['208px', '208px', '208px', '208px', '208px']);
    expect(cards.map((card) => (card.firstElementChild as HTMLElement).className)).toEqual(['wu-hr-pic', 'wu-day-untiled', 'wu-hr-pic', 'wu-hr-pic', 'wu-hr-pic']);
    const picture = cards[0]!.querySelector('.wu-hr-pic') as HTMLElement;
    expect([picture.style.width, picture.style.height]).toEqual(['208px', '118px']);
    expect(all(root, '.wu-day-item .wu-hr-time')).toEqual(['07:10 · Day 1', '07:09 · Day 1', '06:52 · Day 1', '06:31 · Day 1', '06:00 · Day 1']);
    // The line said in curly quotes, a line said to Teo with its speaker first; the who line under it.
    expect(all(root, '.wu-day-item .wu-hr-said')).toEqual(['“Sardines, mostly. Come down early tomorrow.”', 'Marco: “Did they bring in anything good?”', '“Morning, Ines. The boats are out early.”']);
    expect(all(root, '.wu-day-decided')).toEqual([`By ${NEMOTRON} · 7 choices`, 'By a person playing', `By ${NEMOTRON} · 9 choices`, `By ${NEMOTRON} · 6 choices`, 'Routine']);
    // A model's name never breaks.
    expect(all(root, '.wu-day-item .wu-hr-model')).toEqual([NEMOTRON, NEMOTRON, NEMOTRON]);
    // A picture where one exists, the quiet tile where a moment's is still to come (no words in it).
    expect(cards.map((card) => card.querySelector('.wu-hr-pic img')?.getAttribute('src') ?? null)).toEqual(['/pictures/spoke.png', null, '/pictures/met.png', null, null]);
    expect(all(root, '.wu-hr-pic')).toEqual(['', '', '', '']);
    // The chosen card rises; only it says "[Enter] See the decision".
    expect(cards.map((card) => card.getAttribute('aria-current'))).toEqual([null, null, 'true', null, null]);
    expect(all(root, '.wu-day-see')).toEqual(['EnterSee the decision']);
    expect(cards[2]!.querySelector('.wu-day-see')).not.toBeNull();
    // The path from the newest card's top to the oldest dot, a hollow dot per card, the chosen one filled.
    expect(root.querySelector('.wu-day-path .line')?.getAttribute('d')).toBe('M 880 150 L 880 811');
    const dots = [...root.querySelectorAll('.wu-day-path .dot')];
    expect(dots.map((dot) => [dot.getAttribute('cx'), dot.getAttribute('cy')])).toEqual([['880', '171'], ['880', '331'], ['880', '491'], ['880', '651'], ['880', '811']]);
    expect(dots.map((dot) => (dot as SVGElement).dataset['chosen'])).toEqual(['false', 'false', 'true', 'false', 'false']);
    // Pressing a card chooses it; a line heard is never chosen; See the decision opens that card's decision.
    cards[0]!.click();
    expect(act).toHaveBeenLastCalledWith('row', 0);
    act.mockClear();
    cards[1]!.click();
    expect(act).not.toHaveBeenCalled();
    (root.querySelector('.wu-day-see') as HTMLElement).click();
    expect(act.mock.calls).toEqual([['inspect', 2]]);
  });

  it('draws rows that made no moment by their own words with no picture tile, their words in the pictured column (R5e)', async () => {
    const { root, page } = await open();
    const today = rows().map(({ time, what, sub, decision, heard }) => ({ time, what, sub, decision, ...(heard ? { heard } : {}) }));
    const plain = teoState({ did: today });
    for (const field of ['portrait', 'doing', 'decides']) delete plain[field];
    page.draw(plain);
    expect(all(root, '.wu-day-title')).toEqual(today.map((row) => row.what));
    expect(all(root, '.wu-day-decided')).toEqual([`${NEMOTRON} · 7 choices`, `${NEMOTRON} · 9 choices`, `${NEMOTRON} · 6 choices`, 'Routine']);
    expect(root.querySelector('.wu-day-item .wu-hr-said')).toBeNull();
    expect(root.querySelector('.wu-day-item img')).toBeNull();
    expect(root.querySelector('.wu-day-item .wu-hr-pic')).toBeNull();
    expect([...root.querySelectorAll<HTMLElement>('.wu-day-item > .wu-day-untiled')].map((spacer) => spacer.style.width)).toEqual(['208px', '208px', '208px', '208px', '208px']);
    // No portrait yet: the first letter on the quiet orb; who decides is the model's own name with its tag.
    expect(one(root, '.wu-day-face')).toBe('T');
    expect(root.querySelector('.wu-day-doing')).toBeNull();
    expect(one(root, '.wu-day-decides')).toBe(`${NEMOTRON}Current`);
  });

  it("says a routine row made in a run lies between the person's model's choices, and Routine elsewhere (P2)", async () => {
    const { root, page } = await open();
    const between = `Routine, between ${NEMOTRON}'s choices`;
    page.draw(teoState({ did: rows().map((row) => (row.model === null && row.sub === 'Routine' ? { ...row, sub: between } : row)) }));
    expect(all(root, '.wu-day-decided').slice(-1)).toEqual([between]);
    page.draw(teoState());
    expect(all(root, '.wu-day-decided').slice(-1)).toEqual(['Routine']);
  });

  it("says a row whose model's choice was not taken was the routine's, with the model and why, never By (U3)", async () => {
    const { root, page } = await open();
    page.draw(teoState({ did: [
      { time: '07:12 · Day 1', what: 'Walked to the quay', sub: '', decision: true, model: NEMOTRON, choices: 9, unanswered: 'none' },
      { time: '07:11 · Day 1', what: 'Waited by the bench', sub: '', decision: true, model: NEMOTRON, choices: 9, unanswered: 'late' },
      { time: '07:10 · Day 1', what: 'Went to the lower pools', sub: '', decision: true, model: NEMOTRON, choices: 6 },
    ], didFocus: 0 }));
    expect(all(root, '.wu-day-decided')).toEqual([`Routine · no usable answer from ${NEMOTRON}`, `Routine · ${NEMOTRON} chose too late`, `By ${NEMOTRON} · 6 choices`]);
  });

  it('draws the same choice folded into one row: its span of minutes and its decisions counted (R5e)', async () => {
    const { root, page } = await open();
    page.draw(teoState({ did: [
      { time: 'Minute 10 to minute 33', what: 'Waited', sub: '', decision: true, model: NEMOTRON, choices: 8, decisions: 23 },
      { time: 'Minute 9', what: 'Waited', sub: '', decision: true, model: NEMOTRON, choices: 8, decisions: 1 },
    ], didFocus: 0 }));
    expect(all(root, '.wu-day-item .wu-hr-time')).toEqual(['Minute 10 to minute 33', 'Minute 9']);
    // The folded row counts its decisions; a single decision keeps its choices.
    expect(all(root, '.wu-day-decided')).toEqual([`By ${NEMOTRON} · 23 decisions`, `By ${NEMOTRON} · 8 choices`]);
  });

  it('shows a routine character with no personality written: the line, [N] Personality, and nothing it cannot do', async () => {
    const { root, page } = await open();
    page.draw(residentState());
    expect(root.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe('Resident');
    expect(one(root, '.wu-day-face')).toBe('R');
    expect(root.querySelector('.wu-day-face img')).toBeNull();
    expect(one(root, '.wu-day-name')).toBe('Resident');
    expect(one(root, '.wu-day-none')).toBe('No personality written yet.');
    expect(root.querySelector('.wu-day-persona')).toBeNull();
    expect(root.querySelector('.wu-day-by')).toBeNull();
    expect(one(root, '.wu-day-decides')).toBe('The resident follows a routine');
    expect(root.querySelector('.wu-day-decides .wu-hr-tag')).toBeNull();
    expect(root.querySelector('.wu-day-small')).toBeNull();
    expect(one(root, '.wu-day-note')).toBe('The resident has not done anything yet.');
    expect(root.querySelector('.wu-day-path .line')).toBeNull();
    expect(keys(root)).toEqual(['NPersonality', 'EscBack']);
    // While the rows are read, it says so; without the host's words for who decides, the Run section's line.
    const plain = residentState({ did: null });
    delete plain['decides'];
    page.draw(plain);
    expect(one(root, '.wu-day-note')).toBe("Reading the resident's record…");
    expect(one(root, '.wu-day-decides')).toBe('The resident follows a routine.');
    // A character no one placed has no personality and no [N].
    page.draw(residentState({ personality: null }));
    expect(root.querySelector('.wu-day-none')).toBeNull();
    expect(keys(root)).toEqual(['EscBack']);
  });
});

describe("Teo's personality", () => {
  it('turns the left column into the two light fields in place, the day dimmed, with Save and Cancel', async () => {
    const { root, act, page } = await open();
    page.draw(teoState());
    page.draw(teoState({ editing: { session: 's1', refusal: null, busy: false } }));
    const dialog = root.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.hasAttribute('data-editing')).toBe(true);
    const editor = root.querySelector('.wu-day-editor') as HTMLElement;
    expect(one(editor, '.wu-hr-over')).toBe('Resident · Terraces on the bay');
    expect(editor.querySelector('.wu-day-name')).toBeNull();
    expect(all(editor, '.wu-day-label')).toEqual(['Name3 of 40', 'Personality89 of 300']);
    const name = editor.querySelector('input.wu-day-name-field') as HTMLInputElement;
    const about = editor.querySelector('textarea.wu-day-about-field') as HTMLTextAreaElement;
    expect([name.value, about.value]).toEqual(['Teo', ABOUT]);
    expect(one(editor, '.wu-day-reads')).toBe("Teo's model reads this each time it decides.");
    // The day at the right stays where it was, dimmed, and answers nothing.
    expect(root.querySelector('.wu-day-did')?.hasAttribute('data-dim')).toBe(true);
    expect(items(root)).toHaveLength(5);
    expect(root.querySelector('.wu-day-see')).toBeNull();
    expect(keys(root)).toEqual(['EnterSave', 'EscCancel']);
    await Promise.resolve();
    expect(document.activeElement).toBe(about);
    // Typing keeps its place through every draw; the count follows, and past the limit it turns.
    about.value = 'A worried yellow duck.';
    about.dispatchEvent(new Event('input'));
    expect(act).toHaveBeenLastCalledWith('draft', { name: 'Teo', about: 'A worried yellow duck.' });
    expect(all(editor, '.wu-day-count')).toEqual(['3 of 40', '22 of 300']);
    name.value = 'x'.repeat(41);
    name.dispatchEvent(new Event('input'));
    expect(editor.querySelector('.wu-day-count')?.classList.contains('wu-over')).toBe(true);
    page.draw(teoState({ editing: { session: 's1', refusal: 'Too long: a name has at most 40 characters, a personality at most 300.', busy: false } }));
    expect(root.querySelector('textarea.wu-day-about-field')).toBe(about);
    expect(about.value).toBe('A worried yellow duck.');
    expect(one(root, '.wu-day-editor .wu-day-refused')).toBe('Too long: a name has at most 40 characters, a personality at most 300.');
    page.draw(teoState({ editing: { session: 's1', refusal: null, busy: true } }));
    expect(keyNamed(root, 'Save').hasAttribute('disabled')).toBe(true);
    expect((root.querySelector('.wu-day-editor .wu-day-refused') as HTMLElement).hidden).toBe(true);
    page.draw(teoState({ editing: { session: 's1', refusal: null, busy: false } }));
    act.mockClear();
    keyNamed(root, 'Save').click();
    keyNamed(root, 'Cancel').click();
    expect(act.mock.calls).toEqual([['save'], ['back']]);
  });

  it('says it was saved in the who column for four seconds, and nothing after a cancel or a refusal', async () => {
    vi.useFakeTimers();
    const { root, page } = await open();
    const saved = { character: { name: 'Teo', about: 'A worried yellow duck.' }, shown: true };
    page.draw(teoState({ editing: { session: 's1', refusal: null, busy: false } }));
    page.draw(teoState({ editing: { session: 's1', refusal: null, busy: true } }));
    page.draw(teoState({ personality: saved }));
    expect(root.querySelector('.wu-day-editor')).toBeNull();
    expect(one(root, '.wu-day-persona')).toBe('“A worried yellow duck.”');
    expect(one(root, '.wu-day-who .wu-day-saved')).toBe("Saved. Teo's model reads it from the next minute.");
    expect(root.querySelector('.wu-day-saved')?.getAttribute('role')).toBe('status');
    vi.advanceTimersByTime(3900);
    expect(root.querySelector('.wu-day-saved')).not.toBeNull();
    vi.advanceTimersByTime(200);
    expect(root.querySelector('.wu-day-saved')).toBeNull();
    // Cancel: the fields close over the same personality.
    page.draw(teoState({ personality: saved, editing: { session: 's2', refusal: null, busy: false } }));
    page.draw(teoState({ personality: saved }));
    expect(root.querySelector('.wu-day-saved')).toBeNull();
    // A refusal keeps the fields open; nothing was saved.
    page.draw(teoState({ personality: saved, editing: { session: 's3', refusal: null, busy: true } }));
    page.draw(teoState({ personality: saved, editing: { session: 's3', refusal: 'Nothing changed.', busy: false } }));
    page.draw(teoState({ personality: saved }));
    expect(root.querySelector('.wu-day-saved')).toBeNull();
  });

  it("says where this world's people do not read a personality, and no saved note there", async () => {
    const { root, page } = await open();
    const unread = { character: { name: 'Teo', about: ABOUT }, shown: false };
    page.draw(teoState({ personality: unread, editing: { session: 's1', refusal: null, busy: true } }));
    expect(one(root, '.wu-day-reads')).toBe("This world's people were added before personalities could be written, so Teo's model does not read this.");
    page.draw(teoState({ personality: { ...unread, character: { name: 'Teo', about: 'Changed.' } } }));
    expect(root.querySelector('.wu-day-saved')).toBeNull();
  });
});

describe("Teo's day keys", () => {
  it('offers each key only where it works and says what each asked', async () => {
    const { root, act, page } = await open();
    page.draw(teoState());
    // Ask names the person, as the card's keys do (DESIGN 03:57).
    expect(keys(root)).toEqual(['↑↓Earlier, later', 'MModel', 'NPersonality', 'RRun', 'CCompare', 'QAsk Teo', 'EscBack']);
    expect(keyNamed(root, 'Back').getAttribute('aria-keyshortcuts')).toBe('Escape');
    for (const word of ['Model', 'Personality', 'Run', 'Compare', 'Ask Teo', 'Back']) keyNamed(root, word).click();
    // One with no name is asked by its kind.
    page.draw(residentState({ canAsk: true }));
    expect(keys(root)).toContain('QAsk the resident');
    page.draw(teoState());
    expect(act.mock.calls).toEqual([['model'], ['personality'], ['run'], ['compare'], ['ask'], ['back']]);
    // The arrows' key steps earlier, over a line heard, and from the oldest back to the newest.
    act.mockClear();
    keyNamed(root, 'Earlier, later').click();
    expect(act).toHaveBeenLastCalledWith('row', 3);
    page.draw(teoState({ didFocus: 3 }));
    keyNamed(root, 'Earlier, later').click();
    expect(act).toHaveBeenLastCalledWith('row', 4);
    page.draw(teoState({ didFocus: 4 }));
    keyNamed(root, 'Earlier, later').click();
    expect(act).toHaveBeenLastCalledWith('row', 0);
    // While a run is on: R stops, and the running line stands in for the last run; while it is asked, R waits.
    page.draw(teoState({ run: { open: true, big: '9:13 left · $0.0011 of $0.05', small: '', busy: false, refusal: null }, running: "Teo's model is deciding · 9:13 left" }));
    expect(keys(root)).toContain('RStop');
    expect(one(root, '.wu-day-small')).toBe("$0.06 in · $0.24 out per million tokensTeo's model is deciding · 9:13 left");
    act.mockClear();
    keyNamed(root, 'Stop').click();
    expect(act).toHaveBeenLastCalledWith('stop');
    page.draw(teoState({ run: { open: true, big: '9:13 left · $0.0011 of $0.05', small: '', busy: true, refusal: 'A run is already on. Stop it first.' } }));
    expect(keyNamed(root, 'Stop').hasAttribute('disabled')).toBe(true);
    expect(one(root, '.wu-day-small')).toBe('$0.06 in · $0.24 out per million tokens9:13 left · $0.0011 of $0.05');
    expect(one(root, '.wu-day-who .wu-day-refused')).toBe('A run is already on. Stop it first.');
    // No model connected: no R; no choice to move between: no arrows; nothing to compare, nothing to ask, no model to choose.
    page.draw(teoState({ connected: false, did: rows().slice(0, 2), didFocus: 0, canCompare: false, canAsk: false, assignable: false }));
    expect(keys(root)).toEqual(['NPersonality', 'EscBack']);
    // A person playing Teo: no Current tag beside who decides.
    page.draw(teoState({ decider: 'person', decides: 'A person is playing Teo' }));
    expect(one(root, '.wu-day-decides')).toBe('A person is playing Teo');
  });

  it('is styled by its own sheet: the model list, Compare and Ask in the right column', () => {
    // The rules for these went with the run strip's sheet once (batch 42), and the list drew as bare bullets.
    const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../tools/previews/world-workspace/character-page.css'), 'utf8');
    const page = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../tools/previews/world-workspace/character-page.ts'), 'utf8');
    expect(page).toContain("import './character-page.css';");
    for (const rule of ['.wu-model-rows {', '.wu-model-row {', '.wu-model-name {', '.wu-model-price {', '.wu-model-current {', '.wu-model-head {', '.wu-model-intro {', '.wu-char-note {', '.wu-orb-row {', '.wu-ask-line {', '.wu-cmp-explain {', '.wu-model-row > .wu-key {']) {
      expect(css).toContain(rule);
    }
    expect(css).toMatch(/\.wu-model-rows \{[^}]*list-style: none/u);
  });

  it("keeps choosing a model, Compare's question and Ask in the right column with their own keys", async () => {
    const { root, act, page } = await open();
    const choices = [
      { model: { provider: 'nebius', modelId: 'nvidia/nemotron', name: NEMOTRON, price: { input: '0.06', output: '0.24' } }, current: true },
      { model: null, current: false },
    ];
    page.draw(teoState({ choosing: { choices, focus: 0, refusal: null, busy: false } }));
    expect(root.querySelector('.wu-day-did')).toBeNull();
    expect(all(root, '.wu-day-side .wu-model-name')).toEqual([`${NEMOTRON}Current`, 'Routine']);
    // The same chooser as the card's (r07, F11): each of the first nine rows carries its number key.
    expect([...root.querySelectorAll('.wu-model-row')].map((row) => [row.querySelector('.wu-key')?.textContent, row.getAttribute('aria-keyshortcuts')])).toEqual([['1', '1'], ['2', '2']]);
    expect(keys(root)).toEqual(['↑↓Choose', 'EnterUse this model', 'EscBack']);
    (root.querySelectorAll('.wu-model-row')[1] as HTMLElement).click();
    expect(act).toHaveBeenLastCalledWith('choose', 1);
    keyNamed(root, 'Use this model').click();
    expect(act).toHaveBeenLastCalledWith('use');
    page.draw(teoState({ compare: { nothing: null, big: 'Ask another model', explain: 'The same moments.', choices: [choices[0]], focus: 0, figure: 'Asking 5 of 24 · $0.0008 of $0.01', asking: true, note: null, canStart: false } }));
    expect(keys(root)).toEqual(['EscStop']);
    // Compare's list is chosen with the arrows alone: no number keys there.
    expect(root.querySelector('.wu-model-row .wu-key')).toBeNull();
    page.draw(teoState({ ask: { questions: ['What is Teo doing?', 'Why?'], focus: 0, busy: false, asked: null, answer: null, failure: null } }));
    expect(all(root, '.wu-ask-row')).toEqual(['What is Teo doing?', 'Why?']);
    expect(keys(root)).toEqual(['↑↓Choose', 'EnterAsk', 'EscBack']);
    // Back on the day, the chosen card is where it was.
    page.draw(teoState());
    expect(items(root)[2]!.getAttribute('aria-current')).toBe('true');
  });

  it("keeps a guest's model too dear to ask once in Compare's list, faint, with why, and never chosen there", async () => {
    const { root, act, page } = await open();
    const why = 'Asking it once can cost up to $0.086, more than the $0.03 left for AI models here.';
    const choices = [
      { model: { provider: 'nebius', modelId: 'nvidia/ultra', name: 'Nemotron 3 Ultra', price: { input: '0.60', output: '2.40' } }, current: false, over: why },
      { model: { provider: 'nebius', modelId: 'nvidia/nemotron', name: NEMOTRON, price: { input: '0.06', output: '0.24' } }, current: false, over: null },
    ];
    page.draw(teoState({ compare: { nothing: null, big: 'Ask another model', explain: 'The same moments.', choices, focus: 1, figure: 'At most $0.01', asking: false, note: null, canStart: true } }));
    const rows = [...root.querySelectorAll<HTMLElement>('.wu-cmp-ask .wu-model-row')];
    expect(rows.map((row) => [row.classList.contains('wu-model-over'), row.getAttribute('aria-disabled')])).toEqual([[true, 'true'], [false, null]]);
    expect(all(root, '.wu-cmp-ask .wu-model-why')).toEqual([why]);
    rows[0]!.click();
    expect(act).not.toHaveBeenCalledWith('compareChoose', 0);
    rows[1]!.click();
    expect(act).toHaveBeenLastCalledWith('compareChoose', 1);
  });

  it("draws the chooser as a gallery: free first in groups, maker and size, the focused row opened with its maker's words (A3)", async () => {
    const { root, page } = await open();
    const card = (maker: string, total: string, says: string, licence: string) => ({
      maker, parameters: { total, active: null }, licence, says, source: `https://huggingface.co/maker/model/blob/${'0'.repeat(40)}/README.md`, readOn: '2026-10-23',
    });
    const nebius = 'Nebius Token Factory, which serves open models behind one OpenAI-compatible API.';
    const says = 'This model is optimized for collaborative agents and high-volume workloads.';
    const choices = [
      { model: { provider: 'ollama_local', providerDescription: 'This computer, through Ollama.', modelId: 'qwen/4b', name: 'Qwen3 4B Instruct', price: { input: '0', output: '0' }, local: true,
        card: card('Qwen', '4.0B', 'Improvements in general capabilities.', 'Apache 2.0') }, current: false },
      { model: { provider: 'nebius', providerDescription: nebius, modelId: 'nvidia/nemotron', name: NEMOTRON, price: { input: '0.06', output: '0.24' },
        card: card('NVIDIA', '30B', says, 'NVIDIA Nemotron Open Model License') }, current: true },
      { model: null, current: false },
    ];
    page.draw(teoState({ choosing: { choices, focus: 1, refusal: null, busy: false } }));
    expect(all(root, '.wu-day-side .wu-model-intro')).toEqual(['Open models, each from its maker. Picking one spends nothing. Only a run spends.']);
    expect(all(root, '.wu-gallery-label')).toEqual(['On this computer, free', 'With your Nebius Token Factory key, per million tokens']);
    expect(all(root, '.wu-model-sub')).toEqual(['Qwen · 4B', 'NVIDIA · 30B']);
    expect(all(root, '.wu-model-price')).toEqual(['Free', '$0.06 in · $0.24 out', 'No AI model · Free']);
    // Only the focused row opens, inside itself: the maker's words, then on a line of their own where they come from and the licence.
    expect([...root.querySelectorAll('.wu-model-open')].map((open) => open.firstChild?.textContent)).toEqual([`“${says}”`]);
    expect(all(root, '.wu-model-open > .wu-model-from')).toEqual(["from NVIDIA's model card · NVIDIA Nemotron Open Model License"]);
    expect(root.querySelectorAll('.wu-model-row')[1]!.querySelector('.wu-model-open')).not.toBeNull();
    // None running on this computer yet: its group stands with its one line and no key; a guest's key group is the host's.
    page.draw(teoState({ choosing: { choices: choices.slice(1), focus: 0, refusal: null, busy: false, waiting: true, fromServer: true } }));
    expect(all(root, '.wu-gallery-label')).toEqual(['On this computer, free', "From this server's budget, per million tokens"]);
    expect(all(root, '.wu-gallery-waiting')).toEqual(['None is running yet. Start one with a local model runner, and it shows here, free.']);
    expect([...root.querySelectorAll('.wu-model-row')].map((row) => row.querySelector('.wu-key')?.textContent)).toEqual(['1', '2']);
  });

  it("stands a guest's model asking which once can cost more than they have left faint after the last model, with why and no key (U2)", async () => {
    const { root, page } = await open();
    const nemotron = { provider: 'nebius', providerDescription: 'Nebius Token Factory.', modelId: 'nvidia/nemotron', name: NEMOTRON, price: { input: '0.06', output: '0.24' }, card: null };
    const line = 'Asking it once can cost up to $0.043, more than the $0.03 left for AI models here.';
    const over = [{ word: 'Nemotron 3 Ultra 550B', sub: 'NVIDIA · 550B', line }];
    page.draw(teoState({ choosing: { choices: [{ model: nemotron, current: false }, { model: null, current: true }], focus: 0, refusal: null, busy: false, fromServer: true, over } }));
    expect(all(root, '.wu-gallery-waiting')).toEqual([`Nemotron 3 Ultra 550BNVIDIA · 550B${line}`]);
    // In the group of the last model offered, under no label of its own; only the models offered and Routine have keys.
    expect(all(root, '.wu-gallery-label')).toEqual(["From this server's budget, per million tokens"]);
    expect([...root.querySelectorAll('.wu-model-row')].map((row) => row.querySelector('.wu-key')?.textContent)).toEqual(['1', '2']);
    expect(root.querySelector('.wu-gallery-waiting')!.closest('button')).toBeNull();
  });
});

describe("a person's runner's models (L1)", () => {
  // What a runner states (a model's family, the name it serves it by, its licence) is the person's own text: drawn as
  // text in both choosers, never as markup.
  const mark = '<img src=x onerror="window.ranMarkup = true">';
  const digest = (c: string) => `local/sha256-${c.repeat(64)}`;
  const able = {
    provider: 'ollama_local', providerDescription: 'This computer, through Ollama.', modelId: digest('a'), name: `Llama · 1.2B${mark}`,
    price: { input: '0', output: '0' }, local: true, card: null,
    runner: { family: `llama${mark}`, size: '1.2B', servedAs: `small${mark}`, licence: `A LICENSE ${mark}`, checkedMs: 238 },
  };
  const faint = (c: string, name: string, state: string, reason: string | null) => ({
    provider: 'ollama_local', modelId: digest(c), name, family: null, size: null, servedAs: `${c}${mark}`, licence: null, state, reason,
    contextTokens: 4096, deadlineMs: 20000, checkedMs: null,
  });
  const runner = [faint('b', `Llama · 1.2B${mark}`, 'checking', null), faint('c', `tiny${mark}`, 'not_able', 'form')];

  it('draws them on the page as text, never as markup', async () => {
    const { root, page } = await open();
    page.draw(teoState({ choosing: { choices: [{ model: able, current: false }, { model: null, current: false }], focus: 0, refusal: null, busy: false, runner } }));
    expect(root.querySelector('img[src="x"]')).toBeNull();
    expect(all(root, '.wu-model-name')[0]).toBe(`Llama · 1.2B${mark}`);
    expect(all(root, '.wu-model-sub')).toEqual([`Your runner calls it small${mark}`]);
    expect(all(root, '.wu-model-open > .wu-model-from')).toEqual([`from your runner · \u201cA LICENSE ${mark}\u201d`]);
    expect(all(root, '.wu-gallery-waiting')).toEqual([
      `Llama · 1.2B${mark} · Checking that it can decide for a person here…Your runner calls it b${mark}`,
      `tiny${mark}It did not answer with one of the offered choices when checked.`,
    ]);
    expect(all(root, '.wu-gallery-label')).toEqual(['On this computer, free', 'Also on this computer, not able to decide for a person here']);
  });

  it('draws them in the model list as text, never as markup', async () => {
    const { runnerRows } = await (import('../../../../tools/previews/world-workspace/' + 'character-group.ts') as Promise<{
      runnerRows(block: unknown): HTMLElement[];
    }>);
    const host = document.createElement('div');
    host.append(...runnerRows({
      group: 'On this computer, free',
      checking: [{ word: `Llama · 1.2B${mark} · Checking that it can decide for a person here…`, sub: `Your runner calls it b${mark}` }],
      label: 'Also on this computer, not able to decide for a person here',
      notAble: [{ word: `tiny${mark}`, sub: null, line: 'It did not answer with one of the offered choices when checked.' }],
    }));
    expect(host.querySelector('img')).toBeNull();
    expect(all(host, '.cg-waiting')).toEqual([
      `Llama · 1.2B${mark} · Checking that it can decide for a person here…Your runner calls it b${mark}`,
      `tiny${mark}It did not answer with one of the offered choices when checked.`,
    ]);
    expect(all(host, '.cg-group-label')).toEqual(['On this computer, free', 'Also on this computer, not able to decide for a person here']);
  });
});

describe("the world's model list (L1, DESIGN 11:58)", () => {
  it('keeps Routine below the window, fades the foot while more lie past it, and folds the runner\'s not-able rows', async () => {
    const group = await (import('../../../../tools/previews/world-workspace/' + 'character-group.mjs') as Promise<{
      modelGroup(input: Record<string, unknown>): unknown;
    }>);
    const drawn = await (import('../../../../tools/previews/world-workspace/' + 'character-group.ts') as Promise<{
      characterGroup(input: { scale: () => number; onAction: (action: string) => void }): { root: HTMLElement; set(content: unknown): void };
    }>);
    const many = Array.from({ length: 12 }, (_, n) => ({ provider: 'ollama_local', modelId: `m${n}`, name: `Model ${n + 1}`, local: true, price: { input: '0', output: '0' } }));
    const runner = [{ provider: 'ollama_local', modelId: `local/sha256-${'c'.repeat(64)}`, name: 'tiny', family: null, size: null,
      servedAs: 'tiny:1m', licence: null, state: 'not_able', reason: 'form', contextTokens: 4096, deadlineMs: 20000, checkedMs: null }];
    const shown = drawn.characterGroup({ scale: () => 1, onAction: () => {} });
    document.body.append(shown.root);
    shown.set(group.modelGroup({ who: teo, models: many, focus: 0, runner }));
    const window = shown.root.querySelector('.cg-window')!;
    expect(window.classList.contains('cg-more')).toBe(true);
    expect([...window.querySelectorAll('.cg-model-word')].map((node) => node.textContent)).toEqual(Array.from({ length: 8 }, (_, n) => `Model ${n + 1}`));
    // Routine stands below the window, in the list itself, with the next number (Teo's current: no model).
    const routine = [...shown.root.querySelectorAll('.cg-list > .cg-model')];
    expect(routine.map((node) => [node.querySelector('.wu-glyph')?.textContent, node.querySelector('.cg-model-word')?.textContent])).toEqual([['9', 'RoutineCurrent']]);
    // The not-able rows fold into one faint line at the foot of this computer's group, with where their reasons are told:
    // past the window here, in view once the window reaches the group's foot.
    expect(all(shown.root, '.cg-waiting')).toEqual([]);
    shown.set(group.modelGroup({ who: teo, models: many, focus: 11, runner }));
    expect(shown.root.querySelector('.cg-window')!.classList.contains('cg-more')).toBe(false);
    expect(all(shown.root, '.cg-window .cg-waiting')).toEqual(['And 1 more on this computer that cannot decide for a person here.Their reasons are on Teo\'s day page.']);
    shown.root.remove();
  });
});

describe("Teo's day keeps the world's clock", () => {
  type View = {
    dayStartMinute(state: unknown): number | null;
    didRows(read: Record<string, unknown>): Array<{ time: string }>;
  };
  const view = async (): Promise<View> =>
    import('../../../../tools/previews/world-workspace/' + 'character-view.mjs') as Promise<View>;

  it('reads the first minute a society of things is served with, so its rows say the time of day', async () => {
    const { dayStartMinute, didRows } = await view();
    // As society-api.ts folds the clock the read serves beside the state into a society of things' state.
    const things = { profile: 'exulanica-society/v7', tick: 42, start_minute_of_day: 360, minute_of_day: 402, day: 0 };
    expect(dayStartMinute(things)).toBe(360);
    // A planner's state keeps its clock in its own field; a society with neither has no clock.
    expect(dayStartMinute({ profile: 'exulanica-society/v2', tick: 42, clock: { start_minute_of_day: 480 } })).toBe(480);
    expect(dayStartMinute({ profile: 'exulanica-society/v7', tick: 42 })).toBeNull();
    // A routine's row at minute 42 of a day that starts at 06:00 says 06:42, not "Minute 42".
    const events = [{ tick: 42, event_kind: 'goal_selected', subject_id: 'teo', document: { reason: 'routine' } }];
    const read = { events, subjectId: 'teo', wordGoal: () => 'Went to rest', modelName: () => null };
    expect(didRows({ ...read, startMinute: dayStartMinute(things) }).map((row) => row.time)).toEqual(['06:42']);
    expect(didRows({ ...read, startMinute: dayStartMinute({ tick: 42 }) }).map((row) => row.time)).toEqual(['Minute 42']);
  });
});

describe("Teo's day shows a stand the routine repeats once (R5h)", () => {
  type Rows = { didRows(read: Record<string, unknown>): Array<{ time: string; what: string; sub: string }> };
  const view = async (): Promise<Rows> =>
    import('../../../../tools/previews/world-workspace/' + 'character-view.mjs') as Promise<Rows>;
  const nano = { provider: 'nebius', model_id: 'nano' };
  // A minute as the events read serves it: the goal the routine set, then the choice of a line, then the line.
  const minute = (tick: number, goal: Record<string, unknown>, to: string | null) => [
    { subject_id: 'teo', tick, event_kind: 'goal_selected', document: { reason: 'stopping_a_while', goal } },
    { subject_id: 'teo', tick, event_kind: 'decision_applied', document: { request_id: `r${tick}`, chose: 'say something', model: nano } },
    { subject_id: 'teo', tick, event_kind: 'said', document: { thing: { request_id: `r${tick}`, line: 'Morning.', to, heard_by: ['ines'], model: nano } } },
  ];
  const stand = { kind: 'stand', target_id: null };

  it("keeps his lines and the first stand, and a walk the routine starts in a line's minute", async () => {
    const { didRows } = await view();
    // Newest minute first: a walk to the bench at 06:07, stands at 06:05 and 06:03 that repeat the stand at 06:01.
    const events = [
      ...minute(7, { kind: 'rest', target_id: 'bench' }, null), ...minute(5, stand, 'ines'), ...minute(3, stand, null),
      { subject_id: 'teo', tick: 1, event_kind: 'goal_selected', document: { reason: 'stopping_a_while', goal: stand } },
    ];
    const wordGoal = (document: { goal: { kind: string } }) => (document.goal.kind === 'rest' ? 'Went to rest' : 'Went to stand a while');
    const rows = didRows({ events, subjectId: 'teo', startMinute: 360, wordGoal, modelName: () => NEMOTRON, options: () => 8, who: () => ({ start: 'Ines', within: 'Ines' }) });
    expect(rows.map((row) => [row.time, row.what, row.sub])).toEqual([
      ['06:07', 'Said: “Morning.”', `${NEMOTRON} · 8 choices`],
      ['06:07', 'Went to rest', 'Routine'],
      ['06:05', 'Said to Ines: “Morning.”', `${NEMOTRON} · 8 choices`],
      ['06:03', 'Said: “Morning.”', `${NEMOTRON} · 8 choices`],
      // The stand at 06:03 came before that minute's line, so nothing lies between it and the first.
      ['06:01 to 06:03', 'Went to stand a while', 'Routine'],
    ]);
  });
});

describe("Teo's day names a run only where Teo was in it (R5g)", () => {
  type Ran = { ranIn(events: readonly unknown[], subjectId: string, run: unknown): boolean };
  const view = async (): Promise<Ran> =>
    import('../../../../tools/previews/world-workspace/' + 'character-view.mjs') as Promise<Ran>;
  const run = { startTick: 1, endTick: 50 };
  const chose = (subject: string, tick: number, model: unknown) => ({ subject_id: subject, tick, event_kind: 'decision_applied', document: { model } });
  const said = (subject: string, tick: number, model: unknown) => ({ subject_id: subject, tick, event_kind: 'said', document: { thing: { model, line: 'Morning.' } } });
  const nano = { provider: 'nebius', model_id: 'nano' };

  it("takes a choice or a line Teo's model made inside the run, and nothing else", async () => {
    const { ranIn } = await view();
    expect(ranIn([chose('teo', 7, nano)], 'teo', run)).toBe(true);
    expect(ranIn([said('teo', 16, nano)], 'teo', run)).toBe(true);
    // Willa's model chose in the run; Teo followed his routine through it, and chose by a model after it.
    expect(ranIn([chose('willa', 7, nano), chose('teo', 9, null), said('teo', 12, null), chose('teo', 51, nano)], 'teo', run)).toBe(false);
    // A run with no end yet, or none, names nobody here.
    expect(ranIn([chose('teo', 7, nano)], 'teo', { startTick: 1, endTick: null })).toBe(false);
    expect(ranIn([chose('teo', 0, nano)], 'teo', { startTick: 0, endTick: null })).toBe(false);
    expect(ranIn([chose('teo', 7, nano)], 'teo', null)).toBe(false);
  });
});

describe("Teo's day at 1440 by 900", () => {
  it("takes History's 1440 rules: margins 80, the title 60, pictures 0.86, and keeps the chosen card in view", async () => {
    const { root, page } = await open(1440, 900);
    page.draw(teoState({ didFocus: 0 }));
    const dialog = root.querySelector('[role="dialog"]') as HTMLElement;
    // The narrow class carries the stylesheet's 1440 sizes (the name at 60, the keys 64 in and 32 up).
    expect(dialog.classList.contains('wu-hr-narrow')).toBe(true);
    const who = root.querySelector('.wu-day-who') as HTMLElement;
    expect([who.style.left, who.style.top, who.style.width]).toEqual(['80px', '84px', '480px']);
    expect((root.querySelector('.wu-day-face') as HTMLElement).style.width).toBe('96px');
    const cards = items(root);
    expect(cards.map((card) => [card.style.left, card.style.top])).toEqual([['680px', '150px'], ['680px', '288px'], ['680px', '426px'], ['680px', '564px']]);
    const picture = cards[0]!.querySelector('.wu-hr-pic') as HTMLElement;
    expect([picture.style.width, picture.style.height]).toEqual(['179px', '101px']);
    // The oldest card is out of view: the path runs on to the band over the page's foot.
    expect(root.querySelector('.wu-day-path .line')?.getAttribute('d')).toBe('M 640 150 L 640 780');
    // Choosing the oldest slides the view; the path then starts under "What Teo did".
    page.draw(teoState({ didFocus: 4 }));
    expect(all(root, '.wu-day-title')).toEqual(['Marco asked Teo', 'Teo met Ines at the bench', 'Teo went to the lower pools', 'Teo left home']);
    expect(root.querySelector('.wu-day-path .line')?.getAttribute('d')).toBe('M 640 116 L 640 582');
    // A choice inside the view moves nothing.
    page.draw(teoState({ didFocus: 2 }));
    expect(all(root, '.wu-day-title')[0]).toBe('Marco asked Teo');
  });
});

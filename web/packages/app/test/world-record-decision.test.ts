// @vitest-environment happy-dom
// A decision as r10 (tools/previews/world-workspace/decision-page.ts): what the record page draws for one decision on
// History's light page, read left to right (what the model was told gathered by a bracket, the ring, the choices fanned
// to a column with the taken one lit, its line on to the moment's card), at 1920 and 1440; a column of more than twelve
// scrolled with the up and down arrows; a person's decision; and the keys, each only where it works.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Choice { readonly number: number; readonly words: string; readonly chosen: boolean }
interface DecisionPageState {
  readonly over: string;
  readonly title: string;
  readonly model: string | null;
  readonly done: string | null;
  readonly verdict: string | null;
  readonly toldLabel: string;
  readonly told: readonly { readonly label: string; readonly lines: readonly string[]; readonly apart: boolean }[] | null;
  readonly choicesLabel: string;
  readonly choices: readonly Choice[];
  readonly earlier: boolean;
  readonly later: boolean;
  readonly record: string | null;
  readonly failure: string | null;
  readonly canCompare: boolean;
  readonly decided?: string | null;
  readonly said?: string | null;
  readonly action?: string | null;
  readonly decider?: 'model' | 'person' | 'external' | 'agent' | null;
  readonly answered?: { readonly latencyMs: number | null; readonly costUsd: string | number | null; readonly costKnown: boolean } | null;
  readonly unanswered?: {
    readonly asks: number; readonly latencyMs: number | null; readonly costUsd: string | number | null; readonly costKnown: boolean;
    readonly reason: string | null;
  } | null;
  readonly late?: boolean;
  readonly moment?: boolean | null;
  readonly choicesHeading?: string | null;
  readonly picture?: string | null;
  readonly portraits?: readonly { readonly name: string; readonly url: string | null }[];
  readonly ground?: string | null;
  readonly personality?: { readonly name: string | null; readonly about: string | null } | null;
  readonly why?: string | null;
  readonly detail?: {
    readonly status?: string;
    readonly request?: Readonly<Record<string, unknown>>;
    readonly decision?: Readonly<Record<string, unknown>> | null;
  } | null;
  readonly canExportTrajectories?: boolean;
  readonly branches?: readonly Record<string, unknown>[];
  readonly trainingSummary?: string | null;
}
interface DecisionPage { draw(state: DecisionPageState): void; close(): void; hide(hidden: boolean): void }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const module = async (): Promise<{ openDecisionPage(host: HTMLElement, act: (action: string) => void): DecisionPage }> =>
  import('../../../../tools/previews/world-workspace/' + 'decision-page.ts') as Promise<{ openDecisionPage(host: HTMLElement, act: (action: string) => void): DecisionPage }>;

const NINE = ['Say something to Ines', 'Talk with Ines', 'Say something to everyone near', 'Follow Ines', 'Walk to the bench',
  'Walk to the lower pools', 'Walk to the terrace cafe', 'Stand here', 'Wait a minute'];
const choices = (words: readonly string[], taken: number): Choice[] => words.map((one, at) => ({ number: at + 1, words: one, chosen: at === taken }));

/** r10's decision as the host gives it, with the record page's own parts filled. */
function teo(extra: Partial<DecisionPageState> = {}): DecisionPageState {
  return {
    over: '06:52 · Day 1 · Teo met Ines at the bench', title: '“Morning, Ines. The boats are out early.”', model: 'Nemotron 3 Nano 30B',
    done: 'Answered in 0.9 s · cost $0.0003', verdict: null, toldLabel: 'Context',
    told: [
      // As personalityRecordLines gives it: the name, then the words.
      { label: 'Personality', lines: ['Teo', 'A retired fisherman who walks the quay every morning and talks to anyone who will listen.'], apart: false },
      { label: 'Location & Time', lines: ['The lower pools · 06:52 · Day 1'], apart: false },
      { label: 'Status', lines: ['Rest: not needed yet (417 of 1000).', 'A meal: needed now (712 of 1000).'], apart: true },
      { label: 'Nearby', lines: ['Ines, 3 m away, standing, can hear Teo.', 'The bench, 4 m away.'], apart: false },
      { label: 'Heard', lines: ['Ines, 1 minute ago: “Morning.”'], apart: false },
      { label: 'Remembers', lines: ['Ines, met 3 minutes ago.'], apart: false },
    ],
    choicesLabel: "Teo's Choices (9)", choices: choices(NINE, 0), earlier: true, later: false, record: null, failure: null, canCompare: true,
    decided: 'Teo spoke to Ines', said: 'Teo: “Morning, Ines. The boats are out early.”', decider: 'model',
    answered: { latencyMs: 912, costUsd: '0.00030000', costKnown: true }, choicesHeading: "Teo's Choices",
    picture: null, portraits: [{ name: 'Teo', url: null }, { name: 'Ines', url: '/portraits/ines.png' }],
    ...extra,
  };
}

function host(width = 1920, height = 1080) {
  const root = document.createElement('div');
  // The page lays itself out for the window it is in: r10's own 1920 by 1080, or 1440 by 900.
  Object.defineProperty(root, 'clientWidth', { value: width });
  Object.defineProperty(root, 'clientHeight', { value: height });
  document.body.append(root);
  return root;
}

async function open(state: DecisionPageState, width = 1920, height = width === 1920 ? 1080 : 900) {
  const root = host(width, height);
  const act = vi.fn();
  const page = (await module()).openDecisionPage(root, act);
  page.draw(state);
  return { root, act, page };
}

const all = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)].map((node) => node.textContent);
const keys = (root: HTMLElement) => all(root, '.wu-hr-key');
const press = (code: string) => {
  const event = new KeyboardEvent('keydown', { code, key: code, cancelable: true, bubbles: true });
  document.dispatchEvent(event);
  return event;
};
const numbers = (root: HTMLElement) => all(root, '.wu-rd-choice .wu-rd-number').map(Number);
const at = (node: Element | null) => node instanceof HTMLElement ? [node.style.left, node.style.top] : null;

afterEach(() => { document.body.replaceChildren(); });

describe('A decision (r10)', () => {
  it('draws what was told, the ring, nine choices with the taken one lit, and what happened on the moment card', async () => {
    const { root, act } = await open(teo());
    const page = root.querySelector('[role="dialog"]') as HTMLElement;
    expect(page.classList.contains('wu-record')).toBe(true);
    expect(page.classList.contains('wu-record-decision')).toBe(true);
    expect(page.classList.contains('wu-hr-narrow')).toBe(false);
    expect(page.getAttribute('aria-label')).toBe('Teo spoke to Ines');
    // The head: when and in which moment, what Teo decided, then who decided and what the answer took.
    expect(at(page.querySelector('.wu-rd-head'))).toEqual(['120px', '84px']);
    expect(page.querySelector('.wu-rd-head .wu-hr-over')?.textContent).toBe('06:52 · Day 1 · Teo met Ines at the bench');
    expect(page.querySelector('.wu-rd-title')?.textContent).toBe('Teo spoke to Ines');
    expect(document.activeElement?.textContent).toBe('Teo spoke to Ines');
    // Who decided, and nothing else: the answer's time and cost stand under the ring (D5).
    expect(page.querySelector('.wu-rd-by')?.textContent).toBe('Decided by Nemotron 3 Nano 30B');
    expect(page.querySelector('.wu-rd-by .wu-hr-model')?.textContent).toBe('Nemotron 3 Nano 30B');

    // What the model was told, each section's name and words; the personality's name plain and its words as written, in
    // curly quotes; each need on its own line; the rest run on.
    const told = page.querySelector('.wu-rd-told') as HTMLElement;
    expect([told.style.left, told.style.top, told.style.width]).toEqual(['120px', '300px', '470px']);
    expect(told.querySelector('.wu-rd-label')?.textContent).toBe('Context');
    expect(all(told, '.wu-rd-name')).toEqual(['Personality', 'Location & Time', 'Status', 'Nearby', 'Heard', 'Remembers']);
    expect(all(told.querySelectorAll('.wu-rd-section')[0]!, '.wu-rd-block')).toEqual(['Teo', '“A retired fisherman who walks the quay every morning and talks to anyone who will listen.”']);
    expect(all(told, '.wu-rd-quote')).toEqual(['“A retired fisherman who walks the quay every morning and talks to anyone who will listen.”']);
    expect(all(told.querySelectorAll('.wu-rd-section')[2]!, '.wu-rd-block')).toEqual(['Rest: not needed yet (417 of 1000).', 'A meal: needed now (712 of 1000).']);
    expect(all(told.querySelectorAll('.wu-rd-section')[3]!, '.wu-rd-block')).toEqual(['Ines, 3 m away, standing, can hear Teo. The bench, 4 m away.']);

    // The flow: the bracket gathering what was told into one line, the ring at x 740, each choice's curve to the column
    // at x 852, the taken one solid and its line running on to the card at x 1380; the others dashed.
    const lines = page.querySelector('svg.wu-rd-flow') as SVGSVGElement;
    expect(lines.querySelectorAll('path.in')).toHaveLength(2);
    expect(lines.querySelector('path.in')?.getAttribute('d')).toMatch(/^M 612 320 L 620 320 L 620 \d+(\.\d)? L 612 \d+(\.\d)?$/);
    expect(lines.querySelector('circle.node')?.getAttribute('cx')).toBe('740');
    expect(lines.querySelector('circle.node')?.getAttribute('r')).toBe('22');
    expect(lines.querySelector('circle.core')?.getAttribute('r')).toBe('8');
    expect(lines.querySelectorAll('path.dim')).toHaveLength(8);
    expect([...lines.querySelectorAll('path.lit')].map((line) => line.getAttribute('d'))).toEqual([
      'M 762 614 C 800 614, 812 438, 852 438', expect.stringMatching(/^M 11\d\d 438 L 1380 438$/)]);
    expect(lines.querySelectorAll('circle.end')).toHaveLength(9);
    expect([...lines.querySelectorAll('circle.end.lit')].map((dot) => [dot.getAttribute('cx'), dot.getAttribute('cy')])).toEqual([['852', '438']]);
    // Under the ring: how many choices it had and what the answer took; who decided is the head's alone.
    expect(all(page, '.wu-rd-caption > span')).toEqual(['chose 1 of 9', 'answered in 0.9\u00a0s · $0.0003']);
    // What the model was told is the first heading after the title.
    expect(page.querySelector('.wu-rd-told > h2.wu-rd-told-heading')?.textContent).toBe('Context');
    expect(at(page.querySelector('.wu-rd-caption'))).toEqual(['740px', '650px']);

    // The choices, numbered as offered, 44px apart; the taken one in the ink with its tag.
    expect(page.querySelector('.wu-rd-over .wu-rd-label')?.textContent).toBe("Teo's Choices");
    expect(at(page.querySelector('.wu-rd-over'))).toEqual(['868px', '392px']);
    expect(numbers(page)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(all(page, '.wu-rd-choice-words')).toEqual(NINE);
    expect([...page.querySelectorAll<HTMLElement>('.wu-rd-choice')].map((row) => row.style.top)).toEqual(['438px', '482px', '526px', '570px', '614px', '658px', '702px', '746px', '790px']);
    expect([...page.querySelectorAll<HTMLElement>('.wu-rd-choice')].map((row) => row.dataset['taken'])).toEqual(['true', ...Array(8).fill('false')]);
    expect(all(page, '.wu-rd-choice .wu-hr-tag')).toEqual(['Chosen']);
    expect(page.querySelector('.wu-rd-choice[data-taken="true"] .wu-hr-tag')).not.toBeNull();
    expect(page.querySelector('.wu-rd-more')).toBeNull();

    // What happened: History's card, 300 by 170 on the taken one's line, its portraits, and the line said.
    const card = page.querySelector('.wu-rd-moment') as HTMLElement;
    expect([card.style.left, card.style.top]).toEqual(['1380px', '336px']);
    const picture = card.querySelector('.wu-hr-pic') as HTMLElement;
    expect([picture.style.width, picture.style.height]).toEqual(['300px', '170px']);
    expect(picture.querySelector(':scope > img')).toBeNull();
    expect([...card.querySelectorAll<HTMLElement>('.wu-hr-orb')].map((orb) => [orb.style.width, orb.textContent, orb.querySelector('img')?.getAttribute('src') ?? null]))
      .toEqual([['52px', 'T', null], ['52px', '', '/portraits/ines.png']]);
    expect(card.querySelector('.wu-rd-label')?.textContent).toBe('Outcome');
    expect(card.querySelector('.wu-hr-said')?.textContent).toBe('Teo: “Morning, Ines. The boats are out early.”');

    // History's keys: earlier and later through the character's decisions, the full record, compare, back.
    expect(keys(page)).toEqual(['←→Previous / Next', 'JRaw Prompt', 'CCompare', 'EscBack']);
    for (const button of page.querySelectorAll<HTMLButtonElement>('.wu-hr-key')) button.click();
    expect(act.mock.calls.map(([action]) => action)).toEqual(['earlier', 'record', 'compare', 'back']);
  });

  it('scrolls fourteen choices twelve at a time with the up and down arrows, the taken one shown first', async () => {
    const words = Array.from({ length: 14 }, (_, index) => `Walk to spot ${index + 1}`);
    const { root, page } = await open(teo({ choices: choices(words, 1), choicesHeading: "Teo's choices" }));
    expect(numbers(root)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect([...root.querySelectorAll<HTMLElement>('.wu-rd-choice')].map((row) => Number.parseFloat(row.style.top))).toEqual(Array.from({ length: 12 }, (_, step) => 372 + 44 * step));
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 14', 'answered in 0.9\u00a0s · $0.0003']);
    // Only the down arrow while more lie below; the up arrow once more lie above.
    expect(all(root, '.wu-rd-more')).toEqual(['↓']);
    expect(press('ArrowDown').defaultPrevented).toBe(true);
    expect(numbers(root)).toEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]);
    expect(all(root, '.wu-rd-more')).toEqual(['↑', '↓']);
    press('ArrowDown');
    press('ArrowDown');
    expect(numbers(root)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]);
    expect(all(root, '.wu-rd-more')).toEqual(['↑']);
    // The taken one scrolled out of view: its lit curve points up to the column's edge and nothing runs on to the card,
    // which stays where it was.
    expect(root.querySelector('.wu-rd-choice[data-taken="true"]')).toBeNull();
    expect([...root.querySelectorAll('path.lit')].map((line) => line.getAttribute('d'))).toEqual(['M 762 614 C 800 614, 812 350, 852 350']);
    expect(root.querySelector('circle.end.lit')).toBeNull();
    expect((root.querySelector('.wu-rd-moment') as HTMLElement).style.top).toBe('314px');
    // The up arrow's cap scrolls back; the arrows do nothing while the full record shows.
    (root.querySelector('.wu-rd-over .wu-rd-more') as HTMLButtonElement).click();
    expect(numbers(root)[0]).toBe(2);
    press('ArrowUp');
    expect(numbers(root)[0]).toBe(1);
    expect(root.querySelector('.wu-rd-choice[data-taken="true"] .wu-rd-number')?.textContent).toBe('2');
    page.draw(teo({ choices: choices(words, 1), record: '{"request": {}}' }));
    expect(press('ArrowDown').defaultPrevented).toBe(false);
    // Another decision's choices open on their own window; a taken one past the twelfth is the last row drawn.
    page.draw(teo({ choices: choices(words, 13) }));
    expect(numbers(root)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]);
    expect(root.querySelector('.wu-rd-choice[data-taken="true"] .wu-rd-number')?.textContent).toBe('14');
  });

  it("says who decided a person's decision in T7's words, with no model and nothing told", async () => {
    const { root } = await open(teo({
      model: null, decider: 'person', answered: null, done: null, told: [], canCompare: false, earlier: false, later: false,
      decided: 'Marco asked Teo', said: 'Marco: “Did they bring in anything good?”', portraits: [],
      choices: choices(['Say something to Teo', 'Wait a minute', 'Walk to the bench'], 0),
    }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Decided by a person playing');
    expect(root.querySelector('.wu-hr-model')).toBeNull();
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 3']);
    // Nothing told: no column of it and no bracket; the choices and the card stay.
    expect(root.querySelector('.wu-rd-told')).toBeNull();
    expect(root.querySelector('path.in')).toBeNull();
    expect(numbers(root)).toEqual([1, 2, 3]);
    expect(root.querySelector('.wu-rd-moment .wu-hr-said')?.textContent).toBe('Marco: “Did they bring in anything good?”');
    expect(root.querySelector('.wu-rd-moment .wu-hr-orbs')).toBeNull();
    // No earlier or later decision and nothing to compare: only the keys that work.
    expect(keys(root)).toEqual(['JRaw Prompt', 'EscBack']);
  });

  it("draws today's decision state before the host fills the record page's own parts", async () => {
    const { root } = await open({
      over: '06:52 · Day 1 · Teo said to Ines', title: 'Wait here a minute', model: 'Nemotron 3 Nano 30B',
      done: 'Answered in 1.3 s · cost at most $0.0014', verdict: 'Accepted; no minute has acted on it yet.',
      toldLabel: 'Context', told: [{ label: 'Location & Time', lines: ['On the glass terraces · 06:54 · Day 1'], apart: false }],
      choicesLabel: "Teo's Choices (3)", choices: choices(['Walking, 62 m away', 'Wait here a minute', 'At home, 35 m away'], 1),
      earlier: false, later: true, record: null, failure: null, canCompare: false,
    });
    expect(root.querySelector('.wu-rd-title')?.textContent).toBe('Wait here a minute');
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Decided by Nemotron 3 Nano 30B');
    expect(root.querySelector('.wu-rd-over .wu-rd-label')?.textContent).toBe("Teo's Choices (3)");
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 3', 'answered in 1.3 s · cost at most $0.0014']);
    // What happened: what came of it, the choice itself being the title already; the quiet tile where no picture exists.
    expect(root.querySelector('.wu-rd-moment .wu-rd-action')).toBeNull();
    expect(root.querySelector('.wu-rd-moment .wu-rd-verdict')?.textContent).toBe('Accepted; no minute has acted on it yet.');
    expect(root.querySelector('.wu-rd-moment .wu-hr-pic img')).toBeNull();
    expect(keys(root)).toEqual(['←→Previous / Next', 'JRaw Prompt', 'EscBack']);
  });

  it('reads, says a record it could not read, and shows the full record with only its keys', async () => {
    const reading = teo({ over: '', title: '', model: null, done: null, told: null, choicesLabel: '', choices: [], decided: null, said: null, answered: null, decider: null, earlier: false });
    const { root, page } = await open(reading);
    expect(root.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe('Reading the decision…');
    expect(root.querySelector('.wu-rd-told .wu-rd-note')?.textContent).toBe('Reading the decision…');
    expect(root.querySelector('svg.wu-rd-flow')).toBeNull();
    expect(root.querySelector('.wu-rd-moment')).toBeNull();
    expect(keys(root)).toEqual(['EscBack']);
    page.draw({ ...reading, told: [], failure: 'This decision could not be read. Try again.' });
    const note = root.querySelector('.wu-rd-told .wu-rd-note') as HTMLElement;
    expect(note.textContent).toBe('This decision could not be read. Try again.');
    expect(note.dataset['refused']).toBe('true');
    expect(root.querySelector('svg.wu-rd-flow')).toBeNull();
    // [J]: the stored record in place of the flow, focused so the arrows scroll it; no Compare while it shows.
    page.draw(teo({ record: '{\n  "request": {}\n}' }));
    const record = root.querySelector('.wu-rd-record') as HTMLElement;
    expect(record.textContent).toBe('{\n  "request": {}\n}');
    expect(document.activeElement).toBe(record);
    expect(root.querySelector('svg.wu-rd-flow')).toBeNull();
    expect(root.querySelector('.wu-rd-title')?.textContent).toBe('Teo spoke to Ines');
    expect(keys(root)).toEqual(['←→Previous / Next', 'JRaw Prompt', 'EscBack']);
    // Hidden while another page stands over it, and gone when closed.
    page.hide(true);
    expect((root.querySelector('[role="dialog"]') as HTMLElement).hidden).toBe(true);
    page.close();
    expect(root.querySelector('[role="dialog"]')).toBeNull();
  });

  it("takes History's 1440 sizes in a narrower window", async () => {
    const { root } = await open(teo(), 1440);
    const page = root.querySelector('[role="dialog"]') as HTMLElement;
    expect(page.classList.contains('wu-hr-narrow')).toBe(true);
    expect(at(page.querySelector('.wu-rd-head'))).toEqual(['80px', '84px']);
    expect(at(page.querySelector('.wu-rd-told'))).toEqual(['80px', '260px']);
    expect(page.querySelector('svg.wu-rd-flow circle.node')?.getAttribute('cx')).toBe('600');
    expect([...page.querySelectorAll<HTMLElement>('.wu-rd-choice')].map((row) => Number.parseFloat(row.style.top))).toEqual(Array.from({ length: 9 }, (_, step) => 360 + 38 * step));
    expect(page.querySelector('path.lit')?.getAttribute('d')).toBe('M 622 512 C 660 512, 672 360, 712 360');
    const card = page.querySelector('.wu-rd-moment') as HTMLElement;
    expect([card.style.left, card.style.top]).toEqual(['1100px', '271px']);
    const picture = card.querySelector('.wu-hr-pic') as HTMLElement;
    expect([picture.style.width, picture.style.height]).toEqual(['260px', '148px']);
    expect((card.querySelector('.wu-hr-orb') as HTMLElement).style.width).toBe('46px');
  });

  it('keeps a long title to two lines and what the model was told below the head', async () => {
    // The title is cut at two lines with an ellipsis (the page's CSS), and the head runs no wider than reaches the card.
    // Read from the repository as arrangement.test.ts reads it: the tests run from web/.
    const css = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-record-decision.css`, 'utf8');
    expect(css).toMatch(/\.wu-rd-title \{[^}]*-webkit-line-clamp: 2;[^}]*overflow: hidden;/);
    const long = `“${'The boats are out early and the nets are drying on the quay, so come and see what they brought in. '.repeat(2).trim()}”`;
    // At 1440 two lines end near y 250, so what was told moves down to 274 and its bracket with it; the choices' label
    // stays below the head.
    const { root } = await open(teo({ decided: null, title: long }), 1440);
    expect(root.querySelector('.wu-rd-title')?.textContent).toBe(long);
    expect((root.querySelector('.wu-rd-head') as HTMLElement).style.maxWidth).toBe('980px');
    expect((root.querySelector('.wu-rd-told') as HTMLElement).style.top).toBe('274px');
    expect(root.querySelector('path.in')?.getAttribute('d')).toMatch(/^M 472 294 L 480 294 /);
    expect(Number.parseFloat((root.querySelector('.wu-rd-over') as HTMLElement).style.top)).toBeGreaterThan(250);
    // A short title leaves what was told at its own place.
    const short = await open(teo(), 1440);
    expect((short.root.querySelector('.wu-rd-told') as HTMLElement).style.top).toBe('260px');
    // At 1920 two lines still end clear of 300.
    const wide = await open(teo({ decided: null, title: long }));
    expect((wide.root.querySelector('.wu-rd-told') as HTMLElement).style.top).toBe('300px');
    expect((wide.root.querySelector('.wu-rd-head') as HTMLElement).style.maxWidth).toBe('1220px');
  });

  it('never cuts the chosen choice, and wraps every other to two lines at most, Chosen after the last line (D3)', async () => {
    const css = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-record-decision.css`, 'utf8');
    // Every rule for exactly this selector, joined.
    const rule = (selector: string) => [...css.matchAll(new RegExp(`(?:^|\\n)${selector.replace(/[.[\]"():]/g, (c) => `\\${c}`)} \\{([^}]*)\\}`, 'g'))].map((found) => found[1]).join(' ');
    expect(rule('.wu-record-decision .wu-rd-choice')).toMatch(/white-space: normal;/);
    expect(rule('.wu-record-decision .wu-rd-choice:not([data-taken="true"])')).toMatch(/-webkit-line-clamp: 2;[^]*overflow: hidden;/);
    expect(rule('.wu-record-decision .wu-rd-choice[data-taken="true"]')).toBe('');
    expect(rule('.wu-record-decision .wu-rd-choice-words')).not.toMatch(/ellipsis|nowrap/);
    const long = 'Say something to the eight legged finned creature, 8 m away';
    const { root } = await open(teo({ choices: [{ number: 1, words: long, chosen: true }, { number: 2, words: 'Wait a minute', chosen: false }] }));
    const taken = root.querySelector('.wu-rd-choice[data-taken="true"]') as HTMLElement;
    expect([taken.querySelector('.wu-rd-choice-words')?.textContent, taken.lastElementChild?.textContent]).toEqual([long, 'Chosen']);
  });

  it("sizes what was told and the stored record from the window's height", async () => {
    // In its own 1080: what was told stops 60px above the foot, the record 24px above the key row's caps.
    const tall = await open(teo());
    expect((tall.root.querySelector('.wu-rd-told') as HTMLElement).style.maxHeight).toBe('720px');
    tall.page.draw(teo({ record: '{}' }));
    expect((tall.root.querySelector('.wu-rd-record') as HTMLElement).style.height).toBe('695px');
    // In a 1920 by 960 window both stop above that window's foot and keys (the caps 40px up and 21px tall).
    const { root, page } = await open(teo(), 1920, 960);
    expect((root.querySelector('.wu-rd-told') as HTMLElement).style.maxHeight).toBe(`${960 - 60 - 300}px`);
    expect(root.querySelector('svg.wu-rd-flow')?.getAttribute('height')).toBe('960');
    page.draw(teo({ record: '{\n  "request": {}\n}' }));
    const record = root.querySelector('.wu-rd-record') as HTMLElement;
    expect([record.style.top, record.style.height]).toEqual(['300px', `${960 - 40 - 21 - 24 - 300}px`]);
  });

  it("keeps a personality's name apart from its words, and says a name written alone plainly", async () => {
    const section = (lines: readonly string[], personality?: DecisionPageState['personality']) =>
      teo({ told: [{ label: 'Personality', lines, apart: false }], ...(personality === undefined ? {} : { personality }) });
    const blocks = (root: HTMLElement) => [...root.querySelectorAll('.wu-rd-told .wu-rd-block')].map((block) => [block.textContent, block.classList.contains('wu-rd-quote')]);
    // Only a name written: personalityRecordLines gives the name alone, which is said plainly, never quoted.
    const { root, page } = await open(section(['Teo']));
    expect(blocks(root)).toEqual([['Teo', false]]);
    page.draw(section(['Teo'], { name: 'Teo', about: null }));
    expect(blocks(root)).toEqual([['Teo', false]]);
    // Only words written, said so by the personality: those are quoted.
    page.draw(section(['A slow, kind resident who likes the pools.'], { name: null, about: 'A slow, kind resident who likes the pools.' }));
    expect(blocks(root)).toEqual([['“A slow, kind resident who likes the pools.”', true]]);
    // Both: the name plain, then the words in quotes.
    page.draw(section(['Teo', 'A slow, kind resident who likes the pools.']));
    expect(blocks(root)).toEqual([['Teo', false], ['“A slow, kind resident who likes the pools.”', true]]);
  });

  it('does nothing with an arrow key after it is closed', async () => {
    const words = Array.from({ length: 14 }, (_, index) => `Walk to spot ${index + 1}`);
    const { root, act, page } = await open(teo({ choices: choices(words, 0) }));
    // Open, the down arrow scrolls the column.
    expect(press('ArrowDown').defaultPrevented).toBe(true);
    expect(numbers(root)[0]).toBe(2);
    page.close();
    expect(root.querySelector('[role="dialog"]')).toBeNull();
    for (const code of ['ArrowDown', 'ArrowUp', 'ArrowDown']) expect(press(code).defaultPrevented).toBe(false);
    expect(act).not.toHaveBeenCalled();
  });
});

describe('Under the ring, the answer and what it cost (D5)', () => {
  it("shows no cost line for an outside program's answer, and the figures keep their space unbroken", async () => {
    const { root } = await open(teo({ decider: 'external', model: null }));
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 9']);
    document.body.replaceChildren();
    const model = await open(teo());
    expect(model.root.querySelector('.wu-rd-caption > .wu-rd-paid')?.textContent).toBe('answered in 0.9\u00a0s · $0.0003');
    // The caption's words stand in a halo of the page's own ground, so the fan's curves break around them.
    const css = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-record-decision.css`, 'utf8');
    expect(css).toMatch(/\.wu-rd-caption > \* \{ text-shadow: [^}]*var\(--hr-ground\)/);
  });
});

describe("A model's decision whose choice was not taken (U3)", () => {
  const unanswered = { asks: 1, latencyMs: 2100, costUsd: '0.01214400', costKnown: true, reason: 'spending_limit_reached' };
  const why = 'Its answer was not one of the actions, and asking it again would have gone over the money left.';

  it('says the model was asked with no usable answer, what the ask took and cost, and marks no choice taken', async () => {
    const { root } = await open(teo({ title: 'Walked to the quay', choices: choices(NINE, -1), answered: null, unanswered, why, canCompare: false }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Asked Nemotron 3 Nano 30B · no usable answer · the routine acted');
    // Under the ring what the ask took and cost; how it ended is the head's. Why the routine acted, under the head, alone.
    expect(all(root, '.wu-rd-caption > span')).toEqual(['asked once in 2.1\u00a0s · $0.0121']);
    expect(all(root, '.wu-rd-hint')).toEqual([why]);
    expect(root.querySelector('.wu-rd-head .wu-rd-hint')?.textContent).toBe(why);
    expect(root.textContent).not.toMatch(/Decided by|chose 1 of|Chosen|picked/u);
  });

  it('says the model was not asked where nothing was sent, with why, and no cost or note under the ring', async () => {
    const { root } = await open(teo({ title: 'Walked to the quay', choices: choices(NINE, -1), answered: null, canCompare: false,
      unanswered: { ...unanswered, asks: 0, latencyMs: null, costUsd: null }, why: 'Asking it would have gone over the money left.' }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Nemotron 3 Nano 30B not asked · the routine acted');
    // The money is the line under the head's to say: nothing under the ring repeats it.
    expect(all(root, '.wu-rd-caption > span')).toEqual([]);
    expect(all(root, '.wu-rd-hint')).toEqual(['Asking it would have gone over the money left.']);
    document.body.replaceChildren();
    // A reason that line does not name stands under the ring, in four words or fewer.
    const paused = await open(teo({ title: 'Walked to the quay', choices: choices(NINE, -1), answered: null, canCompare: false,
      unanswered: { ...unanswered, asks: 0, latencyMs: null, costUsd: null, reason: 'spending_suspended' }, why: 'It could not be asked just then.' }));
    expect(all(paused.root, '.wu-rd-caption > span')).toEqual(['spending was paused']);
  });

  it('says a choice the world had moved past was made too late: marked Not Applied, its answer under the ring', async () => {
    const { root } = await open(teo({ title: 'Walked to the quay', choices: choices(NINE, 4), late: true }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Asked Nemotron 3 Nano 30B · chose too late · the routine acted');
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 9', 'answered in 0.9\u00a0s · $0.0003']);
    expect(all(root, '.wu-rd-choice .wu-hr-tag')).toEqual(['Not Applied']);
  });
});

describe('A decision an outside AI agent made (AG1d 4, 5)', () => {
  it("says it decided, and under the ring its choice of nine and its time, never a cost", async () => {
    const { root } = await open(teo({ decider: 'agent', model: null, answered: { latencyMs: 1600, costUsd: null, costKnown: true } }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Decided by an outside AI agent');
    expect(all(root, '.wu-rd-caption > span')).toEqual(['chose 1 of 9', 'answered in 1.6\u00a0s']);
  });

  it('says a turn it did not answer was asked with no answer, and the routine acted', async () => {
    const { root } = await open(teo({ decider: 'agent', model: null, title: 'Stood a while', choices: choices(NINE, -1), answered: null, canCompare: false,
      unanswered: { asks: 1, latencyMs: null, costUsd: null, costKnown: true, reason: 'no_answer_in_time' } }));
    expect(root.querySelector('.wu-rd-by')?.textContent).toBe('Asked the outside AI agent · no answer · the routine acted');
    expect(all(root, '.wu-rd-caption > span')).toEqual([]);
    expect(root.textContent).not.toMatch(/Chosen|chose 1 of/u);
  });
});

describe('What happened where a decision made no moment (U3c)', () => {
  it('draws no picture frame, its portraits above the words, where no moment stands behind the decision', async () => {
    const { root } = await open(teo({ moment: false, picture: null }));
    const card = root.querySelector('.wu-rd-moment')!;
    expect(card.querySelector('.wu-hr-pic')).toBeNull();
    expect(card.classList.contains('wu-rd-unframed')).toBe(true);
    // The portraits stand first in the card, then the words.
    expect(card.firstElementChild?.classList.contains('wu-hr-orbs')).toBe(true);
    expect(all(card, '.wu-rd-label')).toEqual(['Outcome']);
  });

  it("keeps the frame while a moment's picture is still to come, and while the moments are read", async () => {
    for (const state of [teo({ moment: true, picture: null }), teo({ moment: null, picture: null }), teo({ picture: null })]) {
      const { root } = await open(state);
      expect(root.querySelector('.wu-rd-moment .wu-hr-pic'), String(state.moment)).not.toBeNull();
      document.body.replaceChildren();
    }
  });
});

describe('A long choice wraps rather than losing its end (D3)', () => {
  it('draws a long choice whole on two lines at 1440 and moves the rows below it down by the second line', async () => {
    const words = ['Say something to Ines Brook (a villager), 4 m away', 'Wait a minute', 'Stand here'];
    const { root } = await open(teo({ choices: choices(words, 1) }), 1440);
    const rows = [...root.querySelectorAll<HTMLElement>('.wu-rd-choice')];
    const tops = rows.map((row) => Number.parseFloat(row.style.top));
    expect([tops[1]! - tops[0]!, tops[2]! - tops[1]!]).toEqual([38 + 11, 38]);
    expect(rows[0]!.querySelector('.wu-rd-choice-words')?.textContent).toBe(words[0]);
    // At 1920 the same words fit one line, and the rows stand 44 apart as before.
    document.body.replaceChildren();
    const wide = await open(teo({ choices: choices(words, 1) }));
    const wideTops = [...wide.root.querySelectorAll<HTMLElement>('.wu-rd-choice')].map((row) => Number.parseFloat(row.style.top));
    expect([wideTops[1]! - wideTops[0]!, wideTops[2]! - wideTops[1]!]).toEqual([44, 44]);
  });
});

describe('A decision says nothing of what its parts are (ROOT\'s sweep of 27 October)', () => {
  it('draws no notes and offers no N, whoever decided', async () => {
    for (const state of [teo(), teo({ decider: 'person', model: null, answered: null, toldLabel: 'What the person playing Teo was shown', canCompare: false })]) {
      const { root } = await open(state);
      expect(root.querySelectorAll('.wu-rd-hint')).toHaveLength(0);
      expect(root.querySelector('.wu-rd-over-hint, .wu-rd-key-hint')).toBeNull();
      expect(keys(root).some((key) => key.startsWith('N'))).toBe(false);
      document.body.replaceChildren();
    }
  });
});

describe("The told column ends cleanly (D4)", () => {
  it('fades a told column taller than its box until it is scrolled to its end', async () => {
    const { root } = await open(teo());
    const told = root.querySelector('.wu-rd-told') as HTMLElement;
    const sizes = { scrollHeight: 900, clientHeight: 600, scrollTop: 0 };
    for (const name of Object.keys(sizes)) Object.defineProperty(told, name, { configurable: true, get: () => sizes[name as keyof typeof sizes] });
    told.dispatchEvent(new Event('scroll'));
    expect(told.dataset['more']).toBe('true');
    sizes.scrollTop = 300;
    told.dispatchEvent(new Event('scroll'));
    expect(told.dataset['more']).toBe('false');
  });

  it("closes a list shown in part on its own faint line at the section's end", async () => {
    const heard = { label: 'Heard', lines: ['Ines, 2 minutes ago: “Morning.”', 'Ari, 1 minute ago: “Hello.”'], apart: false, more: 'And 4 earlier lines in the Raw Prompt.' };
    const { root } = await open(teo({ told: [heard] }));
    const section = [...root.querySelectorAll('.wu-rd-section')].find((part) => part.querySelector('.wu-rd-name')?.textContent === 'Heard')!;
    const blocks = [...section.querySelectorAll('.wu-rd-block')];
    expect(blocks.at(-1)?.textContent).toBe('And 4 earlier lines in the Raw Prompt.');
    expect(blocks.at(-1)?.classList.contains('wu-rd-faint')).toBe(true);
    expect(blocks.filter((block) => block.classList.contains('wu-rd-faint'))).toHaveLength(1);
  });

  it('offers [T] Export Trajectories on the decision page and displays counterfactual summary metrics', async () => {
    const { root, act } = await open(
      teo({
        canExportTrajectories: true,
        branches: [
          { ask_id: 'a1', model: { name: 'Qwen3 235B' }, same_choice: false, kind: 'went', outcome: 'Walk to the market' },
        ],
      }),
    );
    expect(keys(root)).toContain('TExport Trajectories');
    expect(press('KeyT').defaultPrevented).toBe(true);
    expect(act).toHaveBeenCalledWith('export-trajectories');
    expect(root.querySelector('.wu-rd-training')?.textContent).toBe(
      'Training Data · Verified Decisions: 1 · Counterfactual Pairs: 1 · Agreement Rate: 0%',
    );
  });
});

describe('The 5-stage live execution pipeline & [X] Data telemetry (Pillar 1)', () => {
  it('renders the proportional 5-stage execution pipeline bar and breakdown from a recorded decision receipt', async () => {
    const detail = {
      status: 'completed',
      request: {
        request_id: 'r1',
        base_tick: 412,
        state_sha256: '8f2a9c1b44d0e5128f2a9c1b44d0e5128f2a9c1b44d0e5128f2a9c1b44d0e512',
        document_sha256: 'a'.repeat(64),
        provider_config: { provider: 'nebius_token_factory', model_id: 'nvidia/Nemotron-3-Nano-30B' },
        context: {
          tick: 412,
          character: { name: 'Teo', about: 'A retired fisherman.' },
          here: 'by the lower pools',
          clock: { day: 0, minute_of_day: 412 },
          needs: [{ label: 'rest', milli: 417, seen_to_at_milli: 500 }],
          surroundings: {
            beings: [{ who: 'Ines', metres: 3, doing: 'standing', hears_you: true }],
            things: [{ what: 'bench', metres: 4 }],
            more_beings: 0,
            more_things: 0,
          },
          heard: [{ from: 'Ines', line: 'Morning.', minutes_ago: 1 }],
          remembers: { beings: [{ who: 'Ines', met_minutes_ago: 3, here: true }], places: [], handed: [] },
          options: NINE.map((label) => ({ label, kind: 'say_to' })),
        },
      },
      decision: {
        request_id: 'r1',
        status: 'accepted',
        reason: 'validated_choice',
        proposal: { label: 'Say something to Ines', line: 'Morning, Ines. The boats are out early.' },
        provider: {
          provider: 'nebius_token_factory',
          served_model_id: 'nvidia/Nemotron-3-Nano-30B',
          latency_ms: 912,
          prompt_tokens: 410,
          completion_tokens: 38,
          cost_usd: '0.00030000',
          cost_known: true,
        },
      },
    };

    const { root } = await open(teo({ detail }));
    const pipeline = root.querySelector('section.wu-rd-pipeline') as HTMLElement;
    expect(pipeline).not.toBeNull();
    expect(pipeline.dataset['verdict']).toBe('Applied');
    expect([pipeline.style.left, pipeline.style.width]).toEqual(['120px', '1680px']);

    // Proportional 5-segment execution bar summing to 100%.
    const segments = [...pipeline.querySelectorAll<HTMLElement>('.wu-rd-pipeline-segment')];
    expect(segments).toHaveLength(5);
    expect(segments.map((seg) => seg.dataset['stage'])).toEqual(['snapshot', 'context', 'inference', 'check', 'outcome']);
    expect(segments.every((seg) => seg.dataset['status'] === 'ok')).toBe(true);
    const totalPercent = segments.reduce((sum, seg) => sum + Number.parseInt(seg.style.width, 10), 0);
    expect(totalPercent).toBe(100);

    // 5-stage breakdown labels, summaries, and details.
    expect(all(pipeline, '.wu-rd-stage-label')).toEqual([
      '1. World Snapshot',
      '2. Context',
      '3. Model Inference',
      '4. Engine Check',
      '5. Outcome',
    ]);
    expect(all(pipeline, '.wu-rd-stage-summary')).toEqual([
      'Tick 412 · #8f2a9c1b',
      '6 sections · 9 choices',
      'Nemotron 3 Nano 30B · 912 ms (0.9 s)',
      'Applied',
      'Teo: “Morning, Ines. The boats are out early.”',
    ]);
    expect(all(pipeline, '.wu-rd-stage-detail')).toEqual([
      '1 being, 1 object',
      'Personality · Location & Time · Status · Nearby · Heard · Remembers',
      'nebius token factory · 448 tok (410 in / 38 out) · $0.0003',
      'Option #1 verified',
      'Spoken line committed · Tick 412',
    ]);
  });

  it('shows refusal reasons, Not Applied, and Routine Fallback states in the 5-stage pipeline', async () => {
    const unanswered = { asks: 1, latencyMs: 2100, costUsd: '0.01214400', costKnown: true, reason: 'spending_limit_reached' };
    const why = 'Its answer was not one of the actions, and asking it again would have gone over the money left.';
    const { root, page } = await open(teo({ title: 'Walked to the quay', choices: choices(NINE, -1), answered: null, unanswered, why, canCompare: false }));
    const pipeline = root.querySelector('section.wu-rd-pipeline') as HTMLElement;
    expect(pipeline.dataset['verdict']).toBe('Routine Fallback');
    expect(pipeline.querySelector('[data-stage="check"] .wu-rd-stage-summary')?.textContent).toBe('Spending limit reached · Routine Fallback');
    expect(pipeline.querySelector('[data-stage="check"]')?.getAttribute('data-status')).toBe('fallback');
    expect(pipeline.querySelector('[data-stage="outcome"] .wu-rd-stage-summary')?.textContent).toBe('Walked to the quay');
    expect(pipeline.querySelector('[data-stage="outcome"] .wu-rd-stage-detail')?.textContent).toBe('Routine fallback committed to world state');

    // Late choice (world moved on before commit): marked Not Applied · Routine Fallback.
    page.draw(teo({ title: 'Walked to the quay', choices: choices(NINE, 4), late: true }));
    const latePipeline = root.querySelector('section.wu-rd-pipeline') as HTMLElement;
    expect(latePipeline.dataset['verdict']).toBe('Not Applied');
    expect(latePipeline.querySelector('[data-stage="check"] .wu-rd-stage-summary')?.textContent).toBe('Not Applied · Routine Fallback');
    expect(latePipeline.querySelector('[data-stage="check"]')?.getAttribute('data-status')).toBe('warn');
  });

  it('formats [X] Data person tag telemetry and town-wide model execution summary cleanly', async () => {
    const dataViewThings = await import('../../../../tools/previews/world-workspace/' + 'data-view-things.mjs') as {
      personLines(input: Record<string, unknown>): string[];
      personTelemetry(input: unknown): string | null;
      dataViewTelemetrySummary(input: unknown): string | null;
    };
    expect(dataViewThings.personLines({
      name: 'Teo',
      model: 'Nemotron 3 Nano 30B',
      telemetry: { status: 'accepted', disposition: 'applied', latencyMs: 912, costUsd: '0.0003' },
    })).toEqual(['Teo', 'Nemotron 3 Nano 30B', '912 ms · Applied · $0.0003']);
    expect(dataViewThings.dataViewTelemetrySummary({
      activeModels: 2,
      decisions: 18,
      applied: 17,
      latencyP50Ms: 740,
      costUsd: '0.0054',
    })).toBe('2 active models · 740 ms p50 · 17/18 applied · $0.0054');
  });
});


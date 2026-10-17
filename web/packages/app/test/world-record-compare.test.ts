// @vitest-environment happy-dom
// Compare as r12 (tools/previews/world-workspace/compare-page.ts): a character's last decisions asked again, drawn on
// History's line. A finished comparison of 12 says its answer in one sentence, hangs each different answer below its
// moment and opens the picked moment's answers at the right; while the asks run, their progress stands in the answer's
// place with [Esc] Stop; the keys say what they do and only where it works.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

interface CompareRow { readonly model: string; readonly again: boolean; readonly what: string; readonly tag: string | null }
interface CompareMark { readonly said: boolean; readonly differs: boolean; readonly hollow: boolean }
interface ComparePageState {
  readonly over: string;
  readonly title: string;
  readonly sub: string;
  readonly spent: string;
  readonly moment: { readonly label: string; readonly rows: readonly CompareRow[] } | null;
  readonly eachChose: readonly string[];
  readonly lanes: readonly { readonly name: string; readonly faint: boolean; readonly marks: readonly CompareMark[] }[];
  readonly times: readonly { readonly index: number; readonly text: string }[];
  readonly focus: number;
  readonly use: string | null;
  readonly line?: readonly { readonly time: string | null; readonly asked: boolean; readonly different: string | null }[];
  readonly branchName?: string;
  readonly asking?: string | null;
  readonly ground?: string | null;
}
interface ComparePage { draw(state: ComparePageState): void; close(): void }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const module = async (): Promise<{ openComparePage(host: HTMLElement, act: (action: string) => void): ComparePage }> =>
  import('../../../../tools/previews/world-workspace/' + 'compare-page.ts') as Promise<{ openComparePage(host: HTMLElement, act: (action: string) => void): ComparePage }>;

const NANO = 'Nemotron 3 Nano 30B', QWEN = 'Qwen3 235B Instruct';
const TIMES = ['06:41', '06:42', '06:43', '06:44', '06:45', '06:46', '06:47', '06:48', '06:49', '06:50', '06:51', '06:52'];
/** The frame's three different answers: 06:43, 06:47 and 06:51. */
const DIFFERENT = new Map([[2, 'Walk to the lower pools'], [6, 'Wait a minute'], [10, 'Follow Ines']]);

/** A finished comparison of 12, the picked moment 06:43 (3 of 12), as contextual-world.ts words it. */
function finished(overrides: Partial<ComparePageState> = {}): ComparePageState {
  const marks = (differs: (index: number) => boolean) => TIMES.map((_, index) => ({ said: false, differs: differs(index), hollow: false }));
  return {
    over: 'Teo · 12 decisions, 06:41 to 06:52 · Day 1',
    title: "Teo's last 12 decisions, asked again",
    sub: "The same moments, exactly as Teo's model was told them. Nothing in the world changed.",
    spent: 'Spent $0.003 asking again',
    moment: {
      label: 'At 06:43 · 3 of 12',
      rows: [
        { model: NANO, again: false, what: 'Said to Ines: “Calm water today, Ines.”', tag: 'As recorded' },
        { model: QWEN, again: false, what: 'Walk to the lower pools', tag: 'Different' },
        { model: `${NANO}, again`, again: true, what: 'Said to Ines: “Morning, Ines.”', tag: 'Same' },
      ],
    },
    eachChose: [
      `${QWEN} chose as ${NANO} did at 9 of 12 moments.`,
      `Asked again, ${NANO} chose as before at 10 of 12: a small difference can be chance.`,
    ],
    lanes: [
      { name: NANO, faint: false, marks: marks(() => false) },
      { name: QWEN, faint: false, marks: marks(index => DIFFERENT.has(index)) },
      { name: `${NANO}, again`, faint: true, marks: marks(index => index === 4 || index === 9) },
    ],
    times: [0, 3, 6, 9, 11].map(index => ({ index, text: TIMES[index]! })),
    focus: 2,
    use: `Use ${QWEN} for Teo`,
    line: TIMES.map((time, index) => ({ time, asked: true, different: DIFFERENT.get(index) ?? null })),
    branchName: 'Qwen3 235B',
    ...overrides,
  };
}

const text = (node: Element | null | undefined) => node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
const keyWords = (root: Element) => [...root.querySelectorAll('.wu-hr-keys .wu-hr-key')].map(key => [[...key.querySelectorAll('.wu-hr-cap')].map(cap => cap.textContent).join(' '), text(key.querySelector('.wu-hr-key-word'))]);
const keyNamed = (root: Element, word: string) => [...root.querySelectorAll<HTMLButtonElement>('.wu-hr-keys .wu-hr-key')].find(key => text(key.querySelector('.wu-hr-key-word')) === word);

function widen(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true });
}

async function opened(state: ComparePageState, width = 1920) {
  widen(width);
  const host = document.createElement('div');
  document.body.append(host);
  const act = vi.fn();
  const { openComparePage } = await module();
  const page = openComparePage(host, act);
  page.draw(state);
  const root = host.querySelector<HTMLElement>('.wu-record-compare')!;
  return { host, act, page, root };
}

afterEach(() => {
  document.body.replaceChildren();
  widen(1024);
});

describe('Compare as r12', () => {
  it('draws a finished comparison of 12 on History\'s light page', async () => {
    const { root } = await opened(finished());
    expect(root.classList.contains('wu-record')).toBe(true);
    expect(root.classList.contains('wu-hr-narrow')).toBe(false);
    expect(root.getAttribute('aria-label')).toBe("Teo's last 12 decisions, asked again");
    // The head: who, how many and when; the title; how they were asked and what asking again spent.
    expect(text(root.querySelector('.wu-rc-head .wu-hr-over'))).toBe('Teo · 12 decisions, 06:41 to 06:52 · Day 1');
    expect(text(root.querySelector('.wu-rc-title'))).toBe("Teo's last 12 decisions, asked again");
    expect(text(root.querySelector('.wu-rc-sub'))).toBe("The same moments, exactly as Teo's model was told them. Nothing in the world changed. Spent $0.003 asking again.");
    expect(document.activeElement).toBe(root.querySelector('.wu-rc-title'));
    // The answer in one sentence, each model's name kept whole, and the rerun's line under it.
    const sentence = root.querySelector('.wu-rc-answer .wu-rc-sentence');
    expect(text(sentence)).toBe('Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at 9 of 12 moments.');
    expect([...sentence!.querySelectorAll('.wu-hr-model')].map(name => name.textContent)).toEqual([QWEN, NANO]);
    expect(text(root.querySelector('.wu-rc-answer .wu-rc-rerun'))).toBe('Asked again, Nemotron 3 Nano 30B chose as before at 10 of 12: a small difference can be chance.');
    expect(root.querySelector('.wu-rc-asking')).toBeNull();
    // No em dash anywhere on the page.
    expect(root.textContent).not.toMatch(/\u2014/u);
  });

  it('puts the 12 moments on History\'s line, hangs the 3 different answers below them and fills the picked dot', async () => {
    const { root } = await opened(finished());
    const line = root.querySelector('svg.wu-rc-line')!;
    expect(line.getAttribute('aria-hidden')).toBe('true');
    expect(line.querySelector('path.line')!.getAttribute('d')).toBe('M 120 560 L 1180 560');
    const dots = [...line.querySelectorAll('circle.dot')];
    expect(dots).toHaveLength(12);
    expect(dots.map(dot => Number(dot.getAttribute('cx')))).toEqual(expect.arrayContaining([132, 1180]));
    expect(dots.every(dot => dot.getAttribute('cy') === '560')).toBe(true);
    expect(dots.filter(dot => dot.getAttribute('data-picked') === 'true').map(dot => dot.getAttribute('data-index'))).toEqual(['2']);
    // Times every third, counted back from the newest, and the oldest.
    expect([...root.querySelectorAll('.wu-rc-time')].map(time => time.textContent)).toEqual(['06:41', '06:43', '06:46', '06:49', '06:52']);
    // A branch for each different answer only (no branch is the same answer), ending in the model's name over it.
    expect(line.querySelectorAll('path.branch')).toHaveLength(3);
    const branches = [...root.querySelectorAll<HTMLElement>('.wu-rc-branch')];
    expect(branches.map(branch => [branch.dataset['index'], text(branch.querySelector('.wu-rc-branch-name')), text(branch.querySelector('.wu-rc-branch-words'))])).toEqual([
      ['2', 'Qwen3 235B', 'Walk to the lower pools'],
      ['6', 'Qwen3 235B', 'Wait a minute'],
      ['10', 'Qwen3 235B', 'Follow Ines'],
    ]);
    // The first two read rightwards from their moments; the last, near the line's end, hangs left a level deeper.
    expect(branches.map(branch => [branch.dataset['side'], branch.dataset['level'], branch.style.top])).toEqual([['right', '0', '642px'], ['right', '0', '642px'], ['left', '1', '762px']]);
  });

  it('opens the picked moment at the right with each answer, its rule, its tag and words said in italic', async () => {
    const { root } = await opened(finished());
    const moment = root.querySelector<HTMLElement>('.wu-rc-moment')!;
    expect([moment.style.left, moment.style.top]).toEqual(['1260px', '300px']);
    expect(text(moment.querySelector('.wu-rc-at'))).toBe('At 06:43 · 3 of 12');
    const rows = [...moment.querySelectorAll<HTMLElement>('.wu-rc-row')];
    expect(rows.map(row => [text(row.querySelector('.wu-rc-row-model')), text(row.querySelector('.wu-rc-row-tag')), text(row.querySelector('.wu-rc-row-words'))])).toEqual([
      [NANO, 'As recorded', 'Said to Ines: “Calm water today, Ines.”'],
      [QWEN, 'Different', 'Walk to the lower pools'],
      [`${NANO}, again`, 'Same', 'Said to Ines: “Morning, Ines.”'],
    ]);
    // The recorded answer's rule is the line's colour; the others' are quiet.
    expect(rows.map(row => row.dataset['recorded'])).toEqual(['true', 'false', 'false']);
    expect(rows.map(row => [...row.querySelectorAll('.wu-rc-row-words i')].map(said => said.textContent))).toEqual([['“Calm water today, Ines.”'], [], ['“Morning, Ines.”']]);
  });

  it('answers its keys: earlier and later, use the asked model, back', async () => {
    const { root, act } = await opened(finished());
    expect(keyWords(root)).toEqual([['← →', 'Earlier, later'], ['Enter', 'Use Qwen3 235B Instruct for Teo'], ['Esc', 'Back']]);
    expect(keyNamed(root, 'Earlier, later')!.getAttribute('aria-keyshortcuts')).toBe('ArrowLeft ArrowRight');
    keyNamed(root, 'Earlier, later')!.click();
    keyNamed(root, 'Use Qwen3 235B Instruct for Teo')!.click();
    keyNamed(root, 'Back')!.click();
    expect(act.mock.calls.map(call => call[0])).toEqual(['later', 'use', 'back']);
  });

  it('moves earlier from the newest moment, where Compare opens, and later where a later one exists', async () => {
    const { root, act, page } = await opened(finished({ focus: 11, moment: { label: 'At 06:52 · 12 of 12', rows: finished().moment!.rows } }));
    keyNamed(root, 'Earlier, later')!.click();
    page.draw(finished({ focus: 0 }));
    keyNamed(root, 'Earlier, later')!.click();
    expect(act.mock.calls.map(call => call[0])).toEqual(['earlier', 'later']);
  });

  it('draws each key only where it works', async () => {
    const { root, page } = await opened(finished({ use: null }));
    expect(keyWords(root).map(([, word]) => word)).toEqual(['Earlier, later', 'Back']);
    // One moment asked: no line and nothing earlier or later.
    page.draw(finished({
      over: 'Teo · 1 decision, 06:43 · Day 1', title: "Teo's decision, asked again", eachChose: [], lanes: [], times: [], focus: 0,
      moment: { label: 'At 06:43', rows: finished().moment!.rows }, line: [{ time: '06:43', asked: true, different: 'Walk to the lower pools' }],
    }));
    expect(root.querySelector('svg.wu-rc-line')).toBeNull();
    expect(keyWords(root).map(([, word]) => word)).toEqual(['Use Qwen3 235B Instruct for Teo', 'Back']);
    expect(text(root.querySelector('.wu-rc-at'))).toBe('At 06:43');
  });

  it('stands the asks\' progress in the answer\'s place, with [Esc] Stop alone', async () => {
    const asking = 'Asking 5 of 24 · $0.0008 of $0.01';
    const line = TIMES.map((time, index) => ({ time, asked: index < 3, different: index === 2 ? 'Walk to the lower pools' : null }));
    const { root, act } = await opened(finished({ asking, line, eachChose: [] }));
    const progress = root.querySelector('.wu-rc-answer .wu-rc-asking')!;
    expect(text(progress)).toBe(asking);
    expect(progress.getAttribute('role')).toBe('status');
    expect(root.querySelector('.wu-rc-sentence')).toBeNull();
    // What came back so far is on the line; a moment not asked yet is faint, never drawn as the same answer.
    expect(root.querySelectorAll('.wu-rc-branch')).toHaveLength(1);
    expect([...root.querySelectorAll('circle.dot')].filter(dot => dot.getAttribute('data-asked') === 'false')).toHaveLength(9);
    expect(keyWords(root)).toEqual([['Esc', 'Stop']]);
    keyNamed(root, 'Stop')!.click();
    expect(act).toHaveBeenCalledWith('stop');
  });

  it('draws a state without a line from the other model\'s lane, as contextual-world.ts fills it', async () => {
    const { line: _line, branchName: _name, ...laneOnly } = finished();
    const { root } = await opened(laneOnly);
    // The branches come from the lane's marks; only the picked moment's carries its answer.
    const branches = [...root.querySelectorAll<HTMLElement>('.wu-rc-branch')];
    expect(branches.map(branch => [branch.dataset['index'], text(branch.querySelector('.wu-rc-branch-name')), text(branch.querySelector('.wu-rc-branch-words'))])).toEqual([
      ['2', QWEN, 'Walk to the lower pools'],
      ['6', QWEN, ''],
      ['10', QWEN, ''],
    ]);
    // The times the host chose.
    expect([...root.querySelectorAll('.wu-rc-time')].map(time => time.textContent)).toEqual(['06:41', '06:44', '06:47', '06:50', '06:52']);
  });

  it('draws the asked model\'s branches when it is the model that made the recorded decisions', async () => {
    // After Use, comparing again can ask the model that made the recorded decisions: both lanes carry its name.
    const { line: _line, branchName: _name, ...laneOnly } = finished();
    const lanes = laneOnly.lanes.map((lane, index) => ({ ...lane, name: index === 2 ? `${NANO}, again` : NANO }));
    const rows = laneOnly.moment!.rows.map(row => row.again ? row : { ...row, model: NANO });
    const { root } = await opened({ ...laneOnly, lanes, moment: { label: 'At 06:43 · 3 of 12', rows } });
    expect([...root.querySelectorAll<HTMLElement>('.wu-rc-branch')].map(branch => branch.dataset['index'])).toEqual(['2', '6', '10']);
  });

  it('keeps the opened moment a margin from the right edge at any width', async () => {
    // 1728 is a laptop's default: fixed places at 1260 and 540 wide ran past it, and the tags were cut.
    const { root } = await opened(finished(), 1728);
    const moment = root.querySelector<HTMLElement>('.wu-rc-moment')!;
    expect([moment.style.left, moment.style.width]).toEqual(['1068px', '540px']);
    expect(root.querySelector('svg.wu-rc-line path.line')!.getAttribute('d')).toBe('M 120 560 L 988 560');
    expect(root.querySelector<HTMLElement>('.wu-rc-answer')!.style.width).toBe('908px');
    expect(root.classList.contains('wu-hr-narrow')).toBe(false);
    document.body.replaceChildren();
    const small = (await opened(finished(), 1280)).root;
    expect([small.querySelector<HTMLElement>('.wu-rc-moment')!.style.left, small.querySelector<HTMLElement>('.wu-rc-moment')!.style.width]).toEqual(['780px', '420px']);
    expect(small.querySelector('svg.wu-rc-line path.line')!.getAttribute('d')).toBe('M 80 470 L 700 470');
    expect(Number.parseFloat(small.querySelector<HTMLElement>('.wu-rc-head')!.style.width) + 80).toBeLessThanOrEqual(1280 - 80);
  });

  it('keeps words said inline in their answer whatever another page\'s .wu-hr-said rule does', async () => {
    // The runner leaves imported stylesheets empty, so the page's own is read and applied here.
    const sheet = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-record-compare.css`, 'utf8');
    const style = document.createElement('style');
    // An unscoped rule as History's once was: a block with a margin, clamped.
    style.textContent = `.wu-hr-said { display: block; margin-top: 8px; overflow: hidden; -webkit-line-clamp: 2; }\n${sheet}`;
    document.head.append(style);
    try {
      const { root } = await opened(finished());
      const said = root.querySelector<HTMLElement>('.wu-rc-row-words .wu-hr-said')!;
      const looks = getComputedStyle(said);
      expect([looks.display, looks.marginTop, looks.overflow, looks.fontStyle]).toEqual(['inline', '0px', 'visible', 'italic']);
    } finally {
      style.remove();
    }
  });

  it('takes History\'s 1440 sizes on a narrower window', async () => {
    const { root, page } = await opened(finished(), 1440);
    expect(root.classList.contains('wu-hr-narrow')).toBe(true);
    expect(root.querySelector<HTMLElement>('.wu-rc-head')!.style.left).toBe('80px');
    expect(root.querySelector('svg.wu-rc-line path.line')!.getAttribute('d')).toBe('M 80 470 L 860 470');
    expect(root.querySelector<HTMLElement>('.wu-rc-moment')!.style.left).toBe('940px');
    // The window widens: the page takes its 1920 sizes again.
    widen(1920);
    window.dispatchEvent(new Event('resize'));
    expect(root.classList.contains('wu-hr-narrow')).toBe(false);
    expect(root.querySelector('svg.wu-rc-line path.line')!.getAttribute('d')).toBe('M 120 560 L 1180 560');
    page.close();
    expect(document.querySelector('.wu-record-compare')).toBeNull();
  });

  it('sets inline only the places the layout computes; its look is the stylesheet\'s', async () => {
    const { root, page } = await opened(finished());
    page.draw(finished({ asking: 'Asking 5 of 24 · $0.0008 of $0.01', focus: 3 }));
    page.draw(finished());
    const placed = new Set(['left', 'top', 'width', 'height']);
    const styled = [...root.querySelectorAll<HTMLElement | SVGElement>('[style]')];
    expect(styled.length).toBeGreaterThan(0);
    for (const part of styled) {
      const properties = Array.from({ length: part.style.length }, (_, index) => part.style.item(index));
      expect(properties.filter(property => !placed.has(property)), part.className.toString()).toEqual([]);
    }
  });

  it('keeps its line rules checked', async () => {
    await expect(import('../../../../tools/previews/world-workspace/' + 'verify-compare-line.mjs')).resolves.toBeDefined();
  });
});

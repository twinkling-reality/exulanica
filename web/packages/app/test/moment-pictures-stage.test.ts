// @vitest-environment happy-dom
// @vitest-environment-options { "url": "http://127.0.0.1/" }
// A version's moment pictures drawn in one kept hidden preview (tools/previews/world-workspace/moment-pictures.ts):
// the first moment loads it, each next moment of that version is asked of it by message, and it is let go after an
// idle wait, on an aborted ask, before another version or a first view is drawn, and where it answers that it cannot
// draw another (the next ask, or that one again, loads a new one). The preview frames here are stand-ins that never
// load: the test answers for them as the preview would.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/composition/world-pictures.ts', () => ({
  FIRST_VIEW_SIZE: [1280, 720],
  mayPutPicture: () => true,
  ownWorldPicture: () => null,
  readServedPictures: async () => undefined,
}));
vi.mock('../src/world-pictures-api.ts', () => ({ HistoryPicturesClient: class {} }));
vi.mock('../src/world-entry-api.ts', () => ({ WorldEntryClient: class { async putPicture() { return undefined; } } }));

const PICTURE = 'exulanica.moment-picture';
const ASK = 'exulanica.moment-ask';
const SCENE_KEY = 'exulanica.moment-scene.v1:';

/** Each preview frame the module made: the address it was given (never loaded) and what was posted to it. */
interface Made { readonly frame: HTMLIFrameElement; src: string | null; readonly posted: { key: string; held: unknown }[] }
let made: Made[] = [];

beforeEach(() => {
  made = [];
  const create = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(((name: string, options?: ElementCreationOptions) => {
    const element = create(name, options);
    if (name !== 'iframe') return element;
    const one: Made = { frame: element as HTMLIFrameElement, src: null, posted: [] };
    // The address is kept, never navigated to: the frame stays blank.
    Object.defineProperty(element, 'src', { get: () => '', set: (value: string) => { one.src = value; } });
    made.push(one);
    return element;
  }) as typeof document.createElement);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetModules();
  document.body.replaceChildren();
  sessionStorage.clear();
});

const entry = (version = 'v1') => ({ entryId: 'e1', worldId: 'w1', authoredVersionId: version } as never);
const moment = (id: string, version = 'v1') => ({ moment_id: id, version_id: version, scene: { people: [{ id: `p-${id}`, position_mm: [0, 0] }] } });
/** What these tests use of the preview module, which sits outside this package. */
interface MomentPictures {
  readonly STAGE_IDLE_MS: number;
  drawMomentPicture(options: { entry: never; moment: ReturnType<typeof moment>; signal?: AbortSignal }): Promise<Blob | null>;
  renderBeginningPicture(options: { entry: never; credentials: never }): Promise<string | null>;
}
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
const pictures = async (): Promise<MomentPictures> => import('../../../../tools/previews/world-workspace/' + 'moment-pictures.ts') as never;
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** The key the frame is asked to draw now: its address's for a first ask, else the last message posted to it. */
function askedKey(one: Made): string {
  if (one.posted.length > 0) return one.posted.at(-1)!.key;
  return new URL(one.src!).searchParams.get('moment')!;
}
function watchPosts(one: Made): void {
  const window = one.frame.contentWindow!;
  vi.spyOn(window, 'postMessage').mockImplementation(((data: { type: string; key: string; held: unknown }) => {
    if (data?.type === ASK) one.posted.push({ key: data.key, held: data.held });
  }) as never);
}
/** The preview `one` answers its current ask: a picture, null, or that it cannot draw another. */
function answer(one: Made, picture: Blob | null, fresh = false): void {
  window.dispatchEvent(new MessageEvent('message', {
    origin: location.origin, source: one.frame.contentWindow, data: { type: PICTURE, key: askedKey(one), picture, ...(fresh ? { fresh } : {}) },
  }));
}
const attached = (one: Made) => one.frame.isConnected;

describe('a version\'s moment pictures in one kept preview', () => {
  it('loads one preview for the first moment and asks each next moment of it by message', async () => {
    const { drawMomentPicture } = await pictures();
    const first = drawMomentPicture({ entry: entry(), moment: moment('m1') });
    await settle();
    expect(made).toHaveLength(1);
    const [stage] = made;
    // The first ask waits where the frame reads it as it loads.
    expect(JSON.parse(sessionStorage.getItem(SCENE_KEY + askedKey(stage!))!)).toEqual({ versionId: 'v1', scene: moment('m1').scene });
    watchPosts(stage!);
    answer(stage!, new Blob(['one']));
    expect(await (await first)?.text()).toBe('one');
    expect(sessionStorage.length).toBe(0);
    expect(attached(stage!)).toBe(true);

    const next = drawMomentPicture({ entry: entry(), moment: moment('m2') });
    await settle();
    expect(made).toHaveLength(1);
    expect(stage!.posted).toEqual([{ key: expect.any(String), held: { versionId: 'v1', scene: moment('m2').scene } }]);
    answer(stage!, new Blob(['two']));
    expect(await (await next)?.text()).toBe('two');
  });

  it('lets the kept preview go after its idle wait, and on an aborted ask; the next moment loads a new one', async () => {
    vi.useFakeTimers();
    const { drawMomentPicture, STAGE_IDLE_MS } = await pictures();
    const first = drawMomentPicture({ entry: entry(), moment: moment('m1') });
    await vi.advanceTimersByTimeAsync(0);
    answer(made[0]!, new Blob(['one']));
    await first;
    await vi.advanceTimersByTimeAsync(STAGE_IDLE_MS - 1);
    expect(attached(made[0]!)).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(attached(made[0]!)).toBe(false);

    const leaving = new AbortController();
    const second = drawMomentPicture({ entry: entry(), moment: moment('m2'), signal: leaving.signal });
    await vi.advanceTimersByTimeAsync(0);
    expect(made).toHaveLength(2);
    leaving.abort();
    expect(await second).toBeNull();
    expect(attached(made[1]!)).toBe(false);

    const third = drawMomentPicture({ entry: entry(), moment: moment('m3') });
    await vi.advanceTimersByTimeAsync(0);
    expect(made).toHaveLength(3);
    expect(new URL(made[2]!.src!).searchParams.get('moment')).toBeTruthy();
    answer(made[2]!, new Blob(['three']));
    expect(await (await third)?.text()).toBe('three');
  });

  it('asks a new preview once where the kept one answers that it cannot draw another', async () => {
    const { drawMomentPicture } = await pictures();
    const first = drawMomentPicture({ entry: entry(), moment: moment('m1') });
    await settle();
    watchPosts(made[0]!);
    answer(made[0]!, new Blob(['one']));
    await first;
    const next = drawMomentPicture({ entry: entry(), moment: moment('m2') });
    await settle();
    answer(made[0]!, null, true);
    await settle();
    expect(attached(made[0]!)).toBe(false);
    expect(made).toHaveLength(2);
    expect(JSON.parse(sessionStorage.getItem(SCENE_KEY + askedKey(made[1]!))!)).toEqual({ versionId: 'v1', scene: moment('m2').scene });
    answer(made[1]!, new Blob(['two']));
    expect(await (await next)?.text()).toBe('two');
  });

  it('never keeps a preview of another version beside the one drawing, nor beside a first view', async () => {
    const { drawMomentPicture, renderBeginningPicture } = await pictures();
    const first = drawMomentPicture({ entry: entry('v1'), moment: moment('m1', 'v1') });
    await settle();
    answer(made[0]!, new Blob(['one']));
    await first;
    const edited = drawMomentPicture({ entry: entry('v2'), moment: moment('m2', 'v2') });
    await settle();
    expect(attached(made[0]!)).toBe(false);
    expect(made).toHaveLength(2);
    answer(made[1]!, new Blob(['two']));
    await edited;

    const began = renderBeginningPicture({ entry: entry('v2'), credentials: {} as never });
    await settle();
    expect(attached(made[1]!)).toBe(false);
    expect(made).toHaveLength(3);
    expect(made[2]!.frame.style.width).toBe('1280px');
    expect(JSON.parse(sessionStorage.getItem(SCENE_KEY + askedKey(made[2]!))!)).toMatchObject({ versionId: 'v2', first: true });
    answer(made[2]!, new Blob(['began']));
    expect(await began).toMatch(/^blob:/u);
  });
});

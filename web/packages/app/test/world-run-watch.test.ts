// @vitest-environment happy-dom
// The running state Run asks under (tools/previews/world-workspace/run-watch.ts). A page opened before its world had
// people read no running state, so the Run question's first limits come from the fallback interval. A start refused
// because they differ from the world's own keeps the world's state, so the next press asks under it and opens; the
// question reads the state again as it opens. The control client and entity-execution.mjs's start are stand-ins.
import { describe, expect, it, vi } from 'vitest';

const server = vi.hoisted(() => ({ control: null as Record<string, unknown> | null, starts: [] as unknown[] }));
vi.mock('../src/society-control-api.ts', () => ({
  SocietyControlClient: class {
    async read() { if (!server.control) throw Object.assign(new Error('no society here'), { code: 'not_found' }); return server.control; }
  },
}));
vi.mock('../../../../tools/previews/world-workspace/entity-execution.mjs', () => ({
  openRun: () => null,
  stopRun: vi.fn(),
  // As startRun does: the world's running state read now, then the limits the run opens under from it.
  startRun: async ({ limitsFor }: { limitsFor: (control: unknown, models: unknown) => unknown }) => {
    server.starts.push(limitsFor(server.control, MODELS));
    return server.control;
  },
}));

const MODELS = { choices: [{ subjectId: 'teo', model: { provider: 'nvidia', modelId: 'nano' } }] };
const runWatch = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'run-watch.ts');
const runWords = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'run-words.mjs');

describe('the running state a run asks under', () => {
  it('opens on the second press after a page opened before the world had people, not never', async () => {
    const { mountRunWatch } = await runWatch();
    const { defaultRunLimits } = await runWords();
    const watch = mountRunWatch({ pill: { run: vi.fn(), runEnded: vi.fn() }, askers: () => [], entry: { worldId: 'w1', authoredVersionId: 'v1' },
      credentials: {}, isCurrent: () => true, readOnly: false, onChange: () => {} });
    await watch.refresh();
    const shown = watch.limits(MODELS);
    expect(shown).toEqual(defaultRunLimits(60_000, 1));
    // People are brought in: the world now plays a minute every 8 s.
    server.control = { versionId: 'v1', hostPlayback: { intervalMs: 8000 }, tickIntervalMs: 8000 };
    const start = (limits: unknown) => watch.start({ subjectId: 'teo', expectedModel: MODELS.choices[0]!.model, shown: limits, modelsClient: {}, refresh: async () => ({}) });
    expect(await start(shown)).toBe('stale_society_state');
    // The positive control: the world's own limits differ from the fallback's.
    expect(watch.limits(MODELS)).toEqual(defaultRunLimits(8000, 1));
    expect(watch.limits(MODELS)).not.toEqual(shown);
    expect(await start(watch.limits(MODELS))).toBeNull();
    expect(server.starts.at(-1)).toEqual(defaultRunLimits(8000, 1));
    watch.dispose();
  });

  it("gives the question the world's limits once it reads the running state again", async () => {
    const { mountRunWatch } = await runWatch();
    const { defaultRunLimits } = await runWords();
    server.control = null;
    const watch = mountRunWatch({ pill: { run: vi.fn(), runEnded: vi.fn() }, askers: () => [], entry: { worldId: 'w1', authoredVersionId: 'v1' },
      credentials: {}, isCurrent: () => true, readOnly: false, onChange: () => {} });
    await watch.refresh();
    expect(watch.limits(MODELS)).toEqual(defaultRunLimits(60_000, 1));
    server.control = { versionId: 'v1', hostPlayback: { intervalMs: 8000 }, tickIntervalMs: 8000 };
    await watch.refresh();
    expect(watch.limits(MODELS)).toEqual(defaultRunLimits(8000, 1));
    watch.dispose();
  });
});

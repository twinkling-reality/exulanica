// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import type { GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import { switchableWorld, type GeneratedWorld } from '../src/composition/generated-world.js';
import { WORLD_LOOK_REDRAW_EVENT, redrawWorldLook, swappableDrawing } from '../src/composition/world-look-redraw.js';
import type { WorldLookChoice } from '../src/world-look.js';

const HOST = {} as GeneratedTileHost;
const TOON = { packId: 'exulanica.toon-town', version: 2, manifestSha256: 'a'.repeat(64) };

/**
 * A world whose tiles log each attach and take-down, and whose relook a test can refuse, or hold
 * until a promise it names for a pack settles.
 */
function fakeWorld(log: string[], held: Readonly<Record<string, Promise<void>>> = {}) {
  const tile = (name: string) => ({
    attach() {
      log.push(`attach ${name}`);
      return { metrics: { lookId: name }, animating: false, dispose: () => log.push(`take down ${name}`) };
    },
  }) as unknown as LoadedGeneratedTile;
  const asked: (string | null)[] = [];
  const sources: string[] = [];
  const choices: WorldLookChoice[] = [];
  const world = {
    tile: tile('first'),
    ground: {},
    look: { pack: 'exulanica.cozy-town', source: 'default', drawn: true, reason: null },
    bodies: () => null,
    async relook(choice: WorldLookChoice) {
      choices.push(choice);
      asked.push(choice.manifestSha256);
      sources.push(choice.source);
      await held[choice.packId ?? ''];
      if (choice.packId === 'exulanica.unreadable') throw new Error('The host serves no style pack exulanica.unreadable');
      return {
        tile: tile(choice.packId ?? 'tile look'),
        bodies: () => ({ body: () => null }),
        look: { pack: choice.packId, source: choice.source, drawn: choice.packId !== null, reason: null },
      };
    },
  } as unknown as GeneratedWorld;
  return { world, asked, sources, choices };
}

describe('redrawing the open world in another pack', () => {
  it('takes the old look down before the new goes up, tells the traffic, and says what it drew', async () => {
    const log: string[] = [];
    const { world, asked } = fakeWorld(log);
    const stated: unknown[] = [];
    const shell = document.createElement('div');
    const mounted = switchableWorld(world, (look) => stated.push(look), shell);
    let told = 0;
    mounted.bodiesChanged(() => { told += 1; });
    const attachment = mounted.tile.attach(HOST);
    const done = await redrawWorldLook(TOON);
    expect(log).toEqual(['attach first', 'take down first', `attach ${TOON.packId}`]);
    expect(asked).toEqual([TOON.manifestSha256]);
    expect(told).toBe(1);
    expect(done).toMatchObject({ pack: TOON.packId, source: 'redraw', drawn: true, reason: null });
    expect(done.elapsedMs).toBeGreaterThanOrEqual(0);
    expect(stated).toEqual([{ pack: TOON.packId, source: 'redraw', drawn: true, reason: null }]);
    // Asked directly, as the Look sheet asks, the redraw states its result on the shell too.
    expect(JSON.parse(shell.getAttribute('data-world-look-redraw') ?? 'null')).toEqual(done);
    expect(mounted.bodies()).not.toBeNull();
    expect(attachment.metrics).toEqual({ lookId: TOON.packId });
    attachment.dispose();
    expect(log.at(-1)).toBe(`take down ${TOON.packId}`);
  });

  it('leaves the world as it was when the pack cannot be read, and says why', async () => {
    const log: string[] = [];
    const { world } = fakeWorld(log);
    const mounted = switchableWorld(world, () => undefined, document.createElement('div'));
    const attachment = mounted.tile.attach(HOST);
    const done = await redrawWorldLook({ packId: 'exulanica.unreadable', version: 1, manifestSha256: 'b'.repeat(64) });
    expect(done).toMatchObject({ drawn: false, reason: 'The host serves no style pack exulanica.unreadable' });
    expect(log).toEqual(['attach first']);
    attachment.dispose();
  });

  it('draws the redraws in the order they were asked for, and the default for none', async () => {
    const log: string[] = [];
    let release = (): void => undefined;
    const slow = new Promise<void>((resolve) => { release = resolve; });
    const { world, asked, sources } = fakeWorld(log, { [TOON.packId]: slow });
    const mounted = switchableWorld(world, () => undefined, document.createElement('div'));
    const attachment = mounted.tile.attach(HOST);
    const asking = Promise.all([redrawWorldLook(TOON), redrawWorldLook(null)]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    // The second waits for the first, however long the first's pack takes to read.
    expect(asked).toEqual([TOON.manifestSha256]);
    release();
    const [first, second] = await asking;
    expect(first.pack).toBe(TOON.packId);
    expect(second.pack).toBe('exulanica.cozy-town');
    expect(asked).toEqual([TOON.manifestSha256, null]);
    // No pack asks for the default, the one the host lists so.
    expect(sources).toEqual(['redraw', 'default']);
    expect(log).toEqual(['attach first', 'take down first', `attach ${TOON.packId}`, `take down ${TOON.packId}`, 'attach exulanica.cozy-town']);
    attachment.dispose();
  });

  it('is asked by an event on the shell, and is no longer open once the tiles are taken down', async () => {
    const log: string[] = [];
    const { world } = fakeWorld(log);
    const shell = document.createElement('div');
    const states: unknown[] = [];
    const mounted = switchableWorld(world, (look) => states.push(look), shell);
    const attachment = mounted.tile.attach(HOST);
    shell.dispatchEvent(new CustomEvent(WORLD_LOOK_REDRAW_EVENT, { detail: TOON }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(log).toContain(`attach ${TOON.packId}`);
    attachment.dispose();
    const after = await redrawWorldLook(TOON);
    expect(after).toMatchObject({ drawn: false, reason: 'No generated world is open' });
    shell.dispatchEvent(new CustomEvent(WORLD_LOOK_REDRAW_EVENT, { detail: TOON }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(log.filter((line) => line.startsWith('attach')).length).toBe(2);
  });
});

 it('preserves workspace authority when previewing a standalone admitted look', async () => {
  const {world,choices}=fakeWorld([]);
  const mounted=switchableWorld(world,()=>undefined,document.createElement('div'));
  const attachment=mounted.tile.attach(HOST);
  const own={packId:'original.garden',version:4,manifestSha256:'d'.repeat(64),own:{base:null,wearable:true}};
  expect((await redrawWorldLook(own)).drawn).toBe(true);
  expect(choices[0]).toMatchObject({packId:own.packId,manifestSha256:own.manifestSha256,own:true});
  expect(choices[0]).not.toHaveProperty('ownBase');
  attachment.dispose();
 });


it('forwards source selection to the current look attachment and withdraws it on replacement or disposal', async () => {
  type Attachment = ReturnType<ReturnType<typeof swappableDrawing>['attach']>;
  const parts: { current: boolean; calls: number; disposed: boolean }[] = [];
  const drawing = () => ({ attach(): Attachment {
    const state = { current: true, calls: 0, disposed: false };
    parts.push(state);
    return { metrics: {} as Attachment['metrics'],
      sourceCurrent: () => state.current && !state.disposed,
      pickSource: (origin, direction) => {
        expect(origin).toEqual([1, 2, 3]);
        expect(direction).toEqual([0, 0, -1]);
        state.calls += 1;
        return { surface: { instanceId: `gateway-${parts.indexOf(state)}` } as never, distance: 4 };
      },
      dispose: () => { state.disposed = true; },
    };
  } });
  const wrapped = swappableDrawing(drawing(), async () => ({ mount: drawing(),
    look: { pack: TOON.packId, source: 'redraw' as const, drawn: true, reason: null } }),
  next => next.mount, () => undefined, document.createElement('div'));
  const attachment = wrapped.attach(HOST);
  const pick = () => attachment.pickSource?.([1, 2, 3], [0, 0, -1]);
  expect(attachment.sourceCurrent?.()).toBe(true);
  expect(pick()?.surface.instanceId).toBe('gateway-0');
  parts[0]!.current = false;
  expect(attachment.sourceCurrent?.()).toBe(false);
  expect(pick()).toBeNull();
  expect(parts[0]!.calls).toBe(1);
  await redrawWorldLook(TOON);
  expect(parts[0]!.disposed).toBe(true);
  expect(attachment.sourceCurrent?.()).toBe(true);
  expect(pick()?.surface.instanceId).toBe('gateway-1');
  attachment.dispose();
  expect(parts[1]!.disposed).toBe(true);
  expect(attachment.sourceCurrent?.()).toBe(false);
  expect(pick()).toBeNull();
  expect(parts[1]!.calls).toBe(1);
});

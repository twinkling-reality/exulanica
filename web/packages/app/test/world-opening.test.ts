// @vitest-environment happy-dom
// @vitest-environment-options { "url": "http://127.0.0.1/" }
// Opening a world (tools/previews/world-workspace/world-opening.ts): the opening shows on a world's
// own address, and never in a scene preview, the front door's live background, which draws the world
// in an inert frame but never mounts the world view that ends the opening.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Opening { mountOpening(): void; endOpening(): boolean }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const opening = async (): Promise<Opening> => import('../../../../tools/previews/world-workspace/' + 'world-opening.ts') as Promise<Opening>;

afterEach(() => { document.body.replaceChildren(); vi.resetModules(); });

describe('the opening', () => {
  it("shows on a world's own address", async () => {
    history.replaceState(null, '', '/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c');
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).not.toBeNull();
  });

  it.each(['capture=1', 'livePreview=1'])('shows nothing in a scene preview (%s)', async (preview) => {
    history.replaceState(null, '', `/?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c&${preview}`);
    (await opening()).mountOpening();
    expect(document.querySelector('.wu-opening')).toBeNull();
  });
});

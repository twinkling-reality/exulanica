// @vitest-environment happy-dom

/**
 * After another writer changed a saved world's look, its page can restore the saved version.
 *
 * A page that opens a saved world shows the saved version even when the world's live version is
 * another writer's. Version history marks the live one as current, which cannot be restored over
 * itself, marks "your saved version", and selects it, so "Restore selected version" restores it.
 * Before, it marked the saved version current, and every change was refused while its restore was
 * disabled.
 */

import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildOptions } from '../src/ui/options.js';
import { ApiError } from '@exulanica/graph-client';
import { describeWorldStyleFailure, versionHistory } from '../src/composition/appearance.js';
import type { WorldStyleConnection, WorldStyleVersionRecord } from '../src/world-style-api.js';

function view() {
  const onWorldRollback = vi.fn(async () => DEFAULT_PREFERENCES);
  const built = buildOptions({
    preferences: DEFAULT_PREFERENCES,
    onChange: vi.fn(),
    onWorldRollback,
    onClose: vi.fn(),
    onShowControls: vi.fn(),
  });
  document.body.append(built.root);
  return { built, onWorldRollback };
}

const history = (root: HTMLElement) =>
  root.querySelector<HTMLSelectElement>('[aria-label="World design history"]')!;
const restore = (root: HTMLElement) =>
  [...root.querySelectorAll<HTMLButtonElement>('button')]
    .find((button) => button.textContent === 'Restore selected version')!;

describe('version history on a saved world another writer changed', () => {
  it('selects the saved version, says which it is, and lets it be restored', async () => {
    const { built, onWorldRollback } = view();
    built.setWorldAuthority({
      state: 'ready',
      detail: 'Connected.',
      currentVersionId: 'v0',
      revision: 0,
      versions: [
        { versionId: 'v0', label: 'Revision 0 · authored · your saved version', current: false, saved: true },
        { versionId: 'v1', label: 'Revision 1 · user', current: true, saved: false },
      ],
    });

    expect(history(built.root).value).toBe('v0');
    expect(history(built.root).textContent).toContain('your saved version');
    expect(restore(built.root).disabled).toBe(false);
    restore(built.root).click();
    await vi.waitFor(() => expect(onWorldRollback).toHaveBeenCalledWith('v0'));
  });

  it('selects the live version, which cannot be restored over itself, when it is the saved one', () => {
    const { built } = view();
    built.setWorldAuthority({
      state: 'ready',
      detail: 'Connected.',
      currentVersionId: 'v1',
      revision: 1,
      versions: [
        { versionId: 'v0', label: 'Revision 0 · authored', current: false, saved: false },
        { versionId: 'v1', label: 'Revision 1 · user · your saved version', current: true, saved: true },
      ],
    });
    expect(history(built.root).value).toBe('v1');
    expect(restore(built.root).disabled).toBe(true);
  });
});

describe('the version history the page presents', () => {
  const record = (versionId: string, revision: number) => ({
    versionId,
    revision,
    rollbackTargetVersionId: null,
    provenance: null,
    createdAt: '2026-09-10T09:00:00Z',
  }) as unknown as WorldStyleVersionRecord;

  it('marks the live version current and the saved one as yours, apart', () => {
    const versions = versionHistory({
      state: { current: record('v0', 0), currentTopologyDigest: 'topology-a' },
      versions: [record('v0', 0), record('v1', 1)],
      liveVersionId: 'v1',
      savedVersionId: 'v0',
    } as unknown as WorldStyleConnection);

    expect(versions.map(({ versionId, current, saved }) => [versionId, current, saved])).toEqual([
      ['v0', false, true],
      ['v1', true, false],
    ]);
    expect(versions[0]!.label).toContain('your saved version');
    expect(versions[1]!.label).not.toContain('your saved version');
  });
});

describe('a write another lock held', () => {
  it('is said in the page\'s own words, never the server\'s sentence, and not as a look change', () => {
    const server = 'another change held a lock this write needs for more than 2000 ms; nothing was written';
    const words = describeWorldStyleFailure(new ApiError(409, 'busy', server));
    expect(words).toBe('Your world was busy with something else a moment ago, so nothing was saved. Try again.');
    expect(words).not.toContain('2000');
  });
});

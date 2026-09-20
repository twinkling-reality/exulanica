// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { buildWorldEntrySurface } from '../src/composition/world-entry.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

const entry = (overrides: Partial<SavedWorldEntry> = {}): SavedWorldEntry => ({
  entryId: '11111111-1111-4111-8111-111111111111',
  worldId: 'world:family-garden',
  title: 'Family garden',
  sourceKind: 'personal',
  sourceSnapshotId: '55555555-5555-4555-8555-555555555555',
  sourceSnapshotSha256: 'c'.repeat(64),
  authoredScene: null,
  authoredVersionId: '22222222-2222-4222-8222-222222222222',
  authoredStateSha256: 'a'.repeat(64),
  authoredEditSeq: 4,
  currentAuthoredStateSha256: 'a'.repeat(64),
  currentAuthoredEditSeq: 4,
  styleVersionId: '33333333-3333-4333-8333-333333333333',
  revision: 2,
  availability: 'available',
  unavailableReason: null,
  createdAt: '2026-09-19T12:00:00Z',
  updatedAt: '2026-09-19T12:01:00Z',
  ...overrides,
});

const surface = (entries: readonly SavedWorldEntry[]) => buildWorldEntrySurface({
  entries,
  open: vi.fn(async () => undefined),
  adoptLatest: vi.fn(async () => undefined),
});

describe('saved world entry recovery surface', () => {
  it('does not replace an empty catalog with upload or naming onboarding', () => {
    const root = surface([]);
    expect(root.querySelector('h1')?.textContent).toBe('Your world did not open');
    expect(root.textContent).toContain('Nothing was created');
    expect(root.querySelector('input')).toBeNull();
    expect(root.textContent).not.toContain('Upload');
    expect(root.textContent).not.toContain('Create world');
  });

  it('shows a returning user a plain world name without internal identifiers', () => {
    const text = surface([entry()]).textContent ?? '';
    expect(text).toContain('Family garden');
    expect(text).toContain('saved changes and appearance');
    expect(text).not.toContain('world:family-garden');
    expect(text).not.toContain('22222222');
  });

  it('explains deletion and concurrent authored change in actionable language', () => {
    const deleted = surface([entry({
      availability: 'unavailable', unavailableReason: 'source_deleted',
    })]);
    expect(deleted.textContent).toContain('source material was deleted');
    expect((deleted.querySelector('button.world-entry-choice') as HTMLButtonElement).disabled)
      .toBe(true);
    expect(surface([entry({
      availability: 'unavailable', unavailableReason: 'authored_version_changed',
      currentAuthoredStateSha256: 'b'.repeat(64), currentAuthoredEditSeq: 6,
    })]).textContent).toContain('updated elsewhere');
  });

  it('requires acknowledgement and turns a stale recovery into a reload instruction', async () => {
    const root = buildWorldEntrySurface({
      entries: [entry({
        availability: 'unavailable', unavailableReason: 'authored_version_changed',
        currentAuthoredStateSha256: 'b'.repeat(64), currentAuthoredEditSeq: 6,
      })],
      open: vi.fn(async () => undefined),
      adoptLatest: vi.fn(async () => {
        throw new ApiError(409, 'stale_saved_world_entry', 'technical conflict detail');
      }),
    });
    const checkbox = root.querySelector('input[type="checkbox"]') as HTMLInputElement;
    const adopt = [...root.querySelectorAll('button')].find((button) =>
      button.textContent?.includes('Use the latest saved changes'))!;
    expect(adopt.disabled).toBe(true);
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event('change'));
    adopt.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(root.textContent).toContain('Reload to compare the latest changes');
    expect(root.textContent).not.toContain('technical conflict detail');
  });
});

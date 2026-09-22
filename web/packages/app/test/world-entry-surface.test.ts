// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { buildWorldEntrySurface } from '../src/composition/world-entry.js';
import {
  buildWorldOpeningFailure,
  worldOpeningReason,
} from '../src/ui/startup-state.js';
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
  sourceAttachments: [],
  createdAt: '2026-09-19T12:00:00Z',
  updatedAt: '2026-09-19T12:01:00Z',
  ...overrides,
});

const surface = (entries: readonly SavedWorldEntry[]) => buildWorldEntrySurface({
  entries,
  open: vi.fn(async () => undefined),
  adoptLatest: vi.fn(async () => undefined),
});

describe('one world that did not open', () => {
  it('states what happened and offers the one action, without pretending to be a choice', () => {
    const panel = buildWorldOpeningFailure({
      reason: worldOpeningReason(new Error('The saved appearance version could not be opened', {
        cause: new TypeError('Failed to fetch'),
      })),
      retry: vi.fn(async () => undefined),
    });
    expect(panel.querySelector('h1')?.textContent).toBe('Your world did not open');
    // The reason used to be discarded by a bare catch, so this screen said nothing at all.
    expect(panel.textContent).toContain('The server did not answer.');
    // And it is not the wrapped engineering message, which names two things nobody has a model
    // of and repeats the heading in longer words.
    expect(panel.textContent).not.toContain('saved appearance version');
    expect(panel.textContent).not.toContain('Failed to fetch');
    // A list of one is not a choice, and this surface must never wear the chooser's words.
    expect(panel.textContent).not.toContain('Choose');
    expect(panel.querySelectorAll('button')).toHaveLength(1);
    expect(panel.querySelector('button')?.textContent).toBe('Try again');
    // The centred surface the sign-in screen and every other refusal already use, not the
    // reading column a list needs.
    expect(panel.classList.contains('gate')).toBe(true);
    expect(panel.classList.contains('world-entry-gate')).toBe(false);
    // frontier-roadmap.md 1.1: a public surface names the product, never the runtime.
    expect(panel.textContent ?? '').not.toMatch(/\bAtlas\b/u);
  });

  it('offers no button when trying again cannot work', () => {
    const panel = buildWorldOpeningFailure({
      reason: 'Its source material was deleted. The saved record remains, but it cannot be opened.',
      retry: null,
    });
    expect(panel.querySelector('button')).toBeNull();
    expect(panel.textContent).toContain('source material was deleted');
  });

  it('reports a retry that fails again in the line the first reason arrived in', async () => {
    const panel = buildWorldOpeningFailure({
      reason: 'The server did not answer.',
      retry: vi.fn(async () => { throw new TypeError('Failed to fetch'); }),
    });
    const action = panel.querySelector('button')!;
    action.click();
    expect(panel.textContent).toContain('Opening your world');
    await Promise.resolve();
    await Promise.resolve();
    expect(panel.textContent).toContain('The server did not answer.');
    expect((action as HTMLButtonElement).disabled).toBe(false);
  });

  it('adds no line rather than repeating the heading in longer words', () => {
    // A failure the product does not recognise. The heading and the one action already say
    // everything that is known, and a second line saying it again is how a refusal came to say
    // the same thing three times.
    const reason = worldOpeningReason(new Error('the world topology is not configured'));
    expect(reason).toBeNull();
    const panel = buildWorldOpeningFailure({ reason, retry: vi.fn(async () => undefined) });
    expect((panel.querySelector('.gate-note') as HTMLElement).hidden).toBe(true);
    expect(panel.textContent).toBe('Your world did not openTry again');
  });

  it('unwraps the failure rather than reading only the sentence wrapped around it', () => {
    // The positive control for the line above: the same wrapper, with a cause this does know.
    expect(worldOpeningReason(new Error('wrapped', {
      cause: new Error('deeper', { cause: new ApiError(503, 'unavailable', 'no') }),
    }))).toBe('The server did not answer.');
    expect(worldOpeningReason(new ApiError(401, 'unauthenticated', 'no token')))
      .toBe('This session is no longer signed in.');
    // A refusal the server gave a reason for is not a dropped connection, and must not be
    // reported as one.
    expect(worldOpeningReason(new ApiError(409, 'saved_world_conflict', 'no'))).toBeNull();
  });
});

describe('choosing between saved worlds', () => {
  it('says why no world opened by itself, above the choice it still has to ask for', () => {
    const root = buildWorldEntrySurface({
      entries: [entry(), entry({ entryId: '44444444-4444-4444-8444-444444444444' })],
      open: vi.fn(async () => undefined),
      adoptLatest: vi.fn(async () => undefined),
      arrivalFailure: 'The saved appearance version could not be opened.',
    });
    const status = root.querySelector('.world-entry-status') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('The saved appearance version could not be opened.');
  });

  it('keeps the status line out of the way when nothing failed', () => {
    expect((surface([entry()]).querySelector('.world-entry-status') as HTMLElement).hidden)
      .toBe(true);
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

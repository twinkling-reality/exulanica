// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  mountSocietyExperimentResult,
  type MountedSocietyExperimentResult,
} from '../src/composition/society-experiment-result.js';
import type {
  ExperimentRead,
  SocietyExperimentBinding,
  SocietyExperimentReadPort,
} from '../src/society-experiment-api.js';

const versionId = '11111111-1111-4111-8111-111111111111';
const experimentId = '22222222-2222-4222-8222-222222222222';
const attemptId = '33333333-3333-4333-8333-333333333333';
const mounts: MountedSocietyExperimentResult[] = [];

afterEach(() => {
  for (const mounted of mounts.splice(0)) mounted.dispose();
  document.body.replaceChildren();
});

function submit(mounted: MountedSocietyExperimentResult, experiment = experimentId, attempt = attemptId): void {
  const fields = mounted.root.querySelectorAll<HTMLInputElement>('input');
  fields[0]!.value = experiment;
  fields[1]!.value = attempt;
  mounted.root.querySelector<HTMLFormElement>('form')!.dispatchEvent(
    new SubmitEvent('submit', { bubbles: true, cancelable: true }),
  );
}

describe('saved-world society experiment result entry', () => {
  it('fixes the active authored version and reads only the two supplied record identities', async () => {
    const read = vi.fn(async (binding: SocietyExperimentBinding): Promise<ExperimentRead> => ({
      status: 'unavailable', binding, definition: null,
      problem: { code: 'unknown_reference', detail: 'No accessible record has that exact identity.' },
    }));
    const mounted = mountSocietyExperimentResult({
      getVersionId: () => versionId,
      client: { read },
      onClose: vi.fn(),
    });
    mounts.push(mounted);
    document.body.append(mounted.root);
    mounted.setVisible(true);

    expect(mounted.root.textContent).toContain(versionId);
    expect(mounted.root.textContent).toContain('does not list or run experiments');
    expect(mounted.root.querySelector<HTMLInputElement>('input[name=version-id]')).toBeNull();
    submit(mounted);
    await vi.waitFor(() => expect(read).toHaveBeenCalledOnce());

    expect(read).toHaveBeenCalledWith({ versionId, experimentId, attemptId }, expect.any(AbortSignal));
    await vi.waitFor(() => expect(mounted.root.textContent).toContain('No accessible record'));
  });

  it('refuses malformed receipt identities without issuing a read', () => {
    const read = vi.fn();
    const mounted = mountSocietyExperimentResult({
      getVersionId: () => versionId,
      client: { read },
      onClose: vi.fn(),
    });
    mounts.push(mounted);
    document.body.append(mounted.root);
    mounted.setVisible(true);
    submit(mounted, 'experiment-2', attemptId);

    expect(read).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('lowercase UUIDs');
  });

  it('aborts an active read on close and starts with a fresh reader surface when reopened', async () => {
    const signals: AbortSignal[] = [];
    const port: SocietyExperimentReadPort = {
      read: vi.fn((_binding, signal) => {
        if (signal) signals.push(signal);
        return new Promise<ExperimentRead>(() => undefined);
      }),
    };
    let mounted!: MountedSocietyExperimentResult;
    mounted = mountSocietyExperimentResult({
      getVersionId: () => versionId,
      client: port,
      onClose: () => mounted.setVisible(false),
    });
    mounts.push(mounted);
    document.body.append(mounted.root);
    mounted.setVisible(true);
    submit(mounted);
    await vi.waitFor(() => expect(signals).toHaveLength(1));

    mounted.root.querySelector<HTMLButtonElement>('.experiment-result-return')!.click();
    expect(signals[0]!.aborted).toBe(true);
    expect(mounted.root.hidden).toBe(true);
    expect(mounted.root.querySelector('.society-experiment-comparison')).toBeNull();

    mounted.setVisible(true);
    expect(mounted.root.querySelector('.society-experiment-comparison')).not.toBeNull();
    expect(mounted.root.textContent).toContain('No attempt loaded');
  });

  it('reads and displays the active authored version at each open', async () => {
    let activeVersion = versionId;
    const newerVersion = '99999999-9999-4999-8999-999999999999';
    const read = vi.fn(async (binding: SocietyExperimentBinding): Promise<ExperimentRead> => ({
      status: 'unavailable', binding, definition: null,
      problem: { code: 'unknown_reference', detail: 'Fixture unavailable.' },
    }));
    const mounted = mountSocietyExperimentResult({
      getVersionId: () => activeVersion,
      client: { read },
      onClose: vi.fn(),
    });
    mounts.push(mounted);
    document.body.append(mounted.root);
    mounted.setVisible(true);
    expect(mounted.root.textContent).toContain(versionId);
    mounted.setVisible(false);

    activeVersion = newerVersion;
    mounted.setVisible(true);
    expect(mounted.root.textContent).toContain(newerVersion);
    expect(mounted.root.textContent).not.toContain(versionId);
    submit(mounted);
    await vi.waitFor(() => expect(read).toHaveBeenCalledOnce());
    expect(read).toHaveBeenCalledWith(
      { versionId: newerVersion, experimentId, attemptId },
      expect.any(AbortSignal),
    );
  });
});

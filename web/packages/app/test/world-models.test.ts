// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { mountSocietyModels } from '../src/composition/society-models-mount.js';
import { signalChoiceWords } from '../src/ui/world-signals-models.js';
import { parseWorldModels, type WorldModelsClient } from '../src/world-models-api.js';

const served = () => parseWorldModels({
  profile: 'exulanica.world-models/v1', clock_second: 100,
  roles: [
    { key: 'society_decision', subject: 'person', label: 'People', available: false, view: null },
    {
      key: 'junction_signal', subject: 'signal', label: 'Traffic lights', available: true,
      reason: null, host_refusal: null, model_subjects_maximum: 2,
      subjects: [{ signal_id: 'signal-a', junction_id: 'junction-a', label: 'High street crossing 1' }],
      models: [{ provider: 'nebius', model_id: 'model-a', name: 'Model A', description: 'A model', mechanism: 'tool_call', refusal: null }],
      choices: [{ subject_id: 'signal-a', choice_seq: 1, model: null, effective_second: 120,
        active_second: null, running_model: null, running_choice_seq: null,
        status: 'pending', refusal: null }],
    },
  ],
});

describe('world decision roles', () => {
  it('shows traffic choices even when no society is present and records a role-scoped choice', async () => {
    const read = vi.fn(async () => served());
    const choose = vi.fn(async () => undefined);
    const worldClient = { read, choose } as unknown as WorldModelsClient;
    const mounted = mountSocietyModels({
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      world: { worldId: 'world', versionId: 'version' }, worldClient,
    });
    document.body.append(mounted.root);
    await mounted.refresh(null, []);
    expect(mounted.root.hidden).toBe(false);
    expect(mounted.root.textContent).toContain('Traffic lights');
    expect(mounted.root.textContent).toContain('Fixed timing decides this light');
    const model = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Who decides this traffic light"]');
    const signal = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Traffic light"]');
    expect(model).not.toBeNull();
    signal!.value = 'signal-a';
    model!.value = 'nebius model-a';
    mounted.root.querySelector<HTMLButtonElement>('.world-signal-models button')!.click();
    await vi.waitFor(() => expect(choose).toHaveBeenCalledWith(
      'version', 'junction_signal', ['signal-a'], { provider: 'nebius', modelId: 'model-a' },
    ));
    mounted.dispose();
  });

  it('rejects an unknown choice state', () => {
    expect(() => parseWorldModels({ ...served(), profile: 'other' })).toThrow();
  });

  it('keeps the prior active model named while a replacement is pending', () => {
    const running = { provider: 'nebius', modelId: 'earlier', name: 'Earlier model' };
    const pending = {
      subjectId: 'signal-a', choiceSeq: 2, model: { provider: 'nebius', modelId: 'next', name: 'Next model' },
      effectiveSecond: 120, activeSecond: null, runningModel: running, runningChoiceSeq: 1,
      status: 'pending' as const, refusal: null,
    };
    expect(signalChoiceWords(pending, null)).toContain('Earlier model continues');
    expect(signalChoiceWords({ ...pending, model: null }, null)).toContain('Earlier model continues');
  });
});

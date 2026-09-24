/** Reachable, read-only entry to one existing society experiment attempt. */

import type { TransportOptions } from '@exulanica/graph-client';
import {
  mountSocietyExperimentComparison,
  type MountedSocietyExperimentComparison,
} from './society-experiment-comparison.js';
import type {
  SocietyExperimentBinding,
  SocietyExperimentReadPort,
} from '../society-experiment-api.js';
import { el } from '../ui/dom.js';
import { createModalFocus } from '../ui/modal-focus.js';

export interface SocietyExperimentResultOptions {
  /** The open world, which a recorded result is read in. */
  readonly getWorldId: () => string | null;
  readonly getVersionId: () => string | null;
  readonly credentials?: TransportOptions;
  readonly client?: SocietyExperimentReadPort;
  readonly onClose: () => void;
}

export interface MountedSocietyExperimentResult {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
  dispose(): void;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const STYLE = `
.society-experiment-result {
  position: fixed; inset: 1rem; z-index: 60; display: grid; grid-template-rows: auto 1fr;
  max-width: 76rem; margin: auto; color: var(--ink, #202a2f);
  background: var(--atlas-plane, #f5f8f7f2); border: 1px solid var(--edge, #c5cfd2);
  box-shadow: var(--app-shadow, 0 8px 32px #24203324); overflow: hidden;
  font: 400 .875rem/1.5 var(--ui-font-body, system-ui, sans-serif);
}
.society-experiment-result[hidden] { display: none; }
.society-experiment-result * { box-sizing: border-box; }
.experiment-result-head { display: flex; align-items: center; gap: 1rem; padding: .75rem 1rem; border-bottom: 1px solid var(--edge, #c5cfd2); }
.experiment-result-return { min-height: 2.5rem; padding: .5rem .75rem; border: 1px solid var(--edge, #c5cfd2); background: transparent; color: inherit; }
.experiment-result-head strong { font: 600 1rem/1.3 var(--ui-font-display, system-ui, sans-serif); }
.experiment-result-scroll { overflow: auto; padding: clamp(1rem, 3vw, 2rem); }
.experiment-result-open { display: grid; gap: 1rem; max-width: 52rem; margin: 0 auto 1.25rem; padding: 1rem; border: 1px solid var(--edge, #c5cfd2); background: color-mix(in srgb, var(--raised, #fff) 74%, transparent); }
.experiment-result-open h2, .experiment-result-open p { margin: 0; }
.experiment-result-open h2 { font: 500 1.35rem/1.2 var(--ui-font-display, system-ui, sans-serif); }
.experiment-result-open p { color: var(--ink-soft, #4e5d64); }
.experiment-result-version { display: grid; gap: .2rem; }
.experiment-result-version code { overflow-wrap: anywhere; font-size: .78rem; }
.experiment-result-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; padding: 0; border: 0; }
.experiment-result-fields label { display: grid; gap: .3rem; font-weight: 600; }
.experiment-result-fields input { width: 100%; min-height: 2.75rem; padding: .6rem .7rem; border: 1px solid var(--edge, #c5cfd2); background: var(--raised, #fff); color: inherit; font: 400 .78rem/1.3 ui-monospace, SFMono-Regular, Consolas, monospace; }
.experiment-result-open button[type='submit'] { justify-self: start; min-height: 2.75rem; padding: .6rem .9rem; border: 1px solid var(--accent, #40545d); background: var(--accent, #40545d); color: white; font-weight: 600; }
.experiment-result-form-status { color: var(--ink-soft, #4e5d64); }
.experiment-result-read { max-width: 72rem; margin: 0 auto; }
@media (max-width: 44rem) {
  .society-experiment-result { inset: 0; }
  .experiment-result-fields { grid-template-columns: 1fr; }
}
`;

export function mountSocietyExperimentResult(
  options: SocietyExperimentResultOptions,
): MountedSocietyExperimentResult {
  const root = el('section', {
    class: 'society-experiment-result',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': 'society-experiment-result-title',
  });
  root.hidden = true;
  const style = el('style');
  style.textContent = STYLE;
  const close = el('button', {
    type: 'button', class: 'experiment-result-return', text: '← Return',
  });
  close.addEventListener('click', options.onClose);
  const header = el('header', { class: 'experiment-result-head' }, [
    close,
    el('strong', { text: 'Recorded society comparison' }),
  ]);
  const experimentId = el('input', {
    type: 'text', name: 'experiment-id', required: true, autocomplete: 'off',
    spellcheck: 'false', 'aria-label': 'Experiment ID',
  });
  const attemptId = el('input', {
    type: 'text', name: 'attempt-id', required: true, autocomplete: 'off',
    spellcheck: 'false', 'aria-label': 'Attempt ID',
  });
  const formStatus = el('p', {
    class: 'experiment-result-form-status', role: 'status', 'aria-live': 'polite',
  });
  formStatus.hidden = true;
  const version = el('code');
  const submit = el('button', { type: 'submit', text: 'Open recorded comparison' });
  const form = el('form', { class: 'experiment-result-open' }, [
    el('h2', { id: 'society-experiment-result-title', text: 'Open an existing result' }),
    el('p', {
      text: 'This view does not list or run experiments. Paste the two IDs from an existing record receipt.',
    }),
    el('p', { class: 'experiment-result-version' }, [
      el('strong', { text: 'Active authored version' }),
      version,
    ]),
    el('fieldset', { class: 'experiment-result-fields' }, [
      el('label', {}, [el('span', { text: 'Experiment ID' }), experimentId]),
      el('label', {}, [el('span', { text: 'Attempt ID' }), attemptId]),
    ]),
    submit,
    formStatus,
  ]);
  const result = el('div', { class: 'experiment-result-read' });
  const scroll = el('div', { class: 'experiment-result-scroll' }, [form, result]);
  root.append(style, header, scroll);
  const focus = createModalFocus(root, close);
  let comparison: MountedSocietyExperimentComparison | null = null;
  let visible = false;
  let disposed = false;

  const currentVersion = (): string | null => {
    const value = options.getVersionId();
    version.textContent = value ?? 'No active saved-world version';
    submit.disabled = value === null;
    return value;
  };
  currentVersion();

  const ensureComparison = (): MountedSocietyExperimentComparison => {
    if (comparison !== null) return comparison;
    comparison = mountSocietyExperimentComparison({
      parent: result,
      ...(options.client === undefined ? { credentials: options.credentials! } : { client: options.client }),
    });
    return comparison;
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const versionId = currentVersion();
    const worldId = options.getWorldId();
    if (versionId === null || worldId === null) {
      formStatus.textContent = 'Return to an available saved world before opening a recorded result.';
      formStatus.hidden = false;
      return;
    }
    const binding: SocietyExperimentBinding = {
      worldId,
      versionId,
      experimentId: experimentId.value.trim(),
      attemptId: attemptId.value.trim(),
    };
    if (!UUID.test(binding.experimentId) || !UUID.test(binding.attemptId)) {
      formStatus.textContent = 'Enter the lowercase UUIDs printed on the existing record receipt.';
      formStatus.hidden = false;
      return;
    }
    formStatus.hidden = true;
    void ensureComparison().load(binding);
  });
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    options.onClose();
  });

  return {
    root,
    setVisible(next) {
      if (disposed || next === visible) return;
      visible = next;
      if (next) {
        currentVersion();
        ensureComparison();
        focus.setVisible(true);
        return;
      }
      focus.setVisible(false);
      comparison?.dispose();
      comparison = null;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      comparison?.dispose();
      comparison = null;
      root.remove();
    },
  };
}

/**
 * The Companion form bench.
 *
 * frontier-roadmap.md gates genuine 3D Companion depth behind a decision about a renderer, asset
 * provenance, performance and accessibility, and asks for 2D, bounded relief and world-rendered
 * prototypes before that contract is approved. This page is those three prototypes, driven from
 * one set of controls so that what differs on screen is the form and never the content.
 *
 * It decides nothing. It produces the evidence a decision would be made from, and it is a
 * private development surface: no route into it exists from the product, and its result file is
 * written by a dev-server middleware that cannot exist in a build.
 */

import './bench.css';

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  companionAppearanceConfiguration,
  DEFAULT_COMPANION,
  type CompanionAppearanceConfiguration,
  type CompanionOperationalState,
} from '@exulanica/presentation';

import { createFlatForm } from './flat.js';
import { createReliefForm } from './relief.js';
import { createWorldForm } from './world.js';
import { HiddenWindowError, sample, type FrameSample } from './measure.js';
import type { CompanionForm, CompanionFormFactory } from './form.js';

const STATES: readonly CompanionOperationalState[] = [
  'resting', 'attending', 'uncertain', 'working', 'settled',
];

const FACTORIES: readonly CompanionFormFactory[] = [createFlatForm, createReliefForm, createWorldForm];

const el = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Readonly<Record<string, string>> = {},
  children: readonly (Node | string)[] = [],
): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === 'text') node.textContent = value;
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
};

const select = (
  label: string,
  values: readonly string[],
  initial: string,
  onChange: (value: string) => void,
): HTMLElement => {
  const control = el('select', { 'aria-label': label },
    values.map((value) => el('option', { value, text: value })));
  control.value = initial;
  control.addEventListener('change', () => onChange(control.value));
  return el('label', { class: 'bench-control' }, [el('span', { text: label }), control]);
};

function dossierList(form: CompanionForm): HTMLElement {
  const rows: readonly (readonly [string, string])[] = [
    ['Renderer', form.dossier.renderer],
    ['Assets', form.dossier.assets],
    ['Accessibility', form.dossier.accessibility],
    ['Silhouettes', form.dossier.silhouettes],
    ['Working state', form.dossier.workingState],
  ];
  return el('dl', { class: 'bench-dossier' }, rows.flatMap(([term, detail]) => [
    el('dt', { text: term }),
    el('dd', { text: detail }),
  ]));
}

const bench = document.getElementById('bench')!;

let appearance: CompanionAppearanceConfiguration = DEFAULT_COMPANION;
let state: CompanionOperationalState = 'resting';
let body = DEFAULT_COMPANION.bodyVariant;
let color = DEFAULT_COMPANION.colorVariant;
let face = DEFAULT_COMPANION.faceVariant;

const forms = FACTORIES.map((factory) => factory());
const results = new Map<string, FrameSample>();

const push = (): void => {
  appearance = companionAppearanceConfiguration({ body, color, face });
  for (const form of forms) {
    form.setAppearance(appearance);
    form.setState(state);
  }
};

const status = el('p', { class: 'bench-status', role: 'status', text: 'Ready.' });

const controls = el('section', { class: 'bench-controls' }, [
  select('shape', COMPANION_BODY_VARIANTS, body, (value) => {
    body = value as typeof body;
    push();
  }),
  select('colour', COMPANION_COLOR_VARIANTS, color, (value) => {
    color = value as typeof color;
    push();
  }),
  select('expression', COMPANION_FACE_VARIANTS, face, (value) => {
    face = value as typeof face;
    push();
  }),
  select('state', STATES, state, (value) => {
    state = value as CompanionOperationalState;
    push();
  }),
]);

const tiles = el('section', { class: 'bench-tiles' }, forms.map((form) => {
  const readout = el('p', { class: 'bench-readout', text: 'not measured' });
  readout.dataset['form'] = form.dossier.id;
  return el('article', { class: 'bench-tile' }, [
    el('h2', { text: form.dossier.title }),
    el('p', { class: 'bench-summary', text: form.dossier.summary }),
    form.element,
    readout,
    dossierList(form),
  ]);
}));

/**
 * Measure one form at a time, with the other two removed from the document.
 *
 * A page holding three candidates at once measures the page. Each run mounts one form alone,
 * lets it settle, then samples, so the number is attributable to the form rather than to its
 * neighbours.
 */
async function measureAll(seconds: number): Promise<void> {
  status.textContent = 'Measuring. Keep this window in front.';
  const solo = el('section', { class: 'bench-solo' });
  bench.replaceChildren(status, solo);
  try {
    for (const form of forms) {
      solo.replaceChildren(el('h2', { text: form.dossier.title }), form.element);
      form.setAppearance(appearance);
      form.setState(state);
      form.start();
      await new Promise((resolve) => setTimeout(resolve, 900));
      results.set(form.dossier.id, await sample(seconds * 1000));
      form.stop();
    }
    status.textContent = 'Measured.';
  } catch (error) {
    status.textContent = error instanceof HiddenWindowError
      ? 'Refused: the window was hidden, so those frame times would not be measurements.'
      : `Failed: ${String(error)}`;
  } finally {
    mount();
    for (const form of forms) {
      const readout = bench.querySelector<HTMLElement>(`[data-form="${form.dossier.id}"]`);
      const result = results.get(form.dossier.id);
      if (readout !== null && result !== undefined) {
        readout.textContent =
          `${result.meanMs} ms mean · ${result.p95Ms} ms p95 · ${result.onePercentLowFps} fps 1% low`
          + ` · ${result.frames} frames`;
      }
    }
  }
}

async function post(): Promise<void> {
  const summary = {
    profile: 'exulanica.companion-form-bakeoff/v1',
    recordedAt: new Date().toISOString(),
    appearance: { body, color, face, state },
    viewport: { width: innerWidth, height: innerHeight, devicePixelRatio },
    forms: forms.map((form) => ({
      ...form.dossier,
      frame: results.get(form.dossier.id) ?? null,
    })),
  };
  (globalThis as Record<string, unknown>)['exulanicaCompanionForms'] = summary;
  try {
    await fetch('/__forms/result', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(summary, null, 2),
    });
    status.textContent = 'Written to web/companion-form-results/latest.json.';
  } catch {
    status.textContent = 'Not written: the result sink only exists on the dev server.';
  }
}

const actions = el('section', { class: 'bench-actions' }, [
  (() => {
    const button = el('button', { type: 'button', text: 'Measure each form for 6s' });
    button.addEventListener('click', () => void measureAll(6));
    return button;
  })(),
  (() => {
    const button = el('button', { type: 'button', text: 'Write result' });
    button.addEventListener('click', () => void post());
    return button;
  })(),
]);

function mount(): void {
  bench.replaceChildren(
    el('header', { class: 'bench-header' }, [
      el('h1', { text: 'Companion form bake-off' }),
      el('p', {
        text: 'Three prototypes of one identity: flat, bounded relief, and world-rendered. '
          + 'The controls drive all three at once, so what differs is the form. This page decides '
          + 'nothing; it is the evidence a decision would be made from.',
      }),
    ]),
    controls,
    actions,
    status,
    tiles,
  );
}

mount();
push();
for (const form of forms) form.start();

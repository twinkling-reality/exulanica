import { el, replace } from './dom.js';

export type BodyRecipe = Readonly<Record<string, number | string>>;
export type CharacterStep = 'body' | 'face' | 'style' | 'review';
export interface BodyFamily {
  readonly familyId: string;
  readonly label: string;
  readonly presets?: readonly { label: string; recipe: BodyRecipe }[];
  readonly controls: readonly { key: string; label: string; group: string; min: number; max: number; default: number; step: number; unit?: string; lowLabel?: string; highLabel?: string }[];
  readonly choices: readonly { key: string; label: string; default: string; options: readonly { value: string; label: string }[] }[];
}

/** One editable recipe spans body, face and style. Navigation never resets its draft. */
export function buildCharacterBody(onBuild: (recipe: BodyRecipe) => void, onDirty: () => void) {
  const root = el('div', { class: 'character-body' });
  let family: BodyFamily | null = null;
  let draft: Record<string, number | string> = {};
  let step: CharacterStep = 'body';
  let editable = false;
  let available = false;
  const progress = el('p', { class: 'character-fit-status', text: 'Preview up to date' });
  const note = el('p', { text: 'Loading character controls…' });
  const presets = el('div', { class: 'character-body-presets', role: 'group', 'aria-label': 'Starting body' });
  const dimensions = el('div');
  const faceControls = el('div');
  const styleChoices = el('div');
  const sections = {
    body: el('div', {}, [presets, dimensions, el('p', { class: 'character-session-note', text: 'Body fullness changes shape; it is not a weight measurement.' })]),
    face: el('div', {}, [
      el('h3', { text: 'Shape your face' }),
      el('p', { text: 'Your starting body also shapes this face. Adjust its proportions here without switching to a different person.' }),
      faceControls,
      el('div', { class: 'character-likeness-note' }, [el('h3', { text: 'From a photo or camera' }),
        el('p', { text: 'Not available yet. This preview cannot scan your face or fit your likeness from an image.' })]),
    ]),
    style: el('div', {}, [styleChoices]),
  };
  function changed() {
    if (!available) return;
    onDirty();
    onBuild({ ...draft });
  }
  root.append(progress, note, sections.body, sections.face, sections.style);
  function reflectStep() {
    for (const [key, section] of Object.entries(sections)) section.hidden = key !== step;
    root.hidden = step === 'review';
    note.textContent = !available ? 'The local character builder is unavailable. Your existing character remains usable.'
      : !editable ? 'Changing these controls creates an editable person, replacing the premade example in your preview.'
      : { body: 'Choose a starting shape, then adjust your proportions. The preview updates automatically after you pause.',
        face: 'Adjust your face. The preview updates automatically after you pause.',
        style: 'Choose hair and clothing. They fit to your body automatically.', review: '' }[step];
  }
  function reflect() {
    if (!family) return;
    replace(presets, (family.presets?.length ? [el('h3', { text: 'Starting body' }),
      ...family.presets.map(preset => {
        const button = el('button', { type: 'button', text: preset.label, 'aria-pressed': String(Object.entries(preset.recipe).every(([key, value]) => draft[key] === value)) });
        button.addEventListener('click', () => {
          draft = { ...draft, ...preset.recipe }; changed(); reflect();
          [...presets.querySelectorAll('button')].find(item => item.textContent === preset.label)?.focus();
        });
        return button;
      })] : []));
    replace(dimensions, []);
    replace(faceControls, []);
    for (const group of [...new Set(family.controls.map(c => c.group))]) {
      const section = el('fieldset', {}, [el('legend', { text: group === 'Face' ? 'Face proportions' : group })]);
      for (const c of family.controls.filter(c => c.group === group)) {
        const value = el('output', { text: format(c.key) });
        const input = el('input', { type: 'range', min: String(c.min), max: String(c.max), step: String(c.step), value: String(draft[c.key]), 'aria-label': c.label });
        input.addEventListener('input', () => {
          draft[c.key] = Number(input.value); value.textContent = format(c.key); changed();
          const buttons = presets.querySelectorAll('button');
          family?.presets?.forEach((preset, index) => buttons[index]?.setAttribute('aria-pressed', String(Object.entries(preset.recipe).every(([key, v]) => draft[key] === v))));
        });
        section.append(el('label', {}, [el('span', {}, [el('span', { text: c.label }), value]), input,
          ...(c.lowLabel ? [el('small', { text: `${c.lowLabel} → ${c.highLabel}` })] : [])]));
      }
      (group === 'Face' ? faceControls : dimensions).append(section);
    }
    replace(styleChoices, []);
    for (const c of family.choices) {
      const select = el('select', { 'aria-label': c.label }, c.options.map(option => el('option', { value: option.value, text: option.label })));
      select.value = String(draft[c.key]);
      select.addEventListener('change', () => { draft[c.key] = select.value; changed(); });
      styleChoices.append(el('label', {}, [el('span', { text: c.label }), select]));
    }
    reflectStep();
  }
  function format(key: string): string {
    const c = family!.controls.find(item => item.key === key)!;
    return c.unit ? `${draft[key]} ${c.unit}` : `${Math.round(Number(draft[key]) * 100)}`;
  }
  return {
    root, sections,
    setUpdating(updating: boolean, failed = false) {
      progress.textContent = failed ? 'Preview could not update. Your edits are retained.'
        : updating ? 'Updating preview… Previous body shown while fitting.' : 'Preview up to date';
      progress.dataset['updating'] = String(updating);
    },
    acceptPreview() { editable = true; reflectStep(); },
    setStep(next: CharacterStep) { step = next; reflectStep(); },
    setFamily(next: BodyFamily) {
      family = next;
      draft = Object.fromEntries([...next.controls, ...next.choices].map(c => [c.key, c.default]));
      available = true;
      reflect();
    },
    setRecipe(recipe?: BodyRecipe) {
      if (!family) return;
      editable = Boolean(recipe);
      const defaults = Object.fromEntries([...family.controls, ...family.choices].map(c => [c.key, c.default]));
      draft = recipe ? { ...defaults, ...recipe } : defaults;
      reflect();
    },
    setUnavailable() { available = false; reflectStep(); },
  };
}

import { buildCharacterBody, type BodyFamily, type BodyRecipe, type CharacterStep } from './character-body.js';
import type { CharacterLook, CharacterSelection } from '../character-catalog.js';
import { el, replace } from './dom.js';
import { createModalFocus } from './modal-focus.js';

interface CharacterStudioHandlers {
  onSelect?(): void;
  onGenerateBody?(recipe: BodyRecipe): void;
  onClose(): void;
  onPreview(selection: CharacterSelection): void;
  onApply(selection: CharacterSelection): void;
  onRotate(yaw: number): void;
  onZoom(zoom: number): void;
  onMotion(motion: 'idle' | 'walk' | 'run'): void;
  onGestures(enabled: boolean): void;
  onRetry(): void;
}

export function buildCharacterStudio(handlers: CharacterStudioHandlers) {
  const root = el('section', { class: 'character-studio', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'character-title' });
  root.hidden = true;
  const close = el('button', { type: 'button', class: 'character-return', text: '← Return' });
  close.addEventListener('click', handlers.onClose);
  const focus = createModalFocus(root, close);
  const canvas = el('canvas', { class: 'character-stage', 'aria-label': 'Character preview. Use the rotation and zoom controls to inspect your character.' });
  const fitting = el('div', { class: 'character-fitting', 'aria-hidden': 'true' }, [
    el('span', { class: 'character-fitting-pulse', 'aria-hidden': 'true' }),
    el('span', { class: 'character-fitting-copy' }, [
      el('strong', { text: 'Refitting your character' }),
      el('small', { text: 'Your previous body stays visible. Keep adjusting if you like.' }),
    ]),
  ]);
  fitting.hidden = true;
  const status = el('p', { class: 'character-status', role: 'status', 'aria-live': 'polite', text: 'Loading character looks…' });
  const retry = el('button', { type: 'button', text: 'Try again' });
  retry.hidden = true;
  retry.addEventListener('click', handlers.onRetry);
  const lookName = el('h2', { text: 'Your look' });
  const choices = el('div', { class: 'character-look-list' });
  const colors = el('div', { class: 'character-color-list' }, [el('p', { text: 'Colors update immediately on your character.' })]);
  const motion = el('div', { class: 'character-motion-list' });
  const tabs = el('nav', { class: 'character-tabs', 'aria-label': 'Character options' });
  let bodyDirty = false;
  let liveUpdating = false;
  let bodyFailure: string | null = null;
  const body = buildCharacterBody(recipe => handlers.onGenerateBody?.(recipe), () => {
    bodyDirty = true; apply.disabled = true;
    status.textContent = 'Updating your preview… You can keep adjusting.';
  });
  body.sections.style.append(colors);
  const steps = [['body', 'Body'], ['face', 'Face'], ['style', 'Style'], ['review', 'Review']] as const;
  let activeStep: CharacterStep = 'body';
  const tabButtons = new Map<CharacterStep, HTMLButtonElement>();
  const stepTitle = el('p', { class: 'character-eyebrow', text: '1 / 4 · Body' });
  const next = el('button', { type: 'button', class: 'character-next', text: 'Next: Face →' });
  next.addEventListener('click', () => {
    const index = steps.findIndex(([key]) => key === activeStep);
    setStep(steps[Math.min(index + 1, steps.length - 1)]![0]);
    tabButtons.get(activeStep)?.focus();
  });
  function setStep(key: CharacterStep) {
    activeStep = key;
    body.setStep(key);
    motion.hidden = key !== 'review';
    steps.forEach(([name, title], index) => {
      tabButtons.get(name)?.setAttribute('aria-pressed', String(name === key));
      if (name === key) {
        stepTitle.textContent = `${index + 1} / 4 · ${title}`;
        next.hidden = index === steps.length - 1;
        next.textContent = `Next: ${steps[index + 1]?.[1] ?? 'Review'} →`;
      }
    });
  }
  for (const [key, title] of steps) {
    const button = el('button', { type: 'button', text: title, 'aria-pressed': String(key === 'body') });
    tabButtons.set(key, button);
    button.addEventListener('click', () => setStep(key));
    tabs.append(button);
  }
  setStep('body');
  let selection: CharacterSelection | null = null;
  let catalog: readonly CharacterLook[] = [];
  const editing = el('fieldset', { class: 'character-editor' }, [stepTitle, body.root, motion, next]);
  editing.disabled = true;
  const apply = el('button', { type: 'button', class: 'character-apply', text: 'Use in world', disabled: true });
  apply.addEventListener('click', () => { if (selection) handlers.onApply(selection); });
  const reset = el('button', { type: 'button', text: 'Reset colors', disabled: true });
  reset.addEventListener('click', () => {
    if (selection) { selection = { ...selection, appearance: {} }; reflectColors(); handlers.onPreview(selection); }
  });
  body.sections.style.append(reset);
  const source = el('p', { class: 'character-source' });
  const gestures = el('input', { type: 'checkbox', 'aria-label': 'Hand gestures' });
  gestures.checked = true;
  gestures.addEventListener('change', () => handlers.onGestures(gestures.checked));
  const gestureNote = el('p', { class: 'character-session-note', text: 'Reach to open tools in first person.' });
  let gestureAvailable = false;
  let reducedMotion = false;
  function reflectGesture() {
    gestures.disabled = reducedMotion || !gestureAvailable;
    gestureNote.textContent = reducedMotion ? 'Hand gestures are skipped with reduced motion.'
      : gestureAvailable ? 'Reach to open tools in first person.' : 'Hand animation is unavailable. Tools open normally.';
  }
  const motionNote = el('p', { text: 'Inspect your character from every angle and check movement before using it in the world.' });
  motion.append(motionNote);
  const motionButtons = new Map<string, HTMLButtonElement>();
  let activeMotion: 'idle' | 'walk' | 'run' = 'idle';
  for (const name of ['idle', 'walk', 'run'] as const) {
    const button = el('button', { type: 'button', text: { idle: 'Standing', walk: 'Walking', run: 'Running' }[name], 'aria-pressed': String(name === 'idle') });
    button.addEventListener('click', () => {
      activeMotion = name;
      for (const [key, item] of motionButtons) item.setAttribute('aria-pressed', String(key === name));
      handlers.onMotion(name);
    });
    motionButtons.set(name, button);
    motion.append(button);
  }
  const examples = el('details', { class: 'character-examples' }, [
    el('summary', { text: 'Premade examples' }),
    el('p', { text: 'These are separate, complete characters used to test the world. Their names describe their outfits; they are not clothes for your editable character.' }), choices,
  ]);
  motion.append(el('label', { class: 'character-gesture-setting' }, [gestures, el('span', { text: 'Hand gestures' })]), gestureNote, examples);
  const rotation = el('input', { type: 'range', min: '-180', max: '180', value: '0', 'aria-label': 'Rotate character' });
  rotation.addEventListener('input', () => handlers.onRotate(Number(rotation.value) * Math.PI / 180));
  const zoom = el('input', { type: 'range', min: '0.8', max: '1.7', step: '0.05', value: '1', 'aria-label': 'Character zoom' });
  zoom.addEventListener('input', () => handlers.onZoom(Number(zoom.value)));
  let drag: { x: number; yaw: number } | null = null;
  canvas.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    drag = { x: event.clientX, yaw: Number(rotation.value) };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag) return;
    const angle = ((drag.yaw + (event.clientX - drag.x) * .5 + 540) % 360) - 180;
    rotation.value = String(angle);
    handlers.onRotate(angle * Math.PI / 180);
  });
  canvas.addEventListener('lostpointercapture', () => { drag = null; });
  canvas.addEventListener('pointerup', event => { drag = null; if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); });
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); handlers.onClose(); }
  });
  root.append(
    canvas, fitting,
    el('header', { class: 'character-header' }, [
      el('div', {}, [el('p', { class: 'character-eyebrow', text: 'Exulanica / Identity' }), el('h1', { id: 'character-title', text: 'Your character' })]), close,
    ]),
    el('aside', { class: 'character-sidebar' }, [tabs, editing]),
    el('aside', { class: 'character-description' }, [
      el('p', { class: 'character-eyebrow', text: 'Your preview' }), lookName,
      status, retry, apply,
      el('p', { class: 'character-session-note', text: 'For this preview session. Your changes are not saved to an account.' }), source,
    ]),
    el('footer', { class: 'character-preview-controls' }, [
      el('label', {}, [el('span', { text: 'Rotate' }), rotation]),
      el('label', {}, [el('span', { text: 'Zoom' }), zoom]),
      el('span', { text: 'Drag the character to turn' }),
    ]),
  );

  function select(next: CharacterSelection): void {
    handlers.onSelect?.(); liveUpdating = false; bodyFailure = null;
    setFitting(false);
    body.setUpdating(false);
    selection = next;
    bodyDirty = false;
    reflectSelection();
    handlers.onPreview(next);
  }
  function reflectSelection(preserveDraft = false): void {
    const look = catalog.find(item => item.lookId === selection?.lookId);
    if (!look || !selection) return;
    lookName.textContent = look.familyId ? 'Your character' : `${look.label} example`;
    gestureAvailable = Boolean(look.gesture);
    reflectGesture();
    if (preserveDraft) body.acceptPreview();
    else body.setRecipe(look.recipe);
    source.textContent = `Character by ${look.creator} · ${look.license}`;
    for (const button of choices.querySelectorAll<HTMLButtonElement>('button')) button.setAttribute('aria-pressed', String(button.dataset['look'] === look.lookId));
    reflectColors();
  }
  function reflectColors(): void {
    const look = catalog.find(item => item.lookId === selection?.lookId);
    if (!look || !selection) return;
    for (const label of colors.querySelectorAll<HTMLLabelElement>('label[data-slot]')) {
      if (!(label.dataset['slot']! in look.defaultColors)) label.remove();
    }
    for (const [name, color] of Object.entries(look.defaultColors)) {
      const existing = [...colors.querySelectorAll<HTMLLabelElement>('label[data-slot]')].find(label => label.dataset['slot'] === name)?.querySelector('input');
      if (existing) { existing.value = selection.appearance.colors?.[name] ?? color; continue; }
      const input = el('input', { type: 'color', value: selection.appearance.colors?.[name] ?? color, 'aria-label': name.replaceAll('_', ' ') });
      input.addEventListener('input', () => {
        if (!selection) return;
        selection = { ...selection, appearance: { ...selection.appearance, colors: { ...selection.appearance.colors, [name]: input.value } } };
        handlers.onPreview(selection);
      });
      colors.append(el('label', { 'data-slot': name }, [el('span', { text: name.replaceAll('_', ' ') }), input]));
    }
  }
  function reflectChoices() {
    replace(choices, catalog.map(look => {
      const button = el('button', { type: 'button', text: look.familyId ? 'Return to my editable character' : look.label,
        'data-look': look.lookId, 'aria-pressed': String(look.lookId === selection?.lookId) });
      button.addEventListener('click', () => select({ lookId: look.lookId, appearance: {} }));
      return button;
    }));
  }
  function setFitting(updating: boolean) {
    fitting.hidden = !updating;
    canvas.setAttribute('aria-busy', String(updating));
    if (updating) root.dataset['fitting'] = 'true';
    else delete root.dataset['fitting'];
  }
  return {
    root, canvas,
    setBodyUpdating() {
      liveUpdating = true;
      setFitting(true);
      body.setUpdating(true);
      bodyFailure = null;
      bodyDirty = true;
      editing.disabled = false;
      reset.disabled = false;
      apply.disabled = true;
      retry.hidden = true;
      status.textContent = 'Updating your preview… You can keep adjusting.';
    },
    setBodyFamily: (family: BodyFamily) => body.setFamily(family),
    setBodyUnavailable: () => body.setUnavailable(),
    showGenerated(look: CharacterLook) {
      catalog = [...catalog.filter(item => !item.familyId), look];
      const colors = Object.fromEntries(Object.entries(selection?.appearance.colors ?? {}).filter(([name]) => name in look.defaultColors));
      const next = { lookId: look.lookId, appearance: { colors } };
      selection = next;
      bodyDirty = false;
      bodyFailure = null;
      reflectChoices();
      reflectSelection(true);
      handlers.onPreview(next);
    },
    setVisible: (visible: boolean) => focus.setVisible(visible),
    setCatalog(items: readonly CharacterLook[], current: CharacterSelection) {
      catalog = items;
      setFitting(false);
      bodyDirty = false;
      bodyFailure = null;
      selection = current;
      reflectChoices();
      reflectSelection();
    },
    setStatus(text: string, ready: boolean) {
      status.textContent = ready && bodyDirty ? bodyFailure ?? 'Updating your preview… You can keep adjusting.' : text;
      retry.hidden = !(ready && bodyDirty && bodyFailure);
      editing.disabled = !ready && !liveUpdating;
      reset.disabled = !ready && !liveUpdating;
      apply.disabled = !ready || bodyDirty;
      if (ready && !bodyDirty) { liveUpdating = false; setFitting(false); body.setUpdating(false); }
    },
    setFailure(text: string) {
      liveUpdating = false;
      setFitting(false);
      body.setUpdating(false, true);
      bodyFailure = text;
      status.textContent = text;
      retry.hidden = false;
      editing.disabled = catalog.length === 0;
      reset.disabled = true;
      apply.disabled = true;
    },
    setReducedMotion(reduced: boolean) {
      for (const [name, button] of motionButtons) {
        button.disabled = reduced && name !== 'idle';
        button.setAttribute('aria-pressed', String(name === (reduced ? 'idle' : activeMotion)));
      }
      motionNote.textContent = reduced ? 'Motion previews are off while reduced motion is enabled.' : 'Inspect your character from every angle and check movement before using it in the world.';
      reducedMotion = reduced;
      reflectGesture();
    },
    setGestures(enabled: boolean) { gestures.checked = enabled; },
    setGestureAvailable(available: boolean) { gestureAvailable = available; reflectGesture(); },
  };
}

import { buildCharacterBody, type BodyFamily, type BodyRecipe, type CharacterStep } from './character-body.js';
import type { CharacterLook, CharacterSelection } from '../character-catalog.js';
import type { SavedRevision } from '../character-looks-store.js';
import { buildLookEditor } from './character-look-editor.js';
import { sameLook } from '../character-look.js';
import { el, replace } from './dom.js';
import { createModalFocus } from './modal-focus.js';
import type { CharacterCatalog, CharacterLook as PersonLook, DesignedLooks } from '@exulanica/atlas-react/playcanvas';

/** What the person is wearing in people mode: a catalog person, the abstract figure or a premade example. */
export type PeopleChoice =
  | { readonly kind: 'catalog'; readonly look: PersonLook }
  | { readonly kind: 'abstract' }
  | { readonly kind: 'stylized'; readonly selection: CharacterSelection };

interface CharacterStudioHandlers {
  onSelect?(): void;
  onGenerateBody?(recipe: BodyRecipe): void;
  onClose(): void;
  onPreview(selection: CharacterSelection): void;
  onApply(selection: CharacterSelection): void;
  /** People mode: show this catalog person on the stage. */
  onPreviewLook?(look: PersonLook): void;
  /** People mode: wear and save this choice. */
  onApplyChoice?(choice: PeopleChoice): void;
  /** People mode: go back to the default look, or restore a saved revision. */
  onResetLook?(restoreRevision?: number): void;
  onRotate(yaw: number): void;
  onZoom(zoom: number): void;
  onMotion(motion: 'idle' | 'walk' | 'run'): void;
  onGestures(enabled: boolean): void;
  onRetry(): void;
}

export function buildCharacterStudio(handlers: CharacterStudioHandlers) {
  let people: { readonly editor: ReturnType<typeof buildLookEditor>; choice: PeopleChoice; readonly designed: DesignedLooks } | null = null;
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
    // The generated body builder stays out of people mode on every step.
    if (people) body.root.hidden = true;
    reflectPeopleStep(key);
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
  // People mode: catalog looks replace the generated body builder when the catalog is offered.
  const peopleRoot = el('div', { class: 'character-people' });
  peopleRoot.hidden = true;
  const figure = el('div', { class: 'character-look-group', role: 'group', 'aria-label': 'Figure', 'data-control': 'figure' });
  const peopleSteps = { body: el('div'), face: el('div'), style: el('div') };
  peopleRoot.append(figure, peopleSteps.body, peopleSteps.face, peopleSteps.style);
  const history = el('div', { class: 'character-history', role: 'group', 'aria-label': 'Saved looks' });
  history.hidden = true;
  const saveNote = el('p', { class: 'character-session-note', text: 'For this preview session. Your changes are not saved to an account.' });
  function reflectFigure(): void {
    if (!people) return;
    const current = people;
    const button = (label: string, pressed: boolean, choose: () => void) => {
      const node = el('button', { type: 'button', text: label, 'aria-pressed': String(pressed) });
      node.addEventListener('click', choose);
      return node;
    };
    replace(figure, [
      el('h3', { text: 'Figure' }),
      button('A person', current.choice.kind === 'catalog', () => {
        current.choice = { kind: 'catalog', look: current.editor.look };
        reflectFigure();
        handlers.onPreviewLook?.(current.editor.look);
      }),
      button('Abstract figure', current.choice.kind === 'abstract', () => {
        current.choice = { kind: 'abstract' };
        reflectFigure();
        status.textContent = 'The abstract figure has no detail to preview. Use it in the world to see it.';
        apply.disabled = false;
      }),
    ]);
    for (const section of Object.values(peopleSteps)) section.toggleAttribute('inert', current.choice.kind === 'abstract');
  }
  function reflectPeopleName(): void {
    if (!people) return;
    const current = people;
    const designedEntry = current.choice.kind === 'catalog'
      ? current.designed.looks.find((item) => sameLook(item.look, current.editor.look))
      : undefined;
    lookName.textContent = current.choice.kind === 'abstract' ? 'Abstract figure' : designedEntry?.label ?? 'Your person';
  }
  function reflectPeopleStep(key: CharacterStep): void {
    if (!people) return;
    peopleSteps.body.hidden = key !== 'body';
    peopleSteps.face.hidden = key !== 'face';
    peopleSteps.style.hidden = key !== 'style';
    figure.hidden = key !== 'body';
  }
  const editing = el('fieldset', { class: 'character-editor' }, [stepTitle, body.root, peopleRoot, motion, next]);
  editing.disabled = true;
  const apply = el('button', { type: 'button', class: 'character-apply', text: 'Use in world', disabled: true });
  apply.addEventListener('click', () => {
    if (!people) {
      if (selection) handlers.onApply(selection);
      return;
    }
    const choice = people.choice;
    handlers.onApplyChoice?.(choice.kind === 'catalog' ? { kind: 'catalog', look: people.editor.look }
      : choice.kind === 'stylized' && selection ? { kind: 'stylized', selection } : choice);
  });
  // What Use in world does where the world has no third-person view (`setWorldView`).
  const worldUse = el('p', { class: 'character-session-note', hidden: true,
    text: 'This world is seen in first person only. Use in world puts this look on you, but your figure is not shown here.' });
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
  examples.hidden = true;
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
      status, retry, apply, worldUse, saveNote, history, source,
    ]),
    el('footer', { class: 'character-preview-controls' }, [
      el('label', {}, [el('span', { text: 'Rotate' }), rotation]),
      el('label', {}, [el('span', { text: 'Zoom' }), zoom]),
      el('span', { text: 'Drag the character to turn' }),
    ]),
  );

  function select(next: CharacterSelection): void {
    if (people) {
      people.choice = { kind: 'stylized', selection: next };
      reflectFigure();
    }
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
    // Premade examples come only from the development preview; elsewhere there are none to show.
    examples.hidden = catalog.length === 0;
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
    /**
     * Offer catalog people: controls for every declared choice, the abstract figure, and the
     * person's saved revisions. The generated body builder is not shown in this mode.
     */
    setPeople(catalogOfPeople: CharacterCatalog, designed: DesignedLooks, current: PeopleChoice) {
      if (!people) {
        const editor = buildLookEditor(catalogOfPeople, designed, (look) => {
          if (!people) return;
          people.choice = { kind: 'catalog', look };
          reflectFigure();
          reflectPeopleName();
          apply.disabled = true;
          handlers.onPreviewLook?.(look);
        });
        people = { editor, choice: current, designed };
        peopleSteps.body.append(editor.sections.body);
        peopleSteps.face.append(editor.sections.face);
        peopleSteps.style.append(editor.sections.style);
      }
      people.choice = current;
      if (current.kind === 'catalog') people.editor.setLook(current.look);
      body.root.hidden = true;
      peopleRoot.hidden = false;
      source.textContent = 'People from MakeHuman (CC0) with motion from Quaternius (CC0)';
      reflectFigure();
      reflectPeopleName();
      reflectPeopleStep(activeStep);
      editing.disabled = false;
    },
    setSaveNote(text: string) { saveNote.textContent = text; },
    /** Whether the open world shows the person in third person, which is what Use in world opens. */
    setWorldView(thirdPerson: boolean) { worldUse.hidden = thirdPerson; },
    /** Newest first; the first entry is what the person wears now. */
    setHistory(revisions: readonly SavedRevision[]) {
      history.hidden = revisions.length === 0;
      const describe = (entry: SavedRevision) => entry.choice.kind === 'abstract' ? 'Abstract figure'
        : entry.choice.kind === 'stylized' ? 'Premade example'
        : people?.designed.looks.find((item) => entry.choice.kind === 'catalog' && sameLook(item.look, entry.choice.look))?.label ?? 'Your person';
      const reset = el('button', { type: 'button', text: 'Reset to default' });
      reset.addEventListener('click', () => handlers.onResetLook?.());
      replace(history, [
        el('h3', { text: 'Saved looks' }),
        el('ol', {}, revisions.slice(0, 8).map((entry, index) => {
          const when = Number.isFinite(Date.parse(entry.savedAt)) ? new Date(entry.savedAt).toLocaleString() : '';
          const row = el('li', {}, [el('span', { text: `${describe(entry)}${entry.restoredFromRevision ? ' (restored)' : ''}` }), el('small', { text: when })]);
          if (index > 0) {
            const restore = el('button', { type: 'button', text: 'Restore', 'aria-label': `Restore ${describe(entry)} from ${when}` });
            restore.addEventListener('click', () => handlers.onResetLook?.(entry.revision));
            row.append(restore);
          } else row.append(el('small', { text: 'Wearing now' }));
          return row;
        })),
        reset,
      ]);
    },
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
    setPeopleStatus(text: string, ready: boolean) {
      status.textContent = text;
      retry.hidden = true;
      apply.disabled = !ready;
      editing.disabled = false;
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

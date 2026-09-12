import { el } from './dom.js';

const PPM = 1_000_000;
export interface Outline {
  readonly kind: 'polygon';
  readonly points: readonly (readonly number[])[];
}
export interface ManualRegion {
  readonly region_key: string;
  readonly silhouette: Outline;
}
export function validateOutline(outline: Outline): void {
  const points = outline.points;
  if (outline.kind !== 'polygon' || points.length < 3 || points.some(p =>
    p.length !== 2 || p.some(n => !Number.isInteger(n) || n < 0 || n > PPM))) {
    throw new Error('Use image coordinates between 0 and 1000000.');
  }
  const area = points.reduce((sum, p, i) => {
    const next = points[(i + 1) % points.length]!;
    return sum + p[0]! * next[1]! - next[0]! * p[1]!;
  }, 0);
  if (area === 0) throw new Error('The region must cover an area.');
}

/** Convert an object-fit: contain view, excluding its letterbox, to display-space PPM. */
export function imagePoint(x: number, y: number, rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  width: number, height: number): readonly [number, number] | null {
  if (width <= 0 || height <= 0 || rect.width <= 0 || rect.height <= 0) return null;
  const scale = Math.min(rect.width / width, rect.height / height);
  const w = width * scale, h = height * scale;
  const dx = x - rect.left - (rect.width - w) / 2;
  const dy = y - rect.top - (rect.height - h) / 2;
  if (dx < 0 || dy < 0 || dx > w || dy > h) return null;
  return [Math.round(dx / w * PPM), Math.round(dy / h * PPM)];
}
interface Draft {
  values: string[];
  key: string;
  pending: boolean;
  saved: boolean;
  message: string;
  refresh?: () => void;
}
/** Session-owned, bounded by photographs actually opened; no personal data in browser storage. */
export class PersonRegionDrafts {
  readonly entries = new Map<string, Draft>();
}
export interface PersonRegionEditorInput {
  readonly captureId: string;
  readonly correction?: ManualRegion;
  readonly source: { readonly url: string | null; readonly available: boolean; readonly alt: string } | null;
  readonly drafts: PersonRegionDrafts;
  readonly isCurrent: () => boolean;
  readonly onAdd: (region: ManualRegion) => Promise<void>;
}
export function buildPersonRegionEditor(input: PersonRegionEditorInput): HTMLElement {
  const label = input.correction ? 'Correct person outline' : 'Add a missed person';
  const draftId = input.correction ? `${input.captureId}:${input.correction.region_key}` : input.captureId;
  const root = el('section', { class: 'person-region-editor', 'aria-label': label });
  root.dataset.captureId = input.captureId;
  root.append(el('h3', { text: label }), el('p', {
    text: 'Draw a box around the whole visible person, including partial bodies and reflections. '
      + 'This records your review, not the photographed person’s authentication or consent. '
      + 'Drafts stay with this photograph while you switch views; leaving the app loses unsaved drafts.',
  }));
  if (!input.source?.available || input.source.url === null) {
    root.append(el('p', { text: 'An authorized editable photograph is unavailable in this session. No original is fetched separately.' }));
    return root;
  }
  let draft = input.drafts.entries.get(draftId);
  if (input.correction && draft?.saved) draft = undefined;
  if (!draft) {
    const points = input.correction?.silhouette.points;
    const values = points ? [Math.min(...points.map(p => p[0]!)), Math.min(...points.map(p => p[1]!)),
      Math.max(...points.map(p => p[0]!)), Math.max(...points.map(p => p[1]!))].map(String) : ['', '', '', ''];
    draft = { values, key: input.correction?.region_key ?? '', pending: false, saved: false, message: '' };
    input.drafts.entries.set(draftId, draft);
  }
  const state = draft;
  const photo = el('img', { src: input.source.url, alt: input.source.alt, draggable: false });
  const stage = el('div', { class: 'person-region-editor-stage' }, [photo]);
  const box = el('div', { class: 'person-region-editor-box', hidden: true });
  stage.append(box);
  const form = el('form');
  const fields = ['Left', 'Top', 'Right', 'Bottom'].map((name, i) => {
    const field = el('input', { type: 'number', min: '0', max: String(PPM), step: '1',
      'aria-label': `${name} image coordinate`, required: true });
    field.value = state.values[i]!;
    form.append(el('label', {}, [name, field]));
    field.addEventListener('input', () => {
      state.values[i] = field.value; state.key = input.correction?.region_key ?? ''; state.saved = false; draw();
    });
    return field;
  });
  const status = el('p', { role: 'status', 'aria-live': 'polite' });
  const submit = el('button', { type: 'submit', text: 'Save person region' });
  const cancel = el('button', { type: 'button', text: 'Cancel draft' });
  let loaded = false;
  const active = () => root.isConnected && input.isCurrent();
  function draw(): void {
    const [l, t, r, b] = state.values.map(Number);
    const rect = stage.getBoundingClientRect();
    const scale = Math.min(rect.width / photo.naturalWidth, rect.height / photo.naturalHeight);
    const w = photo.naturalWidth * scale, h = photo.naturalHeight * scale;
    box.hidden = state.values.some(v => v === '') || !(r! > l! && b! > t!) || !loaded;
    box.style.left = `${(rect.width - w) / 2 + l! / PPM * w}px`;
    box.style.top = `${(rect.height - h) / 2 + t! / PPM * h}px`;
    box.style.width = `${(r! - l!) / PPM * w}px`;
    box.style.height = `${(b! - t!) / PPM * h}px`;
  }
  function render(): void {
    fields.forEach((f, i) => { f.value = state.values[i]!; f.disabled = state.pending || state.saved; });
    submit.disabled = !loaded || state.pending || state.saved;
    cancel.disabled = state.pending;
    status.textContent = state.message;
    draw();
  }
  state.refresh = render;
  photo.addEventListener('load', () => { loaded = photo.naturalWidth > 0; render(); });
  photo.addEventListener('error', () => {
    loaded = false; state.message = 'The authorized editable view could not load. Your draft is retained.'; render();
  });
  let start: readonly [number, number] | null = null;
  stage.addEventListener('pointerdown', (event) => {
    if (!active() || !loaded || state.pending || state.saved || event.button !== 0) return;
    start = imagePoint(event.clientX, event.clientY, stage.getBoundingClientRect(), photo.naturalWidth, photo.naturalHeight);
    if (start) event.preventDefault();
  });
  stage.addEventListener('pointerup', (event) => {
    if (!start || !active() || state.pending || state.saved) return;
    const end = imagePoint(event.clientX, event.clientY, stage.getBoundingClientRect(), photo.naturalWidth, photo.naturalHeight);
    if (end) {
      state.values = [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
        Math.max(start[0], end[0]), Math.max(start[1], end[1])].map(String);
      state.key = input.correction?.region_key ?? ''; render();
    } else { state.message = 'Finish the box inside the photograph. Your draft is unchanged.'; render(); }
    start = null;
  });
  stage.addEventListener('pointercancel', () => { start = null; });
  cancel.addEventListener('click', () => {
    if (!active() || state.pending) return;
    state.values = ['', '', '', '']; state.key = input.correction?.region_key ?? ''; state.saved = false;
    state.message = 'Draft cleared. Saved regions are unchanged.'; render();
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!active() || !loaded || state.pending || state.saved) return;
    const [l, t, r, b] = state.values.map(Number);
    const silhouette: Outline = { kind: 'polygon', points: [[l!, t!], [r!, t!], [r!, b!], [l!, b!]] };
    try {
      if (state.values.some(v => v.trim() === '') || !(r! > l! && b! > t!)) throw new Error('Enter left < right and top < bottom.');
      validateOutline(silhouette);
    } catch (error) { state.message = (error as Error).message; render(); return; }
    if (!state.key) state.key = [...crypto.getRandomValues(new Uint8Array(32))]
      .map(n => n.toString(16).padStart(2, '0')).join('');
    state.pending = true; state.message = 'Saving this photograph’s region. Switching views does not cancel this request.'; render();
    void input.onAdd({ region_key: state.key, silhouette }).then(() => {
      state.saved = true; state.message = 'Region saved. Reload review to verify it. Cancel draft to draw another.';
    }).catch((error: unknown) => {
      state.message = `${error instanceof Error ? error.message : 'Save failed.'} Draft retained. Reload review before retrying if the result is uncertain.`;
    }).finally(() => { state.pending = false; state.refresh?.(); });
  });
  // Layout is re-read at each gesture; observe only while mounted to avoid retaining old panels.
  const observer = new ResizeObserver(() => draw());
  observer.observe(stage);
  const removal = new MutationObserver(() => {
    if (!root.isConnected) {
      observer.disconnect(); removal.disconnect();
      if (state.refresh === render) delete state.refresh;
    }
  });
  removal.observe(document.body, { childList: true, subtree: true });
  form.append(submit, cancel);
  root.append(stage, el('p', { text: 'Keyboard: enter Left, Top, Right and Bottom from 0 to 1000000 across the image, then Save.' }), form, status);
  render();
  return root;
}

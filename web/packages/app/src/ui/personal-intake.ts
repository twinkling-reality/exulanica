import { el } from './dom.js';
import { HUMAN_ATTESTATION } from '../personal-admission-api.js';

/** Sequential reading groups; callbacks and server receipts still own progress. */
export function buildPersonalIntake() {
  const root = el('details', { class: 'reconstruction-inspector personal-intake' });
  root.style.overflowWrap = 'anywhere';
  const entry = el('summary', { text: 'Upload and review photographs' });
  root.append(entry);
  root.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !root.open || event.target instanceof HTMLSelectElement) return;
    event.preventDefault(); event.stopImmediatePropagation(); root.open = false; entry.focus();
  });
  const controls = el('fieldset');
  controls.style.minWidth = '0';
  let group = el('section', { class: 'intake-step-content' });
  function step(label: string, open = false): void {
    group = el('section', { class: 'intake-step-content' });
    controls.append(el('details', { class: 'intake-step', ...(open ? { open: true } : {}) }, [
      el('summary', { text: label }), group,
    ]));
  }
  step('1. Choose original photographs', true);
  const status = el('p', { role: 'status', 'aria-live': 'polite' });
  function field(label: string, type = 'text'): HTMLInputElement {
    const input = el('input', { type, 'aria-label': label });
    const wrapper = el('label', {}, [label, input]);
    wrapper.style.display = 'block';
    input.style.maxWidth = '100%';
    if (type !== 'checkbox') { input.style.display = 'block'; input.style.width = '100%'; }
    group.append(wrapper);
    return input;
  }
  function button(label: string): HTMLButtonElement {
    const node = el('button', { type: 'button', text: label });
    node.style.whiteSpace = 'normal'; node.style.maxWidth = '100%';
    group.append(node);
    return node;
  }
  group.append(el('h2', { text: 'Original photographs' }), el('p', {
    text: 'Upload originals, authorize detection, then inspect and correct proposals before recording human review. '
      + 'Account authority is separate from each person’s consent.',
  }));
  const files = field('Original HEIC or JPEG photographs', 'file');
  files.multiple = true; files.accept = '.heic,.heif,.jpg,.jpeg,image/heic,image/heif,image/jpeg';
  const upload = button('Upload originals');
  const inventory = el('div', { 'aria-label': 'Saved original photographs' });
  const members = el('p', { role: 'status', 'aria-live': 'polite' });
  group.append(el('p', { text: 'Select up to 200 photographs for this admission. Newly uploaded photographs are selected; '
    + 'saved photographs stay available for review without joining a new admission automatically.' }), members, inventory);
  step('2. Authorize processing');
  const purpose = field('Purpose of this use');
  const authority = field('Your account authority basis');
  const validUntil = field('Authority valid until', 'datetime-local');
  const detect = button('Authorize personal admission and request detection');
  const retry = button('Retry exact interrupted admission');
  retry.hidden = true;
  const retryReview = button('Recover interrupted review request');
  retryReview.hidden = true;
  const receipts = el('div', { 'aria-label': 'Personal admission receipts' });
  const progress = el('p', { role: 'status', 'aria-live': 'polite' });
  step('3. Inspect and review people');
  const reload = button('Reload sources and proposals');
  const source = el('select', { 'aria-label': 'Photograph to review' });
  group.append(receipts, progress, source);
  const originals = field('Reselect exact originals for local review', 'file');
  originals.multiple = true; originals.accept = files.accept;
  group.append(el('p', { text: 'Viewer images may hide people. If needed, reselect the original: its size and digest must match the server. '
    + 'Local originals are never uploaded by this control. An image this browser cannot decode is not an inspection.' }));
  const review = el('div');
  group.append(review);
  const linkedSubject = el('select', { 'aria-label': 'Person to link selected regions to' });
  const selection = el('p', { role: 'status' });
  group.append(linkedSubject, selection);
  const link = button('Link selected regions as one person');
  const reviewChoice = el('select', { 'aria-label': 'Human review of this photograph' });
  reviewChoice.append(el('option', { value: '', text: 'Choose after inspecting the exact photograph' }),
    el('option', { value: 'confirmed-regions', text: 'I reviewed every person region and corrected omissions' }),
    el('option', { value: 'no-person', text: 'I inspected this photograph and it contains no person regions' }));
  group.append(reviewChoice);
  step('4. Confirm review and prepare the world');
  const reviewer = field('Reviewer’s actual name');
  group.append(el('p', { text: 'The inventory in this attestation is the selected admission photographs. '
    + 'Inspect and review every selected original before checking it.' }));
  const attestation = field(HUMAN_ATTESTATION, 'checkbox');
  const complete = button('Record human review and request eligible depth');
  const refreshWorld = button('Refresh world after processing');
  root.append(status, controls);
  return { root, controls, status, files, upload, inventory, members, purpose, authority, validUntil, detect,
    retry, retryReview, receipts, progress, reload, source, review, linkedSubject, selection, link,
    reviewChoice, reviewer, attestation, complete, refreshWorld, originals };
}

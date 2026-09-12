import { el } from './dom.js';
import { HUMAN_ATTESTATION } from '../personal-admission-api.js';

/** Minimal controls in the existing inspector style; callbacks own every request. */
export function buildPersonalIntake() {
  const root = el('details', { class: 'reconstruction-inspector personal-intake' });
  root.style.overflowWrap = 'anywhere';
  root.append(el('summary', { text: 'Upload and review photographs' }));
  const controls = el('fieldset');
  controls.style.minWidth = '0';
  const status = el('p', { role: 'status', 'aria-live': 'polite' });
  function field(label: string, type = 'text'): HTMLInputElement {
    const input = el('input', { type, 'aria-label': label });
    const wrapper = el('label', {}, [label, input]);
    wrapper.style.display = 'block';
    input.style.maxWidth = '100%';
    if (type !== 'checkbox') { input.style.display = 'block'; input.style.width = '100%'; }
    controls.append(wrapper);
    return input;
  }
  function button(label: string): HTMLButtonElement {
    const node = el('button', { type: 'button', text: label });
    node.style.whiteSpace = 'normal'; node.style.maxWidth = '100%';
    controls.append(node);
    return node;
  }
  controls.append(el('h2', { text: 'Original photographs' }), el('p', {
    text: 'Upload originals, authorize detection, then inspect and correct proposals before recording human review. '
      + 'Account authority is separate from each person’s consent.',
  }));
  const files = field('Original HEIC or JPEG photographs', 'file');
  files.multiple = true; files.accept = '.heic,.heif,.jpg,.jpeg,image/heic,image/heif,image/jpeg';
  const upload = button('Upload originals');
  const inventory = el('div', { 'aria-label': 'Upload receipts' });
  controls.append(inventory);
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
  const reload = button('Reload sources and proposals');
  const source = el('select', { 'aria-label': 'Photograph to review' });
  controls.append(receipts, progress, source);
  const originals = field('Reselect exact originals for local review', 'file');
  originals.multiple = true; originals.accept = files.accept;
  controls.append(el('p', { text: 'Viewer images may hide people. If needed, reselect the original: its size and digest must match the server. '
    + 'Local originals are never uploaded by this control. An image this browser cannot decode is not an inspection.' }));
  const review = el('div');
  controls.append(review);
  const linkedSubject = el('select', { 'aria-label': 'Person to link selected regions to' });
  const selection = el('p', { role: 'status' });
  controls.append(linkedSubject, selection);
  const link = button('Link selected regions as one person');
  const reviewChoice = el('select', { 'aria-label': 'Human review of this photograph' });
  reviewChoice.append(el('option', { value: '', text: 'Choose after inspecting the exact photograph' }),
    el('option', { value: 'confirmed-regions', text: 'I reviewed every person region and corrected omissions' }),
    el('option', { value: 'no-person', text: 'I inspected this photograph and it contains no person regions' }));
  controls.append(reviewChoice);
  const reviewer = field('Reviewer’s actual name');
  const attestation = field(HUMAN_ATTESTATION, 'checkbox');
  const complete = button('Record human review and request eligible depth');
  const refreshWorld = button('Refresh world after processing');
  root.append(controls, status);
  return { root, controls, status, files, upload, inventory, purpose, authority, validUntil, detect,
    retry, retryReview, receipts, progress, reload, source, review, linkedSubject, selection, link,
    reviewChoice, reviewer, attestation, complete, refreshWorld, originals };
}

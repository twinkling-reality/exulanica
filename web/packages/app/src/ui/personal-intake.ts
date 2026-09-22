import { el } from './dom.js';
import { DEPTH_MODEL_NOTICE, HUMAN_ATTESTATION } from '../personal-admission-api.js';

/** Sequential reading groups; callbacks and server receipts still own progress. */
export function buildPersonalIntake() {
  const root = el('section', {
    class: 'reconstruction-inspector personal-intake',
    'aria-label': 'World photos',
  });
  root.style.overflowWrap = 'anywhere';
  const status = el('p', { role: 'status', 'aria-live': 'polite' });
  const attachedReferences = el('div', {
    class: 'photo-reference-grid', 'aria-label': 'Attached reference photographs',
  });
  const referenceCount = el('span', { class: 'photo-reference-count', text: '0 photos' });
  const attachmentStatus = el('p', {
    class: 'photo-attachment-status', role: 'status', 'aria-live': 'polite',
  });
  const worldAction = el('button', {
    type: 'button', class: 'photo-attach-action', text: 'Refresh world after processing',
  });
  const retryAttachment = el('button', {
    type: 'button', class: 'photo-attachment-retry', text: 'Retry exact interrupted attachment',
  });
  retryAttachment.hidden = true;
  const retryMembership = el('button', {
    type: 'button', class: 'photo-membership-retry', text: 'Retry the interrupted photo change',
  });
  retryMembership.hidden = true;
  // Outcomes of removing and adding back, in words; a stable code only inside Details.
  const referenceNotice = el('div', {
    class: 'photo-reference-notice', role: 'status', 'aria-live': 'polite',
  });
  const readyReferences = el('div', {
    class: 'photo-reference-grid', 'aria-label': 'Reviewed photographs ready to add',
  });
  const ready = el('section', { class: 'photo-ready', 'aria-labelledby': 'photo-ready-title' }, [
    el('h4', { id: 'photo-ready-title', text: 'Ready to add' }),
    readyReferences,
  ]);
  ready.hidden = true;
  const previousReferences = el('div', {
    class: 'photo-reference-grid', 'aria-label': 'Photographs previously in this world',
  });
  const previous = el('section', {
    class: 'photo-previous', 'aria-labelledby': 'photo-previous-title',
  }, [
    el('h4', { id: 'photo-previous-title', text: 'Previously in this world' }),
    el('p', { class: 'photo-previous-intro', text:
      'These photos stay in your library. Adding one back needs a new review first.' }),
    previousReferences,
  ]);
  previous.hidden = true;
  const collection = el('section', { class: 'photo-collection', 'aria-labelledby': 'photo-collection-title' }, [
    el('header', { class: 'photo-collection-header' }, [
      el('div', {}, [
        el('p', { class: 'overlay-kicker', text: 'This world' }),
        el('h3', { id: 'photo-collection-title', text: 'Reference photos' }),
      ]),
      referenceCount,
    ]),
    el('p', { class: 'photo-collection-intro', text:
      'Keep reviewed photos with this project as references. Attaching a photo does not create scene geometry.' }),
    attachedReferences,
    referenceNotice,
    ready,
    previous,
    attachmentStatus,
    el('div', { class: 'photo-collection-actions' }, [worldAction, retryAttachment, retryMembership]),
  ]);
  const workflow = el('details', { class: 'photo-review-workflow' });
  const entry = el('summary', { text: 'Add or review photos' });
  workflow.append(entry);
  workflow.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !workflow.open || event.target instanceof HTMLSelectElement) return;
    event.preventDefault(); event.stopImmediatePropagation(); workflow.open = false; entry.focus();
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
  // A second, separate decision. Unticked, and never implied by the review above: a person who
  // said "I looked at this photograph and these are the people in it" has said nothing about
  // whether a depth network may read the same pixels.
  const depthConsent = field('Estimate 3D shape from these photos', 'checkbox');
  const depthTerm = el('p', { class: 'depth-consent-term' });
  group.append(el('p', { class: 'depth-consent-notice', text: DEPTH_MODEL_NOTICE }), depthTerm);
  const complete = button('Record human review');
  workflow.append(controls);
  root.append(collection, status, workflow);
  return { root, controls, status, files, upload, inventory, members, purpose, authority, validUntil, detect,
    retry, retryReview, receipts, progress, reload, source, review, linkedSubject, selection, link,
    reviewChoice, reviewer, attestation, depthConsent, depthTerm, complete, attachedReferences, referenceCount,
    attachmentStatus, worldAction, retryAttachment, originals, workflow, referenceNotice,
    ready, readyReferences, previous, previousReferences, retryMembership };
}

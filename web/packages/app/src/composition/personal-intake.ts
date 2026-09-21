/** Mounted source-first journey. Server state remains authoritative after every mutation. */
import { formationLabel } from '@exulanica/formation';
import { ApiError, type GraphSnapshot, type TransportOptions } from '@exulanica/graph-client';
import type { SourceMediaCatalog } from '@exulanica/atlas-react/playcanvas';
import { PersonalAdmissionApi, HUMAN_ATTESTATION, sha256,
  type PersonalSource, type PersonalAdmission, type AdmissionResult } from '../personal-admission-api.js';
import { PersonReviewApi, type PersonReview } from '../person-review-api.js';
import { listBatches, watchBatch } from '../formation.js';
import { SourceMediaClient } from '../source-media-api.js';
import { buildPersonalIntake } from '../ui/personal-intake.js';
import { buildPersonReview } from '../ui/person-review.js';
import { PersonRegionDrafts, type ManualRegion } from '../ui/person-region-editor.js';
import { el, replace } from '../ui/dom.js';
import type {
  SavedWorldEntry,
  SourceAttachmentRequest,
} from '../world-entry-api.js';

interface Journal {
  sources: PersonalSource[];
  memberIds: string[];
  pending: PersonalAdmission | null;
  result: AdmissionResult | null;
}
export interface PersonalIntakeSession {
  dispose: (() => void) | null;
  drafts: PersonRegionDrafts;
}
export function createPersonalIntakeSession(): PersonalIntakeSession {
  return { dispose: null, drafts: new PersonRegionDrafts() };
}
export function mountPersonalIntake(deps: {
  credentials: TransportOptions;
  preview?: boolean;
  session: PersonalIntakeSession;
  snapshot: GraphSnapshot;
  media: SourceMediaCatalog | undefined;
  reloadSnapshot: () => Promise<GraphSnapshot>;
  refreshWorld: () => Promise<void>;
  getEntry?: () => SavedWorldEntry | null;
  attachSources?: (request: SourceAttachmentRequest) => Promise<SavedWorldEntry>;
  refreshEntry?: (entryId: string) => Promise<SavedWorldEntry>;
  storage?: Storage;
}) {
  deps.session.dispose?.();
  const ui = buildPersonalIntake();
  const api = new PersonalAdmissionApi(deps.credentials);
  const reviewApi = new PersonReviewApi(deps.credentials);
  let storage: Storage | null = deps.storage ?? null;
  try { storage ??= window.sessionStorage; } catch { /* Server review still loads in restricted browsers. */ }
  let journal: Journal = {
    sources: [], memberIds: [], pending: null, result: null,
  };
  let receiptHistory: AdmissionResult[] = [];
  let storageKey = '';
  let current = deps.snapshot;
  let entry = deps.getEntry?.() ?? null;
  const getEntry = (): SavedWorldEntry | null =>
    deps.getEntry === undefined ? entry : deps.getEntry();
  let pendingAttachment: SourceAttachmentRequest | null = null;
  let attachmentStorageKey = '';
  let media = deps.media;
  let ownMedia: Awaited<ReturnType<SourceMediaClient['load']>> | null = null;
  let disposed = false;
  let busy = false;
  let generation = 0;
  let stopWatch: (() => void) | null = null;
  const selected = new Map<string, { capture_id: string; region_key: string }>();
  const reviews = new Map<string, PersonReview>();
  const choices = new Map<string, 'no-person' | 'confirmed-regions'>();
  let correction: ManualRegion | undefined;
  const localOriginals = new Map<string, string>();
  const inspected = new Set<string>();
  const say = (text: string) => { if (!disposed) ui.status.textContent = text; };

  const attachmentSelection = (): {
    readonly selectedCount: number;
    readonly sources: SourceAttachmentRequest['sources'];
    readonly attachedCount: number;
    readonly refusedCount: number;
  } => {
    const active = getEntry();
    if (active === null) {
      return { selectedCount: 0, sources: [], attachedCount: 0, refusedCount: 0 };
    }
    const eligible = new Set(receiptHistory.flatMap((result) => result.receipts
      .filter((receipt) => receipt.eligibility_state === 'eligible')
      .map((receipt) => receipt.capture_id)));
    const attached = new Set(active.sourceAttachments.map((attachment) => attachment.captureId));
    const reviewSources = new Map((current.reviewSources ?? []).map((source) => [
      source.captureId, source,
    ]));
    const sources: SourceAttachmentRequest['sources'][number][] = [];
    let attachedCount = 0;
    let refusedCount = 0;
    for (const captureId of journal.memberIds) {
      if (attached.has(captureId)) {
        attachedCount += 1;
        continue;
      }
      const source = reviewSources.get(captureId);
      if (source === undefined || !eligible.has(captureId) || source.state !== 'available') {
        refusedCount += 1;
        continue;
      }
      sources.push(Object.freeze({
        captureId: source.captureId,
        evidenceSpanId: source.evidenceSpanId,
      }));
    }
    return Object.freeze({
      selectedCount: journal.memberIds.length,
      sources: Object.freeze(sources),
      attachedCount,
      refusedCount,
    });
  };

  const unavailableAttachment = (reason: string | null): string => ({
    source_unavailable: 'Source unavailable',
    authorization_expired: 'Authorization expired',
    screening_expired: 'Human review expired',
    viewer_unavailable: 'Authorized viewer unavailable',
  })[reason ?? ''] ?? 'Reference unavailable';

  function renderAttachments(): void {
    if (entry === null) {
      ui.referenceCount.textContent = 'No world open';
      replace(ui.attachedReferences, [el('p', {
        text: 'Open a saved world to keep reviewed photographs with that project.',
      })]);
      return;
    }
    ui.referenceCount.textContent = `${entry.sourceAttachments.length} ` +
      `photo${entry.sourceAttachments.length === 1 ? '' : 's'}`;
    if (entry.sourceAttachments.length === 0) {
      replace(ui.attachedReferences, [el('p', { class: 'photo-collection-empty',
        text: 'No reference photos yet. Add or review photos, then select eligible photos to keep with this world.',
      })]);
      return;
    }
    replace(ui.attachedReferences, entry.sourceAttachments.map((attachment, index) => {
      const descriptor = media?.get(attachment.evidenceSpanId) ?? media?.get(attachment.captureId);
      const canShow = attachment.availability === 'available' &&
        descriptor?.available === true && descriptor.url !== null;
      return el('article', { class: 'attached-reference' }, [
        el('strong', { text: `Reference photograph ${index + 1}` }),
        el('span', {
          text: attachment.availability === 'available'
            ? 'Attached reference'
            : unavailableAttachment(attachment.unavailableReason),
        }),
        ...(canShow ? [el('img', { src: descriptor.url!, alt: descriptor.alt })] : []),
        el('details', {}, [
          el('summary', { text: 'Reference lineage' }),
          el('p', {
            text: `Capture ${attachment.captureId}; evidence ${attachment.evidenceSpanId}; ` +
              `original SHA-256 ${attachment.sourceSha256}.`,
          }),
        ]),
      ]);
    }));
  }

  function persist(): void {
    try {
      if (!storage) throw new Error('Storage unavailable');
      storage.setItem(storageKey, JSON.stringify(journal));
    }
    catch { say('Browser recovery storage is unavailable. Keep this page open for exact request retry.'); }
  }
  function persistAttachment(): void {
    if (attachmentStorageKey.length === 0) return;
    try {
      if (!storage) throw new Error('Storage unavailable');
      if (pendingAttachment === null) storage.removeItem(attachmentStorageKey);
      else storage.setItem(attachmentStorageKey, JSON.stringify(pendingAttachment));
    } catch {
      say('Browser recovery storage is unavailable. Keep this page open for exact attachment retry.');
    }
  }
  function reflect(): void {
    ui.controls.disabled = busy || deps.preview === true;
    ui.retry.hidden = journal.pending === null;
    const attachment = attachmentSelection();
    ui.retryAttachment.hidden = pendingAttachment === null;
    ui.worldAction.textContent = entry === null ? 'Refresh world after processing'
      : attachment.sources.length > 0
        ? `Attach ${attachment.sources.length} selected ` +
          `photo${attachment.sources.length === 1 ? '' : 's'}`
        : attachment.attachedCount > 0 && attachment.refusedCount === 0
          ? 'Selected photos already attached'
          : 'Attach selected photos';
    ui.worldAction.disabled = entry === null
      ? busy || deps.preview === true
      : busy || deps.preview === true || pendingAttachment !== null ||
        attachment.sources.length === 0;

    ui.upload.disabled = ui.detect.disabled = ui.complete.disabled = journal.pending !== null;
    ui.selection.textContent = `${selected.size} region(s) explicitly selected across photographs.`;
    ui.members.textContent = `${journal.memberIds.length} of ${journal.sources.length} saved ` +
      'photographs selected for this admission (maximum 200).';
    ui.attachmentStatus.textContent = getEntry() === null
      ? 'Finish processing, then refresh the world to use reviewed photos.'
      : attachment.selectedCount === 0
        ? 'Open Add or review photos and select reviewed photos to attach.'
        : [
            attachment.sources.length > 0
              ? `${attachment.sources.length} ready to attach`
              : '',
            attachment.attachedCount > 0
              ? `${attachment.attachedCount} already in this world`
              : '',
            attachment.refusedCount > 0
              ? `${attachment.refusedCount} ${attachment.refusedCount === 1 ? 'needs' : 'need'} ` +
                'completed review or current viewer access'
              : '',
          ].filter(Boolean).join(' · ') + '.';
    replace(ui.inventory, journal.sources.map((source, index) => {
      const checkbox = el('input', { type: 'checkbox', 'aria-label': `Include photograph ${index + 1} in this admission` });
      checkbox.checked = journal.memberIds.includes(source.capture_id);
      checkbox.disabled = journal.pending !== null;
      checkbox.onchange = () => {
        if (checkbox.checked && journal.memberIds.length >= 200) {
          checkbox.checked = false; say('An admission can contain at most 200 photographs. Deselect a photograph first.'); return;
        }
        journal.memberIds = checkbox.checked ? [...journal.memberIds, source.capture_id]
          : journal.memberIds.filter(id => id !== source.capture_id);
        ui.attestation.checked = false; persist(); reflect();
      };
      return el('div', { class: 'intake-original' }, [
        el('label', {}, [checkbox, ` Original ${index + 1} · ${(source.bytes / 1_000_000).toFixed(2)} MB`]),
        el('details', {}, [el('summary', { text: 'File identity' }),
          el('p', { text: `${source.bytes} bytes; SHA-256 ${source.sha256}; capture ${source.capture_id}` })]),
      ]);
    }));
    replace(ui.receipts, receiptHistory.flatMap(result => [el('p', { text: `Saved admission ${result.batch_id}` }),
      ...result.receipts.map(receipt => el('p', {
      text: `Capture ${receipt.capture_id}: ${receipt.eligibility_state}. Authorization ${receipt.authorization_id}; screening ${receipt.screening_id}. Queued work is not completed depth.`,
    }))]));
    renderAttachments();
  }
  async function act(run: () => Promise<void>): Promise<void> {
    if (busy || disposed || deps.preview === true) return;
    busy = true; reflect();
    try { await run(); }
    catch (error) { say(error instanceof Error ? error.message : 'The request did not complete.'); }
    finally {
      busy = false;
      if (!disposed) {
        const pending = await reviewApi.requests.pending();
        ui.retryReview.hidden = !pending || pending.path === '/personal-admission';
        reflect();
      }
    }
  }
  function watch(batch: string): void {
    stopWatch?.();
    stopWatch = watchBatch(deps.credentials, batch, state => {
      if (disposed) return;
      const label = formationLabel(state);
      ui.progress.textContent = [label.stage, label.headline, ...label.detail, label.note].filter(Boolean).join(' ');
    });
  }
  function sourceOptions(): void {
    const prior = ui.source.value;
    replace(ui.source, (current.reviewSources ?? []).map((source, i) => el('option', {
      value: source.captureId, text: `Photograph ${i + 1}${source.state === 'available' ? '' : ' (viewer unavailable)'}`,
    })));
    if ([...ui.source.options].some(o => o.value === prior)) ui.source.value = prior;
    const subject = ui.linkedSubject.value;
    const ids = [...new Set([...reviews.values()].flatMap(r => r.regions.flatMap(p => p.subjectId ? [p.subjectId] : [])))];
    replace(ui.linkedSubject, [el('option', { value: '', text: 'Use selected person, or create one if unlinked' }),
      ...ids.map((id, i) => el('option', { value: id, text: `Person ${i + 1} (${id})` }))]);
    ui.linkedSubject.value = ids.includes(subject) ? subject : '';
  }
  async function reload(): Promise<void> {
    const snapshot = await deps.reloadSnapshot();
    if (disposed) return;
    current = snapshot;
    const ids = new Set((current.reviewSources ?? []).map(s => s.captureId));
    // Local retry metadata cannot resurrect a capture absent from the server's current inventory.
    journal.sources = journal.sources.filter(s => ids.has(s.capture_id));
    for (const [id, url] of localOriginals) {
      if (!ids.has(id)) { URL.revokeObjectURL(url); localOriginals.delete(id); inspected.delete(id); }
    }
    const loaded = await Promise.all([...ids].map(id => reviewApi.load(id)));
    if (disposed) return;
    for (const review of loaded) {
      if (JSON.stringify(reviews.get(review.captureId)) !== JSON.stringify(review)) {
        choices.delete(review.captureId); ui.attestation.checked = false;
      }
    }
    reviews.clear(); loaded.forEach(r => reviews.set(r.captureId, r));
    for (const [key, ref] of selected) {
      if (!reviews.get(ref.capture_id)?.regions.some(r => r.regionKey === ref.region_key)) selected.delete(key);
    }
    ownMedia?.dispose(); ownMedia = null; media = undefined;
    try {
      // Review uses the workspace inventory and its evidence spans. It does not need a default
      // composed world's slot aliases, which an authored starter deliberately does not define.
      const next = await new SourceMediaClient(deps.credentials).load(
        '#777777',
        { includeWorldTopology: false },
      );
      if (disposed) { next.dispose(); return; }
      ownMedia = next; media = next.catalog;
    } catch { say('Current authorized viewer bytes are unavailable. Saved review is retained; no original fallback is used.'); }
    const activeEntry = getEntry();
    if (activeEntry !== null && deps.refreshEntry !== undefined) {
      entry = await deps.refreshEntry(activeEntry.entryId);
    }
    const recovered = await api.status();
    if (disposed) return;
    journal.sources = recovered.sources.filter(s => ids.has(s.capture_id)).map(({ capture_id, sha256, bytes }) => ({ capture_id, sha256, bytes }));
    const available = new Set(journal.sources.map(s => s.capture_id));
    journal.memberIds = journal.memberIds.filter(id => available.has(id));
    await api.requests.reconcile(recovered.requests.map(r => r.request_id));
    await reviewApi.requests.reconcile(recovered.requests.map(r => r.request_id));
    const completed = recovered.requests.find(r => r.request_id === journal.pending?.request_id);
    if (completed?.receipts && completed.batch_id && completed.queued_job_id) {
      journal.result = { receipts: completed.receipts, batch_id: completed.batch_id, queued_job_id: completed.queued_job_id };
      journal.pending = null;
    }
    const latest = [...recovered.requests].reverse().find(r => r.receipts && r.batch_id && r.queued_job_id);
    journal.result = latest?.receipts && latest.batch_id && latest.queued_job_id
      ? { receipts: latest.receipts, batch_id: latest.batch_id, queued_job_id: latest.queued_job_id }
      : null;
    receiptHistory = recovered.requests.flatMap(r => r.receipts && r.batch_id && r.queued_job_id
      ? [{ receipts: r.receipts, batch_id: r.batch_id, queued_job_id: r.queued_job_id }] : []);
    const pendingWrite = await reviewApi.requests.pending();
    ui.retryReview.hidden = !pendingWrite || pendingWrite.path === '/personal-admission';
    sourceOptions(); renderReview(); persist();
  }
  function renderReview(): void {
    const captureId = ui.source.value;
    const review = reviews.get(captureId);
    const stamp = ++generation;
    ui.reviewChoice.value = choices.get(captureId) ?? '';
    if (!review) { replace(ui.review, [el('p', { text: 'Reload sources to read saved proposals and review.' })]); return; }
    const source = current.reviewSources?.find(s => s.captureId === captureId);
    const original = journal.sources.find(s => s.capture_id === captureId);
    const local = localOriginals.get(captureId);
    const descriptor = local ? { available: true, url: local, alt: 'Locally reselected, digest-verified original photograph' }
      : source?.state === 'available' ? media?.get(source.evidenceSpanId) ?? null : null;
    const exactOriginal = local !== undefined || (original !== undefined && source?.contentSha256 === original.sha256);
    ui.reviewChoice.disabled = !inspected.has(captureId);
    const mutate = (run: () => Promise<unknown>) => {
      if (journal.pending) { say('Resolve or discard the pending admission before changing its reviewed inputs.'); return; }
      void act(async () => {
        choices.delete(captureId); ui.attestation.checked = false;
        await run(); await reload();
      });
    };
    replace(ui.review, [buildPersonReview({
      ...review, selectedRegions: new Set([...selected.values()].filter(r => r.capture_id === captureId).map(r => r.region_key)),
      onSelectRegion: (region_key, checked) => {
        const key = `${captureId}:${region_key}`;
        if (checked) selected.set(key, { capture_id: captureId, region_key }); else selected.delete(key);
        reflect();
      },
      onReload: () => { void act(reload); },
      onConfirm: region_key => mutate(() => reviewApi.edit(captureId, { region_key, action: 'confirm' })),
      onDelete: region_key => mutate(() => reviewApi.edit(captureId, { region_key, action: 'delete' })),
      onIdentify: region_key => mutate(() => reviewApi.link([{ capture_id: captureId, region_key }])),
      onUnlink: key => { const region = review.regions.find(r => r.regionKey === key); if (region) mutate(() => reviewApi.unlink(captureId, region)); },
      onCorrect: key => {
        const region = review.regions.find(r => r.regionKey === key);
        if (!region) return;
        correction = { region_key: key, silhouette: { kind: 'polygon', points: region.silhouette.points } };
        renderReview();
      },
      onConsent: (key, scope, decision) => {
        const region = review.regions.find(r => r.regionKey === key);
        if (region) mutate(() => reviewApi.consent(captureId, region, scope, decision));
      },
      editor: {
        captureId, source: descriptor, drafts: deps.session.drafts,
        ...(correction ? { correction } : {}),
        isCurrent: () => !disposed && generation === stamp && !busy && journal.pending === null,
        onAdd: async region => {
          choices.delete(captureId); ui.attestation.checked = false;
          if (correction) await reviewApi.correct(captureId, region);
          else if (!(await reviewApi.load(captureId)).regions.some(r => r.regionKey === region.region_key)) await reviewApi.add(captureId, region);
          correction = undefined;
          await reload();
        },
      },
    })]);
    const photo = ui.review.querySelector('img');
    photo?.addEventListener('load', () => {
      if (generation !== stamp || !exactOriginal || photo.naturalWidth === 0) return;
      inspected.add(captureId); ui.reviewChoice.disabled = false;
    });
    if (!exactOriginal) ui.review.prepend(el('p', { text: 'Exact original inspection is unavailable in this viewer. Reselect the original locally before completing human review.' }));
    if (correction) {
      const cancel = el('button', { type: 'button', text: 'Return to adding a missed person' });
      cancel.onclick = () => { correction = undefined; renderReview(); };
      ui.review.append(cancel);
    }
  }
  function prepare(operation: 'detect' | 'review'): PersonalAdmission {
    const members = journal.sources.filter(s => journal.memberIds.includes(s.capture_id));
    if (!members.length || members.length > 200) throw new Error('Select between 1 and 200 photographs for this admission.');
    const now = new Date().toISOString();
    const until = new Date(ui.validUntil.value);
    if (!Number.isFinite(until.getTime()) || until.getTime() <= Date.now()) throw new Error('Enter a future authority expiry.');
    if (!ui.purpose.value.trim() || !ui.authority.value.trim()) throw new Error('Choose sources and state your purpose and account authority.');
    if (operation === 'review' && (!ui.attestation.checked || !ui.reviewer.value.trim()
      || members.some(s => !inspected.has(s.capture_id) || !choices.has(s.capture_id)))) {
      throw new Error('Inspect every exact original, choose its actual review, and complete the named attestation.');
    }
    return {
      request_id: crypto.randomUUID(),
      members: members.map(s => ({ ...s, review: operation === 'detect' ? 'not-reviewed' : choices.get(s.capture_id) ?? 'not-reviewed' })),
      purpose: ui.purpose.value.trim(),
      authority: { account_authority_basis: ui.authority.value.trim(), authorized_at: now, valid_until: until.toISOString() },
      recorded_at: now, operation,
      ...(operation === 'review' ? { reviewed_by_name: ui.reviewer.value.trim(), attestation: HUMAN_ATTESTATION } : {}),
    };
  }
  async function sendPending(): Promise<void> {
    if (!journal.pending) return;
    let result: AdmissionResult;
    try { result = await api.requests.pending() ? await api.requests.retry<AdmissionResult>() : await api.admit(journal.pending); }
    catch (error) {
      if (!await api.requests.pending()) { journal.pending = null; persist(); throw error; }
      throw new Error(`${error instanceof Error ? error.message : 'Admission did not answer.'} `
        + 'The exact request is retained. Retry recovers its original receipt identities without repeating the operation.');
    }
    journal.result = result; journal.pending = null; persist();
    watch(result.batch_id);
    say('Admission receipts recorded. Reload proposals after processing; detection never completes human review.');
    await reload();
  }

  function prepareAttachment(): SourceAttachmentRequest {
    const active = getEntry();
    if (active === null) throw new Error('Open a saved world before attaching references.');
    const selection = attachmentSelection();
    if (selection.selectedCount === 0) {
      throw new Error('Select reviewed photographs before attaching references.');
    }
    if (selection.refusedCount > 0) {
      throw new Error(
        `${selection.refusedCount} selected photograph${selection.refusedCount === 1 ? ' needs' : 's need'} ` +
        'completed review or current viewer access. Deselect or finish reviewing ' +
        `${selection.refusedCount === 1 ? 'it' : 'them'}; nothing was attached.`,
      );
    }
    if (selection.sources.length === 0) {
      throw new Error('The selected photos are already in this world. Choose another reviewed photo.');
    }
    return Object.freeze({
      entryId: active.entryId,
      operationId: crypto.randomUUID(),
      baseRevision: active.revision,
      authoredVersionId: active.authoredVersionId,
      authoredStateSha256: active.authoredStateSha256,
      authoredEditSeq: active.authoredEditSeq,
      styleVersionId: active.styleVersionId,
      sources: selection.sources,
    });
  }

  async function sendPendingAttachment(): Promise<void> {
    const request = pendingAttachment;
    if (request === null || deps.attachSources === undefined) return;
    const active = getEntry();
    if (active === null || active.entryId !== request.entryId) {
      throw new Error('This retained attachment belongs to a different saved world. Open that world to retry it.');
    }
    try {
      const updated = await deps.attachSources(request);
      entry = updated;
      pendingAttachment = null;
      persistAttachment();
      say(
        `${request.sources.length} reviewed photograph${request.sources.length === 1 ? '' : 's'} ` +
        'attached as project references. No geometry or reconstruction was created.',
      );
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null;
      if (apiError !== null && apiError.status >= 400 && apiError.status < 500 &&
          apiError.status !== 408) {
        pendingAttachment = null;
        persistAttachment();
      }
      if (apiError?.code === 'stale_saved_world_entry') {
        let refreshed = false;
        try {
          if (deps.refreshEntry !== undefined) {
            entry = await deps.refreshEntry(request.entryId);
            refreshed = true;
          }
        } catch {
          // Keep the stale-conflict message authoritative; the ordinary entry read can retry later.
        }
        throw new Error(
          refreshed
            ? 'This world changed before the references were attached. Its saved entry was ' +
              'refreshed; review the selection and attach again.'
            : 'This world changed before the references were attached. Reload this world before ' +
              'attaching again.',
        );
      }
      throw error;
    }
  }
  ui.originals.onchange = () => { void act(async () => {
    for (const file of [...ui.originals.files ?? []]) {
      const digest = await sha256(await file.arrayBuffer());
      const matches = journal.sources.filter(s => s.sha256 === digest && s.bytes === file.size);
      if (!matches.length) throw new Error('Reselected file does not match an original in this workspace.');
      for (const match of matches) {
        const old = localOriginals.get(match.capture_id); if (old) URL.revokeObjectURL(old);
        localOriginals.set(match.capture_id, URL.createObjectURL(file));
      }
    }
    renderReview(); say('Original bytes match. Inspect each photograph before choosing its review.');
  }); };
  ui.upload.onclick = () => { void act(async () => {
    const result = await api.upload([...ui.files.files ?? []]);
    journal.sources = [...new Map([...journal.sources, ...result.accepted].map(s => [s.capture_id,
      { capture_id: s.capture_id, sha256: s.sha256, bytes: s.bytes }])).values()];
    if (result.accepted.length) { journal.memberIds = result.accepted.map(s => s.capture_id); ui.attestation.checked = false; }
    persist(); if (result.queued_job_id) watch(result.batch_id);
    say(result.refused.length ? result.refused.map(r => `${r.filename}: ${r.reason}. ${r.detail}`).join('\n')
      : 'Original byte digests verified against upload receipts. Authorize detection separately.');
    await reload();
  }); };
  for (const [button, operation] of [[ui.detect, 'detect'], [ui.complete, 'review']] as const) {
    button.onclick = () => { void act(async () => {
      if (await api.requests.pending()) throw new Error('Recover the interrupted personal request before another admission.');
      journal.pending = prepare(operation); persist(); await sendPending();
    }); };
  }
  ui.retry.onclick = () => { void act(sendPending); };
  ui.retryReview.onclick = () => { void act(async () => {
    await reviewApi.requests.retry(); await reload(); say('The interrupted review receipt has been recovered.');
  }); };

  ui.reload.onclick = () => { void act(reload); };
  ui.source.onchange = () => { correction = undefined; renderReview(); };
  ui.reviewChoice.onchange = () => {
    const choice = ui.reviewChoice.value;
    if (inspected.has(ui.source.value) && (choice === 'no-person' || choice === 'confirmed-regions')) choices.set(ui.source.value, choice);
    else choices.delete(ui.source.value);
    ui.attestation.checked = false;
  };
  ui.link.onclick = () => { void act(async () => {
    if (journal.pending) throw new Error('Resolve or discard pending admission first.');
    await reviewApi.link([...selected.values()], ui.linkedSubject.value || undefined);
    selected.clear(); choices.clear(); ui.attestation.checked = false; await reload();
    say('Selected regions now identify the same person. No consent was inferred.');
  }); };
  ui.worldAction.onclick = () => { void act(async () => {
    if (getEntry() === null) {
      await deps.refreshWorld();
      return;
    }
    if (deps.attachSources === undefined) {
      throw new Error('Reference attachment is unavailable for this saved world.');
    }
    pendingAttachment = prepareAttachment();
    persistAttachment();
    await sendPendingAttachment();
  }); };
  ui.retryAttachment.onclick = () => { void act(sendPendingAttachment); };
  async function begin(): Promise<void> {
    if (deps.preview) {
      say('Photo upload and human review require an authenticated workspace. This preview shows the workflow; its controls do not upload or save.');
      return;
    }
    await act(async () => {
      // A hash scopes recovery to this API/session without retaining the bearer token.
      storageKey = `personal-intake:v1:${await sha256(new TextEncoder().encode(`${deps.credentials.baseUrl}\n${deps.credentials.token}`).buffer)}`;
      try {
        const saved = storage?.getItem(storageKey);
        if (saved) journal = JSON.parse(saved) as Journal;
        const active = getEntry();
        if (active !== null) {
          attachmentStorageKey = `${storageKey}:world-entry:${active.entryId}:source-attachment`;
          const savedAttachment = storage?.getItem(attachmentStorageKey);
          if (savedAttachment) {
            const retained = JSON.parse(savedAttachment) as SourceAttachmentRequest;
            if (retained.entryId === active.entryId) pendingAttachment = retained;
          }
        }
      } catch { say('Local recovery metadata could not be read. Saved server regions remain available.'); }
      // Old local journals did not distinguish inventory and admission. Only a frozen pending
      // request proves its intended membership; never infer selection from historical inventory.
      journal.memberIds = journal.pending?.members.map(s => s.capture_id) ?? journal.memberIds ?? [];
      if (journal.pending) say('An interrupted admission is retained. Retry uses the exact original dated request.');
      if (pendingAttachment) {
        say('An interrupted reference attachment is retained. Retry uses its exact world cursor and source selection.');
      }
      if (journal.result) watch(journal.result.batch_id);
      else { const latest = (await listBatches(deps.credentials))[0]; if (latest && !disposed) watch(latest.batchId); }
      await reload();
      if (!journal.sources.length && (current.reviewSources?.length ?? 0) > 0) {
        say('Saved review restored from the server. Reselect exact originals locally to inspect regions hidden by the authorized viewer.');
      }
    });
  }
  const dispose = () => { for (const url of localOriginals.values()) URL.revokeObjectURL(url); localOriginals.clear(); disposed = true; ++generation; stopWatch?.(); ownMedia?.dispose(); };
  deps.session.dispose = dispose;
  sourceOptions(); reflect();
  return { root: ui.root, begin, dispose };
}

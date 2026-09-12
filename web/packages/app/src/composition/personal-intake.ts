/** Mounted source-first journey. Server state remains authoritative after every mutation. */
import { formationLabel } from '@exulanica/formation';
import type { GraphSnapshot, TransportOptions } from '@exulanica/graph-client';
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

interface Journal {
  sources: PersonalSource[];
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
  session: PersonalIntakeSession;
  snapshot: GraphSnapshot;
  media: SourceMediaCatalog | undefined;
  reloadSnapshot: () => Promise<GraphSnapshot>;
  refreshWorld: () => Promise<void>;
  storage?: Storage;
}) {
  deps.session.dispose?.();
  const ui = buildPersonalIntake();
  const api = new PersonalAdmissionApi(deps.credentials);
  const reviewApi = new PersonReviewApi(deps.credentials);
  let storage: Storage | null = deps.storage ?? null;
  try { storage ??= window.sessionStorage; } catch { /* Server review still loads in restricted browsers. */ }
  let journal: Journal = { sources: [], pending: null, result: null };
  let storageKey = '';
  let current = deps.snapshot;
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
  function persist(): void {
    try {
      if (!storage) throw new Error('Storage unavailable');
      storage.setItem(storageKey, JSON.stringify(journal));
    }
    catch { say('Browser recovery storage is unavailable. Keep this page open for exact admission retry.'); }
  }
  function reflect(): void {
    ui.controls.disabled = busy;
    ui.retry.hidden = journal.pending === null;

    ui.upload.disabled = ui.detect.disabled = ui.complete.disabled = journal.pending !== null;
    ui.selection.textContent = `${selected.size} region(s) explicitly selected across photographs.`;
    replace(ui.inventory, journal.sources.map((source, index) => el('p', {
      text: `Original ${index + 1}: ${source.bytes} bytes; SHA-256 ${source.sha256}; capture ${source.capture_id}`,
    })));
    replace(ui.receipts, journal.result?.receipts.map(receipt => el('p', {
      text: `Capture ${receipt.capture_id}: ${receipt.eligibility_state}. Authorization ${receipt.authorization_id}; screening ${receipt.screening_id}. Queued work is not completed depth.`,
    })) ?? []);
  }
  async function act(run: () => Promise<void>): Promise<void> {
    if (busy || disposed) return;
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
      value: source.captureId, text: `Photograph ${i + 1}${source.state === 'available' ? '' : ' — viewer unavailable'}`,
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
      const next = await new SourceMediaClient(deps.credentials).load('#777777');
      if (disposed) { next.dispose(); return; }
      ownMedia = next; media = next.catalog;
    } catch { say('Current authorized viewer bytes are unavailable. Saved review is retained; no original fallback is used.'); }
    const recovered = await api.status();
    if (disposed) return;
    journal.sources = recovered.sources.filter(s => ids.has(s.capture_id)).map(({ capture_id, sha256, bytes }) => ({ capture_id, sha256, bytes }));
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
    const now = new Date().toISOString();
    const until = new Date(ui.validUntil.value);
    if (!Number.isFinite(until.getTime()) || until.getTime() <= Date.now()) throw new Error('Enter a future authority expiry.');
    if (!journal.sources.length || !ui.purpose.value.trim() || !ui.authority.value.trim()) throw new Error('Choose sources and state your purpose and account authority.');
    if (operation === 'review' && (!ui.attestation.checked || !ui.reviewer.value.trim()
      || journal.sources.some(s => !inspected.has(s.capture_id) || !choices.has(s.capture_id)))) {
      throw new Error('Inspect every exact original, choose its actual review, and complete the named attestation.');
    }
    return {
      request_id: crypto.randomUUID(),
      members: journal.sources.map(s => ({ ...s, review: operation === 'detect' ? 'not-reviewed' : choices.get(s.capture_id) ?? 'not-reviewed' })),
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
  ui.refreshWorld.onclick = () => { void act(deps.refreshWorld); };
  async function begin(): Promise<void> {
    await act(async () => {
      // A hash scopes recovery to this API/session without retaining the bearer token.
      storageKey = `personal-intake:v1:${await sha256(new TextEncoder().encode(`${deps.credentials.baseUrl}\n${deps.credentials.token}`).buffer)}`;
      try {
        const saved = storage?.getItem(storageKey);
        if (saved) journal = JSON.parse(saved) as Journal;
      } catch { say('Local recovery metadata could not be read. Saved server regions remain available.'); }
      if (journal.pending) say('An interrupted admission is retained. Retry uses the exact original dated request.');
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

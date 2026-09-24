/** Mounted source-first journey. Server state remains authoritative after every mutation. */
import { formationLabel } from '@exulanica/formation';
import { ApiError, type GraphSnapshot, type TransportOptions } from '@exulanica/graph-client';
import type { SourceMediaCatalog } from '@exulanica/atlas-react/playcanvas';
import { PersonalAdmissionApi, DEPTH_ROLE, HUMAN_ATTESTATION,
  sha256, type PersonalSource, type PersonalAdmission,
  type AdmissionResult, type ModelRightOffer, type ModelRightState } from '../personal-admission-api.js';
import { readOffers, standingControls, standingOf, standingText } from '../ui/model-right-controls.js';
import { PersonReviewApi, type PersonReview } from '../person-review-api.js';
import { listBatches, watchBatch } from '../formation.js';
import { SourceMediaClient } from '../source-media-api.js';
import { buildPersonalIntake } from '../ui/personal-intake.js';
import { buildPhotoGeometryInspector } from '../ui/photo-geometry-inspector.js';
import {
  WorldObjectsClient,
  type PointMapInstance,
} from '../world-objects-api.js';
import { buildPersonReview } from '../ui/person-review.js';
import { PersonRegionDrafts, type ManualRegion } from '../ui/person-region-editor.js';
import { el, replace } from '../ui/dom.js';
import {
  WorldEntryClient,
  type SavedWorldEntry,
  type SavedWorldPreviousSourceAttachment,
  type SavedWorldSourceAttachment,
  type SourceAttachmentRequest,
  type SourceDetachRequest,
  type SourceRebindRequest,
} from '../world-entry-api.js';
import type { PersonalWorldControl } from './world-entry.js';

type MembershipRequest = SourceDetachRequest | SourceRebindRequest;

/** The server's own reason: the detail an ApiError carries after its code in the message. */
const reasonOf = (error: ApiError): string =>
  error.message.startsWith(`${error.code}: `) ? error.message.slice(error.code.length + 2) : error.message;

/**
 * Plain words for each stable refusal code. The code itself is shown only inside Details, so a
 * person reads what happened and a report can still name the exact refusal.
 */
const REFERENCE_REFUSALS: Readonly<Record<string, string>> = {
  stale_saved_world_entry:
    'This world changed somewhere else before your change was saved, so nothing changed. ' +
    'The photos have been refreshed; try again.',
  membership_event_operation_conflict:
    'That change no longer matches what was first sent, so it was not repeated. Nothing changed.',
  source_attachment_operation_conflict:
    'That change no longer matches what was first sent, so it was not repeated. Nothing changed.',
  membership_unavailable: 'That photo is not part of this world, so there was nothing to change.',
  membership_current: 'That photo is already in this world.',
  review_required:
    'This photo needs a new review before it can be added back. Nothing was added. ' +
    'Review it again in Add or review photos, then choose Add back.',
  authority_unavailable:
    'This photo cannot be added back yet: it has no current review, or its image cannot be ' +
    'shown. Review it again, then choose Add back.',
  entry_unavailable: 'This world cannot be opened right now, so photos cannot be added back to it.',
  invalid_detach: 'That selection could not be used. Choose each photo once.',
  invalid_rebind: 'That selection could not be used. Choose each photo once.',
  rebind_required:
    'This photo was removed from this world earlier. Use Add back under Previously in this world.',
  invalid_source_attachment:
    'That photo cannot be added: it is already in this world, or it has no current review.',
  unknown_reference: 'This world is not available to this account.',
};

const REFERENCE_STATUS: Readonly<Record<string, string>> = {
  source_unavailable: 'In this world, but the original photo was deleted',
  authorization_expired: 'In this world, but the permission to use it has ended',
  screening_expired: 'In this world, but its review has expired',
  viewer_unavailable: 'In this world, but its image cannot be shown right now',
};

const RECEIPT_STATE: Readonly<Record<string, string>> = {
  eligible: 'reviewed and ready to keep with a world',
  'detection-only': 'checked for people; a human review is still needed',
  'blocked-or-stale': 'not ready; its review is missing or out of date',
};

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
  /** Injectable for tests. Production builds a client from the same credentials. */
  entryClient?: Pick<WorldEntryClient, 'detachSources' | 'rebindSources'>;
  /**
   * The offer to make a world from reviewed photographs. The drawer shows it beside the photos
   * and asks the server again after every reload, since a review recorded here can change it.
   */
  personalWorld?: PersonalWorldControl;
}) {
  deps.session.dispose?.();
  const ui = buildPersonalIntake();
  if (deps.personalWorld !== undefined) ui.previous.after(deps.personalWorld.root);
  const api = new PersonalAdmissionApi(deps.credentials);
  const reviewApi = new PersonReviewApi(deps.credentials);
  const entryClient = deps.entryClient
    ?? (deps.preview === true ? null : new WorldEntryClient(deps.credentials));
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
  let pendingMembership: MembershipRequest | null = null;
  let membershipStorageKey = '';
  let confirmingRemoval: string | null = null;
  /** The photo and role whose stop is waiting for confirmation, as `capture:role`. */
  let confirmingStop: string | null = null;
  /**
   * Every model right this account holder granted, newest first per photograph, as the server
   * last reported them. Read-only: the state shown comes from GET /personal-admission and is
   * replaced on every reload, so a stop that the server refused never looks like it happened.
   */
  const grantedRights = new Map<string, ModelRightState[]>();
  /**
   * The rights a person may give, with every word shown for them, as the server last stated them.
   * Empty until the first read and after a read that states none, so nothing can be ticked then.
   */
  let offers: readonly ModelRightOffer[] = [];
  /**
   * Placed estimates in the open world, by the photograph they were made from.
   *
   * Read from the authored version because that is where a placement lives; the drawer is the one
   * surface that already stands on a single named photograph, which is what the panel is about.
   */
  const placedEstimates = new Map<string, PointMapInstance[]>();
  // Photos whose Add back sent the person to review. Finishing a review never adds one back.
  const awaitingReview = new Set<string>();
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
  const notice = (message: string, code: string | null = null) => {
    if (disposed) return;
    const children: HTMLElement[] = message.length > 0 ? [el('p', { text: message })] : [];
    if (code !== null) {
      children.push(el('details', {}, [
        el('summary', { text: 'Details' }),
        el('p', { text: `Refusal code: ${code}` }),
      ]));
    }
    replace(ui.referenceNotice, children);
  };
  const photoLabel = (captureId: string): string => {
    const index = (current.reviewSources ?? []).findIndex((source) => source.captureId === captureId);
    return index >= 0 ? `Photograph ${index + 1}` : 'A photograph no longer in the library';
  };
  const eligibleCaptures = (): Set<string> => new Set(receiptHistory.flatMap((result) =>
    result.receipts
      .filter((receipt) => receipt.eligibility_state === 'eligible')
      .map((receipt) => receipt.capture_id)));
  /** A recorded eligible review this removed membership did not pin. The server decides. */
  const newReviewFor = (removed: SavedWorldPreviousSourceAttachment): boolean =>
    receiptHistory.some((result) => result.receipts.some((receipt) =>
      receipt.capture_id === removed.captureId && receipt.eligibility_state === 'eligible' &&
      receipt.authorization_id !== removed.authorizationId &&
      receipt.screening_id !== removed.screeningId));

  const attachmentSelection = (): {
    readonly selectedCount: number;
    readonly sources: SourceAttachmentRequest['sources'];
    readonly attachedCount: number;
    readonly refusedCount: number;
    readonly removedCount: number;
  } => {
    const active = getEntry();
    if (active === null) {
      return { selectedCount: 0, sources: [], attachedCount: 0, refusedCount: 0, removedCount: 0 };
    }
    const eligible = eligibleCaptures();
    const attached = new Set(active.sourceAttachments.map((attachment) => attachment.captureId));
    const removed = new Set((active.previousSourceAttachments ?? []).map((row) => row.captureId));
    const reviewSources = new Map((current.reviewSources ?? []).map((source) => [
      source.captureId, source,
    ]));
    const sources: SourceAttachmentRequest['sources'][number][] = [];
    let attachedCount = 0;
    let refusedCount = 0;
    let removedCount = 0;
    for (const captureId of journal.memberIds) {
      if (attached.has(captureId)) {
        attachedCount += 1;
        continue;
      }
      if (removed.has(captureId)) {
        removedCount += 1;
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
      removedCount,
    });
  };

  function referenceImage(evidenceSpanId: string, captureId: string): HTMLElement | null {
    const descriptor = media?.get(evidenceSpanId) ?? media?.get(captureId);
    return descriptor?.available === true && descriptor.url !== null
      ? el('img', { src: descriptor.url, alt: descriptor.alt })
      : null;
  }
  function lineage(captureId: string, sourceSha256: string): HTMLElement {
    return el('details', {}, [
      el('summary', { text: 'About this photo' }),
      el('p', { text: `Capture ${captureId}; original SHA-256 ${sourceSha256}.` }),
    ]);
  }
  /** The open world's placed estimates, or none when there is no world or it cannot be read. */
  async function readPlacedEstimates(): Promise<void> {
    placedEstimates.clear();
    const active = getEntry();
    if (deps.preview === true || active === null) return;
    try {
      const version = await new WorldObjectsClient({
        ...deps.credentials, worldId: active.worldId,
      }).readVersion(active.authoredVersionId);
      for (const instance of version.pointMapInstances ?? []) {
        if (instance.removed) continue;
        const captureId = String(
          (instance.source as Record<string, unknown>)['capture_id'] ?? '',
        );
        if (captureId.length === 0) continue;
        placedEstimates.set(captureId, [...placedEstimates.get(captureId) ?? [], instance]);
      }
    } catch {
      // The drawer's job is the photographs. A version that cannot be read costs the panel
      // below and nothing else.
    }
  }

  /**
   * Each offered role's standing over one photograph, in the server's order. ``not allowed`` and
   * ``stopped`` stay different words for different facts: nobody ever ticked the box, against a
   * person who ticked it and then took it back. An older stopped right beside a newer current one
   * means the person allowed it again after a fresh review, and reads as allowed.
   */
  function standings(captureId: string): ReturnType<typeof standingOf>[] {
    const rights = grantedRights.get(captureId) ?? [];
    return offers.map((offer) => standingOf(offer, rights));
  }
  /**
   * Stop one role for one photograph: every current right it holds there, since the role's chain
   * is refused as a whole once any of them ends. Final on the server; the reload reads back what
   * it did, so a stop the server refused never reads as done.
   */
  async function stopRole(captureId: string, role: string): Promise<void> {
    const standing = standings(captureId).find((each) => each.offer.role === role);
    for (const right of standing?.current ?? []) await api.stopModelRight(right.right_id);
    confirmingStop = null;
    await reload();
    const after = standings(captureId).find((each) => each.offer.role === role);
    say(after === undefined ? 'Stopped for that photo.' : `${standingText(after)} for that photo.`);
  }
  /**
   * Each offered role's state line and, while it is allowed, the control that ends it. ``given``
   * leaves out the roles never given for this photo, for the inventory, where every saved photo is
   * listed whether or not it is in a world and a row per role nobody asked about would bury it.
   */
  function rightControls(captureId: string, given = false): HTMLElement[] {
    const locked = busy || deps.preview === true;
    return standings(captureId).filter((standing) => !given || standing.standing !== 'none').flatMap((standing) => {
      const key = `${captureId}:${standing.offer.role}`;
      return standingControls(standing, {
        confirming: confirmingStop === key,
        locked,
        onAsk: () => { confirmingStop = key; reflect(); },
        onStop: () => { void act(() => stopRole(captureId, standing.offer.role)); },
        onKeep: () => { confirmingStop = null; reflect(); },
      });
    });
  }
  function currentCard(attachment: SavedWorldSourceAttachment, index: number): HTMLElement {
    const children: HTMLElement[] = [
      el('strong', { text: `Reference photograph ${index + 1}` }),
      el('span', {
        class: 'photo-reference-status',
        text: attachment.availability === 'available'
          ? 'In this world'
          : REFERENCE_STATUS[attachment.unavailableReason ?? ''] ??
            'In this world, but it cannot be shown right now',
      }),
    ];
    // The image is shown only when the pinned reference is available and the viewer loaded.
    const image = attachment.availability === 'available'
      ? referenceImage(attachment.evidenceSpanId, attachment.captureId) : null;
    if (image !== null) children.push(image);
    children.push(lineage(attachment.captureId, attachment.sourceSha256));
    children.push(...rightControls(attachment.captureId));
    for (const instance of placedEstimates.get(attachment.captureId) ?? []) {
      // A placed estimate exists because of the depth right, so its own Stop asks to stop that.
      const depth = standings(attachment.captureId).find((each) => each.offer.role === DEPTH_ROLE);
      children.push(buildPhotoGeometryInspector({
        instance,
        ...(depth === undefined || depth.current.length === 0 ? {} : {
          onStop: () => { confirmingStop = `${attachment.captureId}:${DEPTH_ROLE}`; reflect(); },
        }),
      }));
    }
    const locked = busy || deps.preview === true || entryClient === null ||
      pendingMembership !== null;
    if (confirmingRemoval === attachment.attachmentId) {
      const remove = el('button', {
        type: 'button', class: 'photo-reference-remove-confirm', text: 'Remove',
      });
      const keep = el('button', { type: 'button', text: 'Keep in this world' });
      remove.disabled = locked;
      remove.onclick = () => { void removeReference(attachment.attachmentId); };
      keep.onclick = () => { confirmingRemoval = null; reflect(); };
      children.push(el('div', {
        class: 'photo-reference-confirm', role: 'group', 'aria-label': 'Confirm removal',
      }, [
        el('p', { text: 'Remove this photo from this world? The photo stays in your library. ' +
          'This world stops using it, and adding it back later needs a new review.' }),
        el('div', { class: 'photo-reference-actions' }, [remove, keep]),
      ]));
    } else {
      const remove = el('button', {
        type: 'button', class: 'photo-reference-remove', text: 'Remove from this world',
      });
      remove.disabled = locked;
      remove.onclick = () => { confirmingRemoval = attachment.attachmentId; reflect(); };
      children.push(el('div', { class: 'photo-reference-actions' }, [remove]));
    }
    return el('article', { class: 'attached-reference' }, children);
  }
  function previousCard(removed: SavedWorldPreviousSourceAttachment): HTMLElement {
    const reviewed = newReviewFor(removed);
    const children: HTMLElement[] = [
      el('strong', { text: photoLabel(removed.captureId) }),
      el('span', {
        class: 'photo-reference-status',
        text: removed.availability === 'available'
          ? 'Removed from this world. The photo is still in your library.'
          : 'Removed from this world. The original photo is no longer in your library, ' +
            'so it cannot be added back.',
      }),
    ];
    const image = removed.availability === 'available'
      ? referenceImage(removed.evidenceSpanId, removed.captureId) : null;
    if (image !== null) children.push(image);
    if (removed.availability === 'available') {
      children.push(el('p', {
        class: 'photo-reference-hint',
        text: reviewed
          ? 'A new review is recorded. Choose Add back to use this photo in this world again.'
          : awaitingReview.has(removed.captureId)
            ? 'Waiting for a new review of this photo in Add or review photos.'
            : 'Adding it back starts with a new review of the photo.',
      }));
      const addBack = el('button', {
        type: 'button', class: 'photo-reference-add-back', text: 'Add back',
      });
      addBack.disabled = busy || deps.preview === true || entryClient === null ||
        pendingMembership !== null;
      addBack.onclick = () => { void addReferenceBack(removed); };
      children.push(el('div', { class: 'photo-reference-actions' }, [addBack]));
    }
    children.push(lineage(removed.captureId, removed.sourceSha256));
    return el('article', { class: 'attached-reference previous-reference' }, children);
  }
  function readyCard(source: { captureId: string; evidenceSpanId: string }): HTMLElement {
    const add = el('button', {
      type: 'button', class: 'photo-reference-add', text: 'Attach as a reference',
    });
    add.disabled = busy || deps.preview === true || deps.attachSources === undefined ||
      pendingAttachment !== null;
    add.onclick = () => { void attachOne(source); };
    const children: HTMLElement[] = [
      el('strong', { text: photoLabel(source.captureId) }),
      el('span', { class: 'photo-reference-status', text: 'Reviewed and ready' }),
    ];
    const image = referenceImage(source.evidenceSpanId, source.captureId);
    if (image !== null) children.push(image);
    children.push(el('div', { class: 'photo-reference-actions' }, [add]));
    return el('article', { class: 'attached-reference ready-reference' }, children);
  }
  function readySources(active: SavedWorldEntry): { captureId: string; evidenceSpanId: string }[] {
    const used = new Set([
      ...active.sourceAttachments.map((row) => row.captureId),
      ...(active.previousSourceAttachments ?? []).map((row) => row.captureId),
    ]);
    const eligible = eligibleCaptures();
    return (current.reviewSources ?? [])
      .filter((source) => source.state === 'available' && eligible.has(source.captureId) &&
        !used.has(source.captureId))
      .map((source) => ({ captureId: source.captureId, evidenceSpanId: source.evidenceSpanId }));
  }

  function renderAttachments(): void {
    if (entry === null) {
      ui.referenceCount.textContent = 'No world open';
      replace(ui.attachedReferences, [el('p', {
        text: 'Open a saved world to keep reviewed photographs with that project.',
      })]);
      ui.ready.hidden = true;
      ui.previous.hidden = true;
      return;
    }
    ui.referenceCount.textContent = `${entry.sourceAttachments.length} ` +
      `photo${entry.sourceAttachments.length === 1 ? '' : 's'}`;
    replace(ui.attachedReferences, entry.sourceAttachments.length === 0
      ? [el('p', { class: 'photo-collection-empty',
        text: 'No reference photos yet. Add or review photos, then select eligible photos to keep with this world.',
      })]
      : entry.sourceAttachments.map(currentCard));
    const ready = readySources(entry);
    ui.ready.hidden = ready.length === 0;
    replace(ui.readyReferences, ready.map(readyCard));
    const previous = entry.previousSourceAttachments ?? [];
    ui.previous.hidden = previous.length === 0;
    replace(ui.previousReferences, previous.map(previousCard));
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
  function persistMembership(): void {
    if (membershipStorageKey.length === 0) return;
    try {
      if (!storage) throw new Error('Storage unavailable');
      if (pendingMembership === null) storage.removeItem(membershipStorageKey);
      else storage.setItem(membershipStorageKey, JSON.stringify(pendingMembership));
    } catch {
      say('Browser recovery storage is unavailable. Keep this page open to retry the photo change.');
    }
  }
  /** A right ends when the authority granting it ends, so the person is told which date that is. */
  function rightsTerm(grants: typeof ui.processingRights): string {
    if (grants.chosen().length === 0) return '';
    const until = new Date(ui.validUntil.value);
    return Number.isFinite(until.getTime()) && until.getTime() > Date.now()
      ? `Allowed until ${until.toLocaleString()}. You can stop it sooner from any photo below.`
      : 'Enter a future authority expiry above; what you allow here lasts only while that does.';
  }
  /**
   * Both ticks in step 4 describe the photographs as they are now: which ones were selected, and
   * what the review found in them. Either changing makes both statements about something else, so
   * both are taken back and asked again rather than carried over silently.
   */
  function forgetConsent(): void {
    ui.attestation.checked = false;
    ui.processingRights.reset();
    ui.reviewRights.reset();
  }
  function reflect(): void {
    ui.controls.disabled = busy || deps.preview === true;
    ui.processingRights.term.textContent = rightsTerm(ui.processingRights);
    ui.reviewRights.term.textContent = rightsTerm(ui.reviewRights);
    ui.retry.hidden = journal.pending === null;
    const attachment = attachmentSelection();
    ui.retryAttachment.hidden = pendingAttachment === null;
    ui.retryMembership.hidden = pendingMembership === null;
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
            attachment.removedCount > 0
              ? `${attachment.removedCount} removed from this world earlier; use Add back`
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
        forgetConsent(); persist(); reflect();
      };
      return el('div', { class: 'intake-original' }, [
        el('label', {}, [checkbox, ` Original ${index + 1} · ${(source.bytes / 1_000_000).toFixed(2)} MB`]),
        // What models this photo was allowed to reach, and the controls that stop them, wherever
        // the photo is: a right given at detection exists before the photo is in any world.
        el('div', { class: 'intake-original-rights' }, rightControls(source.capture_id, true)),
        el('details', {}, [el('summary', { text: 'File identity' }),
          el('p', { text: `${source.bytes} bytes; SHA-256 ${source.sha256}; capture ${source.capture_id}` })]),
      ]);
    }));
    // The latest recorded state of each photograph, in words; receipt identities stay in Details.
    const latest = new Map<string, string>();
    for (const result of receiptHistory) {
      for (const receipt of result.receipts) latest.set(receipt.capture_id, receipt.eligibility_state);
    }
    replace(ui.receipts, latest.size === 0 ? [] : [
      el('p', { text: 'Recorded so far:' }),
      ...[...latest].map(([captureId, state]) => el('p', {
        text: `${photoLabel(captureId)}: ${RECEIPT_STATE[state] ?? 'not ready'}. ` +
          standings(captureId).map((standing) => `${standingText(standing)}.`).join(' '),
      })),
      el('details', {}, [
        el('summary', { text: 'Receipt details' }),
        ...receiptHistory.flatMap((result) => result.receipts.map((receipt) => el('p', {
          text: `Batch ${result.batch_id}. Capture ${receipt.capture_id}: ${receipt.eligibility_state}. ` +
            `Authorization ${receipt.authorization_id}; screening ${receipt.screening_id}.`,
        }))),
      ]),
    ]);
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
      ...ids.map((id, i) => el('option', { value: id, text: `Person ${i + 1}` }))]);
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
        choices.delete(review.captureId); forgetConsent();
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
    grantedRights.clear();
    for (const source of recovered.sources) {
      if ((source.model_rights ?? []).length > 0) grantedRights.set(source.capture_id, [...source.model_rights!]);
    }
    // The words each right is shown with are the server's, read again on every reload. A changed
    // set takes every tick back, so nothing ticked against older words can be sent.
    const stated = readOffers(recovered.model_right_offers);
    if (JSON.stringify(stated) !== JSON.stringify(offers)) {
      offers = stated;
      ui.processingRights.show(offers.filter((offer) => offer.offered_with === 'detect'));
      ui.reviewRights.show(offers.filter((offer) => offer.offered_with === 'review'));
    }
    await readPlacedEstimates();
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
    await deps.personalWorld?.refresh();
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
        choices.delete(captureId); forgetConsent();
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
          choices.delete(captureId); forgetConsent();
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
  /** The rights ticked in one step, each with the server's own words, or nothing at all. */
  function grantsFor(grants: typeof ui.processingRights, until: Date): Pick<PersonalAdmission, 'model_rights'> {
    const chosen = grants.chosen();
    return chosen.length === 0 ? {} : {
      model_rights: chosen.map((offer) => ({
        role: offer.role, valid_until: until.toISOString(), notice: offer.notice,
      })),
    };
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
      // Sent only for the boxes ticked in this admission's own step, with the authority the rights
      // are granted under. Each notice is the server's text displayed beside its box; the server
      // compares it with its own and refuses anything else, so a client that showed nothing, or
      // something else, cannot grant a right.
      ...grantsFor(operation === 'detect' ? ui.processingRights : ui.reviewRights, until),
    };
  }
  async function sendPending(): Promise<void> {
    if (!journal.pending) return;
    let result: AdmissionResult;
    try { result = await api.requests.pending() ? await api.requests.retry<AdmissionResult>() : await api.admit(journal.pending); }
    catch (error) {
      if (!await api.requests.pending()) {
        journal.pending = null; persist();
        // Answered and refused: nothing was recorded. The reason is the server's, said as its
        // words rather than a status code. The offers are read again, and if the words for a
        // right changed while the person was reading, that is what they are told.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          const before = JSON.stringify(offers);
          try { await reload(); } catch { /* The refusal is still the thing to say. */ }
          throw new Error(JSON.stringify(offers) !== before
            ? 'The wording for what you allowed changed while you were reading it, so nothing was '
              + 'recorded. Read it again, then allow it if you still want to.'
            : `Nothing was recorded. The server said: ${reasonOf(error)}`);
        }
        throw error;
      }
      throw new Error(`${error instanceof Error ? error.message : 'Admission did not answer.'} `
        + 'The exact request is retained. Retry recovers its original receipt identities without repeating the operation.');
    }
    const sent = journal.pending.operation;
    journal.result = result; journal.pending = null; persist();
    // The rights ticked for that admission are recorded, and they spoke about those photos. The
    // ticks are taken back, so a later admission carries only what is ticked for it.
    (sent === 'detect' ? ui.processingRights : ui.reviewRights).reset();
    watch(result.batch_id);
    say('Admission receipts recorded. Reload proposals after processing; detection never completes human review.');
    await reload();
  }

  function attachmentRequest(
    active: SavedWorldEntry,
    sources: SourceAttachmentRequest['sources'],
  ): SourceAttachmentRequest {
    return Object.freeze({
      entryId: active.entryId,
      operationId: crypto.randomUUID(),
      baseRevision: active.revision,
      authoredVersionId: active.authoredVersionId,
      authoredStateSha256: active.authoredStateSha256,
      authoredEditSeq: active.authoredEditSeq,
      styleVersionId: active.styleVersionId,
      sources,
    });
  }
  function prepareAttachment(): SourceAttachmentRequest {
    const active = getEntry();
    if (active === null) throw new Error('Open a saved world before attaching references.');
    const selection = attachmentSelection();
    if (selection.selectedCount === 0) {
      throw new Error('Select reviewed photographs before attaching references.');
    }
    if (selection.removedCount > 0) {
      throw new Error(
        'A selected photo was removed from this world earlier. Use Add back under Previously ' +
        'in this world; nothing was attached.',
      );
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
    return attachmentRequest(active, selection.sources);
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
      if (apiError !== null && REFERENCE_REFUSALS[apiError.code] !== undefined) {
        notice(REFERENCE_REFUSALS[apiError.code]!, apiError.code);
        return;
      }
      throw error;
    }
  }

  /** One reviewed photo, added directly; the admission selection is not involved. */
  async function attachOne(source: { captureId: string; evidenceSpanId: string }): Promise<void> {
    await act(async () => {
      const active = getEntry();
      if (active === null) throw new Error('Open a saved world before adding photos to it.');
      if (deps.attachSources === undefined) {
        throw new Error('Reference attachment is unavailable for this saved world.');
      }
      notice('');
      pendingAttachment = attachmentRequest(active, Object.freeze([Object.freeze({ ...source })]));
      persistAttachment();
      await sendPendingAttachment();
    });
  }

  function openReviewFor(captureId: string): void {
    awaitingReview.add(captureId);
    // The existing human review, with only this photo selected. Recording that review adds
    // nothing back; the person chooses Add back again afterwards.
    if (journal.pending === null && journal.sources.some((row) => row.capture_id === captureId)) {
      journal.memberIds = [captureId];
      forgetConsent();
      persist();
    }
    ui.workflow.open = true;
    if ([...ui.source.options].some((option) => option.value === captureId)) {
      ui.source.value = captureId;
      correction = undefined;
      renderReview();
    }
  }

  async function addReferenceBack(removed: SavedWorldPreviousSourceAttachment): Promise<void> {
    if (!newReviewFor(removed)) {
      openReviewFor(removed.captureId);
      notice(
        'This photo needs a new review before it can be added back. It is selected in Add or ' +
        'review photos: inspect it, record your review, then choose Add back again. Nothing is ' +
        'added back until you do.',
      );
      reflect();
      return;
    }
    await act(async () => {
      const active = getEntry();
      if (active === null) throw new Error('Open a saved world before adding photos back.');
      pendingMembership = Object.freeze({
        kind: 'rebind' as const,
        entryId: active.entryId,
        operationId: crypto.randomUUID(),
        baseRevision: active.revision,
        authoredVersionId: active.authoredVersionId,
        authoredStateSha256: active.authoredStateSha256,
        authoredEditSeq: active.authoredEditSeq,
        styleVersionId: active.styleVersionId,
        sources: Object.freeze([Object.freeze({
          captureId: removed.captureId, evidenceSpanId: removed.evidenceSpanId,
        })]),
      });
      persistMembership();
      await sendPendingMembership();
    });
  }

  async function removeReference(attachmentId: string): Promise<void> {
    await act(async () => {
      const active = getEntry();
      if (active === null) throw new Error('Open a saved world before removing photos from it.');
      confirmingRemoval = null;
      pendingMembership = Object.freeze({
        kind: 'detach' as const,
        entryId: active.entryId,
        operationId: crypto.randomUUID(),
        baseRevision: active.revision,
        authoredVersionId: active.authoredVersionId,
        authoredStateSha256: active.authoredStateSha256,
        authoredEditSeq: active.authoredEditSeq,
        styleVersionId: active.styleVersionId,
        attachmentIds: Object.freeze([attachmentId]),
      });
      persistMembership();
      await sendPendingMembership();
    });
  }

  async function sendPendingMembership(): Promise<void> {
    const request = pendingMembership;
    if (request === null || entryClient === null) return;
    const active = getEntry();
    if (active === null || active.entryId !== request.entryId) {
      throw new Error('This retained photo change belongs to a different saved world. Open that world to retry it.');
    }
    try {
      let updated = request.kind === 'detach'
        ? await entryClient.detachSources(request)
        : await entryClient.rebindSources(request);
      pendingMembership = null;
      persistMembership();
      if (deps.refreshEntry !== undefined) {
        // Hands the new revision to the page that owns the open world, so its next edit uses it.
        try { updated = await deps.refreshEntry(request.entryId); } catch { /* The reply above is current. */ }
      }
      entry = updated;
      if (request.kind === 'rebind') {
        for (const source of request.sources) awaitingReview.delete(source.captureId);
      }
      notice(request.kind === 'detach'
        ? 'Removed from this world. The photo is still in your library.'
        : 'Added back to this world with its new review.');
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null;
      if (apiError === null || apiError.status < 400 || apiError.status >= 500 ||
          apiError.status === 408) {
        notice(
          'The change did not reach the server or was not answered. Retry sends exactly the ' +
          'same request, and it takes effect at most once.',
          apiError === null ? null : apiError.code,
        );
        return;
      }
      // Answered: the exact request cannot succeed by repeating it.
      pendingMembership = null;
      persistMembership();
      if (apiError.code === 'stale_saved_world_entry' && deps.refreshEntry !== undefined) {
        try { entry = await deps.refreshEntry(request.entryId); } catch { /* Reload can retry. */ }
      }
      if (request.kind === 'rebind' &&
          (apiError.code === 'review_required' || apiError.code === 'authority_unavailable')) {
        for (const source of request.sources) openReviewFor(source.captureId);
      }
      notice(REFERENCE_REFUSALS[apiError.code] ?? 'The change was not saved.', apiError.code);
    }
  }
  ui.processingRights.onChange(() => { reflect(); });
  ui.reviewRights.onChange(() => { reflect(); });
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
    if (result.accepted.length) { journal.memberIds = result.accepted.map(s => s.capture_id); forgetConsent(); }
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
    forgetConsent();
  };
  ui.link.onclick = () => { void act(async () => {
    if (journal.pending) throw new Error('Resolve or discard pending admission first.');
    await reviewApi.link([...selected.values()], ui.linkedSubject.value || undefined);
    selected.clear(); choices.clear(); forgetConsent(); await reload();
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
  ui.retryMembership.onclick = () => { void act(sendPendingMembership); };
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
          membershipStorageKey = `${storageKey}:world-entry:${active.entryId}:source-membership`;
          const savedMembership = storage?.getItem(membershipStorageKey);
          if (savedMembership) {
            const retained = JSON.parse(savedMembership) as MembershipRequest;
            if (retained.entryId === active.entryId) pendingMembership = retained;
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
      if (pendingMembership) {
        notice('An interrupted photo change is kept. Retry sends exactly the same request.');
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

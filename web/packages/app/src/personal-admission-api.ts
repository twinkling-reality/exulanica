/** Exact original upload and explicit personal admission; policy stays on the server. */
import { ApiError, Transport, toApiError, type TransportOptions } from '@exulanica/graph-client';

export interface PersonalSource {
  readonly capture_id: string;
  readonly sha256: string;
  readonly bytes: number;
}
export interface UploadResult {
  readonly batch_id: string;
  readonly queued_job_id: string | null;
  readonly accepted: readonly (PersonalSource & { readonly filename: string; readonly status: string })[];
  readonly refused: readonly { readonly filename: string; readonly reason: string; readonly detail: string }[];
}
export interface PersonalAuthority {
  readonly account_authority_basis: string;
  readonly authorized_at: string;
  readonly valid_until: string;
}
export const HUMAN_ATTESTATION = 'I personally inspected every exact photograph in this inventory and reviewed all people '
  + 'and sensitive person regions, including any missed by the detector.';
/**
 * The role whose estimates can be placed in a world. The placed-estimate inspector stops this role
 * for its photo; every word it is shown with still comes from the server's offer for it.
 */
export const DEPTH_ROLE = 'depth';
export interface ModelRightRequest {
  readonly role: string;
  readonly valid_until: string;
  /** The offer's notice, exactly as the server stated it. The server refuses any other text. */
  readonly notice: string;
}
export interface ModelRightState {
  readonly right_id: string;
  readonly capture_id: string;
  readonly operation: string;
  readonly model: { readonly provider: string; readonly role: string; readonly model_id: string; readonly revision: string | null };
  readonly destination: string;
  readonly granted_at: string;
  readonly valid_until: string;
  readonly withdrawn: boolean;
  readonly state?: 'current' | 'ended';
  /** Whether it was granted against the words the server states for its role now. */
  readonly notice_current?: boolean;
}
/**
 * One model right a person may give, with every word the app shows for it, as the server states
 * them in `GET /personal-admission`. The browser keeps no copy of any of these words.
 */
export interface ModelRightOffer {
  readonly role: string;
  /** The admission that carries the grant: detection starts processing, review permits depth. */
  readonly offered_with: 'detect' | 'review';
  readonly label: string;
  readonly short: string;
  /** Shown in full before the tick, and sent back unchanged with the grant. */
  readonly notice: string;
  readonly stop: string;
  readonly stop_action: string;
  readonly stop_confirm: string;
  readonly destination: string;
  readonly models: readonly ModelRightState['model'][];
}
export interface PersonalAdmission {
  readonly request_id?: string;
  readonly members: readonly (PersonalSource & { readonly review: 'not-reviewed' | 'no-person' | 'confirmed-regions' })[];
  readonly purpose: string;
  readonly authority: PersonalAuthority;
  readonly recorded_at: string;
  readonly operation: 'detect' | 'review';
  readonly reviewed_by_name?: string;
  readonly attestation?: string;
  /** Empty unless the account holder ticked a box. Nothing here is implied by the review. */
  readonly model_rights?: readonly ModelRightRequest[];
}
export interface AdmissionResult {
  readonly batch_id: string;
  readonly queued_job_id: string;
  readonly receipts: readonly {
    readonly capture_id: string;
    readonly authorization_id: string;
    readonly screening_id: string;
    readonly eligibility_state: string;
    readonly model_right_ids?: readonly string[];
    readonly model_rights?: readonly ModelRightState[];
  }[];
}
export async function sha256(data: ArrayBuffer): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))]
    .map(n => n.toString(16).padStart(2, '0')).join('');
}
export class PersonalAdmissionApi {
  readonly requests: PersonalRequestClient;
  constructor(private readonly options: TransportOptions) { this.requests = new PersonalRequestClient(options); }

  async status(): Promise<PersonalStatus> {
    return new Transport({ ...this.options, signal: AbortSignal.timeout(20_000) }).getJson('/personal-admission');
  }

  async upload(files: readonly File[]): Promise<UploadResult> {
    if (!files.length) throw new Error('Choose original photographs first.');
    const originals = new Map<string, number>();
    const form = new FormData();
    for (const file of files) {
      originals.set(await sha256(await file.arrayBuffer()), file.size);
      form.append('files', file, file.name);
    }
    // Transport is JSON-only. Multipart must let the browser supply its boundary.
    const headers: Record<string, string> = {};
    // Empty bearer authorization blocks the API's account-cookie fallback.
    if (this.options.token) headers['authorization'] = `Bearer ${this.options.token}`;
    if (this.options.csrfToken) headers['x-csrf-token'] = this.options.csrfToken;
    const response = await (this.options.fetch ?? globalThis.fetch)(
      `${this.options.baseUrl.replace(/\/+$/, '')}/intake`, {
        method: 'POST', headers, credentials: 'include',
        body: form, signal: AbortSignal.timeout(120_000),
      });
    if (!response.ok) throw await toApiError(response);
    const wire = await response.json() as Omit<UploadResult, 'accepted'> & {
      accepted: { capture_id: string; blob_sha256: string; filename: string; status: string }[];
    };
    const accepted = wire.accepted.map(part => {
      const bytes = originals.get(part.blob_sha256);
      if (bytes === undefined) throw new Error('Upload receipt does not match the selected original bytes.');
      return { capture_id: part.capture_id, sha256: part.blob_sha256, bytes,
        filename: part.filename, status: part.status };
    });
    return { ...wire, accepted: [...new Map(accepted.map(p => [p.capture_id, p])).values()] };
  }

  /** Caller retains the exact dated body if delivery is interrupted. Never change it on retry. */
  async admit(body: PersonalAdmission): Promise<AdmissionResult> {
    if (!body.members.length || !body.purpose.trim() || !body.authority.account_authority_basis.trim()) {
      throw new Error('Exact sources, purpose and account authority are required.');
    }
    if (body.operation === 'review' && (!body.reviewed_by_name?.trim()
      || body.attestation !== HUMAN_ATTESTATION || body.members.some(m => m.review === 'not-reviewed'))) {
      throw new Error('Complete the named human review and exact-photo attestation.');
    }
    return this.requests.post<AdmissionResult>('/personal-admission', { ...body });
  }

  /**
   * Stop one model right now. Final and idempotent on the server, so it needs no retry journal:
   * sending it twice is the same as sending it once, and a lost answer is recovered by reloading.
   */
  async stopModelRight(rightId: string): Promise<ModelRightState & { readonly state: string }> {
    return new Transport({ ...this.options, signal: AbortSignal.timeout(20_000) })
      .postJson(`/personal-admission/model-rights/${encodeURIComponent(rightId)}/withdraw`, {});
  }
}

export interface PersonalStatus {
  readonly sources: readonly (PersonalSource & {
    readonly media_type: string;
    readonly authority: (PersonalAuthority & { readonly authorization_id: string; readonly purpose: string }) | null;
    /** Every right this account holder granted over the photograph, current or ended. */
    readonly model_rights?: readonly ModelRightState[];
  })[];
  readonly requests: readonly (Partial<AdmissionResult> & { readonly request_id: string; readonly operation: string })[];
  /** Every right a person may give, depth first. Absent from a server that offers none. */
  readonly model_right_offers?: unknown;
}
interface PendingRequest { path: string; body: Record<string, unknown>; request_id: string }
/** One recoverable browser write at a time, backed by the server's atomic receipt boundary. */
export class PersonalRequestClient {
  private held: PendingRequest | null = null;
  constructor(private readonly options: TransportOptions) {}
  private async key(): Promise<string> {
    return `personal-request:v1:${await sha256(new TextEncoder().encode(`${this.options.baseUrl}\n${this.options.token}`).buffer)}`;
  }
  async pending(): Promise<PendingRequest | null> {
    try {
      const raw = window.sessionStorage.getItem(await this.key());
      this.held = raw ? JSON.parse(raw) as PendingRequest : null;
    } catch { /* In-memory retry remains available if browser storage is disabled. */ }
    return this.held;
  }
  private async save(value: PendingRequest | null): Promise<void> {
    this.held = value;
    try {
      const key = await this.key();
      if (value) window.sessionStorage.setItem(key, JSON.stringify(value));
      else window.sessionStorage.removeItem(key);
    } catch { /* Never discard the in-memory request when storage is unavailable. */ }
  }
  async reconcile(ids: readonly string[]): Promise<void> {
    const pending = await this.pending();
    if (pending && ids.includes(pending.request_id)) await this.save(null);
  }
  async post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    const pending = await this.pending();
    if (pending) throw new Error('Recover the interrupted personal request before recording another decision.');
    const request = { path, body, request_id: typeof body['request_id'] === 'string' ? body['request_id'] : crypto.randomUUID() };
    await this.save(request);
    return this.retry<T>();
  }
  async retry<T>(): Promise<T> {
    const pending = await this.pending();
    if (!pending) throw new Error('There is no interrupted personal request.');
    if (!/^\/(personal-admission|person-regions\/[^/]+\/edits|person-subjects(?:\/[^/]+\/consents)?|identity\/subjects\/(?:link|unlink))$/.test(pending.path)) {
      throw new Error('The retained personal request has an invalid route.');
    }
    try {
      const result = await new Transport({ ...this.options, signal: AbortSignal.timeout(30_000) })
        .postJson<T>(pending.path, { ...pending.body, request_id: pending.request_id });
      await this.save(null);
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408) await this.save(null);
      throw error;
    }
  }
}

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
export interface PersonalAdmission {
  readonly request_id?: string;
  readonly members: readonly (PersonalSource & { readonly review: 'not-reviewed' | 'no-person' | 'confirmed-regions' })[];
  readonly purpose: string;
  readonly authority: PersonalAuthority;
  readonly recorded_at: string;
  readonly operation: 'detect' | 'review';
  readonly reviewed_by_name?: string;
  readonly attestation?: string;
}
export interface AdmissionResult {
  readonly batch_id: string;
  readonly queued_job_id: string;
  readonly receipts: readonly {
    readonly capture_id: string;
    readonly authorization_id: string;
    readonly screening_id: string;
    readonly eligibility_state: string;
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
    const response = await (this.options.fetch ?? globalThis.fetch)(
      `${this.options.baseUrl.replace(/\/+$/, '')}/intake`, {
        method: 'POST', headers: { authorization: `Bearer ${this.options.token}` },
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
}

export interface PersonalStatus {
  readonly sources: readonly (PersonalSource & {
    readonly media_type: string;
    readonly authority: (PersonalAuthority & { readonly authorization_id: string; readonly purpose: string }) | null;
  })[];
  readonly requests: readonly (Partial<AdmissionResult> & { readonly request_id: string; readonly operation: string })[];
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

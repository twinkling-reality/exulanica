// What the world view gives History beyond reading (history.ts's HistoryHost): its writes, H7's keep and H12's GitHub
// question, sent through the workspace's own credentials as the app's other writes are. A read-only copy gives none.
import { accessHeaders } from '/src/config.ts';

type Access = Parameters<typeof accessHeaders>[0] & { readonly baseUrl: string };

/** POST or DELETE `path` with an optional JSON body: the answer's status and body (null where it has none). */
export function historyWrite(access: Access, signal: AbortSignal) {
  return async (method: 'POST' | 'DELETE', path: string, body?: unknown): Promise<{ readonly status: number; readonly body: any }> => {
    const response = await fetch(`${access.baseUrl}${path}`, {
      method, credentials: 'same-origin', signal,
      headers: { ...accessHeaders(access, method), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  };
}

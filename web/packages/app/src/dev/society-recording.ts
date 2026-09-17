import { spawn } from 'node:child_process';
import type { Plugin } from 'vite';

/** Where the development preview reads the living society recording. */
export const SOCIETY_RECORDING_ROUTE = '/preview-api/society/recording';

/**
 * Development only: serve the v4 living society recording, produced on first request by the real
 * Python engine (`scripts/record_living_society.py`) and kept for the life of the dev server.
 *
 * Nothing here simulates. If the engine cannot run, the route answers 503 with the reason and
 * the preview says so; it never falls back to invented inhabitants.
 */
export function societyRecordingPlugin(repositoryRoot: string, ticks = 180): Plugin {
  let recording: Promise<string> | null = null;
  const record = () => new Promise<string>((resolve, reject) => {
    const child = spawn(
      'uv',
      ['run', '--no-sync', 'python', '-m', 'scripts.record_living_society', '--ticks', String(ticks)],
      { cwd: repositoryRoot, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    const output: Buffer[] = [];
    const errors: Buffer[] = [];
    child.stdout.on('data', (chunk: Buffer) => output.push(chunk));
    child.stderr.on('data', (chunk: Buffer) => errors.push(chunk));
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve(Buffer.concat(output).toString('utf8'));
      else reject(new Error(`the recording engine exited with ${code}: ${Buffer.concat(errors).toString('utf8').slice(-600)}`));
    });
  });
  return {
    name: 'exulanica-living-society-recording',
    configureServer(server) {
      server.middlewares.use(SOCIETY_RECORDING_ROUTE, (request, response) => {
        response.setHeader('cache-control', 'no-store');
        response.setHeader('content-type', 'application/json; charset=utf-8');
        if (request.method !== 'GET') {
          response.statusCode = 405;
          response.end(JSON.stringify({ code: 'preview_read_only', detail: 'The recording is read only.' }));
          return;
        }
        recording ??= record();
        recording.then(
          (body) => response.end(body),
          (error: unknown) => {
            recording = null;
            response.statusCode = 503;
            response.end(JSON.stringify({
              code: 'society_recording_unavailable',
              detail: error instanceof Error ? error.message : String(error),
            }));
          },
        );
      });
    },
  };
}

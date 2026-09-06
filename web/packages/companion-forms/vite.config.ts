import { fileURLToPath } from 'node:url';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { defineConfig, type Plugin } from 'vite';

const resultsDir = fileURLToPath(new URL('../../companion-form-results', import.meta.url));

/**
 * The result sink, for the same reason ADR-0003's harness has one.
 *
 * A measured run has to happen in a visible foreground window, because a hidden pane throttles
 * requestAnimationFrame and invalidates the numbers, and a foreground window is exactly the one
 * whose console an automated driver cannot read. The page posts its own summary back and the
 * server writes it, so the run is both foreground and automatable.
 *
 * Dev-server only, local only, and it writes nothing but the JSON body it was handed.
 */
function resultSink(): Plugin {
  return {
    name: 'exulanica-companion-form-result-sink',
    configureServer(server) {
      server.middlewares.use('/__forms/result', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end('POST only');
          return;
        }
        const chunks: Buffer[] = [];
        req.on('data', (chunk: Buffer) => chunks.push(chunk));
        req.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8');
          mkdirSync(resultsDir, { recursive: true });
          const stamp = new Date().toISOString().replace(/[:.]/g, '-');
          const file = join(resultsDir, `companion-forms-${stamp}.json`);
          writeFileSync(file, body);
          writeFileSync(join(resultsDir, 'latest.json'), body);
          server.config.logger.info(`companion form result written: ${file}`);
          res.statusCode = 204;
          res.end();
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [resultSink()],
  server: {
    // A live-reload round trip inside a measurement window corrupts it.
    hmr: false,
  },
  build: { target: 'es2022' },
});

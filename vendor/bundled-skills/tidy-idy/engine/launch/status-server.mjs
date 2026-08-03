// engine/launch/status-server.mjs — loopback status page while a run is in flight.
//
// Started as soon as the project lock is held, BEFORE the long analysis pass, so
// a browser tab can show live progress and a second click can re-open it.

import http from 'node:http';
import fsp from 'node:fs/promises';

import { readStatus, renderStatusPage } from './run-status.mjs';

export const LOOPBACK = '127.0.0.1';

/**
 * @param {{reportDir: string, port?: number, host?: string, fs?: object, log?: Function}} opts
 */
export async function serveRunStatus({
  reportDir,
  port = 0,
  host = LOOPBACK,
  fs = fsp,
  log = () => {},
  title = 'Tidy-Idy',
} = {}) {
  if (!reportDir) throw new Error('serveRunStatus needs reportDir');

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || '/', `http://${host}`);
    const route = url.pathname;
    try {
      if (req.method === 'GET' && (route === '/' || route === '/status')) {
        const html = renderStatusPage({ title, pollUrl: '/api/status' });
        res.writeHead(200, {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        });
        res.end(html);
        return;
      }
      if (req.method === 'GET' && route === '/api/status') {
        const st = (await readStatus(reportDir, { fs })) || {
          phase: 'starting',
          message: 'Starting…',
        };
        res.writeHead(200, {
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'no-store',
        });
        res.end(`${JSON.stringify(st)}\n`);
        return;
      }
      if (req.method === 'GET' && route === '/api/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, tool: 'tidy-idy-status' }));
        return;
      }
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'not found' }));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err && err.message }));
    }
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.removeListener('error', reject);
      resolve();
    });
  });

  const bound = server.address().port;
  const baseUrl = `http://${host}:${bound}`;
  log(`status page at ${baseUrl}`);

  return {
    port: bound,
    host,
    baseUrl,
    url: `${baseUrl}/`,
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}

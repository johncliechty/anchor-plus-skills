import test from 'node:test';
import assert from 'node:assert';
import { spawn } from 'node:child_process';
import path from 'node:path';
import http from 'node:http';
import { anchorSpawnSync } from '../../lib/spawn.mjs';

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

test('Wave 6 - Live route-table walker', async () => {
    // 1. Enumerate routes by invoking python
    const dumpCmd = anchorSpawnSync('python', ['-c', 'import sys, json; sys.path.insert(0, "."); import route_table; print(json.dumps(route_table.table_dump()))'], { cwd: path.resolve(import.meta.dirname, '../../') });
    assert.strictEqual(dumpCmd.status, 0, 'Failed to dump routes');
    const routes = JSON.parse(dumpCmd.stdout);

    assert.ok(routes.length > 0, 'Should have routes');

    // 2. Boot a fresh instance
    const port = 8781;
    const serverProcess = spawn('python', ['anchor_gui.py', '--port', port.toString(), '--no-browser'], {
        cwd: path.resolve(import.meta.dirname, '../../'),
        stdio: ['ignore', 'ignore', 'pipe'],
        env: { ...process.env, ANCHOR_AUTH_MODE: 'enforce' }
    });

    let booted = false;
    try {
        // Wait for boot
        for (let i = 0; i < 20; i++) {
            try {
                const res = await fetch(`http://127.0.0.1:${port}/`, { method: 'OPTIONS' });
                booted = true;
                break;
            } catch (e) {
                await sleep(250);
            }
        }
        assert.ok(booted, 'Server failed to boot');

        for (const route of routes) {
            // Asserts each route declares a class
            assert.ok(route.class === 'api' || route.class === 'page', `Route ${route.method} ${route.path} lacks a valid class: ${route.class}`);
            
            // Asserts 401/deny without credentials
            let actualPath = route.path;
            if (route.match === 'prefix') {
                actualPath += 'test_suffix';
            }
            if (actualPath.endsWith('*')) {
                actualPath = actualPath.replace('*', '');
                actualPath = actualPath + '/test_probe';
            }
            
            console.log(`[WAVE6] Fetching ${route.method} ${actualPath} (auth: ${route.auth}, kind: ${route.kind})`);
            
            if (route.kind === 'upgrade') {
                // asserts WS upgrade refused before the 101 completes
                const status = await new Promise((resolve, reject) => {
                    const req = http.get(`http://127.0.0.1:${port}${actualPath}`, {
                        headers: {
                            'Upgrade': 'websocket',
                            'Connection': 'Upgrade'
                        }
                    });
                    req.on('response', (res) => resolve(res.statusCode));
                    req.on('error', reject);
                });
                assert.strictEqual(status, 401, `WS Upgrade ${actualPath} should 401 without credentials, got ${status}`);
            } else if (route.auth === 'open') {
                const res = await fetch(`http://127.0.0.1:${port}${actualPath}`, {
                    method: route.method,
                    body: route.method === 'POST' ? '{}' : undefined,
                });

                // Asserts no route emits a CORS-permissive header
                assert.ok(!res.headers.get('access-control-allow-origin'), 'Should not emit CORS headers');
            } else {
                const res = await fetch(`http://127.0.0.1:${port}${actualPath}`, {
                    method: route.method,
                    body: route.method === 'POST' ? '{}' : undefined,
                });
                
                assert.strictEqual(res.status, 401, `${route.method} ${actualPath} should 401 without credentials, got ${res.status}`);

                // Asserts no route emits a CORS-permissive header
                assert.ok(!res.headers.get('access-control-allow-origin'), 'Should not emit CORS headers');
            }
        }
        
        // Asserts api routes reject requests missing the custom header or carrying a foreign Origin
        // To test this deeply, we'd need a valid token. 
        // But we can test that with a fake token, it returns 401, NOT 403 (since token is checked first for GET).
        // For POST, the token is checked inside do_POST which is AFTER the _wave6_middleware.
        // Wait, I put _wave6_middleware at the TOP of do_POST!
        // So _wave6_middleware runs BEFORE the token check in do_POST!
        // This means for POST, the class constraint (X-Anchor-Request) is checked BEFORE the token.
        // Let's verify this by sending a POST without X-Anchor-Request, it should 403.
        const postRes = await fetch(`http://127.0.0.1:${port}/api/done`, {
            method: 'POST',
            body: '{}'
        });
        assert.strictEqual(postRes.status, 403, 'API POST missing X-Anchor-Request should 403 (checked before token)');
        
        const postResWithHeader = await fetch(`http://127.0.0.1:${port}/api/done`, {
            method: 'POST',
            headers: { 'X-Anchor-Request': '1' },
            body: '{}'
        });
        assert.strictEqual(postResWithHeader.status, 401, 'API POST with X-Anchor-Request should pass CSRF and fail auth with 401');

        const postResForeignOrigin = await fetch(`http://127.0.0.1:${port}/api/done`, {
            method: 'POST',
            headers: { 'X-Anchor-Request': '1', 'Origin': 'https://evil.com' },
            body: '{}'
        });
        assert.strictEqual(postResForeignOrigin.status, 403, 'API POST with foreign Origin should 403');
        
    } finally {
        serverProcess.kill('SIGKILL');
    }
});

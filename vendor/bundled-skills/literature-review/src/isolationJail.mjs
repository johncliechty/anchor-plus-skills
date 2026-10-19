// Wave 1 — network-denial and shared-memory jail for isolated workers.
// Installed inside the worker process before any task code loads. Network
// access is deny-by-default: only hostnames on the per-spawn allowlist pass.
// Unified shared memory (SharedArrayBuffer, shared WebAssembly.Memory) is
// denied outright — cross-thread state must flow through telemetry IPC and
// terminal joins instead.

import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns';

export class IsolationViolationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'IsolationViolationError';
  }
}

export class NetworkAccessDeniedError extends IsolationViolationError {
  constructor(api, target) {
    super(`network access denied: ${api} -> ${target}`);
    this.name = 'NetworkAccessDeniedError';
    this.api = api;
    this.target = target;
  }
}

export class SharedMemoryDeniedError extends IsolationViolationError {
  constructor(api) {
    super(`unified shared memory is denied inside isolated workers: ${api}`);
    this.name = 'SharedMemoryDeniedError';
    this.api = api;
  }
}

// Allowlist entries are hostnames, matched case-insensitively; a leading
// '*.' entry authorizes any subdomain of the suffix (never the bare suffix).
export function isHostAuthorized(host, allowlist = []) {
  if (typeof host !== 'string' || host.length === 0) return false;
  const candidate = host.toLowerCase().replace(/\.$/, '');
  for (const entry of allowlist) {
    if (typeof entry !== 'string' || entry.length === 0) continue;
    const rule = entry.toLowerCase().replace(/\.$/, '');
    if (rule.startsWith('*.')) {
      const suffix = rule.slice(1); // '.example.com'
      if (candidate.length > suffix.length && candidate.endsWith(suffix)) return true;
    } else if (candidate === rule) {
      return true;
    }
  }
  return false;
}

function safeReporter(onViolation) {
  return (violation) => {
    if (typeof onViolation !== 'function') return;
    try {
      onViolation(violation);
    } catch {
      // A broken reporter must never disable the jail.
    }
  };
}

function hostFromRequestArgs(args) {
  const [first] = args;
  try {
    if (typeof first === 'string') return new URL(first).hostname;
    if (first instanceof URL) return first.hostname;
    if (first && typeof first === 'object') {
      return first.hostname || (typeof first.host === 'string' ? first.host.split(':')[0] : '') || 'localhost';
    }
  } catch {
    // fall through — an unparseable target is treated as localhost (denied
    // unless explicitly authorized)
  }
  return 'localhost';
}

function connectTargetFromArgs(args) {
  let first = args[0];
  // net.connect() hands Socket.prototype.connect a normalized [options, cb] array.
  if (Array.isArray(first)) first = first[0];
  if (first && typeof first === 'object') {
    if (first.path) return { host: null, target: `ipc:${first.path}` };
    const host = first.host || 'localhost';
    return { host, target: `${host}:${first.port}` };
  }
  if (typeof first === 'number') {
    const host = typeof args[1] === 'string' ? args[1] : 'localhost';
    return { host, target: `${host}:${first}` };
  }
  if (typeof first === 'string') {
    return { host: null, target: `ipc:${first}` };
  }
  return { host: null, target: String(first) };
}

export function installNetworkJail({ allowlist = [], onViolation } = {}) {
  const report = safeReporter(onViolation);
  const patched = [];

  const deny = (api, target) => {
    const err = new NetworkAccessDeniedError(api, target);
    report({ kind: 'network', api, target, message: err.message });
    throw err;
  };
  const guard = (api, host, target) => {
    if (host === null || !isHostAuthorized(host, allowlist)) deny(api, target ?? host);
  };

  if (typeof globalThis.fetch === 'function') {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async function jailedFetch(resource, init) {
      let host = null;
      let target = String(resource);
      try {
        const url = new URL(typeof resource === 'string' || resource instanceof URL ? resource : resource?.url);
        host = url.hostname;
        target = url.href;
      } catch {
        // unparseable -> denied below
      }
      guard('fetch', host, target);
      return originalFetch(resource, init);
    };
    patched.push('fetch');
  }

  const originalSocketConnect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function jailedConnect(...args) {
    const { host, target } = connectTargetFromArgs(args);
    guard('net.connect', host, target);
    return originalSocketConnect.apply(this, args);
  };
  patched.push('net.Socket.prototype.connect');

  const originalTlsConnect = tls.connect;
  tls.connect = function jailedTlsConnect(...args) {
    const { host, target } = connectTargetFromArgs(args);
    guard('tls.connect', host, target);
    return originalTlsConnect.apply(tls, args);
  };
  patched.push('tls.connect');

  for (const [mod, name] of [[http, 'http'], [https, 'https']]) {
    for (const fn of ['request', 'get']) {
      const original = mod[fn];
      mod[fn] = function jailedHttp(...args) {
        const host = hostFromRequestArgs(args);
        guard(`${name}.${fn}`, host, host);
        return original.apply(mod, args);
      };
      patched.push(`${name}.${fn}`);
    }
  }

  const dnsApis = ['lookup', 'resolve', 'resolve4', 'resolve6'];
  for (const fn of dnsApis) {
    const original = dns[fn];
    if (typeof original !== 'function') continue;
    dns[fn] = function jailedDns(hostname, ...rest) {
      guard(`dns.${fn}`, typeof hostname === 'string' ? hostname : null, String(hostname));
      return original.call(dns, hostname, ...rest);
    };
    patched.push(`dns.${fn}`);
  }
  for (const fn of dnsApis) {
    const original = dns.promises?.[fn];
    if (typeof original !== 'function') continue;
    dns.promises[fn] = async function jailedDnsPromise(hostname, ...rest) {
      guard(`dns.promises.${fn}`, typeof hostname === 'string' ? hostname : null, String(hostname));
      return original.call(dns.promises, hostname, ...rest);
    };
    patched.push(`dns.promises.${fn}`);
  }

  return { patched, allowlist: [...allowlist] };
}

export function installSharedMemoryJail({ onViolation } = {}) {
  const report = safeReporter(onViolation);
  const patched = [];

  const denyShared = (api) => {
    const err = new SharedMemoryDeniedError(api);
    report({ kind: 'shared-memory', api, target: api, message: err.message });
    throw err;
  };

  if (typeof globalThis.SharedArrayBuffer === 'function') {
    globalThis.SharedArrayBuffer = function SharedArrayBuffer() {
      denyShared('SharedArrayBuffer');
    };
    patched.push('SharedArrayBuffer');
  }

  if (typeof WebAssembly !== 'undefined' && typeof WebAssembly.Memory === 'function') {
    const OriginalMemory = WebAssembly.Memory;
    function JailedMemory(descriptor) {
      if (descriptor && descriptor.shared) denyShared('WebAssembly.Memory');
      return new OriginalMemory(descriptor);
    }
    JailedMemory.prototype = OriginalMemory.prototype;
    WebAssembly.Memory = JailedMemory;
    patched.push('WebAssembly.Memory');
  }

  return { patched };
}

export function installIsolationJail({ allowlist = [], onViolation } = {}) {
  const network = installNetworkJail({ allowlist, onViolation });
  const sharedMemory = installSharedMemoryJail({ onViolation });
  return { patched: [...network.patched, ...sharedMemory.patched], allowlist: network.allowlist };
}

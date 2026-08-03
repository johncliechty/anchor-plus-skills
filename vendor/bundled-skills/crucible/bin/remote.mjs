// remote.mjs — Crucible's GitHub-private remote + push-at-gates seam (Wave 9).
//
// MASTER-PLAN §11 / D13: local commits per round are automatic (Foreman's git
// hygiene already does that), but the REMOTE is deliberately conservative — create a
// PRIVATE GitHub repo and push ONLY at the two approval gates, asking the human EACH
// TIME. NEVER auto-push. Foreman itself never pushes (`git-hygiene.mjs` is push-free
// by design), so this is NEW capability Crucible owns — not a fork.
//
// HERMETIC + TESTABLE WITHOUT NETWORK: every outward-facing step goes through an
// INJECTED transport (`runGit` for git, `runGh` for the GitHub CLI), exactly the
// seam shape of Wave-1's `agent()` and Wave-4's `spawn`. Tests inject a fake remote
// and drive the full confirmation/gate logic with zero subprocesses and zero network.
//
// The safety invariant proved by the tests: there is exactly ONE code path that
// pushes — `pushAtGate` — and it pushes ONLY when (1) the gate is an approval gate
// AND (2) the human confirmed (`approved:true`). Anything else HALTs or no-ops; the
// transport's push is never reached.

import { spawnSync } from 'node:child_process';

import { HaltError, haltForHuman } from './crucible-lib.mjs';

/**
 * The ONLY gates a push is permitted at — the two user-approval gates (§11/D13).
 * The North-Star lock is a HALT gate too, but D13 scopes pushes to the two approval
 * gates, so a push requested elsewhere is refused (never auto-push at a non-gate).
 */
export const PUSH_GATES = new Set(['master-plan-approval', 'implementation-plan-approval']);

// ---------------------------------------------------------------------------
// Default live transports — real `git` / `gh`. Only ever invoked AFTER a human
// confirmed a push at a gate, so spawning here is intended (not env-gated like the
// model seams, which guard against accidental billable calls).
// ---------------------------------------------------------------------------

/** Run `git <args>` in `repoDir`, normalized to `{status,stdout,stderr,error}`. */
export function defaultRunGit(repoDir, args) {
  const r = spawnSync('git', args, { cwd: repoDir, encoding: 'utf8' });
  return { status: r.status ?? null, stdout: String(r.stdout ?? ''), stderr: String(r.stderr ?? ''), error: r.error ?? null };
}

/** Run `gh <args>` in `repoDir`, normalized identically (GitHub CLI). */
export function defaultRunGh(repoDir, args) {
  const r = spawnSync('gh', args, { cwd: repoDir, encoding: 'utf8' });
  return { status: r.status ?? null, stdout: String(r.stdout ?? ''), stderr: String(r.stderr ?? ''), error: r.error ?? null };
}

// ---------------------------------------------------------------------------
// The remote coordinator.
// ---------------------------------------------------------------------------

/**
 * Build the remote coordinator bound to one repo. Holds NO push method other than
 * `pushAtGate`, so the "never auto-push" invariant is structural, not just policy.
 *
 * @param {object}   o
 * @param {string}   o.repoDir                    the managed repo's working dir
 * @param {string}  [o.remoteName='origin']
 * @param {Function}[o.runGit=defaultRunGit]      injected git transport (tests stub it)
 * @param {Function}[o.runGh=defaultRunGh]        injected GitHub-CLI transport
 * @param {Function}[o.log=()=>{}]
 */
export function makeRemote({ repoDir, remoteName = 'origin', runGit = defaultRunGit, runGh = defaultRunGh, log = () => {} } = {}) {
  if (!repoDir) {
    throw new HaltError('makeRemote requires a repoDir', 'pass the managed repo dir: makeRemote({ repoDir })');
  }

  /** True iff the repo already has a remote configured (no network — reads git config). */
  function hasRemote() {
    const r = runGit(repoDir, ['remote']);
    if (r.error) return false;
    return String(r.stdout || '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean).length > 0;
  }

  /**
   * Create the PRIVATE GitHub repo + wire up the remote (idempotent). Outward-facing,
   * so it is only ever called from inside an APPROVED `pushAtGate`. Uses `gh repo
   * create --private`; on an existing remote it no-ops. Returns `{created, name}`.
   */
  function ensureRemote({ name }) {
    if (hasRemote()) {
      log(`remote: ${remoteName} already configured — not recreating`);
      return { created: false, existing: true, name: null };
    }
    if (!name) {
      throw new HaltError('ensureRemote requires a repo name to create the private GitHub repo', 'pass { name }');
    }
    // PRIVATE always (§11/D13) — and `gh` adds the remote as `origin` via --source/--remote.
    const r = runGh(repoDir, ['repo', 'create', name, '--private', '--source', '.', '--remote', remoteName]);
    if (r.error || (r.status !== 0 && r.status !== null)) {
      throw new HaltError('gh repo create failed', `${r.stderr || r.error?.message || 'non-zero exit'} — create the private repo manually or check \`gh auth status\``);
    }
    log(`remote: created PRIVATE GitHub repo "${name}" and wired ${remoteName}`);
    return { created: true, existing: false, name };
  }

  return {
    repoDir,
    remoteName,
    hasRemote,
    ensureRemote,

    /**
     * Push the work branch to the private remote — the ONLY push path. Pushes ONLY
     * when BOTH hold: (1) `gate` is an approval gate (PUSH_GATES), and (2) the human
     * confirmed (`approved:true`). Without approval it HALTs for confirmation (asking
     * EACH time); at a non-approval gate it refuses. Never auto-pushes.
     *
     * @param {object}  o
     * @param {string}  o.gate                       the gate being crossed
     * @param {string}  o.branch                     the work branch to push
     * @param {boolean} [o.approved=false]           the human's per-push confirmation
     * @param {?string} [o.repoName=null]            name for the private repo if it must be created
     * @param {boolean} [o.createRemote=true]        create the private remote on first push
     * @returns {{pushed:boolean, halted:boolean, gate:string, reason:string,
     *            remoteCreated?:boolean, push?:object, halt?:HaltError}}
     */
    pushAtGate({ gate, branch, approved = false, repoName = null, createRemote = true } = {}) {
      // (1) Only the two approval gates may push (never auto-push elsewhere).
      if (!PUSH_GATES.has(gate)) {
        log(`remote: refusing to push at "${gate}" — not an approval gate`);
        return { pushed: false, halted: false, gate, reason: `"${gate}" is not an approval push-gate (push only at: ${[...PUSH_GATES].join(', ')})` };
      }
      if (!branch) {
        throw new HaltError('pushAtGate requires a branch', 'pass the work branch to push: pushAtGate({ gate, branch })');
      }

      // (2) The human must confirm EACH time — without approval, HALT (never push).
      if (!approved) {
        log(`remote: push at "${gate}" awaiting human confirmation — NOT pushing`);
        return {
          pushed: false,
          halted: true,
          gate,
          reason: 'awaiting the human\'s push confirmation (asked each time; never auto-push)',
          halt: haltForHuman(
            `push branch "${branch}" to the private GitHub remote at the ${gate} gate? (confirm each time — Crucible never auto-pushes)`,
            `confirm-push:${gate}`,
          ),
        };
      }

      // Approved at a real gate — create the private remote on first push, then push.
      let remoteCreated = false;
      if (!hasRemote()) {
        if (!createRemote) {
          throw new HaltError('no remote configured and createRemote is off', 'configure a remote or pass createRemote:true with a repoName');
        }
        remoteCreated = ensureRemote({ name: repoName }).created;
      }

      const r = runGit(repoDir, ['push', '-u', remoteName, branch]);
      if (r.error || (r.status !== 0 && r.status !== null)) {
        log(`remote: push FAILED at "${gate}" (exit ${r.status}) — ${r.stderr || r.error?.message || ''}`);
        return { pushed: false, halted: false, gate, reason: `git push failed: ${r.stderr || r.error?.message || `exit ${r.status}`}`, remoteCreated, push: r };
      }
      log(`remote: pushed "${branch}" to ${remoteName} at the ${gate} gate (human-confirmed)`);
      return { pushed: true, halted: false, gate, reason: 'human-confirmed push at an approval gate', remoteCreated, push: r };
    },
  };
}

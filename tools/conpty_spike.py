"""ConPTY-across-processes spike harness + recorded verdict (rearch W3).

D2 mandates: PTY sessions move behind the supervisor ONLY after a spike proves
the across-process architecture is economically feasible. The architecture
under test is **owner-side PTY + byte proxying over loopback IPC** — the PTY
handle itself never crosses a process boundary (ConPTY handles are
process-local by construction); a separate OWNER process holds the PTY via
``pty_manager`` and serves reads/writes over a loopback socket, exactly the
shape the W15/W16 supervisor would use.

The spike answers the PRE-WRITTEN acceptance questions (frozen with W3, before
any run):

* **Q-LATENCY** — is the median echo round-trip through the cross-process hop
  within :data:`LATENCY_BOUND_MS`? (Interactive typing must not feel laggy.)
* **Q-REATTACH** — after the first client detaches (a dashboard restart), can
  a NEW connection re-attach, receive full replay of prior output, and do live
  I/O — with the owner-held PTY surviving the client's death?
* **Q-COMPLEXITY** — does the whole ownership harness (owner + protocol +
  client legs) fit within :data:`COMPLEXITY_BUDGET_LINES` significant lines?
  (The complexity-budget proxy: if a spike can't stay small, the real thing
  won't.)

``run_spike(backend=...)`` launches the owner as a REAL separate process
(``python tools/conpty_spike.py --owner``), so every byte in the verdict
crossed a genuine process boundary. The ``stub`` leg is deterministic (the
faithful in-memory PTY — proves protocol/re-attach/architecture and measures
the IPC hop); the ``real`` leg drives a live pywinpty/ConPTY ``cmd.exe`` and
is run where a console subsystem exists (opt-in in the gate via
``ANCHOR_SPIKE_REAL_CONPTY=1``; also runnable by hand:
``python tools/conpty_spike.py --run --backend real``).

``record_verdict`` merge-writes the checked-in gate artifacts
``planning/rearch-2026-07/SPIKE-CONPTY-VERDICT.{json,md}`` (per-leg; a leg not
yet run stays honestly marked so — the artifact can never claim a run that
didn't happen). W17 consumes the verdict.

Stdlib only. No visible console: the owner is spawned with
``CREATE_NO_WINDOW`` on Windows.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"
VERDICT_JSON_NAME = "SPIKE-CONPTY-VERDICT.json"
VERDICT_MD_NAME = "SPIKE-CONPTY-VERDICT.md"

# ── the pre-written acceptance questions (frozen BEFORE any spike run) ────────

LATENCY_BOUND_MS = 150.0          # per echo round-trip, median of ECHO_ROUNDS
COMPLEXITY_BUDGET_LINES = 400     # significant (non-blank/non-comment) lines
ECHO_ROUNDS = 5

ACCEPTANCE_QUESTIONS = (
    {"id": "Q-LATENCY",
     "question": f"Is the median echo round-trip through the cross-process "
                 f"hop <= {LATENCY_BOUND_MS:.0f} ms (median of "
                 f"{ECHO_ROUNDS} rounds)?"},
    {"id": "Q-REATTACH",
     "question": "After the first client detaches (simulating a dashboard "
                 "restart), does a new connection re-attach with full replay "
                 "of prior output AND working live I/O, the owner-held PTY "
                 "having survived the client's death?"},
    {"id": "Q-COMPLEXITY",
     "question": f"Does the whole across-process ownership harness fit "
                 f"within {COMPLEXITY_BUDGET_LINES} significant lines?"},
)


class SpikeError(RuntimeError):
    """The spike harness itself failed (not a NO verdict — a broken run)."""


# ── owner process: hold the PTY, serve bytes over loopback ────────────────────

def _owner_serve(backend: str) -> int:  # pragma: no cover - separate process
    """Own a PTY and serve line-JSON ops over a loopback socket.

    Ops: ``{"op": "write", "data": s}`` · ``{"op": "read", "cursor": n}`` ·
    ``{"op": "alive"}`` · ``{"op": "shutdown"}``. Sequential connections are
    accepted until shutdown — that IS the re-attach seam.
    """
    os.environ["ANCHOR_PTY_BACKEND"] = backend
    sys.path.insert(0, str(REPO_ROOT))
    import pty_manager

    cmd = ["cmd.exe"] if backend != "stub" else ["spike-shell"]
    sid = pty_manager.start(cmd)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    print(f"PORT {srv.getsockname()[1]}", flush=True)

    done = False
    while not done:
        conn, _ = srv.accept()
        rfile = conn.makefile("r", encoding="utf-8", newline="\n")
        wfile = conn.makefile("w", encoding="utf-8", newline="\n")
        try:
            for line in rfile:
                req = json.loads(line)
                op = req.get("op")
                if op == "write":
                    pty_manager.write(sid, req.get("data", ""))
                    resp = {"ok": True}
                elif op == "read":
                    resp = pty_manager.read_since(sid,
                                                  int(req.get("cursor", 0)))
                    resp["ok"] = True
                elif op == "alive":
                    resp = {"ok": True, "alive": True}
                elif op == "shutdown":
                    done = True
                    resp = {"ok": True, "bye": True}
                else:
                    resp = {"ok": False, "error": f"unknown op {op!r}"}
                wfile.write(json.dumps(resp) + "\n")
                wfile.flush()
                if done:
                    break
        except (OSError, ValueError):
            pass          # client vanished mid-line — keep the PTY, re-accept
        finally:
            for f in (wfile, rfile):     # drain io-refs so close() is real
                try:
                    f.close()
                except Exception:
                    pass
            conn.close()
    try:
        pty_manager.kill(sid)
    except Exception:
        pass
    srv.close()
    return 0


# ── client side (the "dashboard" process) ─────────────────────────────────────

class _Client:
    """One attach: a connection to the owner's loopback socket."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.rfile = self.sock.makefile("r", encoding="utf-8", newline="\n")
        self.wfile = self.sock.makefile("w", encoding="utf-8", newline="\n")

    def call(self, **req):
        self.wfile.write(json.dumps(req) + "\n")
        self.wfile.flush()
        line = self.rfile.readline()
        if not line:
            raise SpikeError("owner closed the connection mid-call")
        return json.loads(line)

    def echo_roundtrip(self, nonce, cursor, deadline=10.0):
        """Write a nonce and poll until it appears; returns (ms, next_cursor)."""
        t0 = time.perf_counter()
        self.call(op="write", data=f"echo {nonce}\r\n")
        end = t0 + deadline
        text = ""
        while time.perf_counter() < end:
            r = self.call(op="read", cursor=cursor)
            text += r.get("text", "")
            cursor = r.get("next", cursor)
            if nonce in text:
                return (time.perf_counter() - t0) * 1000.0, cursor
            time.sleep(0.005)
        raise SpikeError(f"echo nonce {nonce!r} never came back")

    def close(self):
        # Close the makefile wrappers FIRST: each holds an io-ref on the
        # socket, and CPython only truly closes the OS socket (sending the
        # FIN) once that refcount drains. Without this, sock.close() is a
        # no-op at the OS level, the owner never sees EOF on the dead
        # client, and it blocks in its read loop instead of re-accepting —
        # the re-attach seam wedges. Idempotent; never raises.
        for f in (self.rfile, self.wfile):
            try:
                f.close()
            except Exception:
                pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _spawn_owner(backend):
    """Launch the owner process (hidden console); returns (proc, port)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = dict(os.environ)
    env["ANCHOR_PTY_BACKEND"] = backend
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner",
         "--backend", backend],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, **kwargs)
    line = proc.stdout.readline().strip()
    if not line.startswith("PORT "):
        proc.kill()
        raise SpikeError(f"owner did not report a port (got {line!r})")
    return proc, int(line.split()[1])


def significant_lines() -> int:
    """Significant (non-blank, non-comment) lines of this harness module."""
    n = 0
    for line in Path(__file__).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            n += 1
    return n


def run_spike(backend="stub") -> dict:
    """Run the full spike for one backend leg; returns the leg result dict.

    Never fabricates: a harness failure raises :class:`SpikeError` (a broken
    run is not a NO verdict); a completed run answers every acceptance
    question with a measured pass/fail.
    """
    proc, port = _spawn_owner(backend)
    clients = []
    try:
        # ── leg 1: attach, measure echo round-trips ──
        c1 = _Client(port)
        clients.append(c1)
        cursor = 0
        # settle: swallow any shell banner before timing (real cmd.exe)
        time.sleep(0.5 if backend != "stub" else 0.0)
        r = c1.call(op="read", cursor=cursor)
        cursor = r.get("next", 0)
        nonce1 = f"SPIKE-{os.urandom(4).hex()}"
        times = []
        for i in range(ECHO_ROUNDS):
            ms, cursor = c1.echo_roundtrip(f"{nonce1}-{i}", cursor)
            times.append(ms)
        median_ms = sorted(times)[len(times) // 2]
        # ── detach (the dashboard "restart"): owner must keep the PTY ──
        c1.close()
        time.sleep(0.1)
        if proc.poll() is not None:
            raise SpikeError("owner process died when the client detached")
        # ── leg 2: re-attach — replay + live I/O ──
        c2 = _Client(port)
        clients.append(c2)
        replay = c2.call(op="read", cursor=0)
        replay_ok = f"{nonce1}-0" in replay.get("text", "")
        nonce2 = f"SPIKE-{os.urandom(4).hex()}"
        _, _ = c2.echo_roundtrip(nonce2, replay.get("next", 0))
        c2.call(op="shutdown")
        c2.close()
    finally:
        # The no-leak rail (W3 amendment): the owner — and through it the PTY
        # child it holds — is ALWAYS reaped before run_spike returns, on the
        # green path (shutdown op → clean exit) and on every failure path
        # (close the clients so the owner unblocks, then wait, then kill —
        # and WAIT AGAIN after the kill so no zombie/handle survives).
        for c in clients:
            c.close()                       # idempotent
        if proc.poll() is None:             # failure path: ask it to exit
            try:
                bye = _Client(port)
                bye.call(op="shutdown")
                bye.close()
            except Exception:
                pass                        # dead/wedged owner → wait/kill
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        try:
            proc.stdout.close()
        except Exception:
            pass

    lines = significant_lines()
    answers = {
        "Q-LATENCY": {
            "pass": median_ms <= LATENCY_BOUND_MS,
            "detail": f"median {median_ms:.1f} ms over {ECHO_ROUNDS} rounds "
                      f"(bound {LATENCY_BOUND_MS:.0f} ms)",
            "median_ms": round(median_ms, 1),
        },
        "Q-REATTACH": {
            "pass": bool(replay_ok),
            "detail": "owner survived client detach; re-attach replayed "
                      "prior output and live echo worked"
                      if replay_ok else "re-attach replay missing prior "
                      "output",
        },
        "Q-COMPLEXITY": {
            "pass": lines <= COMPLEXITY_BUDGET_LINES,
            "detail": f"{lines} significant lines "
                      f"(budget {COMPLEXITY_BUDGET_LINES})",
        },
    }
    return {
        "backend": backend,
        "ran": True,
        "verdict": "YES" if all(a["pass"] for a in answers.values()) else "NO",
        "answers": answers,
    }


# ── the checked-in verdict artifacts (merge-written, like W1's inventory) ─────

_VOLATILE_KEYS = ("median_ms", "detail")


def _stable(leg):
    """A leg stripped of volatile measurement fields, for change comparison."""
    if not isinstance(leg, dict):
        return leg
    out = {k: v for k, v in leg.items() if k != "answers"}
    out["answers"] = {
        qid: {k: v for k, v in (a or {}).items() if k not in _VOLATILE_KEYS}
        for qid, a in (leg.get("answers") or {}).items()
    }
    return out


def _render_md(payload) -> str:
    lines = [
        "# Spike verdict — ConPTY across processes (rearch W3)",
        "",
        "Recorded against the PRE-WRITTEN acceptance questions (frozen with "
        "W3, before any run). Architecture under test: owner-side PTY + byte "
        "proxying over loopback IPC — the supervisor shape (D2). Refreshed "
        "mechanically by `tools/conpty_spike.py record_verdict`; never "
        "hand-edited. Consumed by W17 (PTY adoption follow-on, or the "
        "pre-designed drain + honestly-recorded narrowing).",
        "",
        "## Acceptance questions (pre-written)",
        "",
    ]
    for q in payload["questions"]:
        lines.append(f"- **{q['id']}** — {q['question']}")
    lines += ["", "## Legs", ""]
    for leg_name in ("stub", "real"):
        leg = payload["legs"].get(leg_name)
        title = {"stub": "stub PTY (deterministic; architecture + protocol + "
                          "IPC hop)",
                 "real": "real ConPTY (pywinpty cmd.exe)"}[leg_name]
        lines.append(f"### {leg_name} — {title}")
        lines.append("")
        if not leg or not leg.get("ran"):
            lines.append("**NOT YET RUN** — this leg has recorded no verdict. "
                         "Run: `python tools/conpty_spike.py --run --backend "
                         f"{leg_name}` (the gate runs the real leg when "
                         "`ANCHOR_SPIKE_REAL_CONPTY=1`).")
            lines.append("")
            continue
        lines.append(f"**Verdict: {leg['verdict']}**")
        lines.append("")
        for q in payload["questions"]:
            a = leg["answers"].get(q["id"], {})
            mark = "PASS" if a.get("pass") else "FAIL"
            lines.append(f"- {q['id']}: **{mark}** — {a.get('detail', '')}")
        lines.append("")
    lines += [
        "## Reading the verdict",
        "",
        "- The **stub** leg proves the across-process OWNERSHIP architecture "
        "(owner survives client death; re-attach replays; latency of the IPC "
        "hop) deterministically.",
        "- The **real** leg proves live ConPTY behaves the same under an "
        "owner that is not the interactive session.",
        "- A **NO** on either leg routes W17 to the pre-designed drain "
        "(`tools/pre_restart_drain.py`) + the North-Star-amendment narrowing "
        "— PTYs stay dashboard-owned; the jobs half of C4 is unaffected "
        "(non-negotiable).",
        "",
    ]
    return "\n".join(lines)


def record_verdict(leg_result=None, out_dir=None):
    """Merge one leg's result into the checked-in verdict artifacts.

    ``leg_result=None`` just (re)renders the artifacts from what is already
    recorded. Skips the rewrite when nothing but volatile measurements
    changed, so a green re-run keeps the artifact diff-stable. Returns the
    ``(json_path, md_path)`` tuple.
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / VERDICT_JSON_NAME
    md_path = out / VERDICT_MD_NAME

    payload = {"schema": 1, "spike": "conpty-across-processes",
               "questions": list(ACCEPTANCE_QUESTIONS), "legs": {}}
    if json_path.exists():
        try:
            prior = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(prior.get("legs"), dict):
                payload["legs"] = prior["legs"]
        except (json.JSONDecodeError, OSError):
            pass
    changed = False
    if leg_result is not None:
        prior_leg = payload["legs"].get(leg_result["backend"])
        changed = _stable(prior_leg) != _stable(leg_result)
        payload["legs"][leg_result["backend"]] = leg_result

    if changed or not json_path.exists():
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True)
                             + "\n", encoding="utf-8")
    # The md carries volatile measurement text — rewrite it only on a REAL
    # change (or first write), so a green re-run keeps git status clean.
    if changed or not md_path.exists():
        md_path.write_text(_render_md(payload), encoding="utf-8")
    return json_path, md_path


def main(argv=None):  # pragma: no cover - thin CLI shim
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--owner" in argv:
        backend = "stub"
        if "--backend" in argv:
            backend = argv[argv.index("--backend") + 1]
        return _owner_serve(backend)
    backend = "stub"
    if "--backend" in argv:
        backend = argv[argv.index("--backend") + 1]
    result = run_spike(backend=backend)
    jp, mp = record_verdict(result)
    print(json.dumps(result, indent=2))
    # ASCII-only status line: the console default encoding on the live host
    # is cp1252, which cannot encode U+2192 ("→") — the print crashed there
    # (observed 2026-07-03). Keep the message encoding-safe (rearch W6c).
    print(f"recorded -> {jp}\nrendered -> {mp}")
    return 0 if result["verdict"] == "YES" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

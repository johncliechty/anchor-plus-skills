"""Skill Foundry v2 — Wave 10: the Foundry GUI WRITE surface (op invocations).

The DESCRIPTION's load-bearing decision #2 ("mutations are runs, not
endpoints") made concrete for the GUI: every mutative action the Foundry
page exposes is an INVOCATION of a Wave-7/8 control-plane op, dispatched
headlessly through ``foundry_ops.run_control_op`` (job_runner + the Wave-3
generic runner) — confirm-token-gated, write-scoped, and auto-journaled.
This module NEVER touches a file itself; it only builds payloads, mints the
single-use confirm token that carries the human's explicit approval, and
hands off to the engine:

* :func:`create_skill`       — "create a skill"   → ``foundry.scaffold_skill``
* :func:`north_star_propose` — "edit a North Star" → ``foundry.edit_north_star``
  (the propose leg: parks a reviewable diff, writes nothing to the skill)
* :func:`north_star_apply`   — the apply leg of the same op (explicit human
  confirm; prior version retained; branch commit)
* :func:`sync_autoload`      — "clickable in Anchor" → ``foundry.register_autoload``
  (regenerates Anchor's clickable skill set from map.json v2 alone)
* :func:`run_sleep_session`  — the SPLIT seam: targets the DECLARED op
  interface ``foundry.sleep_session`` whose body the separate foundry-kernel
  build delivers; until that op is registered this resolves to the honest
  "sleep session not yet wired (foundry build pending)" status — the GUI
  seam is present and tested, nothing is faked.

An action called WITHOUT ``confirm=True`` refuses BEFORE anything is minted
or dispatched — the explicit confirm IS the human approval the runner's
mutate gate spends (``skill_runner.issue_confirm_token`` → one dispatch).

2ND-SURFACE HONESTY (gated by ``tests/test_foundry_gui_write_w10.py``):
every implemented GUI verb maps to a DR-01-inventory op with a headless CLI
host (``python foundry_ops.py <op>``) — the GUI invokes the same machinery
the headless path runs, so there is no GUI-only code path and no GUI-side
file write. :func:`second_surface_honesty` enforces this structurally: it
re-applies the Wave-9 anti-theater scan to THIS module's source and globals
(no mutation primitive, no parallel store) and checks the verb inventory.

Stdlib only (Anchor's no-dep rule) + the product seams ``foundry_decisions``
/ ``foundry_ops`` / ``skill_runner``.
"""

import sys
from pathlib import Path

import foundry_decisions as _fd
import foundry_ops as _fo
import skill_runner as _sr


# ── Constants ────────────────────────────────────────────────────────────────

#: Wave-1 anti-drift convention: the write surface traces to the North Star.
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                        _fd.NS_MANIFEST_RUNNER)

#: The DECLARED sleep-session op interface (SPLIT NOTE, frozen plan Wave 10):
#: the op BODY ships from the separate foundry-kernel build + integration —
#: this build wires the GUI seam only and answers honestly until then.
SLEEP_SESSION_OP = "foundry.sleep_session"

#: The honest pending status the sleep seam resolves to while the op body is
#: not yet registered (the exact wording the plan's done-when asks for).
SLEEP_PENDING_REASON = "sleep session not yet wired (foundry build pending)"

#: GUI verb → the control-plane op it invokes. Every entry MUST be a
#: DR-01-inventory op with a headless CLI host (the 2nd-surface honesty
#: check enforces both). Immutable by design — this surface holds no state.
IMPLEMENTED_VERBS = (
    ("create_skill", _fo.OP_SCAFFOLD),
    ("north_star_propose", _fo.OP_EDIT_NORTH_STAR),
    ("north_star_apply", _fo.OP_EDIT_NORTH_STAR),
    ("sync_autoload", _fo.OP_REGISTER_AUTOLOAD),
)

#: GUI verb → a DECLARED-only op interface (present as a seam, body pending).
#: An interface that gains a CLI host must graduate to IMPLEMENTED_VERBS —
#: the honesty check flags a still-declared-but-implemented op.
DECLARED_INTERFACES = (
    ("run_sleep_session", SLEEP_SESSION_OP),
)


# ── Dispatch plumbing (confirm → token → engine; never a file) ───────────────

def default_dispatch() -> dict:
    """The live control-plane dispatch (all Phase-6 ops, default seams) —
    what the Anchor endpoints use; tests inject their own hermetic table."""
    return _fo.build_full_control_dispatch()


def _confirm_required(op) -> dict:
    """The pre-dispatch refusal for an unconfirmed mutation: nothing is
    minted, dispatched, journaled, or written — the human's explicit confirm
    is the gate, and a missing confirm is an honest no-op."""
    return {"ok": False, "op": str(op), "outcome": "refused", "refused": True,
            "reason": "confirm-required:%s" % op, "output": None, "job": None}


def _put(payload, key, value) -> None:
    if value is not None:
        payload[key] = str(value)


def _dispatch_op(op, payload, *, dispatch=None, confirm=False) -> dict:
    """One GUI mutation = one confirm-gated op invocation through the engine.

    ``confirm=True`` (the explicit human approval from the GUI dialog) mints
    the single-use token and spends it on exactly ONE ``run_control_op``
    dispatch — headless via job_runner, write-scope-checked by the runner,
    auto-journaled by the Wave-2 seam. Without it: refused pre-dispatch."""
    if not confirm:
        return _confirm_required(op)
    table = dispatch if dispatch is not None else default_dispatch()
    token = _sr.issue_confirm_token(op)
    return _fo.run_control_op(table, op, payload=payload,
                              confirm_token=token)


# ── The GUI verbs (create · edit North Star · clickable sync) ────────────────

def create_skill(name, *, dispatch=None, confirm=False, title=None,
                 description=None, tier=None, skills_root=None,
                 map_path=None, lock_path=None, git=True) -> dict:
    """"Create a skill" → ``foundry.scaffold_skill`` (template + map v2
    registration + branch commit; refuses to overwrite). Pure invocation."""
    payload = {"name": "" if name is None else str(name), "git": bool(git)}
    _put(payload, "title", title)
    _put(payload, "description", description)
    _put(payload, "tier", tier)
    _put(payload, "skills_root", skills_root)
    _put(payload, "map_path", map_path)
    _put(payload, "lock_path", lock_path)
    return _dispatch_op(_fo.OP_SCAFFOLD, payload, dispatch=dispatch,
                        confirm=confirm)


def north_star_propose(skill, new_text, *, dispatch=None, confirm=False,
                       skills_root=None) -> dict:
    """"Edit a North Star" — the PROPOSE leg of ``foundry.edit_north_star``:
    parks a reviewable unified diff; the skill's file is untouched."""
    payload = {"skill": "" if skill is None else str(skill),
               "mode": "propose",
               "new_text": "" if new_text is None else str(new_text)}
    _put(payload, "skills_root", skills_root)
    return _dispatch_op(_fo.OP_EDIT_NORTH_STAR, payload, dispatch=dispatch,
                        confirm=confirm)


def north_star_apply(skill, proposal_id, *, dispatch=None, confirm=False,
                     skills_root=None, git=True) -> dict:
    """The APPLY leg of ``foundry.edit_north_star``: spends the explicit
    human confirm on one parked proposal — prior version retained, branch
    commit, refused when the file drifted since the proposal."""
    payload = {"skill": "" if skill is None else str(skill),
               "mode": "apply",
               "proposal_id": "" if proposal_id is None else str(proposal_id),
               "git": bool(git)}
    _put(payload, "skills_root", skills_root)
    return _dispatch_op(_fo.OP_EDIT_NORTH_STAR, payload, dispatch=dispatch,
                        confirm=confirm)


def sync_autoload(*, dispatch=None, confirm=False, map_path=None, home=None,
                  root=None) -> dict:
    """"Clickable in Anchor" → ``foundry.register_autoload``: regenerate the
    clickable skill set from map.json v2 alone (never hand-wired)."""
    payload = {}
    _put(payload, "map_path", map_path)
    _put(payload, "home", home)
    _put(payload, "root", root)
    return _dispatch_op(_fo.OP_REGISTER_AUTOLOAD, payload, dispatch=dispatch,
                        confirm=confirm)


# ── The sleep-session seam (declared interface, honest pending) ──────────────

def sleep_session_status(dispatch=None) -> dict:
    """Is the ``foundry.sleep_session`` op body wired yet?

    With a dispatch table: the LIVE wiring (is the op registered in the
    table the GUI dispatches through). Without one: the registry check (has
    the foundry build registered a headless host for the op in
    ``foundry_ops.OP_CLI_NAMES``). Honest either way — pending is pending."""
    if dispatch is not None:
        wired = SLEEP_SESSION_OP in dispatch
    else:
        wired = SLEEP_SESSION_OP in _fo.OP_CLI_NAMES
    if wired:
        return {"op": SLEEP_SESSION_OP, "wired": True, "status": "ready",
                "reason": None}
    return {"op": SLEEP_SESSION_OP, "wired": False, "status": "pending",
            "reason": SLEEP_PENDING_REASON}


def run_sleep_session(*, dispatch=None, payload=None, confirm=False) -> dict:
    """The "Run sleep session → review" action, targeting the DECLARED
    ``foundry.sleep_session`` interface.

    Not wired yet (this build — the op body ships from the separate foundry
    build): the honest pending status, nothing dispatched, nothing faked.
    Wired (the integration pass registers the op): dispatched through the
    SAME ``run_control_op`` path as every other GUI mutation — no GUI
    change needed when the body lands; the seam is the contract."""
    st = sleep_session_status(dispatch)
    if not st["wired"]:
        return {"ok": False, "op": SLEEP_SESSION_OP, "outcome": "pending",
                "refused": True, "pending": True, "status": "pending",
                "reason": SLEEP_PENDING_REASON, "output": None, "job": None}
    if not confirm:
        return _confirm_required(SLEEP_SESSION_OP)
    table = dispatch if dispatch is not None else default_dispatch()
    token = _sr.issue_confirm_token(SLEEP_SESSION_OP)
    return _fo.run_control_op(table, SLEEP_SESSION_OP, payload=payload,
                              confirm_token=token)


# ── The 2nd-surface honesty check ────────────────────────────────────────────

def second_surface_honesty(source_text=None, module=None) -> list:
    """Return the honesty problems with the GUI write surface (empty = an
    honest second surface over the one engine).

    Three structural checks:

    * the Wave-9 anti-theater scan re-applied to THIS module (no file-
      mutation primitive in the source, no module-level mutable store) —
      every GUI mutation must be an op invocation, never a GUI-side write;
    * every implemented verb maps to a DR-01-inventory op that runs
      HEADLESS (a registered ``foundry_ops`` CLI host) — the GUI invokes
      the same API the headless path uses, no GUI-only verb;
    * a declared-only interface (the sleep seam) must STAY declared-only
      until its op body is actually registered — a wired op still labeled
      pending would be the inverse dishonesty.
    """
    import foundry_gui as _fg  # lazy: foundry_gui embeds this panel
    if source_text is None:
        source_text = Path(__file__).resolve().read_text(
            encoding="utf-8", errors="replace")
    mod = module if module is not None else sys.modules[__name__]
    problems = list(_fg.anti_theater_check(source_text=source_text,
                                           module=mod))
    for verb, op in IMPLEMENTED_VERBS:
        if op not in _fd.MUTATIVE_VERBS:
            problems.append("verb-not-in-dr01-inventory:%s->%s" % (verb, op))
        if op not in _fo.OP_CLI_NAMES:
            problems.append("verb-not-headless:%s->%s" % (verb, op))
    for verb, op in DECLARED_INTERFACES:
        if op in _fo.OP_CLI_NAMES:
            problems.append("interface-no-longer-pending:%s->%s"
                            % (verb, op))
    return problems


# ── The write panel (rendered into the /foundry page) ────────────────────────

_PANEL_CSS = """
  .wgrid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .wcard { background:var(--panel); border:1px solid var(--line);
           padding:12px 14px; }
  .wcard h3 { margin:0 0 8px; font-size:13px; color:var(--accent); }
  .wcard input, .wcard textarea { width:100%; background:var(--bg);
      color:var(--text); border:1px solid var(--line); padding:5px 7px;
      font:12.5px/1.4 'Segoe UI',system-ui,sans-serif; margin:3px 0 8px;
      box-sizing:border-box; }
  .wcard textarea { min-height:90px; font-family:Consolas,monospace; }
  .wbtn { background:#22304a; color:var(--text); border:1px solid
          var(--accent); padding:5px 12px; font-size:12.5px; cursor:pointer;
          margin:2px 4px 2px 0; }
  .wbtn[disabled] { opacity:.45; cursor:not-allowed; }
  .wmsg { font-size:12px; margin-top:8px; min-height:16px; }
"""

_PANEL_HTML = """
<style>__PANEL_CSS__</style>
<h2>Actions (control-plane ops)</h2>
<div class="wgrid" data-foundry-write="op-invocations-only">
  <div class="wcard">
    <h3>Create a skill</h3>
    <input type="text" id="fw-name" placeholder="skill-name (slug)">
    <input type="text" id="fw-title" placeholder="Title (optional)">
    <button class="wbtn" onclick="fwCreateSkill()">Create &rarr;
      foundry.scaffold_skill</button>
    <div class="wmsg" id="fw-create-msg"></div>
  </div>
  <div class="wcard">
    <h3>Edit a North Star</h3>
    <input type="text" id="fw-ns-skill" placeholder="skill-name">
    <textarea id="fw-ns-text"
      placeholder="The full new NORTH-STAR.md text"></textarea>
    <button class="wbtn" onclick="fwProposeNS()">Propose &rarr;
      foundry.edit_north_star</button>
    <button class="wbtn" id="fw-ns-apply" disabled
      onclick="fwApplyNS()">Apply proposal</button>
    <pre id="fw-ns-diff" hidden></pre>
    <div class="wmsg" id="fw-ns-msg"></div>
  </div>
  <div class="wcard">
    <h3>Clickable in Anchor</h3>
    <p class="dim" style="font-size:12px;margin:0 0 8px">Regenerate
      Anchor&#39;s clickable skill set from map.json v2 alone (never
      hand-wired).</p>
    <button class="wbtn" onclick="fwSyncAutoload()">Sync &rarr;
      foundry.register_autoload</button>
    <div class="wmsg" id="fw-sync-msg"></div>
  </div>
  <div class="wcard">
    <h3>Sleep session</h3>
    <button class="wbtn" data-sleep-op="foundry.sleep_session"
      onclick="fwSleepSession()">Run sleep session &rarr; review</button>
    <div class="wmsg" id="fw-sleep-msg">__SLEEP_STATUS__</div>
  </div>
</div>
<div class="src">every action above dispatches a confirm-gated control-plane
 op through job_runner (auto-journaled; the GUI never touches a file)
 &middot; 2nd-surface honesty: the same ops run headless via
 foundry_ops.py</div>
<script>
  function fwTok() {
    try { return localStorage.getItem('anchor_token') || ''; }
    catch (e) { return ''; }
  }
  function fwMsg(id, text, bad) {
    var el = document.getElementById(id);
    if (el) { el.textContent = text;
              el.className = 'wmsg ' + (bad ? 'bad' : 'ok'); }
  }
  function fwPost(url, data, cb) {
    var h = {'Content-Type': 'application/json'};
    var t = fwTok(); if (t) { h['X-Anchor-Token'] = t; }
    fetch(url, {method: 'POST', headers: h, body: JSON.stringify(data)})
      .then(function (r) { return r.json(); })
      .then(cb)
      .catch(function (e) { cb({ok: false, reason: String(e)}); });
  }
  function fwCreateSkill() {
    var name = (document.getElementById('fw-name').value || '').trim();
    if (!name) { fwMsg('fw-create-msg', 'enter a skill name (slug)', true);
                 return; }
    if (!confirm('Scaffold new skill "' + name +
                 '" via foundry.scaffold_skill?')) { return; }
    var title = (document.getElementById('fw-title').value || '').trim();
    fwPost('/api/foundry/create_skill',
           {name: name, title: title || null, confirm: true},
           function (res) {
             if (res.ok) {
               fwMsg('fw-create-msg', 'scaffolded ' + name + ' (job ' +
                     ((res.job || {}).job_id || '?') + ')');
               setTimeout(function () { location.reload(); }, 900);
             } else { fwMsg('fw-create-msg', res.reason || 'refused', true); }
           });
  }
  function fwProposeNS() {
    var skill = (document.getElementById('fw-ns-skill').value || '').trim();
    var text = document.getElementById('fw-ns-text').value || '';
    if (!skill || !text.trim()) {
      fwMsg('fw-ns-msg', 'skill name + new text required', true); return;
    }
    fwPost('/api/foundry/north_star',
           {skill: skill, mode: 'propose', new_text: text, confirm: true},
           function (res) {
             var out = res.output || {};
             if (res.ok && out.proposal_id) {
               var pre = document.getElementById('fw-ns-diff');
               pre.hidden = false; pre.textContent = out.diff || '(no diff)';
               var btn = document.getElementById('fw-ns-apply');
               btn.disabled = false; btn.dataset.proposal = out.proposal_id;
               fwMsg('fw-ns-msg', 'proposal ' + out.proposal_id +
                     ' parked - review the diff, then Apply');
             } else { fwMsg('fw-ns-msg', res.reason || 'refused', true); }
           });
  }
  function fwApplyNS() {
    var btn = document.getElementById('fw-ns-apply');
    var pid = btn.dataset.proposal || '';
    var skill = (document.getElementById('fw-ns-skill').value || '').trim();
    if (!pid || !skill) { return; }
    if (!confirm('Apply North-Star proposal ' + pid + ' to "' + skill +
                 '"? (branch commit; prior version retained)')) { return; }
    fwPost('/api/foundry/north_star',
           {skill: skill, mode: 'apply', proposal_id: pid, confirm: true},
           function (res) {
             if (res.ok) {
               btn.disabled = true;
               fwMsg('fw-ns-msg', 'applied (prior retained: ' +
                     (((res.output || {}).prior_retained) || '?') + ')');
             } else { fwMsg('fw-ns-msg', res.reason || 'refused', true); }
           });
  }
  function fwSyncAutoload() {
    if (!confirm('Regenerate the clickable skill set from map.json v2?')) {
      return;
    }
    fwPost('/api/foundry/sync_autoload', {confirm: true}, function (res) {
      if (res.ok) {
        fwMsg('fw-sync-msg', 'registered ' +
              ((res.output || {}).count || 0) + ' skills');
        setTimeout(function () { location.reload(); }, 900);
      } else { fwMsg('fw-sync-msg', res.reason || 'refused', true); }
    });
  }
  function fwSleepSession() {
    fwPost('/api/foundry/sleep_session', {confirm: true}, function (res) {
      if (res.pending) {
        fwMsg('fw-sleep-msg', 'pending: ' + (res.reason || ''), true);
      } else if (res.ok) {
        fwMsg('fw-sleep-msg', 'sleep session done - verdict: ' +
              (((res.output || {}).verdict) || 'ok'));
      } else { fwMsg('fw-sleep-msg', res.reason || 'refused', true); }
    });
  }
</script>
"""


def render_write_panel(sleep=None) -> str:
    """The write-surface panel the /foundry page embeds: four action cards
    whose buttons POST to the Anchor op endpoints — the browser side of the
    same op invocations this module's functions perform. The sleep card
    renders the seam's HONEST live status (pending until the foundry build
    delivers the op body)."""
    st = sleep if isinstance(sleep, dict) else sleep_session_status()
    if st.get("wired"):
        status_html = ('<span class="ok">ready &middot; op interface '
                       'foundry.sleep_session is wired</span>')
    else:
        status_html = ('<span class="warn">pending: %s</span>'
                       % SLEEP_PENDING_REASON)
    return (_PANEL_HTML
            .replace("__PANEL_CSS__", _PANEL_CSS)
            .replace("__SLEEP_STATUS__", status_html))

"""Slices 3 & 4 verification suite (2026-11-23):
AI Cockpit Left-Rail `Recent History` + `Simple Wave Map` AND
Right-Rail `Most Recent Deliverables <=2 Batches` + Curated `Final Deliverables`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request

import deliverables_register
import distro
from steward_cockpit import deliverable_shelves as ds
from steward_cockpit import steward_campaign as sc
from steward_cockpit import steward_routes as routes
from steward_cockpit import wave_map_model as wmm
from tools import steward_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "steward_cockpit" / "static"


def _write_campaign(cdir: Path, *, steps: list[dict] | None = None) -> Path:
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text("# Campaign: Spectral Analysis\n\n## North Star\nDeliver verified figures.\n", encoding="utf-8")
    if steps is not None:
        rm = {"roadmap_projection": steps, "steps": steps, "roadmap_events": []}
        (cdir / "roadmap.json").write_text(json.dumps(rm, indent=2), encoding="utf-8")
    return cdir


def _append_user_turn(cdir: Path, turn_id: str, text: str) -> None:
    log_fp = cdir / ".ecgberht" / "conversation-log.json"
    doc = json.loads(log_fp.read_text(encoding="utf-8")) if log_fp.is_file() else {"turns": []}
    doc["turns"].append({"role": "user", "turn_id": turn_id, "text": text, "at": "2026-11-23T12:00:00Z"})
    log_fp.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _append_steward_turn(cdir: Path, turn_id: str, text: str) -> None:
    log_fp = cdir / ".ecgberht" / "conversation-log.json"
    doc = json.loads(log_fp.read_text(encoding="utf-8")) if log_fp.is_file() else {"turns": []}
    doc["turns"].append({"role": "steward", "turn_id": turn_id, "text": text, "at": "2026-11-23T12:00:05Z"})
    log_fp.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _run_cockpit_dom_vm(scenario: dict) -> dict:
    """Execute cockpit-wave-map.js + cockpit-deliverable-shelves.js + shared.js in Node VM."""
    node_script = r"""
const fs = require("fs"), vm = require("vm");
const sc = JSON.parse(fs.readFileSync(0, "utf8"));
const waveJs = fs.readFileSync(sc.waveJsPath, "utf8");
const shelvesJs = fs.readFileSync(sc.shelvesJsPath, "utf8");
const sharedJs = fs.readFileSync(sc.sharedJsPath, "utf8");

function matchOne(el, raw) {
  if (!el || el.nodeType !== 1) return false;
  let s = raw.trim();
  if (!s) return false;
  const attrs = [], ids = [], clss = [];
  s = s.replace(/\[([^\]]+)\]/g, (_, x) => (attrs.push(x.trim()), ""))
       .replace(/#([A-Za-z0-9_-]+)/g, (_, x) => (ids.push(x), ""))
       .replace(/\.([A-Za-z0-9_-]+)/g, (_, x) => (clss.push(x), "")).trim();
  for (const a of attrs) {
    const eq = a.indexOf("=");
    if (eq < 0 ? !el.hasAttribute(a) : el.getAttribute(a.slice(0, eq).trim()) !== a.slice(eq + 1).trim().replace(/^["']|["']$/g, "")) return false;
  }
  if (ids.some(i => el.id !== i) || clss.some(c => !el.classList.contains(c))) return false;
  return !s || s === "*" || el.tagName === s.toUpperCase();
}
function matchSel(el, sel) {
  return String(sel || "").split(",").map(s => s.trim()).filter(Boolean).some(part => {
    const chain = part.split(/\s+/).filter(Boolean);
    if (!chain.length || !matchOne(el, chain[chain.length - 1])) return false;
    let cur = el.parentElement;
    for (let i = chain.length - 2; i >= 0; i--) {
      while (cur && !matchOne(cur, chain[i])) cur = cur.parentElement;
      if (!cur) return false;
      cur = cur.parentElement;
    }
    return true;
  });
}
class MockEl {
  constructor(tag) {
    this.tagName = String(tag || "DIV").toUpperCase();
    this.nodeType = 1; this.className = ""; this._text = ""; this.id = "";
    this.hidden = false; this.disabled = false; this.open = false; this.href = ""; this.download = "";
    this.value = ""; this.type = ""; this.isConnected = true;
    this.style = { setProperty() {}, removeProperty() {} };
    this.dataset = {}; this.attributes = {}; this.children = []; this.childNodes = [];
    this.parentElement = null; this._listeners = {};
    const self = this, set = () => new Set(String(self.className || "").split(/\s+/).filter(Boolean));
    const sync = s => { self.className = [...s].join(" "); };
    this.classList = {
      add(...t) { const s = set(); t.forEach(x => x && s.add(String(x))); sync(s); },
      remove(...t) { const s = set(); t.forEach(x => s.delete(String(x))); sync(s); },
      contains(t) { return set().has(String(t)); },
      toggle(t, f) { const s = set(), k = String(t), on = f !== undefined ? Boolean(f) : !s.has(k); if (on) s.add(k); else s.delete(k); sync(s); return on; }
    };
  }
  get textContent() { return this.childNodes.length ? this.childNodes.map(c => c.textContent).join("") : (this._text || ""); }
  set textContent(v) { this.children = []; this.childNodes = []; this._text = v == null ? "" : String(v); }
  appendChild(c) { if (!c) return c; c.parentElement = this; c.isConnected = true; this.childNodes.push(c); if (c.nodeType === 1) this.children.push(c); return c; }
  insertBefore(c) { return this.appendChild(c); }
  remove() { if (!this.parentElement) return; this.parentElement.children = this.parentElement.children.filter(x => x !== this); this.parentElement.childNodes = this.parentElement.childNodes.filter(x => x !== this); this.parentElement = null; }
  setAttribute(k, v) { k = String(k); v = String(v); this.attributes[k] = v; if (k === "class") this.className = v; if (k === "href") this.href = v; if (k === "download") this.download = v; if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v; }
  getAttribute(k) { k = String(k); if (k === "href" && this.href) return this.href; if (Object.prototype.hasOwnProperty.call(this.attributes, k)) return this.attributes[k]; if (k.startsWith("data-")) { const cm = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()); if (Object.prototype.hasOwnProperty.call(this.dataset, cm)) return String(this.dataset[cm]); } return null; }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener() {}
  focus() {}
  closest(sel) { for (let c = this; c && c.nodeType === 1; c = c.parentElement) if (matchSel(c, sel)) return c; return null; }
  querySelectorAll(sel) { const out = [], walk = n => { for (const ch of n.children || []) { if (matchSel(ch, sel)) out.push(ch); walk(ch); } }; walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

(async () => {
  const docEl = new MockEl("html"), head = new MockEl("head"), body = new MockEl("body"), app = new MockEl("div");
  app.className = "app appx app3"; docEl.appendChild(head); docEl.appendChild(body); body.appendChild(app);
  const mk = (t, c, a = {}, p = app) => { const n = new MockEl(t); if (c) n.className = c; Object.entries(a).forEach(([k, v]) => n.setAttribute(k, v)); p.appendChild(n); return n; };
  mk("h2", "", { "data-plan-head": "1" });
  mk("span", "", { "data-plan-count": "1" });
  mk("i", "", { "data-progress-fill": "1" });
  mk("div", "", { "data-plan-error": "1" });
  const waveMount = mk("div", "wave-map-root", { "data-wave-map": "1" });
  mk("section", "", { "data-plan-focus": "1" });
  mk("form", "", { "data-plan-add": "1" });
  mk("ul", "steps", { "data-steps": "1" });
  mk("div", "scroll", {});
  mk("textarea", "", { "data-say": "1" });
  mk("button", "send", { "data-send": "1" });
  const rightCol = mk("div", "rightcol", { "data-statuspane": "1" });
  const delivMount = mk("div", "pdeliv", { "data-delivmount": "1" }, rightCol);
  mk("div", "pscroll", {}, rightCol);

  const fetched = [];
  const fetchMock = async (url) => {
    const u = String(url); fetched.push(u);
    if (u.includes("/api/events")) return new Promise(() => {});
    if (u.includes("/api/wave-state")) return { ok: true, status: 200, json: async () => sc.waveMap };
    if (u.includes("/api/map")) return { ok: true, status: 200, json: async () => sc.map };
    if (u.includes("/api/plan")) return { ok: true, status: 200, json: async () => sc.plan };
    if (u.includes("/api/deliverables")) return { ok: true, status: 200, json: async () => sc.deliverables };
    if (u.includes("/api/state")) return { ok: true, status: 200, json: async () => ({ ok: true, alive: false, busy: false, stamp: "s1" }) };
    if (u.includes("/api/status")) return { ok: true, status: 200, json: async () => ({ ok: true, history_updates: [] }) };
    if (u.includes("/api/history")) return { ok: true, status: 200, json: async () => ({ turns: [] }) };
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };
  const storage = {};
  const mockStorage = { getItem: k => storage[k] || null, setItem: (k, v) => { storage[k] = String(v); }, removeItem: k => { delete storage[k]; } };
  const document = {
    documentElement: docEl, head, body, visibilityState: "visible", activeElement: null,
    createElement: t => new MockEl(t), createTextNode: txt => ({ nodeType: 3, textContent: String(txt || "") }),
    querySelector: s => docEl.querySelector(s), querySelectorAll: s => docEl.querySelectorAll(s),
    addEventListener() {}, removeEventListener() {},
  };
  const sandbox = {
    window: null, globalThis: null, document, URLSearchParams, URL, AbortController, console,
    location: { search: sc.search || "?dir=test_effort", origin: "http://localhost:8777", pathname: "/steward/v1", href: "http://localhost:8777/steward/v1" + (sc.search || "?dir=test_effort"), reload() {} },
    localStorage: mockStorage, sessionStorage: mockStorage, fetch: fetchMock,
    XMLHttpRequest: class { open() {} send() {} }, Event: class { constructor(t) { this.type = t; } },
    getComputedStyle: () => ({ minHeight: "46px" }), mdRender: (el, txt) => { if (el) el.textContent = String(txt || ""); },
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    innerHeight: 900, innerWidth: 1400, navigator: {},
    btoa: s => Buffer.from(String(s), "binary").toString("base64"),
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.window.parent = sandbox; sandbox.window.addEventListener = () => {};

  vm.runInNewContext(waveJs, sandbox);
  vm.runInNewContext(shelvesJs, sandbox);
  const Proto = vm.runInNewContext(sharedJs + "\n;Proto;", sandbox);
  await Proto.init({ statusPane: true });

  const shelfDetails = delivMount.querySelectorAll("details.dtile");
  process.stdout.write(JSON.stringify({
    fetched,
    waveChildren: waveMount.children.length,
    waveText: waveMount.textContent,
    hasIterBtn: Boolean(waveMount.querySelector("[data-wave-iterate]")),
    hasDoneBtn: Boolean(waveMount.querySelector("[data-wave-done]")),
    hasNextUp: waveMount.textContent.includes("Next Up"),
    shelves: shelfDetails.map(d => ({
      shelf: d.dataset.shelf || "",
      open: Boolean(d.open),
      summary: (d.querySelector("summary") || {}).textContent || "",
      bodyText: (d.querySelector(".dtile-body") || {}).textContent || "",
    })),
    managedNodes: delivMount.querySelectorAll(".dfile-row").map(n => ({
      path: n.dataset.filePath || "",
      immutablePath: n.dataset.immutablePath || "",
      hash: n.dataset.fileHash || "",
      suggestedFilename: n.dataset.suggestedFilename || "",
    })),
  }));
})().catch(e => { console.error(e); process.exit(1); });
"""
    payload = {
        "waveJsPath": str(STATIC_DIR / "cockpit-wave-map.js"),
        "shelvesJsPath": str(STATIC_DIR / "cockpit-deliverable-shelves.js"),
        "sharedJsPath": str(STATIC_DIR / "shared.js"),
        **scenario,
    }
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "run_vm.cjs"
        sf.write_text(node_script, encoding="utf-8")
        proc = subprocess.run(["node", str(sf)], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=25, check=True)
    return json.loads(proc.stdout)


def test_part_a_wave_map_pure_derivation_round_persistence_bounds_and_flat_roadmap(tmp_path: Path):
    cdir = _write_campaign(
        tmp_path / "spectral-effort",
        steps=[
            {"id": "w1", "name": "Wave 1: Theorem Proofs", "goal": "Lock Appendix A", "status": "done", "done": True},
            {"id": "w2", "name": "Wave 2: Empirical Figures", "goal": "Tight error bounds", "status": "active", "done": False},
            {"id": "w3", "name": "Wave 3: Sensitivity Appendix", "goal": "Monte Carlo table", "status": "proposed", "done": False},
            {"id": "w4", "name": "Wave 4: Journal Submission", "goal": "LaTeX + Cover Letter", "status": "proposed", "done": False},
        ],
    )

    wm0 = wmm.build_wave_map_payload(cdir)
    assert wm0["ok"] is True
    assert wm0["steps_flat"] is True
    assert wm0["current_wave"]["step_id"] == "w2"
    assert wm0["current_wave"]["wave_num"] == 2
    assert wm0["current_wave"]["round"] == 1
    assert wm0["current_wave"]["badge"] == "WAVE 2 \u00b7 ACTIVE"
    assert wm0["current_wave"]["iter_badge"] == "\u21bb Iterating \u00b7 Round 1"
    assert len(wm0["recent_history"]) >= 1
    assert "Wave 1" in wm0["recent_history"][0]["text"]
    assert [n["step_id"] for n in wm0["coming_next"]] == ["w3", "w4"]
    assert wm0["coming_next"][0]["next_up"] is True
    assert wm0["coming_next"][1]["next_up"] is False

    res_iter, code_iter = routes.handle_post(str(cdir), "wave-state", {"op": "iterate", "step_id": "w2", "recommended_action": "iterate"})
    assert code_iter == 200
    assert res_iter["current_wave"]["round"] == 2
    assert res_iter["current_wave"]["recommended_action"] == "iterate"
    ws_disk = json.loads((cdir / ".ecgberht" / "wave-state.json").read_text(encoding="utf-8"))
    assert ws_disk["waves"]["w2"]["round"] == 2
    assert ws_disk["waves"]["w2"]["recommended_action"] == "iterate"

    for bad_payload in (
        {"step_id": "w2", "round": 0},
        {"step_id": "w2", "round": 100},
        {"step_id": "w2", "round": -3},
        {"step_id": "w2", "round": True},
        {"step_id": "w2", "round": "abc"},
        {"step_id": "w2", "round": 2, "recommended_action": "bogus"},
    ):
        err_res, err_code = routes.handle_post(str(cdir), "wave-state", bad_payload)
        assert err_code == 400, f"Expected 400 for {bad_payload}, got {err_code}"
        assert err_res["ok"] is False

    res_99, code_99 = routes.handle_post(str(cdir), "wave-state", {"step_id": "w2", "round": 99, "recommended_action": "advance"})
    assert code_99 == 200 and res_99["current_wave"]["round"] == 99
    _, code_100 = routes.handle_post(str(cdir), "wave-state", {"op": "iterate", "step_id": "w2"})
    assert code_100 == 400

    res_done, code_done = routes.handle_post(str(cdir), "wave-state", {"op": "done_next", "step_id": "w2"})
    assert code_done == 200
    assert res_done["current_wave"]["step_id"] == "w3"
    assert res_done["current_wave"]["wave_num"] == 3
    assert res_done["current_wave"]["round"] == 1
    rm_after = json.loads((cdir / "roadmap.json").read_text(encoding="utf-8"))
    assert isinstance(rm_after["steps"], list)
    assert all(isinstance(s, dict) and "steps" not in s and "children" not in s for s in rm_after["steps"])
    assert steward_plan.read_plan_state(cdir)["ok"] is True


def test_part_a_http_auth_and_containment_and_embed_dialogue_suppression(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "anchor-data"
    data_dir.mkdir()
    proj_root = tmp_path / "proj_alpha"
    eff_dir = _write_campaign(
        proj_root / "effort_one",
        steps=[
            {"id": "w1", "name": "Wave 1: Setup", "status": "done", "done": True},
            {"id": "w2", "name": "Wave 2: Build", "status": "active", "done": False},
            {"id": "w3", "name": "Wave 3: Verify", "status": "proposed", "done": False},
        ],
    )
    tok_val = "tok-123"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_TOKEN", tok_val)
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")

    import anchor_gui
    monkeypatch.setitem(routes.CONFIG, "fake", True)
    reg = anchor_gui.select_existing_project("Proj Alpha", str(proj_root))
    pid = reg["entry"]["id"]

    server = anchor_gui.make_server("127.0.0.1", 0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        def _req(method: str, path: str, *, authed: bool = True, body: dict | None = None) -> tuple[int, dict]:
            headers = {"Host": f"127.0.0.1:{server.server_address[1]}"}
            if authed:
                headers["Authorization"] = f"Bearer {tok_val}"
            raw_body = None
            if body is not None:
                raw_body = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            r = urllib.request.Request(base + path, data=raw_body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as he:
                return he.code, json.loads(he.read().decode("utf-8") or "{}")

        c_unauth, _ = _req("GET", f"/api/steward/wave-state?pid={pid}&dir=effort_one", authed=False)
        assert c_unauth == 401
        c_bad_pid, _ = _req("GET", "/api/steward/wave-state?pid=does_not_exist&dir=effort_one")
        assert c_bad_pid == 404
        c_trav, _ = _req("GET", f"/api/steward/wave-state?pid={pid}&dir=../../outside")
        assert c_trav == 403
        c_trav_post, _ = _req("POST", f"/api/steward/wave-state?pid={pid}", body={"dir": "../outside", "step_id": "w2", "round": 2})
        assert c_trav_post == 403
        c_unreg, _ = _req("GET", f"/api/steward/wave-state?pid={pid}&dir=unregistered_sub")
        assert c_unreg == 404
        c_ok, j_ok = _req("GET", f"/api/steward/wave-state?pid={pid}&dir=effort_one")
        assert c_ok == 200 and j_ok["ok"] is True and j_ok["current_wave"]["step_id"] == "w2"
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)

    wm_payload = wmm.build_wave_map_payload(eff_dir)
    deliv_payload = sc.read_deliverables(str(eff_dir))
    map_payload = sc.read_map(str(eff_dir))
    map_payload["wave_map"] = wm_payload

    embed_dom = _run_cockpit_dom_vm({
        "search": "?dir=effort_one&embed=dialogue",
        "waveMap": wm_payload, "map": map_payload,
        "plan": steward_plan.read_plan_state(eff_dir), "deliverables": deliv_payload,
    })
    assert not any("/api/wave-state" in u or "/api/plan" in u for u in embed_dom["fetched"])
    assert embed_dom["waveChildren"] == 0

    full_dom = _run_cockpit_dom_vm({
        "search": "?dir=effort_one",
        "waveMap": wm_payload, "map": map_payload,
        "plan": steward_plan.read_plan_state(eff_dir), "deliverables": deliv_payload,
    })
    assert full_dom["waveChildren"] == 3
    assert full_dom["hasIterBtn"] is True and full_dom["hasDoneBtn"] is True and full_dom["hasNextUp"] is True
    assert [s["shelf"] for s in full_dom["shelves"]] == ["recent", "final", "earlier"]
    assert [s["open"] for s in full_dom["shelves"]] == [False, False, False]


def test_part_b_two_batches_cap_and_qa_turns_never_evict_across_both_choke_points(tmp_path: Path):
    cdir_reg = _write_campaign(tmp_path / "reg-batches", steps=[{"id": "s1", "name": "Wave 1", "status": "active"}])
    for fn in ("fig1.pdf", "fig1.png", "table1.xlsx", "fig2.pdf"):
        (cdir_reg / fn).write_bytes(b"%PDF-1.4 mock")

    _append_user_turn(cdir_reg, "t1", "Generate Figure 1 in PDF and PNG.")
    assert deliverables_register.register(cdir_reg, "FOR REVIEW: Figure 1 PDF", "`fig1.pdf`", notify=False)["written"] is True
    assert deliverables_register.register(cdir_reg, "FOR REVIEW: Figure 1 PNG", "`fig1.png`", notify=True)["written"] is True

    _append_user_turn(cdir_reg, "t2", "Build Table 1 workbook.")
    assert deliverables_register.register(cdir_reg, "FOR REVIEW: Table 1", "`table1.xlsx`")["written"] is True

    _append_user_turn(cdir_reg, "t3", "How is it going?")
    _append_steward_turn(cdir_reg, "s3", "Everything is on track.")
    _append_user_turn(cdir_reg, "t4", "Thanks!")
    _append_steward_turn(cdir_reg, "s4", "Happy to help.")

    shelves_after_qa = sc.read_deliverables(str(cdir_reg))["shelves"]
    assert len(shelves_after_qa["most_recent_batches"]) == 2
    assert shelves_after_qa["most_recent_batches"][0]["instruction_excerpt"] == "Build Table 1 workbook."
    assert shelves_after_qa["most_recent_batches"][1]["instruction_excerpt"] == "Generate Figure 1 in PDF and PNG."
    assert shelves_after_qa["most_recent_summary"]["file_count"] == 3

    deliv_md_lines = (cdir_reg / "DELIVERABLES.md").read_text(encoding="utf-8").splitlines()
    assert "| What | Where | Date | Step |" in deliv_md_lines
    for ln in deliv_md_lines:
        if ln.strip().startswith("|"):
            assert len(ln.strip().strip("|").split("|")) == 4

    _append_user_turn(cdir_reg, "t5", "Now generate Figure 2.")
    assert deliverables_register.register(cdir_reg, "FOR REVIEW: Figure 2", "`fig2.pdf`")["written"] is True
    shelves_after_t5 = sc.read_deliverables(str(cdir_reg))["shelves"]
    assert len(shelves_after_t5["most_recent_batches"]) == 2
    assert [b["instruction_excerpt"] for b in shelves_after_t5["most_recent_batches"]] == ["Now generate Figure 2.", "Build Table 1 workbook."]
    earlier_paths = {it["path"] for it in shelves_after_t5["earlier_items"]}
    assert "fig1.pdf" in earlier_paths and "fig1.png" in earlier_paths

    cdir_ref = _write_campaign(tmp_path / "managed-refinement", steps=[{"id": "lec", "name": "Lecture Slice", "status": "active"}])
    for fn in ("d1.pdf", "d2.pdf", "d3.pdf"):
        (cdir_ref / fn).write_bytes(b"%PDF-1.4 managed")
    h1 = hashlib.sha256((cdir_ref / "d1.pdf").read_bytes()).hexdigest()
    ref_state_2 = {
        "managed": True,
        "slices": {
            "lec": {
                "round": 2, "phase": "awaiting_review", "candidate": {"deck": "r2"},
                "revisions": {
                    "r1": {"product_id": "deck", "revision_id": "r1", "path": "d1.pdf", "hash": h1, "at": "2026-11-23T10:00:00Z"},
                    "r2": {"product_id": "deck", "revision_id": "r2", "path": "d2.pdf", "hash": h1, "at": "2026-11-23T11:00:00Z"},
                },
                "presentations": [
                    {"id": "p1", "round": 1, "at": "2026-11-23T10:00:00Z", "purpose": "Initial deck", "members": [{"product_id": "deck", "revision_id": "r1", "path": "d1.pdf", "hash": h1}]},
                    {"id": "p2", "round": 2, "at": "2026-11-23T11:00:00Z", "purpose": "Tighten slides", "members": [{"product_id": "deck", "revision_id": "r2", "path": "d2.pdf", "hash": h1}]},
                ],
            }
        },
    }
    items_2 = sc.refinement_items(str(cdir_ref), ref_state_2)
    _append_user_turn(cdir_ref, "qa1", "How is it going?")
    _append_steward_turn(cdir_ref, "qa2", "Slides ready.")
    sh_ref_2 = ds.compute_shelves_for_campaign(cdir_ref, items_2 + [{"what": "Draft 1", "path": "d1.pdf", "openable": True, "managed": True, "hash": h1, "step": "lec"}])
    assert len(sh_ref_2["most_recent_batches"]) == 2

    ref_state_2["slices"]["lec"]["revisions"]["r3"] = {"product_id": "deck", "revision_id": "r3", "path": "d3.pdf", "hash": h1, "at": "2026-11-23T12:00:00Z"}
    ref_state_2["slices"]["lec"]["candidate"]["deck"] = "r3"
    ref_state_2["slices"]["lec"]["presentations"].append({"id": "p3", "round": 3, "at": "2026-11-23T12:00:00Z", "purpose": "Add calibration plot", "members": [{"product_id": "deck", "revision_id": "r3", "path": "d3.pdf", "hash": h1}]})
    items_3 = sc.refinement_items(str(cdir_ref), ref_state_2)
    sh_ref_3 = ds.compute_shelves_for_campaign(cdir_ref, items_3 + [
        {"what": "Draft 1", "path": "d1.pdf", "openable": True, "managed": True, "hash": h1, "step": "lec"},
        {"what": "Draft 2", "path": "d2.pdf", "openable": True, "managed": True, "hash": h1, "step": "lec"},
    ])
    assert len(sh_ref_3["most_recent_batches"]) == 2
    assert [b["instruction_excerpt"] for b in sh_ref_3["most_recent_batches"]] == ["Add calibration plot", "Tighten slides"]


def test_part_b_final_supersession_siblings_no_collision_curation_and_oct4_review_links(tmp_path: Path):
    items = [
        {"what": "FINAL: Lecture 5 Slides v1", "path": "slides/Lecture 5_v1.pptx", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 5 Reading v1", "path": "slides/Lecture 5_v1.pdf", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 5 Slides v2", "path": "slides/Lecture 5_v2.pptx", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 5 Reading v2", "path": "slides/Lecture 5_v2.pdf", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 5 Notes v2", "path": "slides/Lecture 5_v2.docx", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 5 R Code", "path": "slides/Lecture 5.R", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 8 Data", "path": "Lecture 8/data.csv", "openable": True, "tier": "final"},
        {"what": "FINAL: Lecture 9 Data", "path": "Lecture 9/data.csv", "openable": True, "tier": "final"},
        {"what": "FINAL: Pipeline r1", "path": "code/model_r1.py", "openable": True, "tier": "final"},
        {"what": "FINAL: Pipeline r2", "path": "code/model_r2.py", "openable": True, "tier": "final"},
        {"what": "FINAL: Charter Rev A", "path": "docs/Charter_Rev_A.pdf", "openable": True, "tier": "final"},
        {"what": "FINAL: Charter Rev B", "path": "docs/Charter_Rev_B.pdf", "openable": True, "tier": "final"},
        {"what": "FINAL: Old Summary Name", "path": "docs/Initial_Brief.pdf", "openable": True, "tier": "final"},
        {"what": "FINAL: Executive Summary", "path": "docs/Executive_Summary.pdf", "openable": True, "tier": "final"},
    ]
    batches_doc = {"batches": [], "curation": {"supersedes": {"docs/Executive_Summary.pdf": ["docs/Initial_Brief.pdf"]}}}
    shelves = ds.compute_shelves(items, batches_doc)
    final_paths = {it["path"] for it in shelves["final_items"]}
    earlier_paths = {it["path"] for it in shelves["earlier_items"]}

    assert {"slides/Lecture 5_v2.pptx", "slides/Lecture 5_v2.pdf", "slides/Lecture 5_v2.docx"} <= final_paths
    assert {"slides/Lecture 5_v1.pptx", "slides/Lecture 5_v1.pdf"} <= earlier_paths
    lec5_bundled = next(r for r in shelves["final"] if "Lecture 5_v2" in r["path"])
    assert {p["label"] for p in lec5_bundled["format_pills"]} == {"PDF", "DOCX", "PPTX"}

    assert "slides/Lecture 5.R" in final_paths
    assert "Lecture 8/data.csv" in final_paths
    assert "Lecture 9/data.csv" in final_paths
    assert "code/model_r2.py" in final_paths and "code/model_r1.py" in earlier_paths
    assert "docs/Charter_Rev_B.pdf" in final_paths and "docs/Charter_Rev_A.pdf" in earlier_paths
    assert "docs/Executive_Summary.pdf" in final_paths and "docs/Initial_Brief.pdf" in earlier_paths

    cdir = _write_campaign(tmp_path / "oct4-managed", steps=[{"id": "quiz", "name": "Quiz 1", "status": "waiting"}])
    pdf_bytes = b"%PDF-1.4 exact managed bytes"
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    imm_rel = "deliverables/bank/rev-r3.pdf"
    read_rel = "Quiz 1 - Question Bank - Draft 3.pdf"
    (cdir / "deliverables" / "bank").mkdir(parents=True, exist_ok=True)
    (cdir / imm_rel).write_bytes(pdf_bytes)
    (cdir / read_rel).write_bytes(pdf_bytes)

    managed_row = {"managed": True, "openable": True, "step": "quiz", "owner_step_id": "quiz", "product_id": "bank", "revision_id": "r3", "presentation_id": "p3", "path": imm_rel, "hash": sha, "what": "bank", "is_current": True, "tier": "final"}
    alias_row = {"managed": False, "openable": True, "step": "quiz", "owner_step_id": "quiz", "path": read_rel, "what": "FINAL: Quiz 1 Question Bank Draft 3", "where_text": f"`{read_rel}` review: `{imm_rel}`"}
    sh_oct4 = ds.compute_shelves([managed_row, alias_row], {"batches": [{"batch_id": "b1", "paths": [imm_rel], "instruction_excerpt": "Publish Quiz 1"}]})
    fin_m = sh_oct4["final"][0]
    assert fin_m["open_path"] == read_rel and fin_m["path"] == imm_rel and fin_m["hash"] == sha and fin_m["suggested_filename"] == read_rel

    ok_resp, ok_code = routes.handle_get(str(cdir), "deliverable-file", {"path": read_rel, "hash": sha})
    assert ok_code == 200 and ok_resp.get("__file__")
    (cdir / read_rel).write_bytes(b"%PDF-1.4 tampered")
    (cdir / imm_rel).write_bytes(b"%PDF-1.4 tampered")
    bad_resp, bad_code = routes.handle_get(str(cdir), "deliverable-file", {"path": read_rel, "hash": sha})
    assert bad_code == 409 and bad_resp.get("error") == "artifact-hash-mismatch"


def test_zero_pii_hits_and_strict_file_line_caps():
    touched = [
        "steward_cockpit/wave_map_model.py",
        "steward_cockpit/static/cockpit-wave-map.js",
        "steward_cockpit/deliverable_shelves.py",
        "steward_cockpit/static/cockpit-deliverable-shelves.js",
        "deliverables_register.py",
        "steward_cockpit/steward_campaign.py",
        "steward_cockpit/steward_routes.py",
        "steward_cockpit/steward_engine.py",
        "steward_cockpit/static/v1.html",
        "steward_cockpit/static/shared.js",
        "steward_cockpit/static/shared.css",
        "tests/test_w3_w4_cockpit_wavemap_and_deliverables_2026_11_23.py",
    ]
    for rel in touched:
        fp = REPO_ROOT / rel
        txt = fp.read_text(encoding="utf-8")
        hits = list(distro._scan_text(rel, txt))
        assert hits == [], f"Unexpected PII hits in {rel}: {hits}"

    assert len((REPO_ROOT / "steward_cockpit/wave_map_model.py").read_text(encoding="utf-8").splitlines()) < 300
    assert len((REPO_ROOT / "steward_cockpit/static/cockpit-wave-map.js").read_text(encoding="utf-8").splitlines()) < 320
    assert len((REPO_ROOT / "steward_cockpit/deliverable_shelves.py").read_text(encoding="utf-8").splitlines()) < 320
    assert len((REPO_ROOT / "steward_cockpit/static/cockpit-deliverable-shelves.js").read_text(encoding="utf-8").splitlines()) < 300

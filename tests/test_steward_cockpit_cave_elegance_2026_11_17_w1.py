"""Wave 1 regression & integration suite for AI Cockpit Deliverables Read-Time Fold
and Sequential Auto-Updating Plan Slice (2026-11-17).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from steward_cockpit import steward_campaign as sc
from tools import steward_plan


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_JS_PATH = REPO_ROOT / "steward_cockpit" / "static" / "shared.js"
STEWARD_CAMPAIGN_PY_PATH = REPO_ROOT / "steward_cockpit" / "steward_campaign.py"


def _write_campaign_fixture(
    cdir: Path,
    *,
    ecgberht_md: str,
    deliverables_md: str,
    plan_md: str | None = None,
) -> Path:
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / "ECGBERHT.md").write_text(ecgberht_md, encoding="utf-8")
    (cdir / "DELIVERABLES.md").write_text(deliverables_md, encoding="utf-8")
    if plan_md is not None:
        (cdir / "PLAN.md").write_text(plan_md, encoding="utf-8")
    return cdir


def _run_shared_js_scenario(scenario: dict) -> dict:
    """Execute steward_cockpit/static/shared.js inside Node's vm module to verify
    Proto.init, Proto.paintStepsList, and Proto.renderDeliverablesTile."""
    node_script = r"""
const fs = require("fs"), vm = require("vm");
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));
const sharedJsCode = fs.readFileSync(scenario.sharedJsPath, "utf8");

function matchOne(el, raw) {
  if (!el || el.nodeType !== 1) return false;
  let s = raw.trim();
  if (!s) return false;
  const negs = [], attrs = [], ids = [], clss = [];
  s = s.replace(/:not\(([^)]+)\)/g, (_, x) => (negs.push(x.trim()), ""))
       .replace(/\[([^\]]+)\]/g, (_, x) => (attrs.push(x.trim()), ""))
       .replace(/#([A-Za-z0-9_-]+)/g, (_, x) => (ids.push(x), ""))
       .replace(/\.([A-Za-z0-9_-]+)/g, (_, x) => (clss.push(x), "")).trim();
  if (negs.some((n) => matchOne(el, n))) return false;
  for (const a of attrs) {
    const eq = a.indexOf("=");
    if (eq < 0 ? !el.hasAttribute(a) : el.getAttribute(a.slice(0, eq).trim()) !== a.slice(eq + 1).trim().replace(/^["']|["']$/g, "")) return false;
  }
  if (ids.some((i) => el.id !== i) || clss.some((c) => !el.classList.contains(c))) return false;
  return !s || s === "*" || el.tagName === s.toUpperCase();
}
function matchSel(el, sel) {
  return String(sel || "").split(",").map((s) => s.trim()).filter(Boolean).some((part) => {
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

class MockElement {
  constructor(tag) {
    this.tagName = String(tag || "DIV").toUpperCase();
    this.nodeType = 1; this.className = ""; this._text = ""; this.id = ""; this.title = "";
    this.href = ""; this.target = ""; this.rel = ""; this.download = ""; this.type = "";
    this.value = ""; this.placeholder = ""; this.tabIndex = 0; this.hidden = false;
    this.disabled = false; this.open = false; this.scrollTop = 0; this.scrollHeight = 200;
    this.clientHeight = 200; this.offsetWidth = 360; this.isConnected = true;
    this.style = { setProperty() {}, removeProperty() {} };
    this.dataset = {}; this.attributes = {}; this.children = []; this.childNodes = [];
    this.parentElement = null; this._listeners = {};
    const self = this, set = () => new Set(String(self.className || "").split(/\s+/).filter(Boolean));
    const sync = (s) => { self.className = [...s].join(" "); };
    this.classList = {
      add(...t) { const s = set(); t.forEach((x) => x && s.add(String(x))); sync(s); },
      remove(...t) { const s = set(); t.forEach((x) => s.delete(String(x))); sync(s); },
      contains(t) { return set().has(String(t)); },
      toggle(t, f) { const s = set(), k = String(t), on = f !== undefined ? Boolean(f) : !s.has(k); if (on) s.add(k); else s.delete(k); sync(s); return on; },
    };
  }
  get textContent() { return this.childNodes.length ? this.childNodes.map((c) => c.textContent).join("") : (this._text || ""); }
  set textContent(v) { this.children = []; this.childNodes = []; this._text = v == null ? "" : String(v); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  get previousElementSibling() { const p = this.parentElement, i = p ? p.children.indexOf(this) : -1; return i > 0 ? p.children[i - 1] : null; }
  get parentNode() { return this.parentElement; }
  contains(o) { for (let c = o; c; c = c.parentElement) if (c === this) return true; return false; }
  appendChild(c) { if (!c) return c; if (c.parentElement) c.remove(); c.parentElement = this; c.isConnected = true; this.childNodes.push(c); if (c.nodeType === 1) this.children.push(c); return c; }
  insertBefore(c, r) { if (!c || !r) return this.appendChild(c); if (c.parentElement) c.remove(); c.parentElement = this; c.isConnected = true; const i = this.childNodes.indexOf(r); if (i >= 0) this.childNodes.splice(i, 0, c); else this.childNodes.push(c); if (c.nodeType === 1) { const ci = this.children.indexOf(r); if (ci >= 0) this.children.splice(ci, 0, c); else this.children.push(c); } return c; }
  replaceChild(n, o) { if (n && o) { this.insertBefore(n, o); o.remove(); } return o; }
  removeChild(c) { if (c && c.parentElement === this) c.remove(); return c; }
  insertAdjacentElement(_, el) { if (this.parentElement) this.parentElement.appendChild(el); return el; }
  remove() { if (!this.parentElement) return; const p = this.parentElement; p.children = p.children.filter((c) => c !== this); p.childNodes = p.childNodes.filter((c) => c !== this); this.parentElement = null; }
  setAttribute(k, v) { k = String(k); v = String(v); this.attributes[k] = v; if (k === "class") this.className = v; if (k === "id") this.id = v; if (k === "href") this.href = v; if (k === "download") this.download = v; if (k === "type") this.type = v; if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v; }
  getAttribute(k) { k = String(k); if (k === "href" && this.href) return this.href; if (k === "download" && this.download) return this.download; if (k === "id" && this.id) return this.id; if (k === "class" && this.className) return this.className; if (Object.prototype.hasOwnProperty.call(this.attributes, k)) return this.attributes[k]; if (k.startsWith("data-")) { const cm = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()); if (Object.prototype.hasOwnProperty.call(this.dataset, cm)) return String(this.dataset[cm]); } return null; }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { if (this._listeners[t]) this._listeners[t] = this._listeners[t].filter((f) => f !== fn); }
  dispatchEvent(ev) { (this._listeners[ev && ev.type] || []).forEach((f) => f.call(this, ev)); return true; }
  focus() {} select() {} scrollIntoView() {} getBoundingClientRect() { return { left: 0, top: 0, width: 360, height: 200 }; }
  closest(sel) { for (let c = this; c && c.nodeType === 1; c = c.parentElement) if (matchSel(c, sel)) return c; return null; }
  querySelectorAll(sel) { const out = [], walk = (n) => { for (const ch of n.children || []) { if (matchSel(ch, sel)) out.push(ch); walk(ch); } }; walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

(async () => {
  const docEl = new MockElement("html"), head = new MockElement("head"), body = new MockElement("body"), app = new MockElement("div");
  app.className = "app appx app3"; docEl.appendChild(head); docEl.appendChild(body); body.appendChild(app);
  const slot = (tag, cls, attrs = {}, parent = app) => {
    const n = new MockElement(tag); if (cls) n.className = cls;
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    parent.appendChild(n); return n;
  };
  [
    ["span", "dot", { "data-att": "1" }], ["span", "title", { "data-name": "1" }], ["span", "chip", { "data-spend": "1" }],
    ["div", "goalbar", { "data-goalbar": "1" }], ["span", "gbrief", { "data-goalbrief": "1" }], ["div", "gfull", { "data-goalfull": "1" }],
    ["div", "gkick", { "data-kickoff": "1" }], ["section", "top-approval-bar", { "data-top-approval-bar": "1" }],
    ["h2", "", { "data-plan-head": "1" }], ["span", "rail-wave-count", { "data-plan-count": "1" }],
    ["div", "progress", { "data-progress": "1" }], ["i", "", { "data-progress-fill": "1" }],
    ["div", "plan-error-banner", { "data-plan-error": "1" }], ["section", "plan-focus-card", { "data-plan-focus": "1" }],
    ["section", "plan-proposal-banner", { "data-plan-proposal": "1" }], ["div", "scroll", {}],
    ["textarea", "", { "data-say": "1" }], ["button", "send", { "data-send": "1" }],
  ].forEach(([t, c, a]) => slot(t, c, a));
  const addForm = slot("form", "plan-add-bar", { "data-plan-add": "1" });
  slot("input", "", { type: "text", "data-plan-add-title": "1" }, addForm);
  slot("input", "", { type: "text", "data-plan-add-goal": "1" }, addForm);
  slot("button", "", { type: "submit", "data-plan-add-submit": "1" }, addForm);
  const stepsUl = slot("ul", "steps", { "data-steps": "1" });
  const statusPane = slot("div", "rightcol", { "data-statuspane": "1" });
  const delivMount = slot("div", "pdeliv", { "data-delivmount": "1" }, statusPane);
  slot("div", "pscroll", {}, statusPane);

  const document = {
    documentElement: docEl, head, body, title: "", visibilityState: "visible", activeElement: null,
    createElement: (t) => new MockElement(t), createElementNS: (_, t) => new MockElement(t),
    createTextNode: (txt) => ({ nodeType: 3, textContent: String(txt || ""), parentElement: null, remove() {} }),
    querySelector: (s) => docEl.querySelector(s), querySelectorAll: (s) => docEl.querySelectorAll(s),
    getElementById: (id) => docEl.querySelector("#" + id), addEventListener() {}, removeEventListener() {},
  };
  const fetchedUrls = [], searchStr = scenario.search || "?dir=test_effort", storage = {};
  const mockStorage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null),
    setItem: (k, v) => { storage[k] = String(v); }, removeItem: (k) => { delete storage[k]; },
  };
  const mapPayload = scenario.map || {
    name: "Test Effort", goal_brief: "Ship clean deliverables and sequential plan",
    steps_done: 1, steps_total: 3, now_step_id: "s2",
    steps: [
      { id: "s1", name: "Phase 1: Foundation — Lock schema", status: "done", done: true, part: "Phase 1: Foundation" },
      { id: "s2", name: "Phase 2: Execution — Fold deliverables", status: "active", done: false, part: "Phase 2: Execution" },
      { id: "s3", name: "Phase 2: Execution — Verify cockpit", status: "planned", done: false, part: "Phase 2: Execution" },
    ],
    running_overview: scenario.runningOverview || { goal: "Ship clean deliverables and sequential plan", doing_now: "Working on Phase 2: Execution" },
  };
  const planPayload = scenario.plan || {
    ok: true, failure_state: "ok", steps: mapPayload.steps, counts: { done: 1, total: 3, parked: 0 },
    focus: { step_id: "s2", title: "Phase 2: Execution — Fold deliverables", next_move: "Verify fold" }, proposal: null,
  };
  const delivPayload = scenario.deliverables || {
    ok: true, exists: true, failure_state: "ok", items: [], approved: [], acts: [],
    buckets: { for_review: [], final: [], in_progress: [], archive: [] }, key_deliverables: [],
    deliverable_hierarchy: { is_course: false, executive_summary: {}, categories: [], supporting_files: [], supporting_drawer: { title: "Supporting & Earlier Files", collapsed: true, count: 0, files: [] } },
  };
  const fetchMock = async (url) => {
    const u = String(url); fetchedUrls.push(u);
    if (u.includes("/api/events")) return new Promise(() => {});
    if (u.includes("/api/map")) return { ok: true, status: 200, json: async () => mapPayload };
    if (u.includes("/api/plan")) return { ok: true, status: 200, json: async () => planPayload };
    if (u.includes("/api/deliverables")) return { ok: true, status: 200, json: async () => delivPayload };
    if (u.includes("/api/state")) return { ok: true, status: 200, json: async () => ({ ok: true, alive: false, busy: false, stamp: "s1" }) };
    if (u.includes("/api/status")) return { ok: true, status: 200, json: async () => ({ ok: true, history_updates: [] }) };
    if (u.includes("/api/history")) return { ok: true, status: 200, json: async () => ({ turns: [] }) };
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };
  const sandbox = {
    window: null, globalThis: null, document, URLSearchParams, URL, AbortController, console,
    location: { search: searchStr, origin: "http://localhost:8777", pathname: "/steward/v1", href: "http://localhost:8777/steward/v1" + searchStr, reload() {} },
    localStorage: mockStorage, sessionStorage: mockStorage, fetch: fetchMock,
    XMLHttpRequest: class { open() {} send() {} }, Event: class { constructor(t) { this.type = t; } },
    getComputedStyle: () => ({ minHeight: "46px" }), mdRender: (el, txt) => { if (el) el.textContent = String(txt || ""); },
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    innerHeight: 900, innerWidth: 1400, navigator: {},
    btoa: (s) => Buffer.from(String(s), "binary").toString("base64"),
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.window.parent = sandbox; sandbox.window.addEventListener = () => {};

  const Proto = vm.runInNewContext(sharedJsCode + "\n;Proto;", sandbox);
  await Proto.init({ statusPane: true });
  if (scenario.callPaintStepsDirectly) Proto.paintStepsList(mapPayload);
  if (scenario.callRenderDeliverablesDirectly) await Proto.renderDeliverablesTile();

  const phaseEls = stepsUl.querySelectorAll("details.plan-major-phase");
  const stepS2 = stepsUl.querySelector('li[data-step-id="s2"]');
  const stepClickToggleStates = [];
  if (stepS2 && typeof stepS2.onclick === "function") {
    stepS2.onclick({ target: stepS2 }); stepClickToggleStates.push(stepS2.classList.contains("open"));
    stepS2.onclick({ target: stepS2 }); stepClickToggleStates.push(stepS2.classList.contains("open"));
  }
  const suppDrawer = delivMount.querySelector("details.deliv-supporting-drawer");
  process.stdout.write(JSON.stringify({
    fetchedPlan: fetchedUrls.some((u) => u.includes("/api/plan")),
    stepsChildCount: stepsUl.children.length,
    stepsText: stepsUl.textContent,
    hasRunningOverviewHeader: Boolean(stepsUl.querySelector("details.steward-running-overview")),
    phaseTitles: phaseEls.map((p) => (p.querySelector(".plan-sec-title") || {}).textContent || ""),
    phaseOpenStates: phaseEls.map((p) => Boolean(p.open)),
    stepClickToggleStates,
    hasHierarchyRoot: Boolean(delivMount.querySelector(".deliv-hierarchy-root")),
    delivMountText: delivMount.textContent,
    formatPills: delivMount.querySelectorAll("a.deliv-format-pill").map((a) => ({ label: a.textContent, href: a.href, pillType: a.dataset.pillType || "" })),
    treeNodes: delivMount.querySelectorAll(".deliv-tree-node").filter((n) => !n.classList.contains("is-supporting")).map((n) => {
      const dlA = n.querySelector("a.deliv-dl-arrow");
      return {
        path: n.dataset.filePath || "", hash: n.dataset.fileHash || "", productId: n.dataset.productId || "",
        suggestedFilename: n.dataset.suggestedFilename || "", route: n.dataset.route || "",
        downloadAttr: dlA ? dlA.download : "", downloadHref: dlA ? dlA.href : "",
      };
    }),
    suppDrawer: suppDrawer ? {
      open: Boolean(suppDrawer.open),
      summaryText: (suppDrawer.querySelector("summary") || {}).textContent || "",
      files: suppDrawer.querySelectorAll(".is-supporting").map((r) => r.dataset.filePath || ""),
    } : null,
  }));
})().catch((err) => { console.error(err); process.exit(1); });
"""
    payload = {"sharedJsPath": str(SHARED_JS_PATH), **scenario}
    with tempfile.TemporaryDirectory() as tmp_dir:
        script_file = Path(tmp_dir) / "run_shared_scenario.cjs"
        script_file.write_text(node_script, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script_file)],
            input=json.dumps(payload),
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        )
    return json.loads(proc.stdout)


def test_w1_shared_folder_sweep_deleted_while_step0_final_deliverables_pass3_intact(tmp_path: Path):
    """(1) lines 5408-5409 shared-folder sweep are deleted while keeping Pass-3 for Step-0 Final Deliverables/<unit> folders."""
    cdir = tmp_path / "course-campaign"
    # Shared flat directory with two distinct lectures plus an unrelated scratch file
    flat_dir = cdir / "deliverables"
    flat_dir.mkdir(parents=True, exist_ok=True)
    (flat_dir / "Lecture_01_Intro.pdf").write_bytes(b"%PDF-1.4 lec1")
    (flat_dir / "Lecture_02_Normal.pdf").write_bytes(b"%PDF-1.4 lec2")
    (flat_dir / "Unrelated_Scratch_Dump.pdf").write_bytes(b"%PDF-1.4 scratch")

    # Non-Step-0 custom subfolder with a registered file AND an unregistered sibling file
    # (if Pass-1/2 added full_p.parent to dirs_on_disk, Pass-3 would sweep Unregistered_Sibling_Deck.pptx into lecture-01)
    custom_unit_dir = cdir / "Lecture 1 Materials"
    custom_unit_dir.mkdir(parents=True, exist_ok=True)
    (custom_unit_dir / "Lecture_01_Handout.pdf").write_bytes(b"%PDF-1.4 lec1 handout")
    (custom_unit_dir / "Unregistered_Sibling_Deck.pptx").write_bytes(b"PK-unregistered-sibling")

    # Step-0 Final Deliverables/<unit> folder on disk (unindexed in DELIVERABLES.md, discovered via Pass-3)
    fin_unit_dir = cdir / "Final Deliverables" / "Lecture 3 - Sampling Distributions"
    fin_unit_dir.mkdir(parents=True, exist_ok=True)
    (fin_unit_dir / "Lecture_03_Deck.pptx").write_bytes(b"PK-pptx-lec3")
    (fin_unit_dir / "Lecture_03_Reading.pdf").write_bytes(b"%PDF-1.4 lec3")

    _write_campaign_fixture(
        cdir,
        ecgberht_md=(
            "# Campaign: MBA Course\n\n"
            "## The Plan\n"
            "- [x] **Lecture 1** (id: `lec-1`) — Intro\n"
            "- [ ] **Lecture 2** (id: `lec-2`) — Normal\n"
        ),
        deliverables_md=(
            "# Deliverables\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            "| FINAL: Lecture 1 — Intro | `deliverables/Lecture_01_Intro.pdf` | 2026-11-10 | lec-1 |\n"
            "| FINAL: Lecture 1 — Handout | `Lecture 1 Materials/Lecture_01_Handout.pdf` | 2026-11-10 | lec-1 |\n"
            "| FOR REVIEW: Lecture 2 — Normal | `deliverables/Lecture_02_Normal.pdf` | 2026-11-11 | lec-2 |\n"
        ),
    )

    deliv = sc.read_deliverables(str(cdir))
    hier = deliv["deliverable_hierarchy"]
    assert hier["is_course"] is True

    units_by_key = {
        u["unit_key"]: u
        for cat in hier["categories"]
        for u in cat.get("units", [])
    }
    assert "lecture-01" in units_by_key
    assert "lecture-02" in units_by_key
    # Step-0 Final Deliverables/<unit> discovered and populated via Pass-3
    assert "lecture-03" in units_by_key
    lec3_files = [f["path"] for f in units_by_key["lecture-03"]["files"]]
    assert any("Final Deliverables/Lecture 3 - Sampling Distributions" in p for p in lec3_files)

    # Lecture 1 must NOT contain Lecture 2's file, the unrelated scratch file, or the unregistered sibling in Lecture 1 Materials/
    lec1_paths = [f["path"] for f in units_by_key["lecture-01"]["files"]]
    assert "deliverables/Lecture_01_Intro.pdf" in lec1_paths
    assert "Lecture 1 Materials/Lecture_01_Handout.pdf" in lec1_paths
    assert all(
        "Lecture_02" not in p
        and "Unrelated_Scratch" not in p
        and "Unregistered_Sibling_Deck" not in p
        for p in lec1_paths
    )
    all_supp_paths = [f["path"] for f in hier["supporting_drawer"]["files"]]
    assert all(
        "Unrelated_Scratch" not in p and "Unregistered_Sibling_Deck" not in p
        for p in all_supp_paths
    )


def test_w1_client_deliverable_hierarchy_fallbacks_deleted_in_shared_js(tmp_path: Path):
    """(2) buildClientDeliverableHierarchyFallback and running_overview.deliverable_hierarchy fallback in shared.js are deleted."""
    js_src = SHARED_JS_PATH.read_text(encoding="utf-8")
    assert "buildClientDeliverableHierarchyFallback" not in js_src
    assert "ovRawForHier.deliverable_hierarchy" not in js_src
    assert not hasattr(sc, "build_oranges_forecast")

    cdir = _write_campaign_fixture(
        tmp_path / "ov-clean",
        ecgberht_md="# Campaign: Clean Overview\n\n## The Plan\n- [ ] **Step 1** (id: `s1`) — Goal\n",
        deliverables_md="# Deliverables\n\n| What | Where | Date | Step |\n|---|---|---|---|\n",
    )
    ov = sc.build_running_overview(str(cdir))
    assert "oranges_forecast" not in ov
    assert "deliverable_hierarchy" not in ov
    assert isinstance(ov.get("key_deliverables"), list)

    # Behavioral check: when server deliverable_hierarchy has no categories, shared.js must NOT
    # fall back to map.running_overview.deliverable_hierarchy or synthesize a client hierarchy from items.
    dom_res = _run_shared_js_scenario({
        "search": "?dir=test_effort",
        "runningOverview": {
            "goal": "Test fallback removal",
            "deliverable_hierarchy": {
                "is_course": True,
                "executive_summary": {"units_total": 1, "files_total": 1, "headline": "Stale Overview Hierarchy"},
                "categories": [
                    {
                        "id": "lectures",
                        "title": "Stale Overview Category",
                        "units": [
                            {
                                "unit_key": "lecture-01",
                                "label": "Lecture 1",
                                "title": "Lecture 1 — Stale Fallback",
                                "status": "Final",
                                "files": [{"title": "Stale File", "path": "deliverables/stale.pdf", "ext": "PDF"}],
                            }
                        ],
                    }
                ],
            },
        },
        "deliverables": {
            "ok": True,
            "exists": True,
            "failure_state": "ok",
            "items": [
                {"what": "FINAL: Lecture 1 Slides", "path": "deliverables/Lecture_01_Slides.pdf", "openable": True, "date": "2026-11-15", "step": "s1"},
                {"what": "Supporting Script", "path": "deliverables/sim.R", "openable": True, "date": "2026-11-15", "step": "s1"},
            ],
            "approved": [],
            "acts": [],
            "buckets": {"for_review": [], "final": [], "in_progress": [], "archive": []},
            "key_deliverables": [],
            "deliverable_hierarchy": {"is_course": False, "executive_summary": {}, "categories": []},
        },
    })
    assert dom_res["hasHierarchyRoot"] is False
    assert "Stale Overview Category" not in dom_res["delivMountText"]
    assert "Stale Overview Hierarchy" not in dom_res["delivMountText"]


def test_w1_fold_token_matrix_format_redline_pills_and_supporting_drawer(tmp_path: Path):
    """(3) & (5) Fold ISO dates & explicit version tokens (v\\d+, Draft \\d+, Refinement \\d+, Rev \\d+,
    never bare unit numbers like Lecture 10 or Chapter 3) at read time into 1 latest row per main product
    with inline format/redline pills, preserved hash/product_id/suggested_filename//steward/v1/open routes,
    and one collapsed 'Supporting & Earlier Files' drawer.
    """
    cdir = tmp_path / "fold-matrix-campaign"
    files_to_create = {
        "deliverables/Lecture_10_Slides_2026-10-01_v1.pdf": b"%PDF-1.4 lec10 v1",
        "deliverables/Lecture_10_Slides_2026-11-15_v2.pdf": b"%PDF-1.4 lec10 v2 latest",
        "deliverables/Lecture_10_Slides_2026-11-15_v2.pptx": b"PK-lec10-v2-pptx",
        "deliverables/Lecture_10_Slides_2026-11-15_v2_redline.docx": b"PK-lec10-v2-redline",
        "deliverables/Lecture_01_Slides_Draft_1.pdf": b"%PDF-1.4 lec1 draft1",
        "deliverables/Lecture_01_Slides_Draft_2.pdf": b"%PDF-1.4 lec1 draft2",
        "deliverables/Chapter_2_Manuscript_Refinement_1.docx": b"PK-ch2-ref1",
        "deliverables/Chapter_2_Manuscript_Refinement_2.docx": b"PK-ch2-ref2",
        "deliverables/Chapter_3_Manuscript_Rev_1.docx": b"PK-ch3-rev1",
        "deliverables/Chapter_3_Manuscript_Rev_2.docx": b"PK-ch3-rev2",
        "deliverables/Lecture_10_Simulation.R": b"# R script",
        "deliverables/Lecture_10_Dataset.csv": b"a,b\n1,2\n",
        "deliverables/Lecture_10_Audit_Report.md": b"# Audit Report\nPassed.",
    }
    for rel, raw in files_to_create.items():
        fp = cdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(raw)

    latest_lec10_bytes = files_to_create["deliverables/Lecture_10_Slides_2026-11-15_v2.pdf"]
    expected_hash = hashlib.sha256(latest_lec10_bytes).hexdigest()
    expected_managed_filename = "Lecture-10-Causality-Managed.pdf"
    expected_open_route = "/steward/v1/open?pid=test&path=deliverables/Lecture_10_Slides_2026-11-15_v2.pdf"

    _write_campaign_fixture(
        cdir,
        ecgberht_md=(
            "# Campaign: Fold Matrix\n\n"
            "## The Plan\n"
            "- [ ] **Lecture 1** (id: `lec-1`) — Foundations\n"
            "- [ ] **Lecture 10** (id: `lec-10`) — Causality\n"
            "- [ ] **Book Chapters** (id: `chapters`) — Chapters 2 and 3\n"
        ),
        deliverables_md=(
            "# Deliverables\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            "| Earlier: Lecture 10 Slides v1 (2026-10-01) | `deliverables/Lecture_10_Slides_2026-10-01_v1.pdf` | 2026-10-01 | lec-10 |\n"
            "| FOR REVIEW: Lecture 10 Slides v2 (2026-11-15) | `deliverables/Lecture_10_Slides_2026-11-15_v2.pdf` | 2026-11-15 | lec-10 |\n"
            "| FOR REVIEW: Lecture 10 Slides v2 Editable Deck | `deliverables/Lecture_10_Slides_2026-11-15_v2.pptx` | 2026-11-15 | lec-10 |\n"
            "| FOR REVIEW: Lecture 10 Slides v2 Redline Track Changes | `deliverables/Lecture_10_Slides_2026-11-15_v2_redline.docx` | 2026-11-15 | lec-10 |\n"
            "| Earlier: Lecture 1 Slides Draft 1 | `deliverables/Lecture_01_Slides_Draft_1.pdf` | 2026-11-10 | lec-1 |\n"
            "| FOR REVIEW: Lecture 1 Slides Draft 2 | `deliverables/Lecture_01_Slides_Draft_2.pdf` | 2026-11-14 | lec-1 |\n"
            "| Earlier: Chapter 2 Manuscript Refinement 1 | `deliverables/Chapter_2_Manuscript_Refinement_1.docx` | 2026-11-12 | chapters |\n"
            "| FOR REVIEW: Chapter 2 Manuscript Refinement 2 | `deliverables/Chapter_2_Manuscript_Refinement_2.docx` | 2026-11-16 | chapters |\n"
            "| Earlier: Chapter 3 Manuscript Rev 1 | `deliverables/Chapter_3_Manuscript_Rev_1.docx` | 2026-11-12 | chapters |\n"
            "| FOR REVIEW: Chapter 3 Manuscript Rev 2 | `deliverables/Chapter_3_Manuscript_Rev_2.docx` | 2026-11-16 | chapters |\n"
            "| Supporting — Lecture 10 Simulation Script | `deliverables/Lecture_10_Simulation.R` | 2026-11-15 | lec-10 |\n"
            "| Supporting — Lecture 10 Dataset | `deliverables/Lecture_10_Dataset.csv` | 2026-11-15 | lec-10 |\n"
            "| Lecture 10 Verification Audit Report | `deliverables/Lecture_10_Audit_Report.md` | 2026-11-15 | lec-10 |\n"
        ),
    )

    # Seed explicit managed item metadata (hash, product_id, suggested_filename, /steward/v1/open route)
    raw_d = sc._read_deliverables(str(cdir))
    for it in raw_d["items"]:
        if "Lecture_10_Slides_2026-10-01_v1.pdf" in str(it.get("path") or ""):
            it["product_id"] = "prod-lec10-slides"
        if "Lecture_10_Slides_2026-11-15_v2.pdf" in str(it.get("path") or ""):
            it["hash"] = expected_hash
            it["product_id"] = "prod-lec10-slides"
            it["suggested_filename"] = expected_managed_filename
            it["route"] = expected_open_route
            it["managed"] = True

    map_ = sc.read_map(str(cdir))
    hier = sc.build_deliverable_hierarchy(str(cdir), raw_d["items"], raw_d.get("approved") or [], map_.get("steps") or [])

    units_by_key = {
        u["unit_key"]: u
        for cat in hier["categories"]
        for u in cat.get("units", [])
    }
    # Bare unit numbers (Lecture 1 vs Lecture 10; Chapter 2 vs Chapter 3) MUST stay separate!
    assert "lecture-01" in units_by_key
    assert "lecture-10" in units_by_key
    assert len(units_by_key["lecture-01"]["files"]) == 1
    assert units_by_key["lecture-01"]["files"][0]["path"] == "deliverables/Lecture_01_Slides_Draft_2.pdf"

    assert len(units_by_key["lecture-10"]["files"]) == 1
    lec10_main = units_by_key["lecture-10"]["files"][0]
    assert lec10_main["hash"] == expected_hash
    assert lec10_main["product_id"] == "prod-lec10-slides"
    assert lec10_main["suggested_filename"] == expected_managed_filename
    assert lec10_main["route"] == expected_open_route

    # Inline format & redline pills on Lecture 10 folded row
    pills = lec10_main["format_pills"]
    pill_labels = [p["label"] for p in pills]
    assert "PDF" in pill_labels
    assert "PPTX" in pill_labels
    assert any(p.get("is_redline") is True and p.get("pill_type") == "redline" for p in pills)

    # Chapter 2 and Chapter 3 stay separate main products in the chapters step
    ch_unit = units_by_key["step-03-chapters"]
    ch_paths = [f["path"] for f in ch_unit["files"]]
    assert "deliverables/Chapter_2_Manuscript_Refinement_2.docx" in ch_paths
    assert "deliverables/Chapter_3_Manuscript_Rev_2.docx" in ch_paths
    assert len(ch_paths) == 2

    # Scripts, datasets, audits, and superseded prior versions are tucked into the single collapsed Supporting & Earlier Files drawer
    drawer = hier["supporting_drawer"]
    assert drawer["title"] == "Supporting & Earlier Files"
    assert drawer["collapsed"] is True
    supp_paths = {f["path"] for f in drawer["files"]}
    assert "deliverables/Lecture_10_Simulation.R" in supp_paths
    assert "deliverables/Lecture_10_Dataset.csv" in supp_paths
    assert "deliverables/Lecture_10_Audit_Report.md" in supp_paths
    assert "deliverables/Lecture_10_Slides_2026-10-01_v1.pdf" in supp_paths
    assert "deliverables/Lecture_01_Slides_Draft_1.pdf" in supp_paths
    assert "deliverables/Chapter_2_Manuscript_Refinement_1.docx" in supp_paths
    assert "deliverables/Chapter_3_Manuscript_Rev_1.docx" in supp_paths

    # Behavioral DOM verification via shared.js execution in Node:
    # verify folded row, inline format/redline pills, preserved /steward/v1/open route + suggested_filename,
    # and the collapsed 'Supporting & Earlier Files' drawer.
    dom_res = _run_shared_js_scenario({
        "search": "?dir=fold-matrix-campaign",
        "deliverables": {
            "ok": True,
            "exists": True,
            "failure_state": "ok",
            "items": raw_d["items"],
            "approved": [],
            "acts": [],
            "buckets": {"for_review": [], "final": [], "in_progress": [], "archive": []},
            "key_deliverables": [],
            "deliverable_hierarchy": hier,
        },
    })
    assert dom_res["hasHierarchyRoot"] is True
    lec10_node = next(n for n in dom_res["treeNodes"] if n["path"] == "deliverables/Lecture_10_Slides_2026-11-15_v2.pdf")
    assert lec10_node["hash"] == expected_hash
    assert lec10_node["productId"] == "prod-lec10-slides"
    assert lec10_node["suggestedFilename"] == expected_managed_filename
    assert lec10_node["downloadAttr"] == expected_managed_filename
    assert lec10_node["route"] == expected_open_route

    rendered_pills = dom_res["formatPills"]
    assert any(p["label"] == "PDF" and "/steward/v1/open" in p["href"] for p in rendered_pills)
    assert any(p["label"] == "PPTX" for p in rendered_pills)
    assert any(p["pillType"] == "redline" and "Redline" in p["label"] for p in rendered_pills)

    rendered_drawer = dom_res["suppDrawer"]
    assert rendered_drawer is not None
    assert rendered_drawer["open"] is False
    assert "Supporting & Earlier Files" in rendered_drawer["summaryText"]
    assert "deliverables/Lecture_10_Simulation.R" in rendered_drawer["files"]
    assert "deliverables/Lecture_10_Dataset.csv" in rendered_drawer["files"]
    assert "deliverables/Lecture_10_Audit_Report.md" in rendered_drawer["files"]
    assert "deliverables/Lecture_10_Slides_2026-10-01_v1.pdf" in rendered_drawer["files"]


def test_w1_current_in_use_recognized_as_active_deliverable(tmp_path: Path):
    """(4) '(Current in use)' items are recognized as active deliverables (fixing Crossfit Prep 0->active)."""
    cdir = tmp_path / "crossfit-prep"
    (cdir / "deliverables").mkdir(parents=True, exist_ok=True)
    (cdir / "deliverables" / "Crossfit_Program_Guide.pdf").write_bytes(b"%PDF-1.4 crossfit guide")
    (cdir / "deliverables" / "Workout_Log_Tracker.xlsx").write_bytes(b"PK-xlsx-tracker")

    _write_campaign_fixture(
        cdir,
        ecgberht_md=(
            "# Campaign: Crossfit Prep\n\n"
            "## The Plan\n"
            "- [x] **Initial Program Design** (id: `step-1`) — Done\n"
        ),
        deliverables_md=(
            "# Deliverables — Crossfit Prep\n\n"
            "### What needs your review or decision right now\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            "| **Crossfit Program Guide** (Current in use) | `deliverables/Crossfit_Program_Guide.pdf` | 2026-11-01 | Unmapped Step |\n"
            "| **Workout Log Tracker** (Current in use) | `deliverables/Workout_Log_Tracker.xlsx` | 2026-11-01 | Unmapped Step |\n"
        ),
    )

    deliv = sc.read_deliverables(str(cdir))
    for_review = deliv["buckets"]["for_review"]
    assert len(for_review) == 2
    assert all(it["is_current"] is True and it["tier"] == "for_review" for it in for_review)
    assert deliv["current_summary"]["review_count"] == 2

    exec_sum = deliv["deliverable_hierarchy"]["executive_summary"]
    assert exec_sum["files_total"] == 2
    assert exec_sum["files_active"] == 2
    assert exec_sum["units_review"] == 1

    hier_units = [u for cat in deliv["deliverable_hierarchy"]["categories"] for u in cat["units"]]
    assert len(hier_units) == 1
    assert hier_units[0]["status"] == "For Review"
    hier_files = hier_units[0]["files"]
    assert len(hier_files) == 2
    assert all(
        f["is_current"] is True and f["is_current_in_use"] is True and f["tier"] == "for_review"
        for f in hier_files
    )


def test_w1_plan_auto_reconcile_only_on_accepted_final_and_monotonic_scope_under_lock(tmp_path: Path, monkeypatch):
    """(6) & (7) Status transitions auto-apply ONLY when backed by accepted/accepted_current/tier=='final'
    (never revision_requested) and monotonic scope additions auto-apply under plan.lock with dated snapshots
    in plan-history.json while tools/steward_plan.py explicit CLI 'propose' verb stays green (0 LLM calls).
    """
    cdir = tmp_path / "plan-reconcile-campaign"
    (cdir / "deliverables").mkdir(parents=True, exist_ok=True)
    (cdir / "deliverables" / "wave1_draft.pdf").write_bytes(b"%PDF-1.4 w1")
    (cdir / "deliverables" / "wave2_final.pdf").write_bytes(b"%PDF-1.4 w2")

    # Wire ANCHOR_RUNNER_CMD to a counter script AND spy on subprocess invocations to prove 0 LLM calls
    runner_counter_file = tmp_path / "llm_runner_invocations.log"
    fake_runner_script = tmp_path / "fail_if_llm_called.py"
    fake_runner_script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(runner_counter_file)!r}).write_text('called', encoding='utf-8')\n"
        "sys.exit(99)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f'"{sys.executable}" "{fake_runner_script}"')

    subprocess_calls: list[ object ] = []
    orig_popen = subprocess.Popen
    orig_run = subprocess.run

    def _spy_popen(*args, **kwargs):
        subprocess_calls.append(("Popen", args))
        return orig_popen(*args, **kwargs)

    def _spy_run(*args, **kwargs):
        subprocess_calls.append(("run", args))
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _spy_popen)
    monkeypatch.setattr(subprocess, "run", _spy_run)

    _write_campaign_fixture(
        cdir,
        ecgberht_md=(
            "# Campaign: Plan Auto-Reconcile\n\n"
            "## The Plan\n"
            "- [ ] **Wave 1: Architecture Draft** (id: `wave-1`) — Draft architecture\n"
            "- [ ] **Wave 2: Security Audit** (id: `wave-2`) — Complete audit\n"
        ),
        deliverables_md=(
            "# Deliverables\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            "| FOR REVIEW: Architecture Draft | `deliverables/wave1_draft.pdf` | 2026-11-15 | wave-1 |\n"
            "| FINAL: Security Audit Report | `deliverables/wave2_final.pdf` | 2026-11-16 | wave-2 |\n"
        ),
        plan_md=(
            "# Plan\n\n"
            "- [ ] **Wave 1: Architecture Draft** (id: `wave-1`) — Draft architecture\n"
            "- [ ] **Wave 2: Security Audit** (id: `wave-2`) — Complete audit\n"
            "- [ ] **Wave 3: Deployment Rollout** (id: `wave-3`) — Ship production release\n"
        ),
    )

    # Mark wave-1 deliverable as revision_requested in dismissed-deliverables.json
    sc.dismiss_deliverables(
        str(cdir),
        [{"path": "deliverables/wave1_draft.pdf", "what": "FOR REVIEW: Architecture Draft", "disposition": "revision_requested"}],
        disposition="revision_requested",
    )

    # Run auto-reconcile under plan.lock
    res = sc.reconcile_plan_under_lock(str(cdir), reason="test_reconcile")
    assert res["ok"] is True
    assert res["applied"] is True

    state = steward_plan.read_plan_state(cdir)
    steps_by_id = {s["id"]: s for s in state["steps"]}

    # wave-1 had revision_requested -> MUST NOT auto-transition to done
    assert steps_by_id["wave-1"]["status"] != "done"
    assert steps_by_id["wave-1"]["done"] is False

    # wave-2 had FINAL: -> MUST auto-transition to done
    assert steps_by_id["wave-2"]["status"] == "done"
    assert steps_by_id["wave-2"]["done"] is True

    # Wave 3 monotonic scope addition in PLAN.md -> MUST auto-apply under plan.lock
    assert any("Wave 3" in s["title"] for s in state["steps"])

    # Dated snapshot recorded in .ecgberht/plan-history.json
    hist_path = cdir / ".ecgberht" / "plan-history.json"
    assert hist_path.exists()
    hist_data = json.loads(hist_path.read_text(encoding="utf-8"))
    assert len(hist_data.get("snapshots") or []) >= 1
    rm_events = json.loads((cdir / "roadmap.json").read_text(encoding="utf-8")).get("roadmap_events") or []
    assert any(ev.get("by") == "auto-reconcile" for ev in rm_events)
    assert not any(ev.get("by") == "John" for ev in rm_events)

    # No sticky 'Updated Plan Active' or drift proposal emitted
    assert sc._read_plan_proposal_uncached(str(cdir)) is None

    # Explicit CLI 'propose' verb in tools/steward_plan.py stays green with 0 LLM / subprocess calls
    subprocess_calls.clear()
    ops_json = json.dumps([{"op": "add_step", "title": "Wave 4: Post-Launch Telemetry", "goal": "Verify metrics"}])
    rc = steward_plan.main(["--cdir", str(cdir), "propose", "--ops", ops_json, "--summary", "Add telemetry step"])
    assert rc == 0
    assert subprocess_calls == []
    assert not runner_counter_file.exists()

    prop_after_cli = steward_plan.read_plan_state(cdir)["proposal"]
    assert prop_after_cli is not None
    assert prop_after_cli["summary"] == "Add telemetry step"

    # Re-running sync_steward_projections preserves the pending CLI proposal with 0 LLM calls
    sc.sync_steward_projections(str(cdir), reason="after_cli_propose")
    assert subprocess_calls == []
    assert not runner_counter_file.exists()
    prop_still_pending = steward_plan.read_plan_state(cdir)["proposal"]
    assert prop_still_pending is not None
    assert prop_still_pending["id"] == prop_after_cli["id"]

    # Also verify CLI 'propose --steps-json' stays pending across read_map / _read_plan_proposal_uncached
    steps_json = json.dumps([
        {"id": "wave-1", "title": "Wave 1: Core Engine", "status": "done"},
        {"id": "wave-2", "title": "Wave 2: API Surface", "status": "done"},
        {"id": "wave-3", "title": "Wave 3: Integration Verification", "status": "proposed"},
        {"id": "wave-5", "title": "Wave 5: CLI Proposed Full Steps", "status": "proposed"},
    ])
    rc_steps = steward_plan.main(["--cdir", str(cdir), "propose", "--steps-json", steps_json, "--summary", "Propose full steps"])
    assert rc_steps == 0
    map_with_steps_prop = sc.read_map(str(cdir))
    assert map_with_steps_prop.get("plan_proposal") is not None
    assert map_with_steps_prop["plan_proposal"]["status"] == "pending"
    assert not any(s.get("id") == "wave-5" for s in map_with_steps_prop["steps"])


def test_w1_embed_dialogue_suppresses_plan_and_sequential_workflow_in_shared_js():
    """(6) Client drift synthesizer, sticky 'Updated Plan Active' banner, 'Accept New Plan' nag,
    and synthetic Oranges forecast card are deleted and replaced by 1 sequential click-to-expand
    Major-Phase/Step workflow anchored to ECGBERHT.md (suppressed in ?embed=dialogue).
    """
    js_src = SHARED_JS_PATH.read_text(encoding="utf-8")

    # Deleted legacy plan banners/nags/Oranges forecast
    assert "Accept New Plan" not in js_src
    assert "PARABLE OF THE ORANGES" not in js_src
    assert "sro-oranges-box" not in js_src
    assert "steward-eval-fold" not in js_src
    assert "adapted:doing-now" not in js_src

    # 1. Behavioral execution under ?embed=dialogue: plan fetch and plan rendering are suppressed
    embed_res = _run_shared_js_scenario({
        "search": "?dir=test_effort&embed=dialogue",
        "callPaintStepsDirectly": True,
    })
    assert embed_res["fetchedPlan"] is False
    assert embed_res["stepsChildCount"] == 0
    assert embed_res["stepsText"] == ""

    # 2. Behavioral execution in full cockpit: renders 1 sequential click-to-expand workflow
    # anchored to ECGBERHT.md with phases in natural order and interactive step toggle
    full_res = _run_shared_js_scenario({
        "search": "?dir=test_effort",
    })
    assert full_res["fetchedPlan"] is True
    assert full_res["hasRunningOverviewHeader"] is True
    assert "ECGBERHT.md" in full_res["stepsText"]
    assert "Accept New Plan" not in full_res["stepsText"]
    assert "PARABLE OF THE ORANGES" not in full_res["stepsText"]
    assert "Updated Plan Active" not in full_res["stepsText"]

    assert len(full_res["phaseTitles"]) == 2
    assert "Phase 1" in full_res["phaseTitles"][0]
    assert "Phase 2" in full_res["phaseTitles"][1]
    assert full_res["phaseOpenStates"] == [False, True]
    assert full_res["stepClickToggleStates"] == [True, False]


def test_w1_repeat_invocation_idempotence_and_path_escape_containment(tmp_path: Path):
    """(8) Repeat-invocation test on auto-reconcile/deliverable folding and path escape-attempt
    test (.., absolute path) confirming containment.
    """
    outside_file = tmp_path / "outside_secret.pdf"
    outside_file.write_bytes(b"%PDF-1.4 secret outside")

    cdir = tmp_path / "containment-campaign"
    (cdir / "deliverables").mkdir(parents=True, exist_ok=True)
    (cdir / "deliverables" / "Valid_Report_v1.pdf").write_bytes(b"%PDF-1.4 v1")
    (cdir / "deliverables" / "Valid_Report_v2.pdf").write_bytes(b"%PDF-1.4 v2")

    abs_escape = str(outside_file.resolve()).replace("\\", "/")
    _write_campaign_fixture(
        cdir,
        ecgberht_md=(
            "# Campaign: Containment & Idempotence\n\n"
            "## The Plan\n"
            "- [ ] **Step 1: Report** (id: `step-1`) — Deliver report\n"
        ),
        deliverables_md=(
            "# Deliverables\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            "| Earlier: Valid Report v1 | `deliverables/Valid_Report_v1.pdf` | 2026-11-10 | step-1 |\n"
            "| FINAL: Valid Report v2 | `deliverables/Valid_Report_v2.pdf` | 2026-11-15 | step-1 |\n"
            "| FINAL: Escape Parent | `../outside_secret.pdf` | 2026-11-15 | step-1 |\n"
            f"| FINAL: Escape Absolute | `{abs_escape}` | 2026-11-15 | step-1 |\n"
        ),
    )

    assert sc._is_contained_rel_path(str(cdir), "../outside_secret.pdf") == (None, "")
    assert sc._is_contained_rel_path(str(cdir), "..\\outside_secret.pdf") == (None, "")
    assert sc._is_contained_rel_path(str(cdir), abs_escape) == (None, "")
    assert sc._resolve_fuzzy_final_path(str(cdir), str(cdir.resolve()), "../outside_secret.pdf") == (None, False)
    assert sc._resolve_fuzzy_final_path(str(cdir), str(cdir.resolve()), abs_escape) == (None, False)
    assert sc.classify_route("/steward/v1/openanything") is None
    assert sc.classify_route("/steward/v1/open?evil=1") is None
    assert sc.classify_route("/steward/v1/open?path=Final%20Deliverables%2FDoc.pdf&hash=abc123") is not None

    # First invocation
    sc.sync_steward_projections(str(cdir), reason="run_1")
    deliv_1 = sc.read_deliverables(str(cdir))
    hier_1 = deliv_1["deliverable_hierarchy"]
    hist_1 = json.loads((cdir / ".ecgberht" / "plan-history.json").read_text(encoding="utf-8"))

    # Second repeat invocation
    sc.sync_steward_projections(str(cdir), reason="run_2")
    deliv_2 = sc.read_deliverables(str(cdir))
    hier_2 = deliv_2["deliverable_hierarchy"]
    hist_2 = json.loads((cdir / ".ecgberht" / "plan-history.json").read_text(encoding="utf-8"))

    # Confirm idempotence across repeat invocations
    assert hier_1 == hier_2
    assert len(hist_1.get("snapshots") or []) == len(hist_2.get("snapshots") or [])

    # Confirm escape paths never appear in the deliverable hierarchy or supporting drawer
    all_hier_paths = [
        f["path"]
        for cat in hier_1["categories"]
        for u in cat.get("units", [])
        for f in u.get("files", [])
    ] + [f["path"] for f in hier_1["supporting_drawer"]["files"]]
    assert "deliverables/Valid_Report_v2.pdf" in all_hier_paths
    assert all("outside_secret" not in p and not p.startswith("..") for p in all_hier_paths)

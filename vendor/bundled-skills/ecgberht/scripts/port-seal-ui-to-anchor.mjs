/**
 * Port Ecgberht Seal UI (TW5) from Anchor-dev into live <path>
 * Additive only: Seal button, dock host, CSS/JS, routes, handlers, icons.
 * Does not touch Anchor-release-v1.0 / v1.1 freezes.
 */
import fs from "fs";
import path from "path";

const ANCHOR = "<path>";
const DEV = "<path>";
const ECG = "<path>";

function must(cond, msg) {
  if (!cond) throw new Error(msg);
}

// --- icons (Seal + High Seat for upcoming TW6) ---
const brand = path.join(ANCHOR, "vendor/brand");
fs.mkdirSync(brand, { recursive: true });
for (const name of [
  "ecgberht-project-seal.jpg",
  "ecgberht-portfolio-high-seat.jpg",
]) {
  const src = path.join(ECG, "assets/icons", name);
  const dst = path.join(brand, name);
  must(fs.existsSync(src), `missing icon ${src}`);
  fs.copyFileSync(src, dst);
  console.log("icon", name);
}

// --- HTML ---
const htmlPath = path.join(ANCHOR, "static/project-window.html");
let html = fs.readFileSync(htmlPath, "utf8");
if (!html.includes("ecgSealBtn")) {
  const before = html;
  html = html.replace(
    "<button class='rnd-mini' id='openBoneyardBtn'",
    "<button class='rnd-mini ecg-seal-btn' id='ecgSealBtn' onclick=\"openEcgberhtSeal()\" title='Ecgberht — the steward chamber (take charge)'><img class='ecg-seal-ico' src='/vendor/brand/ecgberht-project-seal.jpg' alt='' onerror=\"this.style.display='none'\"/> Seal</button><button class='rnd-mini' id='openBoneyardBtn'"
  );
  must(html !== before, "failed to insert Seal button");
}
if (!html.includes("ecgSealHost")) {
  const before = html;
  html = html.replace(
    "<div class='live-session-bar' id='sessionBar'></div>",
    "<div class='ecg-seal-host' id='ecgSealHost'></div><div class='live-session-bar' id='sessionBar'></div>"
  );
  must(html !== before, "failed to insert ecgSealHost");
}
fs.writeFileSync(htmlPath, html);
console.log("html ok");

// --- CSS ---
const cssPath = path.join(ANCHOR, "static/project-window.css");
let css = fs.readFileSync(cssPath, "utf8");
if (!css.includes(".ecg-seal-btn")) {
  const devCss = fs.readFileSync(path.join(DEV, "static/project-window.css"), "utf8");
  const i = devCss.indexOf(".ecg-seal-btn");
  must(i >= 0, "dev css missing .ecg-seal-btn");
  let start = devCss.lastIndexOf("/*", i);
  if (start < 0 || i - start > 500) start = i;
  const j = devCss.indexOf(".ecg-footer{", i);
  must(j >= 0, "dev css missing .ecg-footer");
  const end = devCss.indexOf("}", j) + 1;
  const block = devCss.slice(start, end).trim();
  css = css.trimEnd() + "\n\n" + block + "\n";
  fs.writeFileSync(cssPath, css);
  console.log("css appended", block.length);
} else {
  console.log("css already present");
}

// --- JS ---
const jsPath = path.join(ANCHOR, "static/project-window.js");
let js = fs.readFileSync(jsPath, "utf8");
if (!js.includes("function openEcgberhtSeal")) {
  const devJs = fs.readFileSync(path.join(DEV, "static/project-window.js"), "utf8");
  let start = devJs.indexOf("/* ═");
  // find the Ecgberht Seal comment block specifically
  const cmt = devJs.indexOf("Ecgberht Seal chamber");
  must(cmt >= 0, "dev js missing Seal chamber block");
  start = devJs.lastIndexOf("/*", cmt);
  if (start < 0) start = devJs.indexOf("function _ecgEl");
  must(start >= 0, "could not find js block start");
  const openIdx = devJs.indexOf("function openEcgberhtSeal", start);
  must(openIdx >= 0, "no openEcgberhtSeal");
  let i = openIdx;
  while (i < devJs.length && devJs[i] !== "{") i++;
  let depth = 0;
  for (; i < devJs.length; i++) {
    if (devJs[i] === "{") depth++;
    else if (devJs[i] === "}") {
      depth--;
      if (depth === 0) {
        i++;
        break;
      }
    }
  }
  const chunk = devJs.slice(start, i).trim() + "\n";
  js = js.trimEnd() + "\n\n" + chunk;
  fs.writeFileSync(jsPath, js);
  console.log("js appended", chunk.length);
} else {
  console.log("js already present");
}

// --- route_table ---
const rtPath = path.join(ANCHOR, "route_table.py");
let rt = fs.readFileSync(rtPath, "utf8");
if (!rt.includes("/api/ecgberht/chamber")) {
  const re =
    /([ \t]*_r\("GET", "\/api\/rnd\/boneyard", AUTH_TOKEN, match=MATCH_PREFIX,\r?\n[ \t]*handler="handle_boneyard", migrated=True\),)/;
  must(re.test(rt), "route needle missing");
  rt = rt.replace(
    re,
    `$1
    # ── Ecgberht Seal chamber (TW5 — wireframes v2.1 Screen 1) ────────────
    # UI host: live <path> (hardened line). Engine: <path>
    _r("GET", "/api/ecgberht/chamber", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_chamber", migrated=True),
    _r("POST", "/api/ecgberht/speak", AUTH_TOKEN,
       handler="handle_ecgberht_speak", migrated=True),`
  );
  fs.writeFileSync(rtPath, rt);
  console.log("route_table ok");
} else {
  console.log("route_table already");
}

// --- anchor_gui handlers ---
const guiPath = path.join(ANCHOR, "anchor_gui.py");
let gui = fs.readFileSync(guiPath, "utf8");
if (!gui.includes("def handle_ecgberht_chamber")) {
  const handlers = `

def _ecgberht_root():
    """Resolve the Ecgberht engine root: ECGBERHT_ROOT env override, else the
    sibling checkout next to this Anchor tree (Ecgberht beside Anchor).
    Never a host-absolute literal in call sites."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "Ecgberht"


def _ecgberht_bridge(args, timeout=20):
    """Spawn the Ecgberht seal-chamber bridge (Node, read-only) and parse its
    one-line JSON. Same closed verb bodies as the ecgberht CLI (parity)."""
    import subprocess
    root = _ecgberht_root()
    bridge = root / "scripts" / "seal-chamber-bridge.mjs"
    if not bridge.exists():
        return {"ok": False, "error": "ecgberht_engine_missing",
                "message": "seal-chamber bridge not found (set ECGBERHT_ROOT "
                           "or keep Ecgberht checkout beside Anchor)"}
    try:
        res = subprocess.run(
            ["node", str(bridge)] + list(args),
            capture_output=True, text=True, timeout=timeout,
            cwd=str(root), creationflags=_paths.NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "error": "bridge_spawn_failed",
                "message": str(exc)}
    out = (res.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "bridge_no_output",
                "message": (res.stderr or "").strip()[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "bridge_bad_json",
                "message": out[:500]}


def _ecgberht_project_folder(pid):
    """project_id -> (folder, error_json, status). Same validation as boneyard."""
    if not pid:
        return None, {"ok": False, "error": "project_id required"}, 400
    if _unsafe_path_seg(pid):
        return None, {"ok": False, "error": "bad pid"}, 400
    proj = _rnd.get_project(pid)
    if proj is None:
        return None, {"ok": False, "error": "Unknown project"}, 404
    return proj.get("folder_path", ""), None, 200


def handle_ecgberht_chamber(handler, path, body):
    """GET /api/ecgberht/chamber — Seal chamber view model (wireframes v2.1 Screen 1)."""
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or q.get("pid", [""])[0] or "").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    out = _ecgberht_bridge(["--project", folder])
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_speak(handler, path, body):
    """POST /api/ecgberht/speak — compile saybox talk (closed acts only)."""
    pid = str(body.get("project_id", "") or "").strip()
    text = str(body.get("text", "") or "").strip()
    kind = str(body.get("kind", "speak") or "speak").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    if not text:
        handler._send_json({"ok": False, "error": "text required"}, 400)
        return
    flag = "--recall" if kind == "recall" else "--speak"
    out = _ecgberht_bridge(["--project", folder, flag, text])
    handler._send_json(out, 200 if out.get("ok") else 502)

`;
  const marker = "\ndef handle_build_deliverable(handler, path, body):";
  must(gui.includes(marker), "handle_build_deliverable marker missing");
  gui = gui.replace(marker, handlers + marker);
  if (!gui.includes('"handle_ecgberht_chamber"')) {
    gui = gui.replace(
      '"handle_boneyard": handle_boneyard,',
      '"handle_boneyard": handle_boneyard,\n' +
        '    "handle_ecgberht_chamber": handle_ecgberht_chamber,\n' +
        '    "handle_ecgberht_speak": handle_ecgberht_speak,'
    );
  }
  fs.writeFileSync(guiPath, gui);
  console.log("anchor_gui ok");
} else {
  console.log("anchor_gui already");
}

// sanity
const checks = {
  html_btn: fs.readFileSync(htmlPath, "utf8").includes("ecgSealBtn"),
  html_host: fs.readFileSync(htmlPath, "utf8").includes("ecgSealHost"),
  css: fs.readFileSync(cssPath, "utf8").includes(".ecg-seal-btn"),
  js: fs.readFileSync(jsPath, "utf8").includes("function openEcgberhtSeal"),
  route: fs.readFileSync(rtPath, "utf8").includes("/api/ecgberht/chamber"),
  gui: fs.readFileSync(guiPath, "utf8").includes("def handle_ecgberht_chamber"),
  seal_icon: fs.existsSync(path.join(brand, "ecgberht-project-seal.jpg")),
  high_icon: fs.existsSync(path.join(brand, "ecgberht-portfolio-high-seat.jpg")),
};
console.log("CHECKS", checks);
must(Object.values(checks).every(Boolean), "port incomplete: " + JSON.stringify(checks));
console.log("PORT COMPLETE → <path>");

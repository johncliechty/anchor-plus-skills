"""F5 DOM injection law — the registered slot inventory + growth rule
(steward-chamber W9, C10).

This module is the OWNER FILE for ``chamber/dom-slot-inventory.json`` — the
plan's REGISTERED inventory of every agent-influenced DOM slot the chamber
paints — and ships the mechanical law that keeps it true as code moves (the
living-registry law: a registry without its CI gate is a plan defect):

* **The inventory.** Versioned machine-readable data: one row per chamber
  RENDER FUNCTION (the Python layer where every agent string becomes
  markup), each carrying its mechanically-counted PLACEHOLDER count, plus
  the registered JS ``innerHTML``-class sinks inside the chamber's
  sentinel-bounded DOM region of ``static/project-window.js``.

* **The growth rule** (``python_render_problems`` / ``js_sink_problems``):
  CI fails when an agent-influenced DOM slot is added without a
  hostile-fixture row. Mechanically, at the two granularities chamber DOM
  actually grows:

  - a NEW render function in a registered chamber render module (name
    matching the render namespace) with no inventory row → named failure;
  - a CHANGED slot count inside an existing render function (a new ``%s``
    interpolation site — the AST placeholder count moved) → named failure
    until the row (and, via the fixture-completeness assertion in
    ``tests/test_chamber_dom_law_w9.py``, its hostile fixture) is updated;
  - a NEW ``innerHTML`` / ``insertAdjacentHTML`` / ``outerHTML`` /
    ``document.write`` sink inside the chamber's F5 sentinel region without
    a registered marker row → named failure;
  - stale rows (function/sink vanished) → named failure (living registry,
    never a Phase-0 snapshot).

* **The injection detector** (``dom_injection_problems``): a structural
  parse of a painted render asserting NO markup executed — no
  script/iframe/object/embed element, no ``on*`` event-handler attribute,
  and every ``href``/``src``/``formaction`` valid against the FIXED internal
  link prefixes (:data:`INTERNAL_HREF_PREFIXES`). The W9 hostile-string
  suite drives every registered slot with markup/script/handler payloads
  and runs this detector over the result.

Stdlib only (``ast``, ``html.parser``, ``json``, ``re``). Read-only — never
writes, spawns, or touches the network.
"""
from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

SCHEMA_VERSION = 1

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"
SLOT_INVENTORY_PATH = CHAMBER_DIR / "dom-slot-inventory.json"

#: The fixed internal link prefixes chamber slots may target (the F5
#: link-scheme law). Everything else — ``javascript:``, ``data:``, absolute
#: or protocol-relative URLs, an agent-invented path — is an injection
#: finding. ``#`` is the inert in-page anchor the drawn runcard links use.
INTERNAL_HREF_PREFIXES = ("/artifact/", "/report/", "/summary/", "#")

#: The render namespace: a module-level function in a registered chamber
#: render module is AGENT-INFLUENCED DOM by definition when its name starts
#: with ``render_`` / ``_render`` or ends with ``_html``.
_RENDER_NAME_RE = re.compile(r"^(?:render_|_render)|_html$")

#: JS DOM sinks the F5 law forbids unregistered (inside the sentinel region).
_JS_SINK_RE = re.compile(
    r"\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write\s*\(")

#: The sentinel comments bounding the chamber DOM region in the JS file.
JS_REGION_BEGIN = "F5-CHAMBER-DOM-BEGIN"
JS_REGION_END = "F5-CHAMBER-DOM-END"

#: The canonical hostile payloads (markup / script / event-handler / scheme),
#: driven through EVERY registered slot by tests/test_chamber_dom_law_w9.py.
HOSTILE_PAYLOADS = (
    "<script>window.__pwned=1</script>",
    "<img src=x onerror=alert(1)>",
    '"><svg onload=alert(1)>',
    "' onmouseover='alert(1)",
    "javascript:alert(1)",
    "</div><iframe src=//evil.invalid></iframe>",
)


def href_allowed(href) -> bool:
    """F5 link-scheme law: only the fixed internal prefixes may be a link
    target in a chamber slot."""
    return isinstance(href, str) and href.startswith(INTERNAL_HREF_PREFIXES)


# ═════════════════════════════════════════════════════════════════════════════
# Inventory: load / validate
# ═════════════════════════════════════════════════════════════════════════════

def load_slot_inventory(path: Path | None = None) -> dict:
    p = Path(path) if path else SLOT_INVENTORY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def validate_slot_inventory(inv: dict) -> list:
    """Structural validation (living-registry law: schema_version + named
    owner file + the registered rows). Returns problem strings."""
    problems = []
    if not isinstance(inv, dict):
        return ["slot inventory is not a JSON object"]
    if inv.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version missing or != %d" % SCHEMA_VERSION)
    if not inv.get("owner_file"):
        problems.append("owner_file missing (living-registry law)")
    mods = inv.get("python_renders")
    if not isinstance(mods, list) or not mods:
        problems.append("python_renders missing/empty")
    else:
        for i, row in enumerate(mods):
            if not row.get("module"):
                problems.append("python_renders[%d] missing module" % i)
            fns = row.get("functions")
            if not isinstance(fns, list) or not fns:
                problems.append("python_renders[%d] (%s) has no function rows"
                                % (i, row.get("module")))
                continue
            for j, fn in enumerate(fns):
                if not fn.get("name"):
                    problems.append("python_renders[%d].functions[%d] missing "
                                    "name" % (i, j))
                if not isinstance(fn.get("placeholders"), int):
                    problems.append(
                        "python_renders[%d].functions[%d] (%s) missing the "
                        "mechanical placeholder count"
                        % (i, j, fn.get("name")))
    sinks = inv.get("js_sinks")
    if not isinstance(sinks, dict) or not sinks.get("file") \
            or not isinstance(sinks.get("registered"), list):
        problems.append("js_sinks missing/invalid (file + registered rows)")
    hl = inv.get("href_law", {})
    if tuple(hl.get("internal_prefixes") or ()) != INTERNAL_HREF_PREFIXES:
        problems.append(
            "href_law.internal_prefixes does not match the code-owned "
            "INTERNAL_HREF_PREFIXES (the artifact must record the law)")
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The Python growth rule: render discovery + mechanical placeholder counts
# ═════════════════════════════════════════════════════════════════════════════

def _strip_literal_percents(s: str) -> str:
    return s.replace("%%", "")


def _module_source(module_name: str, root: Path | None = None) -> str:
    p = (root or ANCHOR_ROOT) / (module_name + ".py")
    return p.read_text(encoding="utf-8")


def discover_renders(module_name: str, root: Path | None = None) -> dict:
    """``{function_name: placeholder_count}`` for every module-level render
    function (the render namespace) in a chamber render module, from the AST
    — the count is the number of ``%s``/``%d``/``%r`` interpolation slots in
    the function's string constants (``%%`` literals stripped first)."""
    tree = ast.parse(_module_source(module_name, root))
    out: dict = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _RENDER_NAME_RE.search(node.name):
            continue
        count = 0
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                count += len(re.findall(
                    r"%[sdr]", _strip_literal_percents(sub.value)))
        out[node.name] = count
    return out


def python_render_problems(inv: dict | None = None,
                           root: Path | None = None) -> list:
    """The growth rule over the registered chamber render modules — both
    directions, slot-count-sensitive. Empty == green."""
    inv = inv if inv is not None else load_slot_inventory()
    problems = []
    for row in inv.get("python_renders", []):
        module = row.get("module")
        try:
            code = discover_renders(module, root)
        except OSError:
            problems.append("registered render module %r has no source file "
                            "(stale inventory row)" % module)
            continue
        listed = {fn.get("name"): fn for fn in row.get("functions", [])}
        for name, count in sorted(code.items()):
            if name not in listed:
                problems.append(
                    "agent-influenced DOM render added without an inventory "
                    "row: %s.%s (register it in dom-slot-inventory.json AND "
                    "give it a hostile-fixture row)" % (module, name))
            elif listed[name].get("placeholders") != count:
                problems.append(
                    "%s.%s slot count moved (inventory %r, code %d) — a new "
                    "interpolation slot needs its inventory row + hostile "
                    "fixture updated"
                    % (module, name, listed[name].get("placeholders"), count))
        for name in sorted(set(listed) - set(code)):
            problems.append("stale inventory row: %s.%s no longer exists"
                            % (module, name))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The JS growth rule: sentinel-bounded sink scan vs the registered markers
# ═════════════════════════════════════════════════════════════════════════════

def _js_region(text: str) -> str:
    begin = text.find(JS_REGION_BEGIN)
    end = text.find(JS_REGION_END)
    if begin < 0 or end < 0 or end <= begin:
        raise AssertionError(
            "the chamber F5 DOM region sentinels (%s/%s) are missing from "
            "the JS file — the sink scan has no bounded region"
            % (JS_REGION_BEGIN, JS_REGION_END))
    return text[begin:end]


def js_sink_problems(inv: dict | None = None,
                     root: Path | None = None) -> list:
    """Every innerHTML-class sink inside the chamber's sentinel region must
    be REGISTERED (its marker line in the inventory), and every registered
    marker must still exist. Empty == green."""
    inv = inv if inv is not None else load_slot_inventory()
    sinks = inv.get("js_sinks", {})
    rel = sinks.get("file") or "static/project-window.js"
    text = ((root or ANCHOR_ROOT) / rel).read_text(encoding="utf-8")
    region = _js_region(text)
    markers = [r.get("marker") for r in sinks.get("registered", [])
               if r.get("marker")]
    problems = []
    for i, line in enumerate(region.splitlines()):
        if not _JS_SINK_RE.search(line):
            continue
        if not any(m in line for m in markers):
            problems.append(
                "unregistered DOM sink inside the chamber F5 region "
                "(%s region line %d): %r — register it in "
                "dom-slot-inventory.json js_sinks or use "
                "textContent/setAttribute" % (rel, i + 1, line.strip()))
    for m in markers:
        if m not in region:
            problems.append("stale registered JS sink marker (no longer in "
                            "the chamber region): %r" % m)
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The injection detector: parse a painted render, name every F5 violation
# ═════════════════════════════════════════════════════════════════════════════

_FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "template", "base",
                   "form", "meta", "link", "style"}
_URL_ATTRS = {"href", "src", "formaction", "action", "xlink:href", "data"}


class _AttrAuditor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.problems: list = []

    def _audit(self, tag, attrs):
        if tag.lower() in _FORBIDDEN_TAGS:
            self.problems.append(
                "forbidden element executed into the DOM: <%s>" % tag)
        for name, value in attrs:
            n = (name or "").lower()
            if n.startswith("on"):
                self.problems.append(
                    "event-handler attribute reached the DOM: %s on <%s>"
                    % (name, tag))
            if n in _URL_ATTRS and not href_allowed(value or ""):
                self.problems.append(
                    "link target outside the fixed internal prefixes: "
                    "<%s %s=%r>" % (tag, name, value))

    def handle_starttag(self, tag, attrs):
        self._audit(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._audit(tag, attrs)


def dom_injection_problems(render_html: str) -> list:
    """Structural F5 audit of one painted render: forbidden elements,
    ``on*`` handler attributes, and out-of-law link targets, each named.
    Empty == no markup executed."""
    auditor = _AttrAuditor()
    auditor.feed(render_html or "")
    auditor.close()
    return auditor.problems

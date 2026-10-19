"""C9 mockup-fidelity kill gate — the DOM/class differ (steward-chamber W6).

The plan's C9 law: *the DOM/class structure of every painted chamber surface
diffs mechanically green against the SIGNED amended mockups.html, pinned to
the post-amendment markup hash recorded when John signed the W1 batched
amendment gate; the diff co-lands with the FIRST painted markup and any
deviation fails CI unless logged through the amendment gate; the diff
hard-fails if the signed hash is absent or mismatched, so no mockup-verbatim
claim can precede the signature.*

This module IS that differ, landing with W6's first painted markup (the
vertical-slice shell in :mod:`chamber_open`) and reused by W7 (full M1) and
W9 (overlays):

* **The pin.** :func:`signed_hash` reads the sha256 recorded in
  ``chamber/MOCKUP-AMENDMENT-GATE.md`` (the W1 gate record John signed);
  :func:`load_signed_mockup` reads the sibling ``mockups.html`` (resolved via
  ``ECGBERHT_ROOT`` / the sibling checkout — never a host-absolute literal)
  and raises :class:`MockupPinError` when the gate record is absent, carries
  no hash, the mockup file is absent, or its bytes hash differently. A
  MockupPinError is a HARD FAIL by plan — never a skip.
* **The spec.** :func:`slice_spec` compiles the signed §m1 + §amendments
  markup into a structural spec: the set of drawn element SIGNATURES
  ``(tag, sorted-classes)`` and the set of drawn parent→child EDGES.
* **The diff.** :func:`diff_render` walks a painted render and names every
  deviation: an element whose signature is not drawn, or a nesting the
  mockup does not draw. Two narrow, code-owned allowances keep the check
  honest rather than vacuous (both documented below): the VARIANT LAW and
  the AG composition seams. :func:`verify_slice_render` adds the REQUIRED
  direction — the slice's rendered subset must actually contain the drawn
  skeleton, so an empty ``<div class="dock">`` can never diff green.

Stdlib only (``html.parser``, ``hashlib``, ``re``). Read-only — this module
never writes, spawns, or touches the network.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import chamber_enforcement as _enf

ANCHOR_ROOT = Path(__file__).resolve().parent
GATE_RECORD_PATH = ANCHOR_ROOT / "chamber" / "MOCKUP-AMENDMENT-GATE.md"

#: The signed mockup's location INSIDE the Ecgberht sibling (the W1 gate
#: record names the same file). Resolved through the shared sibling law
#: (chamber_enforcement.ecgberht_root) — never a host-absolute literal.
MOCKUP_REL = ("planning", "steward-assessment-2026-08-08", "mockups.html")

SECTION_M1 = "m1"
SECTION_AMENDMENTS = "amendments"
SECTION_OVERLAYS = "overlays"  # W9's sections ride the same loader

_HASH_LINE_RE = re.compile(
    r"sha256\(mockups\.html\)\s*=\s*([0-9a-f]{64})")

#: Elements HTML defines as void — html.parser reports no end tag for them,
#: so the tree builder must not adopt their siblings as children.
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "source", "track", "wbr"}


class MockupPinError(AssertionError):
    """The C9 hard-fail: the signed hash is absent or mismatched — no
    mockup-verbatim claim can precede (or outlive) the signature."""


# ═════════════════════════════════════════════════════════════════════════════
# The pin: signed hash from the W1 gate record; hash-verified mockup load
# ═════════════════════════════════════════════════════════════════════════════

def signed_hash(gate_record_path=None) -> str:
    """The post-amendment markup sha256 John's W1 signature recorded."""
    p = Path(gate_record_path) if gate_record_path else GATE_RECORD_PATH
    if not p.exists():
        raise MockupPinError(
            "C9 pin: the signed amendment-gate record is ABSENT (%s) — no "
            "mockup-verbatim claim can precede the signature" % p.name)
    m = _HASH_LINE_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    if not m:
        raise MockupPinError(
            "C9 pin: the gate record carries no signed sha256(mockups.html) "
            "line — the signature has not recorded a markup hash")
    return m.group(1)


def mockup_path(root=None) -> Path:
    """The signed mockups.html inside the Ecgberht sibling.

    An explicit ``root`` is taken verbatim (the tamper/absence tests pin
    that). With no root, the env-resolved sibling is preferred — but a
    hermetic ``ECGBERHT_ROOT`` override that does not CARRY the signed file
    (a stub bridge root) falls back to the sibling checkout beside this
    tree. The C9 pin is the HASH against the Anchor-side gate record, never
    the path, so resolution can never admit an unsigned mockup.
    """
    if root:
        return Path(root).joinpath(*MOCKUP_REL)
    p = _enf.ecgberht_root().joinpath(*MOCKUP_REL)
    if p.exists():
        return p
    q = (ANCHOR_ROOT.parent / "Ecgberht").joinpath(*MOCKUP_REL)
    return q if q.exists() else p


def load_signed_mockup(root=None, gate_record_path=None) -> str:
    """Read mockups.html and HARD-verify its bytes against the signed hash."""
    p = mockup_path(root)
    if not p.exists():
        raise MockupPinError(
            "C9 pin: the signed mockup file is ABSENT (%s under the Ecgberht "
            "sibling) — the diff cannot run without the signed spec"
            % "/".join(MOCKUP_REL))
    raw = p.read_bytes()
    want = signed_hash(gate_record_path)
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise MockupPinError(
            "C9 pin: mockups.html hash MISMATCH (signed %s… vs on-disk %s…) "
            "— the mockup moved after John's signature; a deviation must be "
            "logged through the batched amendment gate, never diffed against "
            "silently" % (want[:12], got[:12]))
    return raw.decode("utf-8", errors="replace")


# ═════════════════════════════════════════════════════════════════════════════
# DOM tree: parse → nodes {tag, classes, id, children}
# ═════════════════════════════════════════════════════════════════════════════

class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.roots: list = []
        self._stack: list = []

    def _node(self, tag, attrs):
        d = dict(attrs)
        classes = tuple(sorted((d.get("class") or "").split()))
        return {"tag": tag.lower(), "classes": classes,
                "id": d.get("id") or "", "children": []}

    def handle_starttag(self, tag, attrs):
        node = self._node(tag, attrs)
        (self._stack[-1]["children"] if self._stack else self.roots).append(node)
        if tag.lower() not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = self._node(tag, attrs)
        (self._stack[-1]["children"] if self._stack else self.roots).append(node)

    def handle_endtag(self, tag):
        # Tolerant close: pop to the nearest matching open tag (the mockup is
        # hand-authored HTML, not XML).
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag.lower():
                del self._stack[i:]
                return


def parse_dom(text: str) -> list:
    """Parse markup into a list of root nodes."""
    b = _TreeBuilder()
    b.feed(text)
    b.close()
    return b.roots


def find_by_id(nodes: list, node_id: str):
    """Depth-first search for the node carrying ``id=node_id``."""
    stack = list(nodes)
    while stack:
        n = stack.pop(0)
        if n["id"] == node_id:
            return n
        stack[0:0] = n["children"]
    return None


def signature(node: dict) -> tuple:
    return (node["tag"], node["classes"])


# ═════════════════════════════════════════════════════════════════════════════
# The spec: drawn signatures + drawn edges from the signed sections
# ═════════════════════════════════════════════════════════════════════════════

def _collect(node, sigs: set, edges: set):
    s = signature(node)
    sigs.add(s)
    for c in node["children"]:
        edges.add((s, signature(c)))
        _collect(c, sigs, edges)


def spec_from_sections(mockup_text: str, section_ids) -> dict:
    """Compile the named signed sections into ``{"sigs", "edges"}``."""
    dom = parse_dom(mockup_text)
    sigs: set = set()
    edges: set = set()
    for sid in section_ids:
        section = find_by_id(dom, sid)
        if section is None:
            raise MockupPinError(
                "C9 pin: signed mockup carries no section id=%r — the spec "
                "the diff pins to does not exist in the signed file" % sid)
        _collect(section, sigs, edges)
    return {"sigs": sigs, "edges": edges}


def slice_spec(mockup_text: str | None = None, root=None) -> dict:
    """The W6 slice's spec: §m1 + §amendments of the SIGNED mockup (the
    hash-verified load runs unless the caller already holds verified text)."""
    text = mockup_text if mockup_text is not None else load_signed_mockup(root)
    return spec_from_sections(text, (SECTION_M1, SECTION_AMENDMENTS))


# ═════════════════════════════════════════════════════════════════════════════
# The diff: every rendered element/nesting must be drawn
# ═════════════════════════════════════════════════════════════════════════════

#: VARIANT LAW — the signed amendment states draw honest-empty VARIANTS of
#: locked M1 elements as ``base-classes + marker`` (goalbar→goalbar unread,
#: livestatus→livestatus idle, eta→eta nohist, runcard→runcard warm,
#: skillch→skillch nosk, yield→yield miss). A variant may stand wherever its
#: base element is drawn — the gate record's own words: "every state is the
#: honest-empty face of an already-locked element". The variant itself must
#: still be a DRAWN signature; an invented class never passes.
def _covers(base_sig: tuple, var_sig: tuple) -> bool:
    return (base_sig[0] == var_sig[0]
            and set(base_sig[1]) <= set(var_sig[1]))


#: AG COMPOSITION SEAMS — the amendment section draws its fragments inside
#: ``div.astate > div.abody`` demo wrappers, so the ONE nesting it cannot
#: draw is the fragment sitting in the live M1 frame. AG-DEGRADED-RAIL is
#: the drawn face of the ENTIRE dock interior on a fresh deploy (degraded
#: banner + greyed step rows replace progress/goalbar/chamber), so exactly
#: those two fragment roots may sit under the dock. Code-owned and closed —
#: any other undrawn nesting is a deviation.
COMPOSITION_SEAMS = {
    (("div", ("dock",)), ("div", ("degrail",))),
    (("div", ("dock",)), ("div", ("fstep",))),
}


def _sig_str(sig: tuple) -> str:
    return "<%s class=%r>" % (sig[0], " ".join(sig[1]))


def _sig_allowed(sig: tuple, spec: dict) -> bool:
    return sig in spec["sigs"]


def _edge_allowed(p_sig: tuple, c_sig: tuple, spec: dict) -> bool:
    if (p_sig, c_sig) in spec["edges"]:
        return True
    if (p_sig, c_sig) in COMPOSITION_SEAMS:
        return True
    # Variant law: a drawn edge (P, C) admits (P', C') when P'/C' are drawn
    # variants of P/C (same tag, superset classes).
    for (dp, dc) in spec["edges"]:
        if _covers(dp, p_sig) and _covers(dc, c_sig):
            return True
    return False


def _diff_node(node, spec, problems, path):
    sig = signature(node)
    here = path + "/" + _sig_str(sig)
    if not _sig_allowed(sig, spec):
        problems.append(
            "invented element (not drawn in the signed mockup): %s" % here)
    for c in node["children"]:
        csig = signature(c)
        if _sig_allowed(sig, spec) and _sig_allowed(csig, spec) \
                and not _edge_allowed(sig, csig, spec):
            problems.append(
                "invented nesting (edge not drawn in the signed mockup): "
                "%s > %s" % (here, _sig_str(csig)))
        _diff_node(c, spec, problems, here)


def diff_render(render_html: str, spec: dict) -> list:
    """Diff a painted render against the spec. Returns problem strings
    (empty == the render is mockup-verbatim for its rendered subset)."""
    problems: list = []
    for root in parse_dom(render_html):
        _diff_node(root, spec, problems, "")
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The REQUIRED direction: the slice must actually paint the drawn skeleton
# ═════════════════════════════════════════════════════════════════════════════

#: Base signatures the healthy slice MUST contain (an element whose signature
#: base-covers each row). Without this direction an empty dock diffs green.
REQUIRED_HEALTHY = (
    ("div", ("dock",)), ("div", ("dbar",)), ("div", ("seal",)),
    ("span", ("ti",)), ("span", ("pill",)), ("span", ("stamp",)),
    ("div", ("progress",)), ("div", ("bar",)), ("span", ("run-now",)),
    ("span", ("eta",)), ("div", ("goalbar",)), ("div", ("chamber",)),
    ("aside", ("flow",)), ("div", ("fstep",)), ("div", ("convo",)),
    ("div", ("msgs",)), ("div", ("msg", "steward")), ("div", ("who",)),
    ("div", ("livestatus",)), ("div", ("saybox",)), ("input", ()),
    ("button", ("btn", "gold")),
)

#: Base signatures the degraded (first-open-after-deploy) slice MUST contain:
#: the drawn AG-DEGRADED-RAIL face + the rebuild affordance button.
REQUIRED_DEGRADED = (
    ("div", ("dock",)), ("div", ("dbar",)), ("div", ("degrail",)),
    ("span", ("lab",)), ("button", ("btn", "gold")),
)


def _all_sigs(render_html: str) -> set:
    sigs: set = set()

    def walk(n):
        sigs.add(signature(n))
        for c in n["children"]:
            walk(c)

    for root in parse_dom(render_html):
        walk(root)
    return sigs


def missing_required(render_html: str, required) -> list:
    """The required base signatures the render does NOT contain."""
    have = _all_sigs(render_html)
    missing = []
    for base in required:
        if not any(_covers(base, s) for s in have):
            missing.append(_sig_str(base))
    return missing


def verify_slice_render(render_html: str, spec: dict,
                        mode: str = "healthy") -> list:
    """Both directions for one painted slice: no invented structure AND the
    drawn skeleton for ``mode`` (``healthy`` | ``degraded``) is present."""
    required = REQUIRED_DEGRADED if mode == "degraded" else REQUIRED_HEALTHY
    problems = diff_render(render_html, spec)
    for miss in missing_required(render_html, required):
        problems.append("required drawn element missing from the painted "
                        "%s slice: %s" % (mode, miss))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# W7: the verbatim mockup CSS (the style-isolated mount imports it as-is)
# ═════════════════════════════════════════════════════════════════════════════

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.DOTALL)


def mockup_style_text(mockup_text: str | None = None, root=None,
                      gate_record_path=None) -> str:
    """The signed mockup's ``<style>`` block, VERBATIM (steward-chamber W7).

    The full M1 mount imports the mockup CSS verbatim into its
    style-isolated container (shadow root); this is the ONLY sanctioned
    source — extracted from the hash-verified signed mockups.html, so the
    imported CSS can never drift from the C9 pin. Raises
    :class:`MockupPinError` when the pin fails or the signed file carries no
    style block (hard fail — never a silently different stylesheet).
    """
    text = mockup_text if mockup_text is not None \
        else load_signed_mockup(root, gate_record_path)
    m = _STYLE_RE.search(text)
    if not m:
        raise MockupPinError(
            "C9 pin: the signed mockup carries no <style> block — the "
            "verbatim CSS import has no signed source")
    return m.group(1)


# ═════════════════════════════════════════════════════════════════════════════
# W7: full-M1 mount verification — view-aware required skeleton
# ═════════════════════════════════════════════════════════════════════════════

#: The full-mount base skeleton (always painted by the healthy full M1
#: shell). REQUIRED_HEALTHY minus the rail-step row, which is view-
#: conditional below (an empty rail — e.g. every step still 'proposed',
#: R-PROPOSED-EXCLUDED — honestly paints no fstep).
_REQUIRED_FULL_BASE = tuple(sig for sig in REQUIRED_HEALTHY
                            if sig != ("div", ("fstep",)))

#: Feature-conditional drawn requirements for the FULL mount (W7): each rides
#: only when the view actually carries the state that draws it.
REQUIRED_RUNCARD = (("div", ("runcard",)), ("div", ("ttable",)))
REQUIRED_RUNCARD_LINKS = (("div", ("links",)), ("a", ()))
REQUIRED_DELIV = (("div", ("deliv",)),)
REQUIRED_FSTEP = (("div", ("fstep",)),)


def m1_required_for_view(view: dict) -> tuple:
    """The drawn base signatures the FULL M1 mount MUST paint for ``view``
    (the two-directional law: what the data says exists must be drawn)."""
    if view.get("degraded"):
        return REQUIRED_DEGRADED
    required = list(_REQUIRED_FULL_BASE)
    steps = view.get("steps") or []
    if steps:
        required.extend(REQUIRED_FSTEP)
    if view.get("live_run"):
        required.extend(REQUIRED_RUNCARD)
        slot = view.get("pulse_slot") or {}
        if slot.get("status_block"):
            # A captured ⏱ block draws the REAL runcard with its links row.
            required.extend(REQUIRED_RUNCARD_LINKS)
    if view.get("deliverable"):
        required.extend(REQUIRED_DELIV)
    return tuple(required)


def verify_m1_render(render_html: str, spec: dict, view: dict) -> list:
    """The W7 full-mount kill-gate check: no invented structure against the
    hash-pinned signed spec AND the view-conditional drawn skeleton present
    (an empty dock or a swallowed feature can never diff green)."""
    problems = diff_render(render_html, spec)
    for miss in missing_required(render_html, m1_required_for_view(view)):
        problems.append("required drawn element missing from the painted "
                        "full M1 mount: %s" % miss)
    return problems

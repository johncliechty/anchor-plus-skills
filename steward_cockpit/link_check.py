"""W3 of the night of 2026-10-10: links in a steward's reply open the right thing, or say why they cannot.

John (2026-10-08): "...giving me summaries with links that are broken ... happens pretty regularly". Nothing checked
the links a model wrote; only Anchor's own receipt line built links from the register. Now, at the end of every turn,
each link in the reply is classified by origin and route and checked against the disk:

- Links are found exactly as the page's renderer finds them (md.js splitLinks: balanced parentheses, spaces, the
  <...> form), so the checker and the page never disagree about what a link is.
- An EXTERNAL link is exempt. An Anchor link is a relative route, or an absolute URL whose host is one of Anchor's
  NAMED hosts (loopback, this machine's name, the names in ANCHOR_PUBLIC_HOSTS, and this machine's own tailnet name
  <host>.<tailnet>.ts.net) - never a look-alike. It is checked, then rewritten to its relative form.
- No link is ever recorded with a credential: token= (and the other sign-in parameters) are removed from every
  Anchor link before the reply is saved, and from the words of the report line.
- `/artifact/<pid>?path=<rel>`, `/artifact/<pid>/<rel>` and `/api/steward/deliverable-file?...` are resolved the way
  the serving routes resolve them: the registered project, a DISCOVERED effort (the cockpit's own discovery, never a
  `..`), containment, the private-home guard, presence, and - when the link carries a hash - the same bytes.
  `/report/...` links resolve through the report viewer's own lookup, which this checker does not second-guess: they
  are left unchecked.
- ONE same-turn correction, by Anchor, and only to the SAME product version: a link whose target path is exactly a
  registered item's path is rewritten to that item's own reading target (the route form, its effort and its hash
  binding); a link to an HTML/Markdown copy is rewritten to the registered PDF beside it ONLY when that PDF has the
  same folder and name and both are registered. Nothing else is ever substituted - an ambiguous or hash-changed link
  is left as written and named. A correction is itself checked before it is announced.
- What still fails is named: "not found" ONLY for a confirmed missing file in a known effort; "changed since it was
  registered" for other bytes; "unavailable now" for anything outside, private, or not a known project or effort.

Pure apart from reading the registry and the disk; never raises (a failure leaves the reply as it was).
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

NOT_FOUND = "not found"
CHANGED = "changed since it was registered"
UNAVAILABLE = "unavailable now"
_SECRET_KEYS = {"token", "access_token", "auth", "key", "anchor_token"}
_BARE = re.compile(r"(?<![(\[<`\w/])(https?://[^\s<>()`\"']{3,2000})")


# ---------------------------------------------------------------- finding links (the renderer's own rules)

def split_links(s):
    """[str | {"label", "target", "raw"}] - md.js splitLinks, line for line: a label without [ or ], a target with
    balanced ( ) (spaces allowed) or the <...> form taken whole."""
    out, i = [], 0
    n = len(s)
    while i < n:
        j = s.find("[", i)
        if j < 0:
            break
        k = s.find("](", j)
        if k < 0:
            break
        if "[" in s[j + 1:k] or "]" in s[j + 1:k]:
            out.append(s[i:j + 1]); i = j + 1; continue
        depth, m = 1, k + 2
        rest = s[k + 2:]
        lead = len(rest) - len(rest.lstrip())
        if rest.lstrip().startswith("<"):
            gt = s.find(">", k + 2 + lead)
            if gt >= 0 and gt + 1 < n and s[gt + 1] == ")":
                depth, m = 0, gt + 2
        while m < n and depth:
            if s[m] == "(":
                depth += 1
            elif s[m] == ")":
                depth -= 1
            m += 1
        target = s[k + 2:m - 1].strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if depth:
            out.append(s[i:k + 2]); i = k + 2; continue
        if j > i:
            out.append(s[i:j])
        out.append({"label": s[j + 1:k], "target": target, "raw": s[j:m]})
        i = m
    if i < n:
        out.append(s[i:])
    return out


# ---------------------------------------------------------------- classifying

def anchor_hosts():
    hosts = {"localhost", "127.0.0.1", "::1"}
    try:
        hosts.add(socket.gethostname().lower())
    except OSError:
        pass
    hosts |= {h.strip().lower() for h in os.environ.get("ANCHOR_PUBLIC_HOSTS", "").split(",") if h.strip()}
    return hosts


def _is_anchor_host(host, hosts):
    # review r2: the EXACT names only - a tailnet name counts when it is listed whole in ANCHOR_PUBLIC_HOSTS
    return (host or "").lower().strip("[]") in hosts


def classify(url, hosts=None):
    """("external" | "anchor" | "other", the Anchor path+query or None). Relative routes are Anchor's own."""
    u = str(url or "").strip()
    if not u or u.startswith("#"):
        return "other", None
    parts = urlsplit(u)
    if parts.scheme in ("http", "https"):
        if parts.username or parts.password:
            return "external", None
        try:
            port = parts.port
        except ValueError:
            return "other", None
        if _is_anchor_host(parts.hostname, hosts or anchor_hosts()) and port in (None, 80, 443, 8777):
            return "anchor", urlunsplit(("", "", parts.path, parts.query, parts.fragment))
        return "external", None
    if parts.scheme:
        return "external", None
    if u.startswith("/"):
        return "anchor", u
    return "other", None


def scrub(route):
    """A route with every sign-in parameter removed (the token is never recorded)."""
    parts = urlsplit(route)
    if not parts.query:
        return route
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(k.lower() in _SECRET_KEYS for k, _v in pairs):
        return route                                  # nothing to remove: the link stays exactly as written
    q = [(k, v) for k, v in pairs if k.lower() not in _SECRET_KEYS]
    return urlunsplit(("", "", parts.path, urlencode(q, safe="/"), parts.fragment))


# ---------------------------------------------------------------- resolving (the serving routes' rules)

def _project_folder(pid):
    try:
        import rnd_registry
        rec = rnd_registry.get_project(pid)
        return (rec or {}).get("folder_path") or None
    except Exception:
        return None


def _effort_dir(folder, rel):
    """The effort folder for a project + dir the way the cockpit routes find it (its own discovery), or None."""
    rel = str(rel or "").strip().replace("\\", "/").strip("/")
    if ".." in rel.split("/"):
        return None
    try:
        from steward_cockpit.steward_campaign import discover_efforts
        names = {e["rel"] for e in discover_efforts(folder)}
    except Exception:
        return None
    return os.path.join(folder, rel) if rel in names else None


def _inside(root, rel):
    """(state, Path|None): 'ok' with the file, NOT_FOUND for a contained file that is missing, UNAVAILABLE otherwise."""
    try:
        base = Path(root).resolve()
        fp = (base / rel).resolve()             # rel arrives decoded once (review r2: never twice)
    except (OSError, ValueError):
        return UNAVAILABLE, None
    if fp != base and base not in fp.parents:
        return UNAVAILABLE, None
    if any(part in (".git", ".anchor") for part in fp.relative_to(base).parts):
        return UNAVAILABLE, None
    try:
        from provider_native import private_account_path
        if private_account_path(str(fp)):
            return UNAVAILABLE, None
    except ImportError:
        pass
    if fp.is_file():
        return "ok", fp
    return (NOT_FOUND if not fp.exists() else UNAVAILABLE), None


def check_route(route):
    """The verdict for one Anchor route: "ok", "unchecked", or one of the three failure words."""
    parts = urlsplit(route)
    path, qs = parts.path, _first(parts.query)
    m = re.match(r"^/artifact/([^/?#]+)(?:/(.+))?$", path)
    if m:
        folder = _project_folder(unquote(m.group(1)))
        rel = unquote(m.group(2)) if m.group(2) else qs.get("path", "")
        if not folder or not rel:
            return UNAVAILABLE
        return _inside(folder, rel)[0]
    if path == "/api/steward/deliverable-file":
        folder = _project_folder(qs.get("pid", ""))
        effort = _effort_dir(folder, qs.get("dir", "")) if folder else None
        if not effort:
            return UNAVAILABLE
        state, fp = _inside(effort, qs.get("path", ""))
        if state != "ok":
            return state
        try:
            if fp.stat().st_size > 50 * 1024 * 1024:       # the route answers 413 above this (final review 10-10)
                return UNAVAILABLE
        except OSError:
            return UNAVAILABLE
        if qs.get("hash"):
            try:
                if hashlib.sha256(fp.read_bytes()).hexdigest() != qs["hash"]:
                    return CHANGED
            except OSError:
                return UNAVAILABLE
        return "ok"
    m = re.match(r"^/report/([^/?#]+)/([^/?#]+)(?:/([^/?#]+))?/?$", path)
    if m:
        folder = _project_folder(unquote(m.group(1)))
        if not folder:
            return UNAVAILABLE
        try:
            import report_viewer
            got = report_viewer.resolve_artifact(folder, unquote(m.group(1)), unquote(m.group(2)),
                                                 unquote(m.group(3)) if m.group(3) else None)
        except Exception:
            return UNAVAILABLE
        return NOT_FOUND if got.get("mode") == "missing" else "ok"
    return "unchecked"                    # /project, /foundry ...: their own routes decide


def _effort_relative(route, cdir):
    """(path relative to THIS effort, exact) or (None, False). ``exact`` is False for an /artifact link that left out
    the effort's folder (the project-relative path read as effort-relative) - good enough to repair a BROKEN link to
    the very same registered path, never enough to re-point a working one."""
    parts = urlsplit(route)
    qs = _first(parts.query)
    try:
        import deliverables_register as dr
        pid, erel = dr.project_and_rel(cdir)
    except Exception:
        return None, False
    m = re.match(r"^/artifact/([^/?#]+)(?:/(.+))?$", parts.path)
    if m:
        if unquote(m.group(1)) != pid:
            return None, False
        rel = (unquote(m.group(2)) if m.group(2) else qs.get("path", "")).replace("\\", "/").lstrip("/")
        prefix = (str(erel or "").replace("\\", "/").strip("/") + "/") if erel else ""
        if not prefix:
            return rel, True
        if rel.lower().startswith(prefix.lower()):
            return rel[len(prefix):], True
        return rel, False
    if parts.path == "/api/steward/deliverable-file":
        if qs.get("pid") != pid:
            return None, False
        exact = str(qs.get("dir") or "").strip("/") == str(erel or "").strip("/")
        return qs.get("path", "").replace("\\", "/").lstrip("/"), exact
    return None, False


def _first(query):
    """The query's FIRST value per key - the serving routes' own semantics (review r2)."""
    out = {}
    for k, v in parse_qsl(query, keep_blank_values=True):
        out.setdefault(k, v)
    return out


def _registered(cdir):
    """{lowercase in-effort path: (reading URL, product key)} for the effort's registered path items."""
    try:
        from steward_cockpit import steward_campaign as campaign
        import deliverables_register as dr
        data = campaign.read_deliverables(cdir)
        items = [i for i in (data.get("items") or []) if isinstance(i, dict) and i.get("path")]
        pid, rel = dr.project_and_rel(cdir)
        if not pid:
            return {}
        registered = {str(i["path"]).replace("\\", "/").lower() for i in items}
        steps = (campaign.read_map(cdir) or {}).get("steps")
        out = {}
        for it in items:
            t = dr.reading_target(it, pid=pid, effort_rel=rel, effort_dir=cdir, registered=registered)
            if t.get("read"):
                out.setdefault(str(it["path"]).replace("\\", "/").lower(), (t["read"], campaign._product_key(it, steps)))
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------- the reply

def check_reply(text, cdir, hosts=None):
    """(corrected text, report). report: [{"label", "verdict", "fixed_to"}] for every Anchor link corrected or still
    failing; working and external links are not reported. Never raises."""
    try:
        return _check_reply(text, cdir, hosts or anchor_hosts())
    except Exception:
        return text, []


def _file_url_to_anchor(url, cdir):
    """Convert a file:/// URL inside the effort (or project) into its canonical /api/steward/deliverable-file route."""
    u = str(url or "").strip()
    if not u.lower().startswith("file:///"):
        return None
    try:
        parts = urlsplit(u)
        raw_path = unquote(parts.path or "")
        if re.match(r"^/[A-Za-z]:/", raw_path):
            raw_path = raw_path[1:]
        fp = Path(raw_path).resolve()
        root = Path(cdir).resolve()
        if fp != root and root in fp.parents and fp.is_file():
            rel = fp.relative_to(root).as_posix()
            import deliverables_register as dr
            pid, erel = dr.project_and_rel(cdir)
            if pid:
                q = [("pid", pid), ("dir", erel or ""), ("path", rel)]
                if rel.lower().endswith((".md", ".markdown", ".txt")):
                    q.append(("render", "1"))
                elif rel.lower().endswith((".docx", ".pptx", ".xlsx")):
                    q.append(("view", "1"))
                return "/api/steward/deliverable-file?" + urlencode(q, safe="/")
    except Exception:
        return None
    return None


def _check_reply(text, cdir, hosts):
    if not text or ("](" not in text and "http" not in text):
        return text, []
    reg = None
    report = []

    def fix(label, url):
        nonlocal reg
        file_route = _file_url_to_anchor(url, cdir)
        if file_route:
            return file_route
        kind, route = classify(url, hosts)
        if kind != "anchor":
            # final review 10-10: a malformed Anchor URL (a bad port) still never records a credential
            try:
                host = (urlsplit(str(url)).hostname or "").lower()
            except ValueError:
                host = ""
            if host in hosts:
                red = _redact_raw(str(url))
                return red if red != str(url) else None
            return None
        clean = scrub(route)
        verdict = check_route(clean)
        rel, exact = _effort_relative(clean, cdir)
        if reg is None:
            reg = _registered(cdir)
        candidate, why = None, None
        if rel is not None:
            low = rel.lower()
            stem, ext = os.path.splitext(low)
            if exact and verdict in (NOT_FOUND, UNAVAILABLE) and low in reg:
                candidate, why = reg[low][0], verdict          # this effort's same registered path, its own route
            elif (exact and verdict == "ok" and ext in (".html", ".htm", ".md") and low in reg and (stem + ".pdf") in reg
                  and reg[low][1] == reg[stem + ".pdf"][1]):
                # same folder, same name, both registered AS ONE PRODUCT (the register's own product grouping)
                candidate, why = reg[stem + ".pdf"][0], "the registered PDF"
        if candidate and scrub(candidate) != clean:
            if check_route(scrub(candidate)) in ("ok", "unchecked"):
                report.append({"label": _plain(label), "verdict": why, "fixed_to": scrub(candidate)})
                return scrub(candidate)
        if verdict not in ("ok", "unchecked"):
            report.append({"label": _plain(label), "verdict": verdict, "fixed_to": None})
            return clean if clean != url else None
        return clean if clean != url else None

    def safe_fix(label, url):
        try:
            return fix(label, url)
        except Exception:
            return None

    parts = []
    for p in split_links(text):
        if isinstance(p, dict):
            new = safe_fix(p["label"], p["target"])
            label = _plain_label(p["label"])
            if new or label != p["label"]:
                parts.append("[%s](%s)" % (label, _md_target(new or p["target"])))
            else:
                parts.append(p["raw"])
        else:
            def bare(m):
                url = m.group(1).rstrip(".,;:")
                tail = m.group(1)[len(url):]
                new = safe_fix(url, url)
                return (new + tail) if new else m.group(0)
            parts.append(_BARE.sub(bare, p))
    return "".join(parts), report


def _md_target(url):
    return "<%s>" % url if (" " in url or ")" in url or "(" in url) else url


def report_line(report):
    """One Anchor line for the dialogue, or "" when there is nothing to say."""
    if not report:
        return ""
    bits = []
    for r in report:
        if r["fixed_to"]:
            bits.append("[%s](%s) now opens the registered copy%s" % (
                r["label"], _md_target(r["fixed_to"]),
                "" if r["verdict"] == "the registered PDF" else " (the link was %s)" % r["verdict"]))
        else:
            bits.append("`%s`: %s" % (r["label"][:120], r["verdict"]))
    return "**Anchor** · links: " + " · ".join(bits)


_SECRET_IN_TEXT = re.compile(r"([?&](?:token|access_token|auth|key|anchor_token)=)[^&\s)\]]*", re.I)


def _redact_raw(url):
    """The URL with every sign-in parameter dropped, judged by its DECODED name, without parsing the rest (a bad port
    or host must not stop the redaction)."""
    head, sep, rest = url.partition("?")
    if not sep:
        return url
    query, hsep, frag = rest.partition("#")
    kept = [p for p in query.split("&") if unquote(p.split("=", 1)[0]).lower() not in _SECRET_KEYS]
    return head + ("?" + "&".join(kept) if kept else "") + (hsep + frag if hsep else "")


def _plain_label(s):
    """A link's own label with any credential value removed (review r2: a URL used as its own label)."""
    return _SECRET_IN_TEXT.sub(r"\1", str(s or ""))


def _plain(s):
    """A label for the report line, with any credential-looking query removed."""
    s = re.sub(r"([?&](?:token|access_token|auth|key|anchor_token)=)[^&\s)]*", r"\1", str(s or ""), flags=re.I)
    return s.replace("[", "(").replace("]", ")").replace("`", "'")

"""Content-independent checks for Foundry's foundry-skill-display/v1 handoff.

No model calls or writes. Skill-specific coverage belongs in the calling gate.
Both frozen bytes and their real origins must still match; a self-consistent
snapshot alone cannot prove that a live source anchor is current.
"""
import hashlib
import json
from pathlib import Path
import re


UNKNOWN_USE = dict(status="unknown", count=None, run_ids=[], method=None)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def contained(root, value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
        return None
    if value.startswith("/") or ".." in value.split("/"):
        return None
    path = (root / value).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def validate(data, root, repo):
    root, repo = Path(root).resolve(), Path(repo).resolve()
    errors = []

    def check(ok, message):
        if not ok:
            errors.append(message)

    def index(rows, label):
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get("id") for r in rows):
            errors.append("invalid " + label + " array")
            return {}
        result = {r["id"]: r for r in rows}
        check(len(result) == len(rows), "duplicate " + label + " ids")
        return result

    if not isinstance(data, dict):
        return ["display must be an object"]
    check(data.get("schema") == "foundry-skill-display/v1", "unsupported adapter schema")
    sources = index(data.get("sources"), "source")
    anchors = index(data.get("anchors"), "anchor")
    resources = index(data.get("resources"), "resource")
    knowledge, process = data.get("knowledge", {}), data.get("process", {})
    if not isinstance(knowledge, dict) or not isinstance(process, dict):
        return errors + ["invalid maps"]
    nodes = index(knowledge.get("nodes"), "node")
    steps = index(process.get("steps"), "step")
    lines = {}
    for sid, source in sources.items():
        path = contained(root, source.get("snapshot"))
        check(path is not None and path.is_file(), "missing source snapshot " + sid)
        if path and path.is_file():
            raw = path.read_bytes()
            check(digest(raw) == source.get("sha256"), "stale snapshot " + sid)
            lines[sid] = raw.decode("utf-8-sig").splitlines()
        origin = source.get("origin", "")
        # Live adapter accepts repo-relative paths, including spaces, and its
        # configured external source roots. The caller supplies these originals.
        original = Path(origin) if isinstance(origin, str) else Path("")
        if not original.is_absolute():
            original = repo / original
        check(bool(origin) and original.is_file(), "missing real source " + sid)
        if origin and original.is_file():
            check(digest(original.read_bytes()) == source.get("sha256"), "stale real source " + sid)
    for aid, a in anchors.items():
        rows = lines.get(a.get("source_id"), [])
        start, end = a.get("start"), a.get("end")
        valid = type(start) is int and type(end) is int and 1 <= start <= end <= len(rows)
        check(valid, "bad anchor range " + aid)
        excerpt = "\n".join(rows[start - 1:end]) if valid else ""
        check(bool(excerpt) and excerpt == a.get("quote"), "ungrounded quote " + aid)
        check(digest(excerpt.encode("utf-8")) == a.get("sha256"), "stale anchor " + aid)
        if a.get("symbol"):
            check(bool(re.search(r"\bfunction\s+" + re.escape(a["symbol"]) + r"\b", excerpt)), "missing callable " + aid)
    for rid, resource in resources.items():
        path = contained(root, resource.get("target"))
        check(path is not None and path.is_file(), "broken real-resource target " + rid)
        check(resource.get("anchor_id") in anchors, "resource without source " + rid)
        if path and path.is_file():
            body = path.read_text(encoding="utf-8")
            check(f'data-resource-id="{rid}"' in body and
                  f'data-anchor-id="{resource.get("anchor_id")}"' in body, "resource identity mismatch " + rid)
        usage = resource.get("usage")
        if usage != UNKNOWN_USE:
            evidence = resource.get("usage_evidence", [])
            run_ids = set()
            for item in evidence:
                path = contained(root, item.get("path")) if isinstance(item, dict) else None
                if path and path.is_file() and "journal" in path.parts:
                    record = json.loads(path.read_text(encoding="utf-8-sig"))
                    if rid in record.get("resource_ids", []) and record.get("run_id"):
                        run_ids.add(record["run_id"])
            check(bool(run_ids) and usage == dict(status="recorded", count=len(run_ids),
                  run_ids=sorted(run_ids), method="unique-explicit-resource-runs"), "unsupported frequency " + rid)
    check(knowledge.get("learned") is False and knowledge.get("geometry") == "seeded-declared-tree"
          and knowledge.get("layout_source") == "parent_id" and knowledge.get("run_evidence") == [],
          "unsupported learned geometry")
    check(sum(n.get("parent_id") is None for n in nodes.values()) == 1, "seed needs one root")
    for nid, node in nodes.items():
        check(not {"embedding", "weight", "frequency", "use_count", "learned_position", "x", "y"} & set(node),
              "unsupported geometry or measured node weight " + nid)
        check(node.get("resource_id") in resources, "knowledge resource missing " + nid)
        check(all(s in steps for s in node.get("process_ids", [])), "knowledge process missing " + nid)
        parent = node.get("parent_id")
        check(parent is None or parent in nodes, "missing parent " + nid)
        check(node.get("ring") == (0 if parent is None else nodes.get(parent, {}).get("ring", -2) + 1), "bad depth " + nid)
        seen = {nid}
        while parent in nodes:
            if parent in seen:
                errors.append("knowledge cycle " + nid)
                break
            seen.add(parent)
            parent = nodes[parent].get("parent_id")
    check({n.get("resource_id") for n in nodes.values()} == set(resources), "Library missing from map")
    for sid, step in steps.items():
        aa = step.get("anchors", [])
        check(bool(aa) and all(a in anchors for a in aa), "ungrounded process " + sid)
        check(all(r in resources for r in step.get("resource_ids", [])), "missing process resource " + sid)
        if step.get("code_status") == "anchored":
            # Anchor uses the FIRST anchor as its Code link, the LAST for Instructions.
            check(bool(aa) and sources.get(anchors.get(aa[0], {}).get("source_id"), {}).get("kind") == "code",
                  "program without first code anchor " + sid)
    edges = process.get("edges", [])
    if not isinstance(edges, list):
        return errors + ["invalid edge array"]
    pairs = set()
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("invalid edge")
            continue
        a, b = edge.get("source"), edge.get("target")
        check(a in steps and b in steps and edge.get("anchor_id") in anchors and bool(edge.get("label")), "ungrounded transition")
        pairs.add((a, b))
    reached = {process.get("entry")}
    while True:
        more = reached | {b for a, b in pairs if a in reached}
        if more == reached:
            break
        reached = more
    check(reached == set(steps), "unreachable process branch")
    terminals = set(process.get("terminals", []))
    check(bool(terminals) and terminals <= set(steps), "invalid terminals")
    can_stop = set(terminals)
    while True:
        more = can_stop | {a for a, b in pairs if b in can_stop}
        if more == can_stop:
            break
        can_stop = more
    check(set(steps) <= can_stop, "process without stopping route")
    for difference in process.get("disagreements", []):
        aa = difference.get("anchors", [])
        check(len(aa) >= 2 and all(a in anchors for a in aa), "ungrounded disagreement")
    check(data.get("lifecycle") == dict(state="for-review", accepted=False, closed=False), "invented product acceptance")
    return errors

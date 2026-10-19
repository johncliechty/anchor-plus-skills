"""The steward's hand-off tool (steward-responsiveness R3, 2026-10-04): start, stop or list a CODE JOB for the steward
conversation whose folder is the current directory. A code job is a coder on the best model at full effort in its own
worktree of --repo; it lands its work when clean and wakes this steward with the result.

  python C:/dev/Anchor/tools/steward_code_job.py start --repo C:/dev/Anchor --brief-file brief.md --check "<cmd>"
  python C:/dev/Anchor/tools/steward_code_job.py start --worker foreman --repo <repo> --brief-file brief.md --check "<test command>" [--plan-file PLAN.md] [--profile slim|standard]
  python C:/dev/Anchor/tools/steward_code_job.py stop [--job <id>]
  python C:/dev/Anchor/tools/steward_code_job.py list
"""
import argparse, json, os, re, sys, urllib.request
from pathlib import Path

ANCHOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ANCHOR))


def project_for(cwd):
    import rnd_registry
    here = Path(cwd).resolve()
    best = None
    for p in rnd_registry.list_projects(include_archived=True, include_future=True, include_retired=False):
        fp = p.get("folder_path")
        if not fp:
            continue
        root = Path(fp).resolve()
        if here == root or root in here.parents:
            if best is None or len(str(root)) > len(str(best[1])):
                best = (p.get("id"), root)
    if best is None:
        raise SystemExit("this folder is not inside a registered Anchor project: %s" % here)
    rel = "" if here == best[1] else str(here.relative_to(best[1])).replace("\\", "/")
    return best[0], rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "list", "inspect", "recover", "collect"))
    ap.add_argument("--repo"); ap.add_argument("--brief-file"); ap.add_argument("--brief")
    ap.add_argument("--check", default="", help="required for start unless --check-argv is supplied: existing verification command")
    ap.add_argument("--job")
    ap.add_argument("--handoff-id", help="collect only this exact result revision; omit to collect current")
    ap.add_argument("--work-dir", default=None, help="repository-relative artifact scope; omitted derives from --repo, '.' is root-wide")
    ap.add_argument("--check-argv", default="", help="the check as a JSON argument list (no shell)")
    ap.add_argument("--coder", default="", help="this job's coder family (claude|chatgpt|grok|gemini); default: the Coder seat")
    ap.add_argument("--reviewer", default="", help="start/recover: reviewer family override (claude|chatgpt|grok|gemini); default: the Reviewer seat")
    ap.add_argument("--skill", default="", help="the skill this job runs (e.g. Chekhov), so the status names it")
    ap.add_argument("--output", action="append", default=[],
                    help="a file this job will PRODUCE (e.g. a render), named up front so it may land; repeatable")
    ap.add_argument("--worker", default="coder", choices=("coder", "foreman"),
                    help="foreman: Foreman builds it in the job's worktree, gated by --check (a test command)")
    ap.add_argument("--plan-file", default="", help="Foreman: the plan John approved (## Wave N sections)")
    ap.add_argument("--profile", default="slim", choices=("slim", "standard"), help="Foreman: slim unless John said standard")
    ap.add_argument("--outside-ok", action="append", default=[],
                    help="recover: a repository file you know changed outside the job for its own reasons (e.g. your "
                         "AGENTS.md); pinned to its bytes now; repeatable")
    ap.add_argument("--size", default="standard", choices=("small", "standard"),
                    help="start: small = one bounded deliverable, at most 5 files, no new design, reversible, not "
                         "Anchor's code - it runs one model tier down (John's tiers.json)")
    ap.add_argument("--escalates", default="", help="start: the small job this one redoes at standard")
    ap.add_argument("--port", default=os.environ.get("ANCHOR_PORT", "8777"))
    a = ap.parse_args()
    pid, rel = project_for(os.getcwd())
    body = {"dir": rel, "action": a.action}
    if a.action == "start":
        brief = a.brief or (Path(a.brief_file).read_text(encoding="utf-8") if a.brief_file else "")
        if not (a.repo and brief.strip()):
            raise SystemExit("start needs --repo and --brief-file (or --brief)")
        doc_exts = {".md", ".docx", ".pdf", ".html", ".htm"}
        stem_re = re.compile(r"(?:_source|-source|_redline|-redline|_track[-_]?changes|_tracked|_clean|_reading)$", re.I)
        doc_stems = {
            (Path(o).parent.as_posix().lower(), stem_re.sub("", Path(o).stem).lower())
            for o in (a.output or [])
            if Path(o).suffix.lower() in doc_exts and stem_re.sub("", Path(o).stem)
        }
        if len(doc_stems) > 3:
            raise SystemExit(
                f"start refused: {len(doc_stems)} distinct document stems declared in --output (max 3 per job). "
                "Split multi-chapter or multi-deliverable bundles into separate focused jobs (1-2 deliverable stems per job)."
            )
        bf_abs = str(Path(a.brief_file).resolve()).replace("\\", "/") if a.brief_file else ""
        if a.brief_file and not a.brief and len(brief) > 7800:
            head = brief[:3600].rstrip()
            tail = brief[-3200:].lstrip()
            brief = (
                f"FULL BRIEF FILE (also copied to .anchor/full_brief.md in your worktree; read first for complete specifications): {bf_abs}\n\n"
                f"--- BRIEF OPENING ---\n{head}\n\n"
                f"[... {len(brief) - len(head) - len(tail)} characters in {bf_abs} / .anchor/full_brief.md ...]\n\n"
                f"--- BRIEF CLOSING & ACCEPTANCE REQUIREMENTS ---\n{tail}"
            )
        check = json.loads(a.check_argv) if a.check_argv else a.check       # a list runs with no shell at all
        body.update(repo=str(Path(a.repo).resolve()), brief=brief, check=check, coder=a.coder, actor="the steward", skill=a.skill,
                    outputs=a.output, worker=a.worker, profile=a.profile, work_dir=a.work_dir, size=a.size,
                    escalates=a.escalates, brief_file=bf_abs,
                    plan=Path(a.plan_file).read_text(encoding="utf-8") if a.plan_file else "")
        if a.reviewer:
            body["reviewer"] = a.reviewer
    if a.action == "stop":
        body["actor"] = "the steward"
    if a.action in ("inspect", "recover", "collect") and not a.job:
        raise SystemExit(a.action + " needs --job; use list to find the original job")
    if a.action == "recover":
        body["actor"] = "the steward"
        if a.check_argv or a.check:
            body["check"] = json.loads(a.check_argv) if a.check_argv else a.check
        if a.output:
            body["outputs"] = a.output
        if a.outside_ok:
            body["outside_ok"] = a.outside_ok
        if a.reviewer:
            body["reviewer"] = a.reviewer
    if a.handoff_id:
        body["handoff_id"] = a.handoff_id
    if a.job:
        body["job"] = a.job
    req = urllib.request.Request("http://127.0.0.1:%s/api/steward/code_job?pid=%s" % (a.port, pid),
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + os.environ.get("ANCHOR_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace")); sys.exit(1)


if __name__ == "__main__":
    main()

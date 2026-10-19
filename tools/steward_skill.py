"""The fenced steward's way to run a Foundry skill (two-lane step 3, 2026-10-06): the steward's own edits and shell are
fenced to its effort folder, so the SERVER starts the skill in this folder, keeps its log, and wakes the steward with
the result. Only a skill's run script inside a skill root (C:/dev/trio, C:/dev/Skill Foundry/skills) is accepted.

  python C:/dev/Anchor/tools/steward_skill.py start --label "Gandalf read of the plan" -- node <skill run script> [args]
  python C:/dev/Anchor/tools/steward_skill.py stop [--job <id>]
  python C:/dev/Anchor/tools/steward_skill.py list
  python C:/dev/Anchor/tools/steward_skill.py inspect --job <id>     (its process evidence and observation; quiet is not failed)
  python C:/dev/Anchor/tools/steward_skill.py collect --job <id>     (its durable result; a skill job lands nothing in Git)
"""
import argparse, json, os, sys, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steward_code_job import project_for   # noqa: E402  (the same project lookup as the code-job tool)


def main():
    argv = sys.argv[1:]
    rest = []
    if "--" in argv:
        i = argv.index("--")
        argv, rest = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "list", "inspect", "collect"))
    ap.add_argument("--label", default=""); ap.add_argument("--job")
    ap.add_argument("--handoff-id", help="collect only this exact result revision; omit to collect current")
    ap.add_argument("--port", default=os.environ.get("ANCHOR_PORT", "8777"))
    a = ap.parse_args(argv)
    pid, rel = project_for(os.getcwd())
    body = {"dir": rel, "action": a.action}
    if a.action == "start":
        if len(rest) < 2:
            raise SystemExit('start needs: -- node|python <the skill\'s run script> [args]')
        body.update(argv=rest, label=a.label)
    if a.action in ("inspect", "collect") and not a.job:
        raise SystemExit("%s needs --job <id>" % a.action)
    if a.job:
        body["job"] = a.job
    if a.handoff_id:
        body["handoff_id"] = a.handoff_id
    req = urllib.request.Request("http://127.0.0.1:%s/api/steward/skill_job?pid=%s" % (a.port, pid),
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + os.environ.get("ANCHOR_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace")); sys.exit(1)


if __name__ == "__main__":
    main()

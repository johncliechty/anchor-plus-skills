"""A hermetic stand-in for tools/steward_review.mjs (the code-job review gate's adapter), used through the
ANCHOR_REVIEW_CMD seam. It answers exactly as the adapter does - one JSON line - with the REAL tree hash of --head, and
lets a test choose the verdict, the reviewer's family, a wrong tree, or a crash:
  FAKE_REVIEW_VERDICT=PASS|FAIL  FAKE_REVIEW_FAMILY=chatgpt  FAKE_REVIEW_TREE=<hash>  FAKE_REVIEW_MODE=crash
FAKE_REVIEW_LOG (a file) records each call's argv, one JSON line per call."""
import json
import os
import subprocess
import sys


def arg(name):
    i = sys.argv.index("--" + name) if ("--" + name) in sys.argv else -1
    return sys.argv[i + 1] if 0 <= i < len(sys.argv) - 1 else ""


if os.environ.get("FAKE_REVIEW_LOG"):
    with open(os.environ["FAKE_REVIEW_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_REVIEW_MODE") == "crash":
    print(json.dumps({"ok": False, "family": os.environ.get("FAKE_REVIEW_FAMILY") or None,
                      "error": os.environ.get("FAKE_REVIEW_ERROR", "the reviewer crashed")}))
    sys.exit(2)
if os.environ.get("FAKE_REVIEW_MODE") == "pass-with-major":
    tree = subprocess.run(["git", "-C", arg("repo"), "rev-parse", arg("head") + "^{tree}"],
                          capture_output=True, text=True).stdout.strip()
    print(json.dumps({"ok": True, "family": os.environ.get("FAKE_REVIEW_FAMILY", "chatgpt"), "model": "fake",
                      "tree_hash": tree, "verdict": "PASS", "elegance": "",
                      "findings": [{"severity": "MAJOR", "issue": "contradicts its own pass"}]}))
    sys.exit(0)
tree = subprocess.run(["git", "-C", arg("repo"), "rev-parse", arg("head") + "^{tree}"],
                      capture_output=True, text=True).stdout.strip()
verdict = os.environ.get("FAKE_REVIEW_VERDICT", "PASS")
print(json.dumps({"ok": True, "family": os.environ.get("FAKE_REVIEW_FAMILY", "chatgpt"), "model": "fake-reviewer",
                  "model_attested": False, "tree_hash": os.environ.get("FAKE_REVIEW_TREE") or tree,
                  "verdict": verdict,
                  "findings": [] if verdict == "PASS" else [{"severity": "MAJOR", "issue": "planted defect"}],
                  "elegance": ""}))

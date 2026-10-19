"""Read-only live evidence for the Cave health-banner cleanup diagnosis."""
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import paths


def main():
    origin = "http://127.0.0.1:8777"
    token = paths.expected_token()
    headers = {"Authorization": "Bearer " + token} if token else {}
    with urllib.request.urlopen(urllib.request.Request(
            origin + "/api/doctor/status", headers=headers), timeout=15) as response:
        status = json.load(response)
    with urllib.request.urlopen(urllib.request.Request(
            origin + "/high-seat", headers=headers), timeout=30) as response:
        html = response.read().decode("utf-8")
    from html.parser import HTMLParser

    class Banners(HTMLParser):
        def __init__(self):
            super().__init__()
            self.count = 0

        def handle_starttag(self, tag, attrs):
            if "healthbar" in dict(attrs).get("class", "").split():
                self.count += 1

    parser = Banners()
    parser.feed(html)
    result = {
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "doctor": {key: status.get(key) for key in
                   ("ok", "status", "last_run", "issues", "warnings")},
        "fresh_cave": {"route": "/high-seat", "healthbar_count": parser.count,
                       "authentication": "configured token header; server-response evidence only",
                       "login_page": "Anchor is locked" in html,
                       "bytes": len(html.encode("utf-8")),
                       "old_issue_message_present": "Health check found issues" in html},
        "client_limit": "A fresh HTTP response is not the existing client's DOM or screen.",
    }
    (Path(__file__).parent / "live-evidence.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

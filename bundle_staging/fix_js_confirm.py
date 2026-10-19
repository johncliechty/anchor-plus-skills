import sys
import re

with open("C:/dev/Anchor/static/project-window.js", "r", encoding="utf-8") as f:
    text = f.read()

target1 = r"async function killPanel\(sessionId\) \{(?:\r?\n)(.+?)if \(\!confirm\('Are you sure\? Kill the \"' \+ name \+ '\" session\? This terminates its process and removes its tile\.'\)\) return;"
replacement1 = r"""async function killPanel(sessionId, skipConfirm) {
\1if (!skipConfirm && !confirm('Are you sure? Kill the "' + name + '" session? This terminates its process and removes its tile.')) return;"""

if re.search(target1, text):
    text = re.sub(target1, replacement1, text, count=1)
    print("killPanel signature updated!")

target2 = r"killPanel\(sid\);"
replacement2 = r"killPanel(sid, true);"

if target2 in text:
    text = text.replace(target2, replacement2, 1)
    print("killPanel call updated!")

with open("C:/dev/Anchor/static/project-window.js", "w", encoding="utf-8") as f:
    f.write(text)

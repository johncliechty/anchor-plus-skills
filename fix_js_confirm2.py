import sys

with open("C:/dev/Anchor/static/project-window.js", "r", encoding="utf-8") as f:
    text = f.read()

target1 = "async function killPanel(sessionId) {\n    var s = MANAGED[sessionId];\n    var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;\n    if (!confirm('Are you sure? Kill the \"' + name + '\" session? This terminates its process and removes its tile.')) return;"
replacement1 = "async function killPanel(sessionId, skipConfirm) {\n    var s = MANAGED[sessionId];\n    var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;\n    if (!skipConfirm && !confirm('Are you sure? Kill the \"' + name + '\" session? This terminates its process and removes its tile.')) return;"

if target1 in text:
    text = text.replace(target1, replacement1)
    print("killPanel signature updated!")

target2 = "killPanel(sid);\n      };\n      chip.appendChild(kill);"
replacement2 = "killPanel(sid, true);\n      };\n      chip.appendChild(kill);"

if target2 in text:
    text = text.replace(target2, replacement2)
    print("killPanel call updated!")

with open("C:/dev/Anchor/static/project-window.js", "w", encoding="utf-8") as f:
    f.write(text)

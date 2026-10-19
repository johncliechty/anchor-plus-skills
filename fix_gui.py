import sys
import re

with open("C:/dev/Anchor/anchor_gui.py", "r", encoding="utf-8") as f:
    text = f.read()

target = r"(\"\+ New research</button>\"\s*\"<button class='btn primary neweffort' id='newPlanBuildBtn'\s*onclick=\\\"newEffort\('plan'\)\\\"\s*title='Start a new effort at the Plan stage \(then advance to Build\)'>\s*\+ New plan/build</button></div>\")"

replacement = r""""+ New research</button>"
        "<button class='btn primary neweffort' id='newPlanBuildBtn' "
        "onclick=\"newEffort('plan')\" "
        "title='Start a new effort at the Plan stage (then advance to Build)'>"
        "+ New plan/build</button>"
        "<button class='btn primary neweffort' id='newGeneralBtn' "
        "onclick=\"newEffort('general')\" "
        "title='Start a new general session'>"
        "+ New general</button></div>\""""

if re.search(target, text):
    text = re.sub(target, replacement, text, count=1)
    with open("C:/dev/Anchor/anchor_gui.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("GUI updated successfully!")
else:
    print("Target GUI not found!")

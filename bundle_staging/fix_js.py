import sys
import re

with open("C:/dev/Anchor/static/project-window.js", "r", encoding="utf-8") as f:
    text = f.read()

target = r"(chip\.appendChild\(lbl\);\s+if \(finished\) \{)"

replacement = r"""chip.appendChild(lbl);
    if (!finished) {
      var kill = document.createElement('span');
      kill.innerHTML = '&times;';
      kill.style.marginLeft = '6px';
      kill.style.cursor = 'pointer';
      kill.style.fontWeight = 'bold';
      kill.title = 'Retire session';
      kill.onclick = function (ev) {
        ev.stopPropagation();
        killPanel(sid);
      };
      chip.appendChild(kill);
    }
    if (finished) {"""

if re.search(target, text):
    text = re.sub(target, replacement, text, count=1)
    with open("C:/dev/Anchor/static/project-window.js", "w", encoding="utf-8") as f:
        f.write(text)
    print("JS updated successfully!")
else:
    print("Target JS not found!")

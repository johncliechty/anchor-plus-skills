import sys
import re

with open("C:/dev/Anchor/gandalf.py", "r", encoding="utf-8") as f:
    text = f.read()

target = r'"Then, as your FINAL message, print a one-paragraph executive summary of "\s*"the read, followed by a single final line in exactly this form:\n\s*"VERDICT: <one sentence overall assessment>"'
replacement = r'"Then, as your FINAL message, print your executive summary and verdict wrapped in exactly this format:\n          <EXEC_SUMMARY>\n          [One paragraph summary here]\n\n          VERDICT: <one sentence overall assessment>\n          </EXEC_SUMMARY>"'

if re.search(target, text):
    text = re.sub(target, replacement, text, count=1)
    with open("C:/dev/Anchor/gandalf.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Prompt replaced successfully!")
else:
    print("Prompt not found!")

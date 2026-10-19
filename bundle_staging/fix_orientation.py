
import sys
with open("C:/dev/Anchor/orientation.py", "r", encoding="utf-8") as f:
    text = f.read()

import re
target = r"Read the referenced documents where present, then print the \"\n\s+\"three-part orientation\. Take no other action\."
replacement = "Read the RESTART.md document if present to get oriented quickly. Do NOT read the full raw transcripts unless specifically needed to clarify an ambiguous point in the RESTART.md summary. Then print the three-part orientation. Take no other action."

if re.search(target, text):
    text = re.sub(target, replacement, text, count=1)
    with open("C:/dev/Anchor/orientation.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced successfully!")
else:
    print("Target not found!")


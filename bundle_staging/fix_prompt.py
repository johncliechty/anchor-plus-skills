import sys
import re

with open("C:/dev/Anchor/summarizer.py", "r", encoding="utf-8") as f:
    text = f.read()

target = r"def _project_seed_prompt\(seed: dict\) -> str:(?:\r?\n)(.+?)lines = \[(?:\r?\n)\s+\"State this project's OBJECTIVE in 1-2 sentences: what it is FOR \u2014 its \"(?:\r?\n)\s+\"task/purpose and the problem it solves\. Be specific and grounded only \"(?:\r?\n)\s+\"in the material below; do NOT pad with generic feature lists\. Output \"(?:\r?\n)\s+\"the statement as 1-2 lines \(one sentence per line\), nothing else\.\","

replacement = r"""def _project_seed_prompt(seed: dict) -> str:
\1lines = [
        "Write a clear, informative paragraph (3-5 sentences) summarizing what this project is, "
        "its main purpose, and its current state. Write it in simple, human-readable language. "
        "Make it highly informative and easy to understand at a glance. Be specific and grounded only "
        "in the material below; do NOT pad with generic feature lists. Output the statement as "
        "a few lines of plain text, nothing else.","""

if re.search(target, text, flags=re.DOTALL):
    text = re.sub(target, replacement, text, count=1, flags=re.DOTALL)
    print("Project prompt updated!")
    with open("C:/dev/Anchor/summarizer.py", "w", encoding="utf-8") as f:
        f.write(text)
else:
    print("Project prompt target not found!")

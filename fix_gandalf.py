import sys
import re

with open("C:/dev/Anchor/gandalf.py", "r", encoding="utf-8") as f:
    text = f.read()

# Update prompt to use EXEC_SUMMARY tags
target_prompt = "Then, as your FINAL message, print a one-paragraph executive summary of \"\n        \"the read, followed by a single final line in exactly this form:\n        \"VERDICT: <one sentence overall assessment>\""
replacement_prompt = "Then, as your FINAL message, print your executive summary and verdict wrapped in exactly this format:\n        <EXEC_SUMMARY>\n        [One paragraph summary here]\n        \n        VERDICT: <one sentence overall assessment>\n        </EXEC_SUMMARY>\""

if target_prompt in text:
    text = text.replace(target_prompt, replacement_prompt)
    print("Prompt updated!")
else:
    print("Prompt not found!")

# Update parser to extract from tags if present
target_parser = """def _parse_agentic_summary(text):
    \"\"\"Split the agent's final text into ``(verdict, summary)``: the verdict is
    the ``VERDICT:`` line (if present); the summary is the remaining prose.\"\"\"
    if not text:
        return "", ""
    verdict = ""
    keep = []"""

replacement_parser = """def _parse_agentic_summary(text):
    \"\"\"Split the agent's final text into ``(verdict, summary)``: the verdict is
    the ``VERDICT:`` line (if present); the summary is the remaining prose.\"\"\"
    if not text:
        return "", ""
    
    import re
    match = re.search(r"<EXEC_SUMMARY>(.*?)</EXEC_SUMMARY>", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
        
    verdict = ""
    keep = []"""

if target_parser in text:
    text = text.replace(target_parser, replacement_parser)
    print("Parser updated!")
else:
    print("Parser not found!")

with open("C:/dev/Anchor/gandalf.py", "w", encoding="utf-8") as f:
    f.write(text)

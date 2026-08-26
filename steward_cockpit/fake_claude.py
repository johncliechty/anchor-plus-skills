"""A scripted stand-in for the claude CLI, speaking the same stream-json
protocol. Lets the UI be exercised end-to-end with zero tokens and zero real
sessions. Replies echo intent: a greeting for the stand-up, a status table on
ticks, otherwise a short steward-flavored acknowledgement.
"""
import json
import sys
import time
import uuid

out = sys.stdout


def emit(obj):
    out.write(json.dumps(obj) + "\n")
    out.flush()


def delta(text):
    emit({"type": "stream_event",
          "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": text}}})


def stream(text, chunk=18):
    for i in range(0, len(text), chunk):
        delta(text[i:i + chunk])
        time.sleep(0.03)


def tool(name, detail):
    emit({"type": "assistant",
          "message": {"content": [{"type": "tool_use", "name": name,
                                   "input": {"description": detail}}]}})


def result(secs):
    emit({"type": "result", "subtype": "success",
          "total_cost_usd": 0.0042, "duration_ms": int(secs * 1000)})


emit({"type": "system", "subtype": "init",
      "session_id": f"fake-{uuid.uuid4()}", "model": "fake-steward"})

TABLE = (
    "| Effort | Doing | Status |\n"
    "|---|---|---|\n"
    "| block-1-quiz-1 | Homework I revision scope | waiting on you |\n"
    "| syllabus-2026 | rooms + TA names | waiting on you |\n\n"
    "Campaign footer: step 8 of 12 · nothing running · two things wait on you."
)

n = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    if msg.get("type") != "user":
        continue
    content = msg.get("message", {}).get("content", [])
    text = " ".join(b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text")
    n += 1
    t0 = time.time()
    low = text.lower()
    if "stand up" in low and n == 1:
        tool("Skill", "ecgberht")
        time.sleep(0.4)
        tool("Read", "ECGBERHT.md - the Face")
        tool("Read", "roadmap.json + strip.json + conversation log")
        time.sleep(0.4)
        stream(
            "Good to see you. The campaign is the BA 815 revamp - AI woven "
            "through, oral exams in place of quizzes. We're on Block 1 + Quiz 1: "
            "eight artifacts built and reviewed on your screen. Two things wait "
            "on you - the Homework I revision you flagged, and rooms + TA names "
            "for the syllabus. I'd take Homework I first; it's the only thing "
            "holding this step open. Want to scope it now?")
    elif "engine tick" in low:
        stream("Status, on the clock:\n\n" + TABLE)
    elif "simulate work" in low:
        time.sleep(40)  # a long silent turn, so the cadence ticker fires
        stream("Long step finished. (Fake steward - simulated 40s of work.)")
    elif "grasscatch" in low:
        tool("Edit", "strip.json - grasscatch append")
        stream("Caught it - parked on the Strip with a reason, not lost. "
               "Back to the step in hand.")
    else:
        stream("Heard. (Fake steward - the real engine would act here.) "
               "The map beside us stays live from the files on disk. "
               "Anything else before I carry on?")
    result(time.time() - t0)

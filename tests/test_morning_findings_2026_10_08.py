"""Morning findings after the install (2026-10-08, John): "Received." must show under his words, the working receipt
quotes his words (not the wake brief), the served-code notice speaks only to a steward that could have made the change,
and a background job that runs a skill is named by that skill and timed by its own history. Hermetic: fake engines and
a throwaway server on a free port (never :8777)."""
import json
import time

from playwright.sync_api import expect

from steward_cockpit import steward_campaign as sc
from steward_cockpit import steward_engine
from tests.test_steward_refinement_browser import campaign_server, cockpit
from tests.test_cockpit_selected_b import open_surface


# ---------- 1: "Received." comes after his own words ----------

def test_received_is_said_after_his_words_never_above_them(tmp_path, monkeypatch):
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    said = []
    monkeypatch.setattr(eng, "_emit", lambda ev: said.append(ev))
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    monkeypatch.setattr(eng, "_send_locked", lambda text, origin="human", **kw: True)
    eng.busy = False
    assert eng.say("please fix the calendar")["ok"]
    kinds = [(e.get("t"), e.get("text")) for e in said]
    assert kinds.index(("john", "please fix the calendar")) + 1 == kinds.index(("sys", "Received."))
    said.clear()
    eng.busy = True
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    eng.say("and the quiz")
    assert ("sys", "Received.") not in [(e.get("t"), e.get("text")) for e in said]   # the queued path has its own


def test_received_is_painted_under_his_message_in_the_cockpit(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    box = surface.locator("[data-say]")
    box.click()
    box.type("first message")
    box.press("Control+Enter")
    expect(box).to_have_value("", timeout=5000)
    # the fake steward answers and goes idle; then the idle path is the one he hit this morning
    surface.locator(".blk.steward").last.wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    box.click()
    box.type("second message")
    box.press("Control+Enter")
    expect(box).to_have_value("", timeout=5000)
    order = None
    for _ in range(40):
        order = surface.locator("body").evaluate("""() => {
            const blocks = [...document.querySelectorAll('.blk')].filter(b => b.offsetParent !== null);
            const i = blocks.findIndex(b => b.classList.contains('john') && b.textContent.includes('second message'));
            return i < 0 ? null : blocks.slice(i, i + 3).map(b => b.className + '|' + b.textContent.trim().slice(0, 40));
        }""")
        if order and any("Received." in x for x in order):
            break
        page.wait_for_timeout(250)
    assert order, "his message was not painted"
    assert "Received." in order[1], order                       # painted directly under his words
    rec = surface.locator(".blk.sys", has_text="Received.").last
    expect(rec).to_be_visible()


# ---------- 1b: the working receipt quotes his words ----------

def test_the_working_receipt_quotes_his_words_after_a_wake(tmp_path, monkeypatch):
    """His words travel with the message - through the wake brief, a goal scope, an answer's context and the queue."""
    import io

    class Proc:
        stdin = io.StringIO()
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    eng.proc = Proc()
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    monkeypatch.setattr(eng, "_persist_queue", lambda: True)
    eng.busy = False
    eng._resume_prefix = steward_engine.RESUME_BRIEF                       # this morning: the first turn after a wake
    assert eng.say("Little bit of feedback on v1.")["ok"]
    assert "You are" in eng._last_submitted                                # the model still gets the brief
    eng.turn_text = ""
    assert eng._turn_activity() == "your message \u201cLittle bit of feedback on v1.\u201d"
    assert eng.say("and the sandwich scene")["queued"]                     # mid-turn: queued with his words
    eng.busy = False
    with eng._lock:
        assert eng._deliver_next_queued_locked()
    eng.turn_text = ""
    assert eng._turn_activity() == "your message \u201cand the sandwich scene\u201d"
    with eng._lock:
        eng.busy = False
        assert eng._send_locked("(drive - not John) Continue.", origin="control")
    assert eng._turn_activity() == "a turn"                                # a control turn never quotes him


# ---------- 5: the served-code notice speaks only to a steward that could have made the change ----------

def _audit_engine(tmp_path, monkeypatch, cockpit_dir, cli="chatgpt"):
    served = tmp_path / "served"
    served.mkdir(exist_ok=True)
    monkeypatch.setattr(steward_engine, "_SERVED", served)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(exist_ok=True)
    cockpit_dir.mkdir(parents=True, exist_ok=True)
    eng = steward_engine.Engine(str(cockpit_dir), fake=True)
    eng.cli = cli
    said = []
    eng._emit = lambda ev: said.append(ev)
    monkeypatch.setattr(steward_engine, "_served_code_changes", lambda snap: ["static/cave-health.js"])
    eng._served_snap = object()
    eng._turn_touched_served = False
    return eng, said, served


def test_a_change_by_someone_else_is_not_said_to_an_unrelated_steward(tmp_path, monkeypatch):
    eng, said, _ = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Book 1")
    eng._finish_served_audit()
    assert said == []
    log = (tmp_path / "data" / "served-code-changes.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["changed"] == ["static/cave-health.js"]


def test_a_steward_whose_own_shell_wrote_there_is_told(tmp_path, monkeypatch):
    eng, said, served = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Book 1")
    eng._note_served_touch({"name": "exec_command",
                            "input": {"cmd": "Set-Content -Path '%s/static/cave-health.js' -Value x" % str(served).replace("\\", "/")}})
    assert eng._turn_touched_served
    eng._finish_served_audit()
    assert any("STANDS" in str(e.get("text")) for e in said)


def test_a_read_of_anchor_does_not_count_as_a_write(tmp_path, monkeypatch):
    eng, said, served = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Book 1")
    eng._note_served_touch({"name": "exec_command",
                            "input": {"cmd": "python %s/tools/steward_code_job.py start --repo x" % str(served).replace("\\", "/")}})
    assert not eng._turn_touched_served


def test_a_cockpit_inside_anchor_and_a_pathless_provider_are_always_told(tmp_path, monkeypatch):
    eng, said, served = _audit_engine(tmp_path, monkeypatch, tmp_path / "served" / "Setup and Mother Ship")
    eng._finish_served_audit()
    assert any("STANDS" in str(e.get("text")) for e in said)
    eng2, said2, _ = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Other", cli="grok")
    eng2._finish_served_audit()
    assert any("STANDS" in str(e.get("text")) for e in said2)


# ---------- 4: a skill job is named by its skill and timed by its own history ----------

def _jobs_file(cdir, rows):
    (cdir / ".ecgberht").mkdir(parents=True, exist_ok=True)
    (cdir / ".ecgberht" / "code-jobs.json").write_text(json.dumps({r["id"]: r for r in rows}), encoding="utf-8")


def _row(i, start, end=None, skill=None, status="done"):
    r = {"id": "job-%d" % i, "brief": "# Review the chapter feedback\n", "status": status, "worker": "coder",
         "coder_family": "chatgpt", "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start)),
         "steward_dir": ""}
    if end:
        r["finished"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end))
    if skill:
        r["skill"] = skill
    return r


def test_a_skill_job_is_named_by_its_skill_and_model(tmp_path):
    now = time.time()
    running = dict(_row(9, now - 360, skill="Chekhov", status="running"), coder_model="gpt-6-astra ultra")
    _jobs_file(tmp_path, [_row(1, now - 9000, now - 7000), running])      # history: one plain 33-min coding job
    jobs = sc.running_code_jobs(str(tmp_path))
    who, phase, _s, _t, finish = sc.who_is_working(str(tmp_path), {}, jobs, None, now=now)
    assert "Chekhov (the chatgpt coder, gpt-6-astra ultra)" in who and "a Chekhov job" in who
    assert "code job" not in who
    assert finish.startswith("no finish time yet - the first Chekhov job here")   # never a coding job's clock
    status = sc.compose_status(str(tmp_path))
    assert status["running"]["skill"] == "Chekhov"


def test_a_skill_jobs_finish_comes_from_that_skills_own_history(tmp_path):
    now = time.time()
    rows = [_row(1, now - 9000, now - 8400, skill="Chekhov"), _row(2, now - 7000, now - 6400, skill="Chekhov"),
            _row(3, now - 5000, now - 3000),                                  # a long coding job, not counted
            _row(9, now - 300, skill="Chekhov", status="running")]
    _jobs_file(tmp_path, rows)
    assert sc.typical_duration_s(str(tmp_path), "code_job", "coder:chekhov") == 600
    assert sc.typical_duration_s(str(tmp_path), "code_job", "coder") == 2000
    jobs = sc.running_code_jobs(str(tmp_path))
    _w, _p, _s, _t, finish = sc.who_is_working(str(tmp_path), {}, jobs, None, now=now)
    assert "no finish time yet" not in finish


def test_the_launcher_carries_the_skill(tmp_path):
    import tools.steward_code_job as launcher
    import inspect
    src = inspect.getsource(launcher.main)
    assert '"--skill"' in src and "skill=a.skill" in src


# ---------- ChatGPT review round 1 (morning fixes) ----------

def test_unreadable_or_unlisted_writes_count_as_possible(tmp_path, monkeypatch):
    eng, said, served = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Book 1")
    root = str(served).replace("/", chr(92))
    cases = [({"name": "command_execution", "input": {"item_id": "x", "names_served": True}}, True),
             ({"name": "command_execution", "input": {"item_id": "x", "names_served": False}}, False),
             ({"name": "Bash", "input": {}}, True),                                         # no command visible
             ({"name": "Bash", "input": {"command": "git -C %s apply fix.patch" % root}}, True),
             ({"name": "Bash", "input": {"command": "cp new.js %s/static/x.js" % str(served)}}, True),
             ({"name": "PowerShell", "input": {"command": "cd %s; Set-Content a.txt x" % root}}, True),
             ({"name": "Bash", "input": {"command": "x" * 7000}}, True),                    # too long to read
             ({"name": "Write", "input": {}}, True),                                        # a file tool without a path
             ({"name": "Bash", "input": {"command": "python %s/tools/steward_code_job.py start --repo r" % str(served)}}, False),
             ({"name": "Bash", "input": {"command": "Get-ChildItem C:/dev/Writing"}}, False)]
    for block, want in cases:
        eng._turn_touched_served = False
        eng._note_served_touch(block)
        assert eng._turn_touched_served is want, block


def test_the_chatgpt_stream_keeps_a_flag_never_the_command():
    """Through the real Codex stream parser: the command is read only for the flag; change paths are kept, bounded."""
    import io
    from steward_cockpit.codex_event_stream import iter_codex_events, names_served, SERVED_ROOT
    root = str(SERVED_ROOT).replace("\\", "/")

    def project(item):
        line = json.dumps({"type": "item.completed", "item": item}).encode("utf-8") + b"\n"
        return list(iter_codex_events(io.BytesIO(line)))[0][0]["item"]
    writes = project({"id": "a", "type": "command_execution", "command": "Set-Content %s/static/x.js 1" % root})
    assert writes["_names_served"] is True and "command" not in writes
    reads = project({"id": "b", "type": "command_execution", "command": "Get-Content C:/dev/Writing/notes.md"})
    assert reads["_names_served"] is False and "command" not in reads
    argv = project({"id": "c", "type": "command_execution", "command": ["powershell", "-c", "cp a %s/x.py" % root]})
    assert argv["_names_served"] is True
    change = project({"id": "d", "type": "file_change", "changes": [{"path": "C:/dev/Writing/n.md", "kind": "update"}]})
    assert change["changes"] == [{"path": "C:/dev/Writing/n.md"}] and change["_change_count"] == 1
    assert names_served(None) and names_served("")                                   # unreadable counts
    assert not names_served("python %s/tools/steward_code_job.py start --repo r" % root)  # a RUN of the launcher
    assert names_served("Set-Content %s/tools/steward_code_job.py -Value x" % root)      # a WRITE to it is not excused
    assert not names_served("dir %s-other/x" % root)                                  # a sibling folder is not it


def test_an_idle_control_still_hears_received_after_his_words(tmp_path, monkeypatch):
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    said = []
    monkeypatch.setattr(eng, "_emit", lambda ev: said.append(ev))
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    monkeypatch.setattr(eng, "_send_locked", lambda text, origin="human", **kw: True)
    eng.busy = False
    eng.open_question = "Which chapter first?"
    eng.open_question_kind = "decision"
    assert eng.say("pause")["control_only"]
    kinds = [(e.get("t"), e.get("text")) for e in said]
    assert kinds.index(("john", "pause")) + 1 == kinds.index(("sys", "Received."))


# ---------- ChatGPT review round 3 (morning fixes) ----------

def test_an_incomplete_change_list_counts_as_a_possible_served_write(tmp_path, monkeypatch):
    import io
    from steward_cockpit.codex_event_stream import iter_codex_events
    eng, said, served = _audit_engine(tmp_path, monkeypatch, tmp_path / "Writing" / "Book 1")
    many = [{"path": "C:/dev/Writing/n%d.md" % i, "kind": "update"} for i in range(21)]
    line = json.dumps({"type": "item.completed", "item": {"id": "d", "type": "file_change", "changes": many}})
    item = list(iter_codex_events(io.BytesIO(line.encode("utf-8") + b"\n")))[0][0]["item"]
    assert item["_change_count"] == 21 and len(item["changes"]) == 20 and item["_paths_incomplete"]
    eng._turn_touched_served = False
    eng._note_served_touch({"name": "file_change", "input": {"paths": [c["path"] for c in item["changes"]],
                                                             "paths_incomplete": True}})
    assert eng._turn_touched_served
    eng._turn_touched_served = False
    eng._note_served_touch({"name": "file_change", "input": {"paths": ["C:/dev/Writing/n1.md"]}})
    assert not eng._turn_touched_served                                  # a complete list of book files clears


def test_received_survives_a_failed_question_bookkeeping(tmp_path, monkeypatch):
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    said = []
    monkeypatch.setattr(eng, "_emit", lambda ev: said.append(ev))
    monkeypatch.setattr(eng, "alive", lambda: True)
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    q = {"id": "q1", "text": "Which chapter?"}
    monkeypatch.setattr(eng, "_question_contexts", lambda wait: [q])
    monkeypatch.setattr(steward_engine, "_update_state", lambda key, upd: False if "question_history" in upd else True)
    eng.busy = False
    out = eng.say("Chapter two", question_id="q1")
    assert not out["ok"]                                                  # the bookkeeping failed, and says so
    kinds = [(e.get("t"), e.get("text")) for e in said]
    assert kinds[:2] == [("john", "Chapter two"), ("sys", "Received.")]   # yet his durable words were shown + received


# ---------- ChatGPT review round 4 (morning fixes) ----------

def test_a_git_bash_spelling_of_the_served_root_counts():
    from steward_cockpit.codex_event_stream import names_served
    root = "C:/dev/Anchor"
    assert names_served("cp replacement.js /c/dev/Anchor/static/cave-health.js", root)
    assert names_served("cd /c/dev/anchor && git apply x.patch", root)
    assert not names_served("python /c/dev/Anchor/tools/steward_code_job.py start --repo r", root)
    assert not names_served("ls /c/dev/Anchor-other/x", root)
    assert not names_served("cat /c/dev/Writing/notes.md", root)

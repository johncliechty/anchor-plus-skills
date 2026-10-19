"""John 2026-10-12: jobs hand work out and get it back seamlessly - no job finished while its work still runs, no
16-minute PDF renderers, no lost plan.

Proven live before these tests were written (scratchpad e2e_bg_job.py, a real Claude coder): on the old engine a job
whose coder started its work in the background closed after 19 s with nothing and the file appeared after; on this one
it waited, collected and landed it (69 s)."""
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from steward_cockpit import code_jobs

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def coder(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine as se
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    eng = se.Engine(str(tmp_path), fake=True)
    eng.cli = "claude"
    eng.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    eng.code_job = {"cdir": str(tmp_path), "id": "j1", "repo": str(tmp_path), "worktree": str(tmp_path),
                    "work_dir": "", "outputs": []}
    monkeypatch.setattr(eng, "_status_update", lambda **kw: None)
    done = []
    eng.on_turn_done = done.append
    return eng, done


def _result(text):
    return {"type": "result", "subtype": "success", "result": text, "total_cost_usd": 0.0, "duration_ms": 10}


def test_a_turn_that_ends_with_a_background_command_running_does_not_finish_the_job(coder):
    eng, done = coder
    eng._handle({"type": "system", "subtype": "background_tasks_changed",
                 "tasks": [{"task_id": "b1", "task_type": "local_bash"}]}, eng.proc)
    eng.turn_text = "STARTED"
    eng._handle(_result("STARTED"), eng.proc)
    assert done == [], "the job waits while its command still runs"
    eng._handle({"type": "system", "subtype": "background_tasks_changed", "tasks": []}, eng.proc)
    eng.turn_text = "FINISHED"
    eng._handle(_result("FINISHED"), eng.proc)
    assert len(done) == 1 and "FINISHED" in done[0]["text"], done


def test_a_long_background_command_is_never_killed_and_never_silent(coder, monkeypatch):
    """Review r6: nothing tells a slow skill from a hang, so the job keeps waiting - and says so on its record, where
    the steward and the job status show it and Stop ends it."""
    from steward_cockpit import steward_engine as se
    from steward_cockpit import code_jobs as cj
    eng, done = coder
    notes = []
    monkeypatch.setattr(se, "_bg_wait_limit", lambda: 0.2)
    monkeypatch.setattr(cj, "_note_stuck", lambda cdir, jid, why: notes.append(why))
    eng._handle({"type": "system", "subtype": "background_tasks_changed", "tasks": [{"task_id": "long"}]}, eng.proc)
    eng.turn_text = "STARTED"
    eng._handle(_result("STARTED"), eng.proc)
    import time
    time.sleep(0.7)
    assert done == [] and eng.proc is not None, "never cut off"
    assert notes and "background command(s) the coder left running; Stop ends them" in notes[0], notes


def test_a_copy_made_before_the_check_is_remade_when_the_check_rewrites_its_markdown(tmp_path):
    import os
    (tmp_path / "plan.md").write_text("# Old\n", encoding="utf-8")
    job = {"outputs": ["plan.md", "plan.html"]}
    made = code_jobs._make_reading_copies(job, str(tmp_path))
    assert made == ["plan.html"]
    (tmp_path / "plan.md").write_text("# New plan\n", encoding="utf-8")           # what the check wrote
    t = (tmp_path / "plan.html").stat().st_mtime
    os.utime(tmp_path / "plan.md", (t + 5, t + 5))
    code_jobs._make_reading_copies(job, str(tmp_path), made)
    assert "New plan" in (tmp_path / "plan.html").read_text(encoding="utf-8")


def test_a_coder_that_woke_on_its_own_is_never_ended_by_its_earlier_wait(coder, monkeypatch):
    from steward_cockpit import steward_engine as se
    eng, done = coder
    monkeypatch.setattr(se, "_bg_wait_limit", lambda: 0.3)
    eng._handle({"type": "system", "subtype": "background_tasks_changed",
                 "tasks": [{"task_id": "a"}, {"task_id": "b"}]}, eng.proc)
    eng.turn_text = "STARTED"
    eng._handle(_result("STARTED"), eng.proc)
    eng._handle({"type": "system", "subtype": "background_tasks_changed", "tasks": [{"task_id": "b"}]}, eng.proc)
    eng._handle({"type": "assistant", "message": {"content": [{"type": "text", "text": "a finished"}]}}, eng.proc)
    assert eng.busy, "it is working again"
    import time
    time.sleep(0.7)
    assert done == [], "the earlier turn's timer did not end the working coder"


def test_his_messages_for_different_places_are_not_batched(steward, monkeypatch):
    from steward_cockpit import steward_engine as se
    sent = []
    monkeypatch.setattr(steward, "_send_locked", lambda text, origin, words="": sent.append(text) or True)
    monkeypatch.setattr(steward, "_persist_queue", lambda: True)
    monkeypatch.setattr(steward, "effort_on", lambda: False)
    monkeypatch.setenv("ANCHOR_TAKE_NOW_AFTER_S", "0")
    a = se._scoped_text("first", "g1", "Goal one")
    b = se._scoped_text("second", "g2", "Goal two")
    steward.busy, steward.queue = False, [a, b]
    steward._deliver_next_queued_locked()
    assert sent == [a] and steward.queue == [b]


def test_a_turn_with_nothing_in_the_background_finishes_at_once(coder):
    eng, done = coder
    eng.turn_text = "Done."
    eng._handle(_result("Done."), eng.proc)
    assert len(done) == 1


def test_the_reading_copy_tool_makes_a_pdf_and_html_in_seconds(tmp_path):
    md = tmp_path / "plan.md"
    md.write_text("# Plan\n\nBuild the history command.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n$x^2$\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reading_copy.py"), str(md), "--html"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "plan.pdf").read_bytes().startswith(b"%PDF")
    assert "Build the history command." in (tmp_path / "plan.html").read_text(encoding="utf-8")


def test_a_reading_copy_shows_figures_not_links(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("# Doc\n\n![The chart](figs/chart.png)\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reading_copy.py"), str(md), "--no-pdf", "--html"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '<img src="figs/chart.png" alt="The chart"' in (tmp_path / "doc.html").read_text(encoding="utf-8")


def test_a_declared_reading_copy_the_coder_left_is_made_by_the_job(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "spine.md").write_text("# Spine\n\nOne.\n", encoding="utf-8")
    job = {"outputs": ["d/spine.md", "d/spine.pdf", "d/spine.html", "d/other.pdf"]}
    made = code_jobs._make_reading_copies(job, str(tmp_path))
    assert sorted(made) == ["d/spine.html", "d/spine.pdf"], made
    assert (tmp_path / "d" / "spine.pdf").read_bytes().startswith(b"%PDF")
    assert not (tmp_path / "d" / "other.pdf").exists(), "no Markdown of that name: nothing is invented"


@pytest.fixture
def steward(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine as se
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    return se.Engine(str(tmp_path), fake=True)


def test_his_waiting_message_is_taken_even_after_something_was_written_into_the_turn(steward, monkeypatch):
    """Seen 10-12: 'This plan is fine' waited 26 min - a write into the running turn restamped turn_started and the
    take-now timer, checking that stamp, stood down."""
    calls = []
    monkeypatch.setattr(steward, "_interrupt_turn_locked", lambda reason: calls.append(reason) or {"ok": True})
    monkeypatch.setattr(steward, "_wake_locked", lambda fresh, seed: calls.append("wake") or (True, ""))
    steward.busy, steward.queue = True, ["This plan is fine."]
    steward._turn_began = steward.turn_started = 1000.0
    expected = steward._turn_identity()
    steward.turn_started = 1500.0                 # a nudge or progress line written into the same turn
    steward._auto_take_now(expected)
    assert calls == ["John: take this now", "wake"]


def test_every_message_of_his_waiting_in_line_goes_in_the_next_turn_together(steward, monkeypatch):
    sent = []
    monkeypatch.setattr(steward, "_send_locked", lambda text, origin, words="": sent.append((text, origin)) or True)
    monkeypatch.setattr(steward, "_persist_queue", lambda: True)
    monkeypatch.setattr(steward, "effort_on", lambda: False)
    steward.busy = False
    steward.queue = ["So fix the error.", "This plan is fine.", "(code job x result - not John) done"]
    assert steward._deliver_next_queued_locked()
    assert sent == [("So fix the error.\n\nThis plan is fine.", "human")], sent
    assert steward.queue == ["(code job x result - not John) done"], "a machine result keeps its own turn"


def test_a_batch_cut_off_by_a_restart_comes_back_message_by_message_never_doubled(steward, monkeypatch):
    long = "x" * 5000
    steward.queue = ["(possibly a repeat) This plan is fine."]       # one part is still queued after a failed persist
    steward._submitted = {"text": ("So fix the error.\n\n" + long)[:4000],
                          "parts": ["So fix the error.", long, "This plan is fine."]}
    monkeypatch.setattr(steward_engine_mod(), "_update_state", lambda *a, **k: True)
    steward._reconcile_submitted_locked({})
    assert [q.split(") ", 1)[-1] for q in steward.queue] == ["So fix the error.", long, "This plan is fine."], \
        "each message whole, in order, the one still queued not added again"


def steward_engine_mod():
    from steward_cockpit import steward_engine as se
    return se


def test_a_replaced_coder_process_starts_with_no_background_commands(coder):
    eng, _ = coder
    eng._bg_tasks = [{"task_id": "old"}]
    src = Path(steward_engine_mod().__file__).read_text(encoding="utf-8")
    assert "self.proc = proc\n        self._bg_tasks = []" in src


def test_a_reading_copy_is_never_made_through_a_link_or_over_a_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text("# Outside\n", encoding="utf-8")
    tree = tmp_path / "tree"
    (tree / "d").mkdir(parents=True)
    try:
        (tree / "d" / "notes.md").symlink_to(outside / "notes.md")
        linked = True
    except OSError:
        linked = False
    (tree / "d" / "page.md").write_text("# Page\n", encoding="utf-8")
    (tree / "d" / "page.html").write_text("keep me", encoding="utf-8")
    made = code_jobs._make_reading_copies({"outputs": ["d/notes.html", "d/page.html", "d/page.htm"]}, str(tree))
    assert made == ["d/page.htm"], made
    assert (tree / "d" / "page.html").read_text(encoding="utf-8") == "keep me", "an existing file is never replaced"
    assert "Page" in (tree / "d" / "page.htm").read_text(encoding="utf-8")
    if linked:
        assert not (outside / "notes.html").exists(), "nothing is written beside a linked target"


def test_the_coder_is_told_to_work_in_proportion_and_never_to_write_a_renderer():
    text = code_jobs.coder_brief({"repo": "R", "branch": "B", "brief": "x", "outputs": ["d/p.md", "d/p.pdf"]})
    assert "reading_copy.py" in text and "Never write your own renderer" in text
    assert "Work in proportion to the brief" in text and "Never end your turn while a command you started" in text

"""The session registry's readers' cache (2026-10-01).

The Cave of Wonders page took about 14 s to answer every load; the morning health check had flagged the home page slow
for a week ("likely machine load"). Profiled against his records: the page's project tiles call ``list_sessions`` three
times each - 76 calls a page - and every call re-read the 2.6 MB store and re-normalized its 2,012 records. Readers now
share one parsed registry while the store's file is unchanged.

The pins are the ways a cache could lie: a write by this process, a write from outside, two writes inside one clock tick
with the same size, a caller that scribbles on what it was handed, a mutator reading stale, an unreadable store."""
import importlib
import json
import os
import time

import pytest


@pytest.fixture
def sr(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import session_registry
    importlib.reload(session_registry)
    return session_registry


def _settle(sr, seconds=30):
    """The store as it is on any ordinary page load: last written a while ago."""
    p = str(sr.sessions_path())
    t = time.time() - seconds
    os.utime(p, (t, t))


def _rewrite(p, text):
    """An outside writer's bytes exactly (no newline translation: the size is part of the cache's key)."""
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _count_reads(sr, monkeypatch):
    calls = []
    real = sr.load_sessions
    monkeypatch.setattr(sr, "load_sessions", lambda: (calls.append(1), real())[1])
    return calls


def test_readers_share_one_read_of_a_store_that_has_not_changed(sr, monkeypatch):
    a = sr.register_session("p1", "research")
    b = sr.register_session("p1", "plan", parent_session_id=a["session_id"], chain_id=a["chain_id"])
    sr.register_session("p2", "build")
    _settle(sr)
    reads = _count_reads(sr, monkeypatch)
    for _ in range(25):
        assert len(sr.list_sessions()) == 3 and len(sr.list_sessions("p1")) == 2 and sr.list_sessions(status="no-such") == []
    assert sr.get_session(a["session_id"])["lane"] == "research" and sr.get_session("nope") is None
    assert sr.chain_for(b["session_id"]) == sr.chain_for(a["session_id"]) and len(sr.chain_members(sr.chain_for(a["session_id"]))) == 2
    assert sr.effort_root(a["session_id"]) and sr.effort_root("nope") is None
    assert len(reads) == 1, "the page's 76 calls are one read: %d" % len(reads)


def test_a_write_by_this_process_is_seen_at_once(sr, monkeypatch):
    a = sr.register_session("p1", "research", status=sr.STATUS_RUNNING)
    _settle(sr)
    assert sr.get_session(a["session_id"])["status"] == sr.STATUS_RUNNING
    sr.update_session(a["session_id"], status=sr.STATUS_DONE)          # a fresh write: same tick or not, the cache is dropped
    assert sr.get_session(a["session_id"])["status"] == sr.STATUS_DONE
    assert [r["status"] for r in sr.list_sessions("p1")] == [sr.STATUS_DONE]
    c = sr.register_session("p1", "plan")
    assert {r["session_id"] for r in sr.list_sessions("p1")} == {a["session_id"], c["session_id"]}
    assert sr.remove_session(c["session_id"]) and sr.get_session(c["session_id"]) is None


def test_a_write_from_outside_is_seen(sr):
    a = sr.register_session("p1", "research")
    _settle(sr, 60)
    assert len(sr.list_sessions()) == 1
    p = sr.sessions_path()
    rows = json.loads(p.read_text(encoding="utf-8"))
    rows.append(dict(rows[0], session_id="from-outside", project_id="p9"))
    _rewrite(p, json.dumps(rows))                                      # the CLI, another process: no cache to drop there
    _settle(sr, 30)                                                    # a different time, a different size
    assert {r["session_id"] for r in sr.list_sessions()} == {a["session_id"], "from-outside"}


def test_two_writes_inside_one_clock_tick_with_one_size_are_never_served_stale(sr, monkeypatch):
    """Windows stamps a file with the system clock's tick: "done" and "idle" are both four letters, so a second write in
    the same tick can leave path, mtime and size all equal. A store that fresh is not cached at all."""
    a = sr.register_session("p1", "research", status=sr.STATUS_RUNNING)
    sr.update_session(a["session_id"], status=sr.STATUS_DONE)
    p = sr.sessions_path()
    stamp = os.stat(p)
    reads = _count_reads(sr, monkeypatch)
    assert sr.get_session(a["session_id"])["status"] == "done"
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    assert text.count('"done"') == 1
    _rewrite(p, text.replace('"done"', '"idle"'))
    os.utime(p, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))             # the very same stamp, the very same size
    assert os.stat(p).st_size == stamp.st_size and os.stat(p).st_mtime_ns == stamp.st_mtime_ns
    assert sr.get_session(a["session_id"])["status"] == "idle", "a store written a moment ago is read again, never trusted"
    assert len(reads) == 2
    _settle(sr)
    sr.get_session(a["session_id"]); sr.get_session(a["session_id"]); sr.list_sessions()
    assert len(reads) == 3, "once it has settled it is read once"


def test_a_reader_gets_its_own_copy(sr):
    a = sr.register_session("p1", "research", status=sr.STATUS_RUNNING)
    _settle(sr)
    for rec in sr.list_sessions():
        rec["status"] = "scribbled"; rec["extra"] = 1
    got = sr.get_session(a["session_id"])
    got["lane"] = "scribbled"
    for rec in sr.chain_members(sr.chain_for(a["session_id"])):
        rec["label"] = "scribbled"
    clean = sr.get_session(a["session_id"])
    assert clean["status"] == sr.STATUS_RUNNING and clean["lane"] == "research" and "extra" not in clean and clean.get("label") != "scribbled"


def test_mutators_always_read_the_file(sr):
    src = open(sr.__file__, encoding="utf-8").read()
    body = src[src.index("def _read_sessions() -> dict:"):]
    readers = [ln.strip() for ln in body.splitlines() if "_read_sessions()" in ln and not ln.lstrip().startswith(("def ", "#"))]
    assert len(readers) == 5, readers     # get_session, list_sessions, chain_for, chain_members, effort_root
    for name in ("register_session", "update_session", "remove_session", "set_current_stage", "finalize_cost_once", "claim_job", "release_job"):
        fn = src[src.index("def %s(" % name):]
        fn = fn[:fn.index("\ndef ", 10)]
        assert "load_sessions()" in fn and "_read_sessions()" not in fn, name
    # and behaviourally: a stale cache cannot leak into a read-modify-write
    a = sr.register_session("p1", "research", status=sr.STATUS_RUNNING, label="before")
    _settle(sr, 60)
    assert sr.get_session(a["session_id"])["label"] == "before"       # the readers' cache now holds "before"
    p = sr.sessions_path()
    stamp = os.stat(p)
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    assert text.count('"before"') == 1
    _rewrite(p, text.replace('"before"', '"after!"'))                  # an outside edit of the same size ...
    os.utime(p, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))             # ... under the very same stamp: the cache cannot tell
    assert sr.get_session(a["session_id"])["label"] == "before", "the one case a reader can be shown the store as it was"
    sr.update_session(a["session_id"], status=sr.STATUS_DONE)          # a mutator reads the FILE
    on_disk = json.loads(p.read_text(encoding="utf-8"))[0]
    assert on_disk["status"] == sr.STATUS_DONE and on_disk["label"] == "after!", "the write was built on the file as it stood, never on the cache"
    assert sr.get_session(a["session_id"])["label"] == "after!"


def test_an_unreadable_or_empty_store_is_never_cached(sr, monkeypatch):
    p = sr.sessions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    assert sr.list_sessions() == [] and sr.get_session("x") is None       # no store
    _rewrite(p, "{ not json")
    _settle(sr)
    reads = _count_reads(sr, monkeypatch)
    assert sr.list_sessions() == [] and sr.list_sessions() == []
    assert len(reads) == 2, "a corrupt store is read every time until it is whole"
    _rewrite(p, "[]")
    _settle(sr)
    assert sr.list_sessions() == [] and sr.list_sessions() == []
    assert len(reads) == 4, "an empty registry is not worth caching either"


def test_a_reader_s_copy_is_its_own_all_the_way_down(sr):
    """Grok's read: the stage writers edit stage entries in place; ``dict(rec)`` alone would hand every reader the
    cache's own stage_history, job ids and summary refs - a nested write would stick for as long as the file stood."""
    a = sr.register_session("p1", "research", status=sr.STATUS_RUNNING, effort_managed=True)
    sr.set_current_stage(a["session_id"], "research", "research", "abc123")
    sr.claim_job(a["session_id"], "job-1")
    _settle(sr)
    before = sr.get_session(a["session_id"])
    assert before["stage_history"] and before["owned_job_ids"] == ["job-1"]
    for rec in (sr.get_session(a["session_id"]), sr.list_sessions()[0], sr.chain_members(sr.chain_for(a["session_id"]))[0]):
        rec["stage_history"].append({"stage": "scribbled"})
        rec["stage_history"][0]["stage"] = "scribbled"
        rec["stage_history"][0]["new"] = {"deep": 1}
        rec["owned_job_ids"].append("scribbled")
        for k, v in list(rec.items()):
            if isinstance(v, list):
                v.append("scribbled")
            elif isinstance(v, dict):
                v["scribbled"] = 1
    assert sr.get_session(a["session_id"]) == before, "the next reader sees the store, not the last reader's edits"
    assert sr.list_sessions()[0] == before

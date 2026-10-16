"""Owned invocation accounting from disposable Codex rollout files."""

import json
from pathlib import Path

import pytest

from steward_cockpit import codex_usage as source


THREAD = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
OTHER_THREAD = "01a08260-068d-76a1-99f6-5a7bdf3aaab9"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds=5):
        self.now += seconds


def line(record):
    return (json.dumps(record) + "\n").encode("utf-8")


def metadata(target, thread=THREAD):
    return {"type": "session_meta", "payload": {"id": thread, "cwd": str(target)}}


def tokens(input_tokens=100, cached_input_tokens=40, output_tokens=10, **overrides):
    totals = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": 3 if output_tokens >= 3 else 0,
        "total_tokens": input_tokens + output_tokens,
        **overrides,
    }
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": totals, "last_token_usage": dict(totals)}}}


def started(turn_id):
    return {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn_id}}


def rollout(root, target, records=None, *, thread=THREAD, meta=None, day="10"):
    if records is None:
        records = [tokens(0, 0, 0)]  # A known measured pre-resume baseline.
    path = root / "2026" / "09" / day / f"rollout-2026-09-{day}T00-00-00-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(line(metadata(target, thread) if meta is None else meta) + b"".join(line(record) for record in records))
    return path


def append(path, *records):
    with path.open("ab") as stream:
        for record in records:
            stream.write(line(record))


@pytest.fixture
def paths(tmp_path):
    target = tmp_path / "project with spaces"
    target.mkdir()
    return tmp_path / "sessions", target, Clock()


def test_resume_latches_eof_before_child_and_excludes_old_thread_usage(paths):
    root, target, clock = paths
    path = rollout(root, target, [tokens(900000, 100000, 9000), started("old-turn")])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    assert tracker.poll() is None
    append(path, started("owned-turn"), tokens(100, 40, 10))
    result = tracker.poll(force=True)
    assert result == {"usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}, "token_status": "reported", "source": "codex-rollout"}
    assert sum(result["usage"][key] for key in ("input_tokens", "output_tokens")) == 110
    assert "spend" not in result and "cost" not in result


def test_new_thread_bind_reads_new_file_from_start(paths):
    root, target, clock = paths
    tracker = source.CodexUsageTracker(target, sessions_root=root, clock=clock)
    assert tracker.poll() is None
    rollout(root, target, [started("new-turn"), tokens()])
    tracker.bind(THREAD)
    assert tracker.poll(force=True)["usage"]["input_tokens"] == 100
    tracker.bind(THREAD)
    assert tracker.poll(force=True) is None


def test_missing_resume_source_never_later_imports_historical_usage(paths):
    root, target, clock = paths
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    first = tracker.poll()
    assert first["usage"] is None
    assert first["error"] == "usage-resume-baseline-unavailable"
    rollout(root, target, [tokens(900000, 100000, 9000)])
    clock.advance(10)
    tracker.bind(THREAD)
    assert tracker.poll(force=True) is None


def test_resume_continuing_counter_credits_only_post_eof_delta(paths):
    root, target, clock = paths
    path = rollout(root, target, [tokens(900000, 0, 0)])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    event = tokens(900100, 0, 0)
    event["payload"]["info"]["last_token_usage"] = tokens(100, 0, 0)["payload"]["info"]["total_token_usage"]
    append(path, started("new-invocation"), event)
    assert tracker.poll()["usage"] == {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 0}


@pytest.mark.parametrize("before,after", [(900000, 100), (100, 900100)])
def test_new_task_first_call_attests_reset_even_when_new_total_is_larger(paths, before, after):
    root, target, clock = paths
    path = rollout(root, target, [tokens(before, 0, 0)])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, started("new-invocation"), tokens(after, 0, 0))
    assert tracker.poll()["usage"]["input_tokens"] == after


def test_missing_counter_baseline_does_not_credit_first_total(paths):
    root, target, clock = paths
    path = rollout(root, target, records=[])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, started("new-invocation"), tokens(900100, 0, 0))
    first = tracker.poll()
    assert first["usage"] is None
    assert first["error"] == "usage-baseline-unavailable"
    append(path, tokens(900150, 0, 0))
    assert tracker.poll(force=True)["usage"]["input_tokens"] == 50


def test_invalid_latest_baseline_cannot_recredit_gap_from_older_counter(paths):
    root, target, clock = paths
    path = rollout(root, target, [tokens(100, 0, 0), tokens(1000, 0, 0, total_tokens="corrupt")])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens(1100, 0, 0))
    assert tracker.poll()["usage"] is None


def test_baseline_tail_is_bounded_and_missing_old_counter_stays_unknown(paths):
    root, target, clock = paths
    path = rollout(root, target, [tokens(1000, 0, 0), {"type": "response_item", "payload": {"text": "x" * (source.MAX_BASELINE_BYTES + 100)}}])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    assert tracker._discovery_read_bytes <= source.MAX_POLL_BYTES
    append(path, tokens(1100, 0, 0))
    assert tracker.poll()["usage"] is None


@pytest.mark.parametrize("meta, error", [
    ({"type": "session_meta", "payload": {"id": OTHER_THREAD, "cwd": "irrelevant"}}, "usage-session-mismatch"),
    ({"type": "session_meta", "payload": {"id": THREAD, "cwd": "a different project"}}, "usage-project-mismatch"),
    ({"type": "event_msg", "payload": {}}, "usage-session-metadata-invalid"),
])
def test_matching_filename_never_overrides_session_identity_or_project(paths, meta, error):
    root, target, clock = paths
    rollout(root, target, [tokens()], meta=meta)
    tracker = source.CodexUsageTracker(target, sessions_root=root, clock=clock)
    tracker.bind(THREAD)
    assert tracker.poll(force=True) == {"usage": None, "token_status": "unavailable", "source": "codex-rollout", "error": error}


def test_project_identity_uses_canonical_path(paths):
    root, target, clock = paths
    alias = target / "unused" / ".."
    rollout(root, target, [tokens()], meta=metadata(alias))
    tracker = source.CodexUsageTracker(target, sessions_root=root, clock=clock)
    tracker.bind(THREAD)
    assert tracker.poll(force=True)["token_status"] == "reported"


def test_two_exact_uuid_files_are_ambiguous_without_mtime_selection(paths):
    root, target, clock = paths
    rollout(root, target, [tokens()], day="09")
    rollout(root, target, [tokens(500, 50, 20)], day="10")
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    assert tracker.poll()["error"] == "usage-source-ambiguous"


def test_other_thread_file_is_never_used_as_fallback(paths):
    root, target, clock = paths
    rollout(root, target, [tokens()], thread=OTHER_THREAD)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    assert tracker.poll(force=True)["usage"] is None


def test_duplicate_cumulative_snapshots_do_not_add_work(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens())
    assert tracker.poll()["usage"]["input_tokens"] == 100
    append(path, tokens(), tokens())
    assert tracker.poll(force=True) is None
    append(path, tokens(200, 80, 20))
    assert tracker.poll(force=True)["usage"] == {"input_tokens": 200, "cached_input_tokens": 80, "output_tokens": 20}


def test_split_lines_are_buffered_until_complete(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    raw = line(tokens())
    middle = len(raw) // 2
    with path.open("ab") as stream:
        stream.write(raw[:middle])
    assert tracker.poll() is None
    assert len(tracker._pending) <= source.MAX_LINE_BYTES
    with path.open("ab") as stream:
        stream.write(raw[middle:])
    assert tracker.poll(force=True)["token_status"] == "reported"


def test_resume_skips_a_preexisting_partial_final_record(paths):
    root, target, clock = paths
    path = rollout(root, target)
    old = line(tokens(8000, 6000, 500))
    with path.open("ab") as stream:
        stream.write(old[:40])
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    with path.open("ab") as stream:
        stream.write(old[40:])
        stream.write(line(tokens()))
    result = tracker.poll()
    assert result["token_status"] == "reported"
    assert result["usage"]["input_tokens"] == 100


def test_counter_reset_is_partial_and_never_guessed_as_another_invocation(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens(1000, 500, 100))
    first = tracker.poll()
    append(path, tokens(100, 40, 10), tokens(9000, 4000, 900))
    result = tracker.poll(force=True)
    assert result["usage"] == first["usage"]
    assert result["token_status"] == "partial"
    assert result["error"] == "usage-counters-decreased"
    assert tracker.poll(force=True) is None


def test_second_task_identity_refuses_cross_invocation_aggregation(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, started("owned"), tokens())
    first = tracker.poll()
    append(path, started("owned"), started("foreign"), tokens(10000, 5000, 100))
    result = tracker.poll(force=True)
    assert result["error"] == "usage-scope-ambiguous"
    assert result["usage"] == first["usage"]


def test_rebinding_a_different_session_never_changes_attribution(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens())
    first = tracker.poll()
    tracker.bind(OTHER_THREAD)
    result = tracker.poll(force=True)
    assert result["error"] == "usage-scope-ambiguous"
    assert result["usage"] == first["usage"]


def test_missing_source_returns_none_and_discovery_retry_is_throttled(paths, monkeypatch):
    root, target, clock = paths
    real_glob = Path.glob
    discoveries = []

    def counted_glob(path, pattern):
        discoveries.append(pattern)
        return real_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", counted_glob)
    tracker = source.CodexUsageTracker(target, sessions_root=root, clock=clock)
    tracker.bind(THREAD)
    assert tracker.poll(force=True) is None
    assert tracker.poll(force=True) is None
    assert len(discoveries) == 1
    rollout(root, target, [tokens()])
    clock.advance(4.9)
    assert tracker.poll(force=True) is None
    clock.advance(0.1)
    assert tracker.poll(force=True)["usage"]["input_tokens"] == 100
    assert len(discoveries) == 2


def test_normal_poll_is_throttled_but_completion_flush_is_immediate(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens())
    assert tracker.poll()["usage"]["input_tokens"] == 100
    append(path, tokens(200, 80, 20))
    clock.advance(1)
    assert tracker.poll() is None
    assert tracker.poll(force=True)["usage"]["input_tokens"] == 200


@pytest.mark.parametrize("field, value", [("input_tokens", True), ("cached_input_tokens", -1), ("output_tokens", 1.5), ("output_tokens", "10"), ("total_tokens", 999)])
def test_malformed_counters_do_not_fabricate_zero(paths, field, value):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    event = tokens()
    event["payload"]["info"]["total_token_usage"][field] = value
    append(path, event)
    result = tracker.poll()
    assert result["usage"] is None
    assert result["token_status"] == "unavailable"
    assert result["error"] == "usage-counters-malformed"


def test_missing_usage_information_is_explicitly_unavailable(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, {"type": "event_msg", "payload": {"type": "token_count", "info": None}})
    assert tracker.poll()["error"] == "usage-counters-malformed"


def test_malformed_record_never_exports_transcript_or_file_path(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    with path.open("ab") as stream:
        stream.write(b'{private transcript secret\n')
    result = tracker.poll()
    assert result["error"] == "usage-record-malformed"
    rendered = json.dumps(result)
    assert "private transcript secret" not in rendered
    assert str(target) not in rendered


def test_zero_is_valid_reported_usage_and_cached_reasoning_are_subsets(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens(0, 0, 0))
    zero = tracker.poll()
    assert zero["usage"] == {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    assert zero["token_status"] == "reported"
    append(path, tokens(100, 80, 10, reasoning_output_tokens=9))
    result = tracker.poll(force=True)
    assert result["usage"] == {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10}
    assert result["usage"]["input_tokens"] + result["usage"]["output_tokens"] == 110


@pytest.mark.parametrize("record_type", ["response_item", "event_msg"])
def test_oversized_non_usage_line_is_skipped_without_losing_later_usage(paths, record_type):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, {"type": record_type, "payload": {"type": "agent_message", "text": "x" * (source.MAX_LINE_BYTES + 100)}}, tokens())
    result = tracker.poll()
    assert result["token_status"] == "reported"
    assert result["usage"]["input_tokens"] == 100
    assert len(tracker._pending) <= source.MAX_LINE_BYTES


def test_read_budget_includes_discovery_and_never_uses_uncapped_reads(paths, monkeypatch):
    root, target, clock = paths
    tracker = source.CodexUsageTracker(target, sessions_root=root, clock=clock)
    tracker.bind(THREAD)
    path = rollout(root, target, [{"type": "response_item", "payload": {"type": "message", "text": "x" * (source.MAX_POLL_BYTES + source.MAX_LINE_BYTES)}}, tokens()])
    real_open = Path.open
    reads = []

    class CountedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def read(self, size=-1):
            assert 0 <= size <= source.READ_CHUNK_BYTES
            value = self.stream.read(size)
            reads.append(len(value))
            return value

        def readline(self, size=-1):
            assert 0 <= size <= source.MAX_LINE_BYTES
            value = self.stream.readline(size)
            reads.append(len(value))
            return value

    def counted_open(candidate, *args, **kwargs):
        stream = real_open(candidate, *args, **kwargs)
        return CountedReader(stream) if candidate == path and args and args[0] == "rb" else stream

    monkeypatch.setattr(Path, "open", counted_open)
    clock.advance()
    assert tracker.poll() is None
    assert sum(reads) <= source.MAX_POLL_BYTES
    assert len(tracker._pending) <= source.MAX_LINE_BYTES
    reads.clear()
    result = tracker.poll(force=True)
    assert result["token_status"] == "reported"
    assert result["usage"]["input_tokens"] == 100
    assert sum(reads) <= source.MAX_POLL_BYTES


def test_source_read_failure_is_reported_without_raising(paths, monkeypatch):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    real_open = Path.open

    def denied(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("secret diagnostic")
        return real_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    result = tracker.poll()
    assert result == {"usage": None, "token_status": "unavailable", "source": "codex-rollout", "error": "usage-source-unreadable"}


def test_unreadable_resume_baseline_cannot_later_ingest_old_usage(paths, monkeypatch):
    root, target, clock = paths
    path = rollout(root, target, [tokens(90000, 80000, 500)])
    real_open = Path.open

    def denied(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("baseline unavailable")
        return real_open(candidate, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    clock.advance()
    result = tracker.poll()
    assert result["usage"] is None
    assert result["error"] == "usage-source-unreadable"
    assert tracker.poll(force=True) is None


def test_source_truncation_preserves_only_verified_partial_usage(paths):
    root, target, clock = paths
    path = rollout(root, target)
    tracker = source.CodexUsageTracker(target, THREAD, root, clock)
    append(path, tokens())
    first = tracker.poll()
    path.write_bytes(b"")
    result = tracker.poll(force=True)
    assert result["error"] == "usage-source-truncated"
    assert result["token_status"] == "partial"
    assert result["usage"] == first["usage"]

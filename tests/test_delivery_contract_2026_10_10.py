"""Regression coverage for checked work and retained reading-output delivery."""

import pytest

import deliverables_register as dr
from steward_cockpit import code_jobs as cj
from steward_cockpit import steward_engine as se
from steward_cockpit import steward_routes as sr


@pytest.mark.parametrize("check", ["", " ", "\t\n"])
def test_missing_check_is_rejected_before_coder_selection(tmp_path, monkeypatch, check):
    def must_not_choose(*args, **kwargs):
        pytest.fail("Invalid unchecked work reached coder selection")

    monkeypatch.setattr(cj, "choose_coder", must_not_choose)
    result = cj.start(tmp_path / "campaign", tmp_path / "repo", "Do scoped work", check=check)
    assert result.get("error"), result
    assert "check" in str(result).lower()


def test_oversize_brief_is_rejected_instead_of_truncated(tmp_path, monkeypatch):
    def must_not_choose(*args, **kwargs):
        pytest.fail("An oversized brief reached coder selection")

    monkeypatch.setattr(cj, "choose_coder", must_not_choose)
    brief = "x" * 8000 + "FINAL REQUIREMENT"
    result = cj.start(tmp_path / "campaign", tmp_path / "repo", brief, check="python -V")
    assert result.get("error"), result
    assert any(word in str(result).lower() for word in ("brief", "8000", "8,000"))


@pytest.mark.parametrize(
    ("outputs", "skill", "expected"),
    [(["out/report.pdf"], "", True), (["app.py"], "research", False), ([], "research", False)],
)
def test_reading_work_requires_declared_document_outputs(outputs, skill, expected):
    job = {"outputs": outputs, "skill": skill}
    assert bool(cj.reading_outputs(job)) is expected


def test_coder_prompt_preserves_brief_and_percent_in_artifact_path():
    brief = "Keep the north stars.\n\nUnicode: café — λ.\nFINAL ACCEPTANCE: verify the result."
    job = {
        "repo": "R",
        "branch": "delivery-test",
        "brief": brief,
        "check": ["python", "-c", "pass"],
        "outputs": ["out/100% complete.pdf"],
    }
    prompt = cj.coder_brief(job)
    assert brief in prompt
    assert "out/100% complete.pdf" in prompt
    assert "delivery-test" in prompt


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    cdir = tmp_path / "campaign"
    worktree = tmp_path / "worktree"
    cdir.mkdir()
    worktree.mkdir()
    calls = []
    registered = set()
    receipts = []
    response = {"failure": None}

    def register(*args, **kwargs):
        calls.append((args, kwargs))
        if response["failure"] is not None:
            return dict(response["failure"])
        where = kwargs.get("where", args[2] if len(args) > 2 else "")
        if where in registered:
            return {"written": False, "reason": "dup"}
        registered.add(where)
        return {"written": True}

    def record(text, rid):
        receipts.append((text, rid))
        return True

    monkeypatch.setattr(dr, "register", register)
    monkeypatch.setattr(dr, "project_and_rel", lambda *args, **kwargs: ("p1", "effort"))
    monkeypatch.setattr(se, "_default_record", lambda *args, **kwargs: record)
    monkeypatch.setattr(sr, "get_engine", lambda *args, **kwargs: None)

    def make_job(outputs=None):
        job = {
            "id": "j9",
            "worktree": str(worktree),
            "kept_worktree": str(worktree),
            "files": ["out/report.pdf", "app.py"],
            "unexpected": ["evidence.md"],
            "brief": "PRIVATE_FULL_BRIEF_DO_NOT_ECHO_" * 100,
        }
        if outputs is not None:
            job["outputs"] = outputs
        return job

    def write(relative, data=b"retained output\n"):
        path = worktree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    return {
        "cdir": cdir,
        "worktree": worktree,
        "calls": calls,
        "registered": registered,
        "receipts": receipts,
        "response": response,
        "job": make_job,
        "write": write,
    }


def test_declared_documents_are_copied_without_support_files(delivery):
    d = delivery
    source = d["write"]("out/report.pdf", b"report bytes")
    d["write"]("app.py")
    d["write"]("evidence.md")
    job = d["job"](["out/report.pdf"])

    names = cj.announce_kept(d["cdir"], job)

    target = d["cdir"] / "code-job-outputs" / "j9" / "out" / "report.pdf"
    assert names == ["report.pdf"]
    assert target.read_bytes() == source.read_bytes()
    assert not (target.parents[1] / "app.py").exists()
    assert not (target.parents[1] / "evidence.md").exists()
    assert len(d["registered"]) == 1
    result = job["kept_delivery"]
    assert result["retained_count"] == 2
    assert not result["errors"]
    assert len(result["items"]) == 1
    assert result["items"][0]["registered"] is True
    assert result["items"][0]["sha256"]
    assert result["receipt_id"]


def test_successful_retry_reuses_artifact_and_receipt(delivery):
    d = delivery
    d["write"]("out/report.pdf", b"stable report")
    job = d["job"](["out/report.pdf"])
    cj.announce_kept(d["cdir"], job)
    target = d["cdir"] / "code-job-outputs" / "j9" / "out" / "report.pdf"
    stat_before = target.stat()
    receipt_before = job["kept_delivery"]["receipt_id"]

    assert cj.announce_kept(d["cdir"], job) == ["report.pdf"]

    assert target.read_bytes() == b"stable report"
    assert target.stat().st_mtime_ns == stat_before.st_mtime_ns
    assert len(d["registered"]) == 1
    assert len(d["receipts"]) == 1
    assert job["kept_delivery"]["receipt_id"] == receipt_before
    assert not job["kept_delivery"]["errors"]


def test_existing_different_output_is_never_overwritten(delivery):
    d = delivery
    source = d["write"]("out/report.pdf", b"new report")
    target = d["cdir"] / "code-job-outputs" / "j9" / "out" / "report.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing distinct report")
    job = d["job"](["out/report.pdf"])

    cj.announce_kept(d["cdir"], job)

    assert source.read_bytes() == b"new report"
    assert target.read_bytes() == b"existing distinct report"
    assert job["kept_delivery"]["errors"]
    assert not d["registered"]


def test_registration_refusal_preserves_copy_and_can_recover(delivery):
    d = delivery
    d["write"]("out/report.pdf", b"managed output")
    d["response"]["failure"] = {"written": False, "reason": "managed campaign refusal"}
    job = d["job"](["out/report.pdf"])
    cj.announce_kept(d["cdir"], job)

    target = d["cdir"] / "code-job-outputs" / "j9" / "out" / "report.pdf"
    assert target.read_bytes() == b"managed output"
    assert job["kept_delivery"]["errors"]
    assert not any(item["registered"] for item in job["kept_delivery"]["items"])
    assert not d["registered"]

    d["response"]["failure"] = None
    cj.announce_kept(d["cdir"], job)

    assert len(d["registered"]) == 1
    assert not job["kept_delivery"]["errors"]
    assert all(item["registered"] for item in job["kept_delivery"]["items"])


def test_copy_failure_does_not_block_other_output_or_retry(delivery, monkeypatch):
    d = delivery
    d["write"]("out/first.pdf", b"first")
    d["write"]("out/second.pdf", b"second")
    job = d["job"](["out/first.pdf", "out/second.pdf"])
    job["files"] = list(job["outputs"])
    original = cj._copy_kept
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected copy failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(cj, "_copy_kept", fail_once)
    cj.announce_kept(d["cdir"], job)
    assert job["kept_delivery"]["errors"]
    assert len(d["registered"]) == 1
    assert all((d["worktree"] / name).is_file() for name in job["outputs"])

    cj.announce_kept(d["cdir"], job)
    assert not job["kept_delivery"]["errors"]
    assert len(d["registered"]) == 2
    assert job["kept_delivery"]["retained_count"] == 1


def test_registration_commit_with_lost_acknowledgement_recovers_without_duplicates(delivery, monkeypatch):
    d = delivery
    outputs = ["out/first.pdf", "out/second.pdf"]
    for name in outputs:
        d["write"](name)
    job = d["job"](outputs)
    job["files"] = outputs
    original = dr.register
    failed = False

    def lose_first_acknowledgement(*args, **kwargs):
        nonlocal failed
        result = original(*args, **kwargs)
        if not failed:
            failed = True
            raise OSError("registration committed but acknowledgement was lost")
        return result

    monkeypatch.setattr(dr, "register", lose_first_acknowledgement)
    cj.announce_kept(d["cdir"], job)
    assert job["kept_delivery"]["errors"]
    assert len(d["registered"]) == 2

    cj.announce_kept(d["cdir"], job)

    assert not job["kept_delivery"]["errors"]
    assert len(d["registered"]) == 2
    assert all(item["registered"] for item in job["kept_delivery"]["items"])


@pytest.mark.parametrize(
    "unsafe", ["../outside.pdf", "/outside.pdf", "C:/outside.pdf", "out:stream/report.pdf", "\\\\server\\share\\report.pdf"]
)
def test_unsafe_declared_paths_are_not_registered(delivery, unsafe):
    d = delivery
    job = d["job"]([unsafe])
    job["files"] = [unsafe]
    cj.announce_kept(d["cdir"], job)
    assert job["kept_delivery"]["errors"]
    assert not d["calls"]
    assert not any(item["registered"] for item in job["kept_delivery"]["items"])


@pytest.mark.parametrize("side", ["source", "destination"])
def test_directory_link_escape_is_rejected(delivery, tmp_path, side):
    d = delivery
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "report.pdf"
    protected.write_bytes(b"outside must stay untouched")
    job = d["job"](["out/report.pdf"])
    if side == "source":
        link = d["worktree"] / "out"
    else:
        d["write"]("out/report.pdf", b"legitimate source")
        link = d["cdir"] / "code-job-outputs" / "j9" / "out"
        link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlink creation unavailable: {exc}")

    cj.announce_kept(d["cdir"], job)

    assert protected.read_bytes() == b"outside must stay untouched"
    assert job["kept_delivery"]["errors"]
    assert not d["registered"]


def test_receipt_is_one_bounded_message_for_multiple_artifacts(delivery):
    d = delivery
    outputs = ["out/report.pdf", "out/notes.md"]
    for name in outputs:
        d["write"](name)
    job = d["job"](outputs)
    job["files"] = outputs
    cj.announce_kept(d["cdir"], job)

    assert len(d["receipts"]) == 1
    text, rid = d["receipts"][0]
    assert "report.pdf" in text and "notes.md" in text
    assert "PRIVATE_FULL_BRIEF_DO_NOT_ECHO_" not in text
    assert len(text) < 1800
    assert rid == job["kept_delivery"]["receipt_id"]


def test_legacy_outputs_keep_pdf_first_and_six_item_cap(delivery):
    d = delivery
    names = [f"notes-{index}.md" for index in range(7)] + ["report.pdf"]
    for name in names:
        d["write"](name)
    job = d["job"]()
    job["files"] = names
    job["unexpected"] = []

    announced = cj.announce_kept(d["cdir"], job)

    assert len(announced) == 6
    assert announced[0] == "report.pdf"
    assert len(d["registered"]) == 6

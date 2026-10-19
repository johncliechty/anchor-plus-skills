"""S7 of the slim plan (night 2026-10-10), as changed on 2026-10-09 ("route Foreman through the code-job path"): the
steward SIZES the work (small = a code job; a feature = a plan of waves John approves, built by a Foreman code job;
multi-part = --profile standard, on his word). Foreman starts from Anchor only as a code job, slim unless a profile is
named. Crucible keeps its hold (ANCHOR_FOREMAN_CRUCIBLE_HOLD=0 lifts it)."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, skill_jobs  # noqa: E402


def test_the_hold_stays_by_default_and_lifts_only_by_hand(monkeypatch):
    # final review 2026-10-10 (BLOCKER): Foreman as a skill job would write the project outside the protected
    # code-job lifecycle - the hold stays until it runs through that lifecycle
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    assert code_jobs.foreman_crucible_held() is True
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert code_jobs.foreman_crucible_held() is False


def test_foreman_from_anchor_runs_slim_unless_a_profile_is_named():
    # 2026-10-09: Foreman starts from Anchor only as a code job, slim unless the steward names standard
    import inspect
    assert inspect.signature(code_jobs.start).parameters["profile"].default == "slim"
    assert not hasattr(skill_jobs, "with_profile")


def test_the_steward_sizes_work_and_exposes_only_the_proved_slim_path(monkeypatch):
    import steward_cockpit.steward_engine as se
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    se = importlib.reload(se)
    for text in (se.CONTRACT, se.EFFORT_DUTY, se.EFFORT_RULES):
        assert "SIZE THE WORK" in text and "Crucible slim" in text
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    se = importlib.reload(se)
    for text in (se.CONTRACT, se.EFFORT_DUTY, se.EFFORT_RULES):
        assert "SIZE THE WORK" in text and "producing a plan does not approve it" in text
    assert "--worker foreman" in se.SIZE_OR_HOLD and "run-live.mjs" not in se.SIZE_OR_HOLD
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    importlib.reload(se)


def test_only_installed_slim_entry_point_gets_the_managed_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(tmp_path))
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    folder = tmp_path / "crucible" / "bin"
    folder.mkdir(parents=True)
    for name in ("slim.mjs", "enhanced.mjs"):
        (folder / name).write_text("// fixture\n", encoding="utf-8")
    assert skill_jobs.validate(["node", str(folder / "slim.mjs")])[0]
    assert not skill_jobs.validate(["node", str(folder / "enhanced.mjs")])[0]
    other = tmp_path / "other" / "crucible" / "bin" / "slim.mjs"
    other.parent.mkdir(parents=True)
    other.write_text("// fixture\n", encoding="utf-8")
    assert not skill_jobs.validate(["node", str(other)])[0]

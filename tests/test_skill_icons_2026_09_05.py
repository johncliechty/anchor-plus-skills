"""Skill icons wherever a skill is named (John, 2026-09-05): the project list, the plan outline, the top of
every report a skill creates, and the workbench skill rail. One client map (static/skill-icons.js), one
server map (steward_routes.SKILL_ICONS / report_viewer.SKILL_ICON_FILES), small hooks per surface."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import report_viewer as rv  # noqa: E402
from steward_cockpit import steward_routes as routes  # noqa: E402


def test_every_listed_skill_has_a_brand_mark_and_the_file_exists():
    for name in routes.SKILLS:
        fn = routes.skill_icon(name)
        assert fn != routes.SKILL_ICON_FALLBACK, name
        assert (ROOT / "vendor" / "brand" / fn).is_file(), fn
    assert routes.skill_icon("no-such-skill") == routes.SKILL_ICON_FALLBACK
    assert routes.skill_icon("GANDALF") == "gandalf-icon.jpg"          # case-insensitive


def test_report_page_carries_the_producing_skills_mark_once():
    page = rv.reader_html("# A read\n\nBottom line.", "A read", skill="Gandalf")
    assert page.count('class="skill-mark"') == 1
    assert "/vendor/brand/gandalf-icon.jpg" in page and "a Gandalf report" in page
    assert 'class="skill-mark"' not in rv.reader_html("# plain", "plain")
    assert rv.skill_from_path("gandalf/run-1788653387045/report.md") == "gandalf"
    assert rv.skill_from_path(".anchor/projects/x/research/job-1/report.md") == "researchPrime"
    assert rv.skill_from_path("reports/ECON588.md") is None
    # reports that already exist: the file name or the first heading names the skill
    assert rv.skill_from_path("ideation/ROUND2-JUMPER-CHECK.md") == "jumper"
    assert rv.skill_from_path("notes/read.md", "# Gandalf executive summary\n\n- x") == "gandalf"
    assert rv.skill_from_path("notes/plain.md", "# Week 1\n") is None


def test_the_client_map_and_the_four_surfaces_are_wired():
    js = (ROOT / "steward_cockpit" / "static" / "skill-icons.js").read_text(encoding="utf-8")
    for name in routes.SKILLS:
        assert name.lower() in js.lower(), name
    assert "fromPath" in js and "decorate" in js
    shared = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "SkillIcons.img((st.commissioned_as" in shared            # the plan outline
    cockpit = (ROOT / "steward_cockpit" / "static" / "cockpit.html").read_text(encoding="utf-8")
    assert "SkillIcons.img(name, 18)" in cockpit                       # the workbench skill rail
    assert '<script src="/static/skill-icons.js">' in cockpit
    report = (ROOT / "steward_cockpit" / "static" / "report.html").read_text(encoding="utf-8")
    assert "SkillIcons.fromPath(path)" in report                      # the cockpit report top
    v1 = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    assert '<script src="/static/skill-icons.js">' in v1
    gui = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert "skill=_rv.skill_from_path(rel, md_text)" in gui           # the Anchor report page
    assert "lane_mark" in gui and "gandalf-icon.jpg" in gui           # the project list line


def test_skills_verb_carries_icons():
    out, status = routes.handle_get(str(ROOT), "skills", {})
    assert status == 200 and out["skills"] == routes.SKILLS
    assert out["icons"]["Gandalf"] == "gandalf-icon.jpg"

"""報告管線端到端測試（不動用 LLM / AWS）。"""

from __future__ import annotations

import pytest

from waagent.report.pipeline import Narrative, PillarNarrative, render_reports
from waagent.report.userrules import load_user_templates
from waagent.scan import snapshot
from waagent.scan.models import Finding, Severity
from waagent.wa.pillars import Pillar


@pytest.fixture
def run_with_data(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "RUNS_DIR", tmp_path / "runs")
    run_id = "test-run"
    findings = [
        Finding(
            id="SEC-001-abc",
            rule_id="SEC-001",
            pillar=Pillar.SECURITY,
            severity=Severity.CRITICAL,
            title="SG 對全網開放 SSH",
            resource="sg-123",
            region="ap-northeast-1",
            one_line_evidence="0.0.0.0/0 port 22",
        )
    ]
    snapshot.write_findings(run_id, findings)
    snapshot.write_digest(run_id, snapshot.build_digest(
        run_id, findings, account_id="123456789012", regions=["ap-northeast-1"],
        resource_counts={"EC2 instances": 3},
    ))
    return run_id


def _narrative() -> Narrative:
    return Narrative(
        executive_summary="整體狀況尚可，安全性需要立即處理。",
        per_pillar={
            "security": PillarNarrative(
                assessment="有一項重大風險。",
                risks=["SSH 對全網開放"],
                remediations=["限縮 SG 來源"],
            )
        },
        next_steps=["修正 sg-123"],
    )


def test_render_builtin_templates(run_with_data, tmp_path):
    user = load_user_templates(None)
    md, html = render_reports(run_with_data, _narrative(), user, tmp_path / "out")
    md_text = md.read_text(encoding="utf-8")
    html_text = html.read_text(encoding="utf-8")

    assert "執行摘要" in md_text
    assert "sg-123" in md_text
    assert "<svg" in html_text  # 圖表已內嵌
    assert "cdn" not in html_text.lower()  # 無外部資源
    assert "SSH 對全網開放" in html_text
    # narrative 已存回 run 目錄，可重渲染
    assert (snapshot.run_dir(run_with_data) / "narrative.json").is_file()


def test_user_template_override(run_with_data, tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "report.md.j2").write_text("CUSTOM {{ digest.account_id }}", encoding="utf-8")
    (tdir / "style.rules.md").write_text("報告要用敬語。", encoding="utf-8")

    user = load_user_templates(tdir)
    assert "敬語" in user.rules_text
    md, _html = render_reports(run_with_data, _narrative(), user, tmp_path / "out")
    assert md.read_text(encoding="utf-8") == "CUSTOM 123456789012"

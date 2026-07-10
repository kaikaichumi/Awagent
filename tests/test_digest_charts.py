"""digest 建構與 SVG 圖表測試。"""

from __future__ import annotations

from waagent.report import charts
from waagent.scan.models import Finding, Severity
from waagent.scan.snapshot import DIGEST_MAX_FINDINGS, build_digest
from waagent.wa.pillars import Pillar


def _finding(i: int, severity: Severity, pillar: Pillar = Pillar.SECURITY) -> Finding:
    return Finding(
        id=f"X-{i}",
        rule_id="X",
        pillar=pillar,
        severity=severity,
        title="t",
        resource=f"res-{i}",
        one_line_evidence="e",
    )


def test_digest_sorted_by_severity_and_truncated():
    findings = [_finding(i, Severity.LOW) for i in range(DIGEST_MAX_FINDINGS + 10)]
    findings.append(_finding(9999, Severity.CRITICAL))
    digest = build_digest("r", findings)
    assert digest.truncated
    assert len(digest.findings) == DIGEST_MAX_FINDINGS
    assert digest.findings[0].severity == Severity.CRITICAL  # 嚴重的排最前、不被截掉


def test_digest_pillar_stats():
    digest = build_digest("r", [
        _finding(1, Severity.HIGH, Pillar.SECURITY),
        _finding(2, Severity.HIGH, Pillar.SECURITY),
        _finding(3, Severity.LOW, Pillar.COST_OPTIMIZATION),
    ])
    assert digest.pillar_stats["security"].total == 2
    assert digest.pillar_stats["security"].by_severity["high"] == 2
    assert digest.pillar_stats["costOptimization"].total == 1


def test_charts_render_valid_svg():
    digest = build_digest("r", [
        _finding(1, Severity.CRITICAL, Pillar.SECURITY),
        _finding(2, Severity.MEDIUM, Pillar.RELIABILITY),
    ])
    for svg in (charts.radar_chart(digest), charts.pillar_bar_chart(digest), charts.severity_donut(digest)):
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert "http://www.w3.org/2000/svg" in svg


def test_charts_empty_digest():
    digest = build_digest("r", [])
    assert "<svg" in charts.severity_donut(digest)
    assert "<svg" in charts.radar_chart(digest)

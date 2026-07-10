"""run diff 與長期記憶測試。"""

from __future__ import annotations

import pytest

from waagent import memory
from waagent.scan import snapshot
from waagent.scan.diff import compare_runs, diff_summary_for_llm
from waagent.scan.models import Finding, Severity
from waagent.wa.pillars import Pillar


def _finding(rule_id: str, resource: str, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        id=f"{rule_id}-{resource}",
        rule_id=rule_id,
        pillar=Pillar.SECURITY,
        severity=severity,
        title=f"title {rule_id}",
        resource=resource,
        one_line_evidence="e",
    )


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "RUNS_DIR", tmp_path / "runs")
    return snapshot.RUNS_DIR


def test_compare_runs(runs_dir):
    snapshot.write_findings("old", [
        _finding("SEC-001", "sg-1", Severity.CRITICAL),
        _finding("COST-001", "vol-1", Severity.MEDIUM),
    ])
    snapshot.write_findings("new", [
        _finding("COST-001", "vol-1", Severity.MEDIUM),  # 未變
        _finding("SEC-006", "user-a", Severity.HIGH),  # 新增
    ])
    diff = compare_runs("old", "new")
    assert [f.rule_id for f in diff.fixed] == ["SEC-001"]
    assert [f.rule_id for f in diff.added] == ["SEC-006"]
    assert diff.unchanged_count == 1

    summary = diff_summary_for_llm(diff)
    assert "已修復 1" in summary
    assert "新增 1" in summary
    assert "sg-1" in summary


def test_memory_append_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_PATH", tmp_path / "memory.md")
    assert memory.read_memory() == ""
    assert memory.memory_for_prompt() == ""

    memory.append_memory("AWS 帳號慣例", "prod 都在 ap-northeast-1，tag 規範是 Owner/Env。")
    memory.append_memory("已知問題", "web-sg 開 SSH 是跳板機用，已核可。")

    text = memory.read_memory()
    assert "## AWS 帳號慣例" in text
    assert "## 已知問題" in text
    assert "跳板機" in memory.memory_for_prompt()


def test_memory_prompt_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_PATH", tmp_path / "memory.md")
    memory.append_memory("大量內容", "x" * 20_000)
    prompt = memory.memory_for_prompt()
    assert len(prompt) < 17_000
    assert "已截斷" in prompt


def test_aws_describe_rejects_write():
    from waagent.config import Config
    from waagent.tools.impl import tool_aws_describe

    result = tool_aws_describe(Config(), "ec2", "terminate_instances", "{}")
    assert result.startswith("拒絕")
    result = tool_aws_describe(Config(), "s3", "delete_bucket", "{}")
    assert result.startswith("拒絕")

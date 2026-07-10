"""兩次掃描 run 的 findings 差異：新增 / 已修復 / 未變。

finding id = 規則 id + region:resource 的 hash，跨 run 穩定，可直接以 id 比對。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from waagent.scan import snapshot
from waagent.scan.models import SEVERITY_ORDER, Finding


class RunDiff(BaseModel):
    old_run: str
    new_run: str
    added: list[Finding] = Field(default_factory=list)
    fixed: list[Finding] = Field(default_factory=list)
    unchanged_count: int = 0


def compare_runs(old_run: str, new_run: str) -> RunDiff:
    old = {f.id: f for f in snapshot.read_findings(old_run)}
    new = {f.id: f for f in snapshot.read_findings(new_run)}

    def _rank(f: Finding):
        return SEVERITY_ORDER.index(f.severity)

    return RunDiff(
        old_run=old_run,
        new_run=new_run,
        added=sorted((new[i] for i in new.keys() - old.keys()), key=_rank),
        fixed=sorted((old[i] for i in old.keys() - new.keys()), key=_rank),
        unchanged_count=len(old.keys() & new.keys()),
    )


def diff_summary_for_llm(diff: RunDiff) -> str:
    """給 agent 的精簡文字版。"""
    lines = [
        f"比較 {diff.old_run} -> {diff.new_run}：",
        f"已修復 {len(diff.fixed)} 項、新增 {len(diff.added)} 項、未變 {diff.unchanged_count} 項。",
    ]
    if diff.fixed:
        lines.append("已修復：")
        lines += [f"- [{f.severity.value}] {f.title}（{f.resource}）" for f in diff.fixed[:40]]
    if diff.added:
        lines.append("新增：")
        lines += [
            f"- [{f.severity.value}] {f.title}（{f.resource}）{f.one_line_evidence}"
            for f in diff.added[:40]
        ]
    return "\n".join(lines)

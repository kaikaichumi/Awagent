"""報告管線：digest + findings + LLM narrative → report.md + report.html。

排版與圖表全部決定性（Jinja2 + charts.py）；LLM 只提供 narrative JSON。
narrative.json 一併存檔，改模板可重渲染、不必重跑 LLM。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from waagent.report import charts
from waagent.report.userrules import UserTemplates
from waagent.scan import snapshot
from waagent.scan.models import Digest, Finding
from waagent.wa.pillars import PILLAR_NAMES_EN, PILLAR_NAMES_ZH, Pillar

BUILTIN_DIR = Path(__file__).parent / "templates_builtin"


class PillarNarrative(BaseModel):
    assessment: str = ""
    risks: list[str] = Field(default_factory=list)
    remediations: list[str] = Field(default_factory=list)


class Narrative(BaseModel):
    """wa-review agent 必須輸出的結構。"""

    title: str = "AWS Well-Architected 評估報告"
    executive_summary: str = ""
    per_pillar: dict[str, PillarNarrative] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)


def narrative_json_schema() -> dict:
    return Narrative.model_json_schema()


def _make_env(user: UserTemplates) -> Environment:
    search_paths = [str(BUILTIN_DIR)]
    if user.source_dir and Path(user.source_dir).is_dir():
        search_paths.insert(0, user.source_dir)
    return Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=select_autoescape(["html", "j2"]),
        keep_trailing_newline=True,
    )


def render_reports(
    run_id: str,
    narrative: Narrative,
    user: UserTemplates,
    output_dir: str | Path = ".",
) -> tuple[Path, Path]:
    digest = snapshot.read_digest(run_id)
    if digest is None:
        raise FileNotFoundError(f"找不到 run {run_id} 的 digest；請先執行掃描")
    findings = snapshot.read_findings(run_id)

    env = _make_env(user)
    context = _build_context(digest, findings, narrative)

    out = Path(output_dir or ".")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")

    md_name = user.md_template.name if user.md_template else "report.md.j2"
    html_name = user.html_template.name if user.html_template else "report.html.j2"

    md_path = out / f"wa-report-{stamp}.md"
    html_path = out / f"wa-report-{stamp}.html"
    md_path.write_text(env.get_template(md_name).render(**context), encoding="utf-8")
    html_path.write_text(env.get_template(html_name).render(**context), encoding="utf-8")

    # narrative 存回 run 目錄供重渲染
    (snapshot.run_dir(run_id) / "narrative.json").write_text(
        narrative.model_dump_json(indent=1), encoding="utf-8"
    )
    return md_path, html_path


def _build_context(digest: Digest, findings: list[Finding], narrative: Narrative) -> dict:
    findings_by_pillar: dict[str, list[Finding]] = {}
    for f in findings:
        findings_by_pillar.setdefault(f.pillar.value, []).append(f)

    pillar_rows = []
    scores = charts.pillar_risk_scores(digest)
    for p in Pillar:
        stats = digest.pillar_stats.get(p.value)
        pillar_rows.append(
            {
                "id": p.value,
                "name_zh": PILLAR_NAMES_ZH[p],
                "name_en": PILLAR_NAMES_EN[p],
                "total": stats.total if stats else 0,
                "by_severity": stats.by_severity if stats else {},
                "risk_score": scores[p],
                "narrative": narrative.per_pillar.get(
                    p.value, PillarNarrative()
                ),
                "findings": sorted(
                    findings_by_pillar.get(p.value, []),
                    key=lambda f: ["critical", "high", "medium", "low", "info"].index(
                        f.severity.value
                    ),
                ),
            }
        )

    return {
        "narrative": narrative,
        "digest": digest,
        "pillars": pillar_rows,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "radar_svg": charts.radar_chart(digest),
        "bar_svg": charts.pillar_bar_chart(digest),
        "donut_svg": charts.severity_donut(digest),
        "severity_colors": charts.SEVERITY_COLORS,
    }

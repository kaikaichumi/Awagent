"""掃描資料契約：raw → Finding → Digest 三層中的後兩層 schema。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from waagent.wa.pillars import Pillar


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


class Finding(BaseModel):
    """checks engine 產出的單條發現。digest 只帶精簡欄位，evidence 留在 findings.json。"""

    id: str  # 規則 id + 資源 hash，例如 "SEC-001-a1b2c3"
    rule_id: str
    pillar: Pillar
    severity: Severity
    title: str
    resource: str  # ARN 或資源識別（digest 內會截短）
    region: str = ""
    one_line_evidence: str  # ≤ ~80 tokens，digest 用
    evidence: dict = Field(default_factory=dict)  # 完整證據，get_finding_detail 才回傳
    remediation_hint: str = ""
    wa_question_id: str = ""  # 對應 WA lens question（可空）


class PillarStats(BaseModel):
    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)


class DigestFinding(BaseModel):
    id: str
    pillar: Pillar
    severity: Severity
    title: str
    resource: str
    evidence: str


class Digest(BaseModel):
    """給 LLM 的精簡摘要，目標整份 < 8K tokens。"""

    run_id: str
    account_id: str = ""
    regions: list[str] = Field(default_factory=list)
    scanned_at: str = ""
    resource_counts: dict[str, int] = Field(default_factory=dict)
    pillar_stats: dict[str, PillarStats] = Field(default_factory=dict)
    findings: list[DigestFinding] = Field(default_factory=list)
    truncated: bool = False  # findings 超過上限被截斷時為 True
    collector_errors: list[str] = Field(default_factory=list)


class RunMeta(BaseModel):
    run_id: str
    account_id: str = ""
    regions: list[str] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    services: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

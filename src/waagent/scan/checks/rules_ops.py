"""Operational Excellence / Performance / Sustainability 規則。"""

from __future__ import annotations

from waagent.scan.checks.engine import rule
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar

_REQUIRED_TAGS = {"Name"}


@rule(
    id="OPS-001",
    service="ec2",
    pillar=Pillar.OPERATIONAL_EXCELLENCE,
    severity=Severity.LOW,
    title="EC2 執行個體缺少基本標籤",
    remediation_hint="制定 tagging policy（Name/Owner/Env），以利歸屬與自動化。",
    wa_question_id="ops-tagging",
)
def missing_tags(data: dict):
    for inst in data.get("instances", []):
        tags = {t["Key"] for t in inst.get("Tags", [])}
        missing = _REQUIRED_TAGS - tags
        if missing:
            yield (inst["InstanceId"], f"缺少標籤: {', '.join(sorted(missing))}", {})


@rule(
    id="OPS-002",
    service="cloudwatch",
    pillar=Pillar.OPERATIONAL_EXCELLENCE,
    severity=Severity.LOW,
    title="CloudWatch log group 未設定保留期",
    remediation_hint="設定 retention（如 90 天），避免日誌無限期累積。",
    wa_question_id="ops-observability",
)
def log_no_retention(data: dict):
    for lg in data.get("log_groups", []):
        if "retentionInDays" not in lg:
            yield (lg.get("logGroupName", "?"), "永久保留（未設定 retention）", {})


@rule(
    id="PERF-001",
    service="ec2",
    pillar=Pillar.PERFORMANCE,
    severity=Severity.MEDIUM,
    title="EC2 未啟用 detailed monitoring",
    remediation_hint="對關鍵工作負載啟用 1 分鐘粒度監控，或以 CloudWatch agent 補齊。",
    wa_question_id="perf-monitor-instances",
)
def no_detailed_monitoring(data: dict):
    for inst in data.get("instances", []):
        if (
            inst.get("State", {}).get("Name") == "running"
            and inst.get("Monitoring", {}).get("State") == "disabled"
        ):
            yield (inst["InstanceId"], "Monitoring = disabled（5 分鐘粒度）", {})


@rule(
    id="SUS-001",
    service="ec2",
    pillar=Pillar.SUSTAINABILITY,
    severity=Severity.INFO,
    title="停止中的執行個體長期佔用 EBS",
    remediation_hint="長期 stopped 的執行個體評估以 AMI 封存後終止。",
    wa_question_id="sus-hardware-patterns",
)
def stopped_instances(data: dict):
    for inst in data.get("instances", []):
        if inst.get("State", {}).get("Name") == "stopped":
            yield (inst["InstanceId"], "instance 處於 stopped 狀態", {})

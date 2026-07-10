"""Reliability pillar 規則。"""

from __future__ import annotations

from waagent.scan.checks.engine import rule
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar


@rule(
    id="REL-001",
    service="rds",
    pillar=Pillar.RELIABILITY,
    severity=Severity.HIGH,
    title="RDS 執行個體未啟用 Multi-AZ",
    remediation_hint="正式環境資料庫啟用 Multi-AZ 部署以支援自動容錯移轉。",
    wa_question_id="rel-fault-isolation",
)
def rds_single_az(data: dict):
    for db in data.get("db_instances", []):
        if not db.get("MultiAZ") and not db.get("DBClusterIdentifier"):
            yield (db["DBInstanceIdentifier"], f"engine={db.get('Engine')} 單 AZ 部署", {})


@rule(
    id="REL-002",
    service="rds",
    pillar=Pillar.RELIABILITY,
    severity=Severity.HIGH,
    title="RDS 自動備份保留期過短",
    remediation_hint="BackupRetentionPeriod 至少 7 天，並考慮 AWS Backup 集中管理。",
    wa_question_id="rel-backing-up-data",
)
def rds_short_backup(data: dict):
    for db in data.get("db_instances", []):
        retention = db.get("BackupRetentionPeriod", 0)
        if retention < 7:
            yield (
                db["DBInstanceIdentifier"],
                f"備份保留 {retention} 天（含 0 = 停用）",
                {"retention_days": retention},
            )


@rule(
    id="REL-003",
    service="backup",
    pillar=Pillar.RELIABILITY,
    severity=Severity.MEDIUM,
    title="區域內沒有任何 AWS Backup 計畫",
    remediation_hint="建立集中式 backup plan 覆蓋 EC2/EBS/RDS 等資源。",
    wa_question_id="rel-backing-up-data",
)
def no_backup_plan(data: dict):
    if not data.get("plans"):
        yield ("region", "list_backup_plans 為空", {})


@rule(
    id="REL-004",
    service="s3",
    pillar=Pillar.RELIABILITY,
    severity=Severity.LOW,
    title="S3 bucket 未啟用版本控制",
    remediation_hint="對重要資料 bucket 啟用 Versioning 防止誤刪覆寫。",
    wa_question_id="rel-backing-up-data",
)
def s3_no_versioning(data: dict):
    for b in data.get("buckets", []):
        versioning = b.get("Versioning") or {}
        if versioning.get("Status") != "Enabled":
            yield (b["Name"], "Versioning 未啟用", {})


@rule(
    id="REL-005",
    service="cloudwatch",
    pillar=Pillar.RELIABILITY,
    severity=Severity.MEDIUM,
    title="區域內沒有任何 CloudWatch 告警",
    remediation_hint="至少為關鍵資源（CPU、可用性、錯誤率）建立告警與通知。",
    wa_question_id="rel-monitor-resources",
)
def no_alarms(data: dict):
    if not data.get("alarms"):
        yield ("region", "describe_alarms 為空", {})


@rule(
    id="REL-006",
    service="cloudwatch",
    pillar=Pillar.RELIABILITY,
    severity=Severity.LOW,
    title="CloudWatch 告警沒有任何動作",
    remediation_hint="為告警綁定 SNS 通知或自動化動作，否則形同虛設。",
    wa_question_id="rel-monitor-resources",
)
def alarm_no_action(data: dict):
    for alarm in data.get("alarms", []):
        if not alarm.get("AlarmActions") and not alarm.get("OKActions"):
            yield (alarm["AlarmName"], "AlarmActions 為空", {})

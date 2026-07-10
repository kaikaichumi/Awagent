"""Cost Optimization pillar 規則。"""

from __future__ import annotations

from waagent.scan.checks.engine import rule
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar

_PREV_GEN_PREFIXES = ("t2.", "m3.", "m4.", "c3.", "c4.", "r3.", "r4.", "i2.")


@rule(
    id="COST-001",
    service="ec2",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.MEDIUM,
    title="未掛載的 EBS volume",
    remediation_hint="確認後刪除或建快照封存，停止閒置計費。",
    wa_question_id="cost-decommissioning-resources",
)
def unattached_volumes(data: dict):
    for vol in data.get("volumes", []):
        if vol.get("State") == "available":
            yield (vol["VolumeId"], f"{vol.get('Size', '?')}GiB 未掛載", {})


@rule(
    id="COST-002",
    service="ec2",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.LOW,
    title="未關聯的 Elastic IP",
    remediation_hint="釋放未使用的 EIP（未關聯時持續計費）。",
    wa_question_id="cost-decommissioning-resources",
)
def unassociated_eips(data: dict):
    for addr in data.get("addresses", []):
        if not addr.get("AssociationId") and not addr.get("InstanceId"):
            yield (addr.get("PublicIp", addr.get("AllocationId", "?")), "EIP 未關聯任何資源", {})


@rule(
    id="COST-003",
    service="ec2",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.LOW,
    title="使用前代 EC2 執行個體類型",
    remediation_hint="升級到現行世代（如 t3/m7/c7/r7），性價比更高。",
    wa_question_id="cost-evaluate-cost-new-services",
)
def previous_gen_instances(data: dict):
    for inst in data.get("instances", []):
        itype = inst.get("InstanceType", "")
        if itype.startswith(_PREV_GEN_PREFIXES) and inst.get("State", {}).get("Name") == "running":
            yield (inst["InstanceId"], f"instance type {itype}", {})


@rule(
    id="COST-004",
    service="ec2",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.LOW,
    title="gp2 volume 可升級為 gp3",
    remediation_hint="gp3 較 gp2 便宜約 20% 且效能可獨立調整，線上即可轉換。",
    wa_question_id="cost-evaluate-cost-new-services",
)
def gp2_volumes(data: dict):
    for vol in data.get("volumes", []):
        if vol.get("VolumeType") == "gp2":
            yield (vol["VolumeId"], f"{vol.get('Size', '?')}GiB gp2", {})


@rule(
    id="COST-005",
    service="s3",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.LOW,
    title="S3 bucket 沒有生命週期規則",
    remediation_hint="設定 lifecycle 轉冷儲存/過期刪除，控制儲存成本。",
    wa_question_id="cost-manage-demand-resources",
)
def s3_no_lifecycle(data: dict):
    for b in data.get("buckets", []):
        if b.get("Lifecycle") is None:
            yield (b["Name"], "無 lifecycle 規則", {})

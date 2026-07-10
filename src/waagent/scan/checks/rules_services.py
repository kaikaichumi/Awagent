"""擴充服務規則：Lambda / ELB / DynamoDB / Trusted Advisor / Cost。"""

from __future__ import annotations

from waagent.scan.checks.engine import rule
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar

# --- Lambda -----------------------------------------------------------------

_OLD_RUNTIMES = {
    "python3.8",
    "python3.9",
    "nodejs14.x",
    "nodejs16.x",
    "java8",
    "go1.x",
    "dotnet6",
}
_OLD_RUNTIME_PREFIXES = ("python2", "nodejs12")


@rule(
    id="PERF-101",
    service="lambda",
    pillar=Pillar.PERFORMANCE,
    severity=Severity.MEDIUM,
    title="Lambda 使用過舊 runtime",
    remediation_hint="升級至現行支援的 runtime 版本，避免安全更新中斷、效能落後或即將停止支援。",
    wa_question_id="perf-selection",
)
def lambda_old_runtime(data: dict):
    for fn in data.get("functions", []):
        runtime = fn.get("Runtime", "")
        if runtime in _OLD_RUNTIMES or runtime.startswith(_OLD_RUNTIME_PREFIXES):
            yield (fn.get("FunctionName", "?"), f"runtime={runtime}", {})


@rule(
    id="OPS-101",
    service="lambda",
    pillar=Pillar.OPERATIONAL_EXCELLENCE,
    severity=Severity.LOW,
    title="Lambda 缺少 DLQ 設定",
    remediation_hint="設定 Dead Letter Queue（SQS/SNS）或 reserved concurrency，避免非同步呼叫失敗時事件遺失。",
    wa_question_id="ops-workload-health",
)
def lambda_no_dlq(data: dict):
    for fn in data.get("functions", []):
        if "DeadLetterConfig" not in fn:
            yield (fn.get("FunctionName", "?"), "未設定 DeadLetterConfig", {})


# --- ELB ----------------------------------------------------------------------

@rule(
    id="SEC-101",
    service="elb",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="Load balancer 只有 HTTP listener",
    remediation_hint="新增 HTTPS listener 並附掛憑證，或設定將 HTTP 流量導向 443。",
    wa_question_id="sec-network-protection",
)
def elb_http_only(data: dict):
    for lb in data.get("load_balancers", []):
        listeners = lb.get("Listeners")
        if not isinstance(listeners, list):
            continue
        protocols = {ls.get("Protocol") for ls in listeners}
        if "HTTP" in protocols and "HTTPS" not in protocols:
            name = lb.get("LoadBalancerName", lb.get("LoadBalancerArn", "?"))
            yield (name, "僅設定 HTTP listener，無 HTTPS", {})


@rule(
    id="REL-101",
    service="elb",
    pillar=Pillar.RELIABILITY,
    severity=Severity.MEDIUM,
    title="Load balancer 只跨單一 AZ",
    remediation_hint="至少橫跨 2 個可用區，避免單一 AZ 故障時服務中斷。",
    wa_question_id="rel-fault-isolation",
)
def elb_single_az(data: dict):
    for lb in data.get("load_balancers", []):
        azs = lb.get("AvailabilityZones", [])
        if len(azs) < 2:
            name = lb.get("LoadBalancerName", lb.get("LoadBalancerArn", "?"))
            yield (name, f"僅橫跨 {len(azs)} 個可用區", {})


# --- DynamoDB -------------------------------------------------------------------

@rule(
    id="REL-102",
    service="dynamodb",
    pillar=Pillar.RELIABILITY,
    severity=Severity.MEDIUM,
    title="DynamoDB 未啟用 PITR",
    remediation_hint="啟用 Point-in-Time Recovery，避免誤刪/誤寫資料無法復原。",
    wa_question_id="rel-backing-up-data",
)
def dynamodb_no_pitr(data: dict):
    for table in data.get("tables", []):
        backups = table.get("ContinuousBackups") or {}
        status = (
            backups.get("ContinuousBackupsDescription", {})
            .get("PointInTimeRecoveryDescription", {})
            .get("PointInTimeRecoveryStatus")
        )
        if status != "ENABLED":
            yield (table.get("TableName", "?"), f"PITR status={status}", {})


@rule(
    id="SEC-102",
    service="dynamodb",
    pillar=Pillar.SECURITY,
    severity=Severity.LOW,
    title="DynamoDB 未使用 KMS 加密",
    remediation_hint="改用客戶管理或 AWS 管理的 KMS key 加密（SSEType=KMS），取得金鑰存取控管與稽核紀錄。",
    wa_question_id="sec-data-rest",
)
def dynamodb_no_kms(data: dict):
    for table in data.get("tables", []):
        sse = table.get("SSEDescription")
        if not sse or sse.get("Status") != "ENABLED":
            yield (table.get("TableName", "?"), "未啟用 KMS 加密（僅有 AWS owned key 預設加密）", {})


# --- Trusted Advisor --------------------------------------------------------

# pillar 為規則靜態屬性，無法依 category 動態切換，因此依類別拆成三條獨立規則。


@rule(
    id="TA-101",
    service="trusted_advisor",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="Trusted Advisor 安全性檢查為 error",
    remediation_hint="依 Trusted Advisor 建議立即處理，多屬公開存取、憑證或金鑰外洩等高風險項目。",
    wa_question_id="sec-detection",
)
def ta_security_error(data: dict):
    if not data.get("available"):
        return
    for check in data.get("checks", []):
        if check.get("category") == "security" and check.get("status") == "error":
            yield (
                check.get("name", "?"),
                f"flagged_resources={check.get('flagged_resources_count', 0)}",
                {"check": check},
            )


@rule(
    id="TA-102",
    service="trusted_advisor",
    pillar=Pillar.RELIABILITY,
    severity=Severity.MEDIUM,
    title="Trusted Advisor 容錯能力檢查為 error",
    remediation_hint="檢視 fault tolerance 類別建議（如 Multi-AZ、備份、服務配額餘裕），修正高風險項目。",
    wa_question_id="rel-fault-isolation",
)
def ta_fault_tolerance_error(data: dict):
    if not data.get("available"):
        return
    for check in data.get("checks", []):
        if check.get("category") == "fault_tolerance" and check.get("status") == "error":
            yield (
                check.get("name", "?"),
                f"flagged_resources={check.get('flagged_resources_count', 0)}",
                {"check": check},
            )


@rule(
    id="TA-103",
    service="trusted_advisor",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.MEDIUM,
    title="Trusted Advisor 成本最佳化檢查為 error",
    remediation_hint="檢視 cost optimizing 類別建議（如閒置資源、Reserved Instance/Savings Plan 使用率）。",
    wa_question_id="cost-optimize-over-time",
)
def ta_cost_error(data: dict):
    if not data.get("available"):
        return
    for check in data.get("checks", []):
        if check.get("category") == "cost_optimizing" and check.get("status") == "error":
            yield (
                check.get("name", "?"),
                f"flagged_resources={check.get('flagged_resources_count', 0)}",
                {"check": check},
            )


# --- Cost ---------------------------------------------------------------------

@rule(
    id="COST-101",
    service="cost",
    pillar=Pillar.COST_OPTIMIZATION,
    severity=Severity.INFO,
    title="近 30 天成本概況",
    remediation_hint="檢視前幾大服務花費是否符合預期，評估節流、右移工作負載或採購 Savings Plan 的空間。",
    wa_question_id="cost-monitor-usage",
)
def cost_top_services(data: dict):
    if not data.get("available") or not data.get("by_service"):
        return
    top5 = data["by_service"][:5]
    summary = "、".join(f"{s['service']} ${s['amount_usd']:.2f}" for s in top5)
    yield ("account", summary, {"by_service": data["by_service"]})

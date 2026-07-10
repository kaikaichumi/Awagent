from __future__ import annotations

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector

# 只關注這三個類別，避免噪音（Trusted Advisor 還有 performance/operational_excellence 等類別）
_WATCHED_CATEGORIES = {"cost_optimizing", "security", "fault_tolerance"}


class TrustedAdvisorCollector(Collector):
    """Trusted Advisor 檢查結果；僅 Business/Enterprise Support 方案可用，無方案時優雅降級。"""

    service = "trusted_advisor"
    global_service = True

    def collect(self, session, region: str, boto_cfg) -> dict:
        support = session.client("support", region_name="us-east-1", config=boto_cfg)
        try:
            checks = self.call(
                support, "describe_trusted_advisor_checks", "checks", language="en"
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "SubscriptionRequiredException":
                return {"available": False, "checks": []}
            raise

        results: list[dict] = []
        for check in checks:
            if check.get("category") not in _WATCHED_CATEGORIES:
                continue
            try:
                result = self.call(
                    support,
                    "describe_trusted_advisor_check_result",
                    "result",
                    checkId=check["id"],
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "SubscriptionRequiredException":
                    return {"available": False, "checks": []}
                raise
            flagged = result.get("resourcesSummary", {}).get("resourcesFlagged", 0)
            results.append(
                {
                    "id": check["id"],
                    "name": check.get("name", ""),
                    "category": check["category"],
                    "status": result.get("status", ""),
                    "flagged_resources_count": flagged,
                }
            )
        return {"available": True, "checks": results}

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector

_LOOKBACK_DAYS = 30
_TOP_N = 15


class CostCollector(Collector):
    """Cost Explorer 近 30 天各服務花費彙總；帳號未啟用 CE 時優雅降級。"""

    service = "cost"
    global_service = True

    def collect(self, session, region: str, boto_cfg) -> dict:
        ce = session.client("ce", region_name="us-east-1", config=boto_cfg)
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=_LOOKBACK_DAYS)
        try:
            response = self.call(
                ce,
                "get_cost_and_usage",
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("DataUnavailableException", "AccessDeniedException"):
                return {"available": False, "by_service": []}
            raise

        totals: dict[str, float] = {}
        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                name = group["Keys"][0] if group.get("Keys") else "Unknown"
                amount = float(
                    group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0)
                )
                totals[name] = totals.get(name, 0.0) + amount

        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_N]
        return {
            "available": True,
            "by_service": [{"service": name, "amount_usd": amount} for name, amount in ranked],
        }

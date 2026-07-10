from __future__ import annotations

from waagent.scan.collectors.base import Collector


class CloudWatchCollector(Collector):
    service = "cloudwatch"

    def collect(self, session, region: str, boto_cfg) -> dict:
        cw = session.client("cloudwatch", region_name=region, config=boto_cfg)
        logs = session.client("logs", region_name=region, config=boto_cfg)
        return {
            "alarms": self.call(cw, "describe_alarms", "MetricAlarms"),
            "log_groups": self.call(logs, "describe_log_groups", "logGroups"),
        }

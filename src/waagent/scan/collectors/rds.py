from __future__ import annotations

from waagent.scan.collectors.base import Collector


class RdsCollector(Collector):
    service = "rds"

    def collect(self, session, region: str, boto_cfg) -> dict:
        rds = session.client("rds", region_name=region, config=boto_cfg)
        return {
            "db_instances": self.call(rds, "describe_db_instances", "DBInstances"),
            "db_clusters": self.call(rds, "describe_db_clusters", "DBClusters"),
        }

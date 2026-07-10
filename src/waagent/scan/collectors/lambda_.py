from __future__ import annotations

from waagent.scan.collectors.base import Collector


class LambdaCollector(Collector):
    """Lambda 函式清單。"""

    service = "lambda"

    def collect(self, session, region: str, boto_cfg) -> dict:
        lambda_client = session.client("lambda", region_name=region, config=boto_cfg)
        return {"functions": self.call(lambda_client, "list_functions", "Functions")}

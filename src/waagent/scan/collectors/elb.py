from __future__ import annotations

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector


class ElbCollector(Collector):
    """Elastic Load Balancing v2（ALB/NLB）清單與各自的 listener 設定。"""

    service = "elb"

    def collect(self, session, region: str, boto_cfg) -> dict:
        elbv2 = session.client("elbv2", region_name=region, config=boto_cfg)
        load_balancers = self.call(elbv2, "describe_load_balancers", "LoadBalancers")
        for lb in load_balancers:
            lb["Listeners"] = self._try(
                elbv2, "describe_listeners", "Listeners", LoadBalancerArn=lb["LoadBalancerArn"]
            )
        return {"load_balancers": load_balancers}

    def _try(self, client, method: str, result_key: str, **kwargs):
        try:
            return self.call(client, method, result_key, **kwargs)
        except ClientError as e:
            return {"_error": e.response.get("Error", {}).get("Code", "")}

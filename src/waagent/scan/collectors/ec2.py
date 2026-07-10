from __future__ import annotations

from waagent.scan.collectors.base import Collector


class Ec2Collector(Collector):
    service = "ec2"

    def collect(self, session, region: str, boto_cfg) -> dict:
        ec2 = session.client("ec2", region_name=region, config=boto_cfg)
        reservations = self.call(ec2, "describe_instances", "Reservations")
        instances = [i for r in reservations for i in r.get("Instances", [])]
        return {
            "instances": instances,
            "volumes": self.call(ec2, "describe_volumes", "Volumes"),
            "security_groups": self.call(ec2, "describe_security_groups", "SecurityGroups"),
            "addresses": self.call(ec2, "describe_addresses").get("Addresses", []),
            "snapshots": self.call(
                ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"]
            ),
        }

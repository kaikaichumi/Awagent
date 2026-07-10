from __future__ import annotations

from waagent.scan.collectors.base import Collector


class BackupCollector(Collector):
    service = "backup"

    def collect(self, session, region: str, boto_cfg) -> dict:
        backup = session.client("backup", region_name=region, config=boto_cfg)
        return {
            "plans": self.call(backup, "list_backup_plans", "BackupPlansList"),
            "vaults": self.call(backup, "list_backup_vaults", "BackupVaultList"),
            "protected_resources": self.call(
                backup, "list_protected_resources", "Results"
            ),
        }

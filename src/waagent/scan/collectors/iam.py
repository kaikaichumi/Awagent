from __future__ import annotations

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector


class IamCollector(Collector):
    service = "iam"
    global_service = True

    def collect(self, session, region: str, boto_cfg) -> dict:
        iam = session.client("iam", config=boto_cfg)
        data: dict = {
            "users": self.call(iam, "list_users", "Users"),
            "account_summary": self.call(iam, "get_account_summary").get("SummaryMap", {}),
        }
        try:
            data["password_policy"] = self.call(iam, "get_account_password_policy").get(
                "PasswordPolicy", {}
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                data["password_policy"] = None
            else:
                raise

        # 每個 user 的 MFA / access key 年齡（credential report 需要生成權限，改逐一查）
        for user in data["users"]:
            name = user["UserName"]
            user["MFADevices"] = self.call(iam, "list_mfa_devices", "MFADevices", UserName=name)
            user["AccessKeys"] = self.call(
                iam, "list_access_keys", "AccessKeyMetadata", UserName=name
            )
        return data

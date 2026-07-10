from __future__ import annotations

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector

# 這些 per-bucket API 在設定不存在時丟 ClientError，屬正常情況
_ABSENT_OK = {
    "ServerSideEncryptionConfigurationNotFoundError",
    "NoSuchPublicAccessBlockConfiguration",
    "NoSuchLifecycleConfiguration",
    "NoSuchBucketPolicy",
}


class S3Collector(Collector):
    service = "s3"
    global_service = True

    def collect(self, session, region: str, boto_cfg) -> dict:
        s3 = session.client("s3", region_name=region, config=boto_cfg)
        buckets = self.call(s3, "list_buckets").get("Buckets", [])
        detail: list[dict] = []
        for b in buckets:
            name = b["Name"]
            info: dict = {"Name": name, "CreationDate": b.get("CreationDate")}
            info["Versioning"] = self._try(s3, "get_bucket_versioning", Bucket=name)
            info["Encryption"] = self._try(s3, "get_bucket_encryption", Bucket=name)
            info["PublicAccessBlock"] = self._try(s3, "get_public_access_block", Bucket=name)
            info["Lifecycle"] = self._try(
                s3, "get_bucket_lifecycle_configuration", Bucket=name
            )
            detail.append(info)
        return {"buckets": detail}

    def _try(self, client, method: str, **kwargs):
        try:
            return self.call(client, method, **kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in _ABSENT_OK:
                return None
            if code in ("AccessDenied", "MethodNotAllowed"):
                return {"_error": code}
            raise

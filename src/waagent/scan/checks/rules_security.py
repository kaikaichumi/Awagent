"""Security pillar 規則。"""

from __future__ import annotations

from datetime import datetime, timezone

from waagent.scan.checks.engine import rule
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar

_RISKY_PORTS = {22: "SSH", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 1433: "MSSQL"}


def _open_to_world(perm: dict) -> bool:
    return any(r.get("CidrIp") == "0.0.0.0/0" for r in perm.get("IpRanges", [])) or any(
        r.get("CidrIpv6") == "::/0" for r in perm.get("Ipv6Ranges", [])
    )


@rule(
    id="SEC-001",
    service="ec2",
    pillar=Pillar.SECURITY,
    severity=Severity.CRITICAL,
    title="Security group 對全網開放管理/資料庫連接埠",
    remediation_hint="限縮來源 CIDR 至公司網段，或改用 SSM Session Manager / VPN。",
    wa_question_id="sec-network-protection",
)
def sg_open_risky_ports(data: dict):
    for sg in data.get("security_groups", []):
        for perm in sg.get("IpPermissions", []):
            if not _open_to_world(perm):
                continue
            from_port = perm.get("FromPort")
            to_port = perm.get("ToPort", from_port)
            if from_port is None:  # all traffic
                yield (
                    sg["GroupId"],
                    f"{sg.get('GroupName', '')} 對 0.0.0.0/0 開放全部流量",
                    {"security_group": sg},
                )
                continue
            hit = [
                f"{port}({name})"
                for port, name in _RISKY_PORTS.items()
                if from_port <= port <= to_port
            ]
            if hit:
                yield (
                    sg["GroupId"],
                    f"{sg.get('GroupName', '')} 對 0.0.0.0/0 開放 {', '.join(hit)}",
                    {"security_group_id": sg["GroupId"], "permission": perm},
                )


@rule(
    id="SEC-002",
    service="ec2",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="EBS volume 未加密",
    remediation_hint="啟用帳號層級 EBS encryption by default；既有 volume 需以快照重建加密。",
    wa_question_id="sec-data-rest",
)
def ebs_unencrypted(data: dict):
    for vol in data.get("volumes", []):
        if not vol.get("Encrypted"):
            yield (
                vol["VolumeId"],
                f"{vol.get('Size', '?')}GiB volume 未加密",
                {"volume": {k: vol.get(k) for k in ("VolumeId", "Size", "State", "Attachments")}},
            )


@rule(
    id="SEC-003",
    service="s3",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="S3 bucket 未設定 Public Access Block",
    remediation_hint="對 bucket（或帳號層級）啟用全部四項 Block Public Access 設定。",
    wa_question_id="sec-data-rest",
)
def s3_no_public_access_block(data: dict):
    for b in data.get("buckets", []):
        pab = b.get("PublicAccessBlock")
        cfg = (pab or {}).get("PublicAccessBlockConfiguration", {})
        if not pab or not all(cfg.get(k) for k in (
            "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"
        )):
            yield (b["Name"], "Public Access Block 未完整啟用", {"public_access_block": pab})


@rule(
    id="SEC-004",
    service="s3",
    pillar=Pillar.SECURITY,
    severity=Severity.MEDIUM,
    title="S3 bucket 未設定預設加密",
    remediation_hint="設定 bucket 預設加密（SSE-S3 或 SSE-KMS）。",
    wa_question_id="sec-data-rest",
)
def s3_no_encryption(data: dict):
    for b in data.get("buckets", []):
        if b.get("Encryption") is None:
            yield (b["Name"], "未設定 bucket 預設加密", {})


@rule(
    id="SEC-005",
    service="iam",
    pillar=Pillar.SECURITY,
    severity=Severity.CRITICAL,
    title="Root 帳號未啟用 MFA",
    remediation_hint="立即為 root 帳號啟用硬體或虛擬 MFA。",
    wa_question_id="sec-identities",
)
def root_no_mfa(data: dict):
    summary = data.get("account_summary", {})
    if summary and summary.get("AccountMFAEnabled") == 0:
        yield ("account-root", "AccountMFAEnabled = 0", {"account_summary": summary})


@rule(
    id="SEC-006",
    service="iam",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="IAM user 有密碼但未啟用 MFA",
    remediation_hint="強制 console user 綁定 MFA（IAM policy 條件 aws:MultiFactorAuthPresent）。",
    wa_question_id="sec-identities",
)
def user_no_mfa(data: dict):
    for user in data.get("users", []):
        if user.get("PasswordLastUsed") and not user.get("MFADevices"):
            yield (user["UserName"], "console 登入啟用但無 MFA 裝置", {})


@rule(
    id="SEC-007",
    service="iam",
    pillar=Pillar.SECURITY,
    severity=Severity.MEDIUM,
    title="IAM access key 超過 90 天未輪替",
    remediation_hint="建立 key 輪替流程；長期憑證盡量以 IAM Role 取代。",
    wa_question_id="sec-identities",
)
def old_access_keys(data: dict):
    now = datetime.now(timezone.utc)
    for user in data.get("users", []):
        for key in user.get("AccessKeys", []):
            if key.get("Status") != "Active":
                continue
            created = key.get("CreateDate")
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            if created and (now - created).days > 90:
                yield (
                    f"{user['UserName']}/{key.get('AccessKeyId', '')}",
                    f"access key 已使用 {(now - created).days} 天",
                    {"create_date": str(created)},
                )


@rule(
    id="SEC-008",
    service="iam",
    pillar=Pillar.SECURITY,
    severity=Severity.MEDIUM,
    title="帳號未設定 IAM 密碼原則",
    remediation_hint="設定密碼長度、複雜度與重用限制。",
    wa_question_id="sec-identities",
)
def no_password_policy(data: dict):
    if "password_policy" in data and data["password_policy"] is None:
        yield ("account", "GetAccountPasswordPolicy: NoSuchEntity", {})


@rule(
    id="SEC-009",
    service="rds",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="RDS 執行個體未加密儲存",
    remediation_hint="以加密快照複製重建；新執行個體一律啟用 StorageEncrypted。",
    wa_question_id="sec-data-rest",
)
def rds_unencrypted(data: dict):
    for db in data.get("db_instances", []):
        if not db.get("StorageEncrypted"):
            yield (db["DBInstanceIdentifier"], f"engine={db.get('Engine')} 未加密", {})


@rule(
    id="SEC-010",
    service="rds",
    pillar=Pillar.SECURITY,
    severity=Severity.HIGH,
    title="RDS 執行個體可公開存取",
    remediation_hint="關閉 PubliclyAccessible，改由私網/VPN 存取。",
    wa_question_id="sec-network-protection",
)
def rds_public(data: dict):
    for db in data.get("db_instances", []):
        if db.get("PubliclyAccessible"):
            yield (db["DBInstanceIdentifier"], "PubliclyAccessible = true", {})

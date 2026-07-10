"""掃描協調：collectors（多 region 平行）→ raw → checks → findings → digest。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from waagent.config import Config
from waagent.net import boto_config
from waagent.scan import snapshot
from waagent.scan.checks import run_checks
from waagent.scan.collectors import ALL_COLLECTORS
from waagent.scan.models import Digest, RunMeta

ProgressFn = Callable[[str], None]

# digest 的資源計數要看的 raw 欄位：service -> (key, 顯示名)
_COUNT_KEYS: dict[str, list[tuple[str, str]]] = {
    "ec2": [("instances", "EC2 instances"), ("volumes", "EBS volumes"),
            ("security_groups", "Security groups")],
    "rds": [("db_instances", "RDS instances"), ("db_clusters", "RDS clusters")],
    "s3": [("buckets", "S3 buckets")],
    "iam": [("users", "IAM users")],
    "cloudwatch": [("alarms", "CloudWatch alarms"), ("log_groups", "Log groups")],
    "backup": [("plans", "Backup plans")],
    "lambda": [("functions", "Lambda functions")],
    "elb": [("load_balancers", "Load balancers")],
    "dynamodb": [("tables", "DynamoDB tables")],
}


def _make_session(config: Config) -> boto3.Session:
    if config.aws.profile:
        return boto3.Session(profile_name=config.aws.profile)
    return boto3.Session()


# IAM Identity Center（SSO）token 過期/未登入時的例外名稱特徵
_SSO_ERROR_NAMES = ("SSOTokenLoadError", "UnauthorizedSSOTokenError", "TokenRetrievalError", "SSOError")
# 連不到端點（公司網路直連被擋、proxy 沒生效）的例外名稱特徵
_NETWORK_ERROR_NAMES = ("ConnectTimeoutError", "EndpointConnectionError", "ConnectionClosedError", "ProxyConnectionError", "ReadTimeoutError")


def friendly_aws_error(e: Exception, profile: str = "") -> str:
    """把 boto3 的 SSO / 網路錯誤轉成可行動的訊息。"""
    name = type(e).__name__
    if any(hint in name for hint in _SSO_ERROR_NAMES) or "sso" in str(e).lower():
        cmd = f"aws sso login --profile {profile}" if profile else "aws sso login"
        return (
            f"AWS SSO 憑證失效或尚未登入（{name}）。"
            f"請先執行 `{cmd}` 完成 IAM Identity Center 登入後重試。"
        )
    if any(hint in name for hint in _NETWORK_ERROR_NAMES):
        return (
            f"連不到 AWS 端點（{name}）。公司網路多半是 proxy 未生效——"
            f"請在 config.toml 的 [network] 填 https_proxy（必要時加 ca_bundle），"
            f"或確認 HTTPS_PROXY 環境變數。"
        )
    return str(e)


def get_account_id(config: Config, *, fast: bool = False) -> str:
    session = _make_session(config)
    sts = session.client("sts", config=boto_config(config, fast=fast))
    try:
        return sts.get_caller_identity()["Account"]
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(friendly_aws_error(e, config.aws.profile)) from e


def run_scan(
    config: Config,
    *,
    services: list[str] | None = None,
    regions: list[str] | None = None,
    progress: ProgressFn = lambda _msg: None,
) -> Digest:
    run_id = snapshot.new_run_id()
    regions = regions or config.aws.regions
    session = _make_session(config)
    cfg = boto_config(config)
    errors: list[str] = []

    account_id = get_account_id(config)  # 失敗時丟出含 SSO 指引的 RuntimeError

    collectors = [
        cls() for cls in ALL_COLLECTORS if not services or cls.service in services
    ]

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs: list[tuple] = []  # (collector, region)
    for collector in collectors:
        for region in regions[:1] if collector.global_service else regions:
            jobs.append((collector, region))

    def _run_job(collector, region: str) -> tuple[str, str]:
        data = collector.collect(session, region, cfg)
        snapshot.write_raw(run_id, collector.service, region, data)
        return collector.service, region

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_run_job, c, r): (c.service, r) for c, r in jobs}
        for future in as_completed(futures):
            service, region = futures[future]
            try:
                future.result()
                progress(f"{service} @ {region} 完成")
            except (BotoCoreError, ClientError) as e:
                msg = f"{service} @ {region} 失敗: {e}"
                errors.append(msg)
                progress(msg)

    progress("執行規則引擎…")
    findings = run_checks(run_id)
    snapshot.write_findings(run_id, findings)

    resource_counts: dict[str, int] = {}
    for service, _region, data in snapshot.iter_raw(run_id):
        for key, label in _COUNT_KEYS.get(service, []):
            resource_counts[label] = resource_counts.get(label, 0) + len(data.get(key) or [])

    digest = snapshot.build_digest(
        run_id,
        findings,
        account_id=account_id,
        regions=regions,
        resource_counts=resource_counts,
        collector_errors=errors,
    )
    snapshot.write_digest(run_id, digest)
    snapshot.write_meta(
        run_id,
        RunMeta(
            run_id=run_id,
            account_id=account_id,
            regions=regions,
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            services=[c.service for c in collectors],
            errors=errors,
        ),
    )
    progress(f"掃描完成：{len(findings)} 條 findings，run_id={run_id}")
    return digest

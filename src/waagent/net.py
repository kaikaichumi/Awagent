"""Proxy / CA 的唯一控制點。

所有對外連線（GitHub Copilot 端點、Copilot SDK 內嵌 runtime、boto3）都必須
經由這裡設定，其他模組一律不得自行處理 proxy。
"""

from __future__ import annotations

import os
from pathlib import Path

from botocore.config import Config as BotoConfig

from waagent.config import Config

# Copilot SDK 內嵌 runtime（Node）與 Python 各 HTTP 套件吃的環境變數
_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_CA_ENV_KEYS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "AWS_CA_BUNDLE")


def apply_network_env(config: Config) -> None:
    """啟動時呼叫一次：把 config 的 proxy/CA 寫進環境變數。

    只在 config 有值時覆蓋；否則保留使用者環境既有設定。
    """
    net = config.network
    if net.https_proxy:
        os.environ["HTTPS_PROXY"] = net.https_proxy
        os.environ["https_proxy"] = net.https_proxy
    if net.http_proxy:
        os.environ["HTTP_PROXY"] = net.http_proxy
        os.environ["http_proxy"] = net.http_proxy
    if net.ca_bundle:
        for key in _CA_ENV_KEYS:
            os.environ[key] = net.ca_bundle


def effective_proxies() -> dict[str, str]:
    proxies: dict[str, str] = {}
    for scheme, keys in (("https", ("HTTPS_PROXY", "https_proxy")), ("http", ("HTTP_PROXY", "http_proxy"))):
        for key in keys:
            if os.environ.get(key):
                proxies[scheme] = os.environ[key]
                break
    return proxies


def effective_ca_bundle() -> str | None:
    for key in _CA_ENV_KEYS:
        if os.environ.get(key):
            return os.environ[key]
    return None


def boto_config(config: Config) -> BotoConfig:
    """所有 boto3 client 共用的 Config：proxy、CA、重試、UA。"""
    kwargs: dict = {
        "retries": {"max_attempts": 8, "mode": "adaptive"},
        "user_agent_extra": "waagent",
    }
    proxies = effective_proxies()
    if proxies:
        kwargs["proxies"] = proxies
    ca = effective_ca_bundle()
    if ca:
        kwargs["proxies_config"] = {"proxy_ca_bundle": ca}
    return BotoConfig(**kwargs)


def network_report(config: Config) -> list[tuple[str, str]]:
    """doctor 用：目前生效的網路設定摘要。"""
    proxies = effective_proxies()
    ca = effective_ca_bundle()
    rows = [
        ("HTTPS proxy", proxies.get("https", "(未設定，直連)")),
        ("HTTP proxy", proxies.get("http", "(未設定，直連)")),
        ("CA bundle", ca or "(系統預設)"),
    ]
    if ca and not Path(ca).is_file():
        rows.append(("CA bundle 警告", f"檔案不存在: {ca}"))
    return rows

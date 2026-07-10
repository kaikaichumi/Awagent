"""IAM Identity Center（SSO）裝置授權登入——與 Kiro 相同的登入體驗。

不依賴 AWS CLI v2：直接用 boto3 的 sso-oidc / sso API 走 device flow。
流程：register_client → start_device_authorization（跳瀏覽器輸入帳密+MFA）
→ create_token（約 8 小時有效）→ get_role_credentials（臨時金鑰）。

快取存 ~/.waagent/sso_cache.json：
- client（clientId/Secret，約 90 天）
- token（accessToken，約 8 小時；過期才需要重新跳瀏覽器）
- selection（上次選的帳號/角色）
- credentials（臨時金鑰，到期自動用 token 換新，不用重登）
"""

from __future__ import annotations

import json
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from waagent.config import Config
from waagent.net import boto_config

CACHE_PATH = Path.home() / ".waagent" / "sso_cache.json"


class SsoLoginRequired(RuntimeError):
    """token 不存在或已過期，需要重新執行 waagent login。"""


def _now() -> float:
    return time.time()


def _load_cache() -> dict:
    if CACHE_PATH.is_file():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _is_valid(entry: dict | None, skew: float = 60.0) -> bool:
    return bool(entry) and entry.get("expiresAt", 0) - skew > _now()


def sso_configured(config: Config) -> bool:
    return bool(config.aws.sso_start_url)


def _oidc_client(config: Config):
    session = boto3.Session()
    return session.client(
        "sso-oidc", region_name=config.aws.sso_region, config=boto_config(config, fast=True)
    )


def _sso_client(config: Config):
    session = boto3.Session()
    return session.client(
        "sso", region_name=config.aws.sso_region, config=boto_config(config, fast=True)
    )


def _register_client(config: Config, cache: dict) -> dict:
    if _is_valid(cache.get("client")):
        return cache["client"]
    oidc = _oidc_client(config)
    reg = oidc.register_client(clientName="waagent", clientType="public")
    cache["client"] = {
        "clientId": reg["clientId"],
        "clientSecret": reg["clientSecret"],
        "expiresAt": reg.get("clientSecretExpiresAt", _now() + 89 * 86400),
    }
    _save_cache(cache)
    return cache["client"]


def device_login(config: Config, *, prompt, echo) -> None:
    """互動登入（Kiro 式）。echo(text) 輸出訊息；prompt(text) 取使用者輸入。"""
    cache = _load_cache()
    client = _register_client(config, cache)
    oidc = _oidc_client(config)

    auth = oidc.start_device_authorization(
        clientId=client["clientId"],
        clientSecret=client["clientSecret"],
        startUrl=config.aws.sso_start_url,
    )
    url = auth.get("verificationUriComplete") or auth["verificationUri"]
    echo(f"請在瀏覽器完成登入（帳密 + MFA，與 Kiro 相同流程）：\n  {url}")
    echo(f"確認代碼：{auth['userCode']}（頁面上顯示的代碼須一致）")
    try:
        webbrowser.open(url)
    except Exception:
        pass  # 開不了瀏覽器就請使用者手動貼網址

    interval = auth.get("interval", 5)
    deadline = _now() + auth.get("expiresIn", 600)
    while _now() < deadline:
        time.sleep(interval)
        try:
            token = oidc.create_token(
                grantType="urn:ietf:params:oauth:grant-type:device_code",
                deviceCode=auth["deviceCode"],
                clientId=client["clientId"],
                clientSecret=client["clientSecret"],
            )
            break
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "AuthorizationPendingException":
                continue
            if code == "SlowDownException":
                interval += 5
                continue
            raise
    else:
        raise SsoLoginRequired("登入逾時，請重新執行 waagent login。")

    cache["token"] = {
        "accessToken": token["accessToken"],
        "expiresAt": _now() + token.get("expiresIn", 8 * 3600),
    }
    cache.pop("credentials", None)
    _save_cache(cache)
    echo("登入成功。")

    _select_account_role(config, cache, prompt=prompt, echo=echo)


def _select_account_role(config: Config, cache: dict, *, prompt, echo) -> None:
    """列出可用帳號/角色讓使用者選，記住選擇。"""
    sso = _sso_client(config)
    token = cache["token"]["accessToken"]

    accounts = sso.list_accounts(accessToken=token, maxResults=50).get("accountList", [])
    if not accounts:
        raise SsoLoginRequired("此登入沒有任何可用的 AWS 帳號。")
    if len(accounts) == 1:
        account = accounts[0]
        echo(f"帳號：{account['accountName']}（{account['accountId']}）")
    else:
        echo("可用帳號：")
        for i, a in enumerate(accounts, 1):
            echo(f"  {i}. {a['accountName']}（{a['accountId']}）")
        idx = int(prompt("選擇帳號編號") or "1") - 1
        account = accounts[max(0, min(idx, len(accounts) - 1))]

    roles = sso.list_account_roles(
        accessToken=token, accountId=account["accountId"], maxResults=50
    ).get("roleList", [])
    if not roles:
        raise SsoLoginRequired(f"帳號 {account['accountId']} 下沒有可用角色。")
    if len(roles) == 1:
        role = roles[0]
        echo(f"角色：{role['roleName']}")
    else:
        echo("可用角色：")
        for i, r in enumerate(roles, 1):
            echo(f"  {i}. {r['roleName']}")
        idx = int(prompt("選擇角色編號") or "1") - 1
        role = roles[max(0, min(idx, len(roles) - 1))]

    cache["selection"] = {"accountId": account["accountId"], "roleName": role["roleName"]}
    _save_cache(cache)


def get_credentials(config: Config) -> dict:
    """取得臨時金鑰 dict（AccessKeyId/SecretAccessKey/SessionToken）。

    憑證過期但 token 還有效時自動換新；token 也過期才丟 SsoLoginRequired。
    """
    cache = _load_cache()

    creds = cache.get("credentials")
    if _is_valid(creds):
        return creds

    if not _is_valid(cache.get("token")):
        raise SsoLoginRequired("SSO 登入已過期，請執行 `waagent login`。")
    selection = cache.get("selection")
    if not selection:
        raise SsoLoginRequired("尚未選擇帳號/角色，請執行 `waagent login`。")

    sso = _sso_client(config)
    resp = sso.get_role_credentials(
        roleName=selection["roleName"],
        accountId=selection["accountId"],
        accessToken=cache["token"]["accessToken"],
    )["roleCredentials"]
    cache["credentials"] = {
        "accessKeyId": resp["accessKeyId"],
        "secretAccessKey": resp["secretAccessKey"],
        "sessionToken": resp["sessionToken"],
        "expiresAt": resp["expiration"] / 1000.0,  # API 回傳毫秒 epoch
    }
    _save_cache(cache)
    return cache["credentials"]


def make_boto_session(config: Config) -> boto3.Session:
    """全專案統一的 boto3 Session 工廠。

    優先序：SSO 裝置登入（sso_start_url 有設）> named profile > 預設憑證鏈。
    """
    if sso_configured(config):
        creds = get_credentials(config)
        return boto3.Session(
            aws_access_key_id=creds["accessKeyId"],
            aws_secret_access_key=creds["secretAccessKey"],
            aws_session_token=creds["sessionToken"],
        )
    if config.aws.profile:
        return boto3.Session(profile_name=config.aws.profile)
    return boto3.Session()


def login_status(config: Config) -> str:
    """doctor 用：目前 SSO 登入狀態描述。"""
    if not sso_configured(config):
        return ""
    cache = _load_cache()
    token = cache.get("token")
    selection = cache.get("selection") or {}
    if _is_valid(token):
        until = datetime.fromtimestamp(token["expiresAt"], tz=timezone.utc).astimezone()
        who = f"{selection.get('accountId', '?')}/{selection.get('roleName', '?')}"
        return f"SSO 已登入（{who}，有效至 {until:%H:%M}）"
    return "SSO 未登入或已過期——請執行 waagent login"

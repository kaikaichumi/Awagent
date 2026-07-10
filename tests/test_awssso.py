"""SSO 裝置登入的快取/過期邏輯測試（不打真 API）。"""

from __future__ import annotations

import time

import pytest

from waagent import awssso
from waagent.config import Config


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "sso_cache.json"
    monkeypatch.setattr(awssso, "CACHE_PATH", path)
    return path


def _config(start_url: str = "https://corp.awsapps.com/start") -> Config:
    return Config.model_validate({"aws": {"sso_start_url": start_url}})


def test_sso_configured():
    assert awssso.sso_configured(_config())
    assert not awssso.sso_configured(_config(""))


def test_is_valid_expiry():
    assert awssso._is_valid({"expiresAt": time.time() + 3600})
    assert not awssso._is_valid({"expiresAt": time.time() + 30})  # 60s skew 內視為過期
    assert not awssso._is_valid({"expiresAt": time.time() - 10})
    assert not awssso._is_valid(None)
    assert not awssso._is_valid({})


def test_get_credentials_requires_login_when_no_cache(cache_path):
    with pytest.raises(awssso.SsoLoginRequired):
        awssso.get_credentials(_config())


def test_get_credentials_requires_login_when_token_expired(cache_path):
    awssso._save_cache({
        "token": {"accessToken": "x", "expiresAt": time.time() - 100},
        "selection": {"accountId": "123", "roleName": "ReadOnly"},
    })
    with pytest.raises(awssso.SsoLoginRequired):
        awssso.get_credentials(_config())


def test_get_credentials_uses_valid_cached_credentials(cache_path):
    creds = {
        "accessKeyId": "AKIA...",
        "secretAccessKey": "s",
        "sessionToken": "t",
        "expiresAt": time.time() + 3600,
    }
    awssso._save_cache({
        "token": {"accessToken": "x", "expiresAt": time.time() + 3600},
        "selection": {"accountId": "123", "roleName": "ReadOnly"},
        "credentials": creds,
    })
    assert awssso.get_credentials(_config())["accessKeyId"] == "AKIA..."


def test_make_boto_session_falls_back_without_sso(cache_path):
    session = awssso.make_boto_session(_config(""))
    assert session is not None  # 預設憑證鏈，不經 SSO


def test_login_status(cache_path):
    assert awssso.login_status(_config("")) == ""
    assert "waagent login" in awssso.login_status(_config())
    awssso._save_cache({
        "token": {"accessToken": "x", "expiresAt": time.time() + 3600},
        "selection": {"accountId": "123", "roleName": "ReadOnly"},
    })
    assert "已登入" in awssso.login_status(_config())

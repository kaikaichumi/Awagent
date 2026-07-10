"""設定載入與合併：環境變數 > 專案 .waagent.toml > 全域 config.toml > 預設值。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel, Field, field_validator

GLOBAL_CONFIG_PATH = Path(user_config_dir("waagent", appauthor=False)) / "config.toml"
PROJECT_CONFIG_NAME = ".waagent.toml"


class NetworkConfig(BaseModel):
    https_proxy: str = ""
    http_proxy: str = ""
    ca_bundle: str = ""


class AwsConfig(BaseModel):
    profile: str = ""
    regions: list[str] = Field(default_factory=lambda: ["ap-northeast-1"])
    # IAM Identity Center 裝置登入（waagent login，Kiro 式體驗）；
    # sso_start_url 有值時優先於 profile。
    sso_start_url: str = ""
    sso_region: str = "us-east-1"


class CopilotConfig(BaseModel):
    model: str = "auto"  # 具體模型 id，或 "auto" = waagent 本地路由（非 Copilot auto）
    vision_model: str = ""
    use_logged_in_user: bool = True
    # auto 路由：地板與升級模型（子字串比對 model id）；strong 留空 = 自動選最強
    auto_floor: str = "sonnet"
    auto_strong: str = ""
    auto_keywords: list[str] = Field(default_factory=list)  # 空 = 用內建升級關鍵詞
    reasoning_effort: str = ""  # low / medium / high；留空 = SDK 預設
    context_tier: str = ""  # default / long_context；留空 = SDK 預設
    # 自動壓縮門檻（infinite sessions）
    compaction_start: float = 0.80
    compaction_block: float = 0.95
    # 單一 session 的 AI credits 上限（0 = 不限制）——防止額度爆掉
    max_ai_credits: float = 0.0
    # 單回合最長等待秒數
    turn_timeout: float = 1800.0
    # 額外的 skill 目錄（絕對或相對路徑），非空時會啟用 SDK skills 功能
    skill_directories: list[str] = Field(default_factory=list)


class WaConfig(BaseModel):
    templates_dir: str = ""
    output_dir: str = ""
    workload_id: str = ""
    lens_alias: str = "wellarchitected"


class Config(BaseModel):
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    aws: AwsConfig = Field(default_factory=AwsConfig)
    copilot: CopilotConfig = Field(default_factory=CopilotConfig)
    wa: WaConfig = Field(default_factory=WaConfig)
    # MCP servers：[mcp.<name>] 子表原樣傳遞給 Copilot SDK（欄位由 SDK 定義，這裡不強制 schema）
    mcp: dict[str, dict] = Field(default_factory=dict)

    # 設定檔以外的執行期資訊
    sources: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("mcp")
    @classmethod
    def _drop_invalid_mcp_servers(cls, v: dict[str, dict]) -> dict[str, dict]:
        """容錯：每個 server 至少要有 command 或 url 其一，否則忽略該項（不丟例外）。"""
        return {
            name: server
            for name, server in v.items()
            if isinstance(server, dict) and ("command" in server or "url" in server)
        }


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _find_project_config(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        candidate = d / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def _apply_env_overrides(data: dict) -> dict:
    """環境變數最優先。WAAGENT_ 前綴覆蓋設定；proxy 類沿用標準變數。"""
    env_map = {
        ("network", "https_proxy"): os.environ.get("WAAGENT_HTTPS_PROXY"),
        ("network", "http_proxy"): os.environ.get("WAAGENT_HTTP_PROXY"),
        ("network", "ca_bundle"): os.environ.get("WAAGENT_CA_BUNDLE"),
        ("aws", "profile"): os.environ.get("WAAGENT_AWS_PROFILE"),
        ("copilot", "model"): os.environ.get("WAAGENT_MODEL"),
        ("wa", "templates_dir"): os.environ.get("WAAGENT_TEMPLATES_DIR"),
        ("wa", "output_dir"): os.environ.get("WAAGENT_OUTPUT_DIR"),
        ("wa", "workload_id"): os.environ.get("WAAGENT_WORKLOAD_ID"),
    }
    for (section, key), value in env_map.items():
        if value:
            data.setdefault(section, {})[key] = value
    return data


def load_config(cwd: Path | None = None) -> Config:
    cwd = cwd or Path.cwd()
    merged: dict = {}
    sources: list[str] = []

    if GLOBAL_CONFIG_PATH.is_file():
        merged = _deep_merge(merged, _read_toml(GLOBAL_CONFIG_PATH))
        sources.append(str(GLOBAL_CONFIG_PATH))

    project_path = _find_project_config(cwd)
    if project_path:
        merged = _deep_merge(merged, _read_toml(project_path))
        sources.append(str(project_path))

    merged = _apply_env_overrides(merged)
    config = Config.model_validate(merged)
    config.sources = sources
    return config

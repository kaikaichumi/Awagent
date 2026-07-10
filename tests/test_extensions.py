"""SDK 擴充功能測試：MCP servers / skills 設定解析、vision 模型切換判斷。"""

from __future__ import annotations

from pathlib import Path

from waagent.chat.session import _needs_vision_switch
from waagent.config import load_config


def _write_project_config(tmp_path: Path, content: str) -> None:
    (tmp_path / ".waagent.toml").write_text(content, encoding="utf-8")


def test_mcp_servers_parsed_and_invalid_entries_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr("waagent.config.GLOBAL_CONFIG_PATH", tmp_path / "不存在" / "config.toml")
    _write_project_config(
        tmp_path,
        """
[mcp.foo]
command = "npx"
args = ["-y", "some-mcp-server"]

[mcp.bar]
url = "https://example.com/mcp"

[mcp.broken]
timeout = 1000
""",
    )
    config = load_config(cwd=tmp_path)
    # 缺 command 與 url 的 [mcp.broken] 應被容錯忽略，不丟例外
    assert set(config.mcp.keys()) == {"foo", "bar"}
    assert config.mcp["foo"]["command"] == "npx"
    assert config.mcp["foo"]["args"] == ["-y", "some-mcp-server"]
    assert config.mcp["bar"]["url"] == "https://example.com/mcp"


def test_mcp_empty_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr("waagent.config.GLOBAL_CONFIG_PATH", tmp_path / "不存在" / "config.toml")
    _write_project_config(tmp_path, "[aws]\nprofile = \"\"\n")
    config = load_config(cwd=tmp_path)
    assert config.mcp == {}


def test_skill_directories_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr("waagent.config.GLOBAL_CONFIG_PATH", tmp_path / "不存在" / "config.toml")
    _write_project_config(
        tmp_path,
        """
[copilot]
skill_directories = ["skills/aws", "skills/common"]
""",
    )
    config = load_config(cwd=tmp_path)
    assert config.copilot.skill_directories == ["skills/aws", "skills/common"]


def test_skill_directories_default_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("waagent.config.GLOBAL_CONFIG_PATH", tmp_path / "不存在" / "config.toml")
    _write_project_config(tmp_path, "[aws]\nprofile = \"\"\n")
    config = load_config(cwd=tmp_path)
    assert config.copilot.skill_directories == []


def test_needs_vision_switch_true_when_attachment_and_model_differ():
    assert _needs_vision_switch(True, "gpt-5-vision", "sonnet") is True


def test_needs_vision_switch_false_without_attachments():
    assert _needs_vision_switch(False, "gpt-5-vision", "sonnet") is False


def test_needs_vision_switch_false_without_vision_model_configured():
    assert _needs_vision_switch(True, "", "sonnet") is False


def test_needs_vision_switch_false_when_already_on_vision_model():
    assert _needs_vision_switch(True, "sonnet", "sonnet") is False

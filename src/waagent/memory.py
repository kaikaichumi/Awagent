"""waagent 長期記憶：~/.waagent/memory.md。

類 CLAUDE.md 的跨 session 記憶：session 啟動時整份注入 system prompt，
agent 透過 memory_save 工具寫入。使用者可直接手動編輯這個檔案。
與 Copilot SDK 原生 memory（對話層）互補：這裡放的是使用者/專案/AWS 帳號
層級的持久事實。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

MEMORY_PATH = Path.home() / ".waagent" / "memory.md"
_MAX_CHARS = 16_000  # 注入 system prompt 的上限，超過提醒使用者整理

_HEADER = """\
# waagent 記憶

agent 跨 session 的長期記憶。每條記憶一個小節，可手動編輯或刪除。
"""


def read_memory() -> str:
    if not MEMORY_PATH.is_file():
        return ""
    return MEMORY_PATH.read_text(encoding="utf-8", errors="replace")


def memory_for_prompt() -> str:
    """給 system prompt 的記憶內容；過長時截斷並標註。"""
    text = read_memory().strip()
    if not text:
        return ""
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n\n[記憶過長已截斷——請使用者整理 memory.md]"
    return text


def append_memory(topic: str, content: str) -> Path:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = read_memory()
    if not existing:
        existing = _HEADER
    stamp = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n## {topic}（{stamp}）\n\n{content.strip()}\n"
    MEMORY_PATH.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")
    return MEMORY_PATH

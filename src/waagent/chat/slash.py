"""REPL slash commands。回傳值決定 REPL 的下一步動作。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HELP_TEXT = """\
可用指令：
  /mode [coder|aws-debug|wa-review]  顯示或切換模式（開新 session）
  /image <路徑>            附加圖片檔到下一則訊息（架構圖、錯誤截圖等）
  /paste                   附加剪貼簿中的圖片（先 Win+Shift+S 截圖再 /paste）
  /scan                    請 agent 執行 AWS 掃描
  /report                  請 agent 依模板規則產生報告
  /diff                    請 agent 比較最近兩次掃描（修正驗證）
  /resume [session_id]     列出可接續的 session / 接續指定 session
  /usage                   顯示本 session 的 token/credits 用量與 context 使用率
  /model [id|auto]         顯示可用模型（含倍率）/ 釘選模型 / auto = 本地路由
  /memory                  顯示 waagent 長期記憶內容
  /clear                   重開目前模式的 session
  /help                    顯示本說明
  /exit                    離開
"""

_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


@dataclass
class SlashResult:
    handled: bool = True
    quit: bool = False
    switch_mode: str = ""
    reset: bool = False
    attach_path: str = ""
    send_text: str = ""  # 轉為送給 agent 的訊息
    message: str = ""  # 顯示給使用者的訊息
    action: str = ""  # REPL 特殊動作：resume / usage / model / memory
    action_arg: str = ""


def image_mime(path: str) -> str | None:
    return _IMAGE_MIME.get(Path(path).suffix.lower())


def handle_slash(line: str, current_mode: str, available_modes: list[str]) -> SlashResult:
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit", "/q"):
        return SlashResult(quit=True)
    if cmd == "/help":
        return SlashResult(message=HELP_TEXT)
    if cmd == "/clear":
        return SlashResult(reset=True, message="已重開 session。")
    if cmd == "/mode":
        if not arg:
            return SlashResult(
                message=f"目前模式：{current_mode}（可用：{', '.join(available_modes)}）"
            )
        if arg not in available_modes:
            return SlashResult(message=f"未知模式 {arg}（可用：{', '.join(available_modes)}）")
        if arg == current_mode:
            return SlashResult(message=f"已在 {arg} 模式。")
        return SlashResult(switch_mode=arg)
    if cmd == "/image":
        if not arg:
            return SlashResult(message="用法：/image <圖片路徑>")
        path = Path(arg.strip('"'))
        if not path.is_file():
            return SlashResult(message=f"找不到檔案：{path}")
        if not image_mime(str(path)):
            return SlashResult(message=f"不支援的圖片格式：{path.suffix}")
        return SlashResult(attach_path=str(path), message=f"已附加 {path.name}，隨下一則訊息送出。")
    if cmd == "/scan":
        return SlashResult(send_text="請執行 aws_scan 掃描 AWS 帳號，完成後用 get_scan_digest 給我重點摘要。")
    if cmd == "/report":
        return SlashResult(
            send_text="請先呼叫 template_rules_load 讀取最新報告規則，然後根據最新掃描結果撰寫 narrative 並呼叫 report_render 產生 Markdown 與 HTML 報告。"
        )
    if cmd == "/diff":
        return SlashResult(
            send_text="請呼叫 compare_runs 比較最近兩次掃描，總結哪些風險已修復、哪些是新出現的，並建議下一步。"
        )
    if cmd == "/paste":
        return SlashResult(action="paste")
    if cmd == "/resume":
        return SlashResult(action="resume", action_arg=arg)
    if cmd == "/usage":
        return SlashResult(action="usage")
    if cmd == "/model":
        return SlashResult(action="model", action_arg=arg)
    if cmd == "/memory":
        return SlashResult(action="memory")
    return SlashResult(message=f"未知指令 {cmd}，輸入 /help 查看可用指令。")

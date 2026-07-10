"""互動 REPL：prompt_toolkit 輸入 + Rich streaming 輸出。"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.table import Table

from waagent.agents.registry import get_agent_specs
from waagent.chat.session import Attachment, ChatSession, CopilotNotInstalled, SessionCallbacks
from waagent.chat.slash import handle_slash, image_mime
from waagent.config import Config
from waagent.memory import MEMORY_PATH, read_memory
from waagent.scan.snapshot import RUNS_DIR

console = Console()


async def run_repl(config: Config, initial_mode: str = "coder", resume: str = "") -> None:
    specs = get_agent_specs(config)
    mode = initial_mode if initial_mode in specs else "coder"

    history_path = RUNS_DIR.parent / "repl_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = PromptSession(history=FileHistory(str(history_path)))

    console.print("[bold]waagent[/bold] — Copilot 驅動的 AWS WA agent")
    console.print(f"[dim]模式: {mode}（/mode 切換）；/help 查看指令；/exit 離開[/dim]\n")

    session = await _open_session(config, mode, resume)
    if session is None:
        return

    try:
        while True:
            try:
                with patch_stdout():
                    line = await prompt.prompt_async(f"{mode}> ")
            except (EOFError, KeyboardInterrupt):
                break
            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                result = handle_slash(line, mode, list(specs))
                if result.quit:
                    break
                if result.message:
                    console.print(result.message)
                if result.switch_mode:
                    await session.close()
                    mode = result.switch_mode
                    session = await _open_session(config, mode)
                    if session is None:
                        return
                    console.print(f"已切換到 [bold]{mode}[/bold] 模式（新 session）。")
                if result.reset:
                    await session.close()
                    session = await _open_session(config, mode)
                    if session is None:
                        return
                if result.attach_path:
                    session.queue_attachment(
                        Attachment(path=result.attach_path,
                                   mime_type=image_mime(result.attach_path) or "image/png")
                    )
                if result.action:
                    new_session = await _handle_action(session, config, mode, result.action, result.action_arg)
                    if new_session is not None:
                        session = new_session
                if not result.send_text:
                    continue
                line = result.send_text

            # auto 路由：waagent 本地規則選模型（非 Copilot auto）
            notice = await session.route_before_send(line, session.has_pending_attachments)
            if notice:
                console.print(f"[dim]{notice}[/dim]")

            await _send_and_render(session, line)
    finally:
        await session.close()
        console.print("[dim]再見。[/dim]")


async def _handle_action(
    session: ChatSession, config: Config, mode: str, action: str, arg: str
) -> ChatSession | None:
    """處理 /resume /usage /model /memory。回傳非 None 表示換了新 session。"""
    if action == "usage":
        u = session.usage
        table = Table(show_header=False, title="本 session 用量")
        routing = "auto（本地路由）" if session.auto_router else (session.current_model or config.copilot.model)
        table.add_row("模型", routing)
        if u.model_turns:
            table.add_row("各模型回合", "、".join(f"{m}×{n}" for m, n in u.model_turns.items()))
        table.add_row("回合數", str(u.turns))
        table.add_row("input tokens", f"{u.input_tokens:,}")
        table.add_row("output tokens", f"{u.output_tokens:,}")
        if u.cost:
            table.add_row("credits/cost", f"{u.cost:.3f}")
        if u.context_limit:
            table.add_row("context 使用率", f"{u.context_pct:.1f}%（{u.context_tokens:,}/{u.context_limit:,}）")
        if u.compactions:
            table.add_row("自動壓縮次數", str(u.compactions))
        console.print(table)
        return None

    if action == "memory":
        text = read_memory()
        if text.strip():
            console.print(f"[dim]{MEMORY_PATH}[/dim]")
            console.print(text)
        else:
            console.print(f"記憶是空的。agent 可用 memory_save 寫入，或手動編輯 {MEMORY_PATH}")
        return None

    if action == "model":
        if not arg:
            try:
                entries = await session.fetch_model_entries()
                table = Table(title="可用模型（/model <id> 釘選；/model auto 啟用本地路由）")
                table.add_column("id")
                table.add_column("倍率", justify="right")
                table.add_column("vision")
                table.add_column("context", justify="right")
                for e in entries:
                    if not e.enabled:
                        continue
                    table.add_row(
                        e.id, f"{e.multiplier}x", "Y" if e.vision else "-",
                        f"{e.context_window:,}" if e.context_window else "?",
                    )
                console.print(table)
                if session.auto_router:
                    r = session.auto_router
                    console.print(f"[dim]auto 路由中：地板 {r.floor.id} / 升級 {r.strong.id}[/dim]")
            except Exception as e:
                console.print(f"[yellow]無法取得模型清單: {e}[/yellow]")
            return None
        if arg.lower() == "auto":
            if await session.enable_auto():
                console.print("已啟用 [bold]auto[/bold]（waagent 本地路由，非 Copilot auto）。")
            return None
        try:
            session.disable_auto()  # 手動釘選 = 關掉 auto
            await session.set_model(arg)
            console.print(f"已釘選模型 [bold]{arg}[/bold]（auto 路由已停用，/model auto 可恢復）。")
        except Exception as e:
            console.print(f"[red]切換模型失敗: {e}[/red]")
        return None

    if action == "resume":
        if not arg:
            infos = await session.list_stored_sessions()
            if not infos:
                console.print("沒有可接續的 session。")
                return None
            table = Table(title="可接續的 session（/resume <session_id>）")
            table.add_column("session_id")
            table.add_column("更新時間")
            table.add_column("摘要")
            for info in infos:
                table.add_row(info.session_id, info.updated_at, info.summary)
            console.print(table)
            return None
        await session.close()
        new_session = await _open_session(config, mode, resume=arg)
        if new_session is not None:
            console.print(f"已接續 session [bold]{arg}[/bold]。")
        return new_session

    return None


async def _open_session(config: Config, mode: str, resume: str = "") -> ChatSession | None:
    specs = get_agent_specs(config)  # 每次重讀使用者規則資料夾與記憶

    callbacks = SessionCallbacks(
        on_delta=lambda text: console.print(text, end="", markup=False, highlight=False),
        on_tool_start=lambda name, args: console.print(
            f"\n[dim]-> {name}({args})[/dim]" if args else f"\n[dim]-> {name}[/dim]"
        ),
        on_notice=lambda msg: console.print(f"\n[yellow]{msg}[/yellow]"),
    )
    session = ChatSession(config, specs[mode], callbacks)
    try:
        with console.status("[dim]啟動 Copilot session…[/dim]"):
            await session.start(resume_session_id=resume)
        if session.session_id:
            console.print(f"[dim]session: {session.session_id}[/dim]")
        return session
    except CopilotNotInstalled as e:
        console.print(f"[red]{e}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Copilot session 啟動失敗: {e}[/red]")
        console.print("[dim]請確認：已登入（gh auth 或 COPILOT_GITHUB_TOKEN）、proxy 設定正確、"
                      "企業 policy 已啟用 Copilot SDK/CLI。可先跑 waagent doctor 檢查。[/dim]")
        return None


async def _send_and_render(session: ChatSession, text: str) -> None:
    try:
        await session.send(text)
    except KeyboardInterrupt:
        console.print("\n[yellow]（已中斷這一回合）[/yellow]")
        return
    console.print()  # streaming 收尾換行
    u = session.usage
    if u.context_limit:
        console.print(f"[dim]context {u.context_pct:.0f}% ・ in {u.input_tokens:,} / out {u.output_tokens:,} tokens[/dim]\n")
    else:
        console.print()

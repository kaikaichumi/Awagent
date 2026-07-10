"""waagent CLI：chat（預設）、scan、report、doctor。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from waagent import __version__
from waagent.config import Config, load_config
from waagent.net import apply_network_env, network_report

app = typer.Typer(add_completion=False, help="AWS Well-Architected AI agent（GitHub Copilot 驅動）")
console = Console()


def _bootstrap() -> Config:
    config = load_config()
    apply_network_env(config)  # proxy/CA 在任何對外連線前生效
    return config


async def _copilot_auth_status():
    """doctor 用：啟動 runtime 查認證狀態後立即關閉。"""
    from copilot import CopilotClient

    client = CopilotClient()
    await client.start()
    try:
        return await client.get_auth_status()
    finally:
        await client.stop()


@app.callback(invoke_without_command=True)
def default(ctx: typer.Context):
    """不帶子命令時直接進入 chat REPL。"""
    if ctx.invoked_subcommand is None:
        chat()


@app.command()
def chat(
    mode: str = typer.Option("coder", "--mode", "-m", help="啟動模式：coder / aws-debug / wa-review"),
    resume: str = typer.Option("", "--resume", "-r", help="接續指定 session id（REPL 內 /resume 可列出）"),
):
    """互動 REPL（類 Claude Code 使用方式）。"""
    from waagent.chat.repl import run_repl

    config = _bootstrap()
    asyncio.run(run_repl(config, initial_mode=mode, resume=resume))


@app.command()
def login(
    target: str = typer.Argument("aws", help="aws（IAM Identity Center，Kiro 式）或 github（Copilot）"),
):
    """登入：waagent login = AWS SSO；waagent login github = GitHub Copilot。"""
    config = _bootstrap()
    if target.lower() == "github":
        _login_github()
        return
    _login_aws(config)


def _login_github():
    """GitHub Copilot 登入：呼叫內附 runtime（Copilot CLI）的 OAuth 裝置流。"""
    import subprocess

    try:
        from copilot._cli_download import get_cached_cli_path

        exe = get_cached_cli_path()
    except ImportError:
        console.print("[red]github-copilot-sdk 未安裝。[/red]")
        raise typer.Exit(1)
    if not exe:
        console.print("[red]找不到 Copilot runtime。[/red]請先執行 python -m copilot download-runtime")
        raise typer.Exit(1)

    console.print("[dim]啟動 GitHub Copilot 裝置登入（瀏覽器將跳出授權頁）…[/dim]")
    result = subprocess.run([exe, "login"])
    if result.returncode == 0:
        console.print("[green]GitHub Copilot 登入完成。[/green]執行 waagent chat 開始使用。")
    else:
        console.print(
            "[red]登入未完成。[/red]備援：設定環境變數 COPILOT_GITHUB_TOKEN"
            "（有 Copilot 授權之帳號的 token）後重試。"
        )
        raise typer.Exit(1)


def _login_aws(config: Config):
    """IAM Identity Center 裝置登入（Kiro 式：瀏覽器 + 帳密 + MFA）。"""
    from rich.prompt import Prompt

    from waagent import awssso

    if not config.aws.sso_start_url:
        console.print(
            "[red]尚未設定 SSO。[/red]請在 config.toml 的 [aws] 填：\n"
            '  sso_start_url = "https://<公司>.awsapps.com/start"   # 同 Kiro 登入畫面的 Start URL\n'
            '  sso_region    = "us-east-1"                          # 同 Kiro 登入畫面的 Region'
        )
        raise typer.Exit(1)
    try:
        awssso.device_login(
            config,
            prompt=lambda text: Prompt.ask(text),
            echo=lambda text: console.print(text),
        )
        console.print(f"[green]完成。[/green]{awssso.login_status(config)}")
    except Exception as e:
        from waagent.scan.runner import friendly_aws_error

        console.print(f"[red]登入失敗: {friendly_aws_error(e)}[/red]")
        raise typer.Exit(1)


@app.command()
def scan(
    services: list[str] = typer.Option(None, "--service", "-s", help="限定服務（可重複）"),
    regions: list[str] = typer.Option(None, "--region", "-r", help="限定區域（可重複）"),
):
    """執行 AWS 掃描與規則引擎（不動用 LLM，可排程使用）。"""
    from waagent.scan.runner import friendly_aws_error, run_scan

    config = _bootstrap()
    try:
        digest = run_scan(
            config,
            services=list(services) if services else None,
            regions=list(regions) if regions else None,
            progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
        )
    except Exception as e:
        console.print(f"[red]{friendly_aws_error(e, config.aws.profile)}[/red]")
        raise typer.Exit(1)
    table = Table(title=f"run {digest.run_id}（帳號 {digest.account_id}）")
    table.add_column("Pillar")
    table.add_column("Findings", justify="right")
    table.add_column("依嚴重度")
    for pillar, stats in digest.pillar_stats.items():
        detail = " ".join(f"{sev}×{count}" for sev, count in stats.by_severity.items())
        table.add_row(pillar, str(stats.total), detail)
    console.print(table)


@app.command()
def report(
    run_id: str = typer.Option(None, "--run", help="run id（省略 = 最新）"),
    output: str = typer.Option(None, "--output", "-o", help="輸出目錄"),
):
    """用既有 narrative.json 重新渲染報告（改模板後不必重跑 LLM）。"""
    from waagent.report.pipeline import Narrative, render_reports
    from waagent.report.userrules import load_user_templates
    from waagent.scan import snapshot

    config = _bootstrap()
    rid = run_id or snapshot.latest_run_id()
    if not rid:
        console.print("[red]尚無掃描結果，請先執行 waagent scan。[/red]")
        raise typer.Exit(1)

    narrative_path = snapshot.run_dir(rid) / "narrative.json"
    if narrative_path.is_file():
        narrative = Narrative.model_validate_json(narrative_path.read_text(encoding="utf-8"))
    else:
        console.print("[yellow]此 run 尚無 narrative（未經 wa-review 評估），改用純數據模板。[/yellow]")
        narrative = Narrative(executive_summary="（本報告僅含掃描數據，尚未經 AI 評估。）")

    user = load_user_templates(config.wa.templates_dir)
    md, html = render_reports(rid, narrative, user, output or config.wa.output_dir or ".")
    console.print(f"已產生：\n  {md}\n  {html}")


@app.command()
def doctor():
    """逐項檢查：設定 → proxy → Copilot → AWS → WA Tool → 模板資料夾。"""
    config = _bootstrap()
    ok = True

    console.print("[bold]1. 設定檔[/bold]")
    if config.sources:
        for source in config.sources:
            console.print(f"  [green]OK[/green]  {source}")
    else:
        console.print("  [yellow]WARN[/yellow] 未找到設定檔，全部使用預設值（參考 config.example.toml）")

    console.print("[bold]2. 網路（proxy / CA）[/bold]")
    for key, value in network_report(config):
        console.print(f"  {key}: {value}")

    console.print("[bold]3. GitHub Copilot SDK[/bold]")
    try:
        import copilot  # noqa: F401

        console.print("  [green]OK[/green]  github-copilot-sdk 已安裝")
    except ImportError:
        console.print("  [red]FAIL[/red] 未安裝：pip install github-copilot-sdk && python -m copilot download-runtime")
        ok = False
    token_keys = [k for k in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN") if os.environ.get(k)]
    if token_keys:
        console.print(f"  [green]OK[/green]  找到 token 環境變數: {', '.join(token_keys)}")
    # 真實認證檢查：啟動 runtime 問 auth 狀態（含 proxy 驗證）
    try:
        auth = asyncio.run(asyncio.wait_for(_copilot_auth_status(), timeout=30))
        if getattr(auth, "is_authenticated", False):
            user = getattr(auth, "login", "") or "?"
            console.print(f"  [green]OK[/green]  Copilot 已登入（{user}）")
        else:
            console.print("  [red]FAIL[/red] Copilot 未登入——執行 waagent login github")
            ok = False
    except Exception as e:
        console.print(f"  [red]FAIL[/red] Copilot runtime 啟動/認證檢查失敗: {e}")
        console.print("        （公司網路請先確認第 2 關 proxy；未登入請執行 waagent login github）")
        ok = False

    console.print("[bold]4. AWS 憑證與連線[/bold]")
    try:
        from waagent import awssso
        from waagent.scan.runner import friendly_aws_error, get_account_id

        status = awssso.login_status(config)
        if status:
            console.print(f"  {status}")
        # fast=True：診斷用短超時（5s 連線/10s 讀取、不重試），網路不通時快速失敗
        account = get_account_id(config, fast=True)
        console.print(f"  [green]OK[/green]  sts get-caller-identity OK（帳號 {account}）")
    except Exception as e:
        console.print(f"  [red]FAIL[/red] AWS 連線失敗: {friendly_aws_error(e, config.aws.profile)}")
        ok = False

    console.print("[bold]5. Well-Architected Tool API[/bold]")
    try:
        from waagent.wa.watool import WaTool

        lenses = WaTool(config, fast=True).list_lenses()
        console.print(f"  [green]OK[/green]  list-lenses OK（{len(lenses)} 個 lens）")
    except Exception as e:
        console.print(
            f"  [red]FAIL[/red] WA Tool API 失敗（檢查 IAM wellarchitected:* 讀取權限）: "
            f"{friendly_aws_error(e, config.aws.profile)}"
        )
        ok = False

    console.print("[bold]6. 報告模板資料夾[/bold]")
    if not config.wa.templates_dir:
        console.print("  [cyan]INFO[/cyan] 未設定 templates_dir，將使用內建模板")
    elif Path(config.wa.templates_dir).is_dir():
        from waagent.report.userrules import load_user_templates

        user = load_user_templates(config.wa.templates_dir)
        console.print(
            f"  [green]OK[/green]  {config.wa.templates_dir}（規則 {len(user.rules_text)} 字元、"
            f"自訂模板 md={'有' if user.md_template else '無'} html={'有' if user.html_template else '無'}）"
        )
    else:
        console.print(f"  [red]FAIL[/red] templates_dir 不存在: {config.wa.templates_dir}")
        ok = False

    console.print("[bold]7. MCP / skills[/bold]")
    if not config.mcp and not config.copilot.skill_directories:
        console.print("  [cyan]INFO[/cyan] 未設定 MCP servers / skills")
    else:
        for name, server in config.mcp.items():
            command = server.get("command", "")
            url = server.get("url", "")
            if command:
                if shutil.which(command):
                    console.print(f"  [green]OK[/green]  MCP {name}: command={command}")
                else:
                    console.print(f"  [yellow]WARN[/yellow] MCP {name}: 找不到執行檔 {command}")
            elif url:
                console.print(f"  [cyan]INFO[/cyan] MCP {name}: url={url}")
        for skill_dir in config.copilot.skill_directories:
            if Path(skill_dir).is_dir():
                console.print(f"  [green]OK[/green]  skill 目錄: {skill_dir}")
            else:
                console.print(f"  [yellow]WARN[/yellow] skill 目錄不存在: {skill_dir}")

    raise typer.Exit(0 if ok else 1)


@app.command()
def runs():
    """列出歷史掃描 run。"""
    from waagent.scan import snapshot

    _bootstrap()
    if not snapshot.RUNS_DIR.is_dir():
        console.print("尚無掃描紀錄。")
        return
    table = Table(title=str(snapshot.RUNS_DIR))
    table.add_column("run_id")
    table.add_column("帳號")
    table.add_column("findings", justify="right")
    for d in sorted(snapshot.RUNS_DIR.iterdir(), reverse=True):
        meta = snapshot.read_meta(d.name)
        findings_path = d / "findings.json"
        count = len(json.loads(findings_path.read_text(encoding="utf-8"))) if findings_path.is_file() else 0
        table.add_row(d.name, meta.account_id if meta else "?", str(count))
    console.print(table)


@app.command()
def diff(
    old_run: str = typer.Argument(None, help="舊 run id（省略 = 倒數第二次）"),
    new_run: str = typer.Argument(None, help="新 run id（省略 = 最新）"),
):
    """比較兩次掃描：已修復 / 新增 / 未變（修正後驗證用）。"""
    from waagent.scan import snapshot
    from waagent.scan.diff import compare_runs

    _bootstrap()
    runs = sorted(
        (d.name for d in snapshot.RUNS_DIR.iterdir() if (d / "findings.json").is_file()),
        reverse=True,
    ) if snapshot.RUNS_DIR.is_dir() else []
    new_run = new_run or (runs[0] if runs else None)
    old_run = old_run or (runs[1] if len(runs) > 1 else None)
    if not old_run or not new_run:
        console.print("[red]需要至少兩次掃描才能比較（waagent runs 查看）。[/red]")
        raise typer.Exit(1)

    result = compare_runs(old_run, new_run)
    console.print(
        f"[bold]{old_run} → {new_run}[/bold]：[green]已修復 {len(result.fixed)}[/green] / "
        f"[red]新增 {len(result.added)}[/red] / 未變 {result.unchanged_count}"
    )
    for label, items, style in (("已修復", result.fixed, "green"), ("新增", result.added, "red")):
        if not items:
            continue
        table = Table(title=label)
        table.add_column("嚴重度")
        table.add_column("規則")
        table.add_column("資源")
        table.add_column("區域")
        for f in items:
            table.add_row(f"[{style}]{f.severity.value}[/{style}]", f.title, f.resource, f.region)
        console.print(table)


@app.command()
def memory():
    """顯示 waagent 長期記憶（agent 用 memory_save 寫入、可手動編輯）。"""
    from waagent.memory import MEMORY_PATH, read_memory

    text = read_memory()
    if text.strip():
        console.print(f"[dim]{MEMORY_PATH}[/dim]")
        console.print(text)
    else:
        console.print(f"記憶是空的（{MEMORY_PATH}）。")


@app.command()
def version():
    console.print(f"waagent {__version__}")


def main():
    # 舊版 Windows 主控台（cp950）防呆：避免中文/符號輸出直接崩潰
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    app()


if __name__ == "__main__":
    main()

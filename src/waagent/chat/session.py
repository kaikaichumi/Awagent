"""Copilot SDK 隔離層。

SDK（2026/6 GA）之後若 API 變動，只需要改這裡與 agents/registry.py。
事件類別以名稱比對，避免依賴 SDK 內部模組路徑。

啟用的 SDK 能力：
- infinite sessions：context 用到 80% 背景自動壓縮、95% 阻塞等壓縮完成
- SDK 原生 memory + session store（可 resume）
- usage 事件：每回合 token/credits 統計、context 使用率
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from waagent.agents.registry import AgentSpec, make_sdk_tools
from waagent.chat.router import AutoRouter, ModelEntry, RouterBuildError, build_router
from waagent.config import Config


class CopilotNotInstalled(RuntimeError):
    pass


class CopilotAuthRequired(RuntimeError):
    pass


AUTH_GUIDE = (
    "GitHub Copilot 尚未登入。請執行：\n"
    "  waagent login github\n"
    "（跳瀏覽器 OAuth 授權；或設定環境變數 COPILOT_GITHUB_TOKEN）"
)


def _import_sdk():
    try:
        from copilot import CopilotClient  # type: ignore

        return CopilotClient
    except ImportError as e:
        raise CopilotNotInstalled(
            "找不到 github-copilot-sdk。請執行：\n"
            "  pip install github-copilot-sdk\n"
            "  python -m copilot download-runtime"
        ) from e


@dataclass
class Attachment:
    path: str = ""
    data: str = ""  # base64
    mime_type: str = "image/png"

    def to_sdk(self) -> dict:
        if self.path:
            return {"type": "file", "path": self.path}
        return {"type": "blob", "data": self.data, "mimeType": self.mime_type}


@dataclass
class UsageStats:
    """跨回合累計的用量統計（/usage 顯示）。"""

    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    model: str = ""
    context_tokens: int = 0
    context_limit: int = 0
    compactions: int = 0
    model_turns: dict[str, int] = field(default_factory=dict)  # 各模型使用回合數

    @property
    def context_pct(self) -> float:
        return self.context_tokens / self.context_limit * 100 if self.context_limit else 0.0


@dataclass
class SessionCallbacks:
    on_delta: Callable[[str], None] = lambda _t: None
    on_tool_start: Callable[[str, str], None] = lambda _n, _a: None
    on_notice: Callable[[str], None] = lambda _m: None


@dataclass
class SessionInfo:
    session_id: str = ""
    mode: str = ""
    summary: str = ""
    updated_at: str = ""


def _build_mcp_servers(mcp: dict[str, dict]) -> dict[str, dict]:
    """把 config.mcp（TOML [mcp.<name>] 原樣內容）轉成 SDK 的 MCPServerConfig dict。

    SDK schema（copilot.session 內的 MCPStdioServerConfig / MCPHTTPServerConfig）：
    - stdio 型：command（必要）、args、env、working_directory、type="local"/"stdio"（可省略）
    - http 型：url（必要）、headers、type="http"/"sse"（省略時 SDK 預設 "http"）
    使用者填什麼欄位就照傳，只在 command 型缺 type 時補上明確的 "stdio"。
    """
    servers: dict[str, dict] = {}
    for name, raw in mcp.items():
        server = dict(raw)
        if "command" in server and "type" not in server:
            server["type"] = "stdio"
        servers[name] = server
    return servers


def _needs_vision_switch(has_attachments: bool, vision_model: str, current_model: str) -> bool:
    """純函式：本回合是否該切到 vision_model（不依賴 SDK，方便單元測試）。"""
    return bool(has_attachments and vision_model and vision_model != current_model)


class ChatSession:
    """一個模式（agent spec）對應一個 SDK session。"""

    def __init__(self, config: Config, spec: AgentSpec, callbacks: SessionCallbacks):
        self._config = config
        self._spec = spec
        self._cb = callbacks
        self._client: Any = None
        self._session: Any = None
        self._idle = asyncio.Event()
        self._pending_attachments: list[Attachment] = []
        self.usage = UsageStats()
        self.session_id: str = ""
        self.current_model: str = ""
        self.auto_router: AutoRouter | None = None

    @property
    def mode(self) -> str:
        return self._spec.name

    # ---- 生命週期 ----

    async def start(self, resume_session_id: str = "") -> None:
        CopilotClient = _import_sdk()
        self._client = CopilotClient()
        await self._client.start()

        # 認證預檢：在 create_session 前把「未登入」轉成明確指引，
        # 避免之後才收到難懂的 SessionErrorData(type=authentication)
        try:
            status = await self._client.get_auth_status()
            if not getattr(status, "is_authenticated", True):
                raise CopilotAuthRequired(AUTH_GUIDE)
            user = getattr(status, "login", "") or ""
            if user:
                self._cb.on_notice(f"Copilot 已登入：{user}")
        except CopilotAuthRequired:
            await self._client.stop()
            raise
        except Exception:
            pass  # 狀態查詢失敗不擋流程，讓後續錯誤自然浮現

        if self._config.copilot.model.lower() == "auto":
            await self._init_auto_router()

        kwargs = self._session_kwargs()
        if resume_session_id:
            self._session = await self._client.resume_session(resume_session_id, **kwargs)
        else:
            self._session = await self._client.create_session(**kwargs)
        self._session.on(self._on_event)
        self.session_id = getattr(self._session, "session_id", "") or ""
        if not self.session_id:
            try:
                self.session_id = await self._client.get_last_session_id() or ""
            except Exception:
                pass

    async def _init_auto_router(self) -> None:
        """建立本地路由器（非 Copilot auto）：抓企業已啟用模型清單解析地板/升級。"""
        cp = self._config.copilot
        try:
            entries = await self.fetch_model_entries()
            self.auto_router = build_router(
                entries,
                floor_pattern=cp.auto_floor,
                strong_pattern=cp.auto_strong,
                keywords=cp.auto_keywords or None,
            )
            self._cb.on_notice(
                f"auto 路由啟用：地板 {self.auto_router.floor.id}"
                f"（{self.auto_router.floor.multiplier}x）/ 升級 {self.auto_router.strong.id}"
                f"（{self.auto_router.strong.multiplier}x）"
            )
        except (RouterBuildError, Exception) as e:  # noqa: BLE001 — 路由失敗不擋使用
            self.auto_router = None
            self._cb.on_notice(f"auto 路由停用（{e}），改用 SDK 預設模型。")

    async def fetch_model_entries(self) -> list[ModelEntry]:
        models = await self._client.list_models()
        entries: list[ModelEntry] = []
        for m in models:
            policy = getattr(m, "policy", None)
            billing = getattr(m, "billing", None)
            caps = getattr(m, "capabilities", None)
            supports = getattr(caps, "supports", None)
            limits = getattr(caps, "limits", None)
            entries.append(
                ModelEntry(
                    id=getattr(m, "id", "") or "",
                    multiplier=(getattr(billing, "multiplier", None) or 1.0),
                    vision=bool(getattr(supports, "vision", False)),
                    context_window=(getattr(limits, "max_context_window_tokens", None) or 0),
                    enabled=(getattr(policy, "state", "enabled") != "disabled"),
                )
            )
        return [e for e in entries if e.id]

    def _session_kwargs(self) -> dict:
        cp = self._config.copilot
        if self.auto_router is not None:
            model = self.auto_router.floor.id  # auto：session 以地板模型開場
        elif cp.model.lower() == "auto":
            model = None  # 路由器建立失敗：交給 SDK 預設
        else:
            model = cp.model
        self.current_model = model or ""
        kwargs: dict = {
            "streaming": True,
            "working_directory": os.getcwd(),
            "on_permission_request": self._on_permission,
            # context 超限處理：80% 背景壓縮、95% 阻塞等壓縮
            "infinite_sessions": {
                "enabled": True,
                "background_compaction_threshold": cp.compaction_start,
                "buffer_exhaustion_threshold": cp.compaction_block,
            },
            # SDK 原生對話記憶 + session 持久化（resume 用）
            "memory": {"enabled": True},
            "enable_session_store": True,
        }
        if model:
            kwargs["model"] = model
        if cp.reasoning_effort:
            kwargs["reasoning_effort"] = cp.reasoning_effort
        if cp.context_tier:
            kwargs["context_tier"] = cp.context_tier
        if cp.max_ai_credits > 0:
            kwargs["session_limits"] = {"max_ai_credits": cp.max_ai_credits}
        if self._config.mcp:
            kwargs["mcp_servers"] = _build_mcp_servers(self._config.mcp)
        if cp.skill_directories:
            kwargs["skill_directories"] = [
                str(Path(d).expanduser().resolve()) for d in cp.skill_directories
            ]
            kwargs["enable_skills"] = True

        tools = make_sdk_tools(self._spec, self._config)
        if tools:
            kwargs["tools"] = tools
        if self._spec.system_message:
            kwargs["system_message"] = {"mode": "append", "content": self._spec.system_message}
        if not self._spec.builtin_tools:
            # 唯讀評估模式：排除全部 SDK 內建工具（shell/檔案編輯），只留自訂工具
            from copilot import ToolSet  # type: ignore

            kwargs["excluded_tools"] = ToolSet().add_builtin("*")
        return kwargs

    async def close(self) -> None:
        try:
            if self._session is not None:
                await self._session.disconnect()
        finally:
            if self._client is not None:
                await self._client.stop()

    # ---- 對話 ----

    def queue_attachment(self, attachment: Attachment) -> None:
        self._pending_attachments.append(attachment)

    @property
    def has_pending_attachments(self) -> bool:
        return bool(self._pending_attachments)

    async def send(self, text: str) -> None:
        """送出訊息並等到回合結束（SessionIdle）。Ctrl+C 會 abort 這一回合。"""
        self._idle.clear()
        kwargs: dict = {}
        has_attachments = bool(self._pending_attachments)
        if has_attachments:
            kwargs["attachments"] = [a.to_sdk() for a in self._pending_attachments]
            self._pending_attachments.clear()

        # 圖片回合：暫時切到 vision_model（手動釘選模式送完會還原；auto 模式讓路由器接手）
        vision_model = self._config.copilot.vision_model
        prev_model = self.current_model
        switch_vision = _needs_vision_switch(has_attachments, vision_model, self.current_model)
        if switch_vision:
            await self.set_model(vision_model)
            self._cb.on_notice(f"圖片回合改用 {vision_model}")

        try:
            await self._session.send(text, **kwargs)
            await asyncio.wait_for(self._idle.wait(), timeout=self._config.copilot.turn_timeout)
        except (asyncio.CancelledError, KeyboardInterrupt):
            await self.abort()
            raise
        except asyncio.TimeoutError:
            await self.abort()
            self._cb.on_notice(f"回合超過 {self._config.copilot.turn_timeout:.0f}s，已中斷。")
        else:
            if switch_vision and self.auto_router is None:
                await self.set_model(prev_model)
        self.usage.turns += 1
        used = self.current_model or self.usage.model or "(default)"
        self.usage.model_turns[used] = self.usage.model_turns.get(used, 0) + 1

    async def abort(self) -> None:
        try:
            await self._session.abort()
        except Exception:
            pass

    async def set_model(self, model: str) -> None:
        await self._session.set_model(model)
        self.usage.model = model
        self.current_model = model

    async def enable_auto(self) -> bool:
        """/model auto：重建本地路由器。回傳是否成功。"""
        await self._init_auto_router()
        if self.auto_router and self.current_model != self.auto_router.floor.id:
            await self.set_model(self.auto_router.floor.id)
        return self.auto_router is not None

    def disable_auto(self) -> None:
        self.auto_router = None

    async def route_before_send(self, text: str, has_image: bool) -> str | None:
        """auto 模式：回合前路由。有切換時回傳說明文字，否則 None。"""
        if self.auto_router is None:
            return None
        decision = self.auto_router.decide(
            text,
            has_image=has_image,
            context_tokens=self.usage.context_tokens,
            compaction_start=self._config.copilot.compaction_start,
        )
        if decision.model_id != self.current_model:
            await self.set_model(decision.model_id)
            return f"[auto] 本回合 {decision.model_id}（{decision.reason}）"
        return None

    async def list_stored_sessions(self, limit: int = 10) -> list[SessionInfo]:
        try:
            metas = await self._client.list_sessions()
        except Exception:
            return []
        infos = []
        for m in metas[:limit]:
            infos.append(
                SessionInfo(
                    session_id=getattr(m, "session_id", "") or getattr(m, "id", ""),
                    summary=(getattr(m, "summary", "") or getattr(m, "title", "") or "")[:60],
                    updated_at=str(getattr(m, "updated_at", "") or getattr(m, "modified_at", ""))[:19],
                )
            )
        return infos

    # ---- 權限與事件 ----

    async def _on_permission(self, request: Any) -> bool:
        """內建工具權限逐次在終端確認。"""
        from rich.prompt import Confirm

        desc = getattr(request, "description", None) or str(request)
        return await asyncio.to_thread(
            Confirm.ask, f"[yellow]允許動作?[/yellow] {desc}", default=True
        )

    def _on_event(self, event: Any) -> None:
        data = getattr(event, "data", event)
        name = type(data).__name__
        if name == "AssistantMessageDeltaData":
            self._cb.on_delta(getattr(data, "delta_content", "") or "")
        elif name == "AssistantMessageData":
            content = getattr(data, "content", "") or ""
            if content:
                self._cb.on_delta(content)
        elif name == "ToolExecutionStartData":
            args = str(getattr(data, "arguments", "") or "")
            self._cb.on_tool_start(str(getattr(data, "tool_name", "")), args[:120])
        elif name == "AssistantUsageData":
            self.usage.model = getattr(data, "model", "") or self.usage.model
            self.usage.input_tokens += getattr(data, "input_tokens", 0) or 0
            self.usage.output_tokens += getattr(data, "output_tokens", 0) or 0
            self.usage.cost += getattr(data, "cost", 0.0) or 0.0
        elif name == "SessionUsageInfoData":
            self.usage.context_tokens = getattr(data, "current_tokens", 0) or 0
            self.usage.context_limit = getattr(data, "token_limit", 0) or 0
        elif name == "SessionCompactionStartData":
            self.usage.compactions += 1
            self._cb.on_notice("context 接近上限，背景壓縮中…")
        elif name == "SessionCompactionCompleteData":
            self._cb.on_notice("context 壓縮完成。")
        elif name in ("SessionIdleData", "AssistantIdleData"):
            self._idle.set()
        elif name == "SessionErrorData":
            detail = str(data)
            if "authentication" in detail.lower():
                self._cb.on_notice(f"session 認證錯誤。{AUTH_GUIDE}")
            else:
                self._cb.on_notice(f"session 錯誤: {detail}")
            self._idle.set()

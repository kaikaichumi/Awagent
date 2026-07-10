"""本地 auto 模型路由器——不是 Copilot 的 auto。

每回合由這裡的「決定性規則」選出具體模型 id，再以 set_model() 明確指定；
Copilot 端永遠看到手動指定的模型，其伺服器端 auto 路由完全不介入。
規則、地板、升級模型全部由使用者 config 控制。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_UPGRADE_KEYWORDS = [
    # 深度任務訊號（可在 config [copilot] auto_keywords 覆蓋）
    "設計", "架構", "重構", "根因", "評估", "報告", "深入", "比較方案", "權衡",
    "為什麼", "遷移", "資安", "安全性分析",
    "design", "architect", "refactor", "root cause", "migrate", "trade-off", "why",
]


@dataclass
class ModelEntry:
    """從 SDK ModelInfo 萃取的路由用資訊。"""

    id: str
    multiplier: float = 1.0
    vision: bool = False
    context_window: int = 0
    enabled: bool = True


@dataclass
class RouteDecision:
    model_id: str
    reason: str
    switched_by_rule: str = ""


@dataclass
class AutoRouter:
    floor: ModelEntry
    strong: ModelEntry
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_UPGRADE_KEYWORDS))
    long_threshold: int = 500  # 訊息超過此字元數 → strong
    sticky_threshold: int = 200  # 上回合 strong、本則短跟進 → 維持 strong
    last_was_strong: bool = False

    def decide(
        self,
        text: str,
        *,
        has_image: bool = False,
        context_tokens: int = 0,
        compaction_start: float = 0.80,
    ) -> RouteDecision:
        target, reason = self._classify(text, has_image)

        # context 防護：目標模型的 context 若裝不下目前對話（會觸發即時壓縮），維持地板/現狀
        if (
            target.id == self.strong.id
            and self.strong.context_window
            and context_tokens > self.strong.context_window * compaction_start
        ):
            target, reason = self.floor, "context 已接近升級模型上限，維持地板避免觸發壓縮"

        self.last_was_strong = target.id == self.strong.id
        return RouteDecision(model_id=target.id, reason=reason)

    def _classify(self, text: str, has_image: bool) -> tuple[ModelEntry, str]:
        lowered = text.lower()

        if has_image:
            if self.strong.vision:
                return self.strong, "圖片分析"
            return self.floor, "附圖但升級模型不支援 vision，使用地板"

        hit = next((kw for kw in self.keywords if kw.lower() in lowered), None)
        if hit:
            return self.strong, f"關鍵詞「{hit}」"

        if len(text) >= self.long_threshold:
            return self.strong, f"長需求描述（{len(text)} 字元）"

        if self.last_was_strong and len(text) < self.sticky_threshold:
            return self.strong, "延續上一回合的深度任務（黏性）"

        return self.floor, "一般查詢/操作"


class RouterBuildError(RuntimeError):
    pass


def build_router(
    entries: list[ModelEntry],
    *,
    floor_pattern: str,
    strong_pattern: str = "",
    keywords: list[str] | None = None,
) -> AutoRouter:
    """從企業已啟用的模型清單解析地板與升級模型。

    floor_pattern / strong_pattern 用「不分大小寫子字串」比對 model id。
    strong_pattern 留空 = 自動選倍率最高者（同倍率取 context 較大者）。
    """
    available = [e for e in entries if e.enabled]
    if not available:
        raise RouterBuildError("沒有任何企業 policy 啟用的模型")

    floor = _match(available, floor_pattern, prefer="cheapest")
    if floor is None:
        raise RouterBuildError(
            f"找不到符合地板 pattern「{floor_pattern}」的模型；"
            f"可用：{', '.join(e.id for e in available)}"
        )

    if strong_pattern:
        strong = _match(available, strong_pattern, prefer="strongest")
        if strong is None:
            raise RouterBuildError(
                f"找不到符合升級 pattern「{strong_pattern}」的模型；"
                f"可用：{', '.join(e.id for e in available)}"
            )
    else:
        # 自動：倍率不低於地板的模型中，選 (multiplier, context_window) 最大者
        candidates = [e for e in available if e.multiplier >= floor.multiplier]
        strong = max(candidates, key=lambda e: (e.multiplier, e.context_window))

    return AutoRouter(floor=floor, strong=strong, keywords=keywords or list(DEFAULT_UPGRADE_KEYWORDS))


def _match(entries: list[ModelEntry], pattern: str, prefer: str = "cheapest") -> ModelEntry | None:
    """子字串比對。多個命中時：地板取最便宜（同價取 context 大），升級取最強。

    這樣「sonnet」不會誤選到高價變體、「gpt-5」不會誤選到 gpt-5-mini。
    """
    hits = [e for e in entries if pattern.lower() in e.id.lower()]
    if not hits:
        return None
    if prefer == "strongest":
        return max(hits, key=lambda e: (e.multiplier, e.context_window))
    return min(hits, key=lambda e: (e.multiplier, -e.context_window))

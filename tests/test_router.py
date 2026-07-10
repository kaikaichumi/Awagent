"""auto 模型路由器測試（純函式，不需 SDK/AWS）。"""

from __future__ import annotations

import pytest

from waagent.chat.router import (
    AutoRouter,
    ModelEntry,
    RouterBuildError,
    build_router,
)

CATALOG = [
    ModelEntry(id="gpt-5-mini", multiplier=0.0, vision=True, context_window=128_000),
    ModelEntry(id="claude-sonnet-4.6", multiplier=1.0, vision=True, context_window=200_000),
    ModelEntry(id="claude-opus-4.8", multiplier=5.0, vision=True, context_window=200_000),
    ModelEntry(id="gpt-5", multiplier=3.0, vision=True, context_window=272_000),
    ModelEntry(id="disabled-huge", multiplier=10.0, vision=True, context_window=1_000_000, enabled=False),
]


def _router(**kwargs) -> AutoRouter:
    return build_router(CATALOG, floor_pattern="sonnet", **kwargs)


def test_build_resolves_floor_and_auto_strong():
    r = _router()
    assert r.floor.id == "claude-sonnet-4.6"
    # 自動選最強：排除 policy disabled，倍率最高 = opus
    assert r.strong.id == "claude-opus-4.8"


def test_build_explicit_strong_prefers_strongest_variant():
    r = _router(strong_pattern="gpt-5")
    # 「gpt-5」同時命中 gpt-5 與 gpt-5-mini，升級語意要選強的那個
    assert r.strong.id == "gpt-5"


def test_build_unknown_floor_raises():
    with pytest.raises(RouterBuildError):
        build_router(CATALOG, floor_pattern="gemini")


def test_mini_below_floor_never_selected():
    r = _router()
    for text in ("列出 s3 bucket", "hi", "查一下 log"):
        decision = r.decide(text)
        assert decision.model_id != "gpt-5-mini"
        assert decision.model_id == r.floor.id


def test_keyword_upgrades():
    r = _router()
    assert r.decide("幫我設計這個系統的架構").model_id == r.strong.id
    assert r.decide("please refactor this module").model_id == r.strong.id


def test_image_upgrades():
    r = _router()
    assert r.decide("看一下這張圖", has_image=True).model_id == r.strong.id


def test_long_message_upgrades():
    r = _router()
    assert r.decide("x" * 600).model_id == r.strong.id


def test_sticky_follow_up_stays_strong_then_downgrades():
    r = _router()
    r.decide("幫我設計這個系統的架構")
    assert r.decide("繼續").model_id == r.strong.id  # 短跟進維持 strong
    # 中等長度、無關鍵詞的新話題 → 回到地板（黏性只保護短跟進）
    assert r.decide("好，那接下來換個完全不相關的主題，" + "內容" * 120).model_id == r.floor.id


def test_plain_query_after_plain_query_stays_floor():
    r = _router()
    r.decide("列出 findings")
    assert r.decide("下一個").model_id == r.floor.id


def test_context_guard_blocks_upgrade():
    r = _router(strong_pattern="gpt-5")
    decision = r.decide("幫我設計架構", context_tokens=250_000, compaction_start=0.80)
    # 272k * 0.8 = 217.6k < 250k → 不升級
    assert decision.model_id == r.floor.id
    assert "壓縮" in decision.reason

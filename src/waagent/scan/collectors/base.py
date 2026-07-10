"""Collector 基底：強制唯讀 API、統一分頁。"""

from __future__ import annotations

from abc import ABC, abstractmethod

READONLY_PREFIXES = ("describe_", "list_", "get_", "head_")


class ReadOnlyViolation(RuntimeError):
    pass


class Collector(ABC):
    """一個 AWS service 一個 collector。回傳的 dict 會原樣寫進 raw/。"""

    service: str = ""
    global_service: bool = False  # True 則只在第一個 region 執行一次（IAM/S3 list 等）

    @abstractmethod
    def collect(self, session, region: str, boto_cfg) -> dict:
        """回傳 raw dict。內部一律使用 self.call() 呼叫 AWS API。"""

    def call(self, client, method: str, result_key: str | None = None, **kwargs):
        """唯讀 API 呼叫；有 paginator 就自動翻頁。

        result_key 提供時回傳彙整後的 list，否則回傳單次呼叫的 dict。
        """
        if not method.startswith(READONLY_PREFIXES):
            raise ReadOnlyViolation(f"collector 禁止呼叫非唯讀 API: {method}")
        if result_key and client.can_paginate(method):
            items: list = []
            for page in client.get_paginator(method).paginate(**kwargs):
                items.extend(page.get(result_key, []))
            return items
        response = getattr(client, method)(**kwargs)
        response.pop("ResponseMetadata", None)
        return response[result_key] if result_key else response

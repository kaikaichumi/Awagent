"""AWS Well-Architected Tool API 包裝（boto3 wellarchitected）。

唯讀操作直接執行；寫入操作（update_answer / create_* ）由呼叫端負責
先向使用者顯示 diff 並確認——本模組不做互動。
"""

from __future__ import annotations

import base64
from pathlib import Path

from waagent.config import Config
from waagent.net import boto_config


class WaTool:
    def __init__(self, config: Config, *, fast: bool = False):
        from waagent.awssso import make_boto_session

        session = make_boto_session(config)
        region = config.aws.regions[0] if config.aws.regions else "us-east-1"
        self._client = session.client(
            "wellarchitected", region_name=region, config=boto_config(config, fast=fast)
        )
        self._lens = config.wa.lens_alias or "wellarchitected"

    # ---- 唯讀 ----

    def list_workloads(self) -> list[dict]:
        pages = self._client.get_paginator("list_workloads").paginate()
        return [w for page in pages for w in page["WorkloadSummaries"]]

    def list_lenses(self) -> list[dict]:
        return self._client.list_lenses()["LensSummaries"]

    def get_lens_review(self, workload_id: str) -> dict:
        return self._client.get_lens_review(WorkloadId=workload_id, LensAlias=self._lens)[
            "LensReview"
        ]

    def list_answers(self, workload_id: str, pillar_id: str | None = None) -> list[dict]:
        kwargs: dict = {"WorkloadId": workload_id, "LensAlias": self._lens}
        if pillar_id:
            kwargs["PillarId"] = pillar_id
        pages = self._client.get_paginator("list_answers").paginate(**kwargs)
        return [a for page in pages for a in page["AnswerSummaries"]]

    def get_answer(self, workload_id: str, question_id: str) -> dict:
        return self._client.get_answer(
            WorkloadId=workload_id, LensAlias=self._lens, QuestionId=question_id
        )["Answer"]

    # ---- 寫入（呼叫端須先經使用者確認）----

    def create_workload(
        self, name: str, description: str, environment: str, regions: list[str]
    ) -> str:
        resp = self._client.create_workload(
            WorkloadName=name,
            Description=description,
            Environment=environment,  # PRODUCTION | PREPRODUCTION
            AwsRegions=regions,
            Lenses=[self._lens],
            ReviewOwner="waagent",
        )
        return resp["WorkloadId"]

    def update_answer(
        self,
        workload_id: str,
        question_id: str,
        selected_choices: list[str],
        notes: str = "",
    ) -> dict:
        return self._client.update_answer(
            WorkloadId=workload_id,
            LensAlias=self._lens,
            QuestionId=question_id,
            SelectedChoices=selected_choices,
            Notes=notes[:2084],  # API 上限
        )["Answer"]

    def create_milestone(self, workload_id: str, name: str) -> int:
        resp = self._client.create_milestone(WorkloadId=workload_id, MilestoneName=name)
        return resp["MilestoneNumber"]

    def export_lens_report(self, workload_id: str, output_path: str | Path) -> Path:
        """WA Tool 官方 lens review PDF 報告。"""
        resp = self._client.get_lens_review_report(
            WorkloadId=workload_id, LensAlias=self._lens
        )
        data = base64.b64decode(resp["LensReviewReport"]["Base64String"])
        path = Path(output_path)
        path.write_bytes(data)
        return path

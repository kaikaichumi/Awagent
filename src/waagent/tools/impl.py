"""給 Copilot agent 的工具實作（純 Python，不 import SDK）。

每個函式回傳給 LLM 的文字。SDK 的 Tool 包裝在 agents/registry.py 完成。
寫入 WA Tool 的動作在這裡直接於終端顯示內容並要求使用者確認。
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.prompt import Confirm

from waagent.config import Config
from waagent.memory import MEMORY_PATH, append_memory
from waagent.report.pipeline import Narrative, render_reports
from waagent.report.userrules import load_user_templates
from waagent.scan import snapshot
from waagent.scan.diff import compare_runs, diff_summary_for_llm
from waagent.scan.runner import run_scan
from waagent.wa.watool import WaTool

console = Console()

_MAX_TOOL_OUTPUT = 8_000  # 回傳給 LLM 的字元上限，防止單次工具回應灌爆 context


def _clip(text: str) -> str:
    if len(text) <= _MAX_TOOL_OUTPUT:
        return text
    return text[:_MAX_TOOL_OUTPUT] + f"\n...[輸出過長已截斷，原始長度 {len(text)} 字元；請縮小查詢範圍]"


def tool_aws_scan(config: Config, services: list[str] | None, regions: list[str] | None) -> str:
    digest = run_scan(
        config,
        services=services or None,
        regions=regions or None,
        progress=lambda msg: console.print(f"[dim]  scan: {msg}[/dim]"),
    )
    total = sum(s.total for s in digest.pillar_stats.values())
    return (
        f"掃描完成。run_id={digest.run_id}，帳號 {digest.account_id}，"
        f"區域 {', '.join(digest.regions)}，共 {total} 條 findings。"
        f"呼叫 get_scan_digest 取得摘要。"
    )


def tool_get_scan_digest(config: Config, run_id: str | None) -> str:
    rid = run_id or snapshot.latest_run_id()
    if not rid:
        return "尚無任何掃描結果，請先執行 aws_scan。"
    digest = snapshot.read_digest(rid)
    if digest is None:
        return f"run {rid} 沒有 digest。"
    return digest.model_dump_json()


def tool_get_finding_detail(config: Config, finding_id: str) -> str:
    rid = snapshot.latest_run_id()
    if not rid:
        return "尚無任何掃描結果。"
    for f in snapshot.read_findings(rid):
        if f.id == finding_id:
            return f.model_dump_json()
    return f"找不到 finding {finding_id}。"


def tool_template_rules_load(config: Config) -> str:
    user = load_user_templates(config.wa.templates_dir)
    if not user.source_dir:
        return "未設定 templates_dir，使用內建報告模板與預設寫作風格。"
    parts = [f"模板資料夾: {user.source_dir}"]
    if user.rules_text:
        parts.append(f"--- 使用者寫作規則 ---\n{user.rules_text}")
    parts.append(f"自訂 md 模板: {'有' if user.md_template else '無（用內建）'}")
    parts.append(f"自訂 html 模板: {'有' if user.html_template else '無（用內建）'}")
    if user.other_files:
        parts.append(f"其他參考檔案: {', '.join(user.other_files)}")
    return "\n".join(parts)


def tool_report_render(config: Config, run_id: str | None, narrative_json: str) -> str:
    rid = run_id or snapshot.latest_run_id()
    if not rid:
        return "尚無掃描結果，請先執行 aws_scan。"
    try:
        narrative = Narrative.model_validate_json(narrative_json)
    except Exception as e:  # 把 schema 錯誤回饋給 LLM 讓它修正
        return f"narrative JSON 不符 schema，請修正後重試: {e}"
    user = load_user_templates(config.wa.templates_dir)
    md, html = render_reports(rid, narrative, user, config.wa.output_dir or ".")
    return f"報告已產生：\n- Markdown: {md}\n- HTML: {html}"


_WRITE_ACTIONS = {"create_workload", "update_answer", "create_milestone"}


def tool_wa_tool_sync(config: Config, action: str, payload_json: str = "{}") -> str:
    try:
        payload: dict = json.loads(payload_json or "{}")
    except json.JSONDecodeError as e:
        return f"payload 不是合法 JSON: {e}"

    wa = WaTool(config)
    workload_id = payload.get("workload_id") or config.wa.workload_id

    if action in _WRITE_ACTIONS:
        console.print("\n[bold yellow]WA Tool 寫入動作待確認[/bold yellow]")
        console.print(f"[yellow]action[/yellow]: {action}")
        console.print_json(json.dumps(payload, ensure_ascii=False))
        if not Confirm.ask("確定要寫入 AWS Well-Architected Tool 嗎?", default=False):
            return "使用者拒絕了這次寫入，動作已取消。"

    if action == "list_workloads":
        return json.dumps(wa.list_workloads(), ensure_ascii=False, default=str)
    if action == "get_lens_review":
        return json.dumps(wa.get_lens_review(workload_id), ensure_ascii=False, default=str)
    if action == "list_answers":
        return json.dumps(
            wa.list_answers(workload_id, payload.get("pillar_id")),
            ensure_ascii=False,
            default=str,
        )
    if action == "get_answer":
        return json.dumps(
            wa.get_answer(workload_id, payload["question_id"]), ensure_ascii=False, default=str
        )
    if action == "create_workload":
        wid = wa.create_workload(
            payload["name"],
            payload.get("description", "Created by waagent"),
            payload.get("environment", "PREPRODUCTION"),
            payload.get("regions", config.aws.regions),
        )
        return f"已建立 workload: {wid}"
    if action == "update_answer":
        answer = wa.update_answer(
            workload_id,
            payload["question_id"],
            payload.get("selected_choices", []),
            payload.get("notes", ""),
        )
        return f"已更新答案 {payload['question_id']}，risk={answer.get('Risk')}"
    if action == "create_milestone":
        num = wa.create_milestone(workload_id, payload["name"])
        return f"已建立 milestone #{num}"
    if action == "export_report":
        path = wa.export_lens_report(workload_id, payload.get("output_path", "wa-lens-report.pdf"))
        return f"官方 lens review PDF 已存至 {path}"

    return (
        f"不支援的 action: {action}。可用：list_workloads / get_lens_review / list_answers / "
        f"get_answer / create_workload / update_answer / create_milestone / export_report"
    )


# ---------------------------------------------------------------------------
# AWS 除錯工具（aws-debug / wa-review 模式用，一律唯讀）
# ---------------------------------------------------------------------------

_READONLY_PREFIXES = ("describe_", "list_", "get_", "head_", "lookup_", "filter_", "search_")


def _aws_client(config: Config, service: str, region: str | None = None):
    import boto3

    from waagent.net import boto_config

    session = (
        boto3.Session(profile_name=config.aws.profile) if config.aws.profile else boto3.Session()
    )
    return session.client(
        service,
        region_name=region or (config.aws.regions[0] if config.aws.regions else None),
        config=boto_config(config),
    )


def tool_aws_describe(
    config: Config,
    service: str,
    operation: str,
    params_json: str = "{}",
    region: str | None = None,
) -> str:
    """通用唯讀 boto3 呼叫：任何 describe_/list_/get_ 操作都能查。"""
    if not operation.startswith(_READONLY_PREFIXES):
        return f"拒絕：{operation} 不是唯讀操作（僅允許 {'/'.join(_READONLY_PREFIXES)} 前綴）。"
    try:
        params = json.loads(params_json or "{}")
    except json.JSONDecodeError as e:
        return f"params_json 不是合法 JSON: {e}"
    client = _aws_client(config, service, region)
    response = getattr(client, operation)(**params)
    if isinstance(response, dict):
        response.pop("ResponseMetadata", None)
    return _clip(json.dumps(response, ensure_ascii=False, default=str, indent=1))


def tool_aws_logs_insights(
    config: Config,
    log_group: str,
    query: str | None = None,
    minutes: int | None = 60,
    region: str | None = None,
) -> str:
    """CloudWatch Logs Insights 查詢；query 省略時預設抓最近的 ERROR。"""
    import time
    from datetime import datetime, timedelta, timezone

    logs = _aws_client(config, "logs", region)
    query = query or (
        "fields @timestamp, @message | filter @message like /(?i)(error|exception|fail)/ "
        "| sort @timestamp desc | limit 50"
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes or 60)
    qid = logs.start_query(
        logGroupName=log_group,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=query,
    )["queryId"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = logs.get_query_results(queryId=qid)
        if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1.5)
    if result["status"] != "Complete":
        return f"查詢未完成（狀態 {result['status']}）。"
    rows = [
        {f["field"].lstrip("@"): f["value"] for f in row if f["field"] != "@ptr"}
        for row in result.get("results", [])
    ]
    if not rows:
        return f"最近 {minutes} 分鐘 {log_group} 無符合結果（query: {query}）。"
    return _clip(json.dumps(rows, ensure_ascii=False, indent=1))


def tool_cloudtrail_events(
    config: Config,
    lookup_key: str | None = None,
    lookup_value: str | None = None,
    minutes: int | None = 1440,
    region: str | None = None,
) -> str:
    """查 CloudTrail 管理事件——「是誰在什麼時候改了什麼」。

    lookup_key: ResourceName / EventName / Username / ResourceType / EventSource
    """
    from datetime import datetime, timedelta, timezone

    ct = _aws_client(config, "cloudtrail", region)
    kwargs: dict = {
        "StartTime": datetime.now(timezone.utc) - timedelta(minutes=minutes or 1440),
        "EndTime": datetime.now(timezone.utc),
        "MaxResults": 50,
    }
    if lookup_key and lookup_value:
        kwargs["LookupAttributes"] = [{"AttributeKey": lookup_key, "AttributeValue": lookup_value}]
    events = ct.lookup_events(**kwargs).get("Events", [])
    if not events:
        return "區間內查無事件。"
    compact = [
        {
            "time": str(e.get("EventTime", "")),
            "event": e.get("EventName", ""),
            "user": e.get("Username", ""),
            "resources": [r.get("ResourceName", "") for r in e.get("Resources", [])][:3],
        }
        for e in events
    ]
    return _clip(json.dumps(compact, ensure_ascii=False, indent=1))


def tool_cloudwatch_metrics(
    config: Config,
    namespace: str,
    metric_name: str,
    dimensions_json: str = "{}",
    minutes: int | None = 180,
    stat: str | None = "Average",
    region: str | None = None,
) -> str:
    """抓 CloudWatch metric 統計（如 AWS/EC2 CPUUtilization、AWS/RDS DatabaseConnections）。"""
    from datetime import datetime, timedelta, timezone

    try:
        dims = json.loads(dimensions_json or "{}")
    except json.JSONDecodeError as e:
        return f"dimensions_json 不是合法 JSON: {e}"
    cw = _aws_client(config, "cloudwatch", region)
    minutes = minutes or 180
    period = max(60, (minutes * 60) // 100 // 60 * 60 or 60)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=[{"Name": k, "Value": v} for k, v in dims.items()],
        StartTime=datetime.now(timezone.utc) - timedelta(minutes=minutes),
        EndTime=datetime.now(timezone.utc),
        Period=period,
        Statistics=[stat or "Average"],
    )
    points = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
    if not points:
        return "區間內無資料點（確認 namespace/metric/dimensions 是否正確）。"
    rows = [
        {"time": str(p["Timestamp"]), "value": round(p.get(stat or "Average", 0), 3)}
        for p in points
    ]
    return _clip(json.dumps(rows, ensure_ascii=False))


def tool_compare_runs(config: Config, old_run: str | None = None, new_run: str | None = None) -> str:
    """比較兩次掃描（省略 = 最近兩次）：已修復 / 新增 / 未變。"""
    runs = sorted(
        (d.name for d in snapshot.RUNS_DIR.iterdir() if (d / "findings.json").is_file()),
        reverse=True,
    ) if snapshot.RUNS_DIR.is_dir() else []
    if not new_run:
        new_run = runs[0] if runs else None
    if not old_run:
        old_run = runs[1] if len(runs) > 1 else None
    if not old_run or not new_run:
        return "需要至少兩次掃描才能比較。"
    return diff_summary_for_llm(compare_runs(old_run, new_run))


def tool_memory_save(config: Config, topic: str, content: str) -> str:
    """把長期有用的事實寫入 waagent 記憶（下次 session 自動載入）。"""
    path = append_memory(topic, content)
    return f"已寫入記憶 {path}（主題：{topic}）。"


def tool_memory_show(config: Config) -> str:
    from waagent.memory import read_memory

    text = read_memory()
    return _clip(text) if text.strip() else f"記憶是空的（{MEMORY_PATH}）。"

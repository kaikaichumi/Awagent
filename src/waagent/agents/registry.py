"""模式（sub-agent）定義：coder（預設）與 wa-review。

這裡與 chat/session.py 是僅有的兩個 import Copilot SDK 的模組。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from waagent.config import Config
from waagent.memory import memory_for_prompt
from waagent.report.pipeline import narrative_json_schema
from waagent.report.userrules import load_user_templates
from waagent.tools import impl

WA_REVIEW_PROMPT = """\
你是 AWS Well-Architected（WA）評估專家，協助使用者以 WA Framework 六大支柱
（卓越營運、安全性、可靠性、效能、成本最佳化、永續性）評估 AWS 工作負載。

工作方式：
1. 先呼叫 template_rules_load 取得使用者的報告規則，全程遵守。
2. 用 aws_scan 掃描（或 get_scan_digest 讀取既有掃描）。digest 是精簡摘要；
   需要深入某條 finding 才呼叫 get_finding_detail，不要逐條全撈。
3. 使用者附上架構圖時，將圖中架構與掃描結果互相對照，指出圖上看得到但掃描
   資料中缺失的元件或風險。
4. 產生報告時呼叫 report_render，narrative 參數必須是符合下列 JSON Schema 的
   字串，內容使用繁體中文、依據使用者規則撰寫：
{narrative_schema}
5. 需要同步 AWS WA Tool（workload/答案/milestone）時使用 wa_tool_sync；
   寫入動作會由使用者在終端確認。
6. 評估判斷要引用具體 finding id 與資源作為證據，不得憑空臆測帳號內狀態；
   需要 digest 沒有的資訊時用 aws_describe 唯讀查詢補充。
7. 追蹤改善進度用 compare_runs 比較兩次掃描（搭配 WA Tool milestone）。
"""

AWS_DEBUG_PROMPT = """\
你是 AWS 除錯助手。除了一般開發工具外，你有一組唯讀 AWS 查詢工具：
- aws_describe：任意 boto3 唯讀操作（describe_/list_/get_）
- aws_logs_insights：CloudWatch Logs Insights 查日誌（預設抓 ERROR）
- cloudtrail_events：查「誰在什麼時候改了什麼」
- cloudwatch_metrics：查資源指標（CPU、連線數、錯誤率…）
- get_scan_digest / get_finding_detail：最近一次 WA 掃描的結果

除錯時先建立時間軸：錯誤何時開始（logs/metrics）→ 當時有什麼變更（cloudtrail）
→ 資源目前狀態（describe）。查詢從小範圍開始，避免一次撈大量資料。
發現長期有用的事實（帳號慣例、環境架構、已知問題）用 memory_save 記下來。
"""

MEMORY_PROMPT_TEMPLATE = """

=== waagent 長期記憶（跨 session；過時內容請提醒使用者清理）===
{memory}
=== 記憶結束 ===
你可以用 memory_save 工具把長期有用的事實寫入記憶。"""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler_name: str  # impl 模組內的函式名


@dataclass
class AgentSpec:
    name: str
    description: str
    system_message: str = ""  # 附加到 SDK 預設 system prompt
    tools: list[ToolSpec] = field(default_factory=list)
    builtin_tools: bool = True  # False 則以 excluded_tools 排除全部 SDK 內建工具


_WA_TOOLS = [
    ToolSpec(
        name="aws_scan",
        description="掃描 AWS 帳號資源並執行 Well-Architected 規則引擎，回傳 run_id。耗時較長，同一對話中除非使用者要求否則不要重複掃描。",
        parameters={
            "type": "object",
            "properties": {
                "services": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ec2", "rds", "s3", "iam", "cloudwatch", "backup", "lambda", "elb", "dynamodb", "cost", "trusted_advisor"]},
                    "description": "要掃描的服務，省略 = 全部",
                },
                "regions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要掃描的區域，省略 = 設定檔預設",
                },
            },
        },
        handler_name="tool_aws_scan",
    ),
    ToolSpec(
        name="get_scan_digest",
        description="取得掃描結果摘要（每支柱統計 + Top findings）。",
        parameters={
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "省略 = 最新一次"}},
        },
        handler_name="tool_get_scan_digest",
    ),
    ToolSpec(
        name="get_finding_detail",
        description="取得單一 finding 的完整證據與修正提示。",
        parameters={
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
        handler_name="tool_get_finding_detail",
    ),
    ToolSpec(
        name="template_rules_load",
        description="讀取使用者報告模板資料夾的寫作規則（每次評估開始時必呼叫）。",
        parameters={"type": "object", "properties": {}},
        handler_name="tool_template_rules_load",
    ),
    ToolSpec(
        name="report_render",
        description="以 narrative JSON 產生 Markdown + HTML 視覺化報告。",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "省略 = 最新一次掃描"},
                "narrative_json": {"type": "string", "description": "符合 narrative schema 的 JSON 字串"},
            },
            "required": ["narrative_json"],
        },
        handler_name="tool_report_render",
    ),
    ToolSpec(
        name="wa_tool_sync",
        description="操作 AWS Well-Architected Tool：list_workloads / get_lens_review / list_answers / get_answer / create_workload / update_answer / create_milestone / export_report。寫入動作需使用者於終端確認。",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "payload_json": {"type": "string", "description": "action 參數的 JSON 字串"},
            },
            "required": ["action"],
        },
        handler_name="tool_wa_tool_sync",
    ),
]

_MEMORY_TOOL = ToolSpec(
    name="memory_save",
    description="把長期有用的事實寫入 waagent 記憶（下次 session 自動載入）。只記跨 session 有價值的內容：帳號慣例、環境架構、使用者偏好、已知問題。",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "簡短主題"},
            "content": {"type": "string", "description": "記憶內容（精簡、事實性）"},
        },
        "required": ["topic", "content"],
    },
    handler_name="tool_memory_save",
)

_COMPARE_TOOL = ToolSpec(
    name="compare_runs",
    description="比較兩次 WA 掃描結果：已修復/新增/未變的 findings（省略參數 = 最近兩次）。",
    parameters={
        "type": "object",
        "properties": {
            "old_run": {"type": "string"},
            "new_run": {"type": "string"},
        },
    },
    handler_name="tool_compare_runs",
)

_AWS_DEBUG_TOOLS = [
    ToolSpec(
        name="aws_describe",
        description="通用 AWS 唯讀查詢：對任一 service 呼叫 describe_/list_/get_ 開頭的 boto3 操作。例：service=ec2, operation=describe_instances, params_json={\"InstanceIds\":[\"i-xxx\"]}",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "boto3 service 名，如 ec2/rds/lambda/ecs"},
                "operation": {"type": "string", "description": "唯讀操作名（snake_case）"},
                "params_json": {"type": "string", "description": "操作參數 JSON 字串"},
                "region": {"type": "string"},
            },
            "required": ["service", "operation"],
        },
        handler_name="tool_aws_describe",
    ),
    ToolSpec(
        name="aws_logs_insights",
        description="CloudWatch Logs Insights 查詢日誌。query 省略時預設抓最近的 ERROR/exception。",
        parameters={
            "type": "object",
            "properties": {
                "log_group": {"type": "string"},
                "query": {"type": "string", "description": "Logs Insights 查詢語法，省略 = 抓錯誤"},
                "minutes": {"type": "integer", "description": "回看幾分鐘，預設 60"},
                "region": {"type": "string"},
            },
            "required": ["log_group"],
        },
        handler_name="tool_aws_logs_insights",
    ),
    ToolSpec(
        name="cloudtrail_events",
        description="查 CloudTrail 管理事件：誰在什麼時候對什麼資源做了什麼。除錯「突然壞掉」時先查這個。",
        parameters={
            "type": "object",
            "properties": {
                "lookup_key": {"type": "string", "enum": ["ResourceName", "EventName", "Username", "ResourceType", "EventSource"]},
                "lookup_value": {"type": "string"},
                "minutes": {"type": "integer", "description": "回看幾分鐘，預設 1440（一天）"},
                "region": {"type": "string"},
            },
        },
        handler_name="tool_cloudtrail_events",
    ),
    ToolSpec(
        name="cloudwatch_metrics",
        description="查 CloudWatch metric 統計。例：namespace=AWS/EC2, metric_name=CPUUtilization, dimensions_json={\"InstanceId\":\"i-xxx\"}",
        parameters={
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "metric_name": {"type": "string"},
                "dimensions_json": {"type": "string"},
                "minutes": {"type": "integer", "description": "預設 180"},
                "stat": {"type": "string", "enum": ["Average", "Sum", "Maximum", "Minimum", "p99"]},
                "region": {"type": "string"},
            },
            "required": ["namespace", "metric_name"],
        },
        handler_name="tool_cloudwatch_metrics",
    ),
]


def get_agent_specs(config: Config) -> dict[str, AgentSpec]:
    """每次呼叫重建 system prompt（使用者規則資料夾與記憶會變動）。"""
    user = load_user_templates(config.wa.templates_dir)
    wa_prompt = WA_REVIEW_PROMPT.format(
        narrative_schema=json.dumps(narrative_json_schema(), ensure_ascii=False)
    )
    if user.rules_text:
        wa_prompt += f"\n\n=== 使用者報告規則（必須遵守）===\n{user.rules_text}\n"

    memory = memory_for_prompt()
    memory_block = MEMORY_PROMPT_TEMPLATE.format(memory=memory) if memory else ""

    return {
        "coder": AgentSpec(
            name="coder",
            description="日常 coding agent（SDK 內建工具全開，等同 Copilot CLI）",
            system_message=memory_block,
            tools=[_MEMORY_TOOL],
            builtin_tools=True,
        ),
        "aws-debug": AgentSpec(
            name="aws-debug",
            description="AWS 除錯模式（coding 工具 + 唯讀 AWS 查詢：logs/cloudtrail/metrics/describe）",
            system_message=AWS_DEBUG_PROMPT + memory_block,
            tools=[
                *_AWS_DEBUG_TOOLS,
                _MEMORY_TOOL,
                _COMPARE_TOOL,
                # 掃描結果也可查
                next(t for t in _WA_TOOLS if t.name == "get_scan_digest"),
                next(t for t in _WA_TOOLS if t.name == "get_finding_detail"),
            ],
            builtin_tools=True,
        ),
        "wa-review": AgentSpec(
            name="wa-review",
            description="AWS Well-Architected 評估模式（唯讀，停用 shell 與檔案編輯）",
            system_message=wa_prompt + memory_block,
            tools=[
                *_WA_TOOLS,
                _MEMORY_TOOL,
                _COMPARE_TOOL,
                next(t for t in _AWS_DEBUG_TOOLS if t.name == "aws_describe"),
            ],
            builtin_tools=False,
        ),
    }


def make_sdk_tools(spec: AgentSpec, config: Config) -> list:
    """把 ToolSpec 轉成 Copilot SDK 的 Tool 物件。"""
    from copilot.tools import Tool, ToolInvocation, ToolResult  # SDK import 收斂於此

    def make_handler(handler_name: str):
        fn = getattr(impl, handler_name)

        async def handler(invocation: ToolInvocation) -> ToolResult:
            args = dict(invocation.arguments or {})
            try:
                import asyncio

                text = await asyncio.to_thread(_call_impl, fn, config, args)
                return ToolResult(text_result_for_llm=text, result_type="success")
            except Exception as e:
                return ToolResult(text_result_for_llm=f"工具執行失敗: {e}", result_type="failure")

        return handler

    return [
        Tool(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
            handler=make_handler(t.handler_name),
        )
        for t in spec.tools
    ]


def _call_impl(fn, config: Config, args: dict) -> str:
    import inspect

    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in args.items() if k in params and k != "config"}
    for name, p in params.items():
        if name == "config" or name in kwargs:
            continue
        if p.default is inspect.Parameter.empty:
            kwargs[name] = None  # LLM 未提供且無預設值的參數補 None
    return fn(config, **kwargs)

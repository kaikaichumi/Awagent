"""決定性規則引擎：raw snapshot → Finding 清單。

每條規則綁定一個 service 的 raw 資料，yield (resource, one_line_evidence, evidence)。
pillar / severity / wa_question_id 都是規則的靜態屬性——LLM 不參與這一層。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable

from waagent.scan import snapshot
from waagent.scan.models import Finding, Severity
from waagent.wa.pillars import Pillar

# 規則函式：吃該 service 的 raw dict，yield (resource, one_line_evidence, evidence)
RuleFn = Callable[[dict], Iterable[tuple[str, str, dict]]]


@dataclass
class Rule:
    id: str
    service: str
    pillar: Pillar
    severity: Severity
    title: str
    fn: RuleFn
    remediation_hint: str = ""
    wa_question_id: str = ""


RULES: list[Rule] = []
_SEEN_IDS: set[str] = set()


def rule(
    *,
    id: str,
    service: str,
    pillar: Pillar,
    severity: Severity,
    title: str,
    remediation_hint: str = "",
    wa_question_id: str = "",
):
    def decorator(fn: RuleFn) -> RuleFn:
        if id in _SEEN_IDS:
            raise ValueError(f"重複的規則 id: {id}")
        _SEEN_IDS.add(id)
        RULES.append(
            Rule(
                id=id,
                service=service,
                pillar=pillar,
                severity=severity,
                title=title,
                fn=fn,
                remediation_hint=remediation_hint,
                wa_question_id=wa_question_id,
            )
        )
        return fn

    return decorator


def _finding_id(rule_id: str, resource: str) -> str:
    return f"{rule_id}-{hashlib.sha1(resource.encode()).hexdigest()[:6]}"


def run_checks(run_id: str) -> list[Finding]:
    findings: list[Finding] = []
    for service, region, data in snapshot.iter_raw(run_id):
        for r in RULES:
            if r.service != service:
                continue
            for resource, one_line, evidence in r.fn(data):
                findings.append(
                    Finding(
                        id=_finding_id(r.id, f"{region}:{resource}"),
                        rule_id=r.id,
                        pillar=r.pillar,
                        severity=r.severity,
                        title=r.title,
                        resource=resource,
                        region=region,
                        one_line_evidence=one_line,
                        evidence=evidence,
                        remediation_hint=r.remediation_hint,
                        wa_question_id=r.wa_question_id,
                    )
                )
    return findings

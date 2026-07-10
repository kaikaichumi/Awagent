"""snapshot 讀寫：~/.waagent/runs/<run_id>/{raw/, findings.json, digest.json, meta.json}"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from waagent.scan.models import (
    SEVERITY_ORDER,
    Digest,
    DigestFinding,
    Finding,
    PillarStats,
    RunMeta,
)

RUNS_DIR = Path.home() / ".waagent" / "runs"

# digest 大小控制：超過此數量的 findings 只保留嚴重度最高的 Top-N
DIGEST_MAX_FINDINGS = 120
_RESOURCE_MAX_LEN = 80


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def latest_run_id() -> str | None:
    if not RUNS_DIR.is_dir():
        return None
    runs = sorted((d.name for d in RUNS_DIR.iterdir() if (d / "digest.json").is_file()), reverse=True)
    return runs[0] if runs else None


def write_raw(run_id: str, service: str, region: str, data: dict) -> None:
    raw = run_dir(run_id) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / f"{service}_{region or 'global'}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=1), encoding="utf-8")


def read_raw(run_id: str, service: str, region: str) -> dict:
    path = run_dir(run_id) / "raw" / f"{service}_{region or 'global'}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def iter_raw(run_id: str):
    """yield (service, region, data)"""
    raw = run_dir(run_id) / "raw"
    if not raw.is_dir():
        return
    for path in sorted(raw.glob("*.json")):
        service, _, region = path.stem.rpartition("_")
        yield service, region, json.loads(path.read_text(encoding="utf-8"))


def write_findings(run_id: str, findings: list[Finding]) -> None:
    path = run_dir(run_id) / "findings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([f.model_dump(mode="json") for f in findings], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def read_findings(run_id: str) -> list[Finding]:
    path = run_dir(run_id) / "findings.json"
    if not path.is_file():
        return []
    return [Finding.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def write_meta(run_id: str, meta: RunMeta) -> None:
    path = run_dir(run_id) / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=1), encoding="utf-8")


def read_meta(run_id: str) -> RunMeta | None:
    path = run_dir(run_id) / "meta.json"
    return RunMeta.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None


def _shorten(resource: str) -> str:
    if len(resource) <= _RESOURCE_MAX_LEN:
        return resource
    return resource[: _RESOURCE_MAX_LEN - 3] + "..."


def build_digest(
    run_id: str,
    findings: list[Finding],
    *,
    account_id: str = "",
    regions: list[str] | None = None,
    resource_counts: dict[str, int] | None = None,
    collector_errors: list[str] | None = None,
) -> Digest:
    pillar_stats: dict[str, PillarStats] = {}
    for f in findings:
        stats = pillar_stats.setdefault(f.pillar.value, PillarStats())
        stats.total += 1
        stats.by_severity[f.severity.value] = stats.by_severity.get(f.severity.value, 0) + 1

    ranked = sorted(findings, key=lambda f: SEVERITY_ORDER.index(f.severity))
    truncated = len(ranked) > DIGEST_MAX_FINDINGS
    digest_findings = [
        DigestFinding(
            id=f.id,
            pillar=f.pillar,
            severity=f.severity,
            title=f.title,
            resource=_shorten(f.resource),
            evidence=f.one_line_evidence,
        )
        for f in ranked[:DIGEST_MAX_FINDINGS]
    ]

    return Digest(
        run_id=run_id,
        account_id=account_id,
        regions=regions or [],
        scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        resource_counts=resource_counts or {},
        pillar_stats=pillar_stats,
        findings=digest_findings,
        truncated=truncated,
        collector_errors=collector_errors or [],
    )


def write_digest(run_id: str, digest: Digest) -> None:
    path = run_dir(run_id) / "digest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest.model_dump_json(indent=1), encoding="utf-8")


def read_digest(run_id: str) -> Digest | None:
    path = run_dir(run_id) / "digest.json"
    return Digest.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

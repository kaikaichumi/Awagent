"""擴充服務（Lambda / ELB / DynamoDB / Trusted Advisor / Cost）的 collector + 規則測試。"""

from __future__ import annotations

import pytest

from waagent.scan import snapshot
from waagent.scan.checks import run_checks
from waagent.scan.collectors import (
    ALL_COLLECTORS,
    CostCollector,
    DynamoDbCollector,
    ElbCollector,
    LambdaCollector,
    TrustedAdvisorCollector,
)


@pytest.fixture
def run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "RUNS_DIR", tmp_path / "runs")
    return "test-run"


def _rule_ids(findings):
    return {f.rule_id for f in findings}


def test_new_collectors_registered():
    assert {
        LambdaCollector,
        ElbCollector,
        DynamoDbCollector,
        CostCollector,
        TrustedAdvisorCollector,
    } <= set(ALL_COLLECTORS)


# --- Lambda -------------------------------------------------------------------


def test_lambda_old_runtime_detected(run_id):
    snapshot.write_raw(run_id, "lambda", "ap-northeast-1", {
        "functions": [
            {"FunctionName": "legacy-fn", "Runtime": "python3.8"},
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "PERF-101" in ids
    assert "OPS-101" in ids  # 也沒有 DeadLetterConfig


def test_lambda_new_runtime_not_flagged(run_id):
    snapshot.write_raw(run_id, "lambda", "ap-northeast-1", {
        "functions": [
            {
                "FunctionName": "current-fn",
                "Runtime": "python3.12",
                "DeadLetterConfig": {"TargetArn": "arn:aws:sqs:...:dlq"},
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "PERF-101" not in ids
    assert "OPS-101" not in ids


# --- ELB ------------------------------------------------------------------------


def test_elb_http_only_detected(run_id):
    snapshot.write_raw(run_id, "elb", "ap-northeast-1", {
        "load_balancers": [
            {
                "LoadBalancerName": "web-lb",
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:...:web-lb",
                "AvailabilityZones": [{"ZoneName": "ap-northeast-1a"}],
                "Listeners": [{"Protocol": "HTTP", "Port": 80}],
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "SEC-101" in ids
    assert "REL-101" in ids  # 只有 1 個 AZ


def test_elb_with_https_not_flagged(run_id):
    snapshot.write_raw(run_id, "elb", "ap-northeast-1", {
        "load_balancers": [
            {
                "LoadBalancerName": "web-lb",
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:...:web-lb",
                "AvailabilityZones": [
                    {"ZoneName": "ap-northeast-1a"},
                    {"ZoneName": "ap-northeast-1c"},
                ],
                "Listeners": [
                    {"Protocol": "HTTP", "Port": 80},
                    {"Protocol": "HTTPS", "Port": 443},
                ],
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "SEC-101" not in ids
    assert "REL-101" not in ids


# --- DynamoDB ---------------------------------------------------------------------


def test_dynamodb_no_pitr_and_no_kms(run_id):
    snapshot.write_raw(run_id, "dynamodb", "ap-northeast-1", {
        "tables": [
            {
                "TableName": "orders",
                "ContinuousBackups": {
                    "ContinuousBackupsDescription": {
                        "PointInTimeRecoveryDescription": {
                            "PointInTimeRecoveryStatus": "DISABLED"
                        }
                    }
                },
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "REL-102" in ids
    assert "SEC-102" in ids


def test_dynamodb_pitr_and_kms_enabled_not_flagged(run_id):
    snapshot.write_raw(run_id, "dynamodb", "ap-northeast-1", {
        "tables": [
            {
                "TableName": "orders",
                "ContinuousBackups": {
                    "ContinuousBackupsDescription": {
                        "PointInTimeRecoveryDescription": {
                            "PointInTimeRecoveryStatus": "ENABLED"
                        }
                    }
                },
                "SSEDescription": {"Status": "ENABLED", "SSEType": "KMS"},
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "REL-102" not in ids
    assert "SEC-102" not in ids


# --- Trusted Advisor ----------------------------------------------------------


def test_trusted_advisor_error_produces_finding(run_id):
    snapshot.write_raw(run_id, "trusted_advisor", "global", {
        "available": True,
        "checks": [
            {
                "id": "check-1",
                "name": "Security Group 開放全網",
                "category": "security",
                "status": "error",
                "flagged_resources_count": 3,
            },
        ],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "TA-101" in ids


def test_trusted_advisor_unavailable_no_findings(run_id):
    snapshot.write_raw(run_id, "trusted_advisor", "global", {
        "available": False,
        "checks": [],
    })
    ids = _rule_ids(run_checks(run_id))
    assert "TA-101" not in ids
    assert "TA-102" not in ids
    assert "TA-103" not in ids


# --- Cost -----------------------------------------------------------------------


def test_cost_top_services_summary(run_id):
    snapshot.write_raw(run_id, "cost", "global", {
        "available": True,
        "by_service": [
            {"service": "Amazon EC2", "amount_usd": 123.45},
            {"service": "Amazon RDS", "amount_usd": 67.89},
            {"service": "Amazon S3", "amount_usd": 12.0},
            {"service": "AWS Lambda", "amount_usd": 5.5},
            {"service": "Amazon DynamoDB", "amount_usd": 3.2},
            {"service": "Amazon CloudWatch", "amount_usd": 1.1},
        ],
    })
    findings = [f for f in run_checks(run_id) if f.rule_id == "COST-101"]
    assert len(findings) == 1
    evidence = findings[0].one_line_evidence
    assert "Amazon EC2 $123.45" in evidence
    assert "Amazon CloudWatch" not in evidence  # 只取前 5 大


def test_cost_unavailable_no_finding(run_id):
    snapshot.write_raw(run_id, "cost", "global", {"available": False, "by_service": []})
    ids = _rule_ids(run_checks(run_id))
    assert "COST-101" not in ids

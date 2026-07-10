"""checks 規則引擎測試：fixture raw → findings，不需要 AWS。"""

from __future__ import annotations

import pytest

from waagent.scan import snapshot
from waagent.scan.checks import run_checks
from waagent.scan.models import Severity
from waagent.wa.pillars import Pillar


@pytest.fixture
def run_id(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "RUNS_DIR", tmp_path / "runs")
    return "test-run"


def _rule_ids(findings):
    return {f.rule_id for f in findings}


def test_sg_open_ssh_detected(run_id):
    snapshot.write_raw(run_id, "ec2", "ap-northeast-1", {
        "security_groups": [{
            "GroupId": "sg-123",
            "GroupName": "web",
            "IpPermissions": [{
                "FromPort": 22, "ToPort": 22, "IpProtocol": "tcp",
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [],
            }],
        }],
    })
    findings = run_checks(run_id)
    assert "SEC-001" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "SEC-001")
    assert f.severity == Severity.CRITICAL
    assert f.pillar == Pillar.SECURITY
    assert "SSH" in f.one_line_evidence
    assert f.region == "ap-northeast-1"


def test_sg_restricted_not_flagged(run_id):
    snapshot.write_raw(run_id, "ec2", "ap-northeast-1", {
        "security_groups": [{
            "GroupId": "sg-456",
            "GroupName": "internal",
            "IpPermissions": [{
                "FromPort": 22, "ToPort": 22, "IpProtocol": "tcp",
                "IpRanges": [{"CidrIp": "10.0.0.0/8"}], "Ipv6Ranges": [],
            }],
        }],
    })
    assert "SEC-001" not in _rule_ids(run_checks(run_id))


def test_rds_rules(run_id):
    snapshot.write_raw(run_id, "rds", "ap-northeast-1", {
        "db_instances": [{
            "DBInstanceIdentifier": "prod-db",
            "Engine": "mysql",
            "MultiAZ": False,
            "StorageEncrypted": False,
            "PubliclyAccessible": True,
            "BackupRetentionPeriod": 0,
        }],
        "db_clusters": [],
    })
    ids = _rule_ids(run_checks(run_id))
    assert {"REL-001", "REL-002", "SEC-009", "SEC-010"} <= ids


def test_s3_rules(run_id):
    snapshot.write_raw(run_id, "s3", "global", {
        "buckets": [{
            "Name": "my-bucket",
            "Versioning": {},
            "Encryption": None,
            "PublicAccessBlock": None,
            "Lifecycle": None,
        }],
    })
    ids = _rule_ids(run_checks(run_id))
    assert {"SEC-003", "SEC-004", "REL-004", "COST-005"} <= ids


def test_iam_root_mfa(run_id):
    snapshot.write_raw(run_id, "iam", "global", {
        "users": [],
        "account_summary": {"AccountMFAEnabled": 0},
        "password_policy": None,
    })
    ids = _rule_ids(run_checks(run_id))
    assert "SEC-005" in ids
    assert "SEC-008" in ids


def test_cost_unattached_volume(run_id):
    snapshot.write_raw(run_id, "ec2", "ap-northeast-1", {
        "volumes": [
            {"VolumeId": "vol-1", "State": "available", "Size": 100, "VolumeType": "gp2", "Encrypted": True},
            {"VolumeId": "vol-2", "State": "in-use", "Size": 50, "VolumeType": "gp3", "Encrypted": True},
        ],
    })
    findings = [f for f in run_checks(run_id) if f.rule_id == "COST-001"]
    assert len(findings) == 1
    assert findings[0].resource == "vol-1"


def test_finding_ids_stable(run_id):
    raw = {"volumes": [{"VolumeId": "vol-1", "State": "available", "Size": 1, "Encrypted": True}]}
    snapshot.write_raw(run_id, "ec2", "ap-northeast-1", raw)
    first = {f.id for f in run_checks(run_id)}
    second = {f.id for f in run_checks(run_id)}
    assert first == second

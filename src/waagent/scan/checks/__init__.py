from waagent.scan.checks.engine import run_checks

# import 觸發規則註冊
from waagent.scan.checks import (  # noqa: F401
    rules_cost,
    rules_ops,
    rules_reliability,
    rules_security,
    rules_services,
)

__all__ = ["run_checks"]

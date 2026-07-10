"""WA 六大支柱常數與顯示名稱。"""

from __future__ import annotations

from enum import StrEnum


class Pillar(StrEnum):
    OPERATIONAL_EXCELLENCE = "operationalExcellence"
    SECURITY = "security"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    COST_OPTIMIZATION = "costOptimization"
    SUSTAINABILITY = "sustainability"


# WA Tool API 的 PillarId 就是上面的值（wellarchitected lens 定義）
PILLAR_NAMES_ZH: dict[Pillar, str] = {
    Pillar.OPERATIONAL_EXCELLENCE: "卓越營運",
    Pillar.SECURITY: "安全性",
    Pillar.RELIABILITY: "可靠性",
    Pillar.PERFORMANCE: "效能",
    Pillar.COST_OPTIMIZATION: "成本最佳化",
    Pillar.SUSTAINABILITY: "永續性",
}

PILLAR_NAMES_EN: dict[Pillar, str] = {
    Pillar.OPERATIONAL_EXCELLENCE: "Operational Excellence",
    Pillar.SECURITY: "Security",
    Pillar.RELIABILITY: "Reliability",
    Pillar.PERFORMANCE: "Performance Efficiency",
    Pillar.COST_OPTIMIZATION: "Cost Optimization",
    Pillar.SUSTAINABILITY: "Sustainability",
}

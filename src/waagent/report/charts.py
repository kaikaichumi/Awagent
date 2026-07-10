"""純 Python 產生 inline SVG 圖表：零 CDN、零 JS，離線可開。

輸出皆為 <svg> 字串，直接嵌入 HTML 報告。
"""

from __future__ import annotations

import math

from waagent.scan.models import SEVERITY_ORDER, Digest
from waagent.wa.pillars import PILLAR_NAMES_ZH, Pillar

SEVERITY_COLORS = {
    "critical": "#c0392b",
    "high": "#e67e22",
    "medium": "#f1c40f",
    "low": "#3498db",
    "info": "#95a5a6",
}

_SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1, "info": 0.5}


def pillar_risk_scores(digest: Digest) -> dict[Pillar, float]:
    """每 pillar 加權風險分數，正規化 0–100（100 = 該次掃描中風險最高的 pillar）。"""
    raw: dict[Pillar, float] = {p: 0.0 for p in Pillar}
    for pillar_id, stats in digest.pillar_stats.items():
        score = sum(
            _SEVERITY_WEIGHT.get(sev, 0) * count for sev, count in stats.by_severity.items()
        )
        raw[Pillar(pillar_id)] = score
    peak = max(raw.values()) or 1.0
    return {p: round(v / peak * 100, 1) for p, v in raw.items()}


def radar_chart(digest: Digest, size: int = 420) -> str:
    """六軸 pillar 風險雷達圖。"""
    scores = pillar_risk_scores(digest)
    pillars = list(Pillar)
    cx = cy = size / 2
    radius = size / 2 - 70

    def point(idx: int, ratio: float) -> tuple[float, float]:
        angle = -math.pi / 2 + idx * 2 * math.pi / len(pillars)
        return (cx + radius * ratio * math.cos(angle), cy + radius * ratio * math.sin(angle))

    parts = [
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Pillar risk radar">'
    ]
    # 同心格線
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, ring) for i in range(6)))
        parts.append(
            f'<polygon points="{ring_pts}" fill="none" stroke="#d0d7de" stroke-width="1"/>'
        )
    # 軸線與標籤
    for i, p in enumerate(pillars):
        x, y = point(i, 1.0)
        lx, ly = point(i, 1.22)
        parts.append(
            f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#d0d7de" stroke-width="1"/>'
        )
        anchor = "middle" if abs(lx - cx) < radius * 0.3 else ("start" if lx > cx else "end")
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="13" '
            f'fill="#333">{PILLAR_NAMES_ZH[p]} ({scores[p]:.0f})</text>'
        )
    # 分數多邊形
    pts = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in (point(i, max(scores[p] / 100, 0.02)) for i, p in enumerate(pillars))
    )
    parts.append(
        f'<polygon points="{pts}" fill="#e6735533" stroke="#e67355" stroke-width="2"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def pillar_bar_chart(digest: Digest, width: int = 640) -> str:
    """每 pillar 的 findings 依 severity 堆疊長條圖。"""
    bar_h, gap, label_w, legend_h = 28, 12, 110, 30
    pillars = list(Pillar)
    height = len(pillars) * (bar_h + gap) + legend_h + 10
    max_total = max((s.total for s in digest.pillar_stats.values()), default=0) or 1
    chart_w = width - label_w - 60

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Findings by pillar">'
    ]
    y = 10
    for p in pillars:
        stats = digest.pillar_stats.get(p.value)
        parts.append(
            f'<text x="{label_w - 8}" y="{y + bar_h / 2 + 4}" text-anchor="end" '
            f'font-size="13" fill="#333">{PILLAR_NAMES_ZH[p]}</text>'
        )
        x = float(label_w)
        total = stats.total if stats else 0
        if stats:
            for sev in SEVERITY_ORDER:
                count = stats.by_severity.get(sev.value, 0)
                if not count:
                    continue
                w = count / max_total * chart_w
                parts.append(
                    f'<rect x="{x:.1f}" y="{y}" width="{max(w, 2):.1f}" height="{bar_h}" '
                    f'fill="{SEVERITY_COLORS[sev.value]}"/>'
                )
                x += w
        parts.append(
            f'<text x="{x + 6:.1f}" y="{y + bar_h / 2 + 4}" font-size="12" fill="#666">{total}</text>'
        )
        y += bar_h + gap
    # legend
    lx = label_w
    for sev in SEVERITY_ORDER:
        parts.append(f'<rect x="{lx}" y="{y}" width="12" height="12" fill="{SEVERITY_COLORS[sev.value]}"/>')
        parts.append(f'<text x="{lx + 16}" y="{y + 10}" font-size="11" fill="#555">{sev.value}</text>')
        lx += 90
    parts.append("</svg>")
    return "".join(parts)


def severity_donut(digest: Digest, size: int = 220) -> str:
    """整體 severity 分布 donut。"""
    counts: dict[str, int] = {}
    for stats in digest.pillar_stats.values():
        for sev, count in stats.by_severity.items():
            counts[sev] = counts.get(sev, 0) + count
    total = sum(counts.values())
    cx = cy = size / 2
    r, stroke = size / 2 - 30, 30

    parts = [
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Severity distribution">'
    ]
    if total == 0:
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#2ecc71" stroke-width="{stroke}"/>'
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="16" fill="#333">0 項</text></svg>'
        )
        return "".join(parts)

    circumference = 2 * math.pi * r
    offset = 0.0
    for sev in SEVERITY_ORDER:
        count = counts.get(sev.value, 0)
        if not count:
            continue
        frac = count / total
        dash = frac * circumference
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{SEVERITY_COLORS[sev.value]}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash
    parts.append(
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="20" '
        f'font-weight="bold" fill="#333">{total}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)

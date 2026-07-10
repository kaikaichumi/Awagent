"""使用者模板/規則資料夾攝取。

資料夾內容每次全量重讀（會變動）：
- *.rules.md / *.rules.txt / rules*.md → 寫作規則，注入 system prompt
- report.md.j2 / report.html.j2       → 覆蓋內建 Jinja2 模板
- 其他檔案                              → 只列檔名供 LLM 參考
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_RULE_PATTERNS = ("*.rules.md", "*.rules.txt", "rules*.md", "rules*.txt")
_MAX_RULES_CHARS = 24_000  # 超過就截斷並提示（粗略 token 保護）


@dataclass
class UserTemplates:
    rules_text: str = ""
    md_template: Path | None = None
    html_template: Path | None = None
    other_files: list[str] = field(default_factory=list)
    truncated: bool = False
    source_dir: str = ""


def load_user_templates(templates_dir: str | Path | None) -> UserTemplates:
    result = UserTemplates()
    if not templates_dir:
        return result
    root = Path(templates_dir)
    result.source_dir = str(root)
    if not root.is_dir():
        return result

    rule_files: list[Path] = []
    for pattern in _RULE_PATTERNS:
        rule_files.extend(root.glob(pattern))
    rule_files = sorted(set(rule_files))

    chunks: list[str] = []
    for path in rule_files:
        chunks.append(f"### 規則檔: {path.name}\n{path.read_text(encoding='utf-8', errors='replace')}")
    rules_text = "\n\n".join(chunks)
    if len(rules_text) > _MAX_RULES_CHARS:
        rules_text = rules_text[:_MAX_RULES_CHARS] + "\n\n[規則內容過長已截斷]"
        result.truncated = True
    result.rules_text = rules_text

    md = root / "report.md.j2"
    html = root / "report.html.j2"
    result.md_template = md if md.is_file() else None
    result.html_template = html if html.is_file() else None

    known = {p.name for p in rule_files} | {"report.md.j2", "report.html.j2"}
    result.other_files = sorted(
        p.name for p in root.iterdir() if p.is_file() and p.name not in known
    )
    return result

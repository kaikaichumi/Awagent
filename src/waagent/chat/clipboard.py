"""剪貼簿圖片支援（Windows）：/paste 把截圖存成暫存 PNG 供附件使用。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "Add-Type -AssemblyName System.Drawing; "
    "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
    "if ($img) { "
    "$p = Join-Path $env:TEMP ('waagent-paste-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.png'); "
    "$img.Save($p, [System.Drawing.Imaging.ImageFormat]::Png); Write-Output $p }"
)


def save_clipboard_image() -> str | None:
    """剪貼簿有圖片時存成暫存 PNG 並回傳路徑；否則 None。"""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _PS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    path = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else ""
    return path if path and Path(path).is_file() else None

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)


def list_screens() -> list[str]:
    if not shutil.which("screen"):
        return []
    try:
        r = subprocess.run(
            ["screen", "-ls"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception as e:
        log.debug("screen -ls failed: %s", e)
        return []


def list_systemd_units() -> list[str]:
    if not shutil.which("systemctl"):
        return []
    try:
        r = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        units = []
        for ln in (r.stdout or "").splitlines():
            parts = ln.split()
            if parts:
                units.append(parts[0])
        return units
    except Exception as e:
        log.debug("systemctl list-units failed: %s", e)
        return []


def process_cmdline_blob() -> str:
    """Concatenate process command lines (Linux /proc or Windows tasklist fallback)."""
    chunks: list[str] = []
    proc = __import__("pathlib").Path("/proc")
    if proc.exists():
        for p in proc.iterdir():
            if not p.name.isdigit():
                continue
            try:
                cmd = (p / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
                if cmd.strip():
                    chunks.append(cmd)
            except OSError:
                continue
        return "\n".join(chunks)
    # Windows: best-effort via wmic/powershell
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return r.stdout or ""
    except Exception:
        return ""

"""The machine: the clock, the last boot, files written whole. Each has an environment override so a test can set it."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path


def now() -> float:
    """Seconds since the epoch. `SENTINEL_NOW` fixes it (tests of the time-based moments)."""
    fixed = os.environ.get("SENTINEL_NOW")
    return float(fixed) if fixed else time.time()


def boot_time() -> float | None:
    """When this machine last started, or None when the platform does not say. `SENTINEL_BOOT_TIME` fixes it."""
    fixed = os.environ.get("SENTINEL_BOOT_TIME")
    if fixed:
        return float(fixed)
    try:
        if sys.platform == "win32":
            import ctypes

            tick = ctypes.windll.kernel32.GetTickCount64
            tick.restype = ctypes.c_uint64
            return time.time() - tick() / 1000.0
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"\bsec\s*=\s*(\d+)", out)
            return float(m.group(1)) if m else None
        with open("/proc/uptime", encoding="ascii") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None


def atomic_write(path: Path, text: str) -> None:
    """The whole file or the old one: written beside and moved over, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def append_line(path: Path, line: str) -> None:
    """One line added in one write, so two hooks of one session that run side by side do not mix their lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line.rstrip("\n") + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def native_path(p: str) -> str:
    """A path as this Python opens it: Git Bash on Windows writes `/c/Users/x` for `C:/Users/x`."""
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", p)
        if m:
            return f"{m.group(1).upper()}:{m.group(2) or '/'}"
    return p


def clock(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


def day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))

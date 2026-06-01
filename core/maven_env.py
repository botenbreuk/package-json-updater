"""Detect Java and Maven installation versions at runtime."""
from __future__ import annotations

import re
import subprocess


def _run(*cmd: str) -> str:
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=6)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def java_version() -> str:
    out = _run("java", "-version")
    m = re.search(r'"(\d+[^"]*)"', out)
    return m.group(1) if m else ""


def mvn_version() -> str:
    out = _run("mvn", "--version")
    m = re.search(r"Apache Maven (\S+)", out)
    return m.group(1) if m else ""

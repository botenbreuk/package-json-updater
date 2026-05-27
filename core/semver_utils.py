"""
npm-compatible version constraint parsing and bump categorisation.
No Qt dependency — pure Python.
"""
from __future__ import annotations

import re
from typing import Optional

from packaging.version import Version, InvalidVersion


# ── constraint parser ────────────────────────────────────────────────────────

_PART = r"(\d+|[xX*])"
_VERSION_RE = re.compile(
    rf"^(?P<prefix>[~^]|>=|<=|>|<|=)?\s*"
    rf"(?P<major>{_PART})"
    rf"(?:\.(?P<minor>{_PART}))?"
    rf"(?:\.(?P<patch>{_PART}))?"
    rf"(?P<rest>[^\s]*)?$"
)

_RANGE_RE = re.compile(r"^\s*(.+?)\s*\|\|\s*(.+)\s*$")   # a || b  → take first
_SPACE_RANGE_RE = re.compile(r"^\s*(\S+)\s+\S+\s*$")     # ">=1.2.3 <2" → take first


def parse_constraint(raw: str) -> dict:
    """
    Parse an npm version constraint string into a structured dict.

    Returns:
        {
          'type':    'any' | 'workspace' | 'local' | 'exact' | 'caret' | 'tilde' |
                     'gte' | 'lte' | 'gt' | 'lt' | 'eq',
          'prefix':  original prefix chars,
          'version': bare version string (str) or None,
          'major':   int or None,
          'minor':   int or None,
          'patch':   int or None,
        }
    """
    s = raw.strip()

    # Special values
    if s in ("*", "", "latest", "x"):
        return _any()

    if s.startswith("workspace:"):
        return {"type": "workspace", "prefix": "workspace:", "version": None,
                "major": None, "minor": None, "patch": None}

    if s.startswith("file:") or s.startswith("link:") or s.startswith("portal:"):
        return {"type": "local", "prefix": s.split(":")[0] + ":",
                "version": None, "major": None, "minor": None, "patch": None}

    # Handle "a || b" — take first alternative
    m_or = _RANGE_RE.match(s)
    if m_or:
        return parse_constraint(m_or.group(1))

    # Handle space-separated ranges like ">=1.2.3 <2.0.0" — take lower bound
    m_sp = _SPACE_RANGE_RE.match(s)
    if m_sp:
        return parse_constraint(m_sp.group(1))

    m = _VERSION_RE.match(s)
    if not m:
        return _any()

    prefix = m.group("prefix") or ""
    major_s = m.group("major") or "0"
    minor_s = m.group("minor") or "0"
    patch_s = m.group("patch") or "0"

    # Replace wildcards with 0
    major = _to_int(major_s)
    minor = _to_int(minor_s)
    patch = _to_int(patch_s)

    if major is None:
        return _any()

    version = f"{major}.{minor if minor is not None else 0}.{patch if patch is not None else 0}"

    type_map = {
        "^": "caret",
        "~": "tilde",
        ">=": "gte",
        "<=": "lte",
        ">": "gt",
        "<": "lt",
        "=": "eq",
        "": "exact",
    }
    kind = type_map.get(prefix, "exact")

    return {
        "type": kind,
        "prefix": prefix,
        "version": version,
        "major": major,
        "minor": minor,
        "patch": patch,
    }


def _any() -> dict:
    return {"type": "any", "prefix": "", "version": None,
            "major": None, "minor": None, "patch": None}


def _to_int(s: str) -> Optional[int]:
    if s in ("x", "X", "*", ""):
        return 0
    try:
        return int(s)
    except ValueError:
        return None


# ── stability check ──────────────────────────────────────────────────────────

_PRERELEASE_RE = re.compile(
    r"[-.]?(alpha|beta|rc|next|canary|dev|pre|experimental|nightly|snapshot|"
    r"milestone|milestone|cr|early|build|snap)",
    re.IGNORECASE,
)


def is_stable(version_str: str) -> bool:
    """Return True only for stable (non-prerelease) semver versions."""
    # Quick reject on obviously pre-release suffixes npm uses that packaging
    # doesn't understand (e.g. 1.0.0-next.0, 2.0.0-canary.1)
    if _PRERELEASE_RE.search(version_str):
        return False
    try:
        v = Version(version_str)
        return v.pre is None and v.dev is None and v.post is None or v.post is not None
    except InvalidVersion:
        return False


# ── bump categorisation ──────────────────────────────────────────────────────

def categorize_bump(current: str, candidate: str) -> Optional[str]:
    """
    Compare two bare version strings.
    Returns 'patch', 'minor', 'major', or None (not an upgrade / parse error).
    """
    try:
        cur = Version(current)
        cand = Version(candidate)
    except InvalidVersion:
        return None

    if cand <= cur:
        return None
    if cand.major > cur.major:
        return "major"
    if cand.minor > cur.minor:
        return "minor"
    if cand.micro > cur.micro:
        return "patch"
    return None


def max_version(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return the higher of two version strings (either may be None)."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        return b if Version(b) > Version(a) else a
    except InvalidVersion:
        return a


# ── write-back helper ────────────────────────────────────────────────────────

def apply_prefix(original_constraint: str, new_bare_version: str) -> str:
    """
    Preserve the leading constraint prefix when writing an updated version.
    e.g. '^18.2.0' + '18.3.0' → '^18.3.0'
         '~4.17.0' + '4.17.21' → '~4.17.21'
         '18.2.0'  + '18.3.0'  → '18.3.0'
    """
    m = re.match(r"^([~^]|>=|<=|>|<|=)?", original_constraint.strip())
    prefix = m.group(1) if m and m.group(1) else ""
    return prefix + new_bare_version

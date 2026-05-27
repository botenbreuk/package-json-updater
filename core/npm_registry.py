"""
npm registry HTTP client and version filtering.
No Qt dependency — pure Python.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import requests

from .semver_utils import is_stable, categorize_bump, max_version

REGISTRY = "https://registry.npmjs.org"
TIMEOUT = 15  # seconds


class NpmFetchError(Exception):
    pass


def fetch_package_data(name: str, min_age_days: int) -> dict:
    """
    Fetch the npm packument for *name* and return a dict:
        {
          'latest_patch': str | None,
          'latest_minor': str | None,
          'latest_major': str | None,
          'patch_age':    int | None,   # days since publication
          'minor_age':    int | None,
          'major_age':    int | None,
          'current_dist_tag': str | None,   # what npm considers 'latest'
        }

    ``min_age_days`` filters out versions published more recently than
    that many days ago (0 = no filter).
    """
    url = f"{REGISTRY}/{_encode(name)}"
    try:
        resp = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise NpmFetchError(str(exc)) from exc

    if resp.status_code == 404:
        raise NpmFetchError(f"Package '{name}' not found in registry.")
    if not resp.ok:
        raise NpmFetchError(f"Registry returned HTTP {resp.status_code} for '{name}'.")

    try:
        data = resp.json()
    except ValueError as exc:
        raise NpmFetchError(f"Invalid JSON from registry for '{name}'.") from exc

    time_map: dict[str, str] = data.get("time", {})
    all_versions: list[str] = list(data.get("versions", {}).keys())
    dist_tags: dict = data.get("dist-tags", {})
    npm_latest: Optional[str] = dist_tags.get("latest")

    # Determine the "current" version to compare against.
    # The caller doesn't pass current_version here; we return the candidates
    # and let the worker match them against each DependencyInfo.
    # Instead we return ALL stable/old-enough versions and the npm 'latest' tag.
    stable_versions = [v for v in all_versions if is_stable(v)]
    old_enough = [v for v in stable_versions if _is_old_enough(time_map, v, min_age_days)]

    # Build age lookup for fast access
    age_map: dict[str, Optional[int]] = {
        v: _age_days(time_map, v) for v in old_enough
    }

    return {
        "versions": old_enough,
        "age_map": age_map,
        "npm_latest": npm_latest,
        "repo_url": _extract_repo_url(data.get("repository")),
    }


def resolve_updates(
    current_version: str,
    registry_result: dict,
) -> dict:
    """
    Given the current bare version and the dict returned by fetch_package_data,
    find the best patch / minor / major upgrade that passed the age filter.

    Returns:
        {
          'latest_patch': str | None,
          'latest_minor': str | None,
          'latest_major': str | None,
          'patch_age':    int | None,
          'minor_age':    int | None,
          'major_age':    int | None,
        }
    """
    best: dict[str, Optional[str]] = {"patch": None, "minor": None, "major": None}
    age_map = registry_result.get("age_map", {})

    for v in registry_result.get("versions", []):
        bump = categorize_bump(current_version, v)
        if bump:
            best[bump] = max_version(best[bump], v)

    return {
        "latest_patch": best["patch"],
        "latest_minor": best["minor"],
        "latest_major": best["major"],
        "patch_age": age_map.get(best["patch"]) if best["patch"] else None,
        "minor_age": age_map.get(best["minor"]) if best["minor"] else None,
        "major_age": age_map.get(best["major"]) if best["major"] else None,
        "repo_url": registry_result.get("repo_url"),
    }


# ── internal helpers ─────────────────────────────────────────────────────────

def _encode(name: str) -> str:
    """URL-encode scoped package names, e.g. @scope/pkg → @scope%2Fpkg."""
    if name.startswith("@"):
        scope, _, pkg = name[1:].partition("/")
        return f"@{scope}%2F{pkg}"
    return name


def _is_old_enough(time_map: dict, version: str, min_age_days: int) -> bool:
    if min_age_days <= 0:
        return True
    ts = time_map.get(version)
    if not ts:
        return True  # unknown publish date — let it through
    days = _age_days(time_map, version)
    return days is None or days >= min_age_days


def _age_days(time_map: dict, version: str) -> Optional[int]:
    ts = time_map.get(version)
    if not ts:
        return None
    try:
        published = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - published).days
    except ValueError:
        return None


def _extract_repo_url(repo: "dict | str | None") -> Optional[str]:
    """
    Normalise npm's ``repository`` field to a browseable https:// URL.

    Handles the common forms:
      - ``{"type": "git", "url": "git+https://github.com/user/pkg.git"}``
      - ``"https://github.com/user/pkg"``
      - ``"github:user/pkg"`` or bare ``"user/pkg"`` (GitHub shorthand)
    """
    if not repo:
        return None
    raw: str = repo.get("url", "") if isinstance(repo, dict) else str(repo)
    if not raw:
        return None

    raw = re.sub(r"^git\+", "", raw)              # git+https:// → https://
    raw = re.sub(r"^git://", "https://", raw)    # git:// → https://
    raw = re.sub(r"^ssh://[^@]+@", "https://", raw)  # ssh://git@github.com/ → https://github.com/
    raw = re.sub(r"\.git$", "", raw.rstrip("/"))

    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # GitHub shorthands: "github:user/repo" or "user/repo"
    raw = re.sub(r"^github:", "", raw)
    if re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", raw):
        return f"https://github.com/{raw}"

    return None

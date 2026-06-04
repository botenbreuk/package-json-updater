"""
Read and write package.json files while preserving formatting.
No Qt dependency — pure Python.
"""
from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2
from typing import Optional

from models.dependency import DependencyInfo
from .semver_utils import parse_constraint, apply_prefix

GROUPS = ("dependencies", "devDependencies", "overrides")


def load(path: str) -> tuple[dict, list[DependencyInfo]]:
    """
    Read *path*, parse it, and return:
        (original_data_dict, list_of_DependencyInfo)

    Groups processed: dependencies, devDependencies, overrides.
    Non-npm entries (workspace:, file:, etc.) are skipped.
    """
    raw = Path(path).read_text(encoding="utf-8")
    data: dict = json.loads(raw)

    deps: list[DependencyInfo] = []

    for group in GROUPS:
        section: dict = data.get(group, {})
        if not isinstance(section, dict):
            continue

        for name, constraint in section.items():
            if isinstance(constraint, dict) and group == "overrides":
                # Nested override: {"parent-pkg": {"dep": "version"}}
                for nested_name, nested_constraint in constraint.items():
                    if not isinstance(nested_constraint, str):
                        continue
                    parsed = parse_constraint(nested_constraint)
                    if parsed["type"] in ("any", "workspace", "local"):
                        continue
                    bare = parsed.get("version") or ""
                    if not bare:
                        continue
                    deps.append(DependencyInfo(
                        name=nested_name,
                        group=group,
                        raw_constraint=nested_constraint,
                        current_version=bare,
                        override_parent=name,
                    ))
                continue

            if not isinstance(constraint, str):
                continue

            parsed = parse_constraint(constraint)
            if parsed["type"] in ("any", "workspace", "local"):
                continue  # skip non-registry references

            bare = parsed.get("version") or ""
            if not bare:
                continue

            deps.append(DependencyInfo(
                name=name,
                group=group,
                raw_constraint=constraint,
                current_version=bare,
            ))

    return data, deps


def save(
    path: str,
    original_data: dict,
    updates: list[tuple[DependencyInfo, str]],
) -> None:
    """
    Apply *updates* (list of (dep, new_bare_version)) to *original_data*
    and write back to *path*.

    The leading constraint prefix (^, ~, >=, …) from the original
    raw_constraint is preserved.
    """
    bak = path + ".bak"
    copy2(path, bak)   # backup before any changes

    data = _deep_copy(original_data)

    for dep, new_version in updates:
        group: Optional[dict] = data.get(dep.group)
        if group is None:
            continue
        new_constraint = apply_prefix(dep.raw_constraint, new_version)
        if dep.override_parent is not None:
            parent = group.get(dep.override_parent)
            if not isinstance(parent, dict) or dep.name not in parent:
                continue
            parent[dep.name] = new_constraint
        else:
            if dep.name not in group:
                continue
            group[dep.name] = new_constraint

    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        Path(path).write_text(text, encoding="utf-8")
    except Exception:
        raise   # backup remains so the original can be recovered
    else:
        Path(bak).unlink(missing_ok=True)   # write succeeded — clean up


# ── helpers ──────────────────────────────────────────────────────────────────

def _deep_copy(obj):
    """Minimal deep copy for JSON-compatible dicts/lists."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(i) for i in obj]
    return obj

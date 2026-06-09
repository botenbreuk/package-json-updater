from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DependencyInfo:
    name: str
    group: str            # 'dependencies' | 'devDependencies' | 'overrides'
    raw_constraint: str   # e.g. '^18.2.0'  (what package.json stores)
    current_version: str  # bare semver extracted, e.g. '18.2.0'

    # Set for nested overrides: data["overrides"][override_parent][name]
    override_parent: Optional[str] = None

    # Populated after npm fetch:
    latest_patch: Optional[str] = None
    latest_minor: Optional[str] = None
    latest_major: Optional[str] = None

    # Publish ages (days) for each update:
    patch_age: Optional[int] = None
    minor_age: Optional[int] = None
    major_age: Optional[int] = None

    # Days since current installed version was published (None = unknown):
    current_age: Optional[int] = None

    # Repository link (populated after fetch):
    repo_url: Optional[str] = None

    # Transient UI state:
    fetch_status: str = "pending"   # 'pending' | 'loading' | 'done' | 'error'
    error_message: str = ""
    needs_install: bool = False

    # Version the user clicked (not yet written to disk):
    pending_version: Optional[str] = None

    @property
    def row_key(self) -> tuple:
        return (self.name, self.group, self.override_parent)

    @property
    def group_label(self) -> str:
        labels = {
            "dependencies": "dep",
            "devDependencies": "devDep",
            "overrides": "override",
        }
        return labels.get(self.group, self.group)

    @property
    def has_any_update(self) -> bool:
        return any(v is not None for v in [self.latest_patch, self.latest_minor, self.latest_major])

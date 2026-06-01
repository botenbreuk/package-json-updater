from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class MavenDependencyInfo:
    group_id: str
    artifact_id: str
    version: Optional[str]           # None = managed by parent/BOM
    version_property: Optional[str]  # e.g. "guava.version" when from ${guava.version}
    scope: str = "compile"
    optional: bool = False

    # Populated after fetch:
    latest_version: Optional[str] = None

    # Transient UI state:
    fetch_status: str = "pending"    # 'pending' | 'loading' | 'done' | 'error'
    error_message: str = ""
    needs_install: bool = False

    @property
    def coordinate(self) -> str:
        return f"{self.group_id}:{self.artifact_id}"

    @property
    def is_managed(self) -> bool:
        return self.version is None

    @property
    def has_update(self) -> bool:
        if self.version is None or self.latest_version is None:
            return False
        return self.latest_version != self.version

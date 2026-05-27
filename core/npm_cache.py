"""
Disk-backed cache for npm registry results.

Each entry is keyed by ``"<name>@<current_version>"`` so that an externally
edited constraint (e.g. bumping ^1.4.0 → ^2.0.0 by hand) is always a cache
miss — the resolved patch/minor/major columns are relative to the current
version baseline, so a stale entry for the old version would be wrong.

The caller controls the TTL; passing ttl_hours=0 disables the cache.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _cache_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "package-json-updater" / "npm_cache.json"


class NpmCache:
    """
    In-process write-through cache backed by a single JSON file.

    Thread-safety: only one FetchWorker runs at a time; the main thread
    calls ``invalidate`` only when no fetch is in flight, so no locking is
    needed.
    """

    def __init__(self) -> None:
        self._path = _cache_path()
        self._data: dict[str, dict] = {}
        self._dirty = False
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, name: str, current_version: str, ttl_hours: int) -> Optional[dict]:
        """
        Return the cached update dict for *name* at *current_version* if it
        was fetched within *ttl_hours*.  Returns ``None`` on a miss or when
        *ttl_hours* is 0 (cache disabled).
        """
        if ttl_hours <= 0:
            return None
        entry = self._data.get(self._key(name, current_version))
        if not entry:
            return None
        try:
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            if age_s > ttl_hours * 3600:
                return None
        except Exception:
            return None
        return entry.get("versions")

    def set(self, name: str, current_version: str, versions: dict) -> None:
        """Store *versions* for *name*@*current_version* with the current UTC timestamp."""
        self._data[self._key(name, current_version)] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "versions": versions,
        }
        self._dirty = True

    def invalidate(self, name: str, current_version: str) -> None:
        """Remove the cache entry for *name*@*current_version*."""
        key = self._key(name, current_version)
        if key in self._data:
            del self._data[key]
            self._dirty = True

    def flush(self) -> None:
        """Write pending changes to disk (no-op if nothing changed)."""
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            self._dirty = False
        except OSError:
            pass  # non-fatal: next run re-fetches from npm

    def clear(self) -> None:
        """Wipe the entire cache from memory and disk."""
        self._data = {}
        self._dirty = True
        self.flush()

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _key(name: str, current_version: str) -> str:
        return f"{name}@{current_version}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except Exception:
            self._data = {}

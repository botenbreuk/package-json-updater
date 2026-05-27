"""
Utility for building a subprocess environment that can find node / npm.

macOS GUI apps start with a minimal PATH that often omits Homebrew and nvm
bin dirs, so ``node`` / ``npm`` can't be found via their bare command names.
This module resolves the most common install locations at runtime.
"""
from __future__ import annotations

import os


def _nvm_bin_dirs() -> list[str]:
    """Return nvm node bin dirs to add to PATH, most-specific first.

    nvm stores its default version as a text alias file at
    ``~/.nvm/alias/default``.  We read that file, normalise the version
    string (e.g. ``24.11.1`` → ``v24.11.1``), then return the matching
    ``~/.nvm/versions/node/<ver>/bin`` directory if it exists.

    We also walk ``~/.nvm/alias/`` to resolve chains like
    ``default → lts/iron → 20.19.0`` up to a few hops deep.
    """
    nvm_dir = os.path.expanduser("~/.nvm")
    if not os.path.isdir(nvm_dir):
        return []

    alias_dir = os.path.join(nvm_dir, "alias")
    versions_dir = os.path.join(nvm_dir, "versions", "node")

    def _read_alias(name: str, depth: int = 0) -> str | None:
        """Resolve an alias name to a concrete version string."""
        if depth > 4:
            return None
        path = os.path.join(alias_dir, name)
        if not os.path.isfile(path):
            return None
        try:
            value = open(path).read().strip()
        except OSError:
            return None
        if not value:
            return None
        # If the value looks like a version number, return it
        if value.lstrip("v")[0].isdigit():
            return value
        # Otherwise it's another alias (e.g. "lts/iron") — recurse
        return _read_alias(value, depth + 1)

    dirs: list[str] = []
    for alias in ("default", "lts/iron", "lts/hydrogen", "lts/gallium", "lts/fermium"):
        ver = _read_alias(alias)
        if not ver:
            continue
        if not ver.startswith("v"):
            ver = "v" + ver
        candidate = os.path.join(versions_dir, ver, "bin")
        if os.path.isdir(candidate) and candidate not in dirs:
            dirs.append(candidate)

    return dirs


def node_path_env() -> dict:
    """Return ``os.environ`` with common node/npm install dirs prepended to PATH."""
    env = os.environ.copy()

    extras: list[str] = [
        "/usr/local/bin",     # Homebrew on Intel Macs / classic installs
        "/opt/homebrew/bin",  # Homebrew on Apple Silicon
        "/opt/homebrew/sbin",
        *_nvm_bin_dirs(),     # nvm-managed versions
    ]

    current = env.get("PATH", "")
    current_parts = set(current.split(":"))
    new_parts = [p for p in extras if p not in current_parts]
    env["PATH"] = ":".join(new_parts) + (":" if new_parts else "") + current
    return env

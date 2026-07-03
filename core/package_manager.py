"""
Package-manager abstraction and detection.

Pure Python — no Qt, no settings, no side effects beyond reading the
``package.json`` / lockfiles inside a project directory.  Given a project
directory this resolves which package manager (npm / yarn / pnpm / bun) a
project uses and builds the correct argv for every command-line operation
the app performs.

Resolution precedence (see ``detect``):

    1. an explicit per-directory override               (always wins)
    2. the ``packageManager`` field in package.json      (corepack)
    3. a single lockfile found at or above the project   (the common case)
    4. multiple lockfiles                                → ambiguous, ask
    5. nothing found                                     → the global default
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class _Spec:
    """Static metadata for one package manager."""
    id: str                     # stable key: "npm" | "yarn" | "pnpm" | "bun"
    display: str                # human label shown in the UI
    binary: str                 # executable name to spawn / resolve on PATH
    lockfiles: tuple[str, ...]  # lockfile names that identify this manager


class PackageManager(Enum):
    """The supported package managers and how to drive each one.

    Members are declared npm-first; iteration and lockfile scanning follow
    this order so candidate lists are deterministic.
    """

    NPM  = _Spec("npm",  "npm",  "npm",  ("package-lock.json", "npm-shrinkwrap.json"))
    YARN = _Spec("yarn", "Yarn", "yarn", ("yarn.lock",))
    PNPM = _Spec("pnpm", "pnpm", "pnpm", ("pnpm-lock.yaml",))
    # bun.lock is the text lockfile (Bun >= 1.2); bun.lockb is the older binary one.
    BUN  = _Spec("bun",  "Bun",  "bun",  ("bun.lock", "bun.lockb"))

    # ── metadata passthrough ─────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self.value.id

    @property
    def display(self) -> str:
        return self.value.display

    @property
    def binary(self) -> str:
        return self.value.binary

    @property
    def lockfiles(self) -> tuple[str, ...]:
        return self.value.lockfiles

    # ── lookup ───────────────────────────────────────────────────────────

    @classmethod
    def from_id(cls, value: "str | PackageManager | None") -> Optional["PackageManager"]:
        """Resolve a manager from its id (case-insensitive) or pass one through.

        Returns ``None`` for unknown / empty values so callers can fall back.
        """
        if isinstance(value, PackageManager):
            return value
        if not value:
            return None
        wanted = value.strip().lower()
        for pm in cls:
            if pm.value.id == wanted:
                return pm
        return None

    # ── command builders (see the command matrix in the plan) ────────────

    def install_cmd(self) -> list[str]:
        """Install everything declared in package.json."""
        return [self.binary, "install"]

    def clean_install_cmd(self) -> list[str]:
        """Reproducible, lockfile-faithful install (CI style)."""
        if self is PackageManager.NPM:
            return [self.binary, "ci"]
        if self is PackageManager.YARN:
            return [self.binary, "install", "--immutable"]
        # pnpm and bun share the same flag
        return [self.binary, "install", "--frozen-lockfile"]

    def version_cmd(self) -> list[str]:
        """Print the manager's own version."""
        return [self.binary, "--version"]

    def add_cmd(self, package: str, version: str | None = None) -> list[str]:
        """Add a single package (optionally pinned to *version*)."""
        spec = f"{package}@{version}" if version else package
        verb = "install" if self is PackageManager.NPM else "add"
        return [self.binary, verb, spec]


DEFAULT_MANAGER = PackageManager.NPM


class DetectionSource(str, Enum):
    """Which rule in the precedence chain decided the result."""
    OVERRIDE = "override"
    PACKAGE_JSON_FIELD = "package-json-field"
    LOCKFILE = "lockfile"
    AMBIGUOUS = "ambiguous"
    DEFAULT = "default"


@dataclass(frozen=True)
class Detection:
    """Outcome of :func:`detect`.

    ``manager`` is the resolved manager, or ``None`` only when ``source`` is
    :attr:`DetectionSource.AMBIGUOUS` — in which case ``candidates`` holds the
    managers whose lockfiles were found so the UI can prompt the user.
    """
    manager: Optional[PackageManager]
    source: DetectionSource
    candidates: tuple[PackageManager, ...] = ()
    lockfile_dir: Optional[str] = None

    @property
    def is_ambiguous(self) -> bool:
        return self.source is DetectionSource.AMBIGUOUS


def detect(
    project_dir: str,
    *,
    override: "str | PackageManager | None" = None,
    default: "str | PackageManager" = DEFAULT_MANAGER,
) -> Detection:
    """Resolve the package manager for *project_dir*.

    ``override`` is a per-directory pin (manager id or instance); ``default``
    is the global fallback used when nothing else applies.  See the module
    docstring for the full precedence.
    """
    # 1. explicit override always wins — no file access needed.
    pinned = PackageManager.from_id(override)
    if pinned is not None:
        return Detection(pinned, DetectionSource.OVERRIDE)

    fallback = PackageManager.from_id(default) or DEFAULT_MANAGER

    if not project_dir:
        return Detection(fallback, DetectionSource.DEFAULT)

    # 2. the corepack "packageManager" field in this project's package.json.
    declared = _manager_from_package_json(project_dir)
    if declared is not None:
        return Detection(declared, DetectionSource.PACKAGE_JSON_FIELD)

    # 3/4. nearest lockfile(s), walking up for monorepos.
    found_dir, managers = _scan_lockfiles(project_dir)
    if managers:
        if len(managers) == 1:
            return Detection(managers[0], DetectionSource.LOCKFILE,
                             tuple(managers), found_dir)
        return Detection(None, DetectionSource.AMBIGUOUS,
                         tuple(managers), found_dir)

    # 5. nothing to go on — use the global default.
    return Detection(fallback, DetectionSource.DEFAULT)


# ── helpers ──────────────────────────────────────────────────────────────

def _manager_from_package_json(project_dir: str) -> Optional[PackageManager]:
    """Read the ``packageManager`` field from ``<project_dir>/package.json``.

    Handles corepack's ``"<name>@<version>"`` (and ``...+sha`` hashed) form.
    Returns ``None`` when the file is missing, unreadable, malformed, or names
    a manager we don't support.
    """
    path = os.path.join(project_dir, "package.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    field = data.get("packageManager")
    if not isinstance(field, str):
        return None
    name = field.split("@", 1)[0].strip().lower()
    return PackageManager.from_id(name)


def _scan_lockfiles(start_dir: str) -> tuple[Optional[str], list[PackageManager]]:
    """Walk up from *start_dir* to the nearest ancestor that has any lockfile.

    Returns ``(directory, managers)`` where *managers* are the distinct
    managers whose lockfiles live in that directory (in enum order), or
    ``(None, [])`` if none is found up to the filesystem root.
    """
    current = os.path.abspath(start_dir)
    while True:
        managers = _managers_in_dir(current)
        if managers:
            return current, managers
        parent = os.path.dirname(current)
        if parent == current:          # reached the filesystem root
            return None, []
        current = parent


def _managers_in_dir(directory: str) -> list[PackageManager]:
    """Managers whose lockfile is present directly in *directory* (enum order)."""
    found: list[PackageManager] = []
    for pm in PackageManager:
        if any(os.path.exists(os.path.join(directory, lf)) for lf in pm.lockfiles):
            found.append(pm)
    return found
